# Sarathi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the core Sarathi framework - engine templates, policy pack structure, learnings system, and optional reference implementation.

**Architecture:** Sarathi is primarily a markdown-based framework for portability. The engine consists of workflow.md (phase lifecycle), required-list.md (policy contracts), and config.md. Policy packs are directories of .md files. A minimal reference implementation provides validation and tooling.

**Tech Stack:** Markdown (primary), Python (optional reference implementation), YAML (for validation schemas)

---

## File Structure

```
Sarathi/
├── engine/
│   ├── workflow.md          # Phase lifecycle with gates
│   ├── required-list.md     # Required inputs per phase
│   └── config.md            # Engine configuration
├── policy-pack/
│   ├── TEMPLATE/
│   │   ├── complexity.md
│   │   ├── conventions.md
│   │   ├── commands.md
│   │   ├── review.md
│   │   ├── escalation.md
│   │   ├── model-routing.md
│   │   ├── skills.md
│   │   └── task-tracking.md
│   └── EXAMPLE/
│       └── [populated example]
├── src/
│   ├── __init__.py
│   ├── engine.py           # Core engine logic
│   ├── dispatch.py         # Sub-agent dispatch
│   ├── evolve.py           # Learn-evolve loop
│   ├── validate.py         # Policy validation
│   └── init.py             # --init workflow
├── tests/
│   ├── test_engine.py
│   ├── test_dispatch.py
│   ├── test_evolve.py
│   └── test_validate.py
├── learnings/
│   └── evolve-baseline.md   # Global baseline template
├── docs/
│   └── specs/
│       └── 2026-04-14-sarathi-design.md
└── plans/
    └── 2026-04-14-sarathi-implementation-plan.md
```

---

## Task 1: Create Engine Core Files

**Files:**
- Create: `Sarathi/engine/workflow.md`
- Create: `Sarathi/engine/required-list.md`
- Create: `Sarathi/engine/config.md`
- Create: `Sarathi/learnings/evolve-baseline.md`

- [ ] **Step 1: Create engine/workflow.md**

```markdown
# Sarathi Engine - Workflow Lifecycle

## Phase Sequence

Phases execute in strict linear order. Policy may gate/skip certain phases based on complexity.

| Phase | Name | Gate | Parallel? |
|-------|------|------|-----------|
| 1 | Route | - | No |
| 2 | Brainstorm | 90% confidence (evidence-weighted) | No |
| 3 | PlanningAdvisor | High complexity only | No |
| 4 | Plan | 90% confidence (evidence-weighted) | No |
| 5 | Build | TDD + Elegance check | Yes (sub-agents) |
| 6 | Verify | Auto-fix bounds | Yes (sub-agents) |
| 7 | Review | 5-round hard stop | Yes (per-unit) |
| 8 | TaskTracking | - | Yes (sub-agents) |
| 9 | RiskCheck | Non-blocking | Yes (sub-agents) |
| 10 | Elegance | Auto-fix attempt | No |
| 11 | PhaseLog | - | No |
| 12 | Learn | - | No |

## Phase Details

### Phase 1: Route

**Entry:** Task received
**Exit:** Complexity classification (Low/Medium/High)

**Method:**
- Policy-defined complexity triggers
- Historical comparison fallback
- Outputs complexity + route mapping

### Phase 2: Brainstorm

**Entry:** Complexity classified
**Exit:** Confidence score >= 90%, evidence package

**Method:**
- Explore dispatch (mentor/apprentice)
- Evidence-weighted confidence gate

**Required Evidence:**
- alternative_approaches_considered (weight: 0.3)
- risks_identified (weight: 0.3)
- success_criteria_defined (weight: 0.2)
- reversibility_assessed (weight: 0.2)

### Phase 3: PlanningAdvisor

**Entry:** High complexity confirmed by Route
**Exit:** Advisory recommendations documented

**Method:**
- Interactive advisory loop
- Skipped for Low/Medium complexity

### Phase 4: Plan

**Entry:** Brainstorm gate passed
**Exit:** 90% confidence, checkpoint list, dependency manifest

**Required Evidence:**
- checkpoint_list (weight: 0.4)
- dependency_map (weight: 0.3)
- rollback_plan (weight: 0.3)

### Phase 5: Build

**Entry:** Plan gate passed
**Exit:** Implementation artifacts, test suite

**Method:**
- Execute dispatch per checkpoint
- Hard TDD (red-green-refactor)
- Policy may override to soft TDD with justification
- Pre-build: Elegance check (auto-fix attempt)

### Phase 6: Verify

**Entry:** Build artifacts ready
**Exit:** Verified artifacts, evidence package

**Method:**
- Auto-fix loop
- Escalation: Budget + Severity hybrid
- Policy defines budgets and severity thresholds

### Phase 7: Review

**Entry:** Verify artifacts ready
**Exit:** Review verdict or escalation bundle

**Method:**
- Per-unit parallel sub-agents
- Spec compliance + code quality
- 5-round hard stop

**Post-hard-stop (non-blocking for siblings):**
- Generate escalation bundle
- Options: force-approve | request-changes | abort | delegate-to-agent
- Task blocks, siblings continue

### Phase 8: TaskTracking

**Entry:** Review passed or escalation resolved
**Exit:** Updated task manifest

**Method:**
- Blocked sub-agent: C+D hybrid
- Background unblock with timeout
- Options menu presented to user

### Phase 9: RiskCheck

**Entry:** Task tracking complete
**Exit:** Risk flag report (non-blocking)

**Method:**
- Devil's advocate dispatch
- Flags concerns, does not block

### Phase 10: Elegance

**Entry:** Build loop entry
**Exit:** Cleaned artifacts or block report

**Method:**
- Auto-fix attempt on style issues
- Blocks only if auto-fix fails

### Phase 11: PhaseLog

**Entry:** Phase transition occurs
**Exit:** Tabular log entry

**Format:**
```
| Timestamp | From | To | Outcome | Iter | Key Decisions |
|-----------|------|----|---------|------|---------------|
```

### Phase 12: Learn

**Entry:** Task completes (any outcome)
**Exit:** Updated learnings.md, policy updates

**Method:**
- Document patterns/failures/approaches
- skill-evolve detects patterns
- Regression gate: >= 80% AND >= best seen

---

## Sub-Agent Dispatch

### Explore Mode (Brainstorm, PlanningAdvisor, RiskCheck)
- Rich Q&A interface
- Persistent context
- May push clarifying questions

### Execute Mode (Plan, Build, Verify, Review)
- Structured task objects
- Stateless-ish, returns artifacts

---

## Model Selection

Engine computes:
- Effort bucket (quick_fix / medium_effort / major_undertaking)
- Token budget
- Time budget
- Complexity score (uncertainty × scope × risk)

Policy defines routing table mapping to model selection.

---

## Policy Validation

core-policy-interface-mapping.md dual-source truth:
- Engine generates expected mapping
- Policy claims its mapping
- --init diffs and reports PASS/DRIFT/TODO
```

