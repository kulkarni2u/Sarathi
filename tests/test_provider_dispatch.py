import sys
from pathlib import Path
import stat
import subprocess

from src.service import _provider_dispatch_command, create_app
from src.runtime import DispatchRequest, DispatchResponse
from src.runtime.providers.configured import CommandProviderAdapter
from src.runtime.providers.local import LocalProviderAdapter
from src.runtime.providers.base import ProviderSession
from src.runtime.providers.cli_bridge import dispatch_via_cli_bridge


def request(app, method, path, body=None, correlation_id="corr-provider-dispatch"):
    return app.handle(
        method,
        path,
        body=body,
        headers={"x-correlation-id": correlation_id},
    )


def assert_ok(response, correlation_id="corr-provider-dispatch"):
    status, payload = response
    assert payload["ok"] is True
    assert payload["correlation_id"] == correlation_id
    assert "data" in payload
    return status, payload["data"]


def assert_error(response, *, status, code, correlation_id="corr-provider-dispatch"):
    actual_status, payload = response
    assert actual_status == status
    assert payload["ok"] is False
    assert payload["correlation_id"] == correlation_id
    assert payload["error"]["code"] == code


def test_provider_health_lists_local_deterministic_provider(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    workspace = create_workspace(app, tmp_path)

    status, data = assert_ok(
        request(app, "GET", f"/api/providers?workspace_id={workspace['id']}")
    )

    assert status == 200
    local = next(provider for provider in data["providers"] if provider["id"] == "local")
    assert local["name"] == "Local deterministic"
    assert local["health"] == "online"
    assert local["auth"] == "not_required"
    assert local["transport_kind"] == "deterministic"
    assert local["transport_posture"] == "builtin"
    assert local["degraded_reason"] is None
    assert "child_task_execution" in local["capabilities"]
    opencode = next(provider for provider in data["providers"] if provider["id"] == "opencode")
    assert opencode["transport_kind"] == "sdk"
    assert opencode["transport_posture"] == "sdk"
    assert opencode["degraded_reason"] is None


def test_provider_settings_can_be_saved_and_health_checked(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    workspace = create_workspace(app, tmp_path)

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace['id']}/providers/codex/test",
            {"path": "python3", "auth": "connected"},
        )
    )

    assert status == 200
    provider = data["provider"]
    assert provider["id"] == "codex"
    assert provider["path"] == "python3"
    assert provider["auth"] == "connected"
    assert provider["health"] == "online"
    assert provider["transport_kind"] == "sdk"
    assert provider["transport_posture"] == "sdk"
    assert "OpenAI SDK is the primary path" in provider["degraded_reason"]
    assert provider["last_checked_at"]

    _, providers_data = assert_ok(
        request(app, "GET", f"/api/providers?workspace_id={workspace['id']}")
    )
    codex = next(item for item in providers_data["providers"] if item["id"] == "codex")
    assert codex["path"] == "python3"
    assert codex["health"] == "online"
    assert codex["transport_posture"] == "sdk"
    assert "OpenAI SDK is the primary path" in codex["degraded_reason"]


def test_codex_provider_can_be_configured_for_sdk_only_mode(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    workspace = create_workspace(app, tmp_path)

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace['id']}/providers/codex/test",
            {
                "path": "",
                "auth": "connected",
                "api_key": "sk-test",
                "base_url": "https://example.invalid/v1",
                "model": "gpt-4.1-mini",
            },
        )
    )

    assert status == 200
    provider = data["provider"]
    assert provider["path"] == ""
    assert provider["health"] == "online"
    assert provider["transport_kind"] == "sdk"
    assert provider["api_key_configured"] is True
    assert provider["base_url"] == "https://example.invalid/v1"
    assert provider["model"] == "gpt-4.1-mini"

    _, providers_data = assert_ok(
        request(app, "GET", f"/api/providers?workspace_id={workspace['id']}")
    )
    codex = next(item for item in providers_data["providers"] if item["id"] == "codex")
    assert codex["path"] == ""
    assert codex["api_key_configured"] is True
    assert codex["base_url"] == "https://example.invalid/v1"
    assert codex["model"] == "gpt-4.1-mini"


