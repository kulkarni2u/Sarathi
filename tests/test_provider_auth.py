"""Tests for provider authentication status detection.

These tests verify that the auth probe logic correctly identifies login state
for providers like codex and opencode, handles probe errors gracefully, and
treats probe failures as "unknown" to keep providers online.
"""
from __future__ import annotations

import stat
from pathlib import Path

from src.runtime.preflight import _check_provider_auth_preflight
from src.service.providers import _check_provider_auth


def _fake_cli_script(tmp_path: Path, name: str, body: str) -> str:
    """Create a fake executable CLI script in tmp_path."""
    script = tmp_path / name
    script.write_text("#!/usr/bin/env python3\n" + body + "\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


class TestCheckProviderAuthService:
    """Tests for _check_provider_auth in src/service/providers.py"""

    def test_codex_logged_in_returns_ok(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "codex",
            "import sys; sys.exit(0)",
        )
        auth_status, reason = _check_provider_auth("codex", path)
        assert auth_status == "ok"
        assert reason is None

    def test_codex_not_logged_in_with_explicit_message_returns_needs_auth(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "codex",
            'import sys; print("Not logged in"); sys.exit(1)',
        )
        auth_status, reason = _check_provider_auth("codex", path)
        assert auth_status == "needs_auth"
        assert "codex login" in reason

    def test_codex_not_logged_in_with_stderr_returns_needs_auth(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "codex",
            'import sys; sys.stderr.write("Not logged in"); sys.exit(1)',
        )
        auth_status, reason = _check_provider_auth("codex", path)
        assert auth_status == "needs_auth"
        assert "codex login" in reason

    def test_codex_non_zero_exit_without_explicit_message_returns_unknown(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "codex",
            "import sys; sys.exit(1)",
        )
        auth_status, reason = _check_provider_auth("codex", path)
        assert auth_status == "unknown"
        assert reason is None

    def test_codex_timeout_returns_unknown(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "codex",
            "import time; time.sleep(10)",
        )
        auth_status, reason = _check_provider_auth("codex", path)
        assert auth_status == "unknown"
        assert reason is None

    def test_codex_missing_login_subcommand_returns_unknown(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "codex",
            'import sys; print("Unknown command"); sys.exit(127)',
        )
        auth_status, reason = _check_provider_auth("codex", path)
        assert auth_status == "unknown"
        assert reason is None

    def test_opencode_logged_in_returns_ok(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "opencode",
            'print("user@example.com"); import sys; sys.exit(0)',
        )
        auth_status, reason = _check_provider_auth("opencode", path)
        assert auth_status == "ok"
        assert reason is None

    def test_opencode_not_logged_in_empty_output_returns_needs_auth(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "opencode",
            "import sys; sys.exit(1)",
        )
        auth_status, reason = _check_provider_auth("opencode", path)
        assert auth_status == "needs_auth"
        assert "opencode auth login" in reason

    def test_opencode_not_logged_in_zero_exit_empty_output_returns_needs_auth(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "opencode",
            "print('')",
        )
        auth_status, reason = _check_provider_auth("opencode", path)
        assert auth_status == "needs_auth"
        assert "opencode auth login" in reason

    def test_opencode_timeout_returns_unknown(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "opencode",
            "import time; time.sleep(10)",
        )
        auth_status, reason = _check_provider_auth("opencode", path)
        assert auth_status == "unknown"
        assert reason is None

    def test_claude_always_returns_unknown(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "claude",
            "import sys; sys.exit(0)",
        )
        auth_status, reason = _check_provider_auth("claude", path)
        assert auth_status == "unknown"
        assert reason is None

    def test_claude_always_returns_unknown_on_error(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "claude",
            "import sys; sys.exit(1)",
        )
        auth_status, reason = _check_provider_auth("claude", path)
        assert auth_status == "unknown"
        assert reason is None

    def test_unknown_provider_returns_unknown(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "unknown",
            "import sys; sys.exit(0)",
        )
        auth_status, reason = _check_provider_auth("unknown", path)
        assert auth_status == "unknown"
        assert reason is None


class TestCheckProviderAuthPreflight:
    """Tests for _check_provider_auth_preflight in src/runtime/preflight.py"""

    def test_codex_logged_in_returns_ok(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "codex",
            "import sys; sys.exit(0)",
        )
        auth_status = _check_provider_auth_preflight("codex", path)
        assert auth_status == "ok"

    def test_codex_not_logged_in_returns_needs_auth(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "codex",
            'import sys; sys.stderr.write("not logged in"); sys.exit(1)',
        )
        auth_status = _check_provider_auth_preflight("codex", path)
        assert auth_status == "needs_auth"

    def test_codex_timeout_returns_unknown(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "codex",
            "import time; time.sleep(10)",
        )
        auth_status = _check_provider_auth_preflight("codex", path)
        assert auth_status == "unknown"

    def test_opencode_logged_in_returns_ok(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "opencode",
            'print("user@example.com"); import sys; sys.exit(0)',
        )
        auth_status = _check_provider_auth_preflight("opencode", path)
        assert auth_status == "ok"

    def test_opencode_not_logged_in_returns_needs_auth(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "opencode",
            "import sys; sys.exit(1)",
        )
        auth_status = _check_provider_auth_preflight("opencode", path)
        assert auth_status == "needs_auth"

    def test_opencode_timeout_returns_unknown(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "opencode",
            "import time; time.sleep(10)",
        )
        auth_status = _check_provider_auth_preflight("opencode", path)
        assert auth_status == "unknown"

    def test_claude_always_returns_unknown(self, tmp_path):
        path = _fake_cli_script(
            tmp_path,
            "claude",
            "import sys; sys.exit(0)",
        )
        auth_status = _check_provider_auth_preflight("claude", path)
        assert auth_status == "unknown"


class TestProviderCheckConfigIntegration:
    """Integration tests: auth probe in _provider_check_config."""

    def test_provider_check_config_codex_logged_out_with_message_sets_needs_auth(self, tmp_path, monkeypatch):
        from src.service.providers import _provider_check_config

        path = _fake_cli_script(
            tmp_path,
            "codex",
            'import sys; print("not logged in"); sys.exit(1)',
        )

        spec = {
            "id": "codex",
            "path": "codex",
            "auth": "workspace_setting",
        }

        config = _provider_check_config(spec, path=path, auth="workspace_setting")

        assert config["health"] == "online"
        assert config["auth"] == "needs_auth"
        assert "codex login" in config.get("last_error", "")
        assert "codex login" in config.get("degraded_reason", "")

    def test_provider_check_config_codex_logged_in_stays_online(self, tmp_path, monkeypatch):
        from src.service.providers import _provider_check_config

        path = _fake_cli_script(
            tmp_path,
            "codex",
            'import sys; sys.exit(0)',
        )

        spec = {
            "id": "codex",
            "path": "codex",
            "auth": "workspace_setting",
        }

        config = _provider_check_config(spec, path=path, auth="workspace_setting")

        assert config["health"] == "online"
        assert config["auth"] == "workspace_setting"
        assert config["last_error"] is None

    def test_provider_check_config_opencode_logged_out_sets_needs_auth(self, tmp_path, monkeypatch):
        from src.service.providers import _provider_check_config

        path = _fake_cli_script(
            tmp_path,
            "opencode",
            'import sys; sys.exit(1)',
        )

        spec = {
            "id": "opencode",
            "path": "opencode",
            "auth": "workspace_setting",
        }

        config = _provider_check_config(spec, path=path, auth="workspace_setting")

        assert config["health"] == "online"
        assert config["auth"] == "needs_auth"
        assert "opencode auth login" in config.get("last_error", "")
        assert "opencode auth login" in config.get("degraded_reason", "")

    def test_provider_check_config_opencode_logged_in_stays_online(self, tmp_path, monkeypatch):
        from src.service.providers import _provider_check_config

        path = _fake_cli_script(
            tmp_path,
            "opencode",
            'print("user@example.com"); import sys; sys.exit(0)',
        )

        spec = {
            "id": "opencode",
            "path": "opencode",
            "auth": "workspace_setting",
        }

        config = _provider_check_config(spec, path=path, auth="workspace_setting")

        assert config["health"] == "online"
        assert config["auth"] == "workspace_setting"
        assert config["last_error"] is None

    def test_provider_check_config_auth_probe_error_keeps_provider_online(self, tmp_path, monkeypatch):
        from src.service.providers import _provider_check_config

        path = _fake_cli_script(
            tmp_path,
            "codex",
            "import time; time.sleep(10)",
        )

        spec = {
            "id": "codex",
            "path": "codex",
            "auth": "workspace_setting",
        }

        config = _provider_check_config(spec, path=path, auth="workspace_setting")

        assert config["health"] == "online"
        assert config["auth"] == "workspace_setting"
        assert config["last_error"] is None

    def test_provider_check_config_claude_skip_auth_probe(self, tmp_path, monkeypatch):
        from src.service.providers import _provider_check_config

        path = _fake_cli_script(
            tmp_path,
            "claude",
            'import sys; sys.exit(1)',
        )

        spec = {
            "id": "claude",
            "path": "claude",
            "auth": "workspace_setting",
        }

        config = _provider_check_config(spec, path=path, auth="workspace_setting")

        assert config["health"] == "online"
        assert config["auth"] == "workspace_setting"
        assert config["last_error"] is None
