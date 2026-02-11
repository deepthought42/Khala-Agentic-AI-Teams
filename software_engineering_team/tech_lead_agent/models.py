"""Models for the Tech Lead agent."""

from typing import List, Optional

from pydantic import BaseModel, Field

from shared.models import ProductRequirements, SystemArchitecture, Task, TaskAssignment


class TechLeadInput(BaseModel):
    """Input for the Tech Lead agent."""

    requirements: ProductRequirements
    architecture: Optional[SystemArchitecture] = Field(
        None,
        description="System architecture from Architecture Expert (required for task breakdown)",
    )
    repo_path: Optional[str] = Field(
        None,
        description="Path to the git repo; Tech Lead uses this for context and orchestration",
    )
    spec_content: Optional[str] = Field(
        None,
        description="Full content of initial_spec.md; used to generate the build plan",
    )
    existing_tasks: Optional[List[Task]] = Field(
        None,
        description="Existing tasks to extend or reprioritize",
    )


class TechLeadOutput(BaseModel):
    """Output from the Tech Lead agent."""

    assignment: TaskAssignment
    summary: str = ""