- [ ] **Step 2: Create engine/required-list.md**

```markdown
# Sarathi Engine - Required Policy Inputs

## Per-Phase Required Inputs

### Phase 1: Route
**Required:** `complexity.md`
- complexity_triggers: list of rule patterns
- classification_thresholds: Low/Medium/High boundaries
- historical_patterns: reference to past task classifications

### Phase 2: Brainstorm
**Required:** `conventions.md` (partial)
- brainstorming_protocol: evidence requirements
- confidence_weights: per evidence type

### Phase 3: PlanningAdvisor
**Required:** `conventions.md` (partial)
- advisor_depth: how detailed should recommendations be

### Phase 4: Plan
**Required:** `conventions.md` (partial)
- checkpoint_requirements: what constitutes a valid checkpoint
- dependency_tracking: how to declare dependencies

### Phase 5: Build
**Required:** `commands.md`, `conventions.md`
- build_commands: how to build
- test_commands: how to test
- tdd_mode: hard | soft | test-adjacent | policy-gated
- conventions: coding style rules

### Phase 6: Verify
**Required:** `escalation.md`
- retry_budgets: max retries per error type
- severity_thresholds: minor vs major classification
- auto_fix_attempts: when to auto-fix vs escalate

### Phase 7: Review
**Required:** `review.md`
- review_criteria: what "reviewed" means
- evidence_requirements: what artifacts to produce
- hard_stop_rounds: 5 (default)
- escalation_options: menu items

### Phase 8: TaskTracking
**Required:** `task-tracking.md`
- task_manifest_format: how to represent tasks
- block_resolution_options: menu items
- background_unblock_retries: N

### Phase 9: RiskCheck
**Required:** `conventions.md` (partial)
- devil_advocate_depth: how thorough

### Phase 10: Elegance
**Required:** `conventions.md` (partial)
- elegance_criteria: what "elegant" means
- auto_fix_policies: what can be auto-fixed

### Phase 11: PhaseLog
**Required:** `config.md`
- log_verbosity: minimal | structured | full

### Phase 12: Learn
**Required:** `skills.md` (partial)
- pattern_detection: how to identify learnable patterns
- evolution_threshold: >= 80% + >= best seen

---

## Cross-Cutting Requirements

### Model Selection
**Required:** `model-routing.md`
- effort_bucket_mapping: task type → bucket
- token_budget_guidelines: per complexity
- time_budget_guidelines: per complexity
- model_routing_table: (bucket + budget + score) → model

### Skill Routing
**Required:** `skills.md`
- skill_families: registered families
- routing_rules: when to use which skill
- discovery_paths: where to look for skills

---

## Validation Contract

A policy pack is valid if it provides all required files with all required fields.

```
PASS: All required inputs satisfied
DRIFT: Mismatch between expected and claimed
TODO: Missing required inputs
```
```

- [ ] **Step 3: Create engine/config.md**

