"""Dispatcher abstractions and local runtime-backed implementations."""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field, replace as _dc_replace
from typing import Any

_DISPATCH_TIMEOUT = int(os.environ.get("SARATHI_DISPATCH_TIMEOUT", "300"))

# Module-level so tests can monkeypatch the backoff sleep.
_sleep = time.sleep

# Substrings (case-insensitive) that indicate a transient provider failure
# worth retrying — rate limits, overload, and transport hiccups.
_TRANSIENT_ERROR_PATTERNS = (
    "rate limit",
    "rate_limit",
    "overloaded",
    "429",
    "529",
    "connection reset",
    "temporarily unavailable",
)


class DispatchTimeoutError(Exception):
    """Raised when a provider dispatch call exceeds the configured timeout."""


class MissingHarnessError(ValueError):
    """Raised when a child-task/graph-node dispatch has no harness_id.

    Per the "declare before dispatch" invariant (see src/harness.py and
    CLAUDE.md), every graph node dispatched during BUILD-phase graph
    execution (FANOUT branches, JUDGE candidates, SYNTHESIZE, etc.) must
    carry the harness_id of a HarnessConfig compiled before it ran. This is
    scoped to dispatches tagged ``constraints["purpose"] ==
    "child_task_execution"`` — the marker TaskGraphExecutor already applies
    to every node it dispatches — so it does not reach ahead into unrelated
    dispatch paths (e.g. the single top-level phase dispatches in
    src/phases/*.py, or the service layer's worker dispatch) that don't yet
    thread a harness_id through.
    """


def require_harness_id(request: "DispatchRequest") -> None:
    """Reject a child-task dispatch request that has no harness_id.

    No-op for any request that isn't tagged as child-task/graph-node work
    (``constraints["purpose"] == "child_task_execution"``); callers decide
    where in the dispatch chain this scoped check applies.
    """
    if request.constraints.get("purpose") != "child_task_execution":
        return
    if not request.harness_id:
        raise MissingHarnessError(
            f"DispatchRequest for task {request.task_id!r} (phase={request.phase!r}) "
            "is a child-task/graph-node dispatch with no harness_id — a HarnessConfig "
            "must be compiled (src/harness.py) and propagated before dispatch."
        )


def _reported_cost_from_artifacts(artifacts: Mapping[str, Any] | None) -> float | None:
    """Extract a provider's self-reported dollar cost from dispatch artifacts.

    claude's CLI bridge surfaces `total_cost_usd` from its result envelope
    into `DispatchResponse.artifacts`; other providers may report a plain
    `cost_usd`. Either wins over a pricing-table computation.
    """
    if not isinstance(artifacts, Mapping):
        return None
    for key in ("total_cost_usd", "cost_usd"):
        value = artifacts.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _is_transient_failure(
    response_or_none: "DispatchResponse | None",
    exc_or_none: Exception | None,
) -> bool:
    """Return True when a failed dispatch looks retriable.

    Transient: a DispatchTimeoutError was raised, the response has
    ``artifacts["timed_out"] is True``, or ``response.error`` matches a
    known rate-limit/overload/transport pattern.
    """
    if isinstance(exc_or_none, DispatchTimeoutError):
        return True
    if response_or_none is None:
        return False
    if response_or_none.success:
        return False
    if response_or_none.artifacts.get("timed_out") is True:
        return True
    error = response_or_none.error
    if isinstance(error, str):
        lowered = error.lower()
        if any(pattern in lowered for pattern in _TRANSIENT_ERROR_PATTERNS):
            return True
    return False

try:
    from .runtime import DispatchRequest, DispatchResponse
    from .runtime.pricing import PricingTable, resolve_cost
    from .runtime.providers import (
        ConfiguredProviderAdapter,
        LocalProviderAdapter,
        ProviderAdapter,
    )
