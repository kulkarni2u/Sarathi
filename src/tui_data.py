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
import time
from pathlib import Path
from typing import Any, Callable

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
    persistence: PersistenceManager,
    description: str,
    policy_pack: str | Path,
    context: str | None = None,
) -> TaskContext:
    """Create a new task from a description and run it through the lifecycle.

    Mirrors `sarathi run` with auto-detected complexity; raises RuntimeError
    when preflight validation blocks execution.

    When `context` is given (and non-empty), it is appended to the task
    description as recent chat context, but `task_id` and `complexity` are
    still derived from the bare `description` so the transcript doesn't
    pollute task identity.
    """
    engine = Engine(policy_pack_path=str(policy_pack), enforce_preflight=True)
    engine.persistence = persistence
    task_description = description
    if context:
        task_description = f"{description}\n\nContext from chat conversation:\n{context}"
    task = TaskContext(
        task_id=engine.generate_task_id(description),
        description=task_description,
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
        self.pending_context: list[str] = []

    def add_context(self, label: str, text: str) -> None:
        """Queue `text` (under `label`) to be sent with the next message."""
        self.pending_context.append(f"{label}:\n{text}")

    def _consume_context(self, message: str) -> str:
        """Wrap `message` with any pending context, clearing the queue.

        Returns `message` unchanged when there is no pending context.
        """
        if not self.pending_context:
            return message
        joined = "\n\n".join(self.pending_context)
        self.pending_context = []
        return f"Context for this conversation:\n\n{joined}\n\nUser message: {message}"

    def resolve_provider(self) -> tuple[str, str] | None:
        """Locate the first available agent CLI as a (name, path) pair."""
        if self.provider is None:
            for name in self.PROVIDERS:
                path = shutil.which(name)
                if path:
                    self.provider = (name, path)
                    break
        return self.provider

    def available_providers(self) -> list[tuple[str, str]]:
        """All agent CLIs found on PATH, as (name, path) pairs."""
        found = []
        for name in self.PROVIDERS:
            path = shutil.which(name)
            if path:
                found.append((name, path))
        return found

    def set_provider(self, name: str) -> bool:
        """Switch the active provider, resetting any claude session.

        Returns True if `name` was found on PATH and selected, else False
        (leaving the current provider unchanged).
        """
        path = shutil.which(name)
        if not path:
            return False
        self.provider = (name, path)
        self.claude_session_id = None
        return True

    def send(self, message: str) -> str:
        provider = self.resolve_provider()
        if provider is None:
            return NO_PROVIDER_HELP
        resolved = self._consume_context(message)
        name, path = provider
        try:
            if name == "claude":
                reply = self._send_claude(path, resolved)
            else:
                reply = self._send_one_shot(name, path, resolved)
        except subprocess.TimeoutExpired:
            return f"{name} timed out after {self.timeout}s."
        except OSError as exc:
            return f"Could not start {name}: {exc}"
        self.history.append((message, reply))
        return reply

    def send_streaming(
        self, message: str, on_text: Callable[[str], None] | None = None
    ) -> str:
        """Send `message`, optionally streaming partial replies via `on_text`.

        For `claude`, reads `stream-json` events from the CLI and invokes
        `on_text` with the growing accumulated text as assistant message
        chunks arrive. For other providers (or when no provider is
        available), falls back to the blocking `send` and calls `on_text`
        once with the full reply.
        """
        provider = self.resolve_provider()
        if provider is None or provider[0] != "claude":
            reply = self.send(message)
            if on_text is not None and reply:
                on_text(reply)
            return reply
        resolved = self._consume_context(message)
        name, path = provider
        try:
            return self._send_claude_streaming(path, message, resolved, on_text)
        except OSError as exc:
            return f"Could not start {name}: {exc}"

    def _send_claude_streaming(
        self,
        path: str,
        original_message: str,
        message: str,
        on_text: Callable[[str], None] | None,
    ) -> str:
        command = [
            path,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]
        if self.claude_session_id:
            command.extend(["--resume", self.claude_session_id])
        deadline = time.monotonic() + self.timeout
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.workspace_root,
        )
        accumulated = ""
        result_text: str | None = None
        session_id: str | None = None
        is_error = False
        timed_out = False
        saw_delta = False
        try:
            if proc.stdin is not None:
                try:
                    proc.stdin.write(message)
                except (BrokenPipeError, OSError):
                    pass
                proc.stdin.close()
            if proc.stdout is not None:
                for line in proc.stdout:
                    if time.monotonic() > deadline:
                        timed_out = True
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    event_type = event.get("type")
                    if event_type == "system" and event.get("subtype") == "init":
                        sid = event.get("session_id")
                        if isinstance(sid, str) and sid:
                            session_id = sid
                    elif event_type == "stream_event":
                        stream_event = event.get("event")
                        if not isinstance(stream_event, dict):
                            continue
                        if stream_event.get("type") == "content_block_delta":
                            delta = stream_event.get("delta")
                            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                                text = delta.get("text")
                                if isinstance(text, str) and text:
                                    accumulated += text
                                    saw_delta = True
                                    if on_text is not None:
                                        on_text(accumulated)
                        # Other stream_event subtypes (message_start, etc.)
                        # carry no text and are ignored.
                    elif event_type == "assistant":
                        if not saw_delta:
                            message_obj = event.get("message") or {}
                            for block in message_obj.get("content") or []:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    accumulated += str(block.get("text") or "")
                            if on_text is not None:
                                on_text(accumulated)
                        # else: assistant events re-deliver the full text
                        # already streamed via text_delta — ignore to avoid
                        # doubling.
                    elif event_type == "result":
                        result_text = str(event.get("result") or "")
                        sid = event.get("session_id")
                        if isinstance(sid, str) and sid:
                            session_id = sid
                        is_error = bool(event.get("is_error"))
            if not timed_out:
                remaining = deadline - time.monotonic()
                try:
                    proc.wait(timeout=max(remaining, 0))
                except subprocess.TimeoutExpired:
                    timed_out = True
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

        if timed_out:
            return f"claude timed out after {self.timeout}s."

        if session_id:
            self.claude_session_id = session_id

        if result_text is not None:
            reply = result_text.strip() or accumulated
            if is_error:
                return f"claude error: {reply}"
            self.history.append((original_message, reply))
            return reply

        if not accumulated and proc.returncode not in (0, None):
            # Older CLIs may reject --include-partial-messages and exit
            # nonzero without ever producing a result event. Fall back to
            # the blocking JSON path.
            reply = self._send_claude(path, message)
            if on_text is not None and reply:
                on_text(reply)
            self.history.append((original_message, reply))
            return reply

        reply = accumulated.strip() or "(empty response)"
        self.history.append((original_message, reply))
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
