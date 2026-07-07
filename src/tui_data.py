"""Data access for the Sarathi terminal dashboard.

Kept free of textual imports so the dashboard's data layer can be tested
headlessly and reused by other frontends (service, MCP).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

try:
    from .engine import Engine, PersistenceManager, TaskContext
    from .evolve import Evolver, PolicyProposal, ProposalReviewStore
    from .runtime.providers.registry import specs_by_fallback_priority
except ImportError:
    # Support direct execution via sarathi.py, which prepends src/ to sys.path.
    from engine import Engine, PersistenceManager, TaskContext
    from evolve import Evolver, PolicyProposal, ProposalReviewStore
    from runtime.providers.registry import specs_by_fallback_priority


class _DynamicChatProviders:
    """Descriptor recomputing the ordered TUI-chat-capable provider tuple
    from the native provider registry on each access (class or instance),
    instead of a tuple frozen at import time — so a provider registered
    after this module first loaded (e.g. a test adding a fifth provider)
    still appears. See `NativeProviderSpec.tui_chat_support`/`fallback_priority`."""

    def __get__(self, obj: Any, objtype: type | None = None) -> tuple[str, ...]:
        return tuple(
            spec.name for spec in specs_by_fallback_priority() if spec.tui_chat_support
        )


class _DynamicStreamingHandlers:
    """Descriptor recomputing the provider-name -> streaming-method-name table
    from the registry on each access. See `NativeProviderSpec.tui_streaming_handler`."""

    def __get__(self, obj: Any, objtype: type | None = None) -> dict[str, str]:
        return {
            spec.name: spec.tui_streaming_handler
            for spec in specs_by_fallback_priority()
            if spec.tui_chat_support and spec.tui_streaming_handler is not None
        }


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
    cancel_check: Callable[[], bool] | None = None,
    task_timeout: float | None = None,
) -> TaskContext:
    """Create a new task from a description and run it through the lifecycle.

    Mirrors `sarathi run` with auto-detected complexity; raises RuntimeError
    when preflight validation blocks execution.

    When `context` is given (and non-empty), it is appended to the task
    description as recent chat context, but `task_id` and `complexity` are
    still derived from the bare `description` so the transcript doesn't
    pollute task identity.

    `cancel_check` and `task_timeout` are forwarded to `Engine.run_task` for
    cooperative cancellation and a wall-clock cap (see `task.stop_reason`).
    """
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
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
        return engine.run_task(task, cancel_check=cancel_check, task_timeout=task_timeout)


NO_PROVIDER_HELP = (
    "No agent CLI found on PATH (looked for: claude, opencode, codex).\n"
    "Install one to chat, or use the task panel (Ctrl+T) to run policy-backed tasks."
)


_ERROR_REPLY_RE = re.compile(r"^(claude|opencode|codex) (error|timed out|exited)|^Could not start ")


def is_error_reply(reply: str) -> bool:
    """True if `reply` is a CLI error/timeout message rather than a normal reply."""
    return bool(_ERROR_REPLY_RE.match(reply))


_SESSION_ID_KEYS = (
    "session_id", "sessionId",
    "thread_id", "threadId",
    "conversation_id", "conversationId",
)

_SESSION_ID_LINE_RE = re.compile(
    r"(?i)\b(?:session|thread|conversation)[ _-]?id\b\s*[:=]\s*\"?([A-Za-z0-9][A-Za-z0-9._-]{5,})\"?"
)


def _codex_event_payloads(event: dict) -> list[dict]:
    """Candidate dicts to scan for assistant text within one decoded codex
    `--json` line.

    Codex's JSONL event shape isn't stable across CLI versions — some wrap
    the real event under a `msg` key, others emit `item`/`message` objects
    at the top level — so this scans all of them rather than committing to
    one schema, per the "be liberal about unknown shapes" contract.
    """
    payloads = [event]
    for key in ("msg", "item", "message"):
        nested = event.get(key)
        if isinstance(nested, dict):
            payloads.append(nested)
    return payloads


def _codex_text_from_payload(payload: dict) -> tuple[str, bool] | None:
    """Pull `(text, is_delta)` out of one candidate payload, or None.

    `is_delta` is True when the text came from a `delta` key, or the
    payload's `type` mentions "delta" — an incremental chunk to append.
    Otherwise the text is a full/completed message, used to seed the reply
    only if no delta has arrived yet (mirrors how the claude streaming path
    ignores a redelivered full message once deltas already built the text).
    """
    type_str = str(payload.get("type") or "").lower()
    for key in ("delta", "text", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value, (key == "delta" or "delta" in type_str)
    return None


def _extract_session_id(*chunks: str | None) -> str | None:
    """Best-effort extraction of a resumable session id from codex/opencode output.

    Neither CLI is guaranteed to emit a machine-readable session id in any
    one shape, so this is telemetry rather than a hard requirement: any
    parse failure or absence of an id-looking value returns None instead of
    raising, so a chat turn never fails because session capture failed.
    """
    for chunk in chunks:
        if not chunk or not chunk.strip():
            continue
        try:
            for line in chunk.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    for key in _SESSION_ID_KEYS:
                        value = parsed.get(key)
                        if isinstance(value, str) and value.strip():
                            return value.strip()
                    continue
                match = _SESSION_ID_LINE_RE.search(line)
                if match:
                    return match.group(1)
        except Exception:  # noqa: BLE001 — telemetry only, never fail a chat turn
            continue
    return None


class ChatSession:
    """Multi-turn chat backed by an agent CLI on PATH.

    Prefers `claude` (true session continuity via --resume); falls back to
    `opencode`/`codex` with recent history folded into the prompt. Free-form
    chat deliberately bypasses the phase-prompt scaffolding the engine uses
    for lifecycle dispatches.
    """

    # Both are registry-backed descriptors (see _DynamicChatProviders /
    # _DynamicStreamingHandlers above) rather than frozen literals, so a
    # provider registered via `registry.register_spec` shows up here too.
    # Order matches each spec's `fallback_priority` (today: claude, codex,
    # opencode); providers absent from `_STREAMING_HANDLERS` (or with no CLI
    # on PATH) fall back to the blocking `send` in `send_streaming` below.
    PROVIDERS = _DynamicChatProviders()
    HISTORY_TURNS = 6

    _STREAMING_HANDLERS = _DynamicStreamingHandlers()

    def __init__(self, workspace_root: str | None = None, timeout: int = 180):
        self.workspace_root = workspace_root or os.getcwd()
        self.timeout = timeout
        self.provider: tuple[str, str] | None = None
        # Per-provider resumable session ids (e.g. {"claude": "sess-1"}).
        # `claude_session_id` below is a compatibility view onto this dict —
        # other code and tests still read/write it as a plain attribute.
        self.session_ids: dict[str, str] = {}
        self.history: list[tuple[str, str]] = []
        self.pending_context: list[str] = []
        self.cancelled = False
        self._active_proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()

    @property
    def claude_session_id(self) -> str | None:
        return self.session_ids.get("claude")

    @claude_session_id.setter
    def claude_session_id(self, value: str | None) -> None:
        if value:
            self.session_ids["claude"] = value
        else:
            self.session_ids.pop("claude", None)

    def clear(self) -> None:
        """Forget the conversation: history, pending context, and CLI session(s)."""
        self.history = []
        self.pending_context = []
        self.session_ids = {}

    def reset_session(self) -> None:
        """Drop the resumable provider session(s), keeping history and pending context."""
        self.session_ids = {}

    def cancel(self) -> bool:
        """Kill the in-flight CLI subprocess, if any.

        Returns True if a running process was signalled. Best-effort: only
        the streaming `claude` path registers a killable process; one-shot
        `subprocess.run` calls cannot be interrupted this way.
        """
        with self._proc_lock:
            proc = self._active_proc
        if proc is not None and proc.poll() is None:
            self.cancelled = True
            proc.kill()
            return True
        return False

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
        self.session_ids = {}
        return True

    def send(self, message: str) -> str:
        self.cancelled = False
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

        Each provider with a streaming implementation (`claude`, `codex`,
        `opencode` — see `_STREAMING_HANDLERS`) reads its CLI's incremental
        output and invokes `on_text` with the growing accumulated text as
        chunks arrive. For providers without one (or when no provider is
        available), falls back to the blocking `send` and calls `on_text`
        once with the full reply.
        """
        self.cancelled = False
        provider = self.resolve_provider()
        if provider is None:
            reply = self.send(message)
            if on_text is not None and reply:
                on_text(reply)
            return reply
        name, path = provider
        handler_name = self._STREAMING_HANDLERS.get(name)
        if handler_name is None:
            reply = self.send(message)
            if on_text is not None and reply:
                on_text(reply)
            return reply
        resolved = self._consume_context(message)
        try:
            return getattr(self, handler_name)(path, message, resolved, on_text)
        except OSError as exc:
            return f"Could not start {name}: {exc}"

    def _run_streaming_subprocess(
        self,
        command: list[str],
        stdin_text: str,
        on_stdout_line: Callable[[str], None],
    ) -> tuple[str, bool, int | None]:
        """Spawn `command`, feed `stdin_text` on stdin, and call
        `on_stdout_line` for each non-empty stdout line as it arrives.

        Shares the reader-thread/queue/deadline plumbing the `claude`
        streaming path pioneered (see `_send_claude_streaming`) so `codex`
        and `opencode` streaming get the same non-blocking incremental
        reads, cooperative cancellation via `cancel()`, and timeout
        handling without duplicating that logic per provider. Always kills
        and reaps the process before returning. Returns
        `(stderr_text, timed_out, returncode)`.
        """
        deadline = time.monotonic() + self.timeout
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.workspace_root,
        )
        with self._proc_lock:
            self._active_proc = proc

        if proc.stdin is not None:
            try:
                proc.stdin.write(stdin_text)
            except (BrokenPipeError, OSError):
                pass
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        line_queue: queue.Queue[str | None] = queue.Queue()
        stderr_chunks: list[str] = []

        def _read_stdout() -> None:
            try:
                if proc.stdout is not None:
                    for raw_line in proc.stdout:
                        line_queue.put(raw_line)
            finally:
                line_queue.put(None)

        def _read_stderr() -> None:
            try:
                if proc.stderr is not None:
                    for raw_line in proc.stderr:
                        stderr_chunks.append(raw_line)
            except (BrokenPipeError, OSError, ValueError):
                pass

        stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
        stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        timed_out = False
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    line = line_queue.get(timeout=min(remaining, 0.5))
                except queue.Empty:
                    continue
                if line is None:  # EOF sentinel
                    break
                stripped = line.strip()
                if stripped:
                    on_stdout_line(stripped)

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
            stderr_thread.join(timeout=1)
            with self._proc_lock:
                self._active_proc = None

        return "".join(stderr_chunks), timed_out, proc.returncode

    def _send_codex_streaming(
        self,
        path: str,
        original_message: str,
        message: str,
        on_text: Callable[[str], None] | None,
    ) -> str:
        """Stream `codex exec --json`, parsing JSONL events incrementally.

        Malformed or unrecognized lines/events are skipped silently (never
        raise) — codex's JSONL shape isn't guaranteed, so this is
        best-effort text extraction, not a strict schema. See
        `_codex_event_payloads`/`_codex_text_from_payload`.
        """
        session_id = self.session_ids.get("codex")
        if session_id:
            command = [path, "exec", "resume", session_id, "--json", message]
        else:
            command = [path, "exec", "--json", self._prompt_with_history(message)]

        accumulated = ""
        saw_delta = False
        raw_lines: list[str] = []

        def _on_line(line: str) -> None:
            nonlocal accumulated, saw_delta
            raw_lines.append(line)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                return  # malformed JSONL line: skip silently
            if not isinstance(event, dict):
                return
            for payload in _codex_event_payloads(event):
                found = _codex_text_from_payload(payload)
                if found is None:
                    continue
                text, is_delta = found
                if is_delta:
                    accumulated += text
                    saw_delta = True
                elif not saw_delta:
                    accumulated += text
                else:
                    continue  # a redelivered full message once deltas exist
                if on_text is not None:
                    on_text(accumulated)
                break

        stderr_text, timed_out, returncode = self._run_streaming_subprocess(
            command, "", _on_line
        )

        if self.cancelled:
            return "(cancelled)"
        if timed_out:
            return f"codex timed out after {self.timeout}s."

        found_session_id = _extract_session_id(*raw_lines, stderr_text)
        if found_session_id:
            self.session_ids["codex"] = found_session_id

        reply = accumulated.strip()
        if returncode not in (0, None):
            if reply:
                self.history.append((original_message, reply))
                return reply
            detail = stderr_text.strip()[:400]
            return f"codex exited with {returncode}: {detail}"

        if reply:
            self.history.append((original_message, reply))
            return reply
        return "(empty response)"

    def _send_opencode_streaming(
        self,
        path: str,
        original_message: str,
        message: str,
        on_text: Callable[[str], None] | None,
    ) -> str:
        """Stream `opencode run`, forwarding stdout lines as they arrive.

        OpenCode has no partial-message JSON protocol like claude/codex; it
        just prints progressively, so each stdout line is appended to the
        growing reply as soon as it's read.
        """
        session_id = self.session_ids.get("opencode")
        if session_id:
            command = [path, "run", "--session", session_id, "--", message]
        else:
            command = [path, "run", "--", self._prompt_with_history(message)]

        accumulated = ""

        def _on_line(line: str) -> None:
            nonlocal accumulated
            accumulated = f"{accumulated}\n{line}" if accumulated else line
            if on_text is not None:
                on_text(accumulated)

        stderr_text, timed_out, returncode = self._run_streaming_subprocess(
            command, "", _on_line
        )

        if self.cancelled:
            return "(cancelled)"
        if timed_out:
            return f"opencode timed out after {self.timeout}s."

        found_session_id = _extract_session_id(accumulated, stderr_text)
        if found_session_id:
            self.session_ids["opencode"] = found_session_id

        reply = accumulated.strip()
        if returncode not in (0, None):
            if reply:
                self.history.append((original_message, reply))
                return reply
            detail = stderr_text.strip()[:400]
            return f"opencode exited with {returncode}: {detail}"

        if reply:
            self.history.append((original_message, reply))
            return reply
        return "(empty response)"

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
        with self._proc_lock:
            self._active_proc = proc
        accumulated = ""
        result_text: str | None = None
        session_id: str | None = None
        is_error = False
        timed_out = False
        saw_delta = False

        if proc.stdin is not None:
            try:
                proc.stdin.write(message)
            except (BrokenPipeError, OSError):
                pass
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        line_queue: queue.Queue[str | None] = queue.Queue()
        stderr_chunks: list[str] = []

        def _read_stdout() -> None:
            try:
                if proc.stdout is not None:
                    for raw_line in proc.stdout:
                        line_queue.put(raw_line)
            finally:
                line_queue.put(None)

        def _read_stderr() -> None:
            try:
                if proc.stderr is not None:
                    for raw_line in proc.stderr:
                        stderr_chunks.append(raw_line)
            except (BrokenPipeError, OSError, ValueError):
                pass

        stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
        stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    line = line_queue.get(timeout=min(remaining, 0.5))
                except queue.Empty:
                    continue
                if line is None:  # EOF sentinel
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
            stderr_thread.join(timeout=1)
            with self._proc_lock:
                self._active_proc = None

        stderr_text = "".join(stderr_chunks)

        if self.cancelled:
            return "(cancelled)"

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

        if accumulated.strip():
            reply = accumulated.strip()
            self.history.append((original_message, reply))
            return reply

        returncode = proc.returncode
        if returncode not in (0, None):
            # Older CLIs may reject --include-partial-messages and exit
            # nonzero without ever producing a result event. Fall back to
            # the blocking JSON path.
            try:
                reply = self._send_claude(path, message)
            except (subprocess.TimeoutExpired, OSError):
                reply = ""
            if reply and not reply.startswith(("claude error", "claude exited", "claude timed out")):
                if on_text is not None:
                    on_text(reply)
                self.history.append((original_message, reply))
                return reply
            detail = stderr_text.strip()[:300] or "no output"
            return f"claude error (exit {returncode}): {detail}"

        return "(empty response)"

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
        session_id = self.session_ids.get(name)
        if name == "opencode":
            if session_id:
                # Resuming: the CLI already has the prior turns, so send the
                # raw message rather than re-folding history into the prompt.
                command = [path, "run", "--session", session_id, "--", message]
            else:
                command = [path, "run", "--", self._prompt_with_history(message)]
        elif session_id:
            command = [path, "exec", "resume", session_id, message]
        else:
            command = [path, "exec", self._prompt_with_history(message)]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            cwd=self.workspace_root,
        )
        found_session_id = _extract_session_id(completed.stdout, completed.stderr)
        if found_session_id:
            self.session_ids[name] = found_session_id
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


