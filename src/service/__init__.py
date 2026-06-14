"""Minimal stdlib service boundary for Sarathi UI clients."""

from __future__ import annotations

from .app import RawResponse, ServiceApp, create_app
from .errors import ServiceError
from .http import create_http_server
from .providers import _provider_dispatch_command

__all__ = [
    "RawResponse",
    "ServiceApp",
    "ServiceError",
    "create_app",
    "create_http_server",
    "_provider_dispatch_command",
]
