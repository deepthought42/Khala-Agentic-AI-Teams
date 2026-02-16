"""Tests for Frontend Expert agent."""

from unittest.mock import MagicMock

import pytest

from frontend_agent import FrontendExpertAgent, FrontendInput, FrontendOutput
from shared.llm import DummyLLMClient


def test_frontend_output_has_npm_packages_to_install() -> None:
    """FrontendOutput includes npm_packages_to_install field with default empty list."""
    out = FrontendOutput(
        code="",
        summary="",
        files={},
        components=[],
        npm_packages_to_install=[],
    )
    assert out.npm_packages_to_install == []


def test_frontend_output_npm_packages_default() -> None:
    """FrontendOutput defaults npm_packages_to_install to empty list."""
    out = FrontendOutput(code="x", summary="y", files={"src/x.ts": "content"})
    assert out.npm_packages_to_install == []


def test_frontend_agent_parses_npm_packages_from_llm() -> None:
    """Frontend agent parses npm_packages_to_install from LLM JSON and includes in output."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Added component",
        "files": {
            "src/app/components/example/example.component.ts": "import { Component } from '@angular/core';\n@Component({ selector: 'app-example', template: '<p>hi</p>' }) export class ExampleComponent {}",
        },
        "components": ["example"],
        "suggested_commit_message": "feat(ui): add example",
        "npm_packages_to_install": ["@ngrx/store", "ngx-toastr"],
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(
        FrontendInput(
            task_description="Add example component",
            requirements="Use NgRx and toastr",
        )
    )
    assert result.npm_packages_to_install == ["@ngrx/store", "ngx-toastr"]


def test_frontend_agent_npm_packages_empty_when_omitted() -> None:
    """When LLM omits npm_packages_to_install, output has empty list."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Added component",
        "files": {
            "src/app/components/example/example.component.ts": "import { Component } from '@angular/core';\n@Component({ selector: 'app-example', template: '<p>hi</p>' }) export class ExampleComponent {}",
        },
        "components": ["example"],
        "suggested_commit_message": "feat(ui): add example",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(FrontendInput(task_description="Add example", requirements=""))
    assert result.npm_packages_to_install == []


def test_frontend_agent_npm_packages_normalizes_non_list() -> None:
    """When LLM returns non-list npm_packages_to_install, it is normalized to list."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Added component",
        "files": {
            "src/app/components/example/example.component.ts": "import { Component } from '@angular/core';\n@Component({ selector: 'app-example', template: '<p>hi</p>' }) export class ExampleComponent {}",
        },
        "components": ["example"],
        "suggested_commit_message": "feat(ui): add example",
        "npm_packages_to_install": "ngx-toastr",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(FrontendInput(task_description="Add example", requirements=""))
    assert result.npm_packages_to_install == ["ngx-toastr"]


def test_frontend_agent_with_dummy_llm() -> None:
    """Frontend agent runs with DummyLLMClient and returns valid output."""
    llm = DummyLLMClient()
    agent = FrontendExpertAgent(llm_client=llm)
    result = agent.run(
        FrontendInput(
            task_description="Create user form component",
            requirements="Angular reactive forms",
        )
    )
    assert result is not None
    assert isinstance(result, FrontendOutput)
    assert result.files
    assert "src/" in next(iter(result.files))
    assert result.npm_packages_to_install == []
