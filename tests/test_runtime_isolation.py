"""Tests for runtime worktree isolation helpers."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.runtime.isolation import GitWorktreeIsolation
from src.runtime.isolation import WorktreeIsolationError


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    (path / "README.md").write_text("# Test\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "init")
    return path


def _resolve_git_path(repo: Path, git_path: str) -> Path:
    path = Path(git_path)
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def test_create_worktree_returns_task_node_path(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    isolation = GitWorktreeIsolation(repo)

    worktree = isolation.create_worktree(task_id="task-1", node_id="node-a")

    assert worktree == repo / ".sarathi" / "worktrees" / "task-1" / "node-a"
    assert worktree.exists()


def test_create_worktree_creates_linked_git_worktree(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    parent_common_dir = _resolve_git_path(repo, _git(repo, "rev-parse", "--git-common-dir"))
    isolation = GitWorktreeIsolation(repo)

    worktree = isolation.create_worktree(task_id="task-1", node_id="node-a")

    child_git_dir = _git(worktree, "rev-parse", "--git-dir")
    child_common_dir = _resolve_git_path(
        worktree,
        _git(worktree, "rev-parse", "--git-common-dir"),
    )
    assert child_git_dir != ".git"
    assert child_common_dir == parent_common_dir


def test_cleanup_worktree_removes_path_and_registration(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    isolation = GitWorktreeIsolation(repo)
    worktree = isolation.create_worktree(task_id="task-1", node_id="node-a")

    isolation.cleanup_worktree(worktree)

    assert not worktree.exists()
    assert str(worktree) not in _git(repo, "worktree", "list", "--porcelain")


def test_cleanup_task_worktrees_removes_each_node_worktree(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    isolation = GitWorktreeIsolation(repo)
    first = isolation.create_worktree(task_id="task-1", node_id="node-a")
    second = isolation.create_worktree(task_id="task-1", node_id="node-b")

    isolation.cleanup_task_worktrees("task-1")

    assert not first.exists()
    assert not second.exists()


def test_apply_worktree_changes_requires_approval(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    isolation = GitWorktreeIsolation(repo)
    worktree = isolation.create_worktree(task_id="task-1", node_id="winner")
    (worktree / "winner.txt").write_text("winner\n", encoding="utf-8")

    result = isolation.apply_worktree_changes(worktree, approved=False)

    assert result["applied"] is False
    assert result["approval_required"] is True
    assert not (repo / "winner.txt").exists()


def test_apply_worktree_changes_applies_untracked_candidate_file(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    isolation = GitWorktreeIsolation(repo)
    worktree = isolation.create_worktree(task_id="task-1", node_id="winner")
    (worktree / "winner.txt").write_text("winner\n", encoding="utf-8")

    result = isolation.apply_worktree_changes(worktree, approved=True)

    assert result["applied"] is True
    assert result["files_changed"] == ["winner.txt"]
    assert (repo / "winner.txt").read_text(encoding="utf-8") == "winner\n"


def test_apply_worktree_changes_applies_tracked_file_modification(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    isolation = GitWorktreeIsolation(repo)
    worktree = isolation.create_worktree(task_id="task-1", node_id="winner")
    (worktree / "README.md").write_text("# Modified in worktree\n", encoding="utf-8")

    result = isolation.apply_worktree_changes(worktree, approved=True)

    assert result["applied"] is True
    assert result["files_changed"] == ["README.md"]
    assert (repo / "README.md").read_text(encoding="utf-8") == "# Modified in worktree\n"


def test_apply_worktree_changes_rejects_dirty_parent_workspace(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    isolation = GitWorktreeIsolation(repo)
    worktree = isolation.create_worktree(task_id="task-1", node_id="winner")
    (worktree / "winner.txt").write_text("winner\n", encoding="utf-8")
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(WorktreeIsolationError, match="parent workspace must be clean"):
        isolation.apply_worktree_changes(worktree, approved=True)

    assert not (repo / "winner.txt").exists()


def test_apply_worktree_changes_excludes_sarathi_runtime_artifacts(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    isolation = GitWorktreeIsolation(repo)
    worktree = isolation.create_worktree(task_id="task-1", node_id="winner")
    (worktree / "winner.txt").write_text("winner\n", encoding="utf-8")
    runtime_dir = worktree / ".sarathi"
    runtime_dir.mkdir()
    (runtime_dir / "trace.json").write_text("{}\n", encoding="utf-8")

    result = isolation.apply_worktree_changes(worktree, approved=True)

    assert result["applied"] is True
    assert result["files_changed"] == ["winner.txt"]
    assert (repo / "winner.txt").exists()
    assert not (repo / ".sarathi" / "trace.json").exists()


def test_apply_worktree_changes_rejects_unmanaged_worktree_path(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    other_repo = _init_repo(tmp_path / "other")
    isolation = GitWorktreeIsolation(repo)
    (other_repo / "winner.txt").write_text("winner\n", encoding="utf-8")

    with pytest.raises(WorktreeIsolationError, match="managed worktree"):
        isolation.apply_worktree_changes(other_repo, approved=True)

    assert not (repo / "winner.txt").exists()
