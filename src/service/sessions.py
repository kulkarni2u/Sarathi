"""Session helpers: sharing, co-drive participants, and session messages.

These module-level functions hold the real logic for the session HTTP
endpoints. Each takes a ``storage: Storage`` first, raises ``ServiceError``
on bad input, and returns plain dict/list payloads. The route branches in
``app.py`` stay thin and delegate here.
"""

from __future__ import annotations

import json
from pathlib import Path
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


def fork_session(
    storage: Storage,
    session_id: str,
    *,
    owner: str | None = None,
) -> dict[str, Any]:
    """Fork a session into a new, independent task + session.

    Clones the source session's message history into the new session, records
    a checkpoint capsule of the source task, and — when the workspace has an
    NCP bridge (``.ncp/config.toml`` + ``.ncp/run.py``) — seeds the fork with
    the parent task's persisted findings (warm start) and writes a fork-lineage
    memory chunk. The new task has its own id, so it measures/LEARNs
    independently. NCP wiring is additive: when no bridge is present, the
    ``ncp`` block is omitted entirely.
    """
    source_session = storage.get_session(session_id)
    if source_session is None:
        raise ServiceError("not_found", "Session not found.", 404)
    source_task = storage.get_task(source_session["task_id"])
    if source_task is None:
        raise ServiceError("not_found", "Source task not found.", 404)

    fork_owner = owner or source_session["owner"]
    workspace_id = source_task["workspace_id"]

    # --- NCP gate + parent-findings fetch (before creating the new task so the
    # findings can be baked into its metadata). ---
    workspace = storage.get_workspace(workspace_id)
    workspace_root = (
        Path(workspace["root_path"]).expanduser() if workspace is not None else None
    )
    ncp_run_path = workspace_root / ".ncp" / "run.py" if workspace_root is not None else None
    ncp_config_present = bool(
        workspace_root is not None
        and (workspace_root / ".ncp" / "config.toml").exists()
        and ncp_run_path is not None
        and ncp_run_path.exists()
    )
    ncp_adapter = None
    ncp_available = False
    seed_findings: list[str] = []
    if ncp_config_present:
        from src.ncp_adapter.persistence_adapter import NCPPersistenceAdapter

        ncp_adapter = NCPPersistenceAdapter(run_path=ncp_run_path)
        try:
            chunks = ncp_adapter._call_fetch(source_task.get("title") or "", k=5)
            ncp_available = True
            for chunk in chunks:
                text = ncp_adapter._reconstruct_chunk_text(chunk).strip()
                if not text:
                    continue
                seed_findings.append(text[:200])
                if len(seed_findings) >= 8:
                    break
        except Exception:
            ncp_available = False
            seed_findings = []

    # --- New task (independent measurement/LEARN) ---
    fork_metadata = dict(source_task.get("metadata") or {})
    fork_block: dict[str, Any] = {
        "forked_from_task": source_task["id"],
        "forked_from_session": session_id,
    }
    if ncp_config_present:
        fork_block["ncp_seed_findings"] = seed_findings
    fork_metadata["fork"] = fork_block

    new_task = storage.create_task(
        workspace_id=workspace_id,
        title=(source_task.get("title") or "Task") + " (fork)",
        description=source_task.get("description"),
        status="pending",
        metadata=fork_metadata,
        project_id=source_task.get("project_id"),
    )

    # --- Checkpoint capsule of the source (reuse checkpoint_capsules). ---
    checkpoint = storage.create_checkpoint_capsule(
        workspace_id=workspace_id,
        task_id=source_task["id"],
        summary=f"Fork checkpoint from session {session_id}",
        key_decisions=[],
        evidence_refs=[],
        repository_action_preference={},
        next_start_point="forked",
        created_by=fork_owner,
        project_id=source_task.get("project_id"),
    )

    # --- New session on the new task. ---
    new_session = storage.create_session(
        workspace_id=workspace_id,
        task_id=new_task["id"],
        owner=fork_owner,
        visibility="private",
    )

    # --- Copy message history into the new session. ---
    messages_copied = 0
    for message in storage.list_messages(session_id=session_id):
        storage.create_message(
            workspace_id=new_task["workspace_id"],
            task_id=new_task["id"],
            session_id=new_session["id"],
            role=message["role"],
            content=message["content"],
            metadata={"forked_from_message": message["id"]},
        )
        messages_copied += 1

    # --- NCP seed write (after the new task exists). ---
    ncp_block: dict[str, Any] | None = None
    if ncp_config_present:
        seed_written = False
        if ncp_available and ncp_adapter is not None:
            try:
                ncp_adapter._call_write_memory(
                    json.dumps(
                        {
                            "_sarathi_type": "ForkSeed",
                            "task_id": new_task["id"],
                            "forked_from_task": source_task["id"],
                            "checkpoint": checkpoint["id"],
                            "summary": f"Fork of '{source_task.get('title')}'",
                        }
                    ),
                    "episodic",
                    "tool_result",
                    f"sarathi.fork.{new_task['id']}",
                )
                seed_written = True
            except Exception:
                seed_written = False
        ncp_block = {
            "config_present": True,
            "available": ncp_available,
            "parent_findings_carried": len(seed_findings),
            "seed_written": seed_written,
        }

    # --- Lifecycle events. ---
    storage.create_lifecycle_event(
        workspace_id=workspace_id,
        task_id=source_task["id"],
        event_type="session.forked",
        payload={
            "object_id": session_id,
            "new_task_id": new_task["id"],
            "new_session_id": new_session["id"],
            "checkpoint_id": checkpoint["id"],
            **({"ncp": ncp_block} if ncp_block else {}),
        },
    )
    storage.create_lifecycle_event(
        workspace_id=workspace_id,
        task_id=new_task["id"],
        event_type="task.forked_created",
        payload={
            "object_id": new_task["id"],
            "forked_from_task": source_task["id"],
            "forked_from_session": session_id,
            "messages_copied": messages_copied,
        },
    )

    return {
        "source_session_id": session_id,
        "task": new_task,
        "session": new_session,
        "checkpoint": checkpoint,
        "messages_copied": messages_copied,
        **({"ncp": ncp_block} if ncp_block else {}),
    }
