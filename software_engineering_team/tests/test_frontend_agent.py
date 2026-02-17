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


def test_frontend_agent_rejects_segment_too_long() -> None:
    """Agent rejects path segments longer than 30 chars."""
    mock_llm = MagicMock()
    long_name = "a" * 35
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Test",
        "files": {
            f"src/app/{long_name}.component.ts": "content",
            "src/app/short.component.ts": "import { Component } from '@angular/core';\n@Component({selector: 'app-short', template: 'x'}) export class Short {}",
        },
        "components": ["short"],
        "suggested_commit_message": "feat: add",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(FrontendInput(task_description="Add", requirements=""))
    assert long_name not in str(result.files.keys())
    assert "src/app/short.component.ts" in result.files


def test_frontend_agent_rejects_sentence_like_name() -> None:
    """Agent rejects path segments that look like sentences (4+ hyphenated words)."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Test",
        "files": {
            "src/app/one-two-three-four-five.component.ts": "content",
            "src/app/task-list.component.ts": "import { Component } from '@angular/core';\n@Component({selector: 'app-task-list', template: 'x'}) export class TaskList {}",
        },
        "components": ["task-list"],
        "suggested_commit_message": "feat: add",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(FrontendInput(task_description="Add", requirements=""))
    assert "one-two-three-four-five" not in str(result.files.keys())
    assert "src/app/task-list.component.ts" in result.files


def test_frontend_agent_rejects_filler_words_in_path() -> None:
    """Agent rejects path segments with filler words like -the-, -with-."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Test",
        "files": {
            "src/app/component-with-the-thing.component.ts": "content",
            "src/app/thing.component.ts": "import { Component } from '@angular/core';\n@Component({selector: 'app-thing', template: 'x'}) export class Thing {}",
        },
        "components": ["thing"],
        "suggested_commit_message": "feat: add",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(FrontendInput(task_description="Add", requirements=""))
    assert "component-with-the-thing" not in str(result.files.keys())
    assert "src/app/thing.component.ts" in result.files


def test_frontend_agent_rejects_verb_prefix_in_path() -> None:
    """Agent rejects path segments starting with verbs like implement-."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Test",
        "files": {
            "src/app/implement-user-form.component.ts": "content",
            "src/app/user-form.component.ts": "import { Component } from '@angular/core';\n@Component({selector: 'app-user-form', template: 'x'}) export class UserForm {}",
        },
        "components": ["user-form"],
        "suggested_commit_message": "feat: add",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(FrontendInput(task_description="Add", requirements=""))
    assert "implement-user-form" not in str(result.files.keys())
    assert "src/app/user-form.component.ts" in result.files


def test_frontend_agent_rejects_path_not_under_src() -> None:
    """Agent rejects files not under src/."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Test",
        "files": {
            "app/x.component.ts": "content",
            "src/app/valid.component.ts": "import { Component } from '@angular/core';\n@Component({selector: 'app-valid', template: 'x'}) export class Valid {}",
        },
        "components": ["valid"],
        "suggested_commit_message": "feat: add",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(FrontendInput(task_description="Add component", requirements=""))
    assert "app/x.component.ts" not in result.files
    assert "src/app/valid.component.ts" in result.files


def test_frontend_agent_rejects_bad_extension() -> None:
    """Agent rejects non-browser file extensions."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Test",
        "files": {
            "src/app/foo.py": "print('hi')",
            "src/app/bar.component.ts": "import { Component } from '@angular/core';\n@Component({selector: 'app-bar', template: 'x'}) export class Bar {}",
        },
        "components": ["bar"],
        "suggested_commit_message": "feat: add",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(FrontendInput(task_description="Add", requirements=""))
    assert "src/app/foo.py" not in result.files
    assert "src/app/bar.component.ts" in result.files


def test_frontend_agent_rejects_empty_content() -> None:
    """Agent rejects files with empty content."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Test",
        "files": {
            "src/app/empty.component.ts": "",
            "src/app/ok.component.ts": "import { Component } from '@angular/core';\n@Component({selector: 'app-ok', template: 'x'}) export class Ok {}",
        },
        "components": ["ok"],
        "suggested_commit_message": "feat: add",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(FrontendInput(task_description="Add", requirements=""))
    assert "src/app/empty.component.ts" not in result.files
    assert "src/app/ok.component.ts" in result.files


