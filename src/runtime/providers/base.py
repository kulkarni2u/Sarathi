"""Provider adapter contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

try:
    from ..contracts import DispatchRequest, DispatchResponse
except ImportError:
    from runtime.contracts import DispatchRequest, DispatchResponse

ProviderTransportKind = Literal[
    "deterministic",
    "sdk",
    "api",
    "cli",
    "command",
    "external",
]


@dataclass(frozen=True)
class ProviderCapabilities:
    """Explicit runtime capability metadata for a provider adapter."""

    transport_kind: ProviderTransportKind = "deterministic"
    supports_streaming: bool = False
    supports_tool_calls: bool = False
    supports_interrupt: bool = False
    supports_resume: bool = False
    supports_session_persistence: bool = False
    supports_workspace_execution: bool = False
    supports_structured_output: bool = True
    supports_human_approval_callbacks: bool = False
    declared_capabilities: tuple[str, ...] = ()

    def to_metadata(self) -> dict[str, Any]:
        return {
            "transport_kind": self.transport_kind,
            "supports_streaming": self.supports_streaming,
            "supports_tool_calls": self.supports_tool_calls,
            "supports_interrupt": self.supports_interrupt,
            "supports_resume": self.supports_resume,
            "supports_session_persistence": self.supports_session_persistence,
            "supports_workspace_execution": self.supports_workspace_execution,
            "supports_structured_output": self.supports_structured_output,
            "supports_human_approval_callbacks": self.supports_human_approval_callbacks,
            "declared_capabilities": list(self.declared_capabilities),
        }


@dataclass
class ProviderSession:
    """Lightweight session contract for future SDK-backed runtimes."""

    session_id: str
    provider_name: str
    transport_kind: ProviderTransportKind
    status: Literal["ready", "running", "closed", "failed"] = "ready"
    metadata: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(ABC):
    """Abstract provider behind dispatcher execution."""

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    @abstractmethod
    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        raise NotImplementedError

    def create_session(self, request: DispatchRequest | None = None) -> ProviderSession | None:
        return None

    def send_session_input(
        self,
        session: ProviderSession,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> DispatchResponse:
        return DispatchResponse(
            success=False,
            artifacts={
                "provider": self.name,
                "session_id": session.session_id,
                "transport_kind": session.transport_kind,
                "metadata": metadata or {},
            },
            error=f"Provider '{self.name}' does not support session input",
        )

    def close_session(self, session: ProviderSession) -> None:
        session.status = "closed"
