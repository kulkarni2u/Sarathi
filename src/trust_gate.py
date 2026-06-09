"""NCP Trust Gate — formal handshake between Sarathi and NCP before execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TrustGateResult(Enum):
    PASS             = "PASS"
    WARN             = "WARN"    # stale keys present, can proceed with caution
    BLOCK            = "BLOCK"   # context untrustworthy, do not execute
    REFRESH_REQUIRED = "REFRESH_REQUIRED"


class NCPEvent(Enum):
    TRUST_GATE_PASS   = "trust_gate_pass"
    TRUST_GATE_WARN   = "trust_gate_warn"
    TRUST_GATE_BLOCK  = "trust_gate_block"
    REFRESH_COMPLETE  = "refresh_complete"
    DRIFT_DETECTED    = "drift_detected"
    CONTEXT_CONTESTED = "context_contested"
    CONTEXT_UPDATED   = "context_updated"


@dataclass
class TrustGateResponse:
    result: TrustGateResult
    scope_drift_score: float = 0.0
    stale_keys: list[str] = field(default_factory=list)
    contested_keys: list[str] = field(default_factory=list)
    message: str = ""


class TrustGate:
    """
    Formal handshake between Sarathi and NCP before harness execution.

    Sarathi cannot execute on BLOCK. WARN triggers refresh for MUTATION tasks.
    Degrades gracefully when NCP is unavailable — returns PASS with a warning message.
    """

    def __init__(self, ncp_mcp_url: str = "http://127.0.0.1:4242/mcp"):
        self.ncp_mcp_url = ncp_mcp_url

    def evaluate(
        self,
        task_class_value: str,
        required_context_keys: list[str],
        pipeline_id: str,
    ) -> TrustGateResponse:
        """
        Call NCP to evaluate context trustworthiness.
        Returns TrustGateResponse with PASS / WARN / BLOCK.
        """
        try:
            import httpx
            resp = httpx.post(
                self.ncp_mcp_url,
                json={
                    "tool": "ncp_get_context",
                    "arguments": {
                        "pipeline_id": pipeline_id,
                        "trust_gate": True,
                        "required_keys": required_context_keys,
                    },
                },
                timeout=10.0,
            )
            if resp.status_code != 200:
                return TrustGateResponse(
                    TrustGateResult.PASS,
                    message="NCP unavailable — degraded mode",
                )

            data = resp.json()
            drift = float(data.get("scope_drift_score", 0.0))
            stale = list(data.get("stale_keys", []))
            contested = list(data.get("contested_keys", []))

            if contested:
                return TrustGateResponse(
                    TrustGateResult.BLOCK, drift, stale, contested,
                    "Contested context — route to resolver",
                )
            if drift > 0.55 or any(k in stale for k in required_context_keys):
                return TrustGateResponse(
                    TrustGateResult.BLOCK, drift, stale, [],
                    f"Scope drift {drift:.2f} exceeds threshold",
                )
            if drift > 0.15 or stale:
                return TrustGateResponse(
                    TrustGateResult.WARN, drift, stale, [],
                    f"Stale keys present: {stale}",
                )
            return TrustGateResponse(TrustGateResult.PASS, drift)

        except Exception as exc:
            return TrustGateResponse(
                TrustGateResult.PASS,
                message=f"Trust gate error (degraded): {exc}",
            )

    def refresh(self, stale_keys: list[str], pipeline_id: str) -> bool:
        """Trigger NCP to refresh stale keys. Returns True on success."""
        try:
            import httpx
            resp = httpx.post(
                self.ncp_mcp_url,
                json={
                    "tool": "ncp_emit_whisper",
                    "arguments": {
                        "pipeline_id": pipeline_id,
                        "whisper_type": "world_check",
                        "payload": {"refresh_keys": stale_keys},
                    },
                },
                timeout=5.0,
            )
            return resp.status_code == 200
        except Exception:
            return False


def arbitrate(
    ncp_result: TrustGateResult,
    task_class_value: str,
    time_constrained: bool = False,
) -> str:
    """
    Map (TrustGateResult × TaskClass × time_constrained) to an execution action.

    Returns one of:
      EXECUTE | EXECUTE_FLAGGED | REFRESH_THEN_EXECUTE |
      BLOCK_UNTIL_REFRESH | PAUSE_AND_NOTIFY | ABORT_AND_ESCALATE
    """
    is_mutation = task_class_value.startswith("mutation")
    is_query    = task_class_value == "query"

    if ncp_result == TrustGateResult.PASS:
        return "EXECUTE"

    if ncp_result == TrustGateResult.BLOCK:
        return "ABORT_AND_ESCALATE"

    # WARN path
    if ncp_result == TrustGateResult.WARN:
        if is_mutation:
            return "PAUSE_AND_NOTIFY" if time_constrained else "BLOCK_UNTIL_REFRESH"
        if is_query:
            return "EXECUTE_FLAGGED"
        return "REFRESH_THEN_EXECUTE"

    return "EXECUTE"