def test_claude_provider_can_be_configured_for_sdk_only_mode(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    workspace = create_workspace(app, tmp_path)

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace['id']}/providers/claude/test",
            {
                "path": "",
                "auth": "connected",
                "api_key": "anthropic-test",
                "base_url": "https://example.invalid/anthropic",
                "model": "claude-sonnet-4-0",
            },
        )
    )

    assert status == 200
    provider = data["provider"]
    assert provider["path"] == ""
    assert provider["health"] == "online"
    assert provider["transport_kind"] == "sdk"
    assert provider["api_key_configured"] is True
    assert provider["base_url"] == "https://example.invalid/anthropic"
    assert provider["model"] == "claude-sonnet-4-0"

    _, providers_data = assert_ok(
        request(app, "GET", f"/api/providers?workspace_id={workspace['id']}")
    )
    claude = next(item for item in providers_data["providers"] if item["id"] == "claude")
    assert claude["path"] == ""
    assert claude["api_key_configured"] is True
    assert claude["base_url"] == "https://example.invalid/anthropic"
    assert claude["model"] == "claude-sonnet-4-0"


def test_provider_settings_are_scoped_per_workspace(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    workspace_a = create_workspace(app, tmp_path / "a")
    workspace_b = create_workspace(app, tmp_path / "b")

    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_a['id']}/providers/codex/test",
            {"path": "python3", "auth": "connected"},
        )
    )
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_b['id']}/providers/codex/test",
            {"path": "/missing/sarathi/codex", "auth": "missing"},
        )
    )

    _, providers_a = assert_ok(
        request(app, "GET", f"/api/providers?workspace_id={workspace_a['id']}")
    )
    _, providers_b = assert_ok(
        request(app, "GET", f"/api/providers?workspace_id={workspace_b['id']}")
    )

    codex_a = next(item for item in providers_a["providers"] if item["id"] == "codex")
    codex_b = next(item for item in providers_b["providers"] if item["id"] == "codex")
    assert codex_a["path"] == "python3"
    assert codex_a["health"] == "online"
    assert codex_b["path"] == "/missing/sarathi/codex"
    assert codex_b["health"] == "offline"


def test_provider_health_reports_missing_cli_path_with_actionable_error(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    workspace = create_workspace(app, tmp_path)

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace['id']}/providers/claude/test",
            {"path": "/missing/sarathi/claude", "auth": "missing"},
        )
    )

    assert status == 200
    provider = data["provider"]
    assert provider["id"] == "claude"
    assert provider["health"] == "offline"
    assert provider["auth"] == "missing"
    assert "CLI path not found" in provider["last_error"]


def test_provider_settings_reject_unknown_provider(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    workspace = create_workspace(app, tmp_path)

    assert_error(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace['id']}/providers/unknown/test",
            {"path": "missing"},
        ),
        status=404,
        code="not_found",
    )


def test_dispatch_requires_in_progress_subtask(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_ready_graph(app, tmp_path)
    _, studio_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    queued_node = studio_data["graph"]["nodes"][0]

    assert_error(
        request(app, "POST", f"/api/subtasks/{queued_node['id']}/dispatch"),
        status=409,
        code="invalid_state",
    )


def test_local_dispatch_persists_dispatch_evidence_and_moves_unit_to_review(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_ready_graph(app, tmp_path)
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "local"},
        )
    )

    assert status == 201
    assert data["dispatch"]["agent_name"] == "local"
    assert data["dispatch"]["status"] == "completed"
    assert data["dispatch"]["metadata"]["context_pack"]["phase"] == "TaskTracking"
    assert data["dispatch"]["metadata"]["context_pack"]["agent_input"]["objective"]
    assert data["dispatch"]["metadata"]["context_pack"]["compilation"]["full_history_excluded"] is True
    assert data["dispatch"]["metadata"]["agent_output"]["status"] == "completed"
    assert data["dispatch"]["metadata"]["agent_output"]["next_recommended_agent"] == "Nirnaya"
    assert data["dispatch"]["metadata"]["artifact_index"]["files_changed"] == [
        "src/confirm_plan_and.py",
        "tests/test_confirm_plan_and.py",
    ]
    assert data["dispatch"]["metadata"]["artifact_index"]["tests_run"] == [
        "python3 -m pytest tests/test_confirm_plan_and.py"
    ]
    assert data["evidence"]["artifact_type"] == "dispatch_result"
    assert data["evidence"]["metadata"]["artifact_index"]["files_changed"] == [
        "src/confirm_plan_and.py",
        "tests/test_confirm_plan_and.py",
    ]
    assert data["subtask"]["status"] == "review"

    _, studio_data = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    assert studio_data["dispatches"][0]["id"] == data["dispatch"]["id"]
    assert studio_data["evidence"][0]["id"] == data["evidence"]["id"]
    event_types = [event["event_type"] for event in studio_data["events"]]
    assert "context.compiled" in event_types
    assert "subtask.dispatched" in event_types
    assert "evidence.created" in event_types