except ImportError:
    from runtime import DispatchRequest, DispatchResponse
    from runtime.pricing import PricingTable, resolve_cost
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
        # Cost resolution is policy-driven: the model-routing section (which
        # already reaches us as provider_config) may carry a `pricing:`
        # mapping. We never hardcode a provider name or a dollar figure here
        # — see src/runtime/pricing.py for parsing/lookup.
        self._provider_config: Mapping[str, Any] = provider_config or {}
        self._pricing_table = PricingTable.from_config(provider_config)

    def _provider_from_config(
        self, provider_config: Mapping[str, Any] | None
    ) -> ProviderAdapter:
        if provider_config:
            return ConfiguredProviderAdapter(provider_config)
        return LocalProviderAdapter()

    def _model_for_provider(self, provider_id: str | None) -> str | None:
        """Best-effort model name for a provider, from its routing config.

        Provider configs (see policy-pack/EXAMPLE/model-routing.md) declare a
        fixed `model` per provider entry; this mirrors that lookup without
        assuming any particular provider exists.
        """
        if not provider_id:
            return None
        providers_cfg = self._provider_config.get("providers")
        if not isinstance(providers_cfg, Mapping):
            return None
        provider_cfg = providers_cfg.get(provider_id)
        if not isinstance(provider_cfg, Mapping):
            return None
        model = provider_cfg.get("model")
        return model if isinstance(model, str) and model else None

    def _apply_cost(self, response: "DispatchResponse") -> None:
        """Fill in `usage.cost_usd` when it isn't already known.

        Precedence: a provider's self-reported cost (already present on the
        usage record, or surfaced in response.artifacts as `total_cost_usd` /
        `cost_usd`) always wins over a pricing-table computation, which wins
        over leaving it unpriced (None).
        """
        usage = response.usage
        if usage is None or usage.cost_usd is not None:
            return
        reported = _reported_cost_from_artifacts(response.artifacts)
        if reported is not None:
            usage.cost_usd = reported
            return
        if self._pricing_table.is_empty():
            return
        model = self._model_for_provider(usage.provider_id)
        usage.cost_usd = resolve_cost(usage, usage.provider_id, model, self._pricing_table)

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
        retry_budget = max(0, request.retry_budget)
        transient_failures: list[str] = []

        for attempt in range(retry_budget + 1):
            response: DispatchResponse | None = None
            exc: Exception | None = None
            try:
                response = self._dispatch_once(request)
            except DispatchTimeoutError as timeout_exc:
                exc = timeout_exc

            transient = _is_transient_failure(response, exc)

            if not transient:
                if exc is not None:
                    raise exc
                if transient_failures:
                    response.artifacts["dispatch_retries"] = {
                        "attempts": attempt + 1,
                        "transient_failures": transient_failures,
                    }
                return response

            if attempt < retry_budget:
                # Still transient and retry budget remains — record what
                # happened and back off before retrying the same provider.
                if exc is not None:
                    transient_failures.append(str(exc))
                else:
                    transient_failures.append(response.error or "transient failure")

                backoff = min(2 ** attempt, 8)
                _sleep(backoff)
                continue

            # Retry budget exhausted on a transient failure. Before giving up
            # on this provider entirely, try any fallback providers the
            # request carries (see _attempt_provider_fallback) — this never
            # fires for non-transient failures, which return above.
            fallback_response = self._attempt_provider_fallback(request, response, exc)
            if fallback_response is not None:
                if transient_failures:
                    fallback_response.artifacts.setdefault(
                        "dispatch_retries",
                        {"attempts": attempt + 1, "transient_failures": list(transient_failures)},
                    )
                return fallback_response

            if exc is not None:
                raise exc
            if transient_failures:
                response.artifacts["dispatch_retries"] = {
                    "attempts": attempt + 1,
                    "transient_failures": transient_failures,
                }
            return response

        # Unreachable: the loop always returns or raises on its last iteration.
        raise AssertionError("LocalDispatcher.dispatch: retry loop exited without returning")

    def _attempt_provider_fallback(
        self,
        request: DispatchRequest,
        response: DispatchResponse | None,
        exc: Exception | None,
    ) -> DispatchResponse | None:
        """Retry a transiently-exhausted dispatch against fallback providers.

        Reads ``request.constraints["fallback_providers"]`` — an ordered list
        of provider ids. This is the seam where a HarnessConfig's resolved
        ``fallback_agents`` (see src/harness.py, health-ordered) are expected
        to land on the request wherever the harness binding is applied to it
        (e.g. alongside ``constraints["provider"]``); nothing upstream
        populates it yet (see delivery notes), so today this is a no-op until
        a caller sets it.

        Tries each fallback once, in the given order, stopping at the first
        success. Returns ``None`` (caller keeps the original failure/timeout)
        when there are no fallback candidates or all of them also fail — this
        method never raises on a fallback's own timeout, it just moves on to
        the next candidate.
        """
        fallback_providers = request.constraints.get("fallback_providers")
        if not isinstance(fallback_providers, (list, tuple)) or not fallback_providers:
            return None

        original_provider = request.constraints.get("provider")
        prior_errors: list[str] = []
        if exc is not None:
            prior_errors.append(str(exc))
        elif response is not None:
            prior_errors.append(response.error or "transient failure")

        for fallback_provider in fallback_providers:
            if not isinstance(fallback_provider, str) or not fallback_provider:
                continue
            if fallback_provider == original_provider:
                continue

            fallback_request = _dc_replace(
                request,
                constraints={**request.constraints, "provider": fallback_provider},
            )
            try:
                fallback_response = self._dispatch_once(fallback_request)
            except DispatchTimeoutError as fallback_timeout:
                prior_errors.append(str(fallback_timeout))
                continue

            if fallback_response.success:
                fallback_response.artifacts["served_by_fallback"] = fallback_provider
                fallback_response.artifacts["fallback_attempted"] = {
                    "original_provider": original_provider,
                    "fallback_used": fallback_provider,
                    "prior_errors": prior_errors,
                }
                return fallback_response

            prior_errors.append(fallback_response.error or "transient failure")

        return None

    def _dispatch_once(self, request: DispatchRequest) -> DispatchResponse:
        # The provider's own subprocess timeout (request.timeout_seconds) is the
        # primary budget and should fire first, returning a structured failure.
        # This outer guard only catches providers that ignore their budget, so
        # give it headroom above the request budget.
        timeout = max(_DISPATCH_TIMEOUT, request.timeout_seconds + 30)
        pool = ThreadPoolExecutor(max_workers=1)
        future: Future[DispatchResponse] = pool.submit(self.provider.dispatch, request)
        try:
            response = future.result(timeout=timeout)
            self._apply_cost(response)
            return response
        except FuturesTimeoutError:
            raise DispatchTimeoutError(
                f"Provider dispatch timed out after {timeout}s "
                f"(task={request.task_id}, phase={request.phase})"
            )
        finally:
            # wait=False: a `with` block (shutdown(wait=True)) would block here
            # until the hung provider call returned, making the timeout cosmetic.
            pool.shutdown(wait=False, cancel_futures=True)
