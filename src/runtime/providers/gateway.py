"""OpenAI-compatible gateway provider adapter (pure-Python, httpx-backed).

Dispatches to any OpenAI-compatible Chat Completions endpoint via ``base_url``
(OpenRouter / Ollama / vLLM / Azure). No Node.js or CLI involved — the HTTP API
is called directly with ``httpx``.
"""

from __future__ import annotations

from collections.abc import Mapping
import os

import httpx

try:
    from ..contracts import DispatchRequest, DispatchResponse, build_usage_record
except ImportError:
    from runtime.contracts import DispatchRequest, DispatchResponse, build_usage_record

from .base import ProviderAdapter, ProviderCapabilities


class GatewayProviderAdapter(ProviderAdapter):
    """Dispatch through any OpenAI-compatible Chat Completions endpoint."""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        model: str,
        api_key_env: str | None = None,
        timeout_seconds: int = 120,
        extra_headers: Mapping[str, str] | None = None,
        declared_capabilities: tuple[str, ...] = ("coding", "planning", "review", "api_runtime"),
    ):
        if not name:
            raise ValueError("Provider name must be non-empty")
        if not base_url:
            raise ValueError("Gateway provider requires a non-empty base_url")
        if not model:
            raise ValueError("Gateway provider requires a non-empty model")
        self._name = name
        self.base_url = base_url
        self.model = model
        self.api_key_env = api_key_env or None
        self.timeout_seconds = timeout_seconds
        self.extra_headers = dict(extra_headers) if extra_headers else {}
        self._declared_capabilities = tuple(declared_capabilities)

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            transport_kind="api",
            supports_structured_output=True,
            supports_workspace_execution=False,
            declared_capabilities=self._declared_capabilities,
        )

    def _chat_completions_url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        headers.update(self.extra_headers)
        if self.api_key_env:
            api_key = os.environ.get(self.api_key_env, "")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _failure_artifacts(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "invocation_kind": "api",
            "transport_kind": "api",
            "base_url": self.base_url,
            "model": self.model,
        }

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        messages = [
            {
                "role": "system",
                "content": f"Sarathi {request.mode} dispatch for phase '{request.phase}'.",
            },
            {"role": "user", "content": request.prompt},
        ]
        payload = {"model": self.model, "messages": messages}
        timeout = request.timeout_seconds or self.timeout_seconds

        try:
            response = httpx.post(
                self._chat_completions_url(),
                json=payload,
                headers=self._build_headers(),
                timeout=timeout,
            )
        except Exception as exc:  # network, timeout, etc.
            return DispatchResponse(
                success=False,
                artifacts=self._failure_artifacts(),
                error=f"Gateway provider '{self.name}' request failed: {exc}",
            )

        if response.status_code < 200 or response.status_code >= 300:
            return DispatchResponse(
                success=False,
                artifacts=self._failure_artifacts(),
                error=(
                    f"Gateway provider '{self.name}' returned HTTP {response.status_code}: "
                    f"{response.text[:500]}"
                ),
            )

        try:
            body = response.json()
        except Exception as exc:
            return DispatchResponse(
                success=False,
                artifacts=self._failure_artifacts(),
                error=f"Gateway provider '{self.name}' returned non-JSON body: {exc}",
            )

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            return DispatchResponse(
                success=False,
                artifacts=self._failure_artifacts(),
                error=f"Gateway provider '{self.name}' response missing message content: {exc}",
            )
        if content is None:
            content = ""

        reported_usage = body.get("usage") if isinstance(body.get("usage"), Mapping) else None

        return DispatchResponse(
            success=True,
            outputs={
                "messages": [content],
                "provider": self.name,
                "model": self.model,
            },
            evidence={"transport_kind": "api", "gateway_dispatch": True},
            artifacts={
                "provider": self.name,
                "invocation_kind": "api",
                "transport_kind": "api",
                "base_url": self.base_url,
                "model": self.model,
            },
            usage=build_usage_record(
                provider_id=self.name,
                provider_family="api",
                dispatch_id=request.task_id,
                prompt=request.prompt,
                response_text=content,
                reported_usage=reported_usage,
            ),
        )