```markdown
# Sarathi Engine Configuration

## Engine Version
version: "0.1.0"

## Default Settings

### Lifecycle
default_phases:
  - Route
  - Brainstorm
  - Plan
  - Build
  - Verify
  - Review
  - TaskTracking
  - RiskCheck
  - Elegance
  - PhaseLog
  - Learn

skip_phases_if_low_complexity:
  - PlanningAdvisor

skip_phases_if_medium_complexity:
  - PlanningAdvisor

### Sub-Agent Dispatch
dispatch_modes:
  explore:
    type: mentor_apprentice
    persistent_context: true
    max_turns: 50
  execute:
    type: task_framing
    stateless: true
    timeout_minutes: 30

### Confidence Gates
gate_threshold: 0.90
evidence_weighted: true

### Parallelization
parallel_within_phase: true
parallel_between_phases: false
max_parallel_subagents: 5

### Logging
phase_log:
  format: tabular
  verbosity: minimal
  output: phase-log.md

### Learn-Evolve
learn_evolve:
  enabled: true
  global_baseline: learnings/evolve-baseline.md
  regression_gate:
    min_pass_rate: 0.80
    require_best_seen: true
  auto_apply_threshold: 0.95

## Platform Integration

### Agent Abstraction Layer
agent_interface:
  dispatch_explore: agent_dispatch_explore
  dispatch_execute: agent_dispatch_execute
  get_context: agent_get_context
  push_question: agent_push_question

### Validation
policy_validation:
  mode: dual_source_truth
  mapping_file: core-policy-interface-mapping.md
  report_format: PASS | DRIFT | TODO
```

- [ ] **Step 4: Create learnings/evolve-baseline.md**

```markdown
# Sarathi Global Evolve Baseline

## Purpose
Central repository for cross-project learnings. Patterns proven in multiple projects with >= 80% pass rate and >= best-seen performance are promoted here.

## Structure

```markdown
## Pattern: [name]
- **First seen:** YYYY-MM-DD, [project]
- **Validated in:** [list of projects]
- **Pass rate:** 0.XX
- **Best seen:** 0.XX
- **Trend:** [improving | stable | declining]
- **Evidence:** [link to learnings files]
- **Promotion date:** YYYY-MM-DD (if promoted)
```

## Active Patterns

<!-- Patterns accumulate here over time -->

## Deprecated Patterns

<!-- Patterns removed after regression -->

## Statistics

- Total patterns: N
- Promoted this month: N
- Deprecated this month: N
```

- [ ] **Step 5: Commit**

```bash
git add Sarathi/engine/ Sarathi/learnings/
git commit -m "feat: add Sarathi engine core files"
```

---

## Task 2: Create Policy Pack Templates

**Files:**
- Create: `Sarathi/policy-pack/TEMPLATE/complexity.md`
- Create: `Sarathi/policy-pack/TEMPLATE/conventions.md`
- Create: `Sarathi/policy-pack/TEMPLATE/commands.md`
- Create: `Sarathi/policy-pack/TEMPLATE/review.md`
- Create: `Sarathi/policy-pack/TEMPLATE/escalation.md`
- Create: `Sarathi/policy-pack/TEMPLATE/model-routing.md`
- Create: `Sarathi/policy-pack/TEMPLATE/skills.md`
- Create: `Sarathi/policy-pack/TEMPLATE/task-tracking.md`
- Create: `Sarathi/policy-pack/EXAMPLE/` (populated example)

- [ ] **Step 1: Create policy-pack/TEMPLATE/complexity.md**

```markdown
# Policy Pack: Complexity Classification

## Complexity Triggers

### Low Complexity Indicators
- Single file change
- Bug fix with clear root cause
- Documentation update
- Simple refactor (rename, reformat)
- Test addition without logic change

### Medium Complexity Indicators
- Multiple files changed
- New feature with clear scope
- Dependency update
- Configuration change
- Integration with existing APIs

### High Complexity Indicators
- Cross-cutting concern
- Architectural change
- New external dependency
- Performance-sensitive code
- Security-sensitive code
- Multi-phase task with checkpoints

## Classification Thresholds

```yaml
low:
  max_files: 1
  max_uncertainty: 0.2
  risk_level: low

medium:
  max_files: 10
  max_uncertainty: 0.5
  risk_level: medium

high:
  max_files: unlimited
  max_uncertainty: 0.7
  risk_level: high
```

## Historical Comparison

Reference patterns from learnings.md:
- Past task complexity classifications
- What triggered high complexity in similar tasks
- What was actually complex vs perceived complex

## Routing Rules

| Complexity | Skip PlanningAdvisor? | TDD Mode | Parallel? |
|------------|---------------------|----------|-----------|
| Low | Yes | soft | No |
| Medium | Yes | soft | Yes |
| High | No | hard | Yes |
```

- [ ] **Step 2: Create policy-pack/TEMPLATE/conventions.md**

```markdown
# Policy Pack: Coding Conventions

## Language/Framework

[Specify language and version constraints]

## Style Guide

[Link to or embed style guide]

## Naming Conventions

```yaml
files: kebab-case
classes: PascalCase
functions: snake_case
constants: SCREAMING_SNAKE_CASE
```

## Code Organization

```yaml
structure:
  - src/
  - tests/
  - docs/
  - config/
