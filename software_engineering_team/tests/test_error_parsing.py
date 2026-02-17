"""Tests for shared.error_parsing."""

from shared.error_parsing import (
    FailureClass,
    ParsedFailure,
    build_agent_feedback,
    get_failure_class_tag,
    parse_ng_build_failure,
    parse_pytest_failure,
)


def test_parse_pytest_import_error():
    stdout = """
= ERRORS ====================================
____________________ ERROR collecting tests/test_models.py _____________________
ImportError while importing test module 'tests/test_models.py'.
tests/test_models.py:7: in <module>
    from app.database import Base
E   ImportError: cannot import name 'Base' from 'app.database'
"""
    failures = parse_pytest_failure(stdout, "")
    assert len(failures) == 1
    assert failures[0].failure_class == FailureClass.IMPORT_ERROR
    assert "Base" in failures[0].message
    assert "app.database" in failures[0].message


def test_parse_pytest_assertion_extracts_test_and_assertion():
    stdout = """
= FAILURES ====================================
FAILED tests/test_auth_middleware.py::test_invalid_auth_header - AssertionError: assert 200 == 401
    def test_invalid_auth_header():
        response = client.get("/api/tasks")
>       assert response.status_code == 401
E       AssertionError: assert 200 == 401
E         +200
E         -401
"""
    failures = parse_pytest_failure(stdout, "")
    assert len(failures) == 1
    assert failures[0].failure_class == FailureClass.PYTEST_ASSERTION
    assert "test_invalid_auth_header" in failures[0].message
    assert "200" in failures[0].message or "401" in failures[0].message
    assert failures[0].file_path == "tests/test_auth_middleware.py"
    assert "test_auth_middleware" in (failures[0].suggestion or "")


def test_parse_pytest_sql_no_such_table():
    stdout = """
ERROR root:auth.py:92 Unexpected error: (sqlite3.OperationalError) no such table: api_tokens
[SQL: SELECT api_tokens.id FROM api_tokens]
"""
    failures = parse_pytest_failure(stdout, "")
    assert len(failures) == 1
    assert failures[0].failure_class == FailureClass.SQL_NO_SUCH_TABLE
    assert "api_tokens" in failures[0].message


def test_parse_ng_build_unresolved():
    stderr = """
Could not resolve "./components/task-form/task-form.component"
    src/app/app.routes.ts:10:53:
      10 | loadComponent: () => import('./components/task-form/task-form.component')
"""
    failures = parse_ng_build_failure("", stderr)
    assert len(failures) == 1
    assert failures[0].failure_class == FailureClass.FRONTEND_UNRESOLVED_IMPORT
    assert "task-form" in failures[0].message


def test_build_agent_feedback():
    failures = [
        ParsedFailure(
            failure_class=FailureClass.IMPORT_ERROR,
            message="cannot import name 'Base' from 'app.database'",
            suggestion="Ensure app.database exports Base.",
            playbook_hint="Add the missing export.",
            raw_excerpt="ImportError: cannot import name 'Base'",
        )
    ]
    feedback = build_agent_feedback(failures, max_chars=500)
    assert "[import_error]" in feedback
    assert "Suggestion:" in feedback
    assert "Playbook:" in feedback
    assert "Base" in feedback


def test_get_failure_class_tag():
    assert get_failure_class_tag(FailureClass.IMPORT_ERROR) == "failure_class=import_error"
    assert get_failure_class_tag(FailureClass.SQL_NO_SUCH_TABLE) == "failure_class=sql_no_such_table"
