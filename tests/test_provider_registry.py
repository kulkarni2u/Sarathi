"""Proves the "one spec, not a 10-file surgery" claim behind the native
provider registry (src/runtime/providers/registry.py).

Registers a throwaway fifth provider ("testprov") purely via `register_spec`
— never touching cli_bridge.py, service/providers.py, preflight.py,
tui_data.py, or harness.py — and demonstrates it flows through every site
that used to hardcode the four shipped providers:

  * the cli_bridge dispatch chain routes to its `dispatch_fn` (argv builder)
  * `ensure_provider_permissions` invokes its `permission_writer`
  * `provider_cli_versions()` (preflight) collects its version probe
  * `tui_data.ChatSession.PROVIDERS` includes it once `tui_chat_support=True`

The registry is process-global, so every test here registers via a fixture
that unregisters in teardown to avoid leaking "testprov" into other tests.
"""
from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from src.permissions import PermissionMode
from src.runtime import DispatchRequest
from src.runtime.providers.cli_bridge import (
    _policy_for_mode,
    dispatch_via_cli_bridge,
    ensure_provider_permissions,
)
from src.runtime.providers.registry import (
    NativeProviderSpec,
    get_spec,
    register_spec,
    unregister_spec,
)


def _fake_cli_script(tmp_path: Path, name: str, body: str) -> Path:
    script = tmp_path / name
    script.write_text("#!/usr/bin/env python3\n" + body + "\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _testprov_dispatch_fn(*, path: str, workspace_root: str, request: DispatchRequest):
    """The fifth provider's "argv builder" — shells out to the fake CLI,
    mirroring how _run_claude/_run_codex/_run_opencode/_run_copilot invoke
    their real CLIs. Proves the dispatch chain calls the spec's own function
    rather than a hardcoded if/elif."""
    from src.runtime.contracts import DispatchResponse

    argv = [path, "--prompt", request.prompt]
    completed = subprocess.run(
        argv, capture_output=True, text=True, cwd=workspace_root, timeout=request.timeout_seconds,
    )
    return DispatchResponse(
        success=completed.returncode == 0,
        outputs={"messages": [completed.stdout.strip()]},
        artifacts={"provider": "testprov", "argv": argv, "invocation_kind": "native_cli"},
    )


def _testprov_permission_writer(workspace_root: str, policy, permission_mode: PermissionMode) -> None:
    # Mirrors _write_claude_settings/_write_codex_config/_write_opencode_config:
    # `policy` here is the raw "testprov:" subtree from permissions.md: the
    # writer itself resolves it to the concrete per-mode dict via
    # _policy_for_mode, exactly like the four shipped writers do.
    mode_policy = _policy_for_mode("testprov", policy, permission_mode)
    marker = Path(workspace_root) / "testprov.marker.json"
    marker.write_text(
        json.dumps({"policy": mode_policy, "mode": permission_mode.value}), encoding="utf-8"
    )


def _testprov_permission_config_path(workspace_root: str) -> str:
    return str(Path(workspace_root) / "testprov.marker.json")


@pytest.fixture
def testprov_spec():
    """Register a fifth provider for the duration of one test, then remove it."""
    spec = NativeProviderSpec(
        name="testprov",
        family="testprov",
        executables=("testprov-cli",),
        dispatch_fn=_testprov_dispatch_fn,
        prompt_transport="argv",
        session_constraint_key=None,
        permission_modes={
            "read_only": {"allow_write": False},
            "read_write": {"allow_write": True},
            "full": {"allow_write": True, "allow_bash": True},
        },
        permission_writer=_testprov_permission_writer,
        permission_writer_unavailable_reason=None,
        permission_config_path=_testprov_permission_config_path,
        legacy_policy_keys=frozenset(),
        version_probe_key="testprov",
        version_probe_executable="testprov-cli",
        auth_probe=None,
        tui_chat_support=True,
        tui_streaming_handler=None,
        fallback_priority=50,
        service_catalog={
            "name": "Test Provider",
            "provider_type": "cli",
            "transport_kind": "cli",
            "transport_posture": "cli_fallback",
            "health": "configured_by_user",
            "auth": "workspace_setting",
            "path": "testprov-cli",
            "capabilities": ["coding"],
            "degraded_reason": None,
        },
    )
    register_spec(spec)
    try:
        yield spec
    finally:
        unregister_spec("testprov")


def test_registering_a_spec_is_the_only_wiring_needed(testprov_spec):
    """Sanity check: get_spec/all_specs see the fifth provider immediately."""
    assert get_spec("testprov") is testprov_spec
    assert get_spec("testprov").family == "testprov"


def test_dispatch_chain_routes_to_fifth_providers_argv_builder(tmp_path, testprov_spec):
    fake_cli = _fake_cli_script(
        tmp_path,
        "testprov-cli",
        "import sys; print('testprov ok: ' + sys.argv[sys.argv.index('--prompt') + 1])",
    )

    response = dispatch_via_cli_bridge(
        provider="testprov",
        path=str(fake_cli),
        workspace_root=str(tmp_path),
        request=DispatchRequest(
            mode="execute",
            task_id="task-testprov",
            phase="Build",
            prompt="hello from the registry test",
        ),
    )

    assert response.success is True
    assert response.outputs["messages"] == ["testprov ok: hello from the registry test"]
    assert response.artifacts["provider"] == "testprov"
    assert response.artifacts["argv"][0] == str(fake_cli)


def test_dispatch_chain_rejects_unregistered_provider_names():
    """Control: a name nobody registered still hits the "not implemented" path."""
    response = dispatch_via_cli_bridge(
        provider="not-a-real-provider",
        path="/bin/true",
        workspace_root="/tmp",
        request=DispatchRequest(mode="execute", task_id="t", phase="Build", prompt="x"),
    )
    assert response.success is False
    assert "not implemented" in (response.error or "")


def test_ensure_provider_permissions_invokes_fifth_providers_writer(tmp_path, testprov_spec):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "permissions.md").write_text(
        """# Permissions

```yaml
permissions:
  testprov:
    modes:
      read_only:
        allow_write: false
      full:
        allow_write: true
        allow_bash: true
```
""",
        encoding="utf-8",
    )

    written = ensure_provider_permissions(str(tmp_path), permission_mode=PermissionMode.FULL)

    assert written["testprov"] == str(tmp_path / "testprov.marker.json")
    marker = json.loads((tmp_path / "testprov.marker.json").read_text())
    assert marker["mode"] == "full"
    assert marker["policy"]["allow_write"] is True
    assert marker["policy"]["allow_bash"] is True


