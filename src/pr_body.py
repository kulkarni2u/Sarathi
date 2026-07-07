"""Assemble an audit-trail PR body from a completed (or in-flight) task.

This is the differentiator for the GitHub issue-as-queue workflow (see
``docs/IMPLEMENTATION-PLAN.md`` item 3.3): instead of a PR description the
author has to write by hand, Sarathi renders the actual phase log and
evidence it already recorded — a phase-by-phase table, whatever quality
signals were measured (never fabricated), evidence highlights, and a link
back to the source GitHub issue when the task carries one.

Two independent task shapes feed this module and are normalized internally
before rendering:

- **Engine shape** — a ``TaskContext``-style dict as written by
  ``PersistenceManager.save_task`` (``.sarathi/tasks/<id>.json``): keys
  ``task_id``, ``description``, ``phase_results`` (list of per-phase dicts
  with ``phase``, ``outcome``, ``decisions``, ``evidence``, ``artifacts``),
  plus optional ``budget_snapshot`` / ``metadata``.
- **Service shape** — a ``tasks`` row from ``src.storage.Storage`` (``id``,
  ``title``, ``description``, ``status``, ``metadata``) with a
  ``lifecycle_events`` list attached by the caller (see
  ``storage.list_events(task_id=...)``); events use the same dotted
  vocabulary the engine mirror and notifications module share
  (``phase.completed``, ``task.completed``, ``approval.requested``, ...).

Nothing here calls out to a model or fabricates data: every section is
either present because it was measured and stored, or it says so plainly.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

# Signal names quality gates in this repo are known to measure (see
# CLAUDE.md's "Quality Signals" section and src/runtime/judge_scoring.py).
# Anything else found alongside these in evidence/artifacts is ignored here
# rather than guessed at.
_QUALITY_SIGNAL_KEYS: tuple[str, ...] = (
    "cost_usd",
    "tokens",
    "total_tokens",
    "consumed_tokens",
    "max_total_tokens",
    "test_pass_rate",
    "blast_radius",
    "accuracy",
    "token_cost",
    "latency_ms",
    "rollback_triggered",
)

_FAIL_OUTCOMES = {"fail", "error", "escalate", "cancelled", "timed_out", "trust_gate_abort"}

_MAX_SCAN_DEPTH = 5


def _scan_for_signals(node: Any, out: dict[str, Any], *, depth: int = 0) -> None:
    """Recursively (bounded) collect known quality-signal keys from ``node``.

    Only records the first value seen for a given key — later duplicates
    (e.g. from earlier phases) do not overwrite it. Never fabricates a
    value: a key absent everywhere in the evidence simply never appears in
    the output.
    """
    if depth > _MAX_SCAN_DEPTH or not isinstance(node, Mapping):
        return
    for key, value in node.items():
        if (
            key in _QUALITY_SIGNAL_KEYS
            and key not in out
            and value is not None
            and isinstance(value, (int, float, bool, str))
        ):
            out[key] = value
        if isinstance(value, Mapping):
            _scan_for_signals(value, out, depth=depth + 1)


def _first_of(node: Any, key: str, out: dict[str, Any], *, depth: int = 0) -> None:
    """Record the first dict/list found under ``key`` anywhere in ``node``."""
    if key in out or depth > _MAX_SCAN_DEPTH or not isinstance(node, Mapping):
        return
    for k, value in node.items():
        if k == key and isinstance(value, (Mapping, list)) and value:
            out[key] = value
            return
        if isinstance(value, Mapping):
            _first_of(value, key, out, depth=depth + 1)
            if key in out:
                return


def _issue_reference(container: Mapping[str, Any]) -> dict[str, Any] | None:
    """Pull a GitHub issue reference out of a task-like dict, however nested.

    Task drafts created via ``src/service/intake.py`` store it at
    ``metadata.github_issue``; callers assembling a fabricated engine-style
    task for testing may place it at the top level instead. Both work.
    """
    candidates: list[Any] = [
        container.get("github_issue"),
        (container.get("metadata") or {}).get("github_issue") if isinstance(container.get("metadata"), Mapping) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, Mapping) and (candidate.get("url") or candidate.get("number") is not None):
            return dict(candidate)
    return None


class _NormalizedPhase:
    __slots__ = ("phase", "status", "decisions")

    def __init__(self, phase: str, status: str, decisions: Sequence[str]):
        self.phase = phase
        self.status = status
        self.decisions = list(decisions)


class _NormalizedTask:
    __slots__ = (
        "description",
        "outcome",
        "phases",
        "quality_signals",
        "verification_summary",
        "review_summary",
        "severity_counts",
        "judge_scorecard",
        "issue",
    )

    def __init__(self) -> None:
        self.description: str = ""
        self.outcome: str = "unknown"
        self.phases: list[_NormalizedPhase] = []
        self.quality_signals: dict[str, Any] = {}
        self.verification_summary: dict[str, Any] | None = None
        self.review_summary: dict[str, Any] | None = None
        self.severity_counts: dict[str, Any] | None = None
        self.judge_scorecard: list[dict[str, Any]] | None = None
        self.issue: dict[str, Any] | None = None


def _normalize_engine_task(data: Mapping[str, Any]) -> _NormalizedTask:
    normalized = _NormalizedTask()
    normalized.description = str(data.get("description") or data.get("task_id") or "Untitled task")
    normalized.issue = _issue_reference(data)

    phase_results = data.get("phase_results")
    phase_results = phase_results if isinstance(phase_results, list) else []

    highlights: dict[str, Any] = {}
    for entry in phase_results:
        if not isinstance(entry, Mapping):
            continue
        phase_name = str(entry.get("phase") or "?")
        status = str(entry.get("outcome") or "unknown")
        decisions = entry.get("decisions")
        normalized.phases.append(
            _NormalizedPhase(phase_name, status, decisions if isinstance(decisions, list) else [])
        )
        evidence = entry.get("evidence") if isinstance(entry.get("evidence"), Mapping) else {}
        artifacts = entry.get("artifacts") if isinstance(entry.get("artifacts"), Mapping) else {}
        _scan_for_signals(evidence, normalized.quality_signals)
        _scan_for_signals(artifacts, normalized.quality_signals)
        _first_of(evidence, "verification_summary", highlights)
        _first_of(artifacts, "verification_summary", highlights)
        _first_of(evidence, "review_summary", highlights)
        _first_of(evidence, "severity_counts", highlights)
        _first_of(artifacts, "judge_scorecard", highlights)
        _first_of(evidence, "judge_scorecard", highlights)

    budget_snapshot = data.get("budget_snapshot")
    if isinstance(budget_snapshot, Mapping):
        _scan_for_signals(budget_snapshot, normalized.quality_signals)

    normalized.verification_summary = highlights.get("verification_summary") if isinstance(highlights.get("verification_summary"), Mapping) else None
    normalized.review_summary = highlights.get("review_summary") if isinstance(highlights.get("review_summary"), Mapping) else None
    normalized.severity_counts = highlights.get("severity_counts") if isinstance(highlights.get("severity_counts"), Mapping) else None
    normalized.judge_scorecard = highlights.get("judge_scorecard") if isinstance(highlights.get("judge_scorecard"), list) else None

    if phase_results and any(
        isinstance(entry, Mapping) and entry.get("outcome") in _FAIL_OUTCOMES for entry in phase_results
    ):
        normalized.outcome = "failed"
    elif phase_results:
        last = phase_results[-1]
        if isinstance(last, Mapping) and str(last.get("phase")) == "learn" and last.get("outcome") == "pass":
            normalized.outcome = "completed"
        else:
            normalized.outcome = "in_progress"

    return normalized


def _normalize_service_task(data: Mapping[str, Any]) -> _NormalizedTask:
    normalized = _NormalizedTask()
    normalized.description = str(data.get("description") or data.get("title") or data.get("id") or "Untitled task")
    normalized.outcome = str(data.get("status") or "unknown")
    normalized.issue = _issue_reference(data)

    events = data.get("lifecycle_events")
    events = events if isinstance(events, list) else []

    highlights: dict[str, Any] = {}
    phase_order: list[str] = []
    phase_status: dict[str, str] = {}
    phase_decisions: dict[str, list[str]] = {}
    for event in events:
        if not isinstance(event, Mapping):
            continue
        event_type = str(event.get("event_type") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        _scan_for_signals(payload, normalized.quality_signals)
        _first_of(payload, "verification_summary", highlights)
        _first_of(payload, "review_summary", highlights)
        _first_of(payload, "severity_counts", highlights)
        _first_of(payload, "judge_scorecard", highlights)

        if not event_type.startswith("phase."):
            continue
        phase_name = str(payload.get("phase") or "?")
        status = str(payload.get("status") or event_type.rsplit(".", 1)[-1])
        if phase_name not in phase_status:
            phase_order.append(phase_name)
        phase_status[phase_name] = status
        decisions = payload.get("decisions")
        if isinstance(decisions, list):
            phase_decisions[phase_name] = [str(item) for item in decisions]

    for phase_name in phase_order:
        normalized.phases.append(
            _NormalizedPhase(phase_name, phase_status[phase_name], phase_decisions.get(phase_name, []))
        )

    metadata = data.get("metadata")
    if isinstance(metadata, Mapping):
        _scan_for_signals(metadata, normalized.quality_signals)

    normalized.verification_summary = highlights.get("verification_summary") if isinstance(highlights.get("verification_summary"), Mapping) else None
    normalized.review_summary = highlights.get("review_summary") if isinstance(highlights.get("review_summary"), Mapping) else None
    normalized.severity_counts = highlights.get("severity_counts") if isinstance(highlights.get("severity_counts"), Mapping) else None
    normalized.judge_scorecard = highlights.get("judge_scorecard") if isinstance(highlights.get("judge_scorecard"), list) else None

    return normalized


def _normalize(task_like: Mapping[str, Any]) -> _NormalizedTask:
    if isinstance(task_like.get("phase_results"), list):
        return _normalize_engine_task(task_like)
    return _normalize_service_task(task_like)


def _render_phase_table(phases: list[_NormalizedPhase]) -> list[str]:
    if not phases:
        return ["_No phase log was recorded for this run._"]
    lines = ["| Phase | Status | Key Decisions |", "| --- | --- | --- |"]
    for phase in phases:
        decisions = "; ".join(phase.decisions) if phase.decisions else "-"
        decisions = decisions.replace("|", "\\|")
        lines.append(f"| {phase.phase} | {phase.status} | {decisions} |")
    return lines


def _render_quality_signals(signals: Mapping[str, Any]) -> list[str]:
    if not signals:
        return ["_No quality signals were recorded for this run._"]
    lines = []
    for key in _QUALITY_SIGNAL_KEYS:
        if key in signals:
            lines.append(f"- **{key}:** {signals[key]}")
    return lines


def _render_evidence(normalized: _NormalizedTask) -> list[str]:
    lines: list[str] = []
    if normalized.verification_summary:
        summary = normalized.verification_summary
        executed = summary.get("command_executed")
        succeeded = summary.get("command_succeeded")
        lines.append(
            "- **Verification:** "
            + (
                f"command executed, succeeded={succeeded}"
                if executed
                else "no test command declared/executed"
            )
        )
    if normalized.review_summary:
        lines.append(f"- **Review summary:** {normalized.review_summary}")
    if normalized.severity_counts:
        lines.append(f"- **Review severity counts:** {normalized.severity_counts}")
    if normalized.judge_scorecard:
        lines.append("- **Judge scorecard:**")
        lines.append("")
        lines.append("  | Branch | Provider | Weighted Score |")
        lines.append("  | --- | --- | --- |")
        for entry in normalized.judge_scorecard:
            if not isinstance(entry, Mapping):
                continue
            lines.append(
                f"  | {entry.get('branch', '-')} | {entry.get('provider', '-')} | {entry.get('weighted_score', '-')} |"
            )
    if not lines:
        lines.append("_No additional evidence was recorded for this run._")
    return lines


def build_pr_body(task_like: Mapping[str, Any]) -> str:
    """Render an audit-trail PR body markdown string from a task-like dict.

    Accepts either an engine ``TaskContext``-style dict (``phase_results``
    present) or a service task dict with a ``lifecycle_events`` list
    attached by the caller. See the module docstring for both shapes.
    """
    normalized = _normalize(task_like)

    sections: list[str] = []
    sections.append("## Summary")
    sections.append("")
    sections.append(normalized.description)
    sections.append("")
    sections.append(f"**Outcome:** {normalized.outcome}")
    sections.append("")
    sections.append("## Phases")
    sections.append("")
    sections.extend(_render_phase_table(normalized.phases))
    sections.append("")
    sections.append("## Quality Signals")
    sections.append("")
    sections.extend(_render_quality_signals(normalized.quality_signals))
    sections.append("")
    sections.append("## Evidence")
    sections.append("")
    sections.extend(_render_evidence(normalized))

    if normalized.issue:
        url = normalized.issue.get("url")
        number = normalized.issue.get("number")
        sections.append("")
        sections.append("---")
        if url:
            label = f"#{number}" if number is not None else url
            sections.append(f"Source issue: [{label}]({url})")
        elif number is not None:
            sections.append(f"Source issue: #{number}")

    return "\n".join(sections).rstrip() + "\n"


def create_pr_if_gh_available(
    workspace_root: str | Path,
    title: str,
    body: str,
    branch: str | None = None,
    *,
    runner: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> dict[str, Any] | None:
    """Best-effort ``gh pr create`` shell-out. Returns ``None`` when skipped.

    Optional by design: this environment (and many CI/agent sandboxes) has
    no ``gh`` on PATH, so callers must treat ``None`` as "not attempted,"
    not as an error. ``runner`` and ``which`` are injectable so tests never
    need a real ``gh`` binary.
    """
    which = which or shutil.which
    if which("gh") is None:
        return None
    runner = runner or subprocess.run

    handle = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    try:
        handle.write(body)
        handle.close()
        command = ["gh", "pr", "create", "--title", title, "--body-file", handle.name]
        if branch:
            command.extend(["--head", branch])
        result = runner(command, cwd=str(workspace_root), capture_output=True, text=True, check=False)
        return {
            "command": command,
            "returncode": getattr(result, "returncode", None),
            "stdout": getattr(result, "stdout", ""),
            "stderr": getattr(result, "stderr", ""),
        }
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
