"""
Structured error parsing for build/test failures.

Categorizes pytest, ng build, and SQLAlchemy errors into structured objects
with error type, file, line, probable cause, and remediation playbooks.
Used by agents to understand failures and apply targeted fixes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class FailureClass(str, Enum):
    """Standard failure classes for observability and agent tuning."""

    EMPTY_COMPLETION = "empty_completion"
    JSON_PARSE_FAILURE = "json_parse_failure"
    IMPORT_ERROR = "import_error"
    SQL_NO_SUCH_TABLE = "sql_no_such_table"
    FRONTEND_UNRESOLVED_IMPORT = "frontend_unresolved_import"
    PYTEST_ASSERTION = "pytest_assertion"
    PYTEST_COLLECTION = "pytest_collection"
    NG_BUILD_ERROR = "ng_build_error"
    ENVIRONMENT = "environment"
    UNKNOWN = "unknown"


@dataclass
class ParsedFailure:
    """Structured representation of a build/test failure."""

    failure_class: FailureClass
    file_path: Optional[str] = None
    line: Optional[int] = None
    message: str = ""
    raw_excerpt: str = ""
    suggestion: str = ""
    playbook_hint: str = ""


# Playbook hints for common failure types (fed to agents)
PLAYBOOK_IMPORT_ERROR = (
    "Add the missing export to the module. For 'cannot import name X from Y', "
    "ensure Y defines and exports X (e.g. in __init__.py or the module itself)."
)
PLAYBOOK_SQL_NO_SUCH_TABLE = (
    "Ensure all SQLAlchemy models are imported into the app's metadata and that "
    "Base.metadata.create_all(bind=engine) is called before any queries. "
    "In tests, use a fixture or conftest that creates tables before running."
)
PLAYBOOK_FRONTEND_UNRESOLVED = (
    "Create the missing component file or fix the import path. For Angular routes, "
    "ensure the path in loadComponent/lazy load matches an existing file that exports "
    "the expected component class."
)
PLAYBOOK_PYTEST_ASSERTION = (
    "Fix the failing assertion. Check the test expectations and ensure the implementation "
    "matches (e.g. status codes, response structure, database state)."
)
PLAYBOOK_PYTEST_COLLECTION = (
    "Fix import or syntax errors that prevent pytest from collecting tests. "
    "Often caused by missing exports (e.g. Base from app.database) or circular imports."
)


def parse_pytest_failure(stdout: str, stderr: str) -> List[ParsedFailure]:
    """
    Parse pytest output into structured failures.

    Handles:
    - ImportError (cannot import name X from Y)
    - sqlite3.OperationalError (no such table: X)
    - AssertionError / test failures
    """
    text = (stdout or "") + "\n" + (stderr or "")
    failures: List[ParsedFailure] = []

    # ImportError: cannot import name 'Base' from 'app.database'
    import_match = re.search(
        r"ImportError(?:\s+while importing[^:]*)?:\s*cannot import name ['\"]([^'\"]+)['\"] from ['\"]([^'\"]+)['\"]",
        text,
        re.IGNORECASE,
    )
    if import_match:
        symbol, module = import_match.group(1), import_match.group(2)
        file_match = re.search(r"tests/test_[^\s]+\.py", text)
        file_path = file_match.group(0) if file_match else None
        failures.append(
            ParsedFailure(
                failure_class=FailureClass.IMPORT_ERROR,
                file_path=file_path,
                message=f"cannot import name '{symbol}' from '{module}'",
                raw_excerpt=text[import_match.start() : import_match.end() + 200],
                suggestion=f"Ensure {module} exports {symbol}. Add 'from .database import Base' or define Base in app/database.py.",
                playbook_hint=PLAYBOOK_IMPORT_ERROR,
            )
        )
        return failures  # Often the root cause; return early

    # no such table: api_tokens (from sqlite3.OperationalError or similar)
    sql_match = re.search(
        r"no such table:\s*([a-zA-Z_]+)",
        text,
        re.IGNORECASE,
    )
    if sql_match:
        table = sql_match.group(1)
        failures.append(
            ParsedFailure(
                failure_class=FailureClass.SQL_NO_SUCH_TABLE,
                message=f"no such table: {table}",
                raw_excerpt=text[sql_match.start() : sql_match.end() + 300],
                suggestion=f"Create the {table} table: ensure the model is in Base.metadata and call Base.metadata.create_all(bind=engine) before queries.",
                playbook_hint=PLAYBOOK_SQL_NO_SUCH_TABLE,
            )
        )
        return failures

    # Pytest assertion failure - extract test name, file, and assertion details
    if "= FAILURES =" in text or "assert " in text:
        raw_excerpt = text[-2500:] if len(text) > 2500 else text
        test_file: Optional[str] = None
        test_name: Optional[str] = None
        assertion_line: Optional[str] = None
        expected_got: Optional[str] = None

        # FAILED tests/test_auth_middleware.py::test_invalid_auth_header
        failed_match = re.search(
            r"FAILED\s+([a-zA-Z0-9_/.-]+test_[a-zA-Z0-9_]+\.py)(?:::(test_[a-zA-Z0-9_]+))?",
            text,
        )
        if failed_match:
            test_file = failed_match.group(1).strip()
            test_name = failed_match.group(2) if failed_match.group(2) else None

        # AssertionError: assert 200 == 401  or  E       AssertionError: assert 200 == 401
        assert_err_match = re.search(
            r"AssertionError:\s*(assert\s+[^\n]+)",
            text,
        )
        if assert_err_match:
            assertion_line = assert_err_match.group(1).strip()[:200]

        # E         +200  /  E         -401  (actual vs expected)
        expected_match = re.search(
            r"E\s+[+-]\s*(\d+)\s*\n\s*E\s+[+-]\s*(\d+)",
            text,
        )
        if expected_match:
            v1, v2 = expected_match.group(1), expected_match.group(2)
            expected_got = f"expected {v2}, got {v1}" if v1 != v2 else f"values {v1} vs {v2}"

        # Build targeted message and suggestion
        msg_parts = []
        if test_name:
            msg_parts.append(f"{test_name} failed")
        if assertion_line:
            msg_parts.append(assertion_line)
        if expected_got:
            msg_parts.append(f"({expected_got})")
        message = (
            " ".join(msg_parts)
            if msg_parts
            else "One or more tests failed (assertion or status code mismatch)"
        )

        suggestion_parts = []
        if test_file:
            suggestion_parts.append(f"Fix {test_file}")
        if test_name:
            suggestion_parts.append(f"({test_name})")
        if assertion_line:
            suggestion_parts.append(f"to satisfy: {assertion_line}")
        suggestion = (
            ". ".join(suggestion_parts) + "."
            if suggestion_parts
            else "Review the failing test(s) and fix the implementation to match expectations."
        )

        failures.append(
            ParsedFailure(
                failure_class=FailureClass.PYTEST_ASSERTION,
                file_path=test_file,
                message=message,
                raw_excerpt=raw_excerpt,
                suggestion=suggestion,
                playbook_hint=PLAYBOOK_PYTEST_ASSERTION,
            )
        )

    # Collection error (not ImportError)
    if "ERROR collecting" in text and FailureClass.IMPORT_ERROR not in [f.failure_class for f in failures]:
        failures.append(
            ParsedFailure(
                failure_class=FailureClass.PYTEST_COLLECTION,
                message="pytest could not collect tests (syntax or import error)",
                raw_excerpt=text[-2000:] if len(text) > 2000 else text,
                suggestion="Fix the error that prevents test collection (imports, syntax).",
                playbook_hint=PLAYBOOK_PYTEST_COLLECTION,
            )
        )

    if not failures:
        failures.append(
            ParsedFailure(
                failure_class=FailureClass.UNKNOWN,
                message="Unrecognized pytest failure",
                raw_excerpt=text[-2000:] if len(text) > 2000 else text,
            )
        )
    return failures


def parse_ng_build_failure(stdout: str, stderr: str) -> List[ParsedFailure]:
    """
    Parse Angular/ng build output into structured failures.

    Handles:
    - Could not resolve "./components/foo/foo.component"
    """
    text = (stdout or "") + "\n" + (stderr or "")
    failures: List[ParsedFailure] = []

    # Could not resolve "./components/task-form/task-form.component"
    resolve_match = re.search(
        r"Could not resolve ['\"]([^'\"]+)['\"]",
        text,
        re.IGNORECASE,
    )
    if resolve_match:
        path = resolve_match.group(1)
        # Try to find file:line from context (e.g. src/app/app.routes.ts:10:53)
        file_match = re.search(r"(src/[^\s:]+\.ts):(\d+):(\d+)", text)
        file_path = file_match.group(1) if file_match else None
        line = int(file_match.group(2)) if file_match and file_match.group(2) else None
        failures.append(
            ParsedFailure(
                failure_class=FailureClass.FRONTEND_UNRESOLVED_IMPORT,
                file_path=file_path,
                line=line,
                message=f"Could not resolve '{path}'",
                raw_excerpt=text[resolve_match.start() : resolve_match.end() + 400],
                suggestion=f"Create the missing file for '{path}' or fix the import path in the route/component.",
                playbook_hint=PLAYBOOK_FRONTEND_UNRESOLVED,
            )
        )
        return failures

    # Generic ng build error
    if "ERROR" in text or "error" in text.lower():
        failures.append(
            ParsedFailure(
                failure_class=FailureClass.NG_BUILD_ERROR,
                message="Angular build failed",
                raw_excerpt=text[-3000:] if len(text) > 3000 else text,
                suggestion="Fix the compilation errors reported above.",
                playbook_hint="Address the specific TypeScript/template errors shown in the output.",
            )
        )

    if not failures:
        failures.append(
            ParsedFailure(
                failure_class=FailureClass.UNKNOWN,
                message="Unrecognized ng build failure",
                raw_excerpt=text[-2000:] if len(text) > 2000 else text,
            )
        )
    return failures


def parse_command_failure(
    command_kind: str,
    stdout: str,
    stderr: str,
) -> List[ParsedFailure]:
    """
    Parse command output based on command kind.

    command_kind: "pytest" | "ng_build" | "py_compile"
    """
    if command_kind == "pytest":
        return parse_pytest_failure(stdout, stderr)
    if command_kind in ("ng_build", "ng"):
        return parse_ng_build_failure(stdout, stderr)
    return [
        ParsedFailure(
            failure_class=FailureClass.UNKNOWN,
            message="Build/test failure",
            raw_excerpt=(stdout or "") + "\n" + (stderr or ""),
        )
    ]


def build_agent_feedback(failures: List[ParsedFailure], max_chars: int = 2500) -> str:
    """
    Build a concise feedback string for agents from parsed failures.

    Includes the primary failure's suggestion and playbook hint, plus truncated raw excerpt.
    """
    if not failures:
        return ""
    primary = failures[0]
    parts = [
        f"[{primary.failure_class.value}] {primary.message}",
        "",
        "Suggestion:",
        primary.suggestion or "Fix the error.",
    ]
    if primary.playbook_hint:
        parts.extend(["", "Playbook:", primary.playbook_hint])
    if primary.raw_excerpt:
        excerpt = primary.raw_excerpt
        if len(excerpt) > max_chars:
            excerpt = excerpt[:max_chars] + "\n... [truncated]"
        parts.extend(["", "Raw output:", excerpt])
    return "\n".join(parts)


def get_failure_class_tag(failure_class: FailureClass) -> str:
    """Return a log-friendly tag for observability."""
    return f"failure_class={failure_class.value}"


def log_failure(failure_class: FailureClass, message: str, **kwargs: object) -> None:
    """
    Log a failure with standardized failure_class tag for observability.

    Use this so failure classes can be aggregated and tuned over time.
    """
    logger.warning(
        "%s | %s",
        get_failure_class_tag(failure_class),
        message,
        extra={"failure_class": failure_class.value, **kwargs},
    )
