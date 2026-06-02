"""CLI bridge that normalizes native provider invocations into Sarathi dispatch output."""

from __future__ import annotations

import argparse
import json
import http.client
from math import ceil
import os
import shutil
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
    from ..contracts import DispatchRequest, DispatchResponse, build_usage_record
    from ..agent_roles import PHASE_AGENT_ROLE_KEYS
except ImportError:
    from runtime.contracts import DispatchRequest, DispatchResponse, build_usage_record
    from runtime.agent_roles import PHASE_AGENT_ROLE_KEYS


def dispatch_via_cli_bridge(
    *,
    provider: str,
    path: str,
    workspace_root: str,
    request: DispatchRequest,
) -> DispatchResponse:
    provider_name = provider.strip().lower()
    if provider_name == "codex":
        return _run_codex(path=path, workspace_root=workspace_root, request=request)
    if provider_name == "copilot":
        return _run_copilot(path=path, workspace_root=workspace_root, request=request)
    if provider_name == "claude":
        return _run_claude(path=path, workspace_root=workspace_root, request=request)
    if provider_name == "opencode":
        return _run_opencode(path=path, workspace_root=workspace_root, request=request)
    return DispatchResponse(
        success=False,
        artifacts={"provider": provider_name, "path": path},
        error=f"Native provider bridge is not implemented for '{provider_name}'",
    )


def _run_codex(*, path: str, workspace_root: str, request: DispatchRequest) -> DispatchResponse:
    prompt = _provider_prompt("codex", request, workspace_root)
    with tempfile.NamedTemporaryFile("w+", suffix="-sarathi-codex.txt", delete=False) as handle:
        output_path = Path(handle.name)
    command = [
        path,
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "-o", str(output_path),
        prompt,
    ]
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=workspace_root,
        timeout=request.timeout_seconds,
        check=False,
    )
    message = _read_text(output_path)
    try:
        output_path.unlink(missing_ok=True)
    except OSError:
        pass
    response = _normalize_native_response(
        provider="codex",
        path=path,
        workspace_root=workspace_root,
        request=request,
        command=command,
        completed=completed,
        message=message,
    )
    return _ncp_fetch_after_dispatch(workspace_root, request, response)


def _run_copilot(*, path: str, workspace_root: str, request: DispatchRequest) -> DispatchResponse:
    prompt = _provider_prompt("copilot", request, workspace_root)
    executable = Path(path).name
    if executable == "gh":
        command = [path, "copilot", "--", "-p", prompt]
    else:
        command = [path, "-p", prompt]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=workspace_root,
        timeout=request.timeout_seconds,
        check=False,
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
    command = [
        path,
        "-p",
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "--add-dir", workspace_root,
        "--",
        prompt,
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=workspace_root,
        timeout=request.timeout_seconds,
        check=False,
    )
    # Unwrap the Claude Code JSON envelope: {"type":"result","result":"...","is_error":...}
    message = _extract_claude_result(completed.stdout)
    response = _normalize_native_response(
        provider="claude",
        path=path,
        workspace_root=workspace_root,
        request=request,
        command=command,
        completed=completed,
        message=message,
    )
    return _ncp_fetch_after_dispatch(workspace_root, request, response)


def _run_opencode(*, path: str, workspace_root: str, request: DispatchRequest) -> DispatchResponse:
    """Bridge for OpenCode via CLI (`opencode run`).

    Uses `opencode run -c --dangerously-skip-permissions --dir <workspace> -- <prompt>`
    which is the recommended way to invoke OpenCode from scripts.
    """
    if _should_use_ncp_handoff(provider="opencode", workspace_root=workspace_root, request=request):
        return _run_ncp_handoff_dispatch(
            provider="opencode",
            workspace_root=workspace_root,
            request=request,
        )
    prompt = _provider_prompt("opencode", request, workspace_root)
    command = [
        path,
        "run",
        "-c",
        "--dangerously-skip-permissions",
        "--dir", workspace_root,
        "--",
        prompt,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=request.timeout_seconds,
            cwd=workspace_root,
        )
        message = result.stdout if result.returncode == 0 else f"Error: {result.stderr}"
        return_code = result.returncode
    except subprocess.TimeoutExpired:
        message = f"Timeout after {request.timeout_seconds}s"
        return_code = 124
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        return_code = 1

    completed = subprocess.CompletedProcess(command, return_code, stdout=message, stderr="")
    response = _normalize_native_response(
        provider="opencode",
        path=path,
        workspace_root=workspace_root,
        request=request,
        command=command,
        completed=completed,
        message=message,
    )
    return _ncp_fetch_after_dispatch(workspace_root, request, response)


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
        return json.loads(resp.read())


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


def _extract_claude_result(raw_output: str) -> str:
    """Extract the inner response from a Claude Code --output-format json envelope.

    Claude Code wraps output in {"type":"result","result":"...","is_error":...}.
    If the output is not a Claude envelope (e.g. a mock or older version), pass through.
    """
    raw = raw_output.strip()
    if not raw:
        return ""
    envelope = _parse_json_dict(raw)
    if envelope is None:
        return raw  # plain text — return as-is
    # Only unwrap if it looks like a Claude Code envelope
    if envelope.get("type") == "result" and "result" in envelope:
        if envelope.get("is_error"):
            return ""
        result = envelope.get("result", "")
        return str(result).strip() if result is not None else ""
    # Raw JSON from provider (mock or structured response) — pass through as-is
    return raw


def _normalize_native_response(
    *,
    provider: str,
    path: str,
    workspace_root: str,
    request: DispatchRequest,
    command: list[str],
    completed: subprocess.CompletedProcess[str],
    message: str,
) -> DispatchResponse:
    parsed = _parse_json_dict(message)
    cli_family = _native_cli_family(provider, path)
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
            **artifacts,
        }
        usage = build_usage_record(
            provider_id=provider,
            provider_family=cli_family,
            dispatch_id=request.task_id,
            prompt=request.prompt,
            response_text=message,
            reported_usage=parsed.get("usage") if isinstance(parsed.get("usage"), dict) else None,
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
    emit_completed = subprocess.run(
        emit_command,
        capture_output=True,
        text=True,
        cwd=workspace_root,
        timeout=request.timeout_seconds,
        check=False,
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
        str(request.timeout_seconds),
    ]
    emit_to = _ncp_handoff_counterpart(provider, request)
    if emit_to:
        handoff_command.extend(["--emit-to", emit_to])
    completed = subprocess.run(
        handoff_command,
        capture_output=True,
        text=True,
        cwd=workspace_root,
        timeout=request.timeout_seconds,
        check=False,
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