def init_workspace(target_path: str | Path, engine: str = "markdown") -> dict[str, Any]:
    """Run the onboarding workflow on a folder, creating a policy pack.

    Mirrors `sarathi init <target_path>` (inspect → interview → generate →
    validate → evolve) but returns a summary dict instead of printing, so
    the TUI can run it in a worker and report results into the chat. The
    returned dict has an ``error`` key on failure, otherwise ``policy_pack``,
    ``languages``, ``build_tools``, ``validation_passed`` and
    ``validation_total``.
    """
    try:
        from .init import InitWorkflow
    except ImportError:
        from init import InitWorkflow

    target = Path(target_path).expanduser()
    if not target.is_dir():
        return {"error": f"Not a directory: {target}"}
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        workflow = InitWorkflow(target_path=str(target), engine_path=engine)
        inspection = workflow.inspect()
        if inspection.get("error"):
            return {"error": inspection["error"]}
        interview = workflow.interview(inspection)
        policy_path = workflow.generate(inspection, interview)
        validation = workflow.validate(policy_path)
        passed = sum(
            1 for r in validation if getattr(r.status, "value", r.status) == "PASS"
        )
        workflow.evolve()
    return {
        "policy_pack": str(policy_path),
        "languages": inspection.get("languages", []),
        "build_tools": inspection.get("build_tools", []),
        "validation_passed": passed,
        "validation_total": len(validation),
    }


def resume_task(
    persistence: PersistenceManager,
    task_id: str,
    policy_pack: str | Path,
    cancel_check: Callable[[], bool] | None = None,
    task_timeout: float | None = None,
) -> TaskContext:
    """Resume a persisted task through the engine.

    `cancel_check` and `task_timeout` are forwarded to `Engine.resume_task`
    (see `start_task`).
    """
    task = persistence.load_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")
    engine = Engine(policy_pack_path=str(policy_pack), enforce_preflight=True)
    engine.persistence = persistence
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return engine.resume_task(task, cancel_check=cancel_check, task_timeout=task_timeout)
