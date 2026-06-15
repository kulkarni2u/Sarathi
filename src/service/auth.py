"""Optional multi-user authentication for the Sarathi service.

Default behavior is single-user local: a single shared bearer token guards
the JSON API (handled by ``ServiceApp._authorize``), and ``auth_enabled()``
is False. Opting in with ``SARATHI_AUTH_ENABLED=1`` turns on per-user token
auth: each request must carry either the admin token (the service's shared
token) or a valid, active user token from the ``users`` table, and the
resolved :class:`Principal` is threaded into routing so endpoints can enforce
participant roles against the authenticated identity rather than a
client-supplied field.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import ServiceError


def auth_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return True when opt-in multi-user auth is enabled via env."""
    env = environ if environ is not None else os.environ
    return env.get("SARATHI_AUTH_ENABLED") == "1"


@dataclass(frozen=True)
class Principal:
    """The authenticated identity behind a request (auth-on mode only)."""

    user_id: str
    username: str
    is_admin: bool = False


def _bearer_from_headers(headers: Mapping[str, str] | None) -> str | None:
    for key, value in (headers or {}).items():
        if key.lower() == "authorization":
            text = str(value)
            if text.startswith("Bearer "):
                return text[len("Bearer ") :]
    return None


def resolve_principal(
    storage: Any,
    headers: Mapping[str, str] | None,
    *,
    admin_token: str | None,
    enabled: bool,
) -> Principal | None:
    """Resolve the request principal when auth is enabled.

    Returns ``None`` when ``enabled`` is False (callers fall back to the
    legacy single shared-token check). When enabled, the bearer must match
    the admin token (-> admin principal) or an active user token in the
    ``users`` table; otherwise a 401 ``ServiceError`` is raised.
    """
    if not enabled:
        return None
    bearer = _bearer_from_headers(headers)
    if not bearer:
        raise ServiceError("unauthorized", "Missing or invalid authorization token.", 401)
    if admin_token is not None and bearer == admin_token:
        return Principal(user_id="admin", username="admin", is_admin=True)
    user = storage.get_user_by_token(bearer)
    if user is None or user.get("status") != "active":
        raise ServiceError("unauthorized", "Missing or invalid authorization token.", 401)
    return Principal(user_id=user["id"], username=user["username"])


def require_admin(principal: Principal | None) -> None:
    """Raise 403 unless the principal is an admin.

    In auth-off mode ``principal`` is ``None`` and the caller has already
    passed the shared-token check, which is the admin-equivalent locally, so
    this is a no-op.
    """
    if principal is not None and not principal.is_admin:
        raise ServiceError("forbidden", "Admin privileges are required.", 403)
