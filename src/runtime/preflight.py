"""Preflight policy evaluation for policy-pack validation."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

try:
    from .providers.registry import all_specs
except ImportError:
    from runtime.providers.registry import all_specs


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
# that prints a version string. Built from the native provider registry so a
# newly registered provider's version probe (and, for copilot's oddity where
# the probed executable "gh" doesn't share its provider name "copilot", its
# own `version_probe_key`) shows up here automatically.
def _provider_version_clis() -> dict[str, str]:
    return {spec.version_probe_key: spec.version_probe_executable for spec in all_specs().values()}


def __getattr__(name: str):  # noqa: D103 — PEP 562 module-level dynamic attribute
    # `_PROVIDER_VERSION_CLIS` is recomputed on every access (instead of a
    # frozen snapshot taken at import time) so providers registered after
    # this module was first imported — e.g. a test registering a fifth
    # provider — still show up in it and in provider_cli_versions().
    if name == "_PROVIDER_VERSION_CLIS":
        return _provider_version_clis()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _check_provider_auth_preflight(provider: str, path: str) -> str:
    """Check provider authentication status; return "ok", "needs_auth", or "unknown".

    ``provider`` is a ``_PROVIDER_VERSION_CLIS`` key (a ``version_probe_key``,
    e.g. "gh" for copilot) rather than necessarily a registered provider name;
    when it doesn't match any spec's auth probe this returns "unknown".
    """
    for spec in all_specs().values():
        if spec.version_probe_key == provider and spec.auth_probe is not None:
            return spec.auth_probe(path)[0]
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
    for provider, executable in _provider_version_clis().items():
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
