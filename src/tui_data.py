"""Data access for the Sarathi terminal dashboard.

Kept free of textual imports so the dashboard's data layer can be tested
headlessly and reused by other frontends (service, MCP).
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

try:
    from .engine import Engine, PersistenceManager, TaskContext
    from .evolve import Evolver, PolicyProposal, ProposalReviewStore
except ImportError:
    # Support direct execution via sarathi.py, which prepends src/ to sys.path.
    from engine import Engine, PersistenceManager, TaskContext
    from evolve import Evolver, PolicyProposal, ProposalReviewStore


def default_persistence(storage_path: str | None = None) -> PersistenceManager:
    return PersistenceManager(storage_path)


def _cli():
    try:
        from . import cli
    except ImportError:
        import cli
    return cli


def task_summaries(persistence: PersistenceManager) -> list[dict[str, Any]]:
    """List persisted tasks, newest first, reading the raw JSON files.

    Reads the files directly instead of `load_task` so the list view stays
    cheap and tolerant of records written by newer/older engine versions.
    """
    summaries: list[dict[str, Any]] = []
    for task_id in persistence.list_tasks():
        path = persistence.storage_path / f"{task_id}.json"
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        results = data.get("phase_results") or []
        last = results[-1] if results else {}
        summaries.append(
            {
                "task_id": data.get("task_id", task_id),
                "description": data.get("description", ""),
                "complexity": data.get("complexity", ""),
                "current_phase": data.get("current_phase") or "Completed",
                "phases": len(results),
                "last_phase": last.get("phase", ""),
                "last_outcome": last.get("outcome", ""),
                "last_updated": data.get("last_updated", ""),
            }
        )
    summaries.sort(key=lambda item: item["last_updated"], reverse=True)
    return summaries


def status_snapshot(persistence: PersistenceManager, task_id: str) -> str | None:
    """Compact supervision snapshot, identical to `sarathi status <task_id>`."""
    task = persistence.load_task(task_id)
    if task is None:
        return None
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _cli()._print_task_status(task)
    return buffer.getvalue().rstrip()


def phase_rows(persistence: PersistenceManager, task_id: str) -> list[dict[str, Any]]:
    """Per-phase result rows for a persisted task."""
    task = persistence.load_task(task_id)
    if task is None:
        return []
    agent_name = _cli().phase_agent_name
    return [
        {
            "phase": result.phase.value,
            "agent": agent_name(result),
            "outcome": result.outcome,
            "iterations": result.iterations,
            "error": result.error or "",
        }
        for result in task.phase_results
    ]


def phase_log_tail(
    persistence: PersistenceManager, task_id: str, max_lines: int = 200
) -> list[str]:
    """Tail of the phase transition log written by the engine."""
    log_file = persistence.storage_path / f"{task_id}_phases.log"
    if not log_file.exists():
        return []
    try:
        lines = log_file.read_text().splitlines()
    except OSError:
        return []
    return lines[-max_lines:]


def format_log_line(line: str) -> str:
    """Render a phase-log JSON entry as a single readable line."""
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return line
    if not isinstance(entry, dict):
        return line
    timestamp = str(entry.get("timestamp", ""))[:19].replace("T", " ")
    parts = [part for part in (timestamp, entry.get("phase"), entry.get("status")) if part]
    return "  ".join(str(part) for part in parts) or line


def learning_records(persistence: PersistenceManager) -> list[dict[str, Any]]:
    """Collect learning records persisted in Learn phase artifacts."""
    records: list[dict[str, Any]] = []
    for task_id in persistence.list_tasks():
        task = persistence.load_task(task_id)
        if task is None:
            continue
        for result in task.phase_results:
            record = result.artifacts.get("learning_record")
            if isinstance(record, dict):
                records.append(record)
    return records


def load_proposals(persistence: PersistenceManager) -> list[PolicyProposal]:
    """Policy proposals generated from persisted learnings."""
    return Evolver().generate_policy_proposals(learning_records=learning_records(persistence))


def decide_proposal(
    proposal: PolicyProposal,
    *,
    accept: bool,
    policy_pack: str | Path,
    reason: str | None = None,
) -> dict[str, Any]:
    """Accept a proposal into the policy pack, or record a rejection."""
    store = ProposalReviewStore(policy_pack)
    if accept:
        return store.accept(proposal)
    return store.reject(proposal, reason=reason)


def resume_task(
    persistence: PersistenceManager, task_id: str, policy_pack: str | Path
) -> TaskContext:
    """Resume a persisted task through the engine."""
    task = persistence.load_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")
    engine = Engine(policy_pack_path=str(policy_pack), enforce_preflight=True)
    engine.persistence = persistence
    return engine.resume_task(task)
