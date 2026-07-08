"""Task intake helpers: drafting metadata, context extraction, and repository bootstrap."""

from __future__ import annotations

import hmac
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, quote, urlparse

from src.init import InitWorkflow
from src.storage import Storage

from .errors import ServiceError
from .preferences import (
    _default_repository_action_preference,
    _optional_dict,
    _optional_text,
)

_SLACK_SIGNING_SECRET_ENV = "SARATHI_SLACK_SIGNING_SECRET"

# GitHub REST API base and the optional bearer-token env var. Mirrors the
# injectable-opener, bare-urllib pattern used by ``src/notifications.py`` for
# Slack: no third-party HTTP client, best-effort auth from the environment.
GITHUB_API_BASE = "https://api.github.com"
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"

_GITHUB_REMOTE_RE = re.compile(r"github\.com[:/]+(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")


def _derive_task_title(prompt: str) -> str:
    words = prompt.strip().split()
    if not words:
        return "Untitled orchestrated task"
    title = " ".join(words[:8]).strip(" .")
    return title[:80] or "Untitled orchestrated task"


def _task_draft_metadata(
    prompt: str,
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source_prompt": prompt,
        "complexity": "high",
        "phase": "prd_ac_draft",
        "prd": {
            "problem": prompt,
            "goal": "Turn the user request into an approved, workspace-scoped Sarathi task.",
            "scope": [
                "Capture source conversation.",
                "Draft acceptance criteria.",
                "Block graph generation until PRD/AC approval.",
            ],
        },
        "acceptance_criteria": [
            "A durable task draft exists in the selected workspace.",
            "The source prompt is preserved as a task-scoped user message.",
            "Sarathi creates a PRD/AC approval gate before task graph generation.",
        ],
        "repository_action_preference": _default_repository_action_preference(),
    }
    if project_id:
        metadata["project_id"] = project_id
    return metadata


