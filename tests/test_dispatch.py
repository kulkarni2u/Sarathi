import sys

from src.dispatch import LocalDispatcher, NullDispatcher, TaskSpec
from src.runtime import DispatchRequest, DispatchResponse
from src.runtime.providers import (
    AnthropicSdkProviderAdapter,
    ConfiguredProviderAdapter,
    ExternalProviderAdapter,
    LocalProviderAdapter,
    OpenAISdkProviderAdapter,
    OpenCodeSdkProviderAdapter,
)


def test_null_dispatcher_execute():
    dispatcher = NullDispatcher()
    spec = TaskSpec(id="test", description="test spec")
    result = dispatcher.dispatch_execute(spec)
    assert result.success is False
    assert result.outputs == {}


def test_task_spec_fields():
    spec = TaskSpec(
        id="task-1",
        description="Test task",
        inputs={"key": "value"},
        expected_outputs={"result": "expected"},
    )
    assert spec.id == "task-1"
    assert spec.inputs == {"key": "value"}
    assert spec.expected_outputs == {"result": "expected"}


def test_local_dispatcher_dispatches_explore_contract():
    dispatcher = LocalDispatcher()
    result = dispatcher.dispatch(
        DispatchRequest(
            mode="explore",
            task_id="task-1",
            phase="Brainstorm",
            prompt="Add auth flow",
            inputs={"task_description": "Add auth flow", "complexity": "high"},
            expected_outputs=["approaches"],
        )
    )

    assert result.success is True
    assert len(result.outputs["approaches"]) >= 3
    assert result.artifacts["provider"] == "local"


def test_local_dispatcher_uses_provider_adapter():
    dispatcher = LocalDispatcher(provider=LocalProviderAdapter())
    result = dispatcher.dispatch(
        DispatchRequest(
            mode="execute",
            task_id="task-1",
            phase="Plan",
            prompt="Add auth flow",
            inputs={"task_description": "Add auth flow", "risks": ["Some risk"]},
            expected_outputs=["implementation_plan"],
        )
    )

    assert result.success is True
    assert result.outputs["implementation_plan"]["objective"] == "Add auth flow"


def test_local_provider_executes_quality_recovery_fix_contract():
    dispatcher = LocalDispatcher(provider=LocalProviderAdapter())

    result = dispatcher.dispatch(
        DispatchRequest(
            mode="execute",
            task_id="task-1",
            phase="Verify",
            prompt="Fix verification failure",
            inputs={"reason": "verification command failed"},
            constraints={"purpose": "quality_recovery_fix"},
            expected_outputs=["recovery_actions", "retry_guidance", "changes_applied"],
        )
    )

    assert result.success is True
    assert result.outputs["changes_applied"] is False
    assert result.outputs["recovery_actions"][0]["action"] == "provider_guided_retry_preparation"


def test_local_provider_emits_provider_aware_recovery_guidance():
    dispatcher = LocalDispatcher(provider=LocalProviderAdapter())

    result = dispatcher.dispatch(
        DispatchRequest(
            mode="execute",
            task_id="task-auth-recovery",
            phase="Review",
            prompt="Fix native provider auth failure",
            inputs={
                "reason": "review findings require retry",
                "recovery_class": "auth",
                "provider_context": {
                    "provider": "claude",
                    "native_cli_family": "claude",
                },
            },
            constraints={
                "purpose": "quality_recovery_fix",
                "recovery_class": "auth",
                "provider": "claude",
            },
            expected_outputs=["recovery_actions", "retry_guidance", "changes_applied"],
        )
    )

    assert result.success is True
    assert result.outputs["recovery_actions"][0]["provider"] == "claude"
    assert result.outputs["recovery_actions"][0]["recovery_class"] == "auth"
    assert any("auth" in guidance.lower() for guidance in result.outputs["retry_guidance"])