```

## Evidence Requirements by Phase

### Brainstorm Evidence
- alternative_approaches_considered: list approaches with tradeoffs
- risks_identified: failure modes and likelihood
- success_criteria_defined: measurable outcomes
- reversibility_assessed: ease of rollback (1-5 scale)

### Plan Evidence
- checkpoint_list: numbered checkpoints with acceptance criteria
- dependency_map: file/module dependencies
- rollback_plan: steps to revert if blocked

## Elegance Criteria

### Auto-Fixable
- Formatting inconsistencies
- Naming violations
- Import ordering
- Comment style

### Requires Human
- Logic complexity (> N cyclomatic complexity)
- Design pattern violations
- Architectural concerns

## Devil's Advocate Depth

```yaml
risk_areas:
  - security: high
  - performance: medium
  - maintainability: high
  - compatibility: medium
```

## TDD Override Policy

```yaml
soft_tdd_allowed_when:
  - exploratory_prototype
  - learning_new_language
  - spike_investigation
override_justification_required: true
```
```

- [ ] **Step 3: Create policy-pack/TEMPLATE/commands.md**

```markdown
# Policy Pack: Build/Test Commands

## Build Commands

```yaml
build:
  command: "npm run build"
  artifact_dir: "dist/"
  timeout_minutes: 10

watch:
  command: "npm run watch"
  trigger: "file change"
```

## Test Commands

```yaml
test:
  command: "npm test"
  coverage_command: "npm run test:coverage"
  timeout_minutes: 5

unit:
  command: "npm run test:unit"
  pattern: "**/*.test.ts"

integration:
  command: "npm run test:integration"
  pattern: "**/*.integration.test.ts"

e2e:
  command: "npm run test:e2e"
  pattern: "**/*.e2e.test.ts"
```

## Debug Commands

```yaml
debug:
  command: "npm run debug"
  port: 9229

inspect:
  command: "node --inspect"
```

## Lint Commands

```yaml
lint:
  command: "npm run lint"
  fix_command: "npm run lint:fix"

format:
  command: "npm run format"
```
```

- [ ] **Step 4: Create policy-pack/TEMPLATE/review.md**

```markdown
# Policy Pack: Review Criteria

## Spec Compliance

### Checklist
- [ ] All acceptance criteria met
- [ ] API contracts honored
- [ ] Error handling complete
- [ ] Edge cases addressed

### Evidence Required
- spec_compliance_checklist: completed checklist
- acceptance_test_results: test output

## Code Quality

### Checklist
- [ ] No syntax errors
- [ ] No obvious logic errors
- [ ] Proper error handling
- [ ] Logging appropriate
- [ ] Security concerns addressed
- [ ] Performance acceptable

### Thresholds
```yaml
max_complexity: 10
max_line_length: 100
min_coverage: 80
```

## Review Rounds

```yaml
max_rounds: 5
hard_stop: true

post_hard_stop:
  non_blocking_escalation: true
  options:
    - force_approve
    - request_changes
    - abort
    - delegate_to_agent
```

## Review Output Format

```yaml
format:
  verdict: pass | fail | escalate
  evidence:
    - type: artifact
      path: path/to/artifact
    - type: diff
      path: path/to/diff
    - type: test_results
      path: path/to/results
  summary: "2-3 sentence summary"
  concerns: ["list of concerns"]
```
```

- [ ] **Step 5: Create policy-pack/TEMPLATE/escalation.md**

```markdown
# Policy Pack: Escalation Bounds

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
  - comment_style

major:
  - logic_error
  - security_vulnerability
  - performance_regression
  - api_contract_violation
  - data_loss_risk

escalation_trigger:
  major_immediately: true
  minor_after_budget: true
```

## Token/Time Budgets

```yaml
per_phase:
  Route: { tokens: 500, minutes: 1 }
  Brainstorm: { tokens: 2000, minutes: 10 }
  Plan: { tokens: 3000, minutes: 15 }
  Build: { tokens: 10000, minutes: 60 }
  Verify: { tokens: 5000, minutes: 30 }
  Review: { tokens: 3000, minutes: 20 }

overall_task:
  max_tokens: 50000
  max_minutes: 180
```

## Escalation Actions

```yaml
on_major_severity:
  action: escalate_immediately
  notify: user
  block_task: true

on_budget_exhausted:
  action: escalate_with_options
  options:
    - increase_budget
    - simplify_scope
    - abort
```
```

- [ ] **Step 6: Create policy-pack/TEMPLATE/model-routing.md**

```markdown
# Policy Pack: Model Selection Routing

## Effort Buckets

```yaml
quick_fix:
  description: "Single file, clear fix"
  example: "Fix typo, add test"
  typical_duration: "< 5 minutes"

medium_effort:
  description: "Well-scoped task"
  example: "Add feature to existing module"
  typical_duration: "15-60 minutes"

major_undertaking:
  description: "Complex, multi-phase"
  example: "New service, architectural change"
  typical_duration: "> 1 hour"
```

## Token Budget Guidelines

```yaml
quick_fix:
  estimated_tokens: 2000
  budget_padding: 1.2

medium_effort:
  estimated_tokens: 10000
  budget_padding: 1.3

major_undertaking:
  estimated_tokens: 50000
  budget_padding: 1.5
```