def test_configured_command_provider_dispatches_non_local_work_unit(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_ready_graph(app, tmp_path)
    provider_script = _write_provider_script(
        tmp_path / "providers" / "codex-provider.py",
        (
            "import json,sys;"
            "request=json.load(sys.stdin);"
            "node=request['inputs'].get('node', {});"
            "print(json.dumps({"
            "'success': True,"
            "'outputs': {"
            "'messages': ['Codex shim completed work unit'],"
            "'work_unit_result': {"
            "'node_id': node.get('id'),"
            "'title': node.get('title'),"
            "'status': 'completed',"
            "'provider': 'codex',"
            "'summary': 'Codex shim completed work unit'"
            "}"
            "},"
            "'evidence': {"
            "'command_provider': True,"
            "'changed_files': ['src/codex_provider.py'],"
            "'tests_ran': ['python3 -m pytest tests/test_codex_provider.py']"
            "},"
            "'artifacts': {'bridge': 'shim'}"
            "}))"
        ),
    )

    # Use the task's workspace, not the extra helper workspace created above.
    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/codex/test",
            {"path": str(provider_script), "auth": "connected"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "codex"},
        )
    )

    assert status == 201
    assert data["dispatch"]["agent_name"] == "codex"
    assert data["dispatch"]["status"] == "completed"
    assert data["dispatch"]["metadata"]["outputs"]["work_unit_result"]["provider"] == "codex"
    assert data["dispatch"]["metadata"]["artifacts"]["bridge"] == "shim"
    assert data["dispatch"]["metadata"]["agent_output"]["summary"] == "Codex shim completed work unit"
    assert data["dispatch"]["metadata"]["artifact_index"]["files_changed"] == [
        "src/codex_provider.py"
    ]
    assert data["dispatch"]["metadata"]["artifact_index"]["tests_run"] == [
        "python3 -m pytest tests/test_codex_provider.py"
    ]
    assert data["subtask"]["status"] == "review"
    assert data["evidence"]["metadata"]["provider"] == "codex"
    assert data["evidence"]["metadata"]["response_evidence"]["command_provider"] is True


def test_local_provider_dispatch_attaches_estimated_usage():
    adapter = LocalProviderAdapter()
    response = adapter.dispatch(
        DispatchRequest(
            mode="execute",
            task_id="task-usage",
            phase="Build",
            prompt="Implement token tracking",
        )
    )

    assert response.success is True
    assert response.usage is not None
    assert response.usage.provider_id == "local"
    assert response.usage.provider_family == "local"
    assert response.usage.estimated is True
    assert response.usage.usage_source == "estimated"
    assert response.usage.total_tokens > 0


def test_command_provider_dispatch_uses_reported_usage_when_available(tmp_path):
    script = tmp_path / "usage_provider.py"
    script.write_text(
        (
            "import json,sys;"
            "request=json.load(sys.stdin);"
            "print(json.dumps({"
            "'success': True,"
            "'outputs': {'messages': ['done']},"
            "'evidence': {'command_provider': True},"
            "'artifacts': {'bridge': 'shim'},"
            "'usage': {"
            "'provider_id': 'demo',"
            "'provider_family': 'command',"
            "'dispatch_id': request['task_id'],"
            "'input_tokens': 50,"
            "'output_tokens': 25,"
            "'total_tokens': 75,"
            "'estimated': False,"
            "'budget_limit': 100,"
            "'budget_remaining': 25,"
            "'budget_state': 'warning',"
            "'usage_source': 'reported'"
            "}"
            "}))"
        )
    )
    adapter = CommandProviderAdapter("demo", [sys.executable, str(script)])

    response = adapter.dispatch(
        DispatchRequest(
            mode="execute",
            task_id="task-reported",
            phase="Build",
            prompt="Implement token tracking",
        )
    )

    assert response.success is True
    assert response.usage is not None
    assert response.usage.provider_id == "demo"
    assert response.usage.provider_family == "command"
    assert response.usage.estimated is False
    assert response.usage.total_tokens == 75
    assert response.usage.budget_state == "warning"