def test_local_provider_executes_child_task_contract():
    dispatcher = LocalDispatcher(provider=LocalProviderAdapter())

    result = dispatcher.dispatch(
        DispatchRequest(
            mode="execute",
            task_id="step-1",
            phase="Build",
            prompt="Implement step",
            inputs={"node": {"id": "step-1", "title": "Implement step"}},
            constraints={"purpose": "child_task_execution"},
            expected_outputs=["work_unit_result"],
        )
    )

    assert result.success is True
    assert result.outputs["work_unit_result"]["node_id"] == "step-1"
    assert result.evidence["child_task_executed"] is True


def test_local_dispatcher_routes_to_configured_provider_from_config():
    dispatcher = LocalDispatcher(
        provider_config={"provider": "acme", "providers": ["acme"]}
    )

    result = dispatcher.dispatch(
        DispatchRequest(
            mode="explore",
            task_id="task-1",
            phase="Brainstorm",
            prompt="Add auth flow",
        )
    )

    assert result.success is True
    assert result.artifacts["provider"] == "acme"
    assert result.outputs["provider"] == "acme"


def test_configured_provider_can_be_selected_from_policy_inputs():
    dispatcher = LocalDispatcher(
        provider=ConfiguredProviderAdapter(
            providers={
                "acme": ExternalProviderAdapter("acme"),
                "contoso": ExternalProviderAdapter("contoso"),
            }
        )
    )

    result = dispatcher.dispatch(
        DispatchRequest(
            mode="execute",
            task_id="task-1",
            phase="Plan",
            prompt="Add auth flow",
            inputs={"runtime": {"provider": "contoso"}},
        )
    )

    assert result.success is True
    assert result.artifacts["provider"] == "contoso"
    assert result.outputs["mode"] == "execute"
    assert result.outputs["implementation_plan"]["steps"]
    assert result.evidence["checkpoint_list"] is True


def test_configured_provider_can_use_command_provider():
    command = [
        sys.executable,
        "-c",
        (
            "import json,sys;"
            "request=json.load(sys.stdin);"
            "print(json.dumps({'success': True, 'outputs': {'phase': request['phase']}, "
            "'evidence': {'command_provider': True}, 'artifacts': {'kind': 'command'}}))"
        ),
    ]
    dispatcher = LocalDispatcher(
        provider=ConfiguredProviderAdapter(
            {
                "provider": "cmd",
                "providers": {
                    "cmd": {"type": "command", "command": command},
                },
            }
        )
    )

    result = dispatcher.dispatch(
        DispatchRequest(
            mode="execute",
            task_id="task-1",
            phase="Verify",
            prompt="Run command provider",
        )
    )

    assert result.success is True
    assert result.outputs["phase"] == "Verify"
    assert result.evidence["command_provider"] is True
    assert result.artifacts["provider"] == "cmd"


def test_configured_provider_reports_unknown_provider_failure():
    dispatcher = LocalDispatcher(provider=ConfiguredProviderAdapter())

    result = dispatcher.dispatch(
        DispatchRequest(
            mode="explore",
            task_id="task-1",
            phase="Brainstorm",
            prompt="Add auth flow",
            constraints={"provider": "missing"},
        )
    )

    assert result.success is False
    assert result.error == "Provider 'missing' is not configured"
    assert result.artifacts["provider"] == "missing"


def test_configured_provider_reports_provider_failure():
    dispatcher = LocalDispatcher(
        provider=ConfiguredProviderAdapter(
            providers={"acme": ExternalProviderAdapter("acme", fail_dispatch=True)}
        )
    )

    result = dispatcher.dispatch(
        DispatchRequest(
            mode="execute",
            task_id="task-1",
            phase="Plan",
            prompt="Add auth flow",
            constraints={"provider": "acme"},
        )
    )

    assert result.success is False
    assert result.error == "Provider 'acme' failed deterministically"
    assert result.artifacts["provider"] == "acme"


def test_local_provider_exposes_capability_metadata():
    provider = LocalProviderAdapter()

    assert provider.capabilities.transport_kind == "deterministic"
    assert provider.capabilities.supports_structured_output is True
    assert "child_task_execution" in provider.capabilities.declared_capabilities