## Time Budget Guidelines

```yaml
quick_fix:
  minutes: 5
  warn_at_minutes: 4

medium_effort:
  minutes: 60
  warn_at_minutes: 45

major_undertaking:
  minutes: 180
  warn_at_minutes: 120
```

## Complexity Score

```yaml
dimensions:
  uncertainty:
    weight: 0.4
    scale: 0-10
  scope:
    weight: 0.3
    scale: 0-10
  risk:
    weight: 0.3
    scale: 0-10

composite_formula: "uncertainty * 0.4 + scope * 0.3 + risk * 0.3"
```

## Model Routing Table

```yaml
quick_fix:
  score_threshold: 3
  preferred_model: "fast-model"
  fallback_model: "standard-model"

medium_effort:
  score_threshold: 6
  preferred_model: "standard-model"
  fallback_model: "capable-model"

major_undertaking:
  score_threshold: 8
  preferred_model: "capable-model"
  fallback_model: "extended-model"

overrides:
  security_sensitive: "extended-model"
  performance_critical: "extended-model"
```
```

- [ ] **Step 7: Create policy-pack/TEMPLATE/skills.md**

```markdown
# Policy Pack: Skill Routing

## Skill Families

```yaml
code_generation:
  description: "Generate code from specs"
  skills:
    - typescript-generator
    - python-generator
    - sql-generator

code_review:
  description: "Review code quality"
  skills:
    - security-reviewer
    - performance-reviewer
    - style-reviewer

testing:
  description: "Test generation and execution"
  skills:
    - unit-test-generator
    - integration-test-generator
    - e2e-test-generator

debugging:
  description: "Debug and fix issues"
  skills:
    - error-analyzer
    - stack-trace-reader
    - regression-detector
```

## Routing Rules

```yaml
task_type_to_skill:
  new_feature:
    primary: "code_generation"
    secondary:
      - "unit-test-generator"

bug_fix:
    primary: "debugging"
    secondary:
      - "error-analyzer"

refactor:
    primary: "code_review"
    secondary:
      - "style-reviewer"

security_work:
    primary: "security-reviewer"
    always_invoke: true
```

## Discovery Paths

```yaml
search_paths:
  - ".skills/"
  - "skills/"
  - "~/shared-skills/"

file_patterns:
  - "*.skill.md"
  - "skill-*.md"
```

## Missing Skill Protocol

```yaml
on_missing_skill:
  action: create_skill
  template: "skills/skill-template.md"
  prompt_for_definition: true
  bake_into_policy: true
```
```

- [ ] **Step 8: Create policy-pack/TEMPLATE/task-tracking.md**

```markdown
# Policy Pack: Task Tracking

## Task Manifest Format

```yaml
task:
  id: "unique-id"
  description: "What this task does"
  status: pending | in_progress | blocked | complete | skipped
  blocked_by: []
  inputs:
    - name: "input name"
      type: "file | api | context"
      path: "path or reference"
  outputs:
    - name: "output name"
      type: "file | api | context"
      path: "path or reference"
  context_ref: "reference to shared context"
```

## Block Resolution Options

```yaml
options:
  - value: wait
    label: "Wait for block to resolve"
    blocking: true
    icon: "hourglass"

  - value: skip
    label: "Skip this task"
    blocking: false
    icon: "forward"

  - value: substitute
    label: "Substitute alternative approach"
    blocking: false
    icon: "swap"

  - value: continue_anyway
    label: "Continue without this output"
    blocking: false
    icon: "play"
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

## Dependency Tracking

```yaml
manifest_fields:
  - id
  - status
  - blocked_by
  - depends_on
  - outputs_produced
  - outputs_consumed

cross_phase_dependencies:
  enabled: true
  manifest_field: "cross_phase_ref"
```
```

- [ ] **Step 9: Create policy-pack/EXAMPLE/ directory with populated example**

- [ ] **Step 10: Commit**

```bash
git add Sarathi/policy-pack/
git commit -m "feat: add Sarathi policy pack templates"
```

---

## Task 3: Create Reference Implementation

**Files:**
- Create: `Sarathi/src/__init__.py`
- Create: `Sarathi/src/engine.py`
- Create: `Sarathi/src/dispatch.py`
- Create: `Sarathi/src/evolve.py`
- Create: `Sarathi/src/validate.py`
- Create: `Sarathi/src/init.py`
- Create: `Sarathi/pyproject.toml`
- Create: `Sarathi/tests/test_engine.py`
- Create: `Sarathi/tests/test_dispatch.py`
- Create: `Sarathi/tests/test_evolve.py`
- Create: `Sarathi/tests/test_validate.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "sarathi"
version = "0.1.0"
description = "Generic workflow orchestration framework for AI agents"
requires-python = ">=3.10"

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "black", "mypy"]

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.black]
line-length = 100

[tool.mypy]
python_version = "3.10"
```

- [ ] **Step 2: Create src/__init__.py**

