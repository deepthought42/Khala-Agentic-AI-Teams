"""Tests for agent_git_tools executor (temp git repos)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_git_tools import GitToolContext, execute_git_tool


def _git_init_with_development(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("# t\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        env={
            **__import__("os").environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "development"], cwd=repo, check=True, capture_output=True)


def test_git_status(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init_with_development(repo)
    ctx = GitToolContext(repo)
    out = execute_git_tool("git_status", {}, ctx)
    assert out["success"] is True
    assert "returncode" in out


def test_git_write_files_and_commit(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init_with_development(repo)
    ctx = GitToolContext(repo)
    r = execute_git_tool(
        "git_write_files_and_commit",
        {"files": {"src/x.txt": "hello"}, "message": "add file"},
        ctx,
    )
    assert r["success"] is True
    assert (repo / "src" / "x.txt").read_text() == "hello"


def test_git_merge_branch_allowed(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init_with_development(repo)
    ctx = GitToolContext(repo, allow_merge_to_default_branch=True)
    b1 = execute_git_tool(
        "git_create_feature_branch",
        {"feature_name": "f1-merge-test"},
        ctx,
    )
    assert b1["success"] is True
    execute_git_tool(
        "git_write_files_and_commit",
        {"files": {"f.txt": "f"}, "message": "on feature"},
        ctx,
    )
    execute_git_tool("git_checkout_branch", {"branch": "development"}, ctx)
    m = execute_git_tool(
        "git_merge_branch",
        {"source_branch": "feature/f1-merge-test", "target_branch": "development"},
        ctx,
    )
    assert m["success"] is True


def test_git_merge_branch_blocked_when_disabled(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init_with_development(repo)
    ctx = GitToolContext(repo, allow_merge_to_default_branch=False)
    m = execute_git_tool(
        "git_merge_branch",
        {"source_branch": "feature/x", "target_branch": "development"},
        ctx,
    )
    assert m["success"] is False
    assert m.get("error") == "merge_disabled"


def test_rejects_path_traversal(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init_with_development(repo)
    ctx = GitToolContext(repo)
    r = execute_git_tool(
        "git_write_files_and_commit",
        {"files": {"../evil.txt": "x"}, "message": "bad"},
        ctx,
    )
    assert r["success"] is False
