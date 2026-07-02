from src.engine import Phase, PhaseResult
from src.runtime import (
    DispatchResponse,
    RecoveryClassificationPolicy,
    RecoveryRunner,
    validate_recovery_classification_config,
)


class RecordingDispatcher:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def dispatch(self, request):
        self.requests.append(request)
        return self.response


class FailingDispatcher:
    def dispatch(self, request):
        raise RuntimeError("provider unavailable")


def test_recovery_runner_emits_retry_action():
    result = PhaseResult(
        phase=Phase.VERIFY,
        outcome="fail",
        artifacts={"verification_summary": {"command_succeeded": False}},
    )

    action = RecoveryRunner().execute(
        task_id="task-1",
        phase="Verify",
        attempt=1,
        result=result,
    ).to_artifact()

    assert action["phase"] == "Verify"
    assert action["attempt"] == 1
    assert action["success"] is True
    assert action["details"]["reason"] == "verification command failed"


def test_recovery_runner_can_dispatch_provider_recovery():
    result = PhaseResult(
        phase=Phase.REVIEW,
        outcome="escalate",
        artifacts={
            "review_summary": {"failed": 2},
            "dispatch_artifacts": {
                "provider": "claude",
                "invocation_kind": "native_cli",
                "native_cli_family": "claude",
                "workspace_root": "/tmp/workspace",
            },
        },
        error="Missing or invalid authorization token.",
    )
    dispatcher = RecordingDispatcher(
        DispatchResponse(
            success=True,
            outputs={"retry_guidance": ["Address blocking review findings"]},
            evidence={"provider_selected": True},
            artifacts={"provider": "review-agent"},
        )
    )

    action = RecoveryRunner(dispatcher=dispatcher).execute(
        task_id="task-2",
        phase="Review",
        attempt=2,
        result=result,
    ).to_artifact()

    assert dispatcher.requests[0].mode == "execute"
    assert dispatcher.requests[0].constraints["purpose"] == "quality_recovery_fix"
    assert dispatcher.requests[0].constraints["recovery_class"] == "auth"
    assert dispatcher.requests[0].inputs["reason"] == "review findings require retry"
    assert dispatcher.requests[0].inputs["provider_context"] == {
        "provider": "claude",
        "invocation_kind": "native_cli",
        "native_cli_family": "claude",
        "workspace_root": "/tmp/workspace",
    }
    assert "changes_applied" in dispatcher.requests[0].expected_outputs
    assert action["success"] is True
    assert action["details"]["recovery_class"] == "auth"
    assert action["details"]["provider_recovery"]["fix_attempted"] is True
    assert action["details"]["provider_recovery"]["success"] is True
    assert action["details"]["provider_recovery"]["provider_context"]["provider"] == "claude"
    assert action["details"]["provider_recovery"]["outputs"]["retry_guidance"] == [
        "Address blocking review findings"
    ]


def test_recovery_runner_preserves_local_action_when_dispatcher_fails():
    result = PhaseResult(
        phase=Phase.VERIFY,
        outcome="fail",
        artifacts={
            "verification_summary": {"lint_errors": 3},
            "dispatch_artifacts": {
                "provider": "copilot",
                "invocation_kind": "native_cli",
                "native_cli_family": "github_copilot",
            },
        },
        error="Provider unavailable: CLI path not found",
    )

    action = RecoveryRunner(dispatcher=FailingDispatcher()).execute(
        task_id="task-3",
        phase="Verify",
        attempt=1,
        result=result,
    ).to_artifact()

    assert action["success"] is True
    assert action["details"]["reason"] == "lint errors detected"
    assert action["details"]["recovery_class"] == "provider_offline"
    assert action["details"]["provider_recovery"]["success"] is False
    assert action["details"]["provider_recovery"]["provider_context"]["provider"] == "copilot"
    assert "provider unavailable" in action["details"]["provider_recovery"]["error"]


def test_recovery_runner_marks_native_cli_failure_when_provider_exit_is_nonzero():
    result = PhaseResult(
        phase=Phase.VERIFY,
        outcome="fail",
        artifacts={
            "verification_summary": {"command_succeeded": False},
            "dispatch_artifacts": {
                "provider": "codex",
                "invocation_kind": "native_cli",
                "native_cli_family": "codex",
                "return_code": 2,
            },
        },
        error="Codex native CLI exited with code 2",
    )

    action = RecoveryRunner().execute(
        task_id="task-4",
        phase="Verify",
        attempt=1,
        result=result,
    ).to_artifact()

    assert action["details"]["recovery_class"] == "native_cli_failure"
    assert action["details"]["provider_context"]["provider"] == "codex"
    assert action["details"]["provider_context"]["return_code"] == 2


