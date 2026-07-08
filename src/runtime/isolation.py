"""Runtime workspace isolation helpers."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


class WorktreeIsolationError(RuntimeError):
    """Raised when a git worktree isolation operation fails."""


class GitWorktreeIsolation:
    """Create and clean git worktrees under `.sarathi/worktrees`."""

    def __init__(self, repo_root: str | Path):
        self.repo_root = Path(repo_root).resolve()
        self.worktrees_root = self.repo_root / ".sarathi" / "worktrees"

    def create_worktree(self, *, task_id: str, node_id: str) -> Path:
        """Create a detached worktree for one graph node and return its path."""
        worktree_path = self._worktree_path(task_id, node_id)
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        self._git("worktree", "add", "--detach", str(worktree_path), "HEAD")
        return worktree_path

    def cleanup_worktree(self, path: str | Path) -> None:
        """Remove one worktree, forcing cleanup of incomplete directories."""
        worktree_path = Path(path).resolve()
        if worktree_path.exists():
            self._git("worktree", "remove", "--force", str(worktree_path))
        self._git("worktree", "prune")

    def cleanup_task_worktrees(self, task_id: str) -> None:
        """Remove all node worktrees created for a task."""
        task_root = self.worktrees_root / self._safe_segment(task_id)
        if not task_root.exists():
            return
        for worktree_path in sorted(task_root.iterdir(), reverse=True):
            if worktree_path.is_dir():
                self.cleanup_worktree(worktree_path)
        if task_root.exists():
            task_root.rmdir()

    def apply_worktree_changes(self, path: str | Path, *, approved: bool) -> dict[str, Any]:
        """Apply a retained candidate worktree's diff back to the parent repo.

        The caller must pass an explicit approval decision. Without approval,
        this is a dry gate that reports approval is required and leaves the
        parent repo untouched.
        """
        worktree_path = Path(path).resolve()
        if not approved:
            return {
                "applied": False,
                "approval_required": True,
                "workspace_dir": str(worktree_path),
                "files_changed": [],
            }

        self._ensure_managed_worktree(worktree_path)
        self._ensure_clean_parent()
        self._intent_to_add_candidate_files(worktree_path)
        diff = self._candidate_diff(worktree_path)
        files_changed = self._changed_files(worktree_path)
        if not diff.strip():
            return {
                "applied": False,
                "approval_required": False,
                "workspace_dir": str(worktree_path),
                "files_changed": [],
            }
        self._git_apply(diff)
        return {
            "applied": True,
            "approval_required": False,
            "workspace_dir": str(worktree_path),
            "files_changed": files_changed,
        }

    def _worktree_path(self, task_id: str, node_id: str) -> Path:
        return self.worktrees_root / self._safe_segment(task_id) / self._safe_segment(node_id)

    def _git(self, *args: str) -> str:
        return self._git_in(self.repo_root, *args)

    def _git_in(self, cwd: Path, *args: str, input_text: str | None = None) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise WorktreeIsolationError(message)
        return result.stdout

    def _git_apply(self, diff: str) -> None:
        self._git_in(self.repo_root, "apply", "--check", "--binary", "-", input_text=diff)
        self._git_in(self.repo_root, "apply", "--binary", "-", input_text=diff)

    def _ensure_managed_worktree(self, worktree_path: Path) -> None:
        try:
            worktree_path.relative_to(self.worktrees_root)
        except ValueError as exc:
            raise WorktreeIsolationError("path is not a managed worktree") from exc

        listed = self._git("worktree", "list", "--porcelain")
        for line in listed.splitlines():
            if not line.startswith("worktree "):
                continue
            registered = Path(line.removeprefix("worktree ")).resolve()
            if registered == worktree_path:
                return
        raise WorktreeIsolationError("path is not a registered managed worktree")

    def _ensure_clean_parent(self) -> None:
        status = self._git("status", "--porcelain=v1", "--untracked-files=all")
        dirty = []
        for line in status.splitlines():
            path = line[3:] if len(line) > 3 else line
            if path.startswith(".sarathi/worktrees/"):
                continue
            dirty.append(line)
        if dirty:
            raise WorktreeIsolationError("parent workspace must be clean before applying candidate worktree changes")

    def _intent_to_add_candidate_files(self, worktree_path: Path) -> None:
        output = self._git_in(worktree_path, "ls-files", "--others", "--exclude-standard", "-z")
        files = [file for file in output.split("\0") if file and not self._is_sarathi_path(file)]
        if files:
            self._git_in(worktree_path, "add", "-N", "--", *files)

    def _candidate_diff(self, worktree_path: Path) -> str:
        return self._git_in(worktree_path, "diff", "--binary", "HEAD", "--", ".", ":(exclude).sarathi")

    def _changed_files(self, worktree_path: Path) -> list[str]:
        output = self._git_in(worktree_path, "diff", "--name-only", "HEAD", "--", ".", ":(exclude).sarathi")
        return sorted(line.strip() for line in output.splitlines() if line.strip())

    @staticmethod
    def _is_sarathi_path(path: str) -> bool:
        return path == ".sarathi" or path.startswith(".sarathi/")

    @staticmethod
    def _safe_segment(value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
        return safe.strip(".-") or "node"