def test_command_provider_defaults_to_session_unsupported_response(tmp_path):
    script = tmp_path / "noop_provider.py"
    script.write_text("print('{}')")
    adapter = CommandProviderAdapter("demo", [sys.executable, str(script)])
    session = ProviderSession(session_id="sess-1", provider_name="demo", transport_kind="command")

    response = adapter.send_session_input(session, "continue")

    assert response.success is False
    assert response.error == "Provider 'demo' does not support session input"
    assert response.artifacts["session_id"] == "sess-1"


def test_dispatch_rejects_offline_non_local_provider(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_ready_graph(app, tmp_path)
    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/claude/test",
            {"path": "/missing/sarathi/claude", "auth": "connected"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]

    assert_error(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "claude"},
        ),
        status=409,
        code="provider_unavailable",
    )


def test_native_codex_provider_uses_cli_bridge_command():
    command = _provider_dispatch_command(
        provider_id="codex",
        path="/Applications/Codex.app/Contents/Resources/codex",
        workspace_root="/tmp/sarathi-workspace",
    )

    assert command[0]
    assert command[1:3] == ["-m", "src.runtime.providers.cli_bridge"]
    assert "--provider" in command
    assert command[command.index("--provider") + 1] == "codex"
    assert command[command.index("--path") + 1] == "/Applications/Codex.app/Contents/Resources/codex"


def test_native_claude_dispatch_runs_in_workspace_and_records_invocation_metadata(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_ready_graph(app, tmp_path)
    native_claude = _write_provider_script(
        tmp_path / "providers" / "claude",
        (
            "import json, os, sys;"
            "print(json.dumps({"
            "'success': True,"
            "'outputs': {'messages': ['Claude native bridge executed']},"
            "'evidence': {'cwd': os.getcwd(), 'argv': sys.argv[1:]},"
            "'artifacts': {'script': 'claude'}"
            "}))"
        ),
    )

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    workspace_root = str(tmp_path)
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/claude/test",
            {"path": str(native_claude), "auth": "connected"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "claude"},
        )
    )

    response_evidence = data["evidence"]["metadata"]["response_evidence"]
    dispatch_artifacts = data["dispatch"]["metadata"]["artifacts"]

    assert status == 201
    assert data["dispatch"]["agent_name"] == "claude"
    assert response_evidence["cwd"] == workspace_root
    assert response_evidence["argv"][0] == "-p"
    assert "--add-dir" in response_evidence["argv"]
    assert response_evidence["argv"][response_evidence["argv"].index("--add-dir") + 1] == workspace_root
    assert "--" in response_evidence["argv"]
    assert "Prompt:" in response_evidence["argv"][-1]
    assert "Task ID:" in response_evidence["argv"][-1]
    assert response_evidence["native_cli_family"] == "claude"
    assert response_evidence["workspace_root_used"] == workspace_root
    assert dispatch_artifacts["script"] == "claude"
    assert dispatch_artifacts["invocation_kind"] == "native_cli"
    assert dispatch_artifacts["workspace_root"] == workspace_root


