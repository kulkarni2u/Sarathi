"""Service error type, request-parsing helpers, and JSON response builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import uuid4
from urllib.parse import parse_qs, urlparse

MAX_BODY_BYTES = 64 * 1024


@dataclass(frozen=True)
class ServiceError(Exception):
    code: str
    message: str
    status: int


def _path_parts(path: str) -> list[str]:
    return [part for part in path.split("?")[0].split("/") if part]


def _query(path: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(path).query)


def _first_query(query: Mapping[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]


def _correlation_id(headers: Mapping[str, str] | None) -> str:
    if headers:
        for key, value in headers.items():
            if key.lower() == "x-correlation-id" and value:
                return value
    return uuid4().hex


def _ok(data: dict[str, Any], correlation_id: str) -> dict[str, Any]:
    return {"ok": True, "data": data, "correlation_id": correlation_id}


def _error(error: ServiceError, correlation_id: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": error.code,
            "message": error.message,
            "status": error.status,
        },
        "correlation_id": correlation_id,
    }
