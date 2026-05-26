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
    from .context_adapter import NCPContextAdapter  # noqa: F401
except ImportError:
    pass

try:
    from .persistence_adapter import NCPPersistenceAdapter  # noqa: F401
except ImportError:
    pass

try:
    from .artifact_adapter import NCPArtifactAdapter  # noqa: F401
except ImportError:
    pass

try:
    from .whisper_router import NCPWhisperRouter  # noqa: F401
except ImportError:
    pass

__all__ = [
    "NCPAdapterConfig",
    "NCPNotAvailableError",
    "NCPContextAdapter",
    "NCPPersistenceAdapter",
    "NCPArtifactAdapter",
    "NCPWhisperRouter",
]