```python
"""Sarathi - Generic workflow orchestration framework."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Create src/engine.py**

```python
"""Core engine logic for Sarathi."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Phase(Enum):
    ROUTE = "Route"
    BRAINSTORM = "Brainstorm"
    PLANNING_ADVISOR = "PlanningAdvisor"
    PLAN = "Plan"
    BUILD = "Build"
    VERIFY = "Verify"
    REVIEW = "Review"
    TASK_TRACKING = "TaskTracking"
    RISK_CHECK = "RiskCheck"
    ELEGANCE = "Elegance"
    PHASE_LOG = "PhaseLog"
    LEARN = "Learn"


class Complexity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class PhaseResult:
    phase: Phase
    outcome: str  # pass | fail | skip | escalate
    iterations: int = 0
    decisions: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskContext:
    task_id: str
    description: str
    complexity: Complexity | None = None
    phase_results: list[PhaseResult] = field(default_factory=list)
    current_phase: Phase = Phase.ROUTE

    def get_phase_log(self) -> list[dict]:
        return [
            {
                "timestamp": r.phase.name,
                "from": r.phase.name,
                "to": "next",
                "outcome": r.outcome,
                "iter": r.iterations,
                "decisions": r.decisions,
            }
            for r in self.phase_results
        ]


class Engine:
    """Core Sarathi engine."""

    def __init__(self, policy_pack_path: str):
        self.policy_pack_path = policy_pack_path
        self.phases = list(Phase)

    def run_task(self, task: TaskContext) -> TaskContext:
        """Run a task through the lifecycle."""
        while task.current_phase != Phase.LEARN:
            next_phase = self._next_phase(task)
            if next_phase is None:
                break
            result = self._execute_phase(task, next_phase)
            task.phase_results.append(result)
            task.current_phase = next_phase
        return task

    def _next_phase(self, task: TaskContext) -> Phase | None:
        """Determine next phase based on routing."""
        if task.current_phase == Phase.ROUTE:
            return Phase.BRAINSTORM
        if task.current_phase == Phase.BRAINSTORM:
            if task.complexity == Complexity.HIGH:
                return Phase.PLANNING_ADVISOR
            return Phase.PLAN
        if task.current_phase == Phase.PLANNING_ADVISOR:
            return Phase.PLAN
        # Add remaining phase transitions...
        return None

    def _execute_phase(self, task: TaskContext, phase: Phase) -> PhaseResult:
        """Execute a single phase."""
        return PhaseResult(phase=phase, outcome="pass")
```

- [ ] **Step 4: Create src/dispatch.py**

```python
"""Sub-agent dispatch for Sarathi."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskSpec:
    id: str
    description: str
    inputs: dict[str, Any] = field(default_factory=dict)
    expected_outputs: list[str] = field(default_factory=list)
    context_ref: str | None = None
    escalation_policy: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExploreResult:
    messages: list[dict[str, Any]]
    confidence: float
    evidence: dict[str, Any]


@dataclass
class ExecuteResult:
    outputs: dict[str, Any]
    artifacts: dict[str, Any]
    success: bool


class Dispatcher(ABC):
    """Base dispatcher for sub-agents."""

    @abstractmethod
    def dispatch_explore(self, prompt: str, context: dict) -> ExploreResult:
        """Dispatch in explore (mentor/apprentice) mode."""
        pass

    @abstractmethod
    def dispatch_execute(self, task: TaskSpec) -> ExecuteResult:
        """Dispatch in execute (task-framing) mode."""
        pass


class NullDispatcher(Dispatcher):
    """Placeholder dispatcher for framework validation."""

    def dispatch_explore(self, prompt: str, context: dict) -> ExploreResult:
        return ExploreResult(messages=[], confidence=1.0, evidence={})

    def dispatch_execute(self, task: TaskSpec) -> ExecuteResult:
        return ExecuteResult(outputs={}, artifacts={}, success=True)
```

- [ ] **Step 5: Create src/evolve.py**

```python
"""Learn-evolve loop for Sarathi."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Pattern:
    name: str
    first_seen: datetime
    validated_in: list[str] = field(default_factory=list)
    pass_rate: float = 0.0
    best_seen: float = 0.0
    trend: str = "stable"  # improving | stable | declining
    evidence_refs: list[str] = field(default_factory=list)
    promotion_date: datetime | None = None


@dataclass
class EvolveBaseline:
    patterns: list[Pattern] = field(default_factory=list)
    total_patterns: int = 0
    promoted_this_month: int = 0
    deprecated_this_month: int = 0


class Evolver:
    """Learn-evolve loop implementation."""

    def __init__(self, baseline_path: str):
        self.baseline_path = baseline_path

    def detect_pattern(
        self, learnings: list[dict[str, Any]], project: str
    ) -> list[Pattern]:
        """Detect recurring patterns across learnings."""
        return []

    def should_promote(self, pattern: Pattern) -> bool:
        """Check regression gate for promotion."""
        return (
            pattern.pass_rate >= 0.80
            and pattern.pass_rate >= pattern.best_seen
        )

    def apply_evolution(self, pattern: Pattern) -> None:
        """Apply high-confidence evolution to policy."""
        pass
```

- [ ] **Step 6: Create src/validate.py**

```python
"""Policy validation for Sarathi."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class ValidationStatus(Enum):
    PASS = "PASS"
    DRIFT = "DRIFT"
    TODO = "TODO"


