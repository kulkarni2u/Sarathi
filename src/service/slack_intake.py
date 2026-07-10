"""Inbound Slack slash-command intake: ``/sarathi run`` and ``/sarathi status``.

This module completes the Slack loop paired with outbound notifications in
``src/notifications.py``: `/sarathi run <description>` drafts a PRD/AC-gated
task (reusing ``_create_slack_task_draft`` from ``.intake``, which emits the
same ``task.draft_created`` / ``approval.requested`` lifecycle events as the
other intake paths — including firing outbound Slack notifications
automatically when a workspace's environment has them configured), and
`/sarathi status <task-id>` reports a task's current state.

Design rules (mirroring ``src/notifications.py``):

- **Secrets stay in the environment**: the signing secret is read from
  ``SARATHI_SLACK_SIGNING_SECRET`` — never from a policy file.
- **Feature is off by default**: when the signing secret env var is unset,
  the route is disabled (see ``ServiceApp._handle_slack_command`` in
  ``app.py``, which 404s in that case).
- **Verification is pure and injectable**: ``verify_slack_signature`` takes
  an explicit ``now`` for deterministic tests; no wall-clock reads hide
  inside it by default behavior beyond the ``time.time()`` fallback.

Slack's expected slash-command response shape is always
``{"response_type": "ephemeral" | "in_channel", "text": ...}`` with HTTP 200
— even for a user-facing error like "unknown command" or "task not found",
so Slack renders the message in the channel/DM rather than showing a generic
webhook failure. Only signature-verification failures and the
feature-disabled case are non-200 (handled at the HTTP layer in ``app.py``,
not in this module).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from typing import Any, Mapping
from urllib.parse import parse_qs

from src.storage import Storage

from .intake import _create_slack_task_draft

# Env var holding the Slack app's signing secret. Never read from a policy
# file — mirrors the secrets-in-env rule for the Slack notifier's webhook
# URL / bot token in ``src/notifications.py``.
SLACK_SIGNING_SECRET_ENV = "SARATHI_SLACK_SIGNING_SECRET"

# Slack recommends rejecting requests whose timestamp has drifted more than
# five minutes from "now" as a replay-attack defense.
DEFAULT_MAX_SKEW_SECONDS = 300

_SIGNATURE_VERSION = "v0"


def verify_slack_signature(
    signing_secret: str,
    timestamp: str | None,
    raw_body: bytes,
    signature: str | None,
    *,
    now: float | None = None,
    max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS,
) -> bool:
    """Verify a Slack request's ``X-Slack-Signature`` header.

    Pure function (no environment reads) so it is trivially unit-testable:
    ``now`` defaults to ``time.time()`` but tests should pass an explicit
    value. Returns ``False`` (never raises) for any malformed input —
    missing/non-numeric timestamp, missing signature, stale timestamp, or a
    signature mismatch.
    """
    if not signing_secret or not signature or not timestamp:
        return False
    try:
        timestamp_value = float(timestamp)
    except (TypeError, ValueError):
        return False
    current = time.time() if now is None else now
    if abs(current - timestamp_value) > max_skew_seconds:
        return False
    base_string = f"{_SIGNATURE_VERSION}:{timestamp}:".encode("utf-8") + raw_body
    digest = hmac.new(
        signing_secret.encode("utf-8"), base_string, hashlib.sha256
    ).hexdigest()
    expected = f"{_SIGNATURE_VERSION}={digest}"
    return hmac.compare_digest(expected, signature)


def parse_slack_form_body(raw_body: bytes) -> dict[str, str]:
    """Parse a Slack ``application/x-www-form-urlencoded`` request body.

    Slack sends single-valued fields; only the first value of each key is
    kept. Malformed/empty bytes decode to an empty mapping rather than
    raising, since callers only need the recognized fields (``command``,
    ``text``, ``user_id``, ``user_name``, ``team_id``, ``channel_id``,
    ``response_url``) and treat anything missing as absent.
    """
    try:
        decoded = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        return {}
    parsed = parse_qs(decoded, keep_blank_values=True)
    return {key: values[0] for key, values in parsed.items() if values}


_HELP_TEXT = (
    "*Sarathi commands*\n"
    "• `/sarathi run <description>` — draft a new task from the description.\n"
    "• `/sarathi run in <workspace-name-or-id>: <description>` — draft a task "
    "in a specific workspace (required when more than one workspace exists).\n"
    "• `/sarathi status <task-id>` — show a task's current status.\n"
    "• `/sarathi help` — show this message."
)

# Matches the `in <workspace>: <rest>` prefix inside `/sarathi run`'s text,
# e.g. "in acme-web: Fix the checkout timeout" -> ("acme-web", "Fix the
# checkout timeout"). Requires the colon so a description that merely
# starts with "in " (e.g. "in production users see...") is not misread as a
# workspace hint unless it also happens to contain an early colon.
_RUN_WORKSPACE_PREFIX_RE = re.compile(
    r"^in\s+(?P<workspace>[^:]+):\s*(?P<rest>.*)$", re.IGNORECASE | re.DOTALL
)


def _ephemeral(text: str) -> dict[str, Any]:
    return {"response_type": "ephemeral", "text": text}


def _in_channel(text: str) -> dict[str, Any]:
    return {"response_type": "in_channel", "text": text}


def _parse_run_text(text: str) -> tuple[str | None, str]:
    """Split ``/sarathi run``'s text into an optional workspace hint + prompt."""
    match = _RUN_WORKSPACE_PREFIX_RE.match(text.strip())
    if match:
        return match.group("workspace").strip(), match.group("rest").strip()
    return None, text.strip()


