"""CLI bridge that normalizes native provider invocations into Sarathi dispatch output."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import http.client
import logging
from math import ceil
import os
import re
import shutil
import signal
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

try:
    import yaml as _yaml
except ImportError:
    _yaml = None  # type: ignore[assignment]

try:
    from ..contracts import DispatchRequest, DispatchResponse, build_usage_record
    from ..agent_roles import PHASE_AGENT_ROLE_KEYS
    from ...permissions import PermissionMode
    from ..workspace_evidence import attach_workspace_evidence, snapshot_workspace
except ImportError:
    from runtime.contracts import DispatchRequest, DispatchResponse, build_usage_record
    from runtime.agent_roles import PHASE_AGENT_ROLE_KEYS
    from permissions import PermissionMode
    from runtime.workspace_evidence import attach_workspace_evidence, snapshot_workspace

logger = logging.getLogger("sarathi.cli_bridge")


def _run_cli_process(
    command: list[str],
    *,
    cwd: str,
    timeout: int,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a provider CLI in its own process group.

    Provider CLIs spawn children (node helpers, MCP servers, shells); a plain
    subprocess timeout kills only the direct child and leaves the rest of the
    tree running — potentially still mutating the workspace after we reported
    a timeout. On POSIX, kill the whole group instead.
    """
    popen_kwargs: dict[str, Any] = {}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        **popen_kwargs,
    )
    try:
        stdout, stderr = proc.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
        else:
            proc.kill()
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except Exception:  # noqa: BLE001 — best-effort reap after kill
            stdout, stderr = "", ""
        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(command, proc.returncode, stdout=stdout or "", stderr=stderr or "")


def _cli_failure_response(
    *,
    provider: str,
    path: str,
    workspace_root: str,
    command: list[str],
    error: str,
    timed_out: bool = False,
) -> DispatchResponse:
    logger.warning("%s CLI dispatch failed: %s", provider, error)
    return DispatchResponse(
        success=False,
        artifacts={
            "provider": provider,
            "path": path,
            "command": command,
            "invocation_kind": "native_cli",
            "workspace_root": workspace_root,
            "timed_out": timed_out,
        },
        error=error,
    )


def dispatch_via_cli_bridge(
    *,
    provider: str,
    path: str,
    workspace_root: str,
    request: DispatchRequest,
) -> DispatchResponse:
    provider_name = provider.strip().lower()
    requested_workspace = request.constraints.get("workspace_dir")
    if isinstance(requested_workspace, str) and requested_workspace.strip():
        workspace_root = requested_workspace
    permission_mode = _coerce_permission_mode(request.constraints.get("permission_mode"))
    if provider_name in {"claude", "codex", "opencode"}:
        try:
            ensure_provider_permissions(workspace_root, permission_mode=permission_mode)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to apply %s provider permissions for %s",
                permission_mode.value,
                provider_name,
            )
    before = snapshot_workspace(workspace_root)
    if provider_name == "codex":
        response = _run_codex(path=path, workspace_root=workspace_root, request=request)
    elif provider_name == "copilot":
        response = _run_copilot(path=path, workspace_root=workspace_root, request=request)
    elif provider_name == "claude":
        response = _run_claude(path=path, workspace_root=workspace_root, request=request)
    elif provider_name == "opencode":
        response = _run_opencode(path=path, workspace_root=workspace_root, request=request)
    else:
        return DispatchResponse(
            success=False,
            artifacts={"provider": provider_name, "path": path},
            error=f"Native provider bridge is not implemented for '{provider_name}'",
        )
    return attach_workspace_evidence(response, before, workspace_root, request, logger=logger)


def _build_codex_command(
    path: str,
    *,
    output_path: Path,
    model: str | None,
    session_id: str | None,
    prompt: str,
) -> list[str]:
    """Build the `codex exec` argv, inserting `resume <SESSION_ID>` when resuming.

    Documented resume syntax is `codex exec resume <SESSION_ID> [same flags]
    <prompt>` — the resume subcommand and id slot in right after `exec`, ahead
    of the flags that a fresh `codex exec` invocation would also carry.
    Centralized here (rather than inlined in `_run_codex`) so tests can assert
    on the argv shape without shelling out to a real codex binary.
    """
    command = [path, "exec"]
    if session_id:
        command.extend(["resume", session_id])
    command.extend(["--skip-git-repo-check", "-o", str(output_path)])
    if model:
        command.extend(["--model", model])
    command.append(prompt)
    return command