def test_configured_provider_surfaces_selected_provider_capabilities():
    provider = ConfiguredProviderAdapter(
        {
            "provider": "cmd",
            "providers": {
                "cmd": {"type": "command", "command": [sys.executable, "-c", "print('{}')"]},
            },
        }
    )

    assert provider.capabilities.transport_kind == "command"
    assert provider.capabilities.supports_workspace_execution is True


def test_opencode_sdk_provider_exposes_sdk_capabilities(tmp_path):
    provider = OpenCodeSdkProviderAdapter(
        workspace_root=str(tmp_path),
        provider_path="/tmp/opencode",
    )

    assert provider.capabilities.transport_kind == "sdk"
    assert provider.capabilities.supports_workspace_execution is True
    assert "sdk_runtime" in provider.capabilities.declared_capabilities


def test_opencode_sdk_provider_falls_back_to_cli_when_sdk_bridge_fails(tmp_path, monkeypatch):
    provider = OpenCodeSdkProviderAdapter(
        workspace_root=str(tmp_path),
        provider_path="/usr/local/bin/opencode",
    )
    request = DispatchRequest(
        mode="execute",
        task_id="task-opencode",
        phase="Build",
        prompt="Implement the feature",
    )

    monkeypatch.setattr(
        provider,
        "_run_sdk_bridge",
        lambda payload, timeout_seconds: {"success": False, "error": "SDK unavailable"},
    )
    monkeypatch.setattr(
        "src.runtime.providers.opencode_sdk.dispatch_via_cli_bridge",
        lambda **kwargs: DispatchResponse(
            success=True,
            outputs={"messages": ["CLI fallback executed"]},
            evidence={"native_cli_family": "opencode"},
            artifacts={"invocation_kind": "native_cli"},
        ),
    )

    result = provider.dispatch(request)

    assert result.success is True
    assert result.outputs["messages"] == ["CLI fallback executed"]
    assert result.artifacts["sdk_fallback_used"] is True
    assert result.evidence["sdk_error"] == "SDK unavailable"


def test_openai_sdk_provider_exposes_sdk_capabilities(tmp_path):
    provider = OpenAISdkProviderAdapter(
        workspace_root=str(tmp_path),
        provider_path="/tmp/openai",
    )

    assert provider.name == "codex"
    assert provider.capabilities.transport_kind == "sdk"
    assert provider.capabilities.supports_workspace_execution is True
    assert "sdk_runtime" in provider.capabilities.declared_capabilities


def test_anthropic_sdk_provider_exposes_sdk_capabilities(tmp_path):
    provider = AnthropicSdkProviderAdapter(
        workspace_root=str(tmp_path),
        provider_path="/tmp/claude",
    )

    assert provider.name == "claude"
    assert provider.capabilities.transport_kind == "sdk"
    assert provider.capabilities.supports_workspace_execution is True
    assert "sdk_runtime" in provider.capabilities.declared_capabilities


def test_anthropic_sdk_provider_forwards_api_settings_to_bridge(tmp_path, monkeypatch):
    provider = AnthropicSdkProviderAdapter(
        workspace_root=str(tmp_path),
        provider_path=None,
        api_key="anthropic-test",
        base_url="https://example.invalid/anthropic",
        model="claude-sonnet-4-0",
    )
    request = DispatchRequest(
        mode="execute",
        task_id="task-anthropic-config",
        phase="Review",
        prompt="Review the feature",
    )
    captured = {}

    def _fake_run(payload, *, timeout_seconds):
        captured.update(payload)
        return {"success": False, "error": "SDK unavailable"}

    monkeypatch.setattr(provider, "_run_sdk_bridge", _fake_run)

    result = provider.dispatch(request)

    assert result.success is False
    assert captured["api_key"] == "anthropic-test"
    assert captured["base_url"] == "https://example.invalid/anthropic"
    assert captured["model"] == "claude-sonnet-4-0"


