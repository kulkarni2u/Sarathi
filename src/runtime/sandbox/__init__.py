"""Sandbox executors for isolated command execution.

Public surface:
  - ``SandboxExecutor`` / ``SandboxResult`` — the provider-agnostic interface.
  - ``DockerSandboxExecutor`` / ``docker_available`` — the Docker backend.
  - ``build_sandbox_executor`` — factory resolving a policy/env spec to an
    executor (or None for the default host path).

Future executors (Modal, Daytona, ...) implement ``SandboxExecutor`` and are
wired through ``build_sandbox_executor`` without changing callers.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

try:
    from .base import SandboxExecutor, SandboxResult
    from .docker import DockerSandboxExecutor, docker_available
except ImportError:  # pragma: no cover - direct module import fallback
    from base import SandboxExecutor, SandboxResult
    from docker import DockerSandboxExecutor, docker_available


def build_sandbox_executor(spec: Any) -> SandboxExecutor | None:
    """Resolve ``spec`` to a SandboxExecutor, or None for host execution.

    ``spec`` may be:
      - ``None`` -> returns None (host execution)
      - a string such as ``"docker"``
      - a Mapping with a ``"sandbox"`` key, e.g. a policy ``execution`` block
        like ``{"sandbox": "docker", "image": "...", "network": "..."}``

    Returns a ``DockerSandboxExecutor`` when the resolved value is ``"docker"``;
    returns None for unknown values or ``None``. Never raises.
    """
    try:
        if spec is None:
            return None

        image: str | None = None
        network: str | None = None

        if isinstance(spec, Mapping):
            value = spec.get("sandbox")
            raw_image = spec.get("image")
            raw_network = spec.get("network")
            if isinstance(raw_image, str):
                image = raw_image
            if isinstance(raw_network, str):
                network = raw_network
        else:
            value = spec

        if not isinstance(value, str):
            return None

        if value.strip().lower() == "docker":
            kwargs: dict[str, Any] = {}
            if image is not None:
                kwargs["image"] = image
            if network is not None:
                kwargs["network"] = network
            return DockerSandboxExecutor(**kwargs)

        return None
    except Exception:
        return None


__all__ = [
    "SandboxExecutor",
    "SandboxResult",
    "DockerSandboxExecutor",
    "docker_available",
    "build_sandbox_executor",
]
