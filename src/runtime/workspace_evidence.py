"""Measured workspace evidence: snapshot, diff, and reconcile against provider claims.

Sarathi dispatches work to coding-agent CLIs that mutate a workspace, but
provider responses report only what the provider *claims* it did
(``success``, ``outputs.files_changed``, ...). This module adds a measured
counterpart: a `git status` snapshot taken before and after a dispatch, a
diff between them, and a reconciliation against whatever the provider
claimed changed.

Design principle: never fabricate signals. Every git call is wrapped so a
measurement failure degrades to ``measured: False`` with a ``reason`` —
it never raises and never silently reports false agreement.
"""

from __future__ import annotations

import subprocess
from typing import Any

try:
    from .contracts import DispatchRequest, DispatchResponse
except ImportError:
    from runtime.contracts import DispatchRequest, DispatchResponse


_SNAPSHOT_TIMEOUT_SECONDS = 10
_DIFF_TIMEOUT_SECONDS = 10


def snapshot_workspace(workspace_root: str) -> dict[str, Any]:
    """Capture a porcelain `git status` snapshot of ``workspace_root``.

    Returns ``{"measured": True, "status": {path: state, ...}}`` on success,
    where ``state`` is the two-character porcelain status code (e.g. " M",
    "??", "A ") for that path.

    On any failure (not a git repo, git missing, timeout, ...) returns
    ``{"measured": False, "reason": "<...>"}`` without raising.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", workspace_root, "status", "--porcelain=v1", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=_SNAPSHOT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return {"measured": False, "reason": "git_unavailable"}
    except subprocess.TimeoutExpired:
        return {"measured": False, "reason": "error: git status timed out"}
    except OSError as exc:
        return {"measured": False, "reason": f"error: {exc}"}

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        if "not a git repository" in stderr.lower():
            return {"measured": False, "reason": "not_a_git_repo"}
        return {"measured": False, "reason": f"error: {stderr or f'git status exited {completed.returncode}'}"}

    status: dict[str, str] = {}
    for line in (completed.stdout or "").splitlines():
        if not line:
            continue
        # Porcelain v1 lines: "XY <path>" (and "XY <old> -> <new>" for renames).
        # XY is always 2 chars, followed by a space, then the path(s).
        code = line[:2]
        path_part = line[3:]
        if " -> " in path_part:
            # Track both sides of a rename so either path's state change is visible.
            old_path, new_path = path_part.split(" -> ", 1)
            status[old_path] = code
            status[new_path] = code
        else:
            status[path_part] = code

    return {"measured": True, "status": status}


def measure_workspace_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare two `snapshot_workspace` results and report what changed.

    A path counts as changed if it appears in only one snapshot, or if its
    porcelain status code differs between snapshots (covers added, modified,
    deleted, and newly-untracked files).

    Returns ``{"measured": True, "files_changed": [...], "change_count": N}``
    when both snapshots were measured, otherwise
    ``{"measured": False, "files_changed": [], "change_count": 0, "reason": "..."}``.
    """
    if not before.get("measured") or not after.get("measured"):
        reasons = []
        if not before.get("measured"):
            reasons.append(f"before: {before.get('reason', 'unmeasured')}")
        if not after.get("measured"):
            reasons.append(f"after: {after.get('reason', 'unmeasured')}")
        return {
            "measured": False,
            "files_changed": [],
            "change_count": 0,
            "reason": "; ".join(reasons),
        }

    before_status: dict[str, str] = before.get("status", {})
    after_status: dict[str, str] = after.get("status", {})

    changed: set[str] = set()
    for path in set(before_status) | set(after_status):
        if before_status.get(path) != after_status.get(path):
            changed.add(path)

    files_changed = sorted(changed)
    return {
        "measured": True,
        "files_changed": files_changed,
        "change_count": len(files_changed),
    }


