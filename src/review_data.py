"""Diff review data layer for the TUI's DiffReviewScreen.

Loads a task's build diff (preferring the real unified diff recorded by the
Review phase, falling back to a live `git diff` against the workspace) and
parses it into per-file, per-hunk records. Also records human approve/reject
decisions onto the task's phase history so they persist across restarts and
become visible to the Review phase on a later run (`find_diff_review`,
consumed by `src/phases/review.py`).

Kept free of engine imports at module scope (only used for typing under
`TYPE_CHECKING`) so this module can be imported from `src/phases/review.py`
without re-entering `src/engine.py` mid-initialization the way `src/engine.py`
imports the phase handlers — see the `TYPE_CHECKING` guard below and the
identical pattern used elsewhere in `src/phases/`.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .engine import PersistenceManager, TaskContext


_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
_DIFF_TIMEOUT_SECONDS = 10
_VALID_DECISIONS = {"approved", "rejected"}


@dataclass
class DiffLine:
    """One line inside a hunk, including its raw `+`/`-`/` ` prefix in `text`."""

    kind: str  # "add" | "del" | "context" | "meta"
    text: str


@dataclass
class DiffHunk:
    """One `@@ -a,b +c,d @@` hunk and the lines it contains."""

    header: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class FileDiff:
    """One file's change within a diff: its status and parsed hunks."""

    path: str
    status: str  # "added" | "modified" | "deleted" | "renamed"
    old_path: str | None = None
    hunks: list[DiffHunk] = field(default_factory=list)
    binary: bool = False


def parse_unified_diff(diff_text: str) -> list[FileDiff]:
    """Parse unified-diff text (as produced by `git diff`) into `FileDiff` records.

    Pure and defensive: unrecognized or malformed input around a `diff --git`
    block is skipped rather than raising, and non-diff text (or empty text)
    simply yields an empty list.
    """
    if not diff_text:
        return []

    lines = diff_text.splitlines()
    files: list[FileDiff] = []
    i = 0
    n = len(lines)

    while i < n:
        match = _DIFF_GIT_RE.match(lines[i])
        if not match:
            i += 1
            continue

        old_path = match.group(1)
        new_path = match.group(2)
        i += 1

        status = "modified"
        binary = False
        renamed = False
        old_side: str | None = old_path
        new_side: str | None = new_path

        # Consume header/meta lines until a hunk, the next file, or EOF.
        while i < n and not lines[i].startswith("@@") and not lines[i].startswith("diff --git "):
            line = lines[i]
            if line.startswith("new file mode"):
                status = "added"
            elif line.startswith("deleted file mode"):
                status = "deleted"
            elif line.startswith("rename from "):
                renamed = True
                old_side = line[len("rename from "):].strip()
            elif line.startswith("rename to "):
                renamed = True
                new_side = line[len("rename to "):].strip()
            elif line.startswith("Binary files") or line.startswith("GIT binary patch"):
                binary = True
            elif line.startswith("--- "):
                value = line[4:].split("\t", 1)[0]
                old_side = None if value.strip() == "/dev/null" else _strip_ab_prefix(value)
            elif line.startswith("+++ "):
                value = line[4:].split("\t", 1)[0]
                new_side = None if value.strip() == "/dev/null" else _strip_ab_prefix(value)
            i += 1

        if status == "modified" and new_side is None:
            status = "deleted"
        elif status == "modified" and old_side is None:
            status = "added"
        elif renamed:
            status = "renamed"

        final_path = new_side or old_side or new_path
        final_old_path = old_side if (old_side is not None and old_side != final_path) else None

        hunks: list[DiffHunk] = []
        while i < n and lines[i].startswith("@@"):
            hunk_match = _HUNK_HEADER_RE.match(lines[i])
            if not hunk_match:
                # Unparseable hunk header — skip the line defensively rather
                # than raising, and let the outer loop reassess.
                i += 1
                continue
            header = lines[i]
            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2)) if hunk_match.group(2) else 1
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4)) if hunk_match.group(4) else 1
            i += 1

            hunk_lines: list[DiffLine] = []
            while i < n and lines[i][:1] in (" ", "+", "-", "\\"):
                raw = lines[i]
                if raw.startswith("+"):
                    kind = "add"
                elif raw.startswith("-"):
                    kind = "del"
                elif raw.startswith("\\"):
                    kind = "meta"
                else:
                    kind = "context"
                hunk_lines.append(DiffLine(kind=kind, text=raw))
                i += 1

            hunks.append(
                DiffHunk(
                    header=header,
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    lines=hunk_lines,
                )
            )

        files.append(
            FileDiff(
                path=final_path,
                status=status,
                old_path=final_old_path,
                hunks=hunks,
                binary=binary,
            )
        )

    return files


def _strip_ab_prefix(path: str) -> str:
    value = path.strip()
    if value.startswith("a/") or value.startswith("b/"):
        return value[2:]
    return value


