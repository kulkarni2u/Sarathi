"""Data access for the Sarathi terminal dashboard.

Kept free of textual imports so the dashboard's data layer can be tested
headlessly and reused by other frontends (service, MCP).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
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


def start_task(
    persistence: PersistenceManager, description: str, policy_pack: str | Path
) -> TaskContext:
    """Create a new task from a description and run it through the lifecycle.

    Mirrors `sarathi run` with auto-detected complexity; raises RuntimeError
    when preflight validation blocks execution.
    """
    engine = Engine(policy_pack_path=str(policy_pack), enforce_preflight=True)
    engine.persistence = persistence
    task = TaskContext(
        task_id=engine.generate_task_id(description),
        description=description,
        complexity=_cli().calculate_complexity(description),
    )
    preflight = engine.preflight_validate_policy(task.task_id)
    task.preflight_validation = preflight
    if preflight.get("blocking"):
        raise RuntimeError(
            "Preflight blocked the task"
            f" ({preflight.get('todo', 0)} TODO, {preflight.get('drift', 0)} drift)"
        )
    return engine.run_task(task)


NO_PROVIDER_HELP = (
    "No agent CLI found on PATH (looked for: claude, opencode, codex).\n"
    "Install one to chat, or use the task panel (Ctrl+T) to run policy-backed tasks."
)


class ChatSession:
    """Multi-turn chat backed by an agent CLI on PATH.

    Prefers `claude` (true session continuity via --resume); falls back to
    `opencode`/`codex` with recent history folded into the prompt. Free-form
    chat deliberately bypasses the phase-prompt scaffolding the engine uses
    for lifecycle dispatches.
    """

    PROVIDERS = ("claude", "opencode", "codex")
    HISTORY_TURNS = 6

    def __init__(self, workspace_root: str | None = None, timeout: int = 180):
        self.workspace_root = workspace_root or os.getcwd()
        self.timeout = timeout
        self.provider: tuple[str, str] | None = None
        self.claude_session_id: str | None = None
        self.history: list[tuple[str, str]] = []

    def resolve_provider(self) -> tuple[str, str] | None:
        """Locate the first available agent CLI as a (name, path) pair."""
        if self.provider is None:
            for name in self.PROVIDERS:
                path = shutil.which(name)
                if path:
                    self.provider = (name, path)
                    break
        return self.provider

    def send(self, message: str) -> str:
        provider = self.resolve_provider()
        if provider is None:
            return NO_PROVIDER_HELP
        name, path = provider
        try:
            if name == "claude":
                reply = self._send_claude(path, message)
            else:
                reply = self._send_one_shot(name, path, message)
        except subprocess.TimeoutExpired:
            return f"{name} timed out after {self.timeout}s."
        except OSError as exc:
            return f"Could not start {name}: {exc}"
        self.history.append((message, reply))
        return reply

    def _send_claude(self, path: str, message: str) -> str:
        command = [path, "-p", "--output-format", "json"]
        if self.claude_session_id:
            command.extend(["--resume", self.claude_session_id])
        completed = subprocess.run(
            command,
            input=message,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            cwd=self.workspace_root,
        )
        try:
            envelope = json.loads(completed.stdout)
        except json.JSONDecodeError:
            envelope = None
        if isinstance(envelope, dict):
            session_id = envelope.get("session_id")
            if isinstance(session_id, str) and session_id:
                self.claude_session_id = session_id
            text = str(envelope.get("result") or "").strip()
            if envelope.get("is_error"):
                return f"claude error: {text or (completed.stderr or '').strip()}"
            if text:
                return text
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip()[:400]
            return f"claude exited with {completed.returncode}: {detail}"
        return (completed.stdout or "").strip() or "(empty response)"

    def _send_one_shot(self, name: str, path: str, message: str) -> str:
        if name == "opencode":
            command = [path, "run", "--", self._prompt_with_history(message)]
        else:
            command = [path, "exec", self._prompt_with_history(message)]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            cwd=self.workspace_root,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip()[:400]
            return f"{name} exited with {completed.returncode}: {detail}"
        return (completed.stdout or "").strip() or "(empty response)"

    def _prompt_with_history(self, message: str) -> str:
        if not self.history:
            return message
        lines = ["Continue this conversation. Reply to the final user message only."]
        for user, assistant in self.history[-self.HISTORY_TURNS:]:
            lines.append(f"User: {user}")
            lines.append(f"Assistant: {assistant}")
        lines.append(f"User: {message}")
        return "\n".join(lines)


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