def test_preflight_version_collection_includes_fifth_provider(tmp_path, monkeypatch, testprov_spec):
    fake_cli = _fake_cli_script(
        tmp_path,
        "testprov-cli",
        "import sys; print('testprov-cli 9.9.9') if '--version' in sys.argv else None",
    )
    assert fake_cli.exists()
    monkeypatch.setenv("PATH", f"{tmp_path}:{__import__('os').environ.get('PATH', '')}")

    import src.runtime.preflight as preflight

    assert "testprov" in preflight._PROVIDER_VERSION_CLIS
    assert preflight._PROVIDER_VERSION_CLIS["testprov"] == "testprov-cli"

    versions = preflight.provider_cli_versions()
    assert "testprov" in versions
    assert versions["testprov"]["version"] == "testprov-cli 9.9.9"
    assert versions["testprov"]["auth"] == "unknown"


def test_tui_providers_includes_fifth_provider_when_chat_support_is_set(testprov_spec):
    from src import tui_data

    assert "testprov" in tui_data.ChatSession.PROVIDERS


def test_tui_providers_excludes_fifth_provider_without_chat_support(tmp_path):
    spec = NativeProviderSpec(
        name="testprov_nochat",
        family="testprov_nochat",
        executables=("testprov-nochat-cli",),
        dispatch_fn=_testprov_dispatch_fn,
        prompt_transport="argv",
        session_constraint_key=None,
        permission_modes=None,
        permission_writer=None,
        permission_writer_unavailable_reason="test fixture: no permission surface",
        permission_config_path=None,
        legacy_policy_keys=frozenset(),
        version_probe_key="testprov_nochat",
        version_probe_executable="testprov-nochat-cli",
        auth_probe=None,
        tui_chat_support=False,
        tui_streaming_handler=None,
        fallback_priority=51,
        service_catalog={
            "name": "Test Provider No Chat",
            "provider_type": "cli",
            "transport_kind": "cli",
            "transport_posture": "cli_fallback",
            "health": "configured_by_user",
            "auth": "workspace_setting",
            "path": "testprov-nochat-cli",
            "capabilities": [],
            "degraded_reason": "test fixture",
        },
    )
    register_spec(spec)
    try:
        from src import tui_data

        assert "testprov_nochat" not in tui_data.ChatSession.PROVIDERS
    finally:
        unregister_spec("testprov_nochat")