def test_anthropic_sdk_provider_falls_back_to_cli_when_sdk_bridge_fails(tmp_path, monkeypatch):
    provider = AnthropicSdkProviderAdapter(
        workspace_root=str(tmp_path),
        provider_path="/usr/local/bin/claude",
    )
    request = DispatchRequest(
        mode="execute",
        task_id="task-anthropic",
        phase="Review",
        prompt="Review the feature",
    )

    monkeypatch.setattr(
        provider,
        "_run_sdk_bridge",
        lambda payload, timeout_seconds: {"success": False, "error": "SDK unavailable"},
    )
    captured = {}

    def _fake_cli_bridge(**kwargs):
        captured.update(kwargs)
        return DispatchResponse(
            success=True,
            outputs={"messages": ["CLI fallback executed"]},
            evidence={"native_cli_family": "claude"},
            artifacts={"invocation_kind": "native_cli"},
        )

    monkeypatch.setattr("src.runtime.providers.anthropic_sdk.dispatch_via_cli_bridge", _fake_cli_bridge)

    result = provider.dispatch(request)

    assert result.success is True
    assert result.outputs["messages"] == ["CLI fallback executed"]
    assert result.artifacts["sdk_fallback_used"] is True
    assert result.evidence["sdk_error"] == "SDK unavailable"
    assert captured["provider"] == "claude"


def test_openai_sdk_provider_forwards_api_settings_to_bridge(tmp_path, monkeypatch):
    provider = OpenAISdkProviderAdapter(
        workspace_root=str(tmp_path),
        provider_path=None,
        api_key="sk-test",
        base_url="https://example.invalid/v1",
        model="gpt-4.1-mini",
    )
    request = DispatchRequest(
        mode="execute",
        task_id="task-openai-config",
        phase="Plan",
        prompt="Plan the feature",
    )
    captured = {}

    def _fake_run(payload, *, timeout_seconds):
        captured.update(payload)
        return {"success": False, "error": "SDK unavailable"}

    monkeypatch.setattr(provider, "_run_sdk_bridge", _fake_run)

    result = provider.dispatch(request)

    assert result.success is False
    assert captured["api_key"] == "sk-test"
    assert captured["base_url"] == "https://example.invalid/v1"
    assert captured["model"] == "gpt-4.1-mini"


def test_openai_sdk_provider_falls_back_to_cli_when_sdk_bridge_fails(tmp_path, monkeypatch):
    provider = OpenAISdkProviderAdapter(
        workspace_root=str(tmp_path),
        provider_path="/usr/local/bin/openai",
    )
    request = DispatchRequest(
        mode="execute",
        task_id="task-openai",
        phase="Build",
        prompt="Implement the feature",
    )

    monkeypatch.setattr(
        provider,
        "_run_sdk_bridge",
        lambda payload, timeout_seconds: {"success": False, "error": "SDK unavailable"},
    )
    captured = {}

    def _fake_cli_bridge(**kwargs):
        captured.update(kwargs)
        return DispatchResponse(
            success=True,
            outputs={"messages": ["CLI fallback executed"]},
            evidence={"native_cli_family": "codex"},
            artifacts={"invocation_kind": "native_cli"},
        )

    monkeypatch.setattr("src.runtime.providers.openai_sdk.dispatch_via_cli_bridge", _fake_cli_bridge)

    result = provider.dispatch(request)

    assert result.success is True
    assert result.outputs["messages"] == ["CLI fallback executed"]
    assert result.artifacts["sdk_fallback_used"] is True
    assert result.evidence["sdk_error"] == "SDK unavailable"
    assert captured["provider"] == "codex"


def test_external_provider_reports_unsupported_mode():
    provider = ExternalProviderAdapter("acme", supported_modes=("execute",))

    result = provider.dispatch(
        DispatchRequest(
            mode="explore",
            task_id="task-1",
            phase="Brainstorm",
            prompt="Add auth flow",
        )
    )

    assert result.success is False
    assert result.error == "Provider 'acme' does not support mode 'explore'"
    assert result.artifacts["supported_modes"] == ["execute"]


def test_local_dispatcher_default_remains_local_provider():
    dispatcher = LocalDispatcher()

    result = dispatcher.dispatch(
        DispatchRequest(
            mode="execute",
            task_id="task-1",
            phase="Plan",
            prompt="Add auth flow",
            inputs={"task_description": "Add auth flow"},
        )
    )

    assert result.success is True
    assert result.artifacts["provider"] == "local"
