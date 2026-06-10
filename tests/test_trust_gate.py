"""Tests for TrustGate, TrustGateResponse, and arbitrate()."""
import pytest
from src.trust_gate import (
    TrustGate,
    TrustGateResult,
    TrustGateResponse,
    NCPEvent,
    arbitrate,
)


# ── arbitrate() decision matrix ─────────────────────────────────────────────

def test_pass_always_executes():
    assert arbitrate(TrustGateResult.PASS, "query") == "EXECUTE"
    assert arbitrate(TrustGateResult.PASS, "mutation/infra") == "EXECUTE"
    assert arbitrate(TrustGateResult.PASS, "analysis") == "EXECUTE"


def test_block_always_aborts():
    assert arbitrate(TrustGateResult.BLOCK, "query") == "ABORT_AND_ESCALATE"
    assert arbitrate(TrustGateResult.BLOCK, "mutation/infra") == "ABORT_AND_ESCALATE"
    assert arbitrate(TrustGateResult.BLOCK, "evolution/harness") == "ABORT_AND_ESCALATE"


def test_warn_query_execute_flagged():
    assert arbitrate(TrustGateResult.WARN, "query") == "EXECUTE_FLAGGED"


def test_warn_mutation_blocks_until_refresh():
    assert arbitrate(TrustGateResult.WARN, "mutation/infra") == "BLOCK_UNTIL_REFRESH"
    assert arbitrate(TrustGateResult.WARN, "mutation/config") == "BLOCK_UNTIL_REFRESH"
    assert arbitrate(TrustGateResult.WARN, "mutation/data") == "BLOCK_UNTIL_REFRESH"


def test_warn_mutation_time_constrained_pauses():
    assert arbitrate(TrustGateResult.WARN, "mutation/infra", time_constrained=True) == "PAUSE_AND_NOTIFY"


def test_warn_analysis_refresh_then_execute():
    assert arbitrate(TrustGateResult.WARN, "analysis") == "REFRESH_THEN_EXECUTE"


def test_warn_codegen_refresh_then_execute():
    assert arbitrate(TrustGateResult.WARN, "codegen/patch") == "REFRESH_THEN_EXECUTE"


# ── TrustGate.evaluate() degrades gracefully when NCP is unreachable ────────

def test_evaluate_degrades_when_ncp_unavailable():
    gate = TrustGate(ncp_mcp_url="http://127.0.0.1:9999/mcp")  # nothing listening
    response = gate.evaluate("analysis", [], "task-test")
    assert response.result == TrustGateResult.PASS
    assert "degraded" in response.message.lower()


def test_refresh_degrades_when_ncp_unavailable():
    gate = TrustGate(ncp_mcp_url="http://127.0.0.1:9999/mcp")
    result = gate.refresh(["some_key"], "task-test")
    assert result is False


# ── TrustGateResponse ────────────────────────────────────────────────────────

def test_trust_gate_response_defaults():
    r = TrustGateResponse(TrustGateResult.PASS)
    assert r.scope_drift_score == 0.0
    assert r.stale_keys == []
    assert r.contested_keys == []
    assert r.message == ""


def test_trust_gate_response_with_stale_keys():
    r = TrustGateResponse(TrustGateResult.WARN, 0.3, ["config.v1"], [], "stale")
    assert r.result == TrustGateResult.WARN
    assert "config.v1" in r.stale_keys


# ── NCPEvent enum ────────────────────────────────────────────────────────────

def test_ncp_event_values_are_strings():
    for event in NCPEvent:
        assert isinstance(event.value, str)


def test_trust_gate_result_roundtrip():
    for result in TrustGateResult:
        assert TrustGateResult(result.value) == result


def test_evaluate_warns_when_gate_evaluation_itself_breaks(monkeypatch):
    # NCP responded, but processing the response failed — the gate is broken,
    # not absent, so it must flag (WARN) instead of silently passing.
    httpx = pytest.importorskip("httpx")

    class _BadResponse:
        status_code = 200

        def json(self):
            raise ValueError("malformed NCP payload")

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: _BadResponse())
    gate = TrustGate(ncp_mcp_url="http://127.0.0.1:4242/mcp")
    response = gate.evaluate("analysis", [], "task-test")
    assert response.result == TrustGateResult.WARN
    assert "error" in response.message.lower()
