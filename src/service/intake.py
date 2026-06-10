"""Task intake helpers: drafting metadata, context extraction, and repository bootstrap."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from src.init import InitWorkflow
from src.storage import Storage

from .errors import ServiceError
from .preferences import (
    _default_repository_action_preference,
    _optional_dict,
    _optional_text,
)


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
    value = context.get("projectId")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _task_context_workspace_id(context: Any) -> str | None:
    if not isinstance(context, Mapping):
        return None
    value = context.get("workspaceId")
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

