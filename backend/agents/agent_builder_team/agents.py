"""
Specialist agents for the Agent Builder Team.

Each agent wraps a focused LLM call and returns a structured model.
"""

from __future__ import annotations

import json
import logging
import textwrap
from dataclasses import dataclass, field
from typing import List

from llm_service.factory import get_client
from llm_service.interface import LLMClient

from .models import (
    AgentPlan,
    AgentSpec,
    FlowchartEdge,
    FlowchartNode,
    GeneratedFile,
    ProcessFlowchart,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

_PROCESS_ANALYST_SYSTEM = """\
You are a senior business process analyst who specialises in converting informal process
descriptions into precise, unambiguous flowcharts.

Your rules:
- Every path through the flowchart MUST terminate at an "end" node.
- Every decision node MUST have outgoing edges for EVERY branch (e.g. both Yes and No).
- Use the smallest number of nodes that fully capture the process.
- Raise clarifying questions for any ambiguous steps.

Return ONLY valid JSON matching this schema exactly (no markdown, no extra keys):
{
  "nodes": [
    {"id": "start", "label": "Start", "node_type": "start"},
    {"id": "n1",    "label": "Step name", "node_type": "process"},
    {"id": "d1",    "label": "Condition?", "node_type": "decision"},
    {"id": "end",   "label": "End", "node_type": "end"}
  ],
  "edges": [
    {"from_node": "start", "to_node": "n1", "label": ""},
    {"from_node": "d1",    "to_node": "n2", "label": "Yes"},
    {"from_node": "d1",    "to_node": "end","label": "No"}
  ],
  "mermaid": "flowchart TD\\n  start([Start]) --> n1[Step 1]\\n  ...",
  "clarifying_questions": ["What happens when X fails?"],
  "validation_notes": ["All paths terminate at End node"],
  "is_complete": true
}
"""

_FLOWCHART_VALIDATOR_SYSTEM = """\
You are a process validation expert. Given a flowchart (nodes, edges, mermaid source) verify:
1. There is exactly one start node.
2. At least one end node exists.
3. Every decision node has at least two outgoing edges.
4. There are no dead-end nodes (every non-end node has at least one outgoing edge).
5. There are no unreachable nodes (every non-start node has at least one incoming edge).

Return ONLY valid JSON:
{
  "is_complete": true,
  "issues": [],
  "suggestions": ["optional improvements"],
  "validation_notes": ["summary"]
}
"""

_AGENT_PLANNER_SYSTEM = """\
You are an AI agent architect designing a multi-agent Python team for the Strands Agents platform.

Given a process flowchart, design specialist agents that together implement the entire process.
Guidelines:
- One agent per distinct responsibility (no agent covers unrelated steps).
- Always include an OrchestratorAgent that coordinates the specialists.
- Name agents in PascalCase ending with "Agent" (e.g. "ValidationAgent").
- team_name must be snake_case, e.g. "invoice_approval_team".
- List phases in execution order.
- human_checkpoints: name phases where human review is required.

Return ONLY valid JSON:
{
  "team_name": "my_process_team",
  "pipeline_description": "One paragraph describing the pipeline.",
  "phases": ["Phase 1: Intake", "Phase 2: Validation", "Phase 3: Delivery"],
  "human_checkpoints": ["Phase 2: Validation"],
  "agents": [
    {
      "name": "IntakeAgent",
      "role": "Intake Specialist",
      "inputs": ["raw_request"],
      "outputs": ["structured_intake"],
      "description": "Parses and normalises incoming requests.",
      "flowchart_nodes": ["n1", "n2"]
    }
  ]
}
"""

_PLAN_REVIEWER_SYSTEM = """\
You are a senior AI systems architect reviewing a proposed agent team plan.
Evaluate:
1. Coverage — does every flowchart step have a responsible agent?
2. Separation of concerns — are agent roles non-overlapping and clear?
3. Feasibility — can each agent be implemented with a single LLM prompt?
4. Handoffs — is data flow between agents clearly defined?
5. Checkpoints — are human review points appropriate?

Return ONLY valid JSON:
{
  "approved": true,
  "issues": [],
  "suggestions": ["optional improvements"],
  "review_notes": "Overall assessment paragraph."
}
"""

_AGENT_BUILDER_SYSTEM = """\
You are an expert Python developer who writes production-quality Strands Agents teams.

Conventions to follow EXACTLY:
- Python 3.10+, from __future__ import annotations in every file.
- Pydantic v2 BaseModel for all request/response data models.
- @dataclass for agent implementations; __init__ accepts an LLMClient.
- LLM client import: from llm_service.factory import get_client
- LLMClient type hint import: from llm_service.interface import LLMClient
- llm.complete_json(prompt, system_prompt=...) for structured responses.
- llm.complete(prompt, system_prompt=...) for free-text responses.
- FastAPI app in api/main.py with @app.get("/health") returning {"status": "ok"}.
- Line length 120; ruff-compatible.
- Do NOT include test files.

Generate the following files for the team:
  __init__.py
  models.py
  agents.py
  orchestrator.py
  api/__init__.py
  api/main.py

Return ONLY valid JSON:
{
  "files": [
    {
      "filename": "__init__.py",
      "content": "...",
      "description": "Public exports"
    }
  ],
  "delivery_notes": "Brief summary of what was built and how to run it."
}
"""

_REFINER_SYSTEM = """\
You are a senior Python code reviewer. Review a set of generated agent team files for:
1. Import errors or missing imports.
2. Pydantic v2 compatibility (use model_dump(), not .dict()).
3. Type annotation correctness.
4. Missing FastAPI routes or health endpoint.
5. Any obvious logic bugs.

Apply minimal, surgical fixes. Do not refactor or add features.

Return ONLY valid JSON with the corrected files:
{
  "files": [
    {"filename": "models.py", "content": "...", "description": "Corrected models"}
  ],
  "refinement_notes": "Summary of changes made."
}
"""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _safe_parse(raw: str, context: str) -> dict:
    """Parse JSON from an LLM response, stripping markdown fences if present."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop opening fence line and closing fence
        inner = lines[1:] if lines[0].startswith("```") else lines
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("JSON parse error in %s: %s\nRaw:\n%s", context, exc, raw[:500])
        return {}


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


@dataclass
class ProcessAnalystAgent:
    """Converts a free-text process description into a structured flowchart."""

    role: str = "Senior Process Analyst"
    llm: LLMClient = field(default_factory=lambda: get_client("agent_builder_process_analyst"))

    def analyze(self, process_description: str) -> ProcessFlowchart:
        prompt = (
            "Convert the following process description into a complete, fully-terminated flowchart.\n\n"
            f"Process description:\n{process_description}"
        )
        raw = self.llm.complete(prompt, system_prompt=_PROCESS_ANALYST_SYSTEM)
        data = _safe_parse(raw, "ProcessAnalystAgent")
        if not data:
            return ProcessFlowchart(
                is_complete=False,
                validation_notes=["LLM returned unparseable response; please retry."],
            )

        nodes = [FlowchartNode(**n) for n in data.get("nodes", [])]
        edges = [FlowchartEdge(**e) for e in data.get("edges", [])]
        return ProcessFlowchart(
            nodes=nodes,
            edges=edges,
            mermaid=data.get("mermaid", ""),
            clarifying_questions=data.get("clarifying_questions", []),
            validation_notes=data.get("validation_notes", []),
            is_complete=bool(data.get("is_complete", True)),
        )


@dataclass
class FlowchartValidatorAgent:
    """Validates that a flowchart is complete and all paths terminate."""

    role: str = "Process Validation Expert"
    llm: LLMClient = field(default_factory=lambda: get_client("agent_builder_flowchart_validator"))

    def validate(self, flowchart: ProcessFlowchart) -> ProcessFlowchart:
        prompt = (
            "Validate the following flowchart for completeness.\n\n"
            f"Nodes:\n{json.dumps([n.model_dump() for n in flowchart.nodes], indent=2)}\n\n"
            f"Edges:\n{json.dumps([e.model_dump() for e in flowchart.edges], indent=2)}\n\n"
            f"Mermaid:\n{flowchart.mermaid}"
        )
        raw = self.llm.complete(prompt, system_prompt=_FLOWCHART_VALIDATOR_SYSTEM)
        data = _safe_parse(raw, "FlowchartValidatorAgent")
        if not data:
            return flowchart

        issues: List[str] = data.get("issues", [])
        suggestions: List[str] = data.get("suggestions", [])
        notes: List[str] = data.get("validation_notes", [])

        flowchart.is_complete = bool(data.get("is_complete", True))
        flowchart.validation_notes = notes + (["Issues: " + "; ".join(issues)] if issues else [])
        if suggestions:
            flowchart.clarifying_questions = list(
                dict.fromkeys(flowchart.clarifying_questions + suggestions)
            )
        return flowchart


@dataclass
class AgentPlannerAgent:
    """Maps a validated flowchart to a team of specialist agents."""

    role: str = "AI Agent Architect"
    llm: LLMClient = field(default_factory=lambda: get_client("agent_builder_planner"))

    def plan(self, flowchart: ProcessFlowchart, process_description: str) -> AgentPlan:
        prompt = textwrap.dedent(f"""
            Design a team of AI agents to implement the following process.

            Original description:
            {process_description}

            Flowchart nodes:
            {json.dumps([n.model_dump() for n in flowchart.nodes], indent=2)}

            Flowchart edges:
            {json.dumps([e.model_dump() for e in flowchart.edges], indent=2)}

            Mermaid diagram:
            {flowchart.mermaid}
        """).strip()

        raw = self.llm.complete(prompt, system_prompt=_AGENT_PLANNER_SYSTEM)
        data = _safe_parse(raw, "AgentPlannerAgent")
        if not data:
            return AgentPlan(
                team_name="unnamed_team",
                pipeline_description="Could not generate plan; please retry.",
                phases=[],
                agents=[],
            )

        agents = [AgentSpec(**a) for a in data.get("agents", [])]
        return AgentPlan(
            team_name=data.get("team_name", "unnamed_team"),
            pipeline_description=data.get("pipeline_description", ""),
            phases=data.get("phases", []),
            human_checkpoints=data.get("human_checkpoints", []),
            agents=agents,
        )


@dataclass
class PlanReviewerAgent:
    """Reviews the agent plan against the flowchart for completeness and correctness."""

    role: str = "Senior AI Systems Architect"
    llm: LLMClient = field(default_factory=lambda: get_client("agent_builder_plan_reviewer"))

    def review(self, plan: AgentPlan, flowchart: ProcessFlowchart) -> AgentPlan:
        prompt = textwrap.dedent(f"""
            Review the following agent plan against the process flowchart.

            Flowchart nodes:
            {json.dumps([n.model_dump() for n in flowchart.nodes], indent=2)}

            Agent plan:
            {json.dumps(plan.model_dump(), indent=2)}
        """).strip()

        raw = self.llm.complete(prompt, system_prompt=_PLAN_REVIEWER_SYSTEM)
        data = _safe_parse(raw, "PlanReviewerAgent")
        if not data:
            return plan

        notes_parts = []
        if data.get("review_notes"):
            notes_parts.append(data["review_notes"])
        if data.get("issues"):
            notes_parts.append("Issues: " + "; ".join(data["issues"]))
        if data.get("suggestions"):
            notes_parts.append("Suggestions: " + "; ".join(data["suggestions"]))

        plan.review_notes = "\n".join(notes_parts)
        return plan


@dataclass
class AgentBuilderAgent:
    """Generates the complete agent team Python source files from a plan + flowchart."""

    role: str = "Senior Python Agent Developer"
    llm: LLMClient = field(default_factory=lambda: get_client("agent_builder_builder"))

    def build(
        self,
        plan: AgentPlan,
        flowchart: ProcessFlowchart,
        process_description: str,
    ) -> tuple[List[GeneratedFile], str]:
        prompt = textwrap.dedent(f"""
            Generate a complete Strands Agents team named "{plan.team_name}".

            Original process description:
            {process_description}

            Pipeline phases:
            {json.dumps(plan.phases, indent=2)}

            Human checkpoints:
            {json.dumps(plan.human_checkpoints, indent=2)}

            Agent specifications:
            {json.dumps([a.model_dump() for a in plan.agents], indent=2)}

            Flowchart (Mermaid):
            {flowchart.mermaid}

            Generate all 6 files: __init__.py, models.py, agents.py,
            orchestrator.py, api/__init__.py, api/main.py.
        """).strip()

        raw = self.llm.complete(prompt, system_prompt=_AGENT_BUILDER_SYSTEM)
        data = _safe_parse(raw, "AgentBuilderAgent")
        if not data or not data.get("files"):
            return [], "Build failed: LLM returned no files."

        files = [GeneratedFile(**f) for f in data["files"]]
        notes = data.get("delivery_notes", "")
        return files, notes


@dataclass
class AgentRefinerAgent:
    """Reviews and surgically corrects generated agent team code."""

    role: str = "Senior Python Code Reviewer"
    llm: LLMClient = field(default_factory=lambda: get_client("agent_builder_refiner"))

    def refine(self, files: List[GeneratedFile]) -> tuple[List[GeneratedFile], str]:
        files_payload = [{"filename": f.filename, "content": f.content} for f in files]
        prompt = (
            "Review and correct the following generated agent team files.\n\n"
            f"Files:\n{json.dumps(files_payload, indent=2)}"
        )
        raw = self.llm.complete(prompt, system_prompt=_REFINER_SYSTEM)
        data = _safe_parse(raw, "AgentRefinerAgent")
        if not data or not data.get("files"):
            # Return original files unchanged if refiner fails
            logger.warning("AgentRefinerAgent returned no files; keeping originals.")
            return files, "No refinements applied."

        refined = [GeneratedFile(**f) for f in data["files"]]
        notes = data.get("refinement_notes", "")
        return refined, notes