def _resolve_workspace_for_run(
    storage: Storage, workspace_hint: str | None
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve the target workspace for a ``/sarathi run`` command.

    Returns ``(workspace, None)`` on success or ``(None, error_text)`` with
    a Slack-friendly explanation otherwise. Resolution rules:

    - a workspace hint (from the ``run in <name-or-id>: ...`` prefix) is
      matched by exact id or case-insensitive name; no match is an error.
    - no hint + exactly one workspace: use it.
    - no hint + no workspaces: friendly "create one first" error.
    - no hint + multiple workspaces: ambiguous — the caller must use the
      ``run in <workspace-name-or-id>: <text>`` prefix syntax.
    """
    workspaces = storage.list_workspaces()
    if workspace_hint:
        needle = workspace_hint.strip().lower()
        for workspace in workspaces:
            if workspace["id"].lower() == needle:
                return workspace, None
            name = str(workspace.get("name") or "").strip().lower()
            if name == needle:
                return workspace, None
        return None, f"No workspace found matching `{workspace_hint}`."
    if not workspaces:
        return None, (
            "No Sarathi workspaces exist yet. Create one first, then retry `/sarathi run`."
        )
    if len(workspaces) == 1:
        return workspaces[0], None
    names = ", ".join(f"`{workspace['name']}`" for workspace in workspaces)
    return None, (
        f"Multiple workspaces exist ({names}). Specify one: "
        "`/sarathi run in <workspace-name-or-id>: <description>`."
    )


def _handle_run(
    storage: Storage,
    text: str,
    *,
    user: str | None,
    channel: str | None,
    team: str | None,
) -> dict[str, Any]:
    workspace_hint, prompt = _parse_run_text(text)
    if not prompt:
        return _ephemeral(f"Usage: `/sarathi run <description>`.\n\n{_HELP_TEXT}")
    workspace, error = _resolve_workspace_for_run(storage, workspace_hint)
    if workspace is None:
        return _ephemeral(error or "Could not resolve a workspace.")
    result = _create_slack_task_draft(
        storage,
        workspace["id"],
        prompt,
        user=user,
        channel=channel,
        team=team,
    )
    task = result["task"]
    return _in_channel(
        f"Created task draft *{task['title']}* (`{task['id']}`) in workspace "
        f"`{workspace['name']}`. Awaiting PRD/AC approval."
    )


def _handle_status(storage: Storage, text: str) -> dict[str, Any]:
    task_id = text.strip()
    if not task_id:
        return _ephemeral("Usage: `/sarathi status <task-id>`")
    task = storage.get_task(task_id)
    if task is None:
        return _ephemeral(f"No task found with id `{task_id}`.")
    lines = [
        f"*Task {task['id']}*: {task['title']}",
        f"Status: `{task['status']}`",
        f"Workspace: `{task['workspace_id']}`",
    ]
    events = storage.list_events(task_id=task_id)
    if events:
        latest = events[-1]
        lines.append(f"Last event: `{latest['event_type']}`")
    return _ephemeral("\n".join(lines))


def handle_slack_command(storage: Storage, form: Mapping[str, str]) -> dict[str, Any]:
    """Route a parsed Slack slash-command form body to a command handler.

    ``form`` is the dict produced by ``parse_slack_form_body``. Always
    returns Slack's expected ``{response_type, text}`` shape; never raises
    for a user-facing routing/validation problem (those become an
    ``ephemeral`` text response instead), so the caller can return HTTP 200
    unconditionally once signature verification has passed.
    """
    text = (form.get("text") or "").strip()
    user = form.get("user_name") or form.get("user_id") or None
    channel = form.get("channel_id")
    team = form.get("team_id")

    if not text:
        return _ephemeral(_HELP_TEXT)

    subcommand, _, rest = text.partition(" ")
    subcommand = subcommand.strip().lower()
    rest = rest.strip()

    if subcommand == "run":
        return _handle_run(storage, rest, user=user, channel=channel, team=team)
    if subcommand == "status":
        return _handle_status(storage, rest)
    if subcommand == "help":
        return _ephemeral(_HELP_TEXT)
    return _ephemeral(f"Unknown command `{subcommand}`.\n\n{_HELP_TEXT}")