def _task_context_project_id(context: Any) -> str | None:
    if not isinstance(context, Mapping):
        return None
    for key in ("projectId", "project_id"):
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _task_context_workspace_id(context: Any) -> str | None:
    if not isinstance(context, Mapping):
        return None
    for key in ("workspaceId", "workspace_id"):
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _parse_github_issue_url(issue_url: str) -> dict[str, Any]:
    parsed = urlparse(issue_url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 4 or parts[2] != "issues":
        raise ServiceError(
            "invalid_request",
            "GitHub issue URLs must look like https://github.com/<owner>/<repo>/issues/<number>.",
            400,
        )
    owner, repo, _, number_text = parts[:4]
    try:
        issue_number = int(number_text)
    except ValueError as exc:
        raise ServiceError("invalid_request", "GitHub issue number must be an integer.", 400) from exc
    return {
        "url": issue_url,
        "host": parsed.netloc,
        "owner": owner,
        "name": repo,
        "full_name": f"{owner}/{repo}",
        "number": issue_number,
        "repository_url": f"{parsed.scheme}://{parsed.netloc}/{owner}/{repo}",
    }


def _github_repository_metadata(repository: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        "workspace_repository_id": repository["id"],
        "workspace_repository_name": repository["name"],
        "workspace_repository_path": repository["path"],
        "workspace_repository_remote_url": repository["remote_url"],
    }
    return metadata


def _resolve_issue_repository(
    storage: Storage,
    workspace_id: str,
    body: Mapping[str, Any],
) -> dict[str, Any] | None:
    repository_id = _optional_text(body, "repository_id")
    if repository_id is not None:
        repository = storage.get_workspace_repository(repository_id)
        if repository is None or repository["workspace_id"] != workspace_id:
            raise ServiceError("not_found", "Repository not found.", 404)
        return repository

    repositories = storage.list_workspace_repositories(workspace_id)
    if len(repositories) == 1 and body.get("issue_number") is not None:
        return repositories[0]
    return None


def _build_github_issue_reference(
    storage: Storage,
    workspace_id: str,
    body: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    issue_url = _optional_text(body, "issue_url")
    if issue_url:
        issue = _parse_github_issue_url(issue_url)
        repository = _resolve_issue_repository(storage, workspace_id, body)
        issue["repository"] = {
            "host": issue["host"],
            "owner": issue["owner"],
            "name": issue["name"],
            "full_name": issue["full_name"],
            "repository_url": issue["repository_url"],
        }
        if repository is not None:
            issue["repository"].update(_github_repository_metadata(repository))
            if repository.get("remote_url"):
                issue["repository"]["remote_url"] = repository["remote_url"]
        return issue, repository

    issue_number_value = body.get("issue_number")
    if issue_number_value is None:
        raise ServiceError("invalid_request", "Field 'issue_url' or 'issue_number' is required.", 400)
    if not isinstance(issue_number_value, int):
        raise ServiceError("invalid_request", "Field 'issue_number' must be an integer.", 400)
    repository = _resolve_issue_repository(storage, workspace_id, body)
    if repository is None:
        raise ServiceError(
            "invalid_request",
            "Provide repository_id when importing a GitHub issue by number.",
            400,
        )
    issue = {
        "url": None,
        "host": None,
        "owner": None,
        "name": None,
        "full_name": None,
        "number": issue_number_value,
        "repository_url": None,
    }
    issue["repository"] = _github_repository_metadata(repository)
    if repository.get("remote_url"):
        issue["repository"]["remote_url"] = repository["remote_url"]
    return issue, repository


def _create_github_issue_task_draft(
    storage: Storage,
    workspace_id: str,
    issue: dict[str, Any],
    repository: dict[str, Any] | None,
    *,
    title: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Draft a PRD/AC-gated task from a GitHub issue reference.

    Shared by the single-issue import route (``.../github/issues/import``)
    and the label-sync route (``.../github/issues/sync``) so both paths
    emit the exact same shape of task, messages, approval gate, and
    lifecycle events.
    """
    task_title = title or f"GitHub issue #{issue['number']}"
    task_metadata = _task_draft_metadata(
        issue["url"] or f"GitHub issue #{issue['number']}",
        project_id=project_id,
    )
    task_metadata["source"] = "github_issue"
    task_metadata["github_issue"] = issue
    repository_metadata: dict[str, Any] = {}
    if issue.get("full_name"):
        repository_metadata["github"] = {
            "host": issue["host"],
            "owner": issue["owner"],
            "name": issue["name"],
            "full_name": issue["full_name"],
            "repository_url": issue["repository_url"],
        }
    if repository is not None:
        repository_metadata.update(_github_repository_metadata(repository))
        if repository.get("remote_url"):
            repository_metadata["remote_url"] = repository["remote_url"]
    if repository_metadata:
        task_metadata["repository"] = repository_metadata

    task = storage.create_task(
        workspace_id=workspace_id,
        title=task_title,
        status="prd_pending",
        description=issue["url"] or f"Imported GitHub issue #{issue['number']}.",
        metadata=task_metadata,
        project_id=task_metadata.get("project_id"),
    )
    user_message = storage.create_message(
        workspace_id=workspace_id,
        task_id=task["id"],
        role="user",
        content=issue["url"] or f"GitHub issue #{issue['number']}",
        metadata={"target": "Sarathi", "source": "github_issue_import"},
    )
    sarathi_message = storage.create_message(
        workspace_id=workspace_id,
        task_id=task["id"],
        role="sarathi",
        content=(
            "I drafted the PRD/AC shell from the GitHub issue reference and opened "
            "the PRD/AC approval gate before graph generation."
        ),
        metadata={"draft_task_id": task["id"], "gate": "PRD/AC", "source": "github_issue_import"},
    )
    gate = storage.create_approval_gate(
        workspace_id=workspace_id,
        task_id=task["id"],
        name="PRD/AC",
        status="pending",
        metadata={
            "requires_human": True,
            "source_issue": issue["url"] or f"GitHub issue #{issue['number']}",
            "acceptance_criteria": task_metadata["acceptance_criteria"],
        },
    )
    storage.create_lifecycle_event(
        workspace_id=workspace_id,
        task_id=task["id"],
        event_type="task.draft_created",
        payload={"object_id": task["id"], "gate": gate["id"]},
    )
    storage.create_lifecycle_event(
        workspace_id=workspace_id,
        task_id=task["id"],
        event_type="approval.requested",
        payload={"object_id": gate["id"], "name": gate["name"]},
    )
    return {
        "task": task,
        "approval_gate": gate,
        "messages": [user_message, sarathi_message],
    }


def _parse_github_remote(remote_url: str | None) -> tuple[str, str] | None:
    """Best-effort ``owner/repo`` extraction from a git remote URL.

    Handles both ``https://github.com/owner/repo(.git)`` and
    ``git@github.com:owner/repo(.git)`` forms.
    """
    if not remote_url:
        return None
    match = _GITHUB_REMOTE_RE.search(remote_url.strip())
    if not match:
        return None
    return match.group("owner"), match.group("repo")


def _repository_full_name_from_row(repository: Mapping[str, Any] | None) -> str | None:
    if repository is None:
        return None
    metadata = repository.get("metadata")
    if isinstance(metadata, Mapping):
        github_meta = metadata.get("github")
        if isinstance(github_meta, Mapping) and github_meta.get("full_name"):
            return str(github_meta["full_name"])
    parsed = _parse_github_remote(repository.get("remote_url"))
    if parsed:
        return f"{parsed[0]}/{parsed[1]}"
    return None


def _resolve_sync_target(
    storage: Storage,
    workspace_id: str,
    body: Mapping[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Resolve the ``owner/repo`` full name and (if known) the attached
    workspace repository row for a label-sync request.

    Priority: explicit ``repository_id`` > explicit ``repository`` (an
    ``owner/repo`` string) > the single repository attached to the
    workspace. An ambiguous request (multiple repositories, none named)
    raises rather than guessing.
    """
    explicit_full_name = _optional_text(body, "repository")
    repository_id = _optional_text(body, "repository_id")
    repository: dict[str, Any] | None = None

    if repository_id is not None:
        repository = storage.get_workspace_repository(repository_id)
        if repository is None or repository["workspace_id"] != workspace_id:
            raise ServiceError("not_found", "Repository not found.", 404)
    elif explicit_full_name is None:
        repositories = storage.list_workspace_repositories(workspace_id)
        if len(repositories) == 1:
            repository = repositories[0]
        elif len(repositories) > 1:
            raise ServiceError(
                "invalid_request",
                "Multiple repositories are attached to this workspace; pass "
                "'repository_id' or 'repository' (\"owner/repo\") to disambiguate.",
                400,
            )

    full_name = explicit_full_name.strip().strip("/") if explicit_full_name else _repository_full_name_from_row(repository)
    if not full_name:
        raise ServiceError(
            "invalid_request",
            "Could not determine a GitHub 'owner/repo' to sync; pass 'repository' "
            "(\"owner/repo\") or attach a GitHub repository to the workspace.",
            400,
        )

    if repository is None:
        for candidate in storage.list_workspace_repositories(workspace_id):
            if _repository_full_name_from_row(candidate) == full_name:
                repository = candidate
                break

    return full_name, repository


def _fetch_open_issues_by_label(
    full_name: str,
    label: str,
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """List open issues carrying ``label`` from ``owner/repo`` via bare urllib.

    No third-party HTTP client (matches the rest of the repo's dispatch
    style: no SDK imports). ``GITHUB_TOKEN`` is read from ``env`` (defaults
    to ``os.environ``) and sent as a bearer token when present; public
    repositories work without it. ``opener`` is injectable for tests
    (default ``urllib.request.urlopen``), mirroring
    ``src/notifications.py``'s ``SlackNotifier``.

    GitHub's issues-list endpoint also returns pull requests; those are
    filtered out here (they carry a ``pull_request`` key).
    """
    env = os.environ if env is None else env
    opener = opener or urllib.request.urlopen
    url = (
        f"{GITHUB_API_BASE}/repos/{full_name}/issues"
        f"?labels={quote(label)}&state=open&per_page=100"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "sarathi-service",
    }
    token = env.get(GITHUB_TOKEN_ENV)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with opener(request, timeout=10) as response:
            status = getattr(response, "status", 200)
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise ServiceError(
            "github_error", f"GitHub API returned HTTP {exc.code} for {full_name}.", 502
        ) from exc
    except urllib.error.URLError as exc:
        raise ServiceError(
            "github_error", f"Failed to reach the GitHub API: {exc.reason}.", 502
        ) from exc
    if status is not None and int(status) >= 300:
        raise ServiceError("github_error", f"GitHub API returned HTTP {status}.", 502)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ServiceError("github_error", "GitHub API returned invalid JSON.", 502) from exc
    if not isinstance(payload, list):
        raise ServiceError("github_error", "Unexpected GitHub API response shape.", 502)
    return [item for item in payload if isinstance(item, dict) and "pull_request" not in item]


def _find_existing_github_issue_draft(
    storage: Storage,
    workspace_id: str,
    full_name: str,
    issue_number: int,
) -> dict[str, Any] | None:
    """Find a previously-drafted task for this issue, keyed by repo + number.

    This is what makes ``sync`` idempotent: re-running it never creates a
    second draft for an issue already imported (whether by a prior sync or
    by the single-issue import route).
    """
    for task in storage.list_tasks_for_workspace(workspace_id):
        metadata = task.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        github_issue = metadata.get("github_issue")
        if not isinstance(github_issue, Mapping):
            continue
        if github_issue.get("number") != issue_number:
            continue
        if github_issue.get("full_name") == full_name:
            return task
    return None


def _sync_github_issues_by_label(
    storage: Storage,
    workspace_id: str,
    body: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """List open issues carrying ``label`` and draft a task for each new one.

    Idempotent: issues already drafted (matched by repository full name +
    issue number, see ``_find_existing_github_issue_draft``) are reported in
    ``skipped`` rather than re-drafted.
    """
    label = _optional_text(body, "label") or "sarathi"
    context = _optional_dict(body, "context") or {}
    project_id = _task_context_project_id(context)

    full_name, repository = _resolve_sync_target(storage, workspace_id, body)
    raw_issues = _fetch_open_issues_by_label(full_name, label, env=env, opener=opener)

    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for raw_issue in raw_issues:
        issue_number = raw_issue.get("number")
        if not isinstance(issue_number, int):
            continue
        existing = _find_existing_github_issue_draft(storage, workspace_id, full_name, issue_number)
        if existing is not None:
            skipped.append({"number": issue_number, "task_id": existing["id"]})
            continue

        issue_url = raw_issue.get("html_url") or f"https://github.com/{full_name}/issues/{issue_number}"
        issue = _parse_github_issue_url(issue_url)
        issue["repository"] = {
            "host": issue["host"],
            "owner": issue["owner"],
            "name": issue["name"],
            "full_name": issue["full_name"],
            "repository_url": issue["repository_url"],
        }
        if repository is not None:
            issue["repository"].update(_github_repository_metadata(repository))
            if repository.get("remote_url"):
                issue["repository"]["remote_url"] = repository["remote_url"]

        raw_title = raw_issue.get("title")
        result = _create_github_issue_task_draft(
            storage,
            workspace_id,
            issue,
            repository,
            title=str(raw_title) if raw_title else None,
            project_id=project_id,
        )
        created.append(result)

    return {
        "label": label,
        "repository": full_name,
        "created": created,
        "skipped": skipped,
    }


def _find_policy_pack_dir(storage: Storage, workspace_id: str) -> Path | None:
    repos = storage.list_workspace_repositories(workspace_id)
    for repo in repos:
        candidate = Path(repo["path"]).expanduser() / "policy-pack"
        if candidate.is_dir():
            return candidate
    return None


def _emit_brainstorm_event(
    storage: Storage,
    event_type: str,
    payload: dict[str, Any],
    *,
    workspace_id: str | None = None,
) -> None:
    try:
        storage.create_lifecycle_event(
            workspace_id=workspace_id,
            task_id=None,
            event_type=event_type,
            payload=payload,
        )
    except Exception:
        pass


def _write_brainstorm_spec(session: dict[str, Any]) -> str | None:
    try:
        sarathi_dir = Path(".sarathi") / "brainstorm" / session["id"]
        sarathi_dir.mkdir(parents=True, exist_ok=True)
        spec_path = sarathi_dir / "spec.md"
        content = session["spec_content"] or f"# {session['title']}\n"
        spec_path.write_text(content, encoding="utf-8")
        return str(spec_path)
    except Exception:
        return None


def _get_policy_pack(storage: Storage, workspace_id: str) -> dict[str, Any]:
    policy_dir = _find_policy_pack_dir(storage, workspace_id)
    if policy_dir is None:
        return {"files": [], "error": "No policy pack found for this workspace"}
    files = []
    for md_file in sorted(policy_dir.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError:
            content = ""
        files.append({"name": md_file.name, "content": content, "size": len(content)})
    return {"files": files}


def _put_policy_pack_file(
    storage: Storage,
    workspace_id: str,
    filename: str,
    body: Mapping[str, Any],
) -> dict[str, Any]:
    if not filename.endswith(".md"):
        raise ServiceError("invalid_request", "Filename must end in .md.", 400)
    if ".." in filename or "/" in filename or "\\" in filename:
        raise ServiceError("invalid_request", "Filename must not contain path traversal characters.", 400)
    policy_dir = _find_policy_pack_dir(storage, workspace_id)
    if policy_dir is None:
        raise ServiceError("not_found", "No policy pack found for this workspace.", 404)
    content = body.get("content")
    if not isinstance(content, str):
        raise ServiceError("invalid_request", "Field 'content' must be a string.", 400)
    target = policy_dir / filename
    try:
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ServiceError("internal_error", f"Failed to write policy file: {exc}", 500)
    return {"ok": True, "filename": filename}


def _preview_repository_intake(path: str) -> dict[str, Any]:
    repo_path = Path(path).expanduser()
    exists = repo_path.exists()
    is_directory = repo_path.is_dir()
    is_git_repo = False
    branch = None
    remote_url = None
    changes: list[str] = []

    if is_directory:
        is_git_repo = _git_output(repo_path, "rev-parse", "--is-inside-work-tree") == "true"
        if is_git_repo:
            branch = _git_output(repo_path, "branch", "--show-current") or None
            remote_url = _git_output(repo_path, "config", "--get", "remote.origin.url") or None
            changes = _git_lines(repo_path, "status", "--short")
    inspection = _inspect_repository(repo_path) if is_directory else {}

    sarathi_initialized = (
        (repo_path / "policy-pack").exists()
        or (repo_path / ".sarathi").exists()
        or (repo_path / "learnings.md").exists()
    )

    warnings: list[str] = []
    if not exists:
        warnings.append("Repository path does not exist yet.")
    elif not is_directory:
        warnings.append("Repository path is not a directory.")
    elif changes:
        warnings.append("Repository has uncommitted or untracked changes.")
    if exists and is_directory and not sarathi_initialized:
        warnings.append("Sarathi policy pack is not initialized yet.")

    recommended_mode = "new_repo"
    if exists and is_directory:
        recommended_mode = "existing_repo" if is_git_repo else "directory"
    if sarathi_initialized:
        recommended_mode = "sarathi_enabled_repo"
    bootstrap = _repository_bootstrap_status(repo_path) if is_directory else _repository_bootstrap_status(None)

    return {
        "path": str(repo_path),
        "name": repo_path.name,
        "exists": exists,
        "is_directory": is_directory,
        "is_git_repo": is_git_repo,
        "branch": branch,
        "remote_url": remote_url,
        "dirty": bool(changes),
        "changes": changes,
        "inspection": inspection,
        "sarathi_initialized": sarathi_initialized,
        "recommended_mode": recommended_mode,
        "requires_interview": not exists or not is_git_repo,
        "warnings": warnings,
        "bootstrap": bootstrap,
        "would_create": bootstrap["missing_files"],
        "would_preserve": bootstrap["present_files"],
    }


def _initialize_workspace_repository(
    storage: Storage,
    repository: dict[str, Any],
    body: Mapping[str, Any],
) -> dict[str, Any]:
    if body.get("approved") is not True:
        raise ServiceError(
            "approval_required",
            "Repository initialization must be explicitly approved before files are created.",
            409,
        )
    preview = _preview_repository_intake(repository["path"])
    interview = _optional_dict(body, "interview") or {}
    if preview["requires_interview"] and not interview:
        raise ServiceError(
            "interview_required",
            "New or non-Git repositories require interview answers before Sarathi initialization.",
            409,
        )

    repo_path = Path(repository["path"]).expanduser()
    if preview["recommended_mode"] == "new_repo":
        repo_path.mkdir(parents=True, exist_ok=True)
    elif not repo_path.exists() or not repo_path.is_dir():
        raise ServiceError("invalid_request", "Repository path must be an existing directory.", 400)

    mode = preview["recommended_mode"]
    bootstrap_result = _write_sarathi_repository_docs(repo_path, repository, preview, interview)
    initialization = {
        "status": "completed",
        "mode": mode,
        "created_files": bootstrap_result["created_files"],
        "preserved_files": bootstrap_result["preserved_files"],
        "bootstrap": preview["bootstrap"],
        "inspection": preview.get("inspection", {}),
        "interview": interview,
    }
    metadata = dict(repository["metadata"])
    metadata["sarathi_initialization"] = initialization
    updated_repository = storage.update_workspace_repository(repository["id"], metadata=metadata)
    storage.create_lifecycle_event(
        workspace_id=repository["workspace_id"],
        event_type="workspace.repository.initialized",
        payload={
            "object_id": repository["id"],
            "path": repository["path"],
            "mode": mode,
            "created_files": bootstrap_result["created_files"],
            "preserved_files": bootstrap_result["preserved_files"],
        },
    )
    return {"repository": updated_repository, "initialization": initialization}


def _write_sarathi_repository_docs(
    repo_path: Path,
    repository: dict[str, Any],
    preview: dict[str, Any],
    interview: Mapping[str, Any],
) -> dict[str, list[str]]:
    project_name = str(interview.get("project_name") or repository.get("name") or preview["name"])
    purpose = str(interview.get("purpose") or "Document this repository for Sarathi orchestration.")
    inspection = preview.get("inspection", {}) if isinstance(preview.get("inspection"), Mapping) else {}
    languages = inspection.get("languages") if isinstance(inspection.get("languages"), list) else []
    frameworks = inspection.get("frameworks") if isinstance(inspection.get("frameworks"), list) else []
    build_tools = inspection.get("build_tools") if isinstance(inspection.get("build_tools"), list) else []
    test_patterns = inspection.get("test_patterns") if isinstance(inspection.get("test_patterns"), list) else []
    primary_language = str(interview.get("primary_language") or (languages[0] if languages else "Unknown"))
    file_map = {
        "SARATHI.md": (
            f"# {project_name} Sarathi Context\n\n"
            f"Purpose: {purpose}\n\n"
            f"Primary language: {primary_language}\n\n"
            f"Recommended mode: {preview['recommended_mode']}\n\n"
            "Sarathi uses this file as the repository-level orientation point for agents.\n"
        ),
        "wiki/README.md": (
            f"# {project_name} Wiki\n\n"
            "## Overview\n"
            f"{purpose}\n\n"
            "## Repository Profile\n"
            f"- Languages: {', '.join(languages) or 'Unknown'}\n"
            f"- Frameworks: {', '.join(frameworks) or 'Unknown'}\n"
            f"- Build tools: {', '.join(build_tools) or 'Unknown'}\n"
            f"- Test patterns: {', '.join(test_patterns) or 'Unknown'}\n\n"
            "## Architecture Notes\n"
            "- Add module boundaries, runtime assumptions, and external dependencies here.\n"
        ),
        "wiki/architecture.md": (
            f"# {project_name} Architecture Notes\n\n"
            "- Capture service boundaries, major modules, and runtime dependencies.\n"
            "- Add diagrams or links to diagrams generated from Sarathi task evidence.\n"
        ),
        "wiki/development.md": (
            f"# {project_name} Development Workflow\n\n"
            "- Document local setup, build, test, and release flow.\n"
            "- Record task routing expectations for Codex, Claude, Copilot, or local providers.\n"
        ),
        "coding-standards.md": (
            "# Coding Standards\n\n"
            "- Keep changes scoped to the active Sarathi task.\n"
            "- Add or update tests with behavior changes.\n"
            "- Preserve existing user changes and avoid destructive git commands.\n"
            f"- Primary language focus: {primary_language}.\n"
        ),
        "guidelines.md": (
            "# Repository Guidelines\n\n"
            "- Preview repository mutations before applying them.\n"
            "- Link evidence, review, and handoff records to every completed task.\n"
            "- Ask for explicit approval before commit, PR, or generated file writes.\n"
            "- Treat workspace context, wiki, policy pack, and learnings as first-class artifacts.\n"
        ),
        "learnings.md": (
            "# Repository Learnings\n\n"
            "Accepted learnings from Sarathi runs should be appended here after review approval.\n"
        ),
    }
    file_map.update(_generated_policy_pack_files(repo_path, preview, interview))
    created: list[str] = []
    preserved: list[str] = []
    for relative_path, content in file_map.items():
        target = repo_path / relative_path
        if target.exists():
            preserved.append(relative_path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        created.append(relative_path)
    return {"created_files": created, "preserved_files": preserved}


def _generated_policy_pack_files(
    repo_path: Path,
    preview: Mapping[str, Any],
    interview: Mapping[str, Any],
) -> dict[str, str]:
    inspection = preview.get("inspection") if isinstance(preview.get("inspection"), Mapping) else {}
    effective_inspection = dict(inspection) if inspection else {}
    if not effective_inspection:
        effective_inspection = _inspect_repository(repo_path)
    with tempfile.TemporaryDirectory(prefix="sarathi-bootstrap-") as tempdir:
        workflow = InitWorkflow(target_path=tempdir)
        generated_path = workflow.generate(effective_inspection, dict(interview))
        files: dict[str, str] = {}
        for source in sorted(generated_path.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(generated_path).as_posix()
            files[f"policy-pack/{relative}"] = source.read_text(encoding="utf-8")
        return files


def _inspect_repository(repo_path: Path) -> dict[str, Any]:
    if not repo_path.exists() or not repo_path.is_dir():
        return {}
    inspection = InitWorkflow(target_path=str(repo_path)).inspect()
    return inspection if isinstance(inspection, dict) and "error" not in inspection else {}


def _repository_bootstrap_status(repo_path: Path | None) -> dict[str, Any]:
    required_files = _required_repository_bootstrap_files()
    if repo_path is None:
        return {
            "required_files": required_files,
            "present_files": [],
            "missing_files": list(required_files),
            "status": "not_initialized",
        }
    present_files = [path for path in required_files if (repo_path / path).exists()]
    missing_files = [path for path in required_files if path not in present_files]
    if not present_files:
        status = "not_initialized"
    elif not missing_files:
        status = "complete"
    else:
        status = "partial"
    return {
        "required_files": required_files,
        "present_files": present_files,
        "missing_files": missing_files,
        "status": status,
    }


def _required_repository_bootstrap_files() -> list[str]:
    return [
        "SARATHI.md",
        "wiki/README.md",
        "wiki/architecture.md",
        "wiki/development.md",
        "coding-standards.md",
        "guidelines.md",
        "learnings.md",
        "policy-pack/commands.md",
        "policy-pack/complexity.md",
        "policy-pack/conventions.md",
        "policy-pack/escalation.md",
        "policy-pack/model-routing.md",
        "policy-pack/review.md",
        "policy-pack/skills.md",
        "policy-pack/task-tracking.md",
    ]


def _parse_slack_body(body: str | Mapping[str, Any]) -> dict[str, Any]:
    """Parse a Slack slash-command body — accepts a form-encoded string or dict.

    Slack sends ``application/x-www-form-urlencoded``; the HTTP layer passes
    the raw string through to ``app.handle`` as ``raw_body`` and the parsed
    dict as ``body``. Callers that invoke ``app.handle`` directly (e.g. tests)
    can pass a pre-built dict and skip the raw-body path.
    """
    if isinstance(body, str):
        parsed = parse_qs(body)
        return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
    if isinstance(body, Mapping):
        return dict(body.items())
    return {}


def _verify_slack_request(
    headers: Mapping[str, str] | None,
    raw_body: str | None,
) -> None:
    """Verify a Slack slash-command request using HMAC SHA-256.

    Reads ``SARATHI_SLACK_SIGNING_SECRET`` from the environment.  If unset
    the check is skipped entirely (safe for local/test use).  When set the
    function requires ``x-slack-request-timestamp`` (within 300 s of now)
    and ``x-slack-signature`` (``v0=...``) headers and rejects invalid or
    missing signatures with a ``ServiceError``.
    """
    secret = os.environ.get(_SLACK_SIGNING_SECRET_ENV)
    if not secret:
        return

    if not headers or not raw_body:
        raise ServiceError("invalid_request", "Missing headers or body for Slack signing verification.", 400)

    timestamp: str | None = None
    signature: str | None = None
    for key, value in headers.items():
        lk = key.lower()
        if lk == "x-slack-request-timestamp":
            timestamp = value
        elif lk == "x-slack-signature":
            signature = value

    if not timestamp:
        raise ServiceError("invalid_request", "Missing x-slack-request-timestamp header.", 400)
    if not signature:
        raise ServiceError("invalid_request", "Missing x-slack-signature header.", 401)

    try:
        request_time = int(timestamp)
    except ValueError:
        raise ServiceError("invalid_request", "Invalid x-slack-request-timestamp.", 400)

    if abs(time.time() - request_time) > 300:
        raise ServiceError("stale_request", "Slack request timestamp is too skewed (>5 minutes from now).", 401)

    sig_basestring = f"v0:{timestamp}:{raw_body}"
    expected = "v0=" + hmac.new(
        secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        "sha256",
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise ServiceError("invalid_signature", "Slack request signature does not match.", 401)


def _create_slack_task_draft(
    storage: Storage,
    workspace_id: str,
    slack_data: dict[str, Any],
) -> dict[str, Any]:
    """Create a PRD/AC-gated task draft from a Slack slash-command payload.

    Mirrors ``_create_github_issue_task_draft``: creates a ``prd_pending``
    task with user + sarathi messages, a PRD/AC approval gate, and lifecycle
    events.  Slack-specific fields are preserved under ``task.metadata.slack_command``.
    """
    prompt = slack_data.get("text", "").strip()
    if not prompt:
        raise ServiceError("invalid_request", "Slash command 'text' must be non-empty.", 400)

    title = _derive_task_title(prompt)
    metadata = _task_draft_metadata(prompt)
    metadata["source"] = "slack_command"

    slack_meta: dict[str, Any] = {}
    for key in ("team_id", "team_domain", "channel_id", "channel_name",
                "user_id", "user_name", "command", "response_url"):
        if key in slack_data:
            slack_meta[key] = slack_data[key]
    if slack_meta:
        metadata["slack_command"] = slack_meta

    task = storage.create_task(
        workspace_id=workspace_id,
        title=title,
        status="prd_pending",
        description=metadata["prd"]["problem"],
        metadata=metadata,
        project_id=metadata.get("project_id"),
    )

    user_message = storage.create_message(
        workspace_id=workspace_id,
        task_id=task["id"],
        role="user",
        content=prompt,
        metadata={"target": "Sarathi", "source": "slack_command"},
    )

    sarathi_message = storage.create_message(
        workspace_id=workspace_id,
        task_id=task["id"],
        role="sarathi",
        content=(
            "I drafted the PRD/AC shell from the Slack command and opened "
            "the PRD/AC approval gate before graph generation."
        ),
        metadata={"draft_task_id": task["id"], "gate": "PRD/AC", "source": "slack_command"},
    )

    gate = storage.create_approval_gate(
        workspace_id=workspace_id,
        task_id=task["id"],
        name="PRD/AC",
        status="pending",
        metadata={
            "requires_human": True,
            "source_prompt": prompt,
            "acceptance_criteria": metadata["acceptance_criteria"],
        },
    )

    storage.create_lifecycle_event(
        workspace_id=workspace_id,
        task_id=task["id"],
        event_type="task.draft_created",
        payload={"object_id": task["id"], "gate": gate["id"]},
    )
    storage.create_lifecycle_event(
        workspace_id=workspace_id,
        task_id=task["id"],
        event_type="approval.requested",
        payload={"object_id": gate["id"], "name": gate["name"]},
    )

    return {
        "task": task,
        "approval_gate": gate,
        "messages": [user_message, sarathi_message],
    }


def _git_output(repo_path: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _git_lines(repo_path: Path, *args: str) -> list[str]:
    output = _git_output(repo_path, *args)
    if not output:
        return []
    return output.splitlines()
