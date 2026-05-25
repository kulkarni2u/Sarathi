"""Anthropic/Claude SDK-backed provider adapter with CLI fallback."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import subprocess
from typing import Any
from uuid import uuid4

try:
    from ..contracts import DispatchRequest, DispatchResponse, build_usage_record
except ImportError:
    from runtime.contracts import DispatchRequest, DispatchResponse, build_usage_record

from .base import ProviderAdapter, ProviderCapabilities, ProviderSession
from .cli_bridge import dispatch_via_cli_bridge


class AnthropicSdkProviderAdapter(ProviderAdapter):
    """Dispatch through the Anthropic SDK/API, with optional Claude CLI fallback."""

    def __init__(
        self,
        *,
        workspace_root: str,
        provider_path: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        node_command: str = "node",
        helper_script: str | None = None,
        timeout_seconds: int = 300,
        fallback_to_cli: bool = True,
    ):
        self._name = "claude"
        self.workspace_root = workspace_root
        self.provider_path = provider_path
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.node_command = node_command
        self.helper_script = helper_script or self._default_helper_script()
        self.timeout_seconds = timeout_seconds
        self.fallback_to_cli = fallback_to_cli

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            transport_kind="sdk",
            supports_workspace_execution=True,
            supports_structured_output=True,
            declared_capabilities=("research", "critique", "review", "sdk_runtime"),
        )

    def create_session(self, request: DispatchRequest | None = None) -> ProviderSession:
        return ProviderSession(
            session_id=f"anthropic-sdk-{uuid4().hex[:12]}",
            provider_name=self.name,
            transport_kind="sdk",
            status="ready",
            metadata={
                "workspace_root": self.workspace_root,
                "task_id": request.task_id if request else None,
            },
        )

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        if request.constraints.get("ncp_handoff_enabled") and self.provider_path:
            return dispatch_via_cli_bridge(
                provider="claude",
                path=self.provider_path,
                workspace_root=self.workspace_root,
                request=request,
            )
        session = self.create_session(request)
        session.status = "running"
        bridge_payload = {
            "task_id": request.task_id,
            "phase": request.phase,
            "mode": request.mode,
            "prompt": request.prompt,
            "title": f"Sarathi {request.phase} {request.task_id}",
            "timeout_seconds": request.timeout_seconds,
            "session_id": session.session_id,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
        }

        try:
            result = self._run_sdk_bridge(bridge_payload, timeout_seconds=request.timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            result = {
                "success": False,
                "artifacts": {
                    "invocation_kind": "sdk",
                    "sdk_family": "anthropic",
                },
                "error": str(exc),
            }

        if bool(result.get("success")):
            session.status = "closed"
            return self._response_from_sdk_result(request, session, result)

        session.status = "failed"
        sdk_error = str(result.get("error") or "Anthropic SDK dispatch failed")
        if self.fallback_to_cli and self.provider_path:
            fallback = dispatch_via_cli_bridge(
                provider="claude",
                path=self.provider_path,
                workspace_root=self.workspace_root,
                request=request,
            )
            fallback.artifacts = {
                **fallback.artifacts,
                "sdk_error": sdk_error,
                "sdk_fallback_used": True,
                "transport_kind": "cli",
            }
            fallback.evidence = {
                **fallback.evidence,
                "sdk_error": sdk_error,
                "sdk_fallback_used": True,
            }
            return fallback

        return DispatchResponse(
            success=False,
            artifacts={
                "provider": self.name,
                "invocation_kind": "sdk",
                "sdk_family": "anthropic",
                "transport_kind": "sdk",
                "provider_session_id": session.session_id,
            },
            error=sdk_error,
        )

    def _response_from_sdk_result(
        self,
        request: DispatchRequest,
        session: ProviderSession,
        result: Mapping[str, Any],
    ) -> DispatchResponse:
        outputs = result.get("outputs") if isinstance(result.get("outputs"), Mapping) else {}
        evidence = result.get("evidence") if isinstance(result.get("evidence"), Mapping) else {}
        artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), Mapping) else {}
        messages = outputs.get("messages") if isinstance(outputs.get("messages"), list) else []
        response_text = "\n".join(str(message) for message in messages if isinstance(message, str))
        usage = build_usage_record(
            provider_id=self.name,
            provider_family="sdk",
            dispatch_id=request.task_id,
            prompt=request.prompt,
            response_text=response_text,
            reported_usage=result.get("usage") if isinstance(result.get("usage"), Mapping) else None,
        )
        return DispatchResponse(
            success=True,
            outputs=dict(outputs),
            evidence={
                **dict(evidence),
                "provider_session_id": evidence.get("provider_session_id", session.session_id),
                "transport_kind": "sdk",
            },
            artifacts={
                "provider": self.name,
                "invocation_kind": "sdk",
                "sdk_family": "anthropic",
                "transport_kind": "sdk",
                "workspace_root": self.workspace_root,
                **dict(artifacts),
            },
            raw_transcript_ref=result.get("raw_transcript_ref") if isinstance(result.get("raw_transcript_ref"), str) else None,
            usage=usage,
            error=result.get("error") if isinstance(result.get("error"), str) else None,
        )

    def _run_sdk_bridge(self, payload: Mapping[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
        helper_script = Path(self.helper_script)
        if not helper_script.exists():
            raise FileNotFoundError(f"Anthropic SDK helper not found: {helper_script}")
        completed = subprocess.run(
            [self.node_command, str(helper_script)],
            input=json.dumps(dict(payload)),
            capture_output=True,
            text=True,
            cwd=self.workspace_root,
            timeout=timeout_seconds,
            check=False,
        )
        raw_output = completed.stdout.strip() or "{}"
        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            stderr = completed.stderr.strip()
            raise RuntimeError(
                f"Anthropic SDK helper returned non-JSON output: {stderr or raw_output}"
            ) from exc
        if completed.returncode != 0 and "error" not in parsed:
            parsed = {
                "success": False,
                "artifacts": {"invocation_kind": "sdk", "sdk_family": "anthropic"},
                "error": completed.stderr.strip() or f"Anthropic SDK helper exited with {completed.returncode}",
            }
        return parsed if isinstance(parsed, dict) else {"success": False, "error": "Invalid SDK bridge payload"}

    def _default_helper_script(self) -> str:
        repo_root = Path(__file__).resolve().parents[3]
        return str(repo_root / "desktop" / "scripts" / "anthropic-sdk-dispatch.mjs")
