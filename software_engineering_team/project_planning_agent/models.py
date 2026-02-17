"""Models for the Project Planning agent."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from shared.models import ProductRequirements


class Milestone(BaseModel):
    """A milestone in the project plan."""

    id: str
    name: str
    description: str = ""
    target_order: int = 0
    scope_summary: str = ""


class RiskItem(BaseModel):
    """A risk with mitigation notes."""

    description: str
    severity: str = "medium"  # low, medium, high
    mitigation: str = ""


class ProjectOverview(BaseModel):
    """High-level project overview from ProjectPlanningAgent."""

    features_and_functionality_doc: str = Field(
        "",
        description="High-level list of required features and functionalities from the spec",
    )
    primary_goal: str = ""
    secondary_goals: List[str] = Field(default_factory=list)
    milestones: List[Milestone] = Field(default_factory=list)
    risk_items: List[RiskItem] = Field(default_factory=list)
    delivery_strategy: str = ""  # e.g., backend-first, vertical slices
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ProjectPlanningInput(BaseModel):
    """Input for the Project Planning agent."""

    requirements: ProductRequirements
    spec_content: str = ""
    repo_state_summary: Optional[str] = Field(
        None,
        description="Summary of existing codebase from scan",
    )


class ProjectPlanningOutput(BaseModel):
    """Output from the Project Planning agent."""

    overview: ProjectOverview
    summary: str = ""
    features_and_functionality_doc: str = Field(
        "",
        description="Standalone features/functionality document (same as overview.features_and_functionality_doc if set)",
    )


def build_fallback_overview_from_requirements(requirements: ProductRequirements) -> ProjectOverview:
    """
    Build a deterministic ProjectOverview from ProductRequirements when LLM-based
    planning fails. Ensures downstream agents (Architecture, Tech Lead) always
    receive a valid overview structure.
    """
    primary_goal = (requirements.title or "").strip() or "Deliver the specified product"
    if requirements.description and requirements.description.strip():
        primary_goal = f"{primary_goal}: {requirements.description[:200].strip()}"
        if len(requirements.description) > 200:
            primary_goal += "..."

    secondary_goals: List[str] = []
    for ac in (requirements.acceptance_criteria or [])[:5]:
        if ac and isinstance(ac, str) and ac.strip():
            secondary_goals.append(ac.strip())
    for c in (requirements.constraints or [])[:3]:
        if c and isinstance(c, str) and c.strip():
            secondary_goals.append(f"Constraint: {c.strip()}")

    milestones = [
        Milestone(id="M1", name="Foundational backend & data", description="Core API, data models, persistence", target_order=0, scope_summary="Backend foundation"),
        Milestone(id="M2", name="Frontend & UX", description="UI implementation and user flows", target_order=1, scope_summary="Frontend and integration"),
        Milestone(id="M3", name="Hardening & polish", description="Testing, security, documentation, deployment", target_order=2, scope_summary="Quality and delivery"),
    ]

    risk_items = [
        RiskItem(description="Spec ambiguity or changing requirements", severity="medium", mitigation="Iterate with stakeholders; document assumptions"),
        RiskItem(description="Performance or scalability gaps", severity="low", mitigation="Design for incremental scaling; profile early"),
        RiskItem(description="Security vulnerabilities", severity="medium", mitigation="Follow security best practices; run security review"),
    ]

    delivery_strategy = "Backend-first with incremental UI; vertical slices to deliver value quickly"

    features_doc = f"# Features and Functionality (fallback)\n\n- Deliver: {primary_goal}\n"
    for ac in (requirements.acceptance_criteria or [])[:8]:
        if ac and isinstance(ac, str) and ac.strip():
            features_doc += f"- {ac.strip()}\n"

    return ProjectOverview(
        features_and_functionality_doc=features_doc,
        primary_goal=primary_goal,
        secondary_goals=secondary_goals,
        milestones=milestones,
        risk_items=risk_items,
        delivery_strategy=delivery_strategy,
    )
