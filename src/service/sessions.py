"""Session helpers: sharing, co-drive participants, and session messages.

These module-level functions hold the real logic for the session HTTP
endpoints. Each takes a ``storage: Storage`` first, raises ``ServiceError``
on bad input, and returns plain dict/list payloads. The route branches in
``app.py`` stay thin and delegate here.
"""

from __future__ import annotations

from typing import Any

from src.storage import Storage

from .errors import ServiceError

_SESSION_VISIBILITIES = {"private", "link"}
_SESSION_STATUSES = {"active", "closed"}
_JOINER_ROLES = {"driver", "observer"}


def create_task_session(
    storage: Storage,
    task: dict[str, Any],
    *,
    owner: str,
    visibility: str,
) -> dict[str, Any]:
    """Create a co-drive session for ``task`` and log ``session.created``."""
    if visibility not in _SESSION_VISIBILITIES:
        raise ServiceError(
            "invalid_request",
            "Unsupported visibility. Allowed values: private, link.",
            400,
        )
    session = storage.create_session(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        owner=owner,
        visibility=visibility,
    )
    storage.create_lifecycle_event(
        workspace_id=task["workspace_id"],
        task_id=task["id"],
        event_type="session.created",
        payload={
            "object_id": session["id"],
            "owner": owner,
            "visibility": visibility,
        },
    )
    return session


def attach_via_share_token(
    storage: Storage,
    *,
    share_token: str,
    user: str,
    role: str,
) -> dict[str, Any]:
    """Join a session resolved by its share token. Returns session + participant."""
    session = storage.get_session_by_share_token(share_token)
    if session is None:
        raise ServiceError("not_found", "Session share link not found.", 404)
    if session["status"] == "closed":
        raise ServiceError("conflict", "Session is closed.", 409)
    if role not in _JOINER_ROLES:
        raise ServiceError(
            "invalid_request",
            "Unsupported role. Allowed values: driver, observer.",
            400,
        )
    participant = storage.add_session_participant(
        session_id=session["id"],
        user=user,
        role=role,
    )
    storage.create_lifecycle_event(
        workspace_id=session["workspace_id"],
        task_id=session["task_id"],
        event_type="session.participant_joined",
        payload={"object_id": session["id"], "user": user, "role": role},
    )
    return {"session": session, "participant": participant}


def join_session(
    storage: Storage,
    session_id: str,
    *,
    user: str,
    role: str,
) -> dict[str, Any]:
    """Join a session by id. Returns the participant dict."""
    session = storage.get_session(session_id)
    if session is None:
        raise ServiceError("not_found", "Session not found.", 404)
    if session["status"] == "closed":
        raise ServiceError("conflict", "Session is closed.", 409)
    if role not in _JOINER_ROLES:
        raise ServiceError(
            "invalid_request",
            "Unsupported role. Allowed values: driver, observer.",
            400,
        )
    participant = storage.add_session_participant(
        session_id=session["id"],
        user=user,
        role=role,
    )
    storage.create_lifecycle_event(
        workspace_id=session["workspace_id"],
        task_id=session["task_id"],
        event_type="session.participant_joined",
        payload={"object_id": session["id"], "user": user, "role": role},
    )
    return participant


def leave_session(
    storage: Storage,
    session_id: str,
    *,
    user: str,
) -> dict[str, Any]:
    """Leave a session (soft delete the participant). Returns the participant."""
    session = storage.get_session(session_id)
    if session is None:
        raise ServiceError("not_found", "Session not found.", 404)
    existing = storage.get_session_participant(session_id, user)
    if existing is None:
        raise ServiceError("not_found", "Participant not found.", 404)
    participant = storage.remove_session_participant(session_id, user)
    storage.create_lifecycle_event(
        workspace_id=session["workspace_id"],
        task_id=session["task_id"],
        event_type="session.participant_left",
        payload={"object_id": session["id"], "user": user},
    )
    return participant


def post_session_message(
    storage: Storage,
    session: dict[str, Any],
    *,
    user: str,
    content: str,
    role: str | None,
) -> dict[str, Any]:
    """Post a message into a session. Observers and non-participants are blocked."""
    participant = storage.get_session_participant(session["id"], user)
    if participant is None or participant["status"] != "active":
        raise ServiceError(
            "forbidden",
            "You are not an active participant in this session.",
            403,
        )
    if participant["role"] == "observer":
        raise ServiceError("forbidden", "Observers cannot post messages.", 403)
    message = storage.create_message(
        workspace_id=session["workspace_id"],
        task_id=session["task_id"],
        session_id=session["id"],
        role=role or "user",
        content=content,
    )
    storage.create_lifecycle_event(
        workspace_id=session["workspace_id"],
        task_id=session["task_id"],
        event_type="message.created",
        payload={
            "object_id": message["id"],
            "session_id": session["id"],
            "user": user,
        },
    )
    return message


def update_task_session(
    storage: Storage,
    session_id: str,
    *,
    visibility: str | None,
    status: str | None,
) -> dict[str, Any]:
    """Update a session's visibility/status and log ``session.updated``."""
    if visibility is not None and visibility not in _SESSION_VISIBILITIES:
        raise ServiceError(
            "invalid_request",
            "Unsupported visibility. Allowed values: private, link.",
            400,
        )
    if status is not None and status not in _SESSION_STATUSES:
        raise ServiceError(
            "invalid_request",
            "Unsupported status. Allowed values: active, closed.",
            400,
        )
    try:
        session = storage.update_session(
            session_id,
            visibility=visibility,
            status=status,
        )
    except KeyError:
        raise ServiceError("not_found", "Session not found.", 404)
    storage.create_lifecycle_event(
        workspace_id=session["workspace_id"],
        task_id=session["task_id"],
        event_type="session.updated",
        payload={
            "object_id": session["id"],
            "visibility": session["visibility"],
            "status": session["status"],
        },
    )
    return session
