"""Executable recovery actions for bounded quality loops."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

try:
    from .contracts import DispatchRequest
except ImportError:
    from runtime.contracts import DispatchRequest


@dataclass
class RecoveryAction:
    """One bounded recovery action executed before a retry."""

    phase: str
    action: str
    attempt: int
    success: bool = True
    details: dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )

    def to_artifact(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "action": self.action,
            "attempt": self.attempt,
            "success": self.success,
            "details": self.details,
            "generated_at": self.generated_at,
        }


class RecoveryRunner:
    """Executes deterministic recovery actions for retryable quality failures."""

    def __init__(self, dispatcher: Any | None = None):
        self.dispatcher = dispatcher

    def execute(self, *, task_id: str, phase: str, attempt: int, result: Any) -> RecoveryAction:
        reason = self._reason(result)
        provider_context = self._provider_context(result)
        recovery_class = self._recovery_class(result, provider_context)
        details = {
            "task_id": task_id,
            "reason": reason,
            "previous_outcome": getattr(result, "outcome", "unknown"),
            "recovery_class": recovery_class,
        }
        if provider_context is not None:
            details["provider_context"] = provider_context
        provider_details = self._dispatch_provider_recovery(
            task_id=task_id,
            phase=phase,
            attempt=attempt,
            reason=reason,
            recovery_class=recovery_class,
            provider_context=provider_context,
            result=result,
        )
        if provider_details is not None:
            details["provider_recovery"] = provider_details
        return RecoveryAction(
            phase=phase,
            action=f"prepare_retry_for_{phase.lower()}",
            attempt=attempt,
            details=details,
        )

    def _reason(self, result: Any) -> str:
        artifacts = getattr(result, "artifacts", {}) or {}
        if isinstance(artifacts.get("verification_summary"), dict):
            summary = artifacts["verification_summary"]
            if summary.get("command_succeeded") is False:
                return "verification command failed"
            if summary.get("lint_errors", 0):
                return "lint errors detected"
        if isinstance(artifacts.get("review_summary"), dict):
            summary = artifacts["review_summary"]
            if summary.get("failed", 0):
                return "review findings require retry"
        return "phase requested recovery"

    def _dispatch_provider_recovery(
        self,
        *,
        task_id: str,
        phase: str,
        attempt: int,
        reason: str,
        recovery_class: str,
        provider_context: dict[str, Any] | None,
        result: Any,
    ) -> dict[str, Any] | None:
        if self.dispatcher is None:
            return None
        inputs = {
            "phase": phase,
            "attempt": attempt,
            "reason": reason,
            "recovery_class": recovery_class,
            "previous_outcome": getattr(result, "outcome", "unknown"),
            "previous_artifacts": getattr(result, "artifacts", {}) or {},
        }
        if provider_context is not None:
            inputs["provider_context"] = provider_context
        request = DispatchRequest(
            mode="execute",
            task_id=task_id,
            phase=phase,
            prompt=f"Execute provider-backed recovery fix for {phase}: {reason}",
            inputs=inputs,
            expected_outputs=["recovery_actions", "retry_guidance", "changes_applied"],
            constraints={
                "purpose": "quality_recovery_fix",
                "recovery_class": recovery_class,
                **(
                    {"provider": provider_context["provider"]}
                    if isinstance(provider_context, dict) and isinstance(provider_context.get("provider"), str)
                    else {}
                ),
            },
            retry_budget=0,
        )
        try:
            response = self.dispatcher.dispatch(request)
        except Exception as exc:
            return {
                "dispatched": True,
                "success": False,
                "recovery_class": recovery_class,
                **({"provider_context": provider_context} if provider_context is not None else {}),
                "error": f"Dispatcher recovery failed: {exc}",
            }

        details = {
            "dispatched": True,
            "fix_attempted": True,
            "success": response.success,
            "recovery_class": recovery_class,
            "outputs": response.outputs,
            "evidence": response.evidence,
            "artifacts": response.artifacts,
        }
        if response.usage:
            details["usage"] = response.usage.to_artifact()
        if provider_context is not None:
            details["provider_context"] = provider_context
        if response.raw_transcript_ref:
            details["raw_transcript_ref"] = response.raw_transcript_ref
        if response.error:
            details["error"] = response.error
        return details

    def _provider_context(self, result: Any) -> dict[str, Any] | None:
        artifacts = getattr(result, "artifacts", {}) or {}
        dispatch_artifacts = artifacts.get("dispatch_artifacts")
        if not isinstance(dispatch_artifacts, dict):
            return None
        context = {
            key: value
            for key, value in dispatch_artifacts.items()
            if key
            in {
                "provider",
                "invocation_kind",
                "native_cli_family",
                "workspace_root",
                "return_code",
                "path",
                "command",
            }
        }
        return context or None

    def _recovery_class(
        self,
        result: Any,
        provider_context: dict[str, Any] | None,
    ) -> str:
        error_text = str(getattr(result, "error", "") or "").lower()
        if "authorization token" in error_text or "auth" in error_text:
            return "auth"
        if "provider unavailable" in error_text or "cli path not found" in error_text:
            return "provider_offline"
        if provider_context and provider_context.get("invocation_kind") == "native_cli":
            return "native_cli_failure"
        if "review" in self._reason(result).lower():
            return "review_content"
        return "generic_retry"