def reconcile_claimed_changes(delta: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    """Compare measured file changes against whatever the provider claimed.

    Looks for claimed file lists in ``outputs["files_changed"]`` and
    ``outputs["work_unit_result"]["files_changed"]`` (defensive about types —
    non-list/non-string entries are ignored).

    Returns:
        - ``divergence is None`` with a ``reason`` when reconciliation is not
          possible (delta unmeasured, or no claim was made at all) — this
          avoids reporting false agreement.
        - Otherwise ``{"claimed_files": [...], "measured_files": [...],
          "claimed_but_unchanged": [...], "changed_but_unclaimed": [...],
          "divergence": bool}``.
    """
    claimed_files = _extract_claimed_files(outputs)

    if not delta.get("measured"):
        return {
            "claimed_files": claimed_files,
            "measured_files": [],
            "claimed_but_unchanged": [],
            "changed_but_unclaimed": [],
            "divergence": None,
            "reason": delta.get("reason", "workspace delta not measured"),
        }

    measured_files: list[str] = list(delta.get("files_changed", []))

    if not claimed_files:
        return {
            "claimed_files": [],
            "measured_files": measured_files,
            "claimed_but_unchanged": [],
            "changed_but_unclaimed": [],
            "divergence": None,
            "reason": "no claimed file changes to reconcile",
        }

    measured_set = set(measured_files)
    claimed_set = set(claimed_files)

    claimed_but_unchanged = sorted(claimed_set - measured_set)
    changed_but_unclaimed = sorted(measured_set - claimed_set)

    return {
        "claimed_files": claimed_files,
        "measured_files": measured_files,
        "claimed_but_unchanged": claimed_but_unchanged,
        "changed_but_unclaimed": changed_but_unclaimed,
        "divergence": bool(claimed_but_unchanged or changed_but_unclaimed),
    }


def _extract_claimed_files(outputs: dict[str, Any]) -> list[str]:
    """Pull a flat, deduped, ordered list of claimed file paths out of ``outputs``."""
    candidates: list[Any] = []
    if isinstance(outputs, dict):
        candidates.append(outputs.get("files_changed"))
        work_unit = outputs.get("work_unit_result")
        if isinstance(work_unit, dict):
            candidates.append(work_unit.get("files_changed"))

    claimed: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, list):
            continue
        for item in candidate:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if value and value not in seen:
                seen.add(value)
                claimed.append(value)
    return claimed


def _looks_like_implementation_work(request: DispatchRequest) -> bool:
    """True when the dispatch is expected to mutate the workspace."""
    if request.phase == "Build":
        return True
    return request.constraints.get("purpose") == "child_task_execution"


def attach_workspace_evidence(
    response: DispatchResponse,
    before: dict[str, Any],
    workspace_root: str,
    request: DispatchRequest,
    *,
    logger: Any = None,
) -> DispatchResponse:
    """Measure the workspace delta since ``before`` and attach it to ``response``.

    Adds (additively, never overwriting an existing measurement):
        - ``response.evidence["workspace_delta"]``
        - ``response.evidence["claim_reconciliation"]``
        - ``response.evidence["workspace_unchanged_on_success"]`` when the
          dispatch claims success on implementation work but nothing in the
          workspace measurably changed.

    Never raises and never flips ``response.success`` — evidence stays evidence.
    """
    if "workspace_delta" in response.evidence:
        # Already measured by an earlier layer (e.g. the CLI bridge already
        # attached evidence before an SDK adapter's CLI-fallback path ran).
        return response

    after = snapshot_workspace(workspace_root)
    delta = measure_workspace_delta(before, after)
    reconciliation = reconcile_claimed_changes(delta, response.outputs if isinstance(response.outputs, dict) else {})

    response.evidence["workspace_delta"] = delta
    response.evidence["claim_reconciliation"] = reconciliation

    if (
        response.success
        and delta.get("measured")
        and delta.get("change_count") == 0
        and _looks_like_implementation_work(request)
    ):
        response.evidence["workspace_unchanged_on_success"] = True
        if logger is not None:
            logger.warning(
                "Dispatch %s reported success for %s but the workspace at %s shows no measured "
                "file changes.",
                request.task_id,
                request.phase,
                workspace_root,
            )

    return response


