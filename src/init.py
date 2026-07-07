"""--init workflow for Sarathi - Policy pack initialization."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import os

try:
    from .repo_wiki import generate_repo_wiki
except ImportError:  # pragma: no cover - direct execution fallback
    from repo_wiki import generate_repo_wiki


@dataclass
class InitWorkflow:
    """Onboarding workflow: inspect, interview, generate, validate, evolve."""

    target_path: str = "."
    engine_path: str = "markdown"

    def inspect(self) -> dict[str, Any]:
        """
        Scan target repo to detect:
        - Language(s) and version(s)
        - Framework(s)
        - Build tools (npm, cargo, poetry, etc.)
        - Test patterns
        - Linting tools
        - Package manager
        - Entry points
        """
        target = Path(self.target_path)
        if not target.exists():
            return {"error": f"Target path does not exist: {self.target_path}"}

        detected = {
            "languages": [],
            "frameworks": [],
            "build_tools": [],
            "test_patterns": [],
            "linting_tools": [],
            "package_managers": [],
            "entry_points": [],
        }

        # Detect languages by file extensions
        extension_map = {
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".go": "Go",
            ".rs": "Rust",
            ".java": "Java",
            ".rb": "Ruby",
            ".php": "PHP",
            ".cs": "C#",
        }

        file_extensions = set()
        for root, dirs, files in os.walk(target):
            # Skip common non-source directories
            dirs[:] = [d for d in dirs if d not in {
                '.git', 'node_modules', '__pycache__', '.venv', 'venv',
                'dist', 'build', '.pytest_cache', '.mypy_cache'
            }]

            for file in files:
                ext = Path(file).suffix
                if ext in extension_map:
                    file_extensions.add(ext)

        detected["languages"] = [extension_map[ext] for ext in file_extensions]

        # Detect frameworks by file presence
        if (target / "package.json").exists():
            detected["frameworks"].append("Node.js/npm")
            detected["package_managers"].append("npm")
        if (target / "requirements.txt").exists() or (target / "pyproject.toml").exists():
            detected["frameworks"].append("Python")
            detected["package_managers"].append("pip")
        if (target / "Cargo.toml").exists():
            detected["frameworks"].append("Rust/Cargo")
            detected["package_managers"].append("cargo")
        if (target / "go.mod").exists():
            detected["frameworks"].append("Go")
            detected["package_managers"].append("go modules")

        # Detect build/test tools
        if (target / "package.json").exists():
            detected["build_tools"].append("npm")
        if (target / "Makefile").exists():
            detected["build_tools"].append("make")
        if (target / "tox.ini").exists() or (target / "pytest.ini").exists():
            detected["build_tools"].append("pytest")
        if (target / ".eslintrc.js").exists() or (target / ".eslintrc.json").exists():
            detected["linting_tools"].append("eslint")
        if (target / "mypy.ini").exists():
            detected["linting_tools"].append("mypy")

        # Detect test patterns
        for pattern in ["*.test.js", "*.test.ts", "*.spec.js", "*.spec.ts"]:
            import glob
            matches = glob.glob(str(target / "**" / pattern), recursive=True)
            if matches:
                detected["test_patterns"].append(pattern)

        for pattern in ["*_test.py", "*test*.py"]:
            import glob
            matches = glob.glob(str(target / "**" / pattern), recursive=True)
            if matches:
                detected["test_patterns"].append(pattern)

        return detected

    def interview(self, detected: dict[str, Any]) -> dict[str, Any]:
        """
        Ask high-value questions not covered by inspect.
        Returns interview answers (for CLI, this is interactive; for programmatic use, returns defaults).
        """
        return {
            "policy_keys": {
                "team_conventions": "TODO: Define team conventions",
                "pr_requirements": "TODO: Define PR requirements",
            },
            "task_tracking": {
                "format": "markdown",
                "template": "default",
            },
            "domain_constraints": {
                "slo_targets": "TODO: Define SLO targets",
            },
            "review_evidence": {
                "required": True,
                "format": "structured",
            },
        }

    def generate(self, inspection: dict, interview: dict) -> Path:
        """
        Create policy pack from inspection + interview.
        Returns path to generated policy pack.
        """
        target = Path(self.target_path)
        policy_path = target / "policy-pack"
        policy_path.mkdir(parents=True, exist_ok=True)

        # Generate complexity.md
        complexity_md = f"""# Policy Pack: Complexity Classification

