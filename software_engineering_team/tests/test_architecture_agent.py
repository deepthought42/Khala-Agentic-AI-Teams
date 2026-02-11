"""Tests for Architecture Expert agent."""

import pytest

from architecture_agent import ArchitectureExpertAgent, ArchitectureInput
from shared.llm import DummyLLMClient
from shared.models import ProductRequirements


@pytest.fixture
def requirements() -> ProductRequirements:
    return ProductRequirements(
        title="Task Manager API",
        description="REST API for tasks with CRUD",
        acceptance_criteria=["POST /tasks", "GET /tasks"],
        constraints=["Python FastAPI", "PostgreSQL"],
        priority="high",
    )


def test_architecture_agent_produces_components(requirements: ProductRequirements) -> None:
    """Architecture Expert returns SystemArchitecture with components."""
    llm = DummyLLMClient()
    agent = ArchitectureExpertAgent(llm_client=llm)
    result = agent.run(
        ArchitectureInput(
            requirements=requirements,
            technology_preferences=["Python", "FastAPI"],
        )
    )
    assert result.architecture.overview
    assert len(result.architecture.components) >= 1
    assert any(c.type == "backend" for c in result.architecture.components)
    assert result.summary or result.architecture.architecture_document


def test_architecture_agent_with_existing_architecture(requirements: ProductRequirements) -> None:
    """Architecture Expert accepts existing_architecture for extension."""
    from shared.models import SystemArchitecture
    llm = DummyLLMClient()
    agent = ArchitectureExpertAgent(llm_client=llm)
    existing = SystemArchitecture(
        overview="Existing API",
        components=[],
    )
    result = agent.run(
        ArchitectureInput(
            requirements=requirements,
            existing_architecture=existing.overview,
        )
    )
    assert result.architecture.components
