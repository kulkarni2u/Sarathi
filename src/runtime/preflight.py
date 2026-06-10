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


def provider_cli_versions(timeout: int = 10) -> dict[str, str | None]:
    """Return ``{provider: version-string-or-None}`` for known provider CLIs.

    Runs ``<cli> --version`` for each known CLI with a short timeout. Never
    raises: a missing CLI, a non-zero exit, or a timeout simply yields
    ``None`` for that provider.
    """
    versions: dict[str, str | None] = {}
    for provider, executable in _PROVIDER_VERSION_CLIS.items():
        path = shutil.which(executable)
        if not path:
            versions[provider] = None
            continue
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
            versions[provider] = None
            continue
        output = (result.stdout or "").strip() or (result.stderr or "").strip()
        versions[provider] = output or None
    return versions