def load_task_diff(task: "TaskContext", workspace_root: str | None = None) -> list[FileDiff]:
    """Load a task's build diff as `FileDiff` records.

    Source priority:
      1. The real unified diff recorded by the Review phase (`git diff HEAD`,
         captured by `collect_review_context` into
         `artifacts["review_inputs"]["workspace_diff"]["diff"]`), searched
         across the task's phase history most-recent-first.
      2. A live `git diff --cached` + `git diff` against `workspace_root`
         (falls back to the current directory) — used when the task hasn't
         reached Review yet, or no recorded diff is present.

    Returns `[]` (never raises) when neither source yields a diff, e.g. the
    workspace isn't a git repo.
    """
    diff_text = _recorded_diff_text(task)
    if diff_text is None:
        diff_text = _live_diff_text(workspace_root or os.getcwd())
    if not diff_text:
        return []
    return parse_unified_diff(diff_text)


def _recorded_diff_text(task: "TaskContext") -> str | None:
    phase_results = getattr(task, "phase_results", None) or []
    for pr in reversed(phase_results):
        artifacts = getattr(pr, "artifacts", None)
        if not isinstance(artifacts, dict):
            continue
        review_inputs = artifacts.get("review_inputs")
        if isinstance(review_inputs, dict):
            workspace_diff = review_inputs.get("workspace_diff")
            diff_text = _diff_text_from(workspace_diff)
            if diff_text is not None:
                return diff_text
        # Defensive: a `workspace_diff` attached directly to the artifacts,
        # not nested under `review_inputs`.
        diff_text = _diff_text_from(artifacts.get("workspace_diff"))
        if diff_text is not None:
            return diff_text
    return None


def _diff_text_from(workspace_diff: Any) -> str | None:
    if not isinstance(workspace_diff, dict):
        return None
    diff_text = workspace_diff.get("diff")
    if isinstance(diff_text, str) and diff_text.strip():
        return diff_text
    return None


def _live_diff_text(workspace_root: str) -> str | None:
    try:
        staged = subprocess.run(
            ["git", "-C", workspace_root, "diff", "--cached"],
            capture_output=True,
            text=True,
            timeout=_DIFF_TIMEOUT_SECONDS,
            check=False,
        )
        unstaged = subprocess.run(
            ["git", "-C", workspace_root, "diff"],
            capture_output=True,
            text=True,
            timeout=_DIFF_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if staged.returncode != 0 and unstaged.returncode != 0:
        return None
    combined = (staged.stdout or "") + (unstaged.stdout or "")
    return combined or None


def record_review_decision(
    persistence: "PersistenceManager",
    task_id: str,
    path: str,
    decision: str,
    hunk_index: int | None = None,
    note: str | None = None,
) -> "TaskContext":
    """Record a file (or hunk) review decision, persisted onto the task.

    Mirrors `Engine.record_approval`'s persistence pattern: mutate the
    artifacts of the task's most recent phase result (`artifacts["diff_review"]
    ["decisions"]`) and save the task via `persistence`. Re-deciding the same
    `(path, hunk_index)` replaces the earlier entry rather than appending a
    duplicate.

    The Review phase (`src/phases/review.py`, via `find_diff_review`) reads
    this back out of phase history on a later run — searching most-recent
    first — so a decision recorded here is visible to the reviewer on resume
    even when it lands on a pre-Review phase result (e.g. the task is
    currently paused at Build). Works just as well for an already-terminal
    task: the decision is still recorded for audit even though no resume
    will read it.

    Raises `ValueError` for an unknown decision, a missing task, or a task
    with no phase history to attach the decision to.
    """
    if decision not in _VALID_DECISIONS:
        raise ValueError(f"decision must be one of {sorted(_VALID_DECISIONS)}, got {decision!r}")
    task = persistence.load_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")
    if not task.phase_results:
        raise ValueError(f"Task {task_id} has no phase history to record a review decision against.")

    last_result = task.phase_results[-1]
    diff_review = last_result.artifacts.setdefault("diff_review", {"decisions": []})
    decisions = diff_review.setdefault("decisions", [])
    decisions[:] = [
        entry
        for entry in decisions
        if not (entry.get("path") == path and entry.get("hunk_index") == hunk_index)
    ]
    decisions.append(
        {
            "path": path,
            "hunk_index": hunk_index,
            "decision": decision,
            "note": note,
            "decided_at": datetime.now().isoformat(),
        }
    )
    persistence.save_task(task)
    return task


def find_diff_review(task: "TaskContext") -> dict[str, Any]:
    """Most recent non-empty `diff_review` artifact in the task's phase history.

    Searched most-recent-first (same order `record_review_decision` writes
    to), so a decision recorded while the task was paused mid-lifecycle is
    still found once later phases have appended their own results. Returns
    `{}` when no decisions have been recorded.
    """
    phase_results = getattr(task, "phase_results", None) or []
    for pr in reversed(phase_results):
        artifacts = getattr(pr, "artifacts", None)
        if not isinstance(artifacts, dict):
            continue
        diff_review = artifacts.get("diff_review")
        if isinstance(diff_review, dict) and diff_review.get("decisions"):
            return diff_review
    return {}


def rejected_paths(diff_review: dict[str, Any]) -> list[str]:
    """Sorted, deduped file paths with a `rejected` decision (any hunk)."""
    paths: set[str] = set()
    for entry in diff_review.get("decisions", []) if isinstance(diff_review, dict) else []:
        if isinstance(entry, dict) and entry.get("decision") == "rejected":
            path = entry.get("path")
            if isinstance(path, str) and path:
                paths.add(path)
    return sorted(paths)