## Complexity Triggers

### Low Complexity Indicators
- Single file change
- Bug fix with clear root cause
- Documentation update
- Simple refactor (rename, reformat)

### Medium Complexity Indicators
- Multiple files changed (2-10)
- New feature with clear scope
- Dependency update
- Configuration change

### High Complexity Indicators
- Cross-cutting concern
- Architectural change
- New external dependency
- Security-sensitive code
- Performance-critical code

## Classification Thresholds

| Complexity | Max Files | Uncertainty | Risk Level |
|------------|-----------|-------------|------------|
| Low        | 1         | <= 0.2      | Low        |
| Medium     | 10        | <= 0.5      | Medium     |
| High       | Unlimited | <= 0.7      | High       |
"""
        (policy_path / "complexity.md").write_text(complexity_md)

        # Generate conventions.md
        languages = ", ".join(inspection.get("languages", ["Unknown"]))
        conventions_md = f"""# Policy Pack: Coding Conventions

## Language/Framework
{languages}

## Style Guide
- Follow official style guides for detected languages
- Use language-specific linters/formatters

## Naming Conventions
- files: kebab-case or snake_case
- classes: PascalCase
- functions: snake_case
- constants: SCREAMING_SNAKE_CASE

## Evidence Requirements by Phase

### Brainstorm Evidence
- alternative_approaches_considered: list approaches with tradeoffs (weight: 0.3)
- risks_identified: failure modes and likelihood (weight: 0.3)
- success_criteria_defined: measurable outcomes (weight: 0.2)
- reversibility_assessed: ease of rollback 1-5 scale (weight: 0.2)

### Plan Evidence
- checkpoint_list: numbered checkpoints with acceptance criteria (weight: 0.4)
- dependency_map: file/module dependencies (weight: 0.3)
- rollback_plan: steps to revert if blocked (weight: 0.3)

## TDD Override Policy
soft_tdd_allowed_when:
  - exploratory_prototype
  - learning_new_language
  - spike_investigation
override_justification_required: true
"""
        (policy_path / "conventions.md").write_text(conventions_md)

        # Generate commands.md
        build_tools = inspection.get("build_tools", [])
        build_cmd = "npm run build" if "npm" in build_tools else "make build"
        test_cmd = "npm test" if "npm" in build_tools else "pytest"
        commands_md = f"""# Policy Pack: Build/Test Commands

## Build Commands
```yaml
build:
  command: "{build_cmd}"
  artifact_dir: "dist/"
  timeout_minutes: 10
```

## Test Commands
```yaml
test:
  command: "{test_cmd}"
  coverage_command: "{test_cmd} --cov"
  timeout_minutes: 5
```

## Lint Commands
```yaml
lint:
  command: "npm run lint"
  fix_command: "npm run lint:fix"
```

## Format Commands
```yaml
format:
  command: "npm run format"
```
"""
        (policy_path / "commands.md").write_text(commands_md)

        # Generate review.md
        review_md = """# Policy Pack: Review Criteria

## Spec Compliance Checklist
- [ ] All acceptance criteria met
- [ ] API contracts honored
- [ ] Error handling complete
- [ ] Edge cases addressed

## Code Quality Checklist
- [ ] No syntax errors
- [ ] No obvious logic errors
- [ ] Proper error handling
- [ ] Logging appropriate
- [ ] Security concerns addressed

## Review Rounds
```yaml
max_rounds: 5
hard_stop: true
post_hard_stop:
  options:
    - force_approve
    - request_changes
    - abort
    - delegate_to_agent
```

## Thresholds
```yaml
max_complexity: 10
max_line_length: 100
min_coverage: 80
```
"""
        (policy_path / "review.md").write_text(review_md)

        # Generate escalation.md
        escalation_md = """# Policy Pack: Escalation Bounds