@dataclass
class ValidationResult:
    status: ValidationStatus
    required_input: str
    policy_file: str | None
    issue: str | None = None


class PolicyValidator:
    """Dual-source truth policy validation."""

    def __init__(self, engine_path: str, policy_pack_path: str):
        self.engine_path = Path(engine_path)
        self.policy_pack_path = Path(policy_pack_path)

    def load_required_list(self) -> dict[str, Any]:
        """Load engine's required-list.md."""
        required_file = self.engine_path / "required-list.md"
        return {}  # Parse markdown

    def load_policy_claims(self) -> dict[str, Any]:
        """Load policy pack's claimed coverage."""
        return {}

    def validate(self) -> list[ValidationResult]:
        """Run dual-source validation."""
        results = []
        required = self.load_required_list()
        claims = self.load_policy_claims()

        for phase, inputs in required.items():
            for inp in inputs:
                if inp in claims.get(phase, []):
                    results.append(
                        ValidationResult(
                            status=ValidationStatus.PASS,
                            required_input=inp,
                            policy_file=claims[inp],
                        )
                    )
                elif inp in claims.get("optional", []):
                    results.append(
                        ValidationResult(
                            status=ValidationStatus.DRIFT,
                            required_input=inp,
                            policy_file=None,
                            issue="claimed as optional",
                        )
                    )
                else:
                    results.append(
                        ValidationResult(
                            status=ValidationStatus.TODO,
                            required_input=inp,
                            policy_file=None,
                            issue="not provided",
                        )
                    )
        return results
```

- [ ] **Step 7: Create src/init.py**

```python
"""--init workflow for Sarathi."""

import subprocess
from pathlib import Path
from typing import Any


class InitWorkflow:
    """Onboarding workflow: inspect, interview, generate, validate, evolve."""

    def __init__(self, target_path: str, engine_path: str):
        self.target_path = Path(target_path)
        self.engine_path = Path(engine_path)

    def inspect(self) -> dict[str, Any]:
        """Scan target repo, detect language/framework/build tools."""
        return {
            "language": "python",
            "framework": "fastapi",
            "build_tools": ["pytest", "black"],
            "test_patterns": ["*.test.py", "*.spec.py"],
        }

    def interview(self, detected: dict[str, Any]) -> dict[str, Any]:
        """Ask high-value questions not covered by inspect."""
        return {
            "policy_keys": {},
            "task_tracking": {},
            "domain_constraints": {},
        }

    def generate(self, inspection: dict, interview: dict) -> Path:
        """Create policy pack from inspection + interview."""
        output_path = self.target_path / "policy-pack"
        output_path.mkdir(parents=True, exist_ok=True)
        return output_path

    def validate(self, policy_pack_path: Path) -> list[Any]:
        """Validate against engine contracts."""
        from .validate import PolicyValidator

        validator = PolicyValidator(self.engine_path, policy_pack_path)
        return validator.validate()

    def evolve(self) -> None:
        """Run learning loop + skill-evolve."""
        pass
```

- [ ] **Step 8: Create tests/test_engine.py**

```python
"""Tests for engine core."""

import pytest
from sarathi.engine import Engine, Phase, Complexity, TaskContext


def test_engine_initialization():
    engine = Engine("/path/to/policy")
    assert engine.phases == list(Phase)


def test_route_phase_sets_complexity():
    engine = Engine("/path/to/policy")
    task = TaskContext(task_id="test-1", description="simple fix")
    result = engine.run_task(task)
    assert result.current_phase == Phase.LEARN


def test_phase_log_format():
    engine = Engine("/path/to/policy")
    task = TaskContext(task_id="test-1", description="simple fix")
    task = engine.run_task(task)
    log = task.get_phase_log()
    assert isinstance(log, list)
```

- [ ] **Step 9: Create tests/test_dispatch.py**

```python
"""Tests for dispatch module."""

import pytest
from sarathi.dispatch import TaskSpec, NullDispatcher, ExecuteResult


def test_null_dispatcher_execute():
    dispatcher = NullDispatcher()
    task = TaskSpec(id="t1", description="test")
    result = dispatcher.dispatch_execute(task)
    assert result.success is True


def test_task_spec_fields():
    task = TaskSpec(
        id="t1",
        description="test task",
        inputs={"file": "src/main.py"},
        expected_outputs=["src/main.py"],
    )
    assert task.id == "t1"
    assert task.inputs["file"] == "src/main.py"
```

- [ ] **Step 10: Create tests/test_evolve.py**

```python
"""Tests for evolve module."""

import pytest
from datetime import datetime
from sarathi.evolve import Evolver, Pattern


def test_pattern_pass_gate():
    evolver = Evolver("/path/to/baseline")
    pattern = Pattern(
        name="test-pattern",
        first_seen=datetime.now(),
        pass_rate=0.85,
        best_seen=0.80,
    )
    assert evolver.should_promote(pattern) is True


def test_pattern_fails_below_gate():
    evolver = Evolver("/path/to/baseline")
    pattern = Pattern(
        name="test-pattern",
        first_seen=datetime.now(),
        pass_rate=0.75,
        best_seen=0.80,
    )
    assert evolver.should_promote(pattern) is False
