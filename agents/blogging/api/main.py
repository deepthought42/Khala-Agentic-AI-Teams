"""
FastAPI application exposing the research-and-review and full pipeline as HTTP endpoints.
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional, Union

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from blog_research_agent.agent import ResearchAgent
from blog_research_agent.agent_cache import AgentCache
from blog_research_agent.llm import OllamaLLMClient
from blog_research_agent.models import ResearchBriefInput
from blog_review_agent import BlogReviewAgent, BlogReviewInput

try:
    from shared.artifacts import write_artifact
except ImportError:
    write_artifact = None

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

import os

_TAVILY_KEY_PRESENT = bool(os.environ.get("TAVILY_API_KEY"))
if not _TAVILY_KEY_PRESENT:
    logger.warning(
        "TAVILY_API_KEY is not set. The research agent requires this key for "
        "web search. Set it before calling /research-and-review or /full-pipeline."
    )

# Base directory for run artifacts (when work_dir is requested)
RUN_ARTIFACTS_BASE = Path(tempfile.gettempdir()) / "blogging_runs"

app = FastAPI(
    title="Blog Research & Review API",
    description="Runs research and review agents. Optional full pipeline with gates and artifact persistence.",
    version="0.2.0",
)


class AudienceDetails(BaseModel):
    """Audience details for targeting the content."""

    skill_level: Optional[str] = Field(
        None,
        description="e.g. 'beginner', 'intermediate', 'expert'.",
    )
    profession: Optional[str] = Field(
        None,
        description="e.g. 'CTO', 'developer', 'data scientist'.",
    )
    hobbies: Optional[List[str]] = Field(
        None,
        description="Relevant hobbies or interests.",
    )
    other: Optional[str] = Field(
        None,
        description="Any other audience context.",
    )


class ResearchAndReviewRequest(BaseModel):
    """Request body for the research-and-review endpoint."""

    brief: str = Field(..., max_length=50_000, description="Short description of the content topic.")
    title_concept: Optional[str] = Field(
        None,
        description="Optional idea or angle for the title.",
    )
    audience: Optional[Union[AudienceDetails, str]] = Field(
        None,
        description="Audience details (object or free-text string).",
    )
    tone_or_purpose: Optional[str] = Field(
        None,
        description="e.g. 'educational', 'technical deep-dive', 'persuasive'.",
    )
    max_results: int = Field(
        20,
        ge=1,
        le=50,
        description="Maximum number of references to return.",
    )


class TitleChoiceResponse(BaseModel):
    """A title choice with probability of success."""

    title: str
    probability_of_success: float


class ResearchAndReviewResponse(BaseModel):
    """Response from the research-and-review endpoint."""

    title_choices: List[TitleChoiceResponse] = Field(
        ...,
        description="Top title choices with probability of success.",
    )
    outline: str = Field(
        ...,
        description="Detailed blog outline with notes for the first draft.",
    )
    compiled_document: Optional[str] = Field(
        None,
        description="Formatted research document (sources, academic papers, similar topics).",
    )
    notes: Optional[str] = Field(
        None,
        description="High-level synthesis and suggestions from the research agent.",
    )


def _format_audience(audience: Optional[Union[AudienceDetails, str]]) -> str:
    """Convert audience input to a string for the agents."""
    if audience is None:
        return ""
    if isinstance(audience, str):
        return audience.strip()
    parts = []
    if audience.skill_level:
        parts.append(f"skill level: {audience.skill_level}")
    if audience.profession:
        parts.append(f"profession: {audience.profession}")
    if audience.hobbies:
        parts.append(f"interests: {', '.join(audience.hobbies)}")
    if audience.other:
        parts.append(audience.other)
    return "; ".join(parts) if parts else ""


# Shared LLM client and agents (initialized on first request or at startup)
_llm_client: Optional[OllamaLLMClient] = None
_research_agent: Optional[ResearchAgent] = None
_review_agent: Optional[BlogReviewAgent] = None


def _get_agents() -> tuple[ResearchAgent, BlogReviewAgent]:
    """Lazily initialize and return research and review agents."""
    global _llm_client, _research_agent, _review_agent
    if _llm_client is None:
        _llm_client = OllamaLLMClient(model="deepseek-r1", timeout=1800.0)
    if _research_agent is None:
        cache = AgentCache(cache_dir=".agent_cache")
        _research_agent = ResearchAgent(llm_client=_llm_client, cache=cache)
    if _review_agent is None:
        _review_agent = BlogReviewAgent(llm_client=_llm_client)
    return _research_agent, _review_agent


@app.post(
    "/research-and-review",
    response_model=ResearchAndReviewResponse,
    summary="Run research and review pipeline",
    description="Executes the research agent (web + arXiv search) and review agent to produce title choices and a blog outline from the given brief and audience details.",
)
def research_and_review(request: ResearchAndReviewRequest) -> ResearchAndReviewResponse:
    """
    Run the research-and-review pipeline.

    Accepts a brief, optional title concept, and audience details. Returns
    title choices, a blog outline, and the compiled research document.
    """
    try:
        research_agent, review_agent = _get_agents()
    except Exception as e:
        logger.exception("Failed to initialize agents")
        raise HTTPException(status_code=500, detail=f"Agent initialization failed: {e}") from e

    llm_requests_before = _llm_client.request_count if _llm_client is not None else 0

    # Build brief text (include title concept if provided)
    brief_text = request.brief.strip()
    if request.title_concept:
        brief_text = f"{brief_text}. Title concept: {request.title_concept.strip()}"

    audience_str = _format_audience(request.audience)

    work_dir = None
    if request.work_dir:
        work_dir = Path(request.work_dir)
    elif request.run_id:
        work_dir = RUN_ARTIFACTS_BASE / request.run_id
        work_dir.mkdir(parents=True, exist_ok=True)

    brief_input = ResearchBriefInput(
        brief=brief_text,
        audience=audience_str or None,
        tone_or_purpose=request.tone_or_purpose,
        max_results=request.max_results,
    )

    try:
        research_result = research_agent.run(brief_input)
    except Exception as e:
        logger.exception("Research agent failed")
        raise HTTPException(status_code=500, detail=f"Research failed: {e}") from e

    try:
        review_input = BlogReviewInput(
            brief=request.brief,
            audience=audience_str or None,
            tone_or_purpose=request.tone_or_purpose,
            references=research_result.references,
        )
        review_result = review_agent.run(review_input)
    except Exception as e:
        logger.exception("Review agent failed")
        raise HTTPException(status_code=500, detail=f"Review failed: {e}") from e

    if work_dir is not None and write_artifact is not None:
        research_doc = research_result.compiled_document or ""
        if not research_doc and research_result.references:
            parts = ["## Sources\n"]
            for ref in research_result.references:
                parts.append(f"- **{ref.title}** ({ref.url}): {ref.summary}")
            research_doc = "\n".join(parts)
        write_artifact(work_dir, "research_packet.md", research_doc)
        write_artifact(work_dir, "outline.md", review_result.outline)
        logger.info("Persisted artifacts to %s", work_dir)

    llm_requests_after = _llm_client.request_count if _llm_client is not None else llm_requests_before
    logger.info(
        "Completed research-and-review pipeline with %s LLM requests",
        llm_requests_after - llm_requests_before,
    )

    return ResearchAndReviewResponse(
        title_choices=[
            TitleChoiceResponse(
                title=tc.title,
                probability_of_success=tc.probability_of_success,
            )
            for tc in review_result.title_choices
        ],
        outline=review_result.outline,
        compiled_document=research_result.compiled_document,
        notes=research_result.notes,
    )


class FullPipelineRequest(BaseModel):
    """Request body for the full pipeline endpoint."""

    brief: str = Field(..., max_length=50_000, description="Short description of the content topic.")
    title_concept: Optional[str] = Field(None, description="Optional idea or angle for the title.")
    audience: Optional[Union[AudienceDetails, str]] = Field(None, description="Audience details.")
    tone_or_purpose: Optional[str] = Field(None, description="e.g. 'educational', 'technical deep-dive'.")
    max_results: int = Field(20, ge=1, le=50, description="Maximum references.")
    run_gates: bool = Field(True, description="Run validators, fact-check, and compliance gates.")
    max_rewrite_iterations: int = Field(3, ge=1, le=10, description="Max rewrite iterations on FAIL.")


class FullPipelineResponse(BaseModel):
    """Response from the full pipeline endpoint."""

    status: str = Field(..., description="PASS, FAIL, or NEEDS_HUMAN_REVIEW.")
    work_dir: str = Field(..., description="Path to artifact directory.")
    title_choices: List[TitleChoiceResponse] = Field(default_factory=list)
    outline: str = ""
    draft_preview: Optional[str] = Field(None, description="First 2000 chars of draft.")


@app.post(
    "/full-pipeline",
    response_model=FullPipelineResponse,
    summary="Run full blog pipeline with gates",
    description="Runs research -> review -> draft -> validators -> compliance -> rewrite loop. Persists all artifacts.",
)
def full_pipeline(request: FullPipelineRequest) -> FullPipelineResponse:
    """Run the full brand-aligned pipeline with artifact persistence and gates."""
    import sys
    from pathlib import Path
    _blogging_root = Path(__file__).resolve().parent.parent
    if str(_blogging_root) not in sys.path:
        sys.path.insert(0, str(_blogging_root))
    from agent_implementations.blog_writing_process_v2 import run_pipeline

    run_id = str(uuid.uuid4())[:8]
    work_dir = RUN_ARTIFACTS_BASE / run_id
    work_dir.mkdir(parents=True, exist_ok=True)

    brief_text = request.brief.strip()
    if request.title_concept:
        brief_text = f"{brief_text}. Title concept: {request.title_concept.strip()}"
    audience_str = _format_audience(request.audience)

    brief_input = ResearchBriefInput(
        brief=brief_text,
        audience=audience_str or None,
        tone_or_purpose=request.tone_or_purpose,
        max_results=request.max_results,
    )

    try:
        research_result, review_result, draft_result, status = run_pipeline(
            brief_input,
            work_dir=work_dir,
            run_gates=request.run_gates,
            max_rewrite_iterations=request.max_rewrite_iterations,
        )
    except Exception as e:
        logger.exception("Full pipeline failed")
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}") from e

    return FullPipelineResponse(
        status=status,
        work_dir=str(work_dir),
        title_choices=[
            TitleChoiceResponse(title=tc.title, probability_of_success=tc.probability_of_success)
            for tc in review_result.title_choices
        ],
        outline=review_result.outline,
        draft_preview=draft_result.draft[:2000] + ("..." if len(draft_result.draft) > 2000 else ""),
    )


@app.get("/health")
def health() -> dict:
    """Health check endpoint. Includes a warning when TAVILY_API_KEY is missing."""
    warnings = []
    if not _TAVILY_KEY_PRESENT:
        warnings.append("TAVILY_API_KEY is not set; research agent will fail")
    result: dict = {"status": "ok"}
    if warnings:
        result["warnings"] = warnings
    return result