def test_frontend_agent_with_architecture() -> None:
    """Agent includes architecture in context when provided."""
    from shared.models import ArchitectureComponent, SystemArchitecture

    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Test",
        "files": {"src/app/x.component.ts": "content"},
        "components": ["x"],
        "suggested_commit_message": "feat: add",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    arch = SystemArchitecture(
        overview="Test arch",
        components=[ArchitectureComponent(name="UserService", type="frontend")],
    )
    result = agent.run(
        FrontendInput(
            task_description="Add component",
            requirements="",
            architecture=arch,
        )
    )
    call_args = mock_llm.complete_json.call_args[0][0]
    assert "Architecture" in call_args
    assert "Test arch" in call_args
    assert "UserService" in call_args


def test_frontend_agent_with_security_issues() -> None:
    """Agent includes security_issues in context when provided."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Test",
        "files": {"src/app/x.component.ts": "content"},
        "components": ["x"],
        "suggested_commit_message": "feat: add",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(
        FrontendInput(
            task_description="Fix vulnerability",
            requirements="",
            security_issues=[{"severity": "high", "category": "xss", "description": "Vuln", "recommendation": "Fix", "location": "x"}],
        )
    )
    call_args = mock_llm.complete_json.call_args[0][0]
    assert "Security issues" in call_args


def test_frontend_agent_with_accessibility_issues() -> None:
    """Agent includes accessibility_issues in context when provided."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Test",
        "files": {"src/app/x.component.ts": "content"},
        "components": ["x"],
        "suggested_commit_message": "feat: add",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(
        FrontendInput(
            task_description="Fix a11y",
            requirements="",
            accessibility_issues=[{"severity": "medium", "wcag_criterion": "1.1.1", "description": "Missing alt", "recommendation": "Add alt", "location": "x"}],
        )
    )
    call_args = mock_llm.complete_json.call_args[0][0]
    assert "Accessibility" in call_args


def test_frontend_agent_with_code_review_issues() -> None:
    """Agent includes code_review_issues in context when provided."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Test",
        "files": {"src/app/x.component.ts": "content"},
        "components": ["x"],
        "suggested_commit_message": "feat: add",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(
        FrontendInput(
            task_description="Address review",
            requirements="",
            code_review_issues=[{"severity": "medium", "description": "Refactor", "suggestion": "Simplify", "file_path": "x.ts"}],
        )
    )
    call_args = mock_llm.complete_json.call_args[0][0]
    assert "Code review" in call_args


def test_frontend_agent_with_qa_issues() -> None:
    """Agent includes qa_issues in context when provided."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Test",
        "files": {"src/app/x.component.ts": "content"},
        "components": ["x"],
        "suggested_commit_message": "feat: add",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(
        FrontendInput(
            task_description="Fix bugs",
            requirements="",
            qa_issues=[{"severity": "high", "description": "Bug", "recommendation": "Fix it", "location": "x.ts"}],
        )
    )
    call_args = mock_llm.complete_json.call_args[0][0]
    assert "QA issues" in call_args
    assert "Bug" in call_args


def test_frontend_agent_clarification_requests_non_list_normalized() -> None:
    """Agent normalizes non-list clarification_requests to list."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Need info",
        "files": {},
        "components": [],
        "suggested_commit_message": "",
        "needs_clarification": True,
        "clarification_requests": "Single question",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(FrontendInput(task_description="Vague", requirements=""))
    assert result.needs_clarification
    assert "Single question" in result.clarification_requests


def test_frontend_agent_needs_clarification() -> None:
    """Agent returns needs_clarification when LLM says so."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Need more info",
        "files": {},
        "components": [],
        "suggested_commit_message": "",
        "needs_clarification": True,
        "clarification_requests": ["What API format?"],
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(FrontendInput(task_description="Vague task", requirements=""))
    assert result.needs_clarification
    assert "What API format?" in result.clarification_requests


def test_frontend_agent_all_files_rejected_fallback_to_code() -> None:
    """When all files rejected but code exists, agent still returns code."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "import { Component } from '@angular/core';\n@Component({selector: 'app-x', template: 'x'}) export class X {}",
        "summary": "Test",
        "files": {"wrong/path.ts": "content"},
        "components": ["x"],
        "suggested_commit_message": "feat: add",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(FrontendInput(task_description="Add", requirements=""))
    assert not result.files
    assert result.code


def test_frontend_agent_unescapes_newlines_in_files() -> None:
    """Agent unescapes \\n in file contents."""
    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = {
        "code": "",
        "summary": "Test",
        "files": {"src/app/x.component.ts": "line1\\nline2"},
        "components": ["x"],
        "suggested_commit_message": "feat: add",
    }
    agent = FrontendExpertAgent(llm_client=mock_llm)
    result = agent.run(FrontendInput(task_description="Add", requirements=""))
    assert result.files["src/app/x.component.ts"] == "line1\nline2"
