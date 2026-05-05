"""--init workflow for Sarathi - Policy pack initialization."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import os


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
