"""Dispatcher abstractions and local runtime-backed implementations."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from typing import Any

_DISPATCH_TIMEOUT = int(os.environ.get("SARATHI_DISPATCH_TIMEOUT", "300"))


class DispatchTimeoutError(Exception):
    """Raised when a provider dispatch call exceeds the configured timeout."""

try:
    from .runtime import DispatchRequest, DispatchResponse
    from .runtime.providers import (
        ConfiguredProviderAdapter,
        LocalProviderAdapter,
        ProviderAdapter,
    )
except ImportError:
    from runtime import DispatchRequest, DispatchResponse
    from runtime.providers import (
        ConfiguredProviderAdapter,
        LocalProviderAdapter,
        ProviderAdapter,
    )


@dataclass
class TaskSpec:
    id: str
    description: str
    inputs: dict[str, Any] = field(default_factory=dict)
    expected_outputs: dict[str, Any] = field(default_factory=dict)
    context_ref: str | None = None
    escalation_policy: str | None = None


@dataclass
class ExploreResult:
    messages: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecuteResult:
    outputs: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    success: bool = False


class Dispatcher(ABC):
    @abstractmethod
    def dispatch_explore(self, spec: TaskSpec) -> ExploreResult:
        raise NotImplementedError

    @abstractmethod
    def dispatch_execute(self, spec: TaskSpec) -> ExecuteResult:
        raise NotImplementedError

    @abstractmethod
    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        raise NotImplementedError


class NullDispatcher(Dispatcher):
    def dispatch_explore(self, spec: TaskSpec) -> ExploreResult:
        return ExploreResult()

    def dispatch_execute(self, spec: TaskSpec) -> ExecuteResult:
        return ExecuteResult()

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        return DispatchResponse(success=False, error="No dispatcher configured")


class LocalDispatcher(Dispatcher):
    """Deterministic local dispatcher for early orchestration slices."""

    def __init__(
        self,
        provider: ProviderAdapter | None = None,
        provider_config: Mapping[str, Any] | None = None,
    ):
        self.provider = provider or self._provider_from_config(provider_config)

    def _provider_from_config(
        self, provider_config: Mapping[str, Any] | None
    ) -> ProviderAdapter:
        if provider_config:
            return ConfiguredProviderAdapter(provider_config)
        return LocalProviderAdapter()

    def dispatch_explore(self, spec: TaskSpec) -> ExploreResult:
        response = self.dispatch(
            DispatchRequest(
                mode="explore",
                task_id=spec.id,
                phase=spec.inputs.get("phase", "unknown"),
                prompt=spec.description,
                inputs=spec.inputs,
                expected_outputs=list(spec.expected_outputs),
            )
        )
        return ExploreResult(
            messages=response.outputs.get("messages", []),
            confidence=float(response.outputs.get("confidence", 0.0)),
            evidence=response.evidence,
            artifacts=response.artifacts,
        )

    def dispatch_execute(self, spec: TaskSpec) -> ExecuteResult:
        response = self.dispatch(
            DispatchRequest(
                mode="execute",
                task_id=spec.id,
                phase=spec.inputs.get("phase", "unknown"),
                prompt=spec.description,
                inputs=spec.inputs,
                expected_outputs=list(spec.expected_outputs),
            )
        )
        return ExecuteResult(
            outputs=response.outputs,
            artifacts=response.artifacts,
            success=response.success,
        )

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        # The provider's own subprocess timeout (request.timeout_seconds) is the
        # primary budget and should fire first, returning a structured failure.
        # This outer guard only catches providers that ignore their budget, so
        # give it headroom above the request budget.
        timeout = max(_DISPATCH_TIMEOUT, request.timeout_seconds + 30)
        pool = ThreadPoolExecutor(max_workers=1)
        future: Future[DispatchResponse] = pool.submit(self.provider.dispatch, request)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            raise DispatchTimeoutError(
                f"Provider dispatch timed out after {timeout}s "
                f"(task={request.task_id}, phase={request.phase})"
            )
        finally:
            # wait=False: a `with` block (shutdown(wait=True)) would block here
            # until the hung provider call returned, making the timeout cosmetic.
            pool.shutdown(wait=False, cancel_futures=True)