def test_cli_bridge_can_route_claude_via_ncp_handoff(tmp_path, monkeypatch):
    workspace_root = tmp_path
    (workspace_root / ".ncp").mkdir(parents=True)
    (workspace_root / ".ncp" / "config.toml").write_text("[store]\ntype = 'sqlite'\n", encoding="utf-8")

    calls: list[list[str]] = []

    def _fake_run(command, **kwargs):
        calls.append(list(command))
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 0, stdout="Whisper emitted.\n", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"success":true,"outputs":{"messages":["ok"],"summary":"handled via ncp"},"evidence":{"ncp":true},"artifacts":{"script":"ncp"}}',
            stderr="",
        )

    monkeypatch.setattr("src.runtime.providers.cli_bridge.shutil.which", lambda name: "/usr/local/bin/ncp" if name == "ncp" else None)
    monkeypatch.setattr("src.runtime.providers.cli_bridge.subprocess.run", _fake_run)

    response = dispatch_via_cli_bridge(
        provider="claude",
        path="/usr/local/bin/claude",
        workspace_root=str(workspace_root),
        request=DispatchRequest(
            mode="execute",
            task_id="subtask-123",
            phase="TaskTracking",
            prompt="Implement the slice.",
            inputs={"node": {"id": "n1", "title": "Slice"}, "context_pack": {"agent_input": {"relevant_files": ["a.py"]}}},
            constraints={"purpose": "child_task_execution", "provider": "claude", "ncp_handoff_enabled": True},
        ),
    )

    assert response.success is True
    assert response.artifacts["ncp_handoff_used"] is True
    assert response.artifacts["transport_kind"] == "ncp_handoff"
    assert response.evidence["ncp_handoff_used"] is True
    assert calls[0][:3] == ["/usr/local/bin/ncp", "emit", "--cwd"]
    assert "--to" in calls[0]
    assert calls[0][calls[0].index("--to") + 1] == "claude"
    assert calls[1][:3] == ["/usr/local/bin/ncp", "handoff", "claude"]
    assert "--emit-to" in calls[1]
    assert calls[1][calls[1].index("--emit-to") + 1] == "opencode"
    assert "--pipeline-id" in calls[1]
    assert calls[1][calls[1].index("--pipeline-id") + 1] == "sarathi_subtask-123"


def test_native_copilot_dispatch_uses_github_cli_shape_and_records_invocation_metadata(tmp_path):
    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_ready_graph(app, tmp_path)
    native_gh = _write_provider_script(
        tmp_path / "providers" / "gh",
        (
            "import json, os, sys;"
            "print(json.dumps({"
            "'success': True,"
            "'outputs': {'messages': ['Copilot native bridge executed']},"
            "'evidence': {'cwd': os.getcwd(), 'argv': sys.argv[1:]},"
            "'artifacts': {'script': 'gh'}"
            "}))"
        ),
    )

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    workspace_root = str(tmp_path)
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/copilot/test",
            {"path": str(native_gh), "auth": "connected"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "copilot"},
        )
    )

    response_evidence = data["evidence"]["metadata"]["response_evidence"]
    dispatch_artifacts = data["dispatch"]["metadata"]["artifacts"]

    assert status == 201
    assert data["dispatch"]["agent_name"] == "copilot"
    assert response_evidence["cwd"] == workspace_root
    assert response_evidence["argv"][:3] == ["copilot", "--", "-p"]
    assert response_evidence["native_cli_family"] == "github_copilot"
    assert response_evidence["workspace_root_used"] == workspace_root
    assert dispatch_artifacts["script"] == "gh"
    assert dispatch_artifacts["invocation_kind"] == "native_cli"
    assert dispatch_artifacts["workspace_root"] == workspace_root


def test_native_opencode_dispatch_prefers_sdk_and_records_invocation_metadata(tmp_path, monkeypatch):
    from src.runtime.providers.opencode_sdk import OpenCodeSdkProviderAdapter

    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_ready_graph(app, tmp_path)
    native_opencode = _write_provider_script(
        tmp_path / "providers" / "opencode",
        "print('opencode version 1.0.0')",
    )

    monkeypatch.setattr(
        OpenCodeSdkProviderAdapter,
        "_run_sdk_bridge",
        lambda self, payload, timeout_seconds: {
            "success": True,
            "outputs": {"messages": ["OpenCode SDK bridge executed"]},
            "evidence": {
                "opencode_sdk": True,
                "provider_session_id": "sdk-session-123",
                "workspace_root_used": self.workspace_root,
            },
            "artifacts": {
                "provider_session_id": "sdk-session-123",
                "server_url": "http://127.0.0.1:4096",
            },
        },
    )

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    workspace_root = str(tmp_path)
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/opencode/test",
            {"path": str(native_opencode), "auth": "connected"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "opencode"},
        )
    )

    response_evidence = data["evidence"]["metadata"]["response_evidence"]
    dispatch_artifacts = data["dispatch"]["metadata"]["artifacts"]

    assert status == 201
    assert data["dispatch"]["agent_name"] == "opencode"
    assert response_evidence["opencode_sdk"] is True
    assert response_evidence["provider_session_id"] == "sdk-session-123"
    assert response_evidence["workspace_root_used"] == workspace_root
    assert dispatch_artifacts["invocation_kind"] == "sdk"
    assert dispatch_artifacts["transport_kind"] == "sdk"
    assert dispatch_artifacts["workspace_root"] == workspace_root


