"""Tests for retry/backoff, fallback-agent failover, and provider health tracking."""
from __future__ import annotations

import json

import pytest

from src.dispatch import DispatchTimeoutError, LocalDispatcher, _is_transient_failure
from src.runtime.contracts import DispatchRequest, DispatchResponse
from src.runtime.providers.base import ProviderAdapter, ProviderCapabilities
from src.runtime.provider_health import ProviderHealthStore


# ── helpers ────────────────────────────────────────────────────────────────

class _StubProvider(ProviderAdapter):
    """Provider stub that returns a queued sequence of responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    @property
    def name(self) -> str:
        return "stub"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(transport_kind="deterministic", supports_structured_output=True)

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        self.calls += 1
        item = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


def _make_request(**overrides) -> DispatchRequest:
    defaults = dict(mode="execute", task_id="t1", phase="Build", prompt="do work")
    defaults.update(overrides)
    return DispatchRequest(**defaults)


# ── LocalDispatcher retry behavior ───────────────────────────────────────────

def test_retries_transient_failure_once_with_retry_budget(monkeypatch):
    sleeps = []
    monkeypatch.setattr("src.dispatch._sleep", lambda secs: sleeps.append(secs))

    provider = _StubProvider([
        DispatchResponse(success=False, error="rate limit exceeded"),
        DispatchResponse(success=True, outputs={"ok": True}),
    ])
    dispatcher = LocalDispatcher(provider=provider)

    response = dispatcher.dispatch(_make_request(retry_budget=1))

    assert response.success is True
    assert provider.calls == 2
    assert sleeps == [1]
    assert response.artifacts["dispatch_retries"] == {
        "attempts": 2,
        "transient_failures": ["rate limit exceeded"],
    }


def test_non_transient_failure_does_not_retry(monkeypatch):
    sleeps = []
    monkeypatch.setattr("src.dispatch._sleep", lambda secs: sleeps.append(secs))

    provider = _StubProvider([
        DispatchResponse(success=False, error="invalid api key"),
        DispatchResponse(success=True, outputs={"ok": True}),
    ])
    dispatcher = LocalDispatcher(provider=provider)

    response = dispatcher.dispatch(_make_request(retry_budget=2))

    assert response.success is False
    assert response.error == "invalid api key"
    assert provider.calls == 1
    assert sleeps == []
    assert "dispatch_retries" not in response.artifacts


def test_retry_budget_zero_never_retries(monkeypatch):
    sleeps = []
    monkeypatch.setattr("src.dispatch._sleep", lambda secs: sleeps.append(secs))

    provider = _StubProvider([
        DispatchResponse(success=False, error="rate limit exceeded"),
        DispatchResponse(success=True, outputs={"ok": True}),
    ])
    dispatcher = LocalDispatcher(provider=provider)

    response = dispatcher.dispatch(_make_request(retry_budget=0))

    assert response.success is False
    assert response.error == "rate limit exceeded"
    assert provider.calls == 1
    assert sleeps == []
    assert "dispatch_retries" not in response.artifacts


# ── _is_transient_failure ────────────────────────────────────────────────────

@pytest.mark.parametrize("error_text", [
    "Rate limit exceeded",
    "rate_limit_exceeded",
    "Server overloaded, try again",
    "HTTP 429 Too Many Requests",
    "received 529 from upstream",
    "Connection reset by peer",
    "Service temporarily unavailable",
])
def test_is_transient_failure_matches_known_patterns(error_text):
    response = DispatchResponse(success=False, error=error_text)
    assert _is_transient_failure(response, None) is True


def test_is_transient_failure_false_for_unrelated_error():
    response = DispatchResponse(success=False, error="invalid api key")
    assert _is_transient_failure(response, None) is False


def test_is_transient_failure_true_for_timeout_exception():
    assert _is_transient_failure(None, DispatchTimeoutError("timed out")) is True


def test_is_transient_failure_true_for_timed_out_artifact():
    response = DispatchResponse(success=False, error="boom", artifacts={"timed_out": True})
    assert _is_transient_failure(response, None) is True


def test_is_transient_failure_false_for_success():
    response = DispatchResponse(success=True)
    assert _is_transient_failure(response, None) is False


# ── _HarnessAwareDispatcher failover ─────────────────────────────────────────

class _RoutingDispatcher:
    """Stub base dispatcher whose result depends on constraints['provider']."""

    def __init__(self, results: dict[str, DispatchResponse]):
        self.results = results
        self.requests: list[DispatchRequest] = []

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        self.requests.append(request)
        provider = request.constraints.get("provider")
        return self.results[provider]


def test_failover_to_fallback_agent_on_primary_failure():
    from src.engine import _HarnessAwareDispatcher

    base = _RoutingDispatcher({
        "a": DispatchResponse(success=False, error="invalid api key"),
        "b": DispatchResponse(success=True, outputs={"ok": True}),
    })
    d = _HarnessAwareDispatcher(base)
    d.preferred_agent = "a"
    d.fallback_agents = ["b"]

    response = d.dispatch(_make_request())

    assert response.success is True
    assert response.artifacts["failover"] == {
        "failed_provider": "a",
        "fallback_used": "b",
        "attempted": ["a", "b"],
    }
    assert [r.constraints.get("provider") for r in base.requests] == ["a", "b"]


def test_failover_skipped_when_workspace_already_modified():
    from src.engine import _HarnessAwareDispatcher

    base = _RoutingDispatcher({
        "a": DispatchResponse(
            success=False,
            error="invalid api key",
            evidence={"workspace_delta": {"change_count": 2}},
        ),
        "b": DispatchResponse(success=True, outputs={"ok": True}),
    })
    d = _HarnessAwareDispatcher(base)
    d.preferred_agent = "a"
    d.fallback_agents = ["b"]

    response = d.dispatch(_make_request())

    assert response.success is False
    assert response.artifacts["failover_skipped"] == "workspace_already_modified"
    assert "failover" not in response.artifacts
    # Only the primary was attempted.
    assert [r.constraints.get("provider") for r in base.requests] == ["a"]


def test_failover_does_not_override_explicit_provider_constraint():
    from src.engine import _HarnessAwareDispatcher

    base = _RoutingDispatcher({
        "explicit": DispatchResponse(success=False, error="invalid api key"),
        "b": DispatchResponse(success=True, outputs={"ok": True}),
    })
    d = _HarnessAwareDispatcher(base)
    d.preferred_agent = "a"
    d.fallback_agents = ["b"]

    response = d.dispatch(_make_request(constraints={"provider": "explicit"}))

    assert response.success is False
    assert response.error == "invalid api key"
    assert "failover" not in response.artifacts
    assert "failover_skipped" not in response.artifacts
    # Only the explicitly requested provider was attempted.
    assert [r.constraints.get("provider") for r in base.requests] == ["explicit"]


def test_failover_all_fail_returns_last_failure_with_history():
    from src.engine import _HarnessAwareDispatcher

    base = _RoutingDispatcher({
        "a": DispatchResponse(success=False, error="invalid api key (a)"),
        "b": DispatchResponse(success=False, error="invalid api key (b)"),
    })
    d = _HarnessAwareDispatcher(base)
    d.preferred_agent = "a"
    d.fallback_agents = ["b"]

    response = d.dispatch(_make_request())

    assert response.success is False
    assert response.error == "invalid api key (b)"
    assert response.artifacts["failover"] == {
        "failed_provider": "a",
        "fallback_used": None,
        "attempted": ["a", "b"],
    }


# ── ProviderHealthStore ───────────────────────────────────────────────────────

def test_provider_health_record_and_score(tmp_path):
    store = ProviderHealthStore(tmp_path)
    store.record("claude", True)
    store.record("claude", True)
    store.record("claude", False)

    assert store.score("claude") == pytest.approx(2 / 3)


def test_provider_health_unseen_provider_defaults_to_one(tmp_path):
    store = ProviderHealthStore(tmp_path)
    assert store.score("nobody") == 1.0


def test_provider_health_floor_at_point_one(tmp_path):
    store = ProviderHealthStore(tmp_path)
    for _ in range(10):
        store.record("flaky", False)

    assert store.score("flaky") == pytest.approx(0.1)


def test_provider_health_corrupt_file_tolerated(tmp_path):
    health_file = tmp_path / "provider_health.json"
    health_file.write_text("{not valid json")

    store = ProviderHealthStore(tmp_path)
    assert store.snapshot() == {}
    store.record("claude", True)
    assert store.score("claude") == 1.0


def test_provider_health_atomic_write_produces_valid_json(tmp_path):
    store = ProviderHealthStore(tmp_path)
    store.record("claude", True)
    store.record("codex", False)

    health_file = tmp_path / "provider_health.json"
    assert health_file.exists()
    data = json.loads(health_file.read_text())
    assert data["claude"]["successes"] == 1
    assert data["codex"]["failures"] == 1
    # No leftover temp file.
    assert not (tmp_path / "provider_health.json.tmp").exists()


def test_provider_health_persists_across_instances(tmp_path):
    store1 = ProviderHealthStore(tmp_path)
    store1.record("claude", True)
    store1.record("claude", False)

    store2 = ProviderHealthStore(tmp_path)
    assert store2.score("claude") == pytest.approx(0.5)
