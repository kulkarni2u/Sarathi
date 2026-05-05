from src.engine import Phase, PhaseResult
from src.runtime import DispatchResponse, RecoveryRunner


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
