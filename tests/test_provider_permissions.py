import json
import stat
from pathlib import Path

from src.permissions import PermissionMode
from src.runtime import DispatchRequest
from src.runtime.providers.opencode_sdk import OpenCodeSdkProviderAdapter
from src.runtime.providers.cli_bridge import dispatch_via_cli_bridge
from src.runtime.providers.cli_bridge import ensure_provider_permissions


def _write_policy(root: Path) -> None:
    policy_dir = root / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "permissions.md").write_text(
        """# Permissions

```yaml
permissions:
  claude:
    modes:
      read_only:
        allowed_tools: [Read, Glob, Grep, LS, TodoRead]
      read_write:
        allowed_tools: [Read, Glob, Grep, LS, TodoRead, Write, Edit, TodoWrite]
      full:
        allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, LS, WebFetch, WebSearch, TodoRead, TodoWrite]
  codex:
    modes:
      read_only:
        full_auto: false
        disable_sandbox: false
      read_write:
        full_auto: true
        disable_sandbox: false
      full:
        full_auto: true
        disable_sandbox: true
  opencode:
    modes:
      read_only:
        permission:
          read: allow
          grep: allow
      read_write:
        permission:
          read: allow
          grep: allow
          edit: allow
          write: allow
      full:
        permission:
          read: allow
          grep: allow
          edit: allow
          write: allow
          bash: allow
```
"""
    )


def _write_legacy_policy(root: Path) -> None:
    policy_dir = root / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "permissions.md").write_text(
        """# Permissions

```yaml
permissions:
  claude:
    allowed_tools: [Bash]
  codex:
    full_auto: true
    disable_sandbox: true
  opencode:
    permission:
      bash: allow
```
"""
    )


def test_read_only_provider_permissions_do_not_enable_full_auto(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _write_policy(tmp_path)

    ensure_provider_permissions(str(tmp_path), permission_mode=PermissionMode.READ_ONLY)

    claude = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert claude["permissions"]["allow"] == ["Read", "Glob", "Grep", "LS", "TodoRead"]

    codex = (tmp_path / "home" / ".codex" / "config.yaml").read_text()
    assert "full-auto: true" not in codex
    assert "disable-sandbox: true" not in codex

    opencode = json.loads((tmp_path / "opencode.json").read_text())
    assert "autoapprove" not in opencode
    assert opencode["permission"] == {"read": "allow", "grep": "allow"}


def test_read_write_provider_permissions_allow_file_edits_without_disabling_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _write_policy(tmp_path)

    ensure_provider_permissions(str(tmp_path), permission_mode="read_write")

    claude = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "Edit" in claude["permissions"]["allow"]
    assert "Write" in claude["permissions"]["allow"]
    assert "Bash" not in claude["permissions"]["allow"]

    codex = (tmp_path / "home" / ".codex" / "config.yaml").read_text()
    assert "full-auto: true" in codex
    assert "disable-sandbox: true" not in codex

    opencode = json.loads((tmp_path / "opencode.json").read_text())
    assert opencode["permission"]["edit"] == "allow"
    assert opencode["permission"]["write"] == "allow"
    assert "bash" not in opencode["permission"]


def test_full_provider_permissions_use_full_mode_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _write_policy(tmp_path)

    ensure_provider_permissions(str(tmp_path), permission_mode=PermissionMode.FULL)

    claude = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "Bash" in claude["permissions"]["allow"]

    codex = (tmp_path / "home" / ".codex" / "config.yaml").read_text()
    assert "full-auto: true" in codex
    assert "disable-sandbox: true" in codex

    opencode = json.loads((tmp_path / "opencode.json").read_text())
    assert opencode["permission"]["bash"] == "allow"


def test_opencode_permission_mode_downgrade_removes_stale_grants(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _write_policy(tmp_path)

    ensure_provider_permissions(str(tmp_path), permission_mode=PermissionMode.FULL)
    ensure_provider_permissions(str(tmp_path), permission_mode=PermissionMode.READ_ONLY)

    opencode = json.loads((tmp_path / "opencode.json").read_text())
    assert opencode["permission"] == {"read": "allow", "grep": "allow"}


def test_legacy_flat_permissions_only_broaden_full_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _write_legacy_policy(tmp_path)

    ensure_provider_permissions(str(tmp_path), permission_mode=PermissionMode.READ_ONLY)

    claude = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "Bash" not in claude["permissions"]["allow"]
    codex = (tmp_path / "home" / ".codex" / "config.yaml").read_text()
    assert "full-auto: true" not in codex
    assert "disable-sandbox: true" not in codex
    opencode = json.loads((tmp_path / "opencode.json").read_text())
    assert "bash" not in opencode["permission"]

    ensure_provider_permissions(str(tmp_path), permission_mode=PermissionMode.FULL)

    claude = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert claude["permissions"]["allow"] == ["Bash"]
    codex = (tmp_path / "home" / ".codex" / "config.yaml").read_text()
    assert "full-auto: true" in codex
    assert "disable-sandbox: true" in codex
    opencode = json.loads((tmp_path / "opencode.json").read_text())
    assert opencode["permission"] == {"bash": "allow"}


def test_cli_bridge_applies_request_permission_mode_before_provider_launch(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _write_policy(tmp_path)
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "out = sys.argv[sys.argv.index('-o') + 1]\n"
        "open(out, 'w').write('codex ok')\n",
        encoding="utf-8",
    )
    fake_codex.chmod(fake_codex.stat().st_mode | stat.S_IXUSR)

    response = dispatch_via_cli_bridge(
        provider="codex",
        path=str(fake_codex),
        workspace_root=str(tmp_path),
        request=DispatchRequest(
            mode="execute",
            task_id="task-permissions",
            phase="Build",
            prompt="No-op",
            constraints={"permission_mode": "read_only"},
        ),
    )

    assert response.success is True
    codex = (tmp_path / "home" / ".codex" / "config.yaml").read_text()
    assert "full-auto: true" not in codex


def test_opencode_sdk_applies_request_permission_mode_before_helper(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _write_policy(tmp_path)
    adapter = OpenCodeSdkProviderAdapter(workspace_root=str(tmp_path))

    def fake_sdk_bridge(payload, *, timeout_seconds):
        return {"success": True, "outputs": {"messages": ["ok"]}}

    monkeypatch.setattr(adapter, "_run_sdk_bridge", fake_sdk_bridge)

    response = adapter.dispatch(
        DispatchRequest(
            mode="execute",
            task_id="task-opencode-sdk-permissions",
            phase="Build",
            prompt="No-op",
            constraints={"permission_mode": "read_write"},
        )
    )

    assert response.success is True
    opencode = json.loads((tmp_path / "opencode.json").read_text())
    assert opencode["permission"]["edit"] == "allow"
    assert opencode["permission"]["write"] == "allow"
    assert "bash" not in opencode["permission"]