```

- [ ] **Step 11: Create tests/test_validate.py**

```python
"""Tests for validate module."""

import pytest
from sarathi.validate import PolicyValidator, ValidationStatus


def test_validation_pass():
    validator = PolicyValidator("/engine", "/policy")
    results = validator.validate()
    assert isinstance(results, list)
```

- [ ] **Step 12: Run tests to verify they pass**

```bash
cd Sarathi && pip install -e ".[dev]" && pytest tests/ -v
```

Expected: PASS (null dispatcher returns success)

- [ ] **Step 13: Commit**

```bash
git add Sarathi/src/ Sarathi/tests/ Sarathi/pyproject.toml
git commit -m "feat: add Sarathi reference implementation"
```

---

## Task 4: Create CLI Entry Points

**Files:**
- Create: `Sarathi/src/cli.py`
- Create: `Sarathi/sarathi.py` (entry point script)

- [ ] **Step 1: Create src/cli.py**

```python
"""CLI for Sarathi."""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(prog="sarathi")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Initialize policy pack")
    init_parser.add_argument("target", nargs="?", default=".")
    init_parser.add_argument("--engine", default=None)

    validate_parser = subparsers.add_parser("validate", help="Validate policy pack")
    validate_parser.add_argument("policy_pack")

    run_parser = subparsers.add_parser("run", help="Run a task")
    run_parser.add_argument("task_file")
    run_parser.add_argument("--policy-pack", required=True)

    args = parser.parse_args()

    if args.command == "init":
        from .init import InitWorkflow

        workflow = InitWorkflow(args.target, args.engine or "engine")
        inspection = workflow.inspect()
        interview = workflow.interview(inspection)
        policy_path = workflow.generate(inspection, interview)
        results = workflow.validate(policy_path)
        print(f"Validation results: {results}")

    elif args.command == "validate":
        from .validate import PolicyValidator

        validator = PolicyValidator("engine", args.policy_pack)
        results = validator.validate()
        for r in results:
            print(f"{r.status.value}: {r.required_input}")

    elif args.command == "run":
        print("Run not yet implemented")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create sarathi.py entry point**

```python
#!/usr/bin/env python3
"""Sarathi CLI entry point."""

from sarathi.src.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit**

```bash
git add Sarathi/sarathi.py Sarathi/src/cli.py
git commit -m "feat: add Sarathi CLI"
```

---

## Task 5: Create Documentation

**Files:**
- Create: `Sarathi/README.md`
- Create: `Sarathi/docs/core-policy-interface-mapping.md`

- [ ] **Step 1: Create README.md**

```markdown
# Sarathi

A generic, tool-agnostic workflow orchestration framework for AI development agents.

## Quick Start

```bash
# Install
pip install sarathi

# Initialize policy pack for a project
sarathi init

# Validate policy pack
sarathi validate ./policy-pack

# Run a task
sarathi run task.yaml --policy-pack ./policy-pack
```

## Architecture

- **Engine** (`engine/`) - Zero domain knowledge, defines HOW
- **Policy Pack** (`policy-pack/`) - Domain-specific rules
- **Learn-Evolve** - System gets smarter over time

## Lifecycle Phases

1. Route → 2. Brainstorm → 3. Planning Advisor → 4. Plan → 5. Build → 6. Verify → 7. Review → 8. Task Tracking → 9. Risk Check → 10. Elegance → 11. Phase Log → 12. Learn

## Policy Pack Structure

```
policy-pack/
├── complexity.md      # Complexity classification
├── conventions.md    # Coding standards
├── commands.md       # Build/test commands
├── review.md         # Review criteria
├── escalation.md     # Escalation bounds
├── model-routing.md  # Model selection
├── skills.md         # Skill routing
└── task-tracking.md  # Task manifest
```

## Learn More

See [DESIGN.md](./DESIGN.md) for full specification.
```

- [ ] **Step 2: Create docs/core-policy-interface-mapping.md**

```markdown
# Core Policy Interface Mapping

This file is auto-generated by --init validation. It shows how policy pack files map to engine required inputs.

## Mapping Table

| Phase | Required Input | Policy File | Status |
|-------|---------------|-------------|--------|
| Route | complexity_triggers | complexity.md | ✓ |
| Build | build_commands | commands.md | ✓ |
| ... | ... | ... | ... |

## Validation

Run `sarathi validate ./policy-pack` to check coverage.
```

- [ ] **Step 3: Commit**

```bash
git add Sarathi/README.md Sarathi/docs/
git commit -m "docs: add Sarathi README and docs"
```

---

## Summary

**Deliverables:**
- Engine core files (workflow.md, required-list.md, config.md)
- Policy pack templates (TEMPLATE + EXAMPLE)
- Reference implementation (Python)
- CLI entry points
- Documentation

**Next Steps:**
1. Populate policy-pack/EXAMPLE with realistic content
2. Implement actual agent dispatch integrations
3. Build out skill-evolve pattern detection
4. Create first real policy pack for a specific project