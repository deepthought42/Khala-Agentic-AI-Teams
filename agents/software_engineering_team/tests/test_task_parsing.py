"""Tests for task parsing and dependency-aware interleaving."""

import pytest

from shared.models import Task, TaskAssignment, TaskStatus, TaskType
from shared.task_parsing import _normalize_task_type_and_assignee, parse_assignment_from_data


def test_interleave_respects_dependencies() -> None:
    """Interleaving must not place a task before its dependencies."""
    data = {
        "tasks": [
            {
                "id": "backend-models",
                "title": "Data models",
                "type": "backend",
                "assignee": "backend",
                "description": "Create models",
                "user_story": "As a dev",
                "requirements": "",
                "acceptance_criteria": [],
                "dependencies": [],
            },
            {
                "id": "backend-crud-api",
                "title": "CRUD API",
                "type": "backend",
                "assignee": "backend",
                "description": "Create CRUD endpoints",
                "user_story": "As a dev",
                "requirements": "",
                "acceptance_criteria": [],
                "dependencies": ["backend-models"],
            },
            {
                "id": "frontend-app-shell",
                "title": "App shell",
                "type": "frontend",
                "assignee": "frontend",
                "description": "Create app shell",
                "user_story": "As a dev",
                "requirements": "",
                "acceptance_criteria": [],
                "dependencies": [],
            },
            {
                "id": "frontend-list",
                "title": "List component",
                "type": "frontend",
                "assignee": "frontend",
                "description": "List that fetches from API",
                "user_story": "As a dev",
                "requirements": "",
                "acceptance_criteria": [],
                "dependencies": ["backend-crud-api"],
            },
        ],
        "execution_order": ["backend-models", "backend-crud-api", "frontend-app-shell", "frontend-list"],
        "rationale": "",
    }
    assignment = parse_assignment_from_data(data)
    order = assignment.execution_order

    # frontend-list depends on backend-crud-api; backend-crud-api must appear before frontend-list
    idx_crud = order.index("backend-crud-api")
    idx_list = order.index("frontend-list")
    assert idx_crud < idx_list, "frontend-list must come after backend-crud-api (dependency)"

    # Should be interleaved (backend and frontend alternate where possible)
    backend_ids = [t for t in order if t.startswith("backend-")]
    frontend_ids = [t for t in order if t.startswith("frontend-")]
    assert len(backend_ids) == 2
    assert len(frontend_ids) == 2


def test_normalize_fixes_frontend_id_with_backend_type() -> None:
    """frontend-app-shell with type=backend gets normalized to frontend."""
    task_type, assignee = _normalize_task_type_and_assignee(
        "frontend-app-shell", TaskType.BACKEND, "backend"
    )
    assert task_type == TaskType.FRONTEND
    assert assignee == "frontend"


def test_normalize_fixes_backend_id_with_frontend_type() -> None:
    """backend-todo-api with type=frontend gets normalized to backend."""
    task_type, assignee = _normalize_task_type_and_assignee(
        "backend-todo-api", TaskType.FRONTEND, "frontend"
    )
    assert task_type == TaskType.BACKEND
    assert assignee == "backend"


def test_parse_assignment_normalizes_misclassified_tasks() -> None:
    """parse_assignment_from_data fixes type/assignee when task id indicates domain."""
    data = {
        "tasks": [
            {
                "id": "frontend-app-init",
                "title": "Initialize frontend app",
                "type": "backend",  # Wrong - should be frontend
                "assignee": "backend",
                "description": "Create Angular app",
                "user_story": "As a dev",
                "requirements": "",
                "acceptance_criteria": [],
                "dependencies": [],
            },
        ],
        "execution_order": ["frontend-app-init"],
        "rationale": "",
    }
    assignment = parse_assignment_from_data(data)
    assert len(assignment.tasks) == 1
    t = assignment.tasks[0]
    assert t.type == TaskType.FRONTEND
    assert t.assignee == "frontend"
