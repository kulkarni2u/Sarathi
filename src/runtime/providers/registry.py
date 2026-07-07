"""Declarative registry of native provider CLI specs.

Every hardcoded per-provider branch that used to be scattered across
``cli_bridge.py``, ``service/providers.py``, ``preflight.py``, ``tui_data.py``,
and ``harness.py`` (permission whitelists, dispatch dispatch chains, CLI
executable maps, version/auth probes, TUI provider tables, fallback order)
consults this module instead. Adding a new native CLI provider (cursor-agent,
gemini-cli, amp, ...) means constructing one ``NativeProviderSpec`` and calling
``register_spec`` — no other file needs to change.

``cli_bridge.py`` owns the four shipped providers' run functions, permission
writers, and constants (they are genuinely provider-specific and stay put per
the "keep the function, reference it from the spec" rule); it registers its
specs at the bottom of its own module. This module never imports
``cli_bridge`` at load time — ``_ensure_seeded`` imports it lazily, on first
use, so the registry is populated regardless of which module a caller imports
first.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

try:
    from ..contracts import DispatchResponse
    from ...permissions import PermissionMode
except ImportError:
    from runtime.contracts import DispatchResponse
    from permissions import PermissionMode


@dataclass(frozen=True)
class SdkTransportSpec:
    """Optional SDK-first transport a provider can use ahead of its native CLI.

    ``requires_cli_path=True`` (opencode today) means this provider has no
    credential-only mode: the SDK payload always needs a resolved CLI path,
    and a missing one is a hard dispatch failure. ``requires_cli_path=False``
    (claude/codex today) means the SDK payload is used when an API key is
    configured *or* the resolved CLI path is this provider's own native
    binary; otherwise dispatch falls back to the plain command transport.
    """

    transport_type: str
    api_key_env: str | None = None
    requires_cli_path: bool = False


@dataclass(frozen=True)
class NativeProviderSpec:
    """Everything the hardcoded per-provider sites used to branch on."""

    # Identity
    name: str
    family: str
    executables: tuple[str, ...]

    # Dispatch (cli_bridge.py's dispatch chain)
    dispatch_fn: Callable[..., DispatchResponse]
    prompt_transport: str  # "stdin" | "argv"
    session_constraint_key: str | None

    # Permissions (cli_bridge.py's ensure_provider_permissions wiring)
    permission_modes: Mapping[str, Mapping[str, Any]] | None
    permission_writer: Callable[[str, Mapping[str, Any], PermissionMode], None] | None
    permission_writer_unavailable_reason: str | None
    permission_config_path: Callable[[str], str] | None
    legacy_policy_keys: frozenset[str]

    # Preflight (version + auth probes)
    version_probe_key: str
    version_probe_executable: str
    auth_probe: Callable[[str], tuple[str, str | None]] | None

    # TUI chat
    tui_chat_support: bool
    tui_streaming_handler: str | None

    # Fallback ordering (lower sorts first) and native_cli_family resolution
    fallback_priority: int
    family_by_executable: Mapping[str, str] = field(default_factory=dict)

    # service/providers.py catalog entry (name, provider_type, transport_kind,
    # transport_posture, health, auth, path, capabilities, degraded_reason)
    service_catalog: Mapping[str, Any] = field(default_factory=dict)

    # Optional SDK-first transport (claude/codex today)
    sdk_transport: SdkTransportSpec | None = None

    def native_cli_family(self, path_executable: str) -> str:
        """Resolve the native_cli_family artifact value for a resolved CLI path's basename."""
        return self.family_by_executable.get(path_executable.lower(), self.family)


_REGISTRY: dict[str, NativeProviderSpec] = {}
_SEEDED = False


def _ensure_seeded() -> None:
    """Import cli_bridge (which registers the four shipped specs) on first use.

    Deferred so this module never imports cli_bridge at its own import time —
    cli_bridge imports *this* module at its top, so an eager import here
    would be circular. Safe to call repeatedly; only imports once.
    """
    global _SEEDED
    if _SEEDED:
        return
    _SEEDED = True
    try:
        from . import cli_bridge  # noqa: F401  (side effect: register_spec calls)
    except ImportError:
        from runtime.providers import cli_bridge  # noqa: F401


def register_spec(spec: NativeProviderSpec) -> None:
    """Register (or replace) a provider spec. Used by cli_bridge's default
    seeding and by tests/extensions adding a new provider."""
    _REGISTRY[spec.name] = spec


def unregister_spec(name: str) -> None:
    """Remove a registered spec. Mainly for test teardown after `register_spec`
    adds a throwaway provider — the registry is process-global, so tests that
    register one should remove it afterwards to avoid leaking into other tests."""
    _REGISTRY.pop(name, None)


def get_spec(name: str) -> NativeProviderSpec | None:
    _ensure_seeded()
    return _REGISTRY.get(name)


def all_specs() -> dict[str, NativeProviderSpec]:
    _ensure_seeded()
    return dict(_REGISTRY)


def specs_by_fallback_priority() -> list[NativeProviderSpec]:
    """All registered specs ordered by ascending ``fallback_priority``."""
    return sorted(all_specs().values(), key=lambda spec: spec.fallback_priority)


# ---------------------------------------------------------------------------
# Shared auth probes (previously duplicated verbatim between
# src/service/providers.py and src/runtime/preflight.py)
# ---------------------------------------------------------------------------


def probe_codex_auth(path: str) -> tuple[str, str | None]:
    """Return (status, reason) via ``codex login status``."""
    try:
        result = subprocess.run(
            [path, "login", "status"],
            capture_output=True,
            timeout=5,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return "ok", None
        output = (result.stdout or "") + (result.stderr or "")
        if "not logged in" in output.lower():
            return "needs_auth", "CLI installed but not logged in (run: codex login)"
        # Non-zero exit without a clear "not logged in" message: treat as
        # unknown (could be a missing subcommand on older CLI versions).
        return "unknown", None
    except Exception:  # noqa: BLE001 — probe errors keep the provider online
        return "unknown", None


def probe_opencode_auth(path: str) -> tuple[str, str | None]:
    """Return (status, reason) via ``opencode auth list``."""
    try:
        result = subprocess.run(
            [path, "auth", "list"],
            capture_output=True,
            timeout=5,
            text=True,
            check=False,
        )
        if result.returncode == 0 and (result.stdout or "").strip():
            return "ok", None
        if result.returncode != 0:
            return "needs_auth", "CLI installed but not logged in (run: opencode auth login)"
        # Zero exit but empty output means not logged in.
        return "needs_auth", "CLI installed but not logged in (run: opencode auth login)"
    except Exception:  # noqa: BLE001 — probe errors keep the provider online
        return "unknown", None


def probe_unknown_auth(_path: str) -> tuple[str, str | None]:
    """Providers with no reliable non-interactive auth check (e.g. claude)."""
    return "unknown", None