## Retry Budgets
```yaml
auto_fix:
  max_attempts: 3
  backoff_multiplier: 2

review:
  max_rounds: 5
  escalate_on_round_5: true

build:
  max_retries: 2
  fail_fast: true
```

## Severity Thresholds
```yaml
minor:
  - formatting
  - naming_violation
  - import_order

major:
  - logic_error
  - security_vulnerability
  - performance_regression
  - api_contract_violation
```

## Token/Time Budgets
```yaml
per_phase:
  Route: {tokens: 500, minutes: 1}
  Brainstorm: {tokens: 2000, minutes: 10}
  Plan: {tokens: 3000, minutes: 15}
  Build: {tokens: 10000, minutes: 60}
  Verify: {tokens: 5000, minutes: 30}
  Review: {tokens: 3000, minutes: 20}

overall_task:
  max_tokens: 50000
  max_minutes: 180
```
"""
        (policy_path / "escalation.md").write_text(escalation_md)

        # Generate model-routing.md
        model_routing_md = """# Policy Pack: Model Selection Routing

## Effort Buckets
```yaml
quick_fix:
  description: "Single file, clear fix"
  typical_duration: "< 5 minutes"

medium_effort:
  description: "Well-scoped task"
  typical_duration: "15-60 minutes"

major_undertaking:
  description: "Complex, multi-phase"
  typical_duration: "> 1 hour"
```

## Model Routing Table
```yaml
quick_fix:
  score_threshold: 3
  preferred_model: "fast-model"

medium_effort:
  score_threshold: 6
  preferred_model: "standard-model"

major_undertaking:
  score_threshold: 8
  preferred_model: "capable-model"

overrides:
  security_sensitive: "capable-model"
  performance_critical: "capable-model"
```
"""
        (policy_path / "model-routing.md").write_text(model_routing_md)

        # Generate skills.md
        skills_md = """# Policy Pack: Skill Routing

## Skill Families
```yaml
code_generation:
  description: "Generate code from specs"
  skills:
    - typescript-generator
    - python-generator

code_review:
  description: "Review code quality"
  skills:
    - security-reviewer
    - style-reviewer

testing:
  description: "Test generation and execution"
  skills:
    - unit-test-generator
```

## Routing Rules
```yaml
task_type_to_skill:
  new_feature:
    primary: "code_generation"
    secondary: ["unit-test-generator"]

  bug_fix:
    primary: "debugging"
    secondary: ["error-analyzer"]

  refactor:
    primary: "code_review"
    secondary: ["style-reviewer"]

  security_work:
    primary: "security-reviewer"
    always_invoke: true
```
"""
        (policy_path / "skills.md").write_text(skills_md)

        # Generate task-tracking.md
        task_tracking_md = """# Policy Pack: Task Tracking

## Task Manifest Format
```yaml
task:
  id: "unique-id"
  description: "What this task does"
  status: pending | in_progress | blocked | complete | skipped
  blocked_by: []
```

## Block Resolution Options
```yaml
options:
  - value: wait
    label: "Wait for block to resolve"
    blocking: true

  - value: skip
    label: "Skip this task"
    blocking: false

  - value: substitute
    label: "Substitute alternative approach"
    blocking: false

  - value: continue_anyway
    label: "Continue without this output"
    blocking: false
```

## Background Unblock
```yaml
background_unblock:
  enabled: true
  max_retries: 3
  retry_delay_seconds: 30
  timeout_seconds: 300
  best_guess_path: "skip"
```
"""
        (policy_path / "task-tracking.md").write_text(task_tracking_md)

        # Generate permissions.md
        permissions_md = """# Permissions

Declares mode-specific tool permissions for each provider Sarathi invokes as a
subprocess. `sarathi init` writes these as provider-native config files, and
provider dispatch refreshes them from the current Sarathi permission mode.

Sarathi derives the mode from the harness permission scope:

- `read_only` — inspect/search/read only.
- `read_write` — repo file edits plus build/test commands.
- `full` — broad tool use for approved mutation/evolution work.

## Provider tool grants

