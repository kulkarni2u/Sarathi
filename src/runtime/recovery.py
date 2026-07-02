"""Executable recovery actions for bounded quality loops."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc
from typing import Any, NamedTuple

try:
    from .contracts import DispatchRequest
except ImportError:
    from runtime.contracts import DispatchRequest


class ReasonRule(NamedTuple):
    """One ordered rule used to derive a human-readable recovery reason."""

    artifact: str
    field: str
    check: str  # "equals" or "truthy"
    expected: Any
    reason: str


@dataclass(frozen=True)
class RecoveryClassificationPolicy:
    """Runtime policy for classifying phase failures into recovery classes.

    Mirrors the ``QualityLoopPolicy`` pattern: defaults reproduce today's
    hardcoded substring-matching behavior byte-for-byte, and policy packs can
    override or extend the rules via ``escalation.md``'s
    ``recovery_classification`` block.
    """

    reason_rules: tuple[ReasonRule, ...] = (
        ReasonRule("verification_summary", "command_succeeded", "equals", False, "verification command failed"),
        ReasonRule("verification_summary", "lint_errors", "truthy", None, "lint errors detected"),
        ReasonRule("review_summary", "failed", "truthy", None, "review findings require retry"),
    )
    default_reason: str = "phase requested recovery"

    error_text_rules: tuple[tuple[tuple[str, ...], str], ...] = (
        (("authorization token", "auth"), "auth"),
        (("provider unavailable", "cli path not found"), "provider_offline"),
    )
    native_cli_invocation_kind: str = "native_cli"
    native_cli_class: str | None = "native_cli_failure"
    reason_keyword_rules: tuple[tuple[str, str], ...] = (("review", "review_content"),)
    default_class: str = "generic_retry"

    @classmethod
    def from_escalation(cls, escalation: dict[str, Any] | None = None) -> "RecoveryClassificationPolicy":
        if not isinstance(escalation, dict):
            return cls()
        config = escalation.get("recovery_classification")
        if not isinstance(config, dict):
            return cls()
        defaults = cls()
        return cls(
            reason_rules=_parse_reason_rules(config.get("reason_rules"), defaults.reason_rules),
            default_reason=_string_or_default(config, "default_reason", defaults.default_reason),
            error_text_rules=_parse_error_text_rules(config.get("error_text_rules"), defaults.error_text_rules),
            native_cli_invocation_kind=_string_or_default(
                config, "native_cli_invocation_kind", defaults.native_cli_invocation_kind
            ),
            native_cli_class=_optional_string_or_default(config, "native_cli_class", defaults.native_cli_class),
            reason_keyword_rules=_parse_keyword_rules(
                config.get("reason_keyword_rules"), defaults.reason_keyword_rules
            ),
            default_class=_string_or_default(config, "default_class", defaults.default_class),
        )

    def classify_reason(self, result: Any) -> str:
        """Derive a human-readable reason from a phase result's artifacts."""
        artifacts = getattr(result, "artifacts", {}) or {}
        for rule in self.reason_rules:
            section = artifacts.get(rule.artifact)
            if not isinstance(section, dict):
                continue
            value = section.get(rule.field)
            if rule.check == "equals" and value == rule.expected:
                return rule.reason
            if rule.check == "truthy" and bool(value):
                return rule.reason
        return self.default_reason

    def classify(
        self,
        *,
        error_text: str,
        provider_context: dict[str, Any] | None,
        reason: str,
    ) -> str:
        """Classify a failure into a recovery class using policy-defined rules."""
        text = (error_text or "").lower()
        for matches, recovery_class in self.error_text_rules:
            if any(match in text for match in matches):
                return recovery_class
        if (
            self.native_cli_class
            and provider_context
            and provider_context.get("invocation_kind") == self.native_cli_invocation_kind
        ):
            return self.native_cli_class
        reason_lower = (reason or "").lower()
        for keyword, recovery_class in self.reason_keyword_rules:
            if keyword in reason_lower:
                return recovery_class
        return self.default_class

    def to_artifact(self) -> dict[str, Any]:
        return {
            "reason_rules": [
                {
                    "artifact": rule.artifact,
                    "field": rule.field,
                    "check": rule.check,
                    "expected": rule.expected,
                    "reason": rule.reason,
                }
                for rule in self.reason_rules
            ],
            "default_reason": self.default_reason,
            "error_text_rules": [
                {"matches": list(matches), "class": recovery_class}
                for matches, recovery_class in self.error_text_rules
            ],
            "native_cli_invocation_kind": self.native_cli_invocation_kind,
            "native_cli_class": self.native_cli_class,
            "reason_keyword_rules": [
                {"keyword": keyword, "class": recovery_class}
                for keyword, recovery_class in self.reason_keyword_rules
            ],
            "default_class": self.default_class,
        }