def test_claude_dispatch_uses_ncp_handoff_when_workspace_is_ncp_enabled(tmp_path, monkeypatch):
    from src.runtime.providers.anthropic_sdk import AnthropicSdkProviderAdapter

    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_ready_graph(app, tmp_path)
    (tmp_path / ".ncp").mkdir(parents=True)
    (tmp_path / ".ncp" / "config.toml").write_text("[store]\ntype = 'sqlite'\n", encoding="utf-8")
    native_claude = _write_provider_script(
        tmp_path / "providers" / "claude",
        "print('claude version 1.0.0')",
    )

    monkeypatch.setattr(
        AnthropicSdkProviderAdapter,
        "_run_sdk_bridge",
        lambda self, payload, timeout_seconds: (_ for _ in ()).throw(AssertionError("SDK path should not run")),
    )
    monkeypatch.setattr(
        "src.runtime.providers.anthropic_sdk.dispatch_via_cli_bridge",
        lambda **kwargs: DispatchResponse(
            success=True,
            outputs={
                "work_unit_result": {
                    "node_id": kwargs["request"].inputs["node"]["id"],
                    "title": kwargs["request"].inputs["node"]["title"],
                    "status": "completed",
                    "provider": "claude",
                    "summary": "routed through ncp handoff",
                }
            },
            evidence={"ncp_handoff_used": True},
            artifacts={"transport_kind": "ncp_handoff"},
        ),
    )

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/claude/test",
            {"path": str(native_claude), "auth": "connected"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]

    status, data = assert_ok(
        request(app, "POST", f"/api/subtasks/{running_node['id']}/dispatch", {"provider": "claude"})
    )

    assert status == 201
    assert data["dispatch"]["agent_name"] == "claude"
    assert data["dispatch"]["metadata"]["outputs"]["work_unit_result"]["provider"] == "claude"
    assert data["dispatch"]["metadata"]["artifacts"]["transport_kind"] == "ncp_handoff"


def test_opencode_dispatch_uses_ncp_handoff_when_workspace_is_ncp_enabled(tmp_path, monkeypatch):
    from src.runtime.providers.opencode_sdk import OpenCodeSdkProviderAdapter

    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_ready_graph(app, tmp_path)
    (tmp_path / ".ncp").mkdir(parents=True)
    (tmp_path / ".ncp" / "config.toml").write_text("[store]\ntype = 'sqlite'\n", encoding="utf-8")
    native_opencode = _write_provider_script(
        tmp_path / "providers" / "opencode",
        "print('opencode version 1.0.0')",
    )

    monkeypatch.setattr(
        OpenCodeSdkProviderAdapter,
        "_run_sdk_bridge",
        lambda self, payload, timeout_seconds: (_ for _ in ()).throw(AssertionError("SDK path should not run")),
    )
    monkeypatch.setattr(
        "src.runtime.providers.opencode_sdk.dispatch_via_cli_bridge",
        lambda **kwargs: DispatchResponse(
            success=True,
            outputs={
                "work_unit_result": {
                    "node_id": kwargs["request"].inputs["node"]["id"],
                    "title": kwargs["request"].inputs["node"]["title"],
                    "status": "completed",
                    "provider": "opencode",
                    "summary": "routed through ncp handoff",
                }
            },
            evidence={"ncp_handoff_used": True},
            artifacts={"transport_kind": "ncp_handoff"},
        ),
    )

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/opencode/test",
            {"path": str(native_opencode), "auth": "connected"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]

    status, data = assert_ok(
        request(app, "POST", f"/api/subtasks/{running_node['id']}/dispatch", {"provider": "opencode"})
    )

    assert status == 201
    assert data["dispatch"]["agent_name"] == "opencode"
    assert data["dispatch"]["metadata"]["outputs"]["work_unit_result"]["provider"] == "opencode"
    assert data["dispatch"]["metadata"]["artifacts"]["transport_kind"] == "ncp_handoff"


