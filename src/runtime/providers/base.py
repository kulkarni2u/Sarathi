"""Provider adapter contract."""
from __future__ import annotations

from abc import ABC, abstractmethod

try:
    from ..contracts import DispatchRequest, DispatchResponse
except ImportError:
    from runtime.contracts import DispatchRequest, DispatchResponse


class ProviderAdapter(ABC):
    """Abstract provider behind dispatcher execution."""

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        raise NotImplementedError
