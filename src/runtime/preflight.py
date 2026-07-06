"""Preflight policy evaluation for policy-pack validation."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class PreflightPolicy:
    """Controls which validation statuses block execution."""

    block_on_todo: bool = True
    block_on_drift: bool = False

    def should_block(self, todo_count: int, drift_count: int) -> bool:
        if self.block_on_todo and todo_count > 0:
            return True
        if self.block_on_drift and drift_count > 0:
            return True
        return False

    def warning_count(self, drift_count: int) -> int:
        return drift_count


# CLI binaries Sarathi can dispatch to or shell out to, mapped to the flag
# that prints a version string.
_PROVIDER_VERSION_CLIS: dict[str, str] = {
    "claude": "claude",
    "codex": "codex",
    "opencode": "opencode",
    "gh": "gh",
}


def _check_provider_auth_preflight(provider: str, path: str) -> str:
    """Check provider authentication status; return "ok", "needs_auth", or "unknown"."""
    if provider == "claude":
        return "unknown"

    if provider == "codex":
        try:
            result = subprocess.run(
                [path, "login", "status"],
                capture_output=True,
                timeout=5,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                return "ok"
            output = (result.stdout or "") + (result.stderr or "")
            if "not logged in" in output.lower():
                return "needs_auth"
            # Non-zero exit without clear "not logged in" message: treat as unknown
            # (could be missing subcommand on older versions)
            return "unknown"
        except Exception:
            return "unknown"

    if provider == "opencode":
        try:
            result = subprocess.run(
                [path, "auth", "list"],
                capture_output=True,
                timeout=5,
                text=True,
                check=False,
            )
            if result.returncode == 0 and (result.stdout or "").strip():
                return "ok"
            if result.returncode != 0:
                # Non-zero exit from auth list command suggests not logged in
                return "needs_auth"
            # Zero exit but empty output means not logged in
            return "needs_auth"
        except Exception:
            return "unknown"

    return "unknown"


def provider_cli_versions(timeout: int = 10) -> dict[str, dict[str, str | None]]:
    """Return version and auth status for known provider CLIs.

    Returns dict mapping provider name to {"version": version-string-or-None, "auth": auth-status}.
    Auth status is "ok", "needs_auth", or "unknown".

    Runs ``<cli> --version`` and auth probes for each known CLI with a short timeout. Never
    raises: a missing CLI, a non-zero exit, or a timeout simply yields
    ``None`` for that provider's version and "unknown" for auth.
    """
    result: dict[str, dict[str, str | None]] = {}
    for provider, executable in _PROVIDER_VERSION_CLIS.items():
        path = shutil.which(executable)
        if not path:
            result[provider] = {"version": None, "auth": "unknown"}
            continue
        try:
            version_result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
            result[provider] = {"version": None, "auth": "unknown"}
            continue
        output = (version_result.stdout or "").strip() or (version_result.stderr or "").strip()
        version = output or None
        auth_status = _check_provider_auth_preflight(provider, path)
        result[provider] = {"version": version, "auth": auth_status}
    return result