def test_native_codex_dispatch_prefers_sdk_and_records_invocation_metadata(tmp_path, monkeypatch):
    from src.runtime.providers.openai_sdk import OpenAISdkProviderAdapter

    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_ready_graph(app, tmp_path)
    native_codex = _write_provider_script(
        tmp_path / "providers" / "codex",
        "print('codex version 1.0.0')",
    )

    monkeypatch.setattr(
        OpenAISdkProviderAdapter,
        "_run_sdk_bridge",
        lambda self, payload, timeout_seconds: {
            "success": True,
            "outputs": {"messages": ["OpenAI SDK bridge executed"]},
            "evidence": {
                "openai_sdk": True,
                "provider_session_id": "sdk-session-codex-123",
                "workspace_root_used": self.workspace_root,
                "model": "gpt-4.1",
            },
            "artifacts": {
                "provider_session_id": "sdk-session-codex-123",
                "model": "gpt-4.1",
            },
        },
    )

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    workspace_root = str(tmp_path)
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/codex/test",
            {"path": str(native_codex), "auth": "connected"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "codex"},
        )
    )

    response_evidence = data["evidence"]["metadata"]["response_evidence"]
    dispatch_artifacts = data["dispatch"]["metadata"]["artifacts"]

    assert status == 201
    assert data["dispatch"]["agent_name"] == "codex"
    assert response_evidence["openai_sdk"] is True
    assert response_evidence["provider_session_id"] == "sdk-session-codex-123"
    assert response_evidence["workspace_root_used"] == workspace_root
    assert response_evidence["model"] == "gpt-4.1"
    assert dispatch_artifacts["invocation_kind"] == "sdk"
    assert dispatch_artifacts["transport_kind"] == "sdk"
    assert dispatch_artifacts["workspace_root"] == workspace_root


def test_native_claude_dispatch_prefers_sdk_and_records_invocation_metadata(tmp_path, monkeypatch):
    from src.runtime.providers.anthropic_sdk import AnthropicSdkProviderAdapter

    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_ready_graph(app, tmp_path)
    native_claude = _write_provider_script(
        tmp_path / "providers" / "claude",
        "print('claude version 1.0.0')",
    )

    monkeypatch.setattr(
        AnthropicSdkProviderAdapter,
        "_run_sdk_bridge",
        lambda self, payload, timeout_seconds: {
            "success": True,
            "outputs": {"messages": ["Anthropic SDK bridge executed"]},
            "evidence": {
                "anthropic_sdk": True,
                "provider_session_id": "sdk-session-claude-123",
                "workspace_root_used": self.workspace_root,
                "model": "claude-sonnet-4-0",
            },
            "artifacts": {
                "provider_session_id": "sdk-session-claude-123",
                "model": "claude-sonnet-4-0",
            },
        },
    )

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    workspace_root = str(tmp_path)
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/claude/test",
            {"path": str(native_claude), "auth": "connected"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "claude"},
        )
    )

    response_evidence = data["evidence"]["metadata"]["response_evidence"]
    dispatch_artifacts = data["dispatch"]["metadata"]["artifacts"]

    assert status == 201
    assert data["dispatch"]["agent_name"] == "claude"
    assert response_evidence["anthropic_sdk"] is True
    assert response_evidence["provider_session_id"] == "sdk-session-claude-123"
    assert response_evidence["workspace_root_used"] == workspace_root
    assert response_evidence["model"] == "claude-sonnet-4-0"
    assert dispatch_artifacts["invocation_kind"] == "sdk"
    assert dispatch_artifacts["transport_kind"] == "sdk"
    assert dispatch_artifacts["workspace_root"] == workspace_root