def validate_recovery_classification_config(config: Any) -> list[str]:
    """Return validation issues for a recovery_classification policy block."""
    if config is None:
        return []
    if not isinstance(config, dict):
        return ["recovery_classification must be a mapping"]

    issues: list[str] = []
    for key in ("error_text_rules", "reason_rules", "reason_keyword_rules"):
        value = config.get(key)
        if key in config and not isinstance(value, list):
            issues.append(f"recovery_classification.{key} must be a list")
    for key in ("default_class", "default_reason", "native_cli_invocation_kind"):
        value = config.get(key)
        if key in config and not (isinstance(value, str) and value):
            issues.append(f"recovery_classification.{key} must be a non-empty string")
    if "native_cli_class" in config:
        value = config["native_cli_class"]
        if value is not None and not (isinstance(value, str) and value):
            issues.append("recovery_classification.native_cli_class must be a non-empty string or null")
    return issues


def _string_or_default(config: dict[str, Any], key: str, default: str) -> str:
    value = config.get(key)
    return value if isinstance(value, str) and value else default


def _optional_string_or_default(config: dict[str, Any], key: str, default: str | None) -> str | None:
    if key not in config:
        return default
    value = config[key]
    if value is None:
        return None
    return value if isinstance(value, str) and value else default


def _parse_error_text_rules(
    value: Any, default: tuple[tuple[tuple[str, ...], str], ...]
) -> tuple[tuple[tuple[str, ...], str], ...]:
    if not isinstance(value, list):
        return default
    rules: list[tuple[tuple[str, ...], str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        matches = item.get("matches")
        recovery_class = item.get("class")
        if not isinstance(matches, list) or not isinstance(recovery_class, str) or not recovery_class:
            continue
        normalized_matches = tuple(
            match.lower() for match in matches if isinstance(match, str) and match
        )
        if not normalized_matches:
            continue
        rules.append((normalized_matches, recovery_class))
    return tuple(rules) if rules else default


def _parse_keyword_rules(
    value: Any, default: tuple[tuple[str, str], ...]
) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        return default
    rules: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        keyword = item.get("keyword")
        recovery_class = item.get("class")
        if isinstance(keyword, str) and keyword and isinstance(recovery_class, str) and recovery_class:
            rules.append((keyword.lower(), recovery_class))
    return tuple(rules) if rules else default


def _parse_reason_rules(value: Any, default: tuple[ReasonRule, ...]) -> tuple[ReasonRule, ...]:
    if not isinstance(value, list):
        return default
    rules: list[ReasonRule] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        artifact = item.get("artifact")
        field_name = item.get("field")
        reason = item.get("reason")
        if not (
            isinstance(artifact, str)
            and artifact
            and isinstance(field_name, str)
            and field_name
            and isinstance(reason, str)
            and reason
        ):
            continue
        if "equals" in item:
            rules.append(ReasonRule(artifact, field_name, "equals", item["equals"], reason))
        elif item.get("truthy") is True:
            rules.append(ReasonRule(artifact, field_name, "truthy", None, reason))
        else:
            continue
    return tuple(rules) if rules else default


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

    def __init__(
        self,
        dispatcher: Any | None = None,
        escalation: dict[str, Any] | None = None,
        classification_policy: RecoveryClassificationPolicy | None = None,
    ):
        self.dispatcher = dispatcher
        self.classification_policy = classification_policy or RecoveryClassificationPolicy.from_escalation(
            escalation
        )

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
        return self.classification_policy.classify_reason(result)

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
        error_text = str(getattr(result, "error", "") or "")
        return self.classification_policy.classify(
            error_text=error_text,
            provider_context=provider_context,
            reason=self._reason(result),
        )