def collect_review_context(workspace_root: str, max_diff_bytes: int = 30000) -> dict[str, Any]:
    """Collect a real ``git diff`` for the Review phase to evaluate.

    Runs ``git -C <workspace_root> diff HEAD --stat`` and
    ``git -C <workspace_root> diff HEAD`` against the working tree, truncating
    the diff at ``max_diff_bytes`` (on a line boundary, with a trailing
    marker) so large diffs stay bounded. Untracked files are pulled from
    :func:`snapshot_workspace`.

    Returns ``{"measured": True, "diff_stat": str, "diff": str,
    "diff_truncated": bool, "untracked_files": [...]}`` on success, or
    ``{"measured": False, "reason": "..."}`` on any failure (not a git repo,
    git missing, timeout, ...) without raising.
    """
    try:
        stat_completed = subprocess.run(
            ["git", "-C", workspace_root, "diff", "HEAD", "--stat"],
            capture_output=True,
            text=True,
            timeout=_DIFF_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return {"measured": False, "reason": "git_unavailable"}
    except subprocess.TimeoutExpired:
        return {"measured": False, "reason": "error: git diff --stat timed out"}
    except OSError as exc:
        return {"measured": False, "reason": f"error: {exc}"}

    if stat_completed.returncode != 0:
        stderr = (stat_completed.stderr or "").strip()
        if "not a git repository" in stderr.lower():
            return {"measured": False, "reason": "not_a_git_repo"}
        return {"measured": False, "reason": f"error: {stderr or f'git diff --stat exited {stat_completed.returncode}'}"}

    try:
        diff_completed = subprocess.run(
            ["git", "-C", workspace_root, "diff", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_DIFF_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return {"measured": False, "reason": "git_unavailable"}
    except subprocess.TimeoutExpired:
        return {"measured": False, "reason": "error: git diff timed out"}
    except OSError as exc:
        return {"measured": False, "reason": f"error: {exc}"}

    if diff_completed.returncode != 0:
        stderr = (diff_completed.stderr or "").strip()
        if "not a git repository" in stderr.lower():
            return {"measured": False, "reason": "not_a_git_repo"}
        return {"measured": False, "reason": f"error: {stderr or f'git diff exited {diff_completed.returncode}'}"}

    diff_text = diff_completed.stdout or ""
    diff, truncated = _truncate_diff(diff_text, max_diff_bytes)

    snapshot = snapshot_workspace(workspace_root)
    untracked_files: list[str] = []
    if snapshot.get("measured"):
        untracked_files = sorted(
            path for path, code in snapshot.get("status", {}).items() if code == "??"
        )

    return {
        "measured": True,
        "diff_stat": stat_completed.stdout or "",
        "diff": diff,
        "diff_truncated": truncated,
        "untracked_files": untracked_files,
    }


def _truncate_diff(diff_text: str, max_diff_bytes: int) -> tuple[str, bool]:
    """Truncate ``diff_text`` to at most ``max_diff_bytes`` bytes on a line boundary.

    Returns ``(diff, truncated)``. When truncation occurs, a trailing marker
    line is appended (counted separately from ``max_diff_bytes``).
    """
    encoded = diff_text.encode("utf-8")
    if len(encoded) <= max_diff_bytes:
        return diff_text, False

    truncated_bytes = encoded[:max_diff_bytes]
    # Back off to the last newline so we don't split a line mid-way.
    last_newline = truncated_bytes.rfind(b"\n")
    if last_newline > 0:
        truncated_bytes = truncated_bytes[:last_newline]

    truncated_text = truncated_bytes.decode("utf-8", errors="ignore")
    marker = f"\n... [diff truncated at {max_diff_bytes} bytes]"
    return truncated_text + marker, True