def _run_codex(*, path: str, workspace_root: str, request: DispatchRequest) -> DispatchResponse:
    prompt = _provider_prompt("codex", request, workspace_root)
    with tempfile.NamedTemporaryFile("w+", suffix="-sarathi-codex.txt", delete=False) as handle:
        output_path = Path(handle.name)
    raw_session_id = request.constraints.get("codex_session_id")
    session_id = raw_session_id if isinstance(raw_session_id, str) and raw_session_id else None
    command = _build_codex_command(
        path,
        output_path=output_path,
        model=_requested_model(request),
        session_id=session_id,
        prompt=prompt,
    )
    try:
        completed = _run_cli_process(
            command,
            cwd=workspace_root,
            timeout=request.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return _cli_failure_response(
            provider="codex", path=path, workspace_root=workspace_root, command=command,
            error=f"codex CLI timed out after {request.timeout_seconds}s; process group killed.",
            timed_out=True,
        )
    except OSError as exc:
        return _cli_failure_response(
            provider="codex", path=path, workspace_root=workspace_root, command=command,
            error=f"codex CLI could not be started: {exc}",
        )
    finally:
        message = _read_text(output_path)
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass
    # Codex isn't guaranteed to emit a machine-readable session id; scan the
    # captured output file plus stdout/stderr defensively and record nothing
    # if none is found — this is telemetry, not a dispatch requirement.
    codex_session_id = _extract_session_id(message, completed.stdout, completed.stderr)
    extra_artifacts = {"codex_session_id": codex_session_id} if codex_session_id else {}
    response = _normalize_native_response(
        provider="codex",
        path=path,
        workspace_root=workspace_root,
        request=request,
        command=command,
        completed=completed,
        message=message,
        extra_artifacts=extra_artifacts,
    )
    return _ncp_fetch_after_dispatch(workspace_root, request, response)


def _run_copilot(*, path: str, workspace_root: str, request: DispatchRequest) -> DispatchResponse:
    prompt = _provider_prompt("copilot", request, workspace_root)
    executable = Path(path).name
    if executable == "gh":
        command = [path, "copilot", "--", "-p", prompt]
    else:
        command = [path, "-p", prompt]
    try:
        completed = _run_cli_process(
            command,
            cwd=workspace_root,
            timeout=request.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return _cli_failure_response(
            provider="copilot", path=path, workspace_root=workspace_root, command=command,
            error=f"copilot CLI timed out after {request.timeout_seconds}s; process group killed.",
            timed_out=True,
        )
    except OSError as exc:
        return _cli_failure_response(
            provider="copilot", path=path, workspace_root=workspace_root, command=command,
            error=f"copilot CLI could not be started: {exc}",
        )
    message = (completed.stdout or "").strip()
    response = _normalize_native_response(
        provider="copilot",
        path=path,
        workspace_root=workspace_root,
        request=request,
        command=command,
        completed=completed,
        message=message,
    )
    return _ncp_fetch_after_dispatch(workspace_root, request, response)


def _run_claude(*, path: str, workspace_root: str, request: DispatchRequest) -> DispatchResponse:
    if _should_use_ncp_handoff(provider="claude", workspace_root=workspace_root, request=request):
        return _run_ncp_handoff_dispatch(
            provider="claude",
            workspace_root=workspace_root,
            request=request,
        )
    prompt = _provider_prompt("claude", request, workspace_root)
    # Prompt goes over stdin: argv has a hard size limit (ARG_MAX) and the
    # prompt embeds the full context pack JSON.
    command = [
        path,
        "-p",
        "--output-format", "json",
        "--add-dir", workspace_root,
    ]
    model = _requested_model(request)
    if model:
        command.extend(["--model", model])
    session_id = request.constraints.get("claude_session_id")
    if isinstance(session_id, str) and session_id:
        command.extend(["--resume", session_id])
    try:
        completed = _run_cli_process(
            command,
            cwd=workspace_root,
            timeout=request.timeout_seconds,
            input_text=prompt,
        )
    except subprocess.TimeoutExpired:
        return _cli_failure_response(
            provider="claude", path=path, workspace_root=workspace_root, command=command,
            error=f"claude CLI timed out after {request.timeout_seconds}s; process group killed.",
            timed_out=True,
        )
    except OSError as exc:
        return _cli_failure_response(
            provider="claude", path=path, workspace_root=workspace_root, command=command,
            error=f"claude CLI could not be started: {exc}",
        )
    # Unwrap the Claude Code JSON envelope: {"type":"result","result":"...","is_error":...}
    envelope = _parse_claude_envelope(completed.stdout)
    reported_usage: dict[str, Any] | None = None
    envelope_artifacts: dict[str, Any] = {}
    if envelope is not None:
        message = envelope["message"]
        reported_usage = envelope.get("usage")
        for env_key, artifact_key in (
            ("session_id", "claude_session_id"),
            ("total_cost_usd", "total_cost_usd"),
            ("num_turns", "num_turns"),
            ("duration_ms", "provider_duration_ms"),
        ):
            if envelope.get(env_key) is not None:
                envelope_artifacts[artifact_key] = envelope[env_key]
        if envelope.get("is_error"):
            return DispatchResponse(
                success=False,
                artifacts={
                    "provider": "claude",
                    "path": path,
                    "command": command,
                    "return_code": completed.returncode,
                    "invocation_kind": "native_cli",
                    "workspace_root": workspace_root,
                    **envelope_artifacts,
                },
                usage=build_usage_record(
                    provider_id="claude",
                    provider_family="claude",
                    dispatch_id=request.task_id,
                    prompt=request.prompt,
                    response_text=message,
                    reported_usage=reported_usage,
                ),
                error=message or (completed.stderr or "").strip() or "Claude reported an error result.",
            )
    else:
        message = (completed.stdout or "").strip()
    response = _normalize_native_response(
        provider="claude",
        path=path,
        workspace_root=workspace_root,
        request=request,
        command=command,
        completed=completed,
        message=message,
        reported_usage=reported_usage,
        extra_artifacts=envelope_artifacts,
    )
    return _ncp_fetch_after_dispatch(workspace_root, request, response)


def _build_opencode_command(
    path: str,
    *,
    workspace_root: str,
    session_id: str | None,
    prompt: str,
) -> list[str]:
    """Build the `opencode run` argv.

    Passes `--session <id>` to resume a prior conversation when one is
    stored in constraints; otherwise falls back to `-c` (continue the most
    recent local session), which was the prior stateless-continuity default.
    """
    command = [path, "run"]
    if session_id:
        command.extend(["--session", session_id])
    else:
        command.append("-c")
    command.extend(["--dir", workspace_root, "--", prompt])
    return command


def _run_opencode(*, path: str, workspace_root: str, request: DispatchRequest) -> DispatchResponse:
    """Bridge for OpenCode via CLI (`opencode run`).

    Uses `opencode run -c --dir <workspace> -- <prompt>` by default, or
    `opencode run --session <id> --dir <workspace> -- <prompt>` when a
    resumable `opencode_session_id` is present in constraints.
    Tool approvals are pre-granted via opencode.json written by `sarathi init`.
    """
    if _should_use_ncp_handoff(provider="opencode", workspace_root=workspace_root, request=request):
        return _run_ncp_handoff_dispatch(
            provider="opencode",
            workspace_root=workspace_root,
            request=request,
        )
    prompt = _provider_prompt("opencode", request, workspace_root)
    raw_session_id = request.constraints.get("opencode_session_id")
    session_id = raw_session_id if isinstance(raw_session_id, str) and raw_session_id else None
    command = _build_opencode_command(
        path,
        workspace_root=workspace_root,
        session_id=session_id,
        prompt=prompt,
    )
    stderr_text = ""
    try:
        result = _run_cli_process(
            command,
            cwd=workspace_root,
            timeout=request.timeout_seconds,
        )
        message = result.stdout if result.returncode == 0 else f"Error: {result.stderr}"
        return_code = result.returncode
        stderr_text = result.stderr or ""
    except subprocess.TimeoutExpired:
        message = f"Timeout after {request.timeout_seconds}s; process group killed"
        return_code = 124
    except OSError as exc:
        message = str(exc)
        return_code = 1

    completed = subprocess.CompletedProcess(command, return_code, stdout=message, stderr="")
    # As with codex, OpenCode's session id is best-effort telemetry: scan
    # stdout/stderr defensively and omit the artifact rather than fail.
    opencode_session_id = _extract_session_id(message, stderr_text)
    extra_artifacts = {"opencode_session_id": opencode_session_id} if opencode_session_id else {}
    response = _normalize_native_response(
        provider="opencode",
        path=path,
        workspace_root=workspace_root,
        request=request,
        command=command,
        completed=completed,
        message=message,
        extra_artifacts=extra_artifacts,
    )
    return _ncp_fetch_after_dispatch(workspace_root, request, response)


def _requested_model(request: DispatchRequest) -> str | None:
    model = request.constraints.get("model")
    return model if isinstance(model, str) and model.strip() else None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_opencode(base_url: str, timeout: int = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"{base_url}/session", timeout=1)
            return
        except Exception:
            time.sleep(0.3)
    raise TimeoutError(f"OpenCode server at {base_url} did not become ready in {timeout}s")


def _opencode_http(method: str, url: str, body: dict | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"OpenCode server returned non-JSON from {method} {url}: {raw[:200]!r}"
        ) from exc


def _opencode_create_session(base_url: str) -> str:
    data = _opencode_http("POST", f"{base_url}/session", {})
    return data["id"]


def _opencode_send_and_wait(base_url: str, session_id: str, text: str, timeout: int = 120) -> str:
    """POST a message and read the SSE stream until the assistant reply is complete.

    OpenCode streams the reply as SSE events on the POST response body.
    We must keep the connection open; closing it stops generation.
    """
    import threading

    body = json.dumps({"parts": [{"type": "text", "text": text}], "role": "user"}).encode()
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80

    result: list[str] = []
    error: list[str] = []

    def _stream() -> None:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            conn.request("POST", f"/session/{session_id}/message", body=body,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            buf = b""
            while True:
                chunk = resp.read(1024)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line.startswith(b"data:"):
                        continue
                    payload = line[5:].strip()
                    event = _parse_json_dict(payload.decode(errors="replace"))
                    if event is None:
                        continue
                    # Collect text parts from assistant message events
                    parts = event.get("parts", [])
                    for part in parts:
                        if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                            result.append(part["text"])
                    # Check for finish / done signal
                    if event.get("type") in {"message_stop", "done", "finish"} or event.get("finish_reason"):
                        return
        except Exception as exc:
            error.append(str(exc))
        finally:
            conn.close()

    t = threading.Thread(target=_stream, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if result:
        return "".join(result)
    # Fallback: poll GET /session/{id}/message in case SSE parsing missed the content
    return _opencode_poll_reply(base_url, session_id, timeout=min(30, timeout // 2))


def _opencode_poll_reply(base_url: str, session_id: str, timeout: int = 30) -> str:
    """Fallback: poll GET /session/{id}/message for a completed assistant reply."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        messages = _opencode_http("GET", f"{base_url}/session/{session_id}/message")
        for msg in reversed(messages if isinstance(messages, list) else []):
            info = msg.get("info", {})
            if info.get("role") != "assistant":
                continue
            parts = msg.get("parts", [])
            texts = [p["text"] for p in parts if isinstance(p, dict) and p.get("type") == "text" and p.get("text")]
            if texts:
                return "\n".join(texts)
        time.sleep(2)
    raise TimeoutError(f"No assistant reply within {timeout}s")


def _parse_claude_envelope(raw_output: str) -> dict[str, Any] | None:
    """Parse a Claude Code --output-format json envelope into normalized fields.

    Claude Code wraps output in {"type":"result","result":"...","is_error":...,
    "usage":{...},"total_cost_usd":...,"session_id":...}. Returns None when the
    output is not a Claude envelope (plain text, a mock, or a structured bridge
    response) so callers can fall back to pass-through handling.

    The usage/cost/session fields are real provider telemetry — far more
    accurate than character-count estimates — so they must not be discarded.
    """
    raw = raw_output.strip()
    if not raw:
        return None
    envelope = _parse_json_dict(raw)
    if envelope is None or envelope.get("type") != "result" or "result" not in envelope:
        return None
    result = envelope.get("result")
    usage = envelope.get("usage")
    return {
        "message": str(result).strip() if result is not None else "",
        "is_error": bool(envelope.get("is_error")),
        "usage": usage if isinstance(usage, dict) else None,
        "session_id": envelope.get("session_id"),
        "total_cost_usd": envelope.get("total_cost_usd"),
        "num_turns": envelope.get("num_turns"),
        "duration_ms": envelope.get("duration_ms"),
    }


_SESSION_ID_KEYS = (
    "session_id", "sessionId",
    "thread_id", "threadId",
    "conversation_id", "conversationId",
)

_SESSION_ID_LINE_RE = re.compile(
    r"(?i)\b(?:session|thread|conversation)[ _-]?id\b\s*[:=]\s*\"?([A-Za-z0-9][A-Za-z0-9._-]{5,})\"?"
)


def _find_session_id_in_dict(data: dict[str, Any]) -> str | None:
    for key in _SESSION_ID_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_session_id(*chunks: str | None) -> str | None:
    """Best-effort extraction of a resumable session/thread id from CLI output.

    Codex and OpenCode aren't guaranteed to emit a machine-readable session
    id in any one shape — it may show up as a JSON envelope, one JSON object
    per output line, or a plain "session id: <uuid>" line on stderr. This is
    telemetry, not a dispatch requirement: any parse failure or absence of an
    id-looking value returns None instead of raising, so a dispatch never
    fails because session capture failed.
    """
    for chunk in chunks:
        if not chunk or not chunk.strip():
            continue
        try:
            whole = _parse_json_dict(chunk)
            if whole is not None:
                found = _find_session_id_in_dict(whole)
                if found:
                    return found
            for line in chunk.splitlines():
                line = line.strip()
                if not line:
                    continue
                parsed_line = _parse_json_dict(line)
                if parsed_line is not None:
                    found = _find_session_id_in_dict(parsed_line)
                    if found:
                        return found
                    continue
                match = _SESSION_ID_LINE_RE.search(line)
                if match:
                    return match.group(1)
        except Exception:  # noqa: BLE001 — telemetry only, never fail dispatch
            continue
    return None


def _normalize_native_response(
    *,
    provider: str,
    path: str,
    workspace_root: str,
    request: DispatchRequest,
    command: list[str],
    completed: subprocess.CompletedProcess[str],
    message: str,
    reported_usage: dict[str, Any] | None = None,
    extra_artifacts: dict[str, Any] | None = None,
) -> DispatchResponse:
    parsed = _parse_json_dict(message)
    cli_family = _native_cli_family(provider, path)
    extra_artifacts = extra_artifacts or {}
    if parsed is not None:
        outputs = parsed.get("outputs") if isinstance(parsed.get("outputs"), dict) else {}
        evidence = parsed.get("evidence") if isinstance(parsed.get("evidence"), dict) else {}
        artifacts = parsed.get("artifacts") if isinstance(parsed.get("artifacts"), dict) else {}
        raw_transcript_ref = parsed.get("raw_transcript_ref") if isinstance(parsed.get("raw_transcript_ref"), str) else None
        success = bool(parsed.get("success", completed.returncode == 0))
        error = parsed.get("error") if isinstance(parsed.get("error"), str) else None
        outputs = _ensure_structured_outputs(
            provider=provider,
            request=request,
            outputs=outputs,
            fallback_summary=message,
            success=success,
        )
        evidence = {
            "provider_bridge": "native_cli",
            "native_cli_family": cli_family,
            "provider_output_received": bool(message.strip()),
            "workspace_root_used": workspace_root,
            **evidence,
        }
        artifacts = {
            "provider": provider,
            "path": path,
            "command": command,
            "return_code": completed.returncode,
            "invocation_kind": "native_cli",
            "native_cli_family": cli_family,
            "workspace_root": workspace_root,
            **extra_artifacts,
            **artifacts,
        }
        usage = build_usage_record(
            provider_id=provider,
            provider_family=cli_family,
            dispatch_id=request.task_id,
            prompt=request.prompt,
            response_text=message,
            reported_usage=(
                parsed.get("usage") if isinstance(parsed.get("usage"), dict) else reported_usage
            ),
        )
        return DispatchResponse(
            success=success,
            outputs=outputs,
            evidence=evidence,
            artifacts=artifacts,
            raw_transcript_ref=raw_transcript_ref,
            usage=usage,
            error=error,
        )

    if completed.returncode != 0:
        return DispatchResponse(
            success=False,
            artifacts={
                "provider": provider,
                "path": path,
                "command": command,
                "return_code": completed.returncode,
                "stdout": (completed.stdout or "").strip(),
                **extra_artifacts,
            },
            error=(completed.stderr or message or "Provider CLI failed.").strip(),
        )

    summary = message or (completed.stdout or "").strip() or f"{provider} completed {request.phase}"
    outputs = _ensure_structured_outputs(
        provider=provider,
        request=request,
        outputs={"messages": [summary]},
        fallback_summary=summary,
        success=True,
    )
    usage = build_usage_record(
        provider_id=provider,
        provider_family=cli_family,
        dispatch_id=request.task_id,
        prompt=request.prompt,
        response_text=summary,
        reported_usage=reported_usage,
    )
    return DispatchResponse(
        success=True,
        outputs=outputs,
        evidence={
            "provider_bridge": "native_cli",
            "native_cli_family": cli_family,
            "provider_output_received": bool(summary.strip()),
            "workspace_root_used": workspace_root,
        },
        artifacts={
            "provider": provider,
            "path": path,
            "command": command,
            "return_code": completed.returncode,
            "invocation_kind": "native_cli",
            "native_cli_family": cli_family,
            "workspace_root": workspace_root,
            **extra_artifacts,
        },
        usage=usage,
    )


def _should_use_ncp_handoff(
    *,
    provider: str,
    workspace_root: str,
    request: DispatchRequest,
) -> bool:
    if provider not in {"claude", "opencode"}:
        return False
    if not request.constraints.get("ncp_handoff_enabled"):
        return False
    if not (Path(workspace_root) / ".ncp" / "config.toml").exists():
        return False
    return _resolve_ncp_cli_path() is not None


def _resolve_ncp_cli_path() -> str | None:
    configured = os.environ.get("SARATHI_NCP_CLI_PATH", "").strip()
    if configured:
        return configured
    return shutil.which("ncp")


def _ncp_handoff_counterpart(provider: str, request: DispatchRequest) -> str | None:
    explicit = request.constraints.get("ncp_emit_to")
    if isinstance(explicit, str) and explicit:
        return explicit
    if provider == "claude":
        return "opencode"
    if provider == "opencode":
        return "claude"
    return None


def _summarize_ncp_handoff_payload(provider: str, request: DispatchRequest) -> str:
    context_pack = request.context_pack if isinstance(request.context_pack, dict) else {}
    agent_input = context_pack.get("agent_input") if isinstance(context_pack.get("agent_input"), dict) else {}
    relevant_files = agent_input.get("relevant_files") if isinstance(agent_input.get("relevant_files"), list) else []
    acceptance = (
        agent_input.get("acceptance_criteria")
        if isinstance(agent_input.get("acceptance_criteria"), list)
        else []
    )
    summary_parts = [
        f"task={request.task_id}",
        f"phase={request.phase}",
        f"prompt={request.prompt}",
    ]
    if relevant_files:
        summary_parts.append("files=" + ",".join(str(item) for item in relevant_files[:6]))
    if acceptance:
        summary_parts.append("acceptance=" + "; ".join(str(item) for item in acceptance[:3]))
    summary_parts.append(f"provider={provider}")
    payload = " | ".join(summary_parts)
    return payload[:600]


def _estimate_text_tokens(text: str) -> int:
    cleaned = text.strip()
    if not cleaned:
        return 0
    return max(1, ceil(len(cleaned) / 4))


def _provider_handoff_instruction(provider: str, request: DispatchRequest) -> str:
    evidence_keys = _PHASE_EVIDENCE_KEYS.get(request.phase, [])
    output_keys = _PHASE_OUTPUT_KEYS.get(request.phase, request.expected_outputs)
    purpose = request.constraints.get("purpose")
    node = request.inputs.get("node") if isinstance(request.inputs.get("node"), dict) else {}
    lines = [
        f"You are the {provider} provider bridge for Sarathi using NCP handoff transport.",
        "Respond with JSON only.",
        "Return an object with keys: success (boolean), outputs (object), evidence (object), artifacts (object), and optional error (string).",
        "Use pending NCP whisper context as the primary task truth instead of reconstructing history.",
        "Prefer bounded summaries, artifact references, and concrete results over restating inputs.",
        f"Phase: {request.phase}",
        f"Mode: {request.mode}",
        f"Task ID: {request.task_id}",
        f"Prompt: {request.prompt}",
    ]
    if isinstance(purpose, str) and purpose:
        lines.append(f"Purpose: {purpose}")
    if node:
        node_id = node.get("id")
        node_title = node.get("title")
        if node_id:
            lines.append(f"Node ID: {node_id}")
        if node_title:
            lines.append(f"Node Title: {node_title}")
    if request.token_budget is not None:
        lines.append(f"Token Budget: {request.token_budget}")
        lines.append("Stay concise and avoid replaying repo or task history.")
    if evidence_keys:
        lines.append(f"Set these boolean keys in evidence (true/false): {evidence_keys}.")
    if output_keys:
        lines.append(f"Include these keys in outputs: {output_keys}.")
    lines.append("When executing a child task, include outputs.work_unit_result with node_id, title, status, provider, and summary.")
    return "\n".join(lines)


def _ncp_handoff_token_profile(
    *,
    provider: str,
    request: DispatchRequest,
    payload: str,
    instruction: str,
) -> dict[str, Any]:
    full_prompt = _provider_prompt(provider, request)
    full_prompt_tokens = _estimate_text_tokens(full_prompt)
    handoff_instruction_tokens = _estimate_text_tokens(instruction)
    handoff_payload_tokens = _estimate_text_tokens(payload)
    compact_total = handoff_instruction_tokens + handoff_payload_tokens
    savings = max(full_prompt_tokens - compact_total, 0)
    reduction_ratio = (savings / full_prompt_tokens) if full_prompt_tokens else 0.0
    return {
        "estimator": "chars_div_4",
        "full_provider_prompt_tokens": full_prompt_tokens,
        "handoff_instruction_tokens": handoff_instruction_tokens,
        "handoff_payload_tokens": handoff_payload_tokens,
        "handoff_total_tokens": compact_total,
        "token_savings": savings,
        "reduction_ratio": round(reduction_ratio, 4),
    }


def _run_ncp_handoff_dispatch(
    *,
    provider: str,
    workspace_root: str,
    request: DispatchRequest,
) -> DispatchResponse:
    ncp_path = _resolve_ncp_cli_path()
    if not ncp_path:
        return DispatchResponse(
            success=False,
            artifacts={"provider": provider, "workspace_root": workspace_root, "ncp_handoff_used": False},
            error="NCP CLI not available for handoff dispatch.",
        )
    pipeline_id = str(request.constraints.get("ncp_pipeline_id") or f"sarathi_{request.task_id}")
    payload = _summarize_ncp_handoff_payload(provider, request)
    instruction = _provider_handoff_instruction(provider, request)
    token_profile = _ncp_handoff_token_profile(
        provider=provider,
        request=request,
        payload=payload,
        instruction=instruction,
    )
    emit_command = [
        ncp_path,
        "emit",
        "--cwd",
        workspace_root,
        "--from-agent",
        "sarathi",
        "--to",
        provider,
        "--type",
        "share",
        "--confidence",
        "0.95",
        "--pipeline-id",
        pipeline_id,
        "--payload",
        payload,
    ]
    # The emit is bookkeeping before the real handoff — cap it so it cannot
    # consume the budget the provider call needs.
    emit_timeout = min(60, request.timeout_seconds)
    emit_started = time.monotonic()
    try:
        emit_completed = subprocess.run(
            emit_command,
            capture_output=True,
            text=True,
            cwd=workspace_root,
            timeout=emit_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return DispatchResponse(
            success=False,
            artifacts={
                "provider": provider,
                "workspace_root": workspace_root,
                "ncp_handoff_used": True,
                "ncp_pipeline_id": pipeline_id,
                "emit_command": emit_command,
                "timed_out": True,
            },
            error=f"ncp emit timed out after {emit_timeout}s",
        )
    if emit_completed.returncode != 0:
        return DispatchResponse(
            success=False,
            artifacts={
                "provider": provider,
                "workspace_root": workspace_root,
                "ncp_handoff_used": True,
                "ncp_pipeline_id": pipeline_id,
                "ncp_handoff_payload": payload,
                "ncp_handoff_instruction": instruction,
                "ncp_handoff_token_profile": token_profile,
                "emit_command": emit_command,
                "emit_stdout": (emit_completed.stdout or "").strip(),
            },
            error=(emit_completed.stderr or emit_completed.stdout or "ncp emit failed").strip(),
        )

    handoff_timeout = max(30, request.timeout_seconds - int(time.monotonic() - emit_started))
    handoff_command = [
        ncp_path,
        "handoff",
        provider,
        "--cwd",
        workspace_root,
        "--pipeline-id",
        pipeline_id,
        "--instruction",
        instruction,
        "--timeout-seconds",
        str(handoff_timeout),
    ]
    emit_to = _ncp_handoff_counterpart(provider, request)
    if emit_to:
        handoff_command.extend(["--emit-to", emit_to])
    try:
        completed = subprocess.run(
            handoff_command,
            capture_output=True,
            text=True,
            cwd=workspace_root,
            timeout=handoff_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return DispatchResponse(
            success=False,
            artifacts={
                "provider": provider,
                "workspace_root": workspace_root,
                "ncp_handoff_used": True,
                "ncp_pipeline_id": pipeline_id,
                "emit_command": emit_command,
                "timed_out": True,
            },
            error=f"ncp handoff timed out after {handoff_timeout}s",
        )
    message = (completed.stdout or "").strip()
    response = _normalize_native_response(
        provider=provider,
        path=ncp_path,
        workspace_root=workspace_root,
        request=request,
        command=handoff_command,
        completed=completed,
        message=message,
    )
    response.artifacts = {
        **response.artifacts,
        "ncp_handoff_used": True,
        "ncp_pipeline_id": pipeline_id,
        "ncp_handoff_payload": payload,
        "ncp_handoff_instruction": instruction,
        "ncp_handoff_token_profile": token_profile,
        "emit_command": emit_command,
        "transport_kind": "ncp_handoff",
    }
    response.evidence = {
        **response.evidence,
        "ncp_handoff_used": True,
        "ncp_pipeline_id": pipeline_id,
        "ncp_handoff_token_profile": token_profile,
    }
    return response


def _native_cli_family(provider: str, path: str) -> str:
    executable = Path(path).name.lower()
    if provider == "copilot" and executable == "gh":
        return "github_copilot"
    if provider == "claude":
        return "claude"
    if provider == "codex":
        return "codex"
    if provider == "opencode":
        return "opencode"
    return provider


def _ensure_structured_outputs(
    *,
    provider: str,
    request: DispatchRequest,
    outputs: dict[str, Any],
    fallback_summary: str,
    success: bool,
) -> dict[str, Any]:
    normalized = dict(outputs)
    node = request.inputs.get("node") if isinstance(request.inputs.get("node"), dict) else {}
    work_unit = normalized.get("work_unit_result") if isinstance(normalized.get("work_unit_result"), dict) else {}
    work_unit_summary = work_unit.get("summary") if isinstance(work_unit.get("summary"), str) else ""
    summary = normalized.get("summary")
    if not isinstance(summary, str) or not summary.strip() or summary.strip().startswith("{"):
        summary = work_unit_summary or fallback_summary.strip() or f"{provider} handled {request.phase}"
        normalized["summary"] = summary
    messages = normalized.get("messages")
    if not isinstance(messages, list):
        normalized["messages"] = [summary]
    if request.constraints.get("purpose") == "child_task_execution":
        if not isinstance(work_unit, dict):
            normalized["work_unit_result"] = {
                "node_id": node.get("id"),
                "title": node.get("title") or request.prompt,
                "status": "completed" if success else "failed",
                "provider": provider,
                "summary": summary,
            }
    return normalized


_PHASE_EVIDENCE_KEYS: dict[str, list[str]] = {
    "Brainstorm": [
        "alternative_approaches_considered",
        "risks_identified",
        "success_criteria_defined",
        "reversibility_assessed",
    ],
    "Plan": ["checkpoint_list", "dependency_map", "rollback_plan"],
    "Build": ["tests_written", "implementation_complete", "conventions_followed"],
    "Verify": ["tests_pass", "no_regressions", "coverage_adequate"],
    "Review": ["spec_met", "code_quality_acceptable", "no_blocking_issues"],
}

_PHASE_OUTPUT_KEYS: dict[str, list[str]] = {
    "Brainstorm": ["approaches", "risks", "success_criteria"],
    "Plan": ["implementation_plan", "checkpoints", "rollback_plan"],
    "Build": ["summary", "files_changed", "tests_added"],
    "Verify": ["test_results", "summary"],
    "Review": ["verdict", "findings", "summary"],
}


# ------------------------------------------------------------------
# NCP context helpers
# ------------------------------------------------------------------

_NCP_PROVIDERS = {"claude", "opencode"}


def _ncp_available(workspace_root: str) -> bool:
    """Return True when .ncp/run.py exists at workspace_root."""
    return (Path(workspace_root) / ".ncp" / "run.py").exists()


def _ncp_prompt_instructions(
    provider: str,
    request: DispatchRequest,
    workspace_root: str | None,
) -> list[str]:
    """Build NCP open/close prompt lines for providers with bash access.

    Returns empty list when NCP is unavailable or the provider doesn't
    support bash execution (only claude and opencode do).
    """
    if workspace_root is None:
        return []
    if provider not in _NCP_PROVIDERS:
        return []
    if not _ncp_available(workspace_root):
        return []

    phase_role = PHASE_AGENT_ROLE_KEYS.get(request.phase, "pravaha")
    task_trunc = request.prompt[:80].replace('"', "'")
    intent = f"{request.phase} - {request.mode}"

    return [
        "",
        "=== NCP Context Spine ===",
        "This subagent MUST integrate with NCP (Neural Context Protocol) for cross-phase memory.",
        "BEGIN -- Load prior context by running this command before any other work:",
        f".ncp/run.py get_context '{{\"agent_id\":\"sarathi.{phase_role}\",\"role\":\"{phase_role}\",\"task\":\"{request.task_id}: {task_trunc}\",\"intent\":\"{intent}\"}}'",
        "",
        "END -- After all work is complete, persist your findings by running this command:",
        f".ncp/run.py write_memory '{{\"content\":\"<findings summary: key decisions, file paths, evidence>\",\"layer\":\"episodic\",\"src\":\"tool_result\",\"written_by\":\"{phase_role}\"}}'",
        "",
        "Include your findings summary in the JSON response as outputs.ncp_findings.",
        "========================",
    ]


def _ncp_fetch_after_dispatch(
    workspace_root: str,
    request: DispatchRequest,
    response: DispatchResponse,
) -> DispatchResponse:
    """After subagent dispatch, fetch NCP findings written by the subagent.

    Attaches fetch results to ``response.evidence.ncp_fetch_after_dispatch``
    so callers can confirm the subagent's NCP memory writes persisted.
    """
    run_path = Path(workspace_root) / ".ncp" / "run.py"
    if not run_path.exists():
        return response

    query = f"{request.phase} {request.prompt[:60]}"
    try:
        result = subprocess.run(
            [sys.executable, str(run_path), "fetch", json.dumps({"query": query, "k": 2})],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            response.evidence["ncp_fetch_after_dispatch"] = result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass

    return response


def _provider_prompt(provider: str, request: DispatchRequest, workspace_root: str | None = None) -> str:
    ncp_lines = _ncp_prompt_instructions(provider, request, workspace_root)
    evidence_keys = _PHASE_EVIDENCE_KEYS.get(request.phase, [])
    output_keys = _PHASE_OUTPUT_KEYS.get(request.phase, request.expected_outputs)
    evidence_hint = (
        f"Set these boolean keys in evidence (true/false based on your work): {evidence_keys}."
        if evidence_keys else ""
    )
    output_hint = f"Include these keys in outputs: {output_keys}." if output_keys else ""
    lines = [
        f"You are the {provider} provider bridge for Sarathi.",
        "Respond with JSON only.",
        "Return an object with keys: success (boolean), outputs (object), evidence (object), artifacts (object), and optional error (string).",
        f"Phase: {request.phase}",
        f"Mode: {request.mode}",
        f"Task ID: {request.task_id}",
        f"Prompt: {request.prompt}",
        f"Inputs: {json.dumps(request.inputs)}",
        f"Constraints: {json.dumps(request.constraints)}",
    ]
    if request.context_pack is not None:
        lines.append(f"Context Pack: {json.dumps(request.context_pack)}")
        lines.append("Use the context pack as the primary source of task truth instead of reconstructing history.")
    if request.token_budget is not None:
        lines.append(f"Token Budget: {request.token_budget}")
        lines.append("Prefer concise reasoning and artifact references over verbose restatement.")
    if evidence_hint:
        lines.append(evidence_hint)
    if output_hint:
        lines.append(output_hint)
    lines.append("When executing a child task, include outputs.work_unit_result with node_id, title, status, provider, and summary.")
    if ncp_lines:
        lines = [*ncp_lines, *lines]
    return "\n".join(lines)


# ------------------------------------------------------------------
# Provider permission config helpers
# ------------------------------------------------------------------

_DEFAULT_CLAUDE_TOOLS = [
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "LS",
    "WebFetch", "WebSearch", "TodoRead", "TodoWrite",
]

_DEFAULT_PROVIDER_PERMISSION_MODES: dict[str, dict[str, dict[str, Any]]] = {
    "claude": {
        "read_only": {
            "allowed_tools": ["Read", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "TodoRead"],
        },
        "read_write": {
            "allowed_tools": [
                "Read", "Write", "Edit", "Glob", "Grep", "LS",
                "WebFetch", "WebSearch", "TodoRead", "TodoWrite",
            ],
        },
        "full": {"allowed_tools": _DEFAULT_CLAUDE_TOOLS},
    },
    "codex": {
        "read_only": {"full_auto": False, "disable_sandbox": False},
        "read_write": {"full_auto": True, "disable_sandbox": False},
        "full": {"full_auto": True, "disable_sandbox": True},
    },
    "opencode": {
        "read_only": {
            "permission": {
                "read": "allow",
                "grep": "allow",
                "glob": "allow",
                "list": "allow",
            },
        },
        "read_write": {
            "permission": {
                "read": "allow",
                "grep": "allow",
                "glob": "allow",
                "list": "allow",
                "edit": "allow",
                "write": "allow",
            },
        },
        "full": {
            "permission": {
                "read": "allow",
                "grep": "allow",
                "glob": "allow",
                "list": "allow",
                "edit": "allow",
                "write": "allow",
                "bash": "allow",
            },
        },
    },
}


def _coerce_permission_mode(value: Any) -> PermissionMode:
    if isinstance(value, PermissionMode):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        for mode in PermissionMode:
            if normalized == mode.value:
                return mode
    return PermissionMode.READ_ONLY


def _load_permissions_policy(workspace_root: str) -> dict[str, Any]:
    """Parse permissions.yaml from policy-pack/permissions.md, if present."""
    policy_path = Path(workspace_root) / "policy-pack" / "permissions.md"
    if not policy_path.exists() or _yaml is None:
        return {}
    try:
        content = policy_path.read_text(encoding="utf-8")
        blocks = re.findall(r"```yaml\s*(.*?)\s*```", content, re.DOTALL)
        for block in blocks:
            parsed = _yaml.safe_load(block)
            if isinstance(parsed, dict) and "permissions" in parsed:
                return parsed["permissions"]
    except Exception:  # noqa: BLE001
        pass
    return {}


def _policy_for_mode(
    provider: str,
    policy: dict[str, Any],
    permission_mode: PermissionMode,
) -> dict[str, Any]:
    mode_value = permission_mode.value
    selected = deepcopy(_DEFAULT_PROVIDER_PERMISSION_MODES[provider][mode_value])
    modes = policy.get("modes")
    if isinstance(modes, dict):
        mode_policy = modes.get(mode_value)
        if isinstance(mode_policy, dict):
            selected.update(mode_policy)
        return selected

    # Backward-compatible flat policies are treated as full-mode overrides only.
    # This prevents old `full_auto: true` / `auto_approve: true` templates from
    # silently broadening read-only dispatches.
    if permission_mode == PermissionMode.FULL:
        legacy_keys = {
            "claude": {"allowed_tools"},
            "codex": {"full_auto", "disable_sandbox"},
            "opencode": {"permission", "permissions"},
        }.get(provider, set())
        for key in legacy_keys:
            if key in policy:
                selected[key] = policy[key]
    return selected


def _write_claude_settings(
    workspace_root: str,
    policy: dict[str, Any],
    permission_mode: PermissionMode,
) -> None:
    """Merge allowed_tools into .claude/settings.json (permissions.allow)."""
    mode_policy = _policy_for_mode("claude", policy, permission_mode)
    tools = mode_policy.get("allowed_tools") or _DEFAULT_PROVIDER_PERMISSION_MODES["claude"][permission_mode.value]["allowed_tools"]
    # A bare tool name allows all uses of that tool; "Tool(pattern)" scopes it.
    # ("Bash(*)" is NOT a match-everything rule in Claude Code's rule syntax.)
    allow = list(tools)
    settings_dir = Path(workspace_root) / ".claude"
    settings_dir.mkdir(exist_ok=True)
    settings_path = settings_dir / "settings.json"
    existing: dict[str, Any] = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    existing.setdefault("permissions", {})
    existing["permissions"]["allow"] = allow
    existing["permissions"].setdefault("deny", [])
    settings_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


_CODEX_CONFIG_MARKER = "# Sarathi-managed Codex permission config"


def _write_codex_config(
    workspace_root: str,
    policy: dict[str, Any],
    permission_mode: PermissionMode,
) -> None:
    """Write ~/.codex/config.yaml from policy, creating parent dirs if needed.

    Refuses to overwrite a config file Sarathi did not create — clobbering the
    user's global Codex settings is worse than skipping the policy write.
    """
    codex_dir = Path.home() / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    config_path = codex_dir / "config.yaml"
    if config_path.exists():
        try:
            first_line = config_path.read_text(encoding="utf-8").splitlines()[:1]
        except OSError:
            first_line = []
        if first_line and first_line[0].strip() != _CODEX_CONFIG_MARKER:
            logger.warning(
                "Refusing to overwrite user-managed Codex config at %s; "
                "apply the Sarathi permission policy manually or remove the file.",
                config_path,
            )
            return
    mode_policy = _policy_for_mode("codex", policy, permission_mode)
    lines: list[str] = [_CODEX_CONFIG_MARKER + "\n"]
    if mode_policy.get("full_auto", False):
        lines.append("full-auto: true\n")
    if mode_policy.get("disable_sandbox", False):
        lines.append("disable-sandbox: true\n")
    config_path.write_text("".join(lines), encoding="utf-8")


def _write_opencode_config(
    workspace_root: str,
    policy: dict[str, Any],
    permission_mode: PermissionMode,
) -> None:
    """Merge mode-specific tool permissions into opencode.json at workspace root."""
    config_path = Path(workspace_root) / "opencode.json"
    existing: dict[str, Any] = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    existing.pop("autoapprove", None)
    mode_policy = _policy_for_mode("opencode", policy, permission_mode)
    permissions = mode_policy.get("permission") or mode_policy.get("permissions") or {}
    if isinstance(permissions, dict):
        existing["permission"] = dict(permissions)
    config_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


def ensure_provider_permissions(
    workspace_root: str,
    permission_mode: PermissionMode | str = PermissionMode.READ_ONLY,
) -> dict[str, str]:
    """
    Read policy-pack/permissions.md and write provider-native config files.

    Returns a dict mapping provider name → config path written (for status reporting).
    Silently skips any provider whose section is absent from the policy.
    """
    policy = _load_permissions_policy(workspace_root)
    mode = _coerce_permission_mode(permission_mode)
    written: dict[str, str] = {}
    if "claude" in policy:
        _write_claude_settings(workspace_root, policy["claude"], mode)
        written["claude"] = str(Path(workspace_root) / ".claude" / "settings.json")
    if "codex" in policy:
        _write_codex_config(workspace_root, policy["codex"], mode)
        written["codex"] = str(Path.home() / ".codex" / "config.yaml")
    if "opencode" in policy:
        _write_opencode_config(workspace_root, policy["opencode"], mode)
        written["opencode"] = str(Path(workspace_root) / "opencode.json")
    return written


def _parse_json_dict(text: str) -> dict[str, Any] | None:
    if not text.strip():
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sarathi native provider bridge")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--workspace-root", required=True)
    args = parser.parse_args(argv)

    try:
        payload = json.load(sys.stdin)
        request = DispatchRequest(
            mode=payload["mode"],
            task_id=payload["task_id"],
            phase=payload["phase"],
            prompt=payload["prompt"],
            inputs=payload.get("inputs", {}),
            expected_outputs=payload.get("expected_outputs", []),
            constraints=payload.get("constraints", {}),
            timeout_seconds=int(payload.get("timeout_seconds", 300) or 300),
            retry_budget=int(payload.get("retry_budget", 0) or 0),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        # Emit a structured failure instead of a stack trace so the caller can
        # surface the error as a normal dispatch failure.
        print(json.dumps({
            "success": False,
            "outputs": {},
            "evidence": {},
            "artifacts": {"provider": args.provider},
            "error": f"Invalid bridge payload on stdin: {type(exc).__name__}: {exc}",
        }))
        return 1
    response = dispatch_via_cli_bridge(
        provider=args.provider,
        path=args.path,
        workspace_root=args.workspace_root,
        request=request,
    )
    print(
        json.dumps(
            {
                "success": response.success,
                "outputs": response.outputs,
                "evidence": response.evidence,
                "artifacts": response.artifacts,
                "raw_transcript_ref": response.raw_transcript_ref,
                "usage": response.usage.to_artifact() if response.usage else None,
                "error": response.error,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