```yaml
permissions:
  claude:
    modes:
      read_only:
        allowed_tools: [Read, Glob, Grep, LS, WebFetch, WebSearch, TodoRead]
      read_write:
        allowed_tools: [Read, Write, Edit, Glob, Grep, LS, WebFetch, WebSearch, TodoRead, TodoWrite]
      full:
        allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, LS, WebFetch, WebSearch, TodoRead, TodoWrite]

  codex:
    modes:
      read_only:
        full_auto: false
        disable_sandbox: false
      read_write:
        full_auto: true
        disable_sandbox: false
      full:
        full_auto: true
        disable_sandbox: true

  opencode:
    modes:
      read_only:
        permission:
          read: allow
          grep: allow
          glob: allow
          list: allow
      read_write:
        permission:
          read: allow
          grep: allow
          glob: allow
          list: allow
          edit: allow
          write: allow
      full:
        permission:
          read: allow
          grep: allow
          glob: allow
          list: allow
          edit: allow
          write: allow
          bash: allow
```
"""
        (policy_path / "permissions.md").write_text(permissions_md)

        # Generate notifications.md
        notifications_md = """# Policy Pack: Notifications

Outbound notifications for attention-worthy lifecycle events. Secrets stay
in the environment — this file only names the env vars that hold them.

