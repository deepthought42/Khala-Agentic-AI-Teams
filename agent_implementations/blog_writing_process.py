"""
Example: run research agent, then blog review agent, then blog draft agent.

The blog review agent takes the brief + researched sources and produces:
1. Top 10 catchy title choices with probability of success.
2. A detailed blog outline with notes for the first draft.

The blog draft agent takes the research document + outline and produces
a full blog post draft compliant with the brand and writing style guide.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from blog_research_agent.agent import ResearchAgent
from blog_research_agent.agent_cache import AgentCache
from blog_research_agent.models import ResearchBriefInput
from blog_research_agent.llm import OllamaLLMClient
from blog_review_agent import BlogReviewAgent, BlogReviewInput
from blog_draft_agent import BlogDraftAgent, DraftInput

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

STYLE_GUIDE_PATH = Path(__file__).resolve().parent.parent / "docs" / "brandon_kindred_brand_and_writing_style_guide.md"

llm_client = OllamaLLMClient(
    model="deepseek-r1",
    timeout=1800.0,
)

# 1. Research
cache = AgentCache(cache_dir=".agent_cache")
research_agent = ResearchAgent(llm_client=llm_client, cache=cache)
brief = ResearchBriefInput(
    brief="LLM observability best practices for large enterprises",
    audience="CTOs and platform teams",
    tone_or_purpose="technical deep-dive",
    max_results=20,
)
research_result = research_agent.run(brief)
logger.info("RESEARCH RESULT DOCUMENT: \n ---------------------------------------- \n %s", research_result)

# 2. Blog review (titles + outline from brief + sources)
review_agent = BlogReviewAgent(llm_client=llm_client)
review_input = BlogReviewInput(
    brief=brief.brief,
    audience=brief.audience,
    tone_or_purpose=brief.tone_or_purpose,
    references=research_result.references,
)
review_result = review_agent.run(review_input)
logger.info("OUTLINE DOCUMENT: \n ---------------------------------------- \n %s", review_result)

# 3. Blog draft (research document + outline -> full draft)
research_document = research_result.compiled_document or ""
if not research_document and research_result.references:
    # Fallback: build minimal research doc from references
    parts = ["## Sources\n"]
    for ref in research_result.references:
        parts.append(f"- **{ref.title}** ({ref.url}): {ref.summary}")
        if ref.key_points:
            parts.append("  Key points: " + "; ".join(ref.key_points[:3]))
    research_document = "\n".join(parts)

draft_agent = BlogDraftAgent(llm_client=llm_client, default_style_guide_path=STYLE_GUIDE_PATH)
draft_input = DraftInput(
    research_document=research_document,
    outline=review_result.outline,
    audience=brief.audience,
    tone_or_purpose=brief.tone_or_purpose,
)
draft_result = draft_agent.run(draft_input)
logger.info("DRAFT DOCUMENT: \n ---------------------------------------- \n %s", draft_result.draft[:2000] + ("..." if len(draft_result.draft) > 2000 else ""))

# 4. Output
print("\n--- Top 10 title choices (with probability of success) ---")
for i, tc in enumerate(review_result.title_choices, 1):
    print(f"{i}. {tc.title}  [{tc.probability_of_success:.0%}]")
print("\n--- Blog outline ---\n")
print(review_result.outline)
print("\n--- Blog draft ---\n")
print(draft_result.draft)