def test_recovery_classification_policy_defaults_match_hardcoded_behavior():
    """Absent/malformed escalation must reproduce today's hardcoded classification."""
    default_policy = RecoveryClassificationPolicy.from_escalation(None)
    same_policy = RecoveryClassificationPolicy.from_escalation({})
    malformed_policy = RecoveryClassificationPolicy.from_escalation({"recovery_classification": "not-a-dict"})

    assert default_policy == RecoveryClassificationPolicy()
    assert same_policy == RecoveryClassificationPolicy()
    assert malformed_policy == RecoveryClassificationPolicy()

    assert default_policy.classify(error_text="Missing authorization token", provider_context=None, reason="x") == "auth"
    assert (
        default_policy.classify(error_text="Provider unavailable: CLI path not found", provider_context=None, reason="x")
        == "provider_offline"
    )
    assert (
        default_policy.classify(
            error_text="", provider_context={"invocation_kind": "native_cli"}, reason="x"
        )
        == "native_cli_failure"
    )
    assert default_policy.classify(error_text="", provider_context=None, reason="Review findings require retry") == "review_content"
    assert default_policy.classify(error_text="", provider_context=None, reason="phase requested recovery") == "generic_retry"


def test_recovery_classification_policy_can_be_overridden_via_escalation():
    escalation = {
        "recovery_classification": {
            "error_text_rules": [
                {"matches": ["rate limit", "429"], "class": "rate_limited"},
            ],
            "reason_keyword_rules": [
                {"keyword": "timeout", "class": "timeout_retry"},
            ],
            "native_cli_class": None,
            "default_class": "needs_human",
            "reason_rules": [
                {"artifact": "custom_summary", "field": "blocked", "truthy": True, "reason": "custom block detected"},
            ],
            "default_reason": "no signal available",
        }
    }
    policy = RecoveryClassificationPolicy.from_escalation(escalation)

    assert policy.classify(error_text="HTTP 429 rate limit exceeded", provider_context=None, reason="x") == "rate_limited"
    # auth/provider_offline hardcoded defaults are fully replaced, not merged.
    assert policy.classify(error_text="missing authorization token", provider_context=None, reason="x") == "needs_human"
    # native_cli_class disabled -> falls through to reason keyword rules / default.
    assert (
        policy.classify(error_text="", provider_context={"invocation_kind": "native_cli"}, reason="a timeout occurred")
        == "timeout_retry"
    )
    assert policy.classify(error_text="", provider_context={"invocation_kind": "native_cli"}, reason="x") == "needs_human"

    result = PhaseResult(
        phase=Phase.VERIFY,
        outcome="fail",
        artifacts={"custom_summary": {"blocked": True}},
    )
    assert policy.classify_reason(result) == "custom block detected"
    assert policy.classify_reason(PhaseResult(phase=Phase.VERIFY, outcome="fail")) == "no signal available"


def test_recovery_runner_uses_custom_escalation_classification():
    escalation = {
        "recovery_classification": {
            "error_text_rules": [{"matches": ["rate limit"], "class": "rate_limited"}],
        }
    }
    result = PhaseResult(
        phase=Phase.VERIFY,
        outcome="fail",
        artifacts={"verification_summary": {"command_succeeded": False}},
        error="429 rate limit hit",
    )

    action = RecoveryRunner(escalation=escalation).execute(
        task_id="task-5",
        phase="Verify",
        attempt=1,
        result=result,
    ).to_artifact()

    assert action["details"]["recovery_class"] == "rate_limited"

    # Confirm passing a pre-built policy object also works.
    action2 = RecoveryRunner(
        classification_policy=RecoveryClassificationPolicy.from_escalation(escalation)
    ).execute(
        task_id="task-6",
        phase="Verify",
        attempt=1,
        result=result,
    ).to_artifact()
    assert action2["details"]["recovery_class"] == "rate_limited"


def test_validate_recovery_classification_config():
    assert validate_recovery_classification_config(None) == []
    assert validate_recovery_classification_config({}) == []
    assert validate_recovery_classification_config("nope") == ["recovery_classification must be a mapping"]

    issues = validate_recovery_classification_config(
        {
            "error_text_rules": "not-a-list",
            "default_class": "",
            "native_cli_class": 5,
        }
    )
    assert "recovery_classification.error_text_rules must be a list" in issues
    assert "recovery_classification.default_class must be a non-empty string" in issues
    assert "recovery_classification.native_cli_class must be a non-empty string or null" in issues
