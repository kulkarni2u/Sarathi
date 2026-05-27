"""NCP adapter package — replaces Sarathi context/storage with NCP runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class NCPNotAvailableError(RuntimeError):
    """Raised when NCP is requested but unreachable."""


@dataclass
class NCPAdapterConfig:
    """Configuration for NCP adapter instances."""
    mode: Literal["direct", "mcp"] = "direct"
    endpoint: str = "http://127.0.0.1:4242/mcp"
    run_path: Path = Path(".ncp/run.py")
    default_k: int = 3
    min_confidence: float = 0.60


try:
    from .context_adapter import NCPContextAdapter
except ImportError as e:
    raise ImportError(
        "NCPContextAdapter is not available. Ensure all ncp_adapter dependencies are "
        f"installed. Missing dependency: {e}"
    ) from e

try:
    from .persistence_adapter import NCPPersistenceAdapter
except ImportError as e:
    raise ImportError(
        "NCPPersistenceAdapter is not available. Ensure all ncp_adapter dependencies are "
        f"installed. Missing dependency: {e}"
    ) from e

try:
    from .artifact_adapter import NCPArtifactAdapter
except ImportError as e:
    raise ImportError(
        "NCPArtifactAdapter is not available. Ensure all ncp_adapter dependencies are "
        f"installed. Missing dependency: {e}"
    ) from e

try:
    from .whisper_router import NCPWhisperRouter
except ImportError as e:
    raise ImportError(
        "NCPWhisperRouter is not available. Ensure all ncp_adapter dependencies are "
        f"installed. Missing dependency: {e}"
    ) from e

__all__ = [
    "NCPAdapterConfig",
    "NCPNotAvailableError",
    "NCPContextAdapter",
    "NCPPersistenceAdapter",
    "NCPArtifactAdapter",
    "NCPWhisperRouter",
]