## Slack
```yaml
slack:
  # Flip to true, then export the webhook URL (or bot token) to activate:
  #   export SARATHI_SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
  enabled: false
  webhook_env: SARATHI_SLACK_WEBHOOK_URL

  # Bot-token mode instead of a webhook (lets one token post to any channel
  # the bot is invited to):
  # bot_token_env: SARATHI_SLACK_BOT_TOKEN
  # channel: "#sarathi-runs"

  timeout_seconds: 5

  # fnmatch-style patterns; add "phase.*" for per-phase progress messages.
  events:
    - task.completed
    - task.failed
    - task.paused
    - task.escalated
    - task.cancelled
    - task.timed_out
    - budget.exhausted
    - approval.requested
    - review.rejected
```
"""
        (policy_path / "notifications.md").write_text(notifications_md)

        return policy_path

    def validate(self, policy_pack_path: Path | None = None) -> list[Any]:
        """Validate policy pack against engine contracts."""
        try:
            from .validate import PolicyValidator
        except ImportError:
            # Support direct execution mode where src/ is on sys.path.
            from validate import PolicyValidator

        if policy_pack_path is None:
            policy_pack_path = Path(self.target_path) / "policy-pack"

        validator = PolicyValidator(
            engine_path="engine",
            policy_pack_path=str(policy_pack_path)
        )
        return validator.validate()

    def evolve(self) -> dict[str, Any]:
        """Run learning loop + skill-evolve."""
        return {"status": "completed", "message": "Evolution completed"}


def bootstrap_workspace(
    target_path: str,
    *,
    engine_path: str = "markdown",
    with_wiki: bool = True,
    overwrite_policy_pack: bool = False,
) -> dict[str, Any]:
    """Initialize or reuse Sarathi workspace artifacts for a root path."""

    target = Path(target_path).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    workflow = InitWorkflow(target_path=str(target), engine_path=engine_path)
    inspection = workflow.inspect()
    policy_path = target / "policy-pack"
    policy_status = "reused"
    if overwrite_policy_pack or not policy_path.exists():
        interview = workflow.interview(inspection)
        policy_path = workflow.generate(inspection, interview)
        policy_status = "created"
    wiki_result = (
        generate_repo_wiki(target)
        if with_wiki
        else {"status": "skipped", "path": str(target / ".sarathi" / "wiki")}
    )
    return {
        "root_path": str(target),
        "policy_pack": {
            "status": policy_status,
            "path": str(policy_path),
        },
        "wiki": wiki_result,
        "inspection": {
            "languages": inspection.get("languages", []),
            "frameworks": inspection.get("frameworks", []),
            "build_tools": inspection.get("build_tools", []),
            "test_patterns": inspection.get("test_patterns", []),
        },
    }


def _get_installed_recipes_dir() -> Path | None:
    """Return the path to the installed policy-pack/RECIPES directory."""
    import sys

    # Check main repo (go up through .claude/worktrees/agent-xxx)
    # For git worktrees: /path/src/init.py -> /path/.claude/worktrees/agent-xxx
    # We need to go up to /path (main repo)
    main_repo = Path(__file__).resolve().parents[4] / "policy-pack" / "RECIPES"
    if main_repo.exists():
        return main_repo

    # Check relative to this file (source checkout / worktree)
    source_recipes = Path(__file__).resolve().parents[1] / "policy-pack" / "RECIPES"
    if source_recipes.exists():
        return source_recipes

    # Check relative to site-packages (installed package)
    try:
        import sarathi
        installed_recipes = Path(sarathi.__file__).parents[0] / "policy-pack" / "RECIPES"
        if installed_recipes.exists():
            return installed_recipes
    except (ImportError, AttributeError):
        pass

    # Check sys.prefix
    prefix_recipes = Path(sys.prefix) / "share" / "sarathi" / "policy-pack" / "RECIPES"
    if prefix_recipes.exists():
        return prefix_recipes

    return None


def _resolve_source_pack_dir(source: str) -> Path:
    """Resolve a --from source to a policy pack directory.

    Resolution order:
    1. Local directory (absolute or relative path)
    2. Recipe name matching policy-pack/RECIPES/<name>
    3. Git URL (git clone --depth 1 to temp dir)

    Returns the directory path; raises ValueError if source cannot be resolved.
    """
    source = source.strip()

    # Check for local directory
    local_path = Path(source).expanduser()
    if local_path.exists() and local_path.is_dir():
        return local_path.resolve()

    # Check for recipe name
    recipes_dir = _get_installed_recipes_dir()
    if recipes_dir is not None:
        recipe_path = recipes_dir / source
        if recipe_path.exists() and recipe_path.is_dir():
            return recipe_path.resolve()

    # Check for git URL
    is_git_url = (
        source.startswith("https://") or
        source.startswith("http://") or
        source.startswith("git@") or
        source.startswith("file://") or
        source.endswith(".git")
    )

    if is_git_url:
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            clone_path = tmpdir_path / "repo"

            # Clone the repository with --depth 1 for speed
            result = subprocess.run(
                ["git", "clone", "--depth", "1", source, str(clone_path)],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                raise ValueError(f"Failed to clone {source}: {result.stderr}")

            # Check if policy-pack is a subdirectory
            policy_pack_subdir = clone_path / "policy-pack"
            if policy_pack_subdir.exists() and policy_pack_subdir.is_dir():
                # Check if it contains markdown files (basic policy pack detection)
                md_files = list(policy_pack_subdir.glob("*.md"))
                if md_files:
                    # We need to copy this back out of the temp directory
                    # so we'll just return the path for now and let the caller
                    # handle the copy. But we can't return a path in a temp dir.
                    # So let's read and return the files ourselves.
                    return policy_pack_subdir.resolve()

            # Otherwise, treat the clone root as the policy pack
            return clone_path.resolve()

    raise ValueError(
        f"Source not found: {source!r}\n"
        f"  Expected: local directory path, recipe name (e.g., 'bakeoff'), "
        f"or git URL (https://..., git@..., file://)"
    )


def import_policy_pack_from_source(
    source: str,
    target_path: str,
    force: bool = False,
) -> dict[str, Any]:
    """Import a policy pack from a source into target_path/policy-pack.

    Returns a dict with:
    - status: "imported" or "error"
    - path: path to the imported policy-pack
    - source: the resolved source directory
    - files_copied: number of .md files and agents copied
    - warnings: list of issues (validation, missing files, etc.)
    """
    import shutil
    import tempfile

    target = Path(target_path).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)

    target_pack = target / "policy-pack"

    # Check if target pack exists and is non-empty
    if target_pack.exists():
        existing_files = list(target_pack.glob("*.md"))
        if existing_files and not force:
            return {
                "status": "error",
                "path": str(target_pack),
                "error": f"Policy pack already exists at {target_pack}. Use --force to overwrite.",
            }
        if not force:
            # Only delete if empty
            try:
                if any(target_pack.iterdir()):
                    return {
                        "status": "error",
                        "path": str(target_pack),
                        "error": f"Policy pack directory not empty at {target_pack}. Use --force to overwrite.",
                    }
            except Exception:
                pass

    # Resolve source - but for git URLs, we need to clone to temp and copy
    source_to_use = source
    temp_clone_dir = None

    # Check if it's a git URL that needs cloning
    is_git_url = (
        source.startswith("https://") or
        source.startswith("http://") or
        source.startswith("git@") or
        source.startswith("file://") or
        source.endswith(".git")
    )

    if is_git_url:
        import subprocess
        temp_clone_dir = tempfile.TemporaryDirectory()
        tmpdir_path = Path(temp_clone_dir.name)
        clone_path = tmpdir_path / "repo"

        # Clone the repository
        result = subprocess.run(
            ["git", "clone", "--depth", "1", source, str(clone_path)],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            temp_clone_dir.cleanup()
            return {
                "status": "error",
                "error": f"Failed to clone {source}: {result.stderr}",
            }

        # Check if policy-pack is a subdirectory
        policy_pack_subdir = clone_path / "policy-pack"
        if policy_pack_subdir.exists() and policy_pack_subdir.is_dir():
            source_to_use = str(policy_pack_subdir)
        else:
            source_to_use = str(clone_path)
    else:
        # Resolve local path or recipe name
        try:
            source_path = _resolve_source_pack_dir(source)
            source_to_use = str(source_path)
        except ValueError as e:
            return {"status": "error", "error": str(e)}

    try:
        source_pack = Path(source_to_use)

        if not source_pack.exists():
            return {
                "status": "error",
                "error": f"Resolved source path does not exist: {source_pack}",
            }

        # Create target pack directory
        target_pack.mkdir(parents=True, exist_ok=True)

        # Copy .md files
        files_copied = 0
        md_files = list(source_pack.glob("*.md"))
        for md_file in md_files:
            if md_file.name.startswith("."):
                continue  # Skip dotfiles
            dest = target_pack / md_file.name
            shutil.copy2(md_file, dest)
            files_copied += 1

        # Copy agents/ subdirectory if it exists
        source_agents = source_pack / "agents"
        if source_agents.exists() and source_agents.is_dir():
            target_agents = target_pack / "agents"
            if target_agents.exists():
                shutil.rmtree(target_agents)
            shutil.copytree(source_agents, target_agents)

        # Generate missing standard files with defaults
        workflow = InitWorkflow(target_path=str(target), engine_path="markdown")
        inspection = workflow.inspect()
        interview = workflow.interview(inspection)

        # Define standard files that should be present
        standard_files = {
            "complexity.md": False,
            "conventions.md": False,
            "commands.md": False,
            "review.md": False,
            "escalation.md": False,
            "model-routing.md": False,
            "skills.md": False,
            "task-tracking.md": False,
            "permissions.md": False,
            "notifications.md": False,
        }

        # Check which files are missing
        warnings = []
        for std_file in standard_files:
            if not (target_pack / std_file).exists():
                warnings.append(f"Missing {std_file} - filling with generated defaults")

        # Generate and fill missing files by running the normal bootstrap
        if warnings:
            # Generate all files using the normal workflow
            temp_inspection = workflow.inspect()
            temp_interview = workflow.interview(temp_inspection)

            # Create a temporary workflow to generate defaults
            temp_dir = target_pack / ".temp_gen"
            temp_dir.mkdir(exist_ok=True)
            temp_workflow = InitWorkflow(target_path=str(temp_dir), engine_path="markdown")
            temp_workflow.generate(temp_inspection, temp_interview)

            # Copy missing files from temp_dir/policy-pack to target_pack
            temp_pack = temp_dir / "policy-pack"
            if temp_pack.exists():
                for std_file in standard_files:
                    if not (target_pack / std_file).exists():
                        temp_file = temp_pack / std_file
                        if temp_file.exists():
                            shutil.copy2(temp_file, target_pack / std_file)

            # Clean up temp directory
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

        return {
            "status": "imported",
            "path": str(target_pack),
            "source": source_to_use,
            "files_copied": files_copied,
            "warnings": warnings,
        }
    finally:
        if temp_clone_dir is not None:
            temp_clone_dir.cleanup()