def test_codex_dispatch_can_run_in_sdk_only_mode_without_cli_path(tmp_path, monkeypatch):
    from src.runtime.providers.openai_sdk import OpenAISdkProviderAdapter

    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_ready_graph(app, tmp_path)

    monkeypatch.setattr(
        OpenAISdkProviderAdapter,
        "_run_sdk_bridge",
        lambda self, payload, timeout_seconds: {
            "success": True,
            "outputs": {"messages": ["OpenAI SDK bridge executed without CLI"]},
            "evidence": {
                "openai_sdk": True,
                "provider_session_id": "sdk-only-codex-123",
                "workspace_root_used": self.workspace_root,
                "model": payload.get("model"),
            },
            "artifacts": {
                "provider_session_id": "sdk-only-codex-123",
                "model": payload.get("model"),
            },
        },
    )

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/codex/test",
            {
                "path": "",
                "auth": "connected",
                "api_key": "sk-test",
                "model": "gpt-4.1-mini",
            },
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "codex"},
        )
    )

    response_evidence = data["evidence"]["metadata"]["response_evidence"]
    dispatch_artifacts = data["dispatch"]["metadata"]["artifacts"]

    assert status == 201
    assert data["dispatch"]["status"] == "completed"
    assert response_evidence["openai_sdk"] is True
    assert response_evidence["provider_session_id"] == "sdk-only-codex-123"
    assert response_evidence["model"] == "gpt-4.1-mini"
    assert dispatch_artifacts["invocation_kind"] == "sdk"
    assert dispatch_artifacts["transport_kind"] == "sdk"


def test_claude_dispatch_can_run_in_sdk_only_mode_without_cli_path(tmp_path, monkeypatch):
    from src.runtime.providers.anthropic_sdk import AnthropicSdkProviderAdapter

    app = create_app(tmp_path / "sarathi.db")
    task = create_task_with_ready_graph(app, tmp_path)

    monkeypatch.setattr(
        AnthropicSdkProviderAdapter,
        "_run_sdk_bridge",
        lambda self, payload, timeout_seconds: {
            "success": True,
            "outputs": {"messages": ["Anthropic SDK bridge executed without CLI"]},
            "evidence": {
                "anthropic_sdk": True,
                "provider_session_id": "sdk-only-claude-123",
                "workspace_root_used": self.workspace_root,
                "model": payload.get("model"),
            },
            "artifacts": {
                "provider_session_id": "sdk-only-claude-123",
                "model": payload.get("model"),
            },
        },
    )

    _, studio_before = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    workspace_id = studio_before["task"]["workspace_id"]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/providers/claude/test",
            {
                "path": "",
                "auth": "connected",
                "api_key": "anthropic-test",
                "model": "claude-sonnet-4-0",
            },
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/schedule"))
    _, scheduled_snapshot = assert_ok(request(app, "GET", f"/api/tasks/{task['id']}/studio"))
    running_node = scheduled_snapshot["graph"]["nodes"][0]

    status, data = assert_ok(
        request(
            app,
            "POST",
            f"/api/subtasks/{running_node['id']}/dispatch",
            {"provider": "claude"},
        )
    )

    response_evidence = data["evidence"]["metadata"]["response_evidence"]
    dispatch_artifacts = data["dispatch"]["metadata"]["artifacts"]

    assert status == 201
    assert data["dispatch"]["status"] == "completed"
    assert response_evidence["anthropic_sdk"] is True
    assert response_evidence["provider_session_id"] == "sdk-only-claude-123"
    assert response_evidence["model"] == "claude-sonnet-4-0"
    assert dispatch_artifacts["invocation_kind"] == "sdk"
    assert dispatch_artifacts["transport_kind"] == "sdk"


def create_workspace(app, tmp_path):
    _, workspace_data = assert_ok(
        request(
            app,
            "POST",
            "/api/workspaces",
            {"name": "Sarathi App", "root_path": str(tmp_path)},
        )
    )
    return workspace_data["workspace"]


def create_task_with_ready_graph(app, tmp_path):
    workspace = create_workspace(app, tmp_path)
    workspace_id = workspace["id"]
    _, draft_data = assert_ok(
        request(
            app,
            "POST",
            f"/api/workspaces/{workspace_id}/task-drafts",
            {"prompt": "Dispatch ready work unit.", "title": "Provider dispatch"},
        )
    )
    task = draft_data["task"]
    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/approve",
            {"name": "PRD/AC", "status": "approved"},
        )
    )
    assert_ok(request(app, "POST", f"/api/tasks/{task['id']}/graph-draft"))
    assert_ok(
        request(
            app,
            "POST",
            f"/api/tasks/{task['id']}/approve",
            {"name": "Task graph", "status": "approved"},
        )
    )
    return task


def _write_provider_script(path: Path, inline_python: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env python3\n" + inline_python + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path
