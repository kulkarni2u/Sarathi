# Sarathi Engine Workflow

## Overview

Sarathi is a generic, tool-agnostic workflow orchestration framework. The engine defines HOW to deliver (not what to build). Policy packs provide domain knowledge.

## Phase Lifecycle Model

Every task moves through 12 phases in sequence. Each phase has:
- **Entry Gate**: Prerequisites that must be satisfied before phase begins
- **Exit Gate**: Evidence that must be collected before phase completes
- **Methods**: Available approaches for completing phase work
- **Outputs**: Artifacts produced by the phase

## Sub-Agent Dispatch Model

### Explore vs Execute Modes

| Mode | Purpose | Model Requirements | Typical Use |
|------|---------|---------------------|-------------|
| **Explore** | Discovery, brainstorming, options analysis | High creativity, low latency tolerance, larger context window | Route, Brainstorm, PlanningAdvisor |
| **Execute** | Implementation, verification, production | High reliability, low latency, focused output | Build, Verify, Review |

### Model Selection Criteria

1. **Task complexity**: Simple tasks → smaller models, complex tasks → frontier models
2. **Context requirements**: Long context needs → models with larger windows
3. **Latency requirements**: Interactive → fast models, background → slower capable models
4. **Creativity vs precision**: Creative tasks → reasoning models, precision tasks → fast models

## Phase Transition Rules

1. A phase must PASS its exit gate before transitioning to next phase
2. If exit gate shows DRIFT, the phase must re-execute with corrections
3. If exit gate shows BLOCKED, escalate to human review
4. Parallel phases may execute concurrently when independence is confirmed

---

## Phase 1: Route

**Purpose**: Classify the incoming task and select the appropriate workflow path.

### Entry Gate
- Task description available
- Policy pack loaded (optional but recommended)

### Exit Gate
- Task type classification (feature/bug/refactor/docs/deploy)
- Workflow path selected (full/accelerated/minimal)
- Initial model recommendation

### Methods
- `classify_task()`: Analyze task description against known patterns
- `check_policy()`: Consult policy pack for routing guidance
- `recommend_path()`: Select workflow path based on classification

### Required Evidence
- Classification confidence score (>0.7 for full path, >0.5 for accelerated)
- Policy pack consulted (yes/no)

### Outputs
- Task classification document
- Workflow path selection
- Model recommendation

---

## Phase 2: Brainstorm

**Purpose**: Explore multiple approaches before committing to a solution.

### Entry Gate
- Task classification from Route
- Policy pack context (if available)

### Exit Gate
- At least 2 distinct approaches identified
- Each approach has pros/cons documented
- Risks identified for each approach

### Methods
- `generate_approaches()`: Enumerate solution variants
- `analyze_tradeoffs()`: Evaluate approaches against constraints
- `identify_risks()`: Surface potential failure modes

### Required Evidence
- Minimum 2 approaches documented
- Risk assessment for each approach
- Policy pack patterns applied (where relevant)

### Outputs
- Approaches document with tradeoffs
- Risk summary
- Recommendation for approach selection

---

## Phase 3: PlanningAdvisor

**Purpose**: Provide guidance on plan structure and execution strategy.

### Entry Gate
- Task classification
- Brainstorm output (approaches + risks)
- Policy pack loaded

### Exit Gate
- Plan structure recommended
- Phase ordering validated
- Dependencies mapped

### Methods
- `recommend_structure()`: Suggest plan organization
- `validate_dependencies()`: Ensure phase dependencies are satisfied
- `suggest_parallelization()`: Identify phases that can run concurrently

### Required Evidence
- Plan structure documented
- Dependency graph complete
- Parallelization opportunities identified

### Outputs
- Plan structure recommendation
- Dependency map
- Parallelization strategy

---

## Phase 4: Plan

**Purpose**: Create actionable implementation plan with detailed steps.

### Entry Gate
- Selected approach from Brainstorm
- PlanningAdvisor guidance
- Policy pack context

### Exit Gate
- All phases have defined entry/exit criteria
- Tasks are ordered correctly
- Dependencies resolved

### Methods
- `define_phases()`: Create detailed phase definitions
- `sequence_tasks()`: Order tasks by dependency
- `allocate_resources()`: Assign models and tools to tasks

### Required Evidence
- Phase definitions complete
- Task sequence validated
- Resource allocation documented

### Outputs
- Detailed phase plan
- Task sequence
- Resource allocation

---

## Phase 5: Build

**Purpose**: Execute implementation according to plan.

### Entry Gate
- Approved plan
- All dependencies satisfied
- Required tools available

### Exit Gate
- Implementation complete for assigned scope
- Code compiles/runs without errors
- Basic unit tests pass

### Methods
- `implement()`: Write code/features
- `compile_check()`: Verify syntax and structure
- `unit_test()`: Execute basic test suite

### Required Evidence
- Implementation artifacts created
- Compilation/validation successful
- Unit tests executed (passing)

### Outputs
- Implementation artifacts
- Test results
- Build logs

---

## Phase 6: Verify

**Purpose**: Validate implementation against requirements and specifications.

### Entry Gate
- Build output available
- Requirements documentation
- Test specifications

### Exit Gate
- All requirements verified
- Test coverage adequate
- Known issues documented

### Methods
- `verify_requirements()`: Check implementation against spec
- `coverage_check()`: Measure test coverage
- `issue_documentation()`: Record any gaps or problems

### Required Evidence
- Requirements traceability matrix
- Coverage report
- Issue list (if any)

### Outputs
- Verification report
- Coverage metrics
- Issue documentation

---

## Phase 7: Review

**Purpose**: Conduct thorough code/project review for quality and consistency.

### Entry Gate
- Verified implementation
- Review criteria defined
- Reviewer model assigned

### Exit Gate
- Review completed with findings
- All critical issues addressed
- Quality bar met

### Methods
- `conduct_review()`: Execute review process
- `address_findings()`: Fix or document review issues
- `certify_quality()`: Confirm quality bar achieved

### Required Evidence
- Review findings documented
- Critical issues resolved
- Quality certification

### Outputs
- Review report
- Findings resolution log
- Quality certification

---

## Phase 8: TaskTracking

**Purpose**: Monitor progress and maintain visibility into task state.

### Entry Gate
- Active tasks in execution
- Tracking mechanism available

### Exit Gate
- All tasks tracked
- Progress documented
- Blockers identified

### Methods
- `track_progress()`: Update task status
- `identify_blockers()`: Surface obstacles
- `report_status()`: Generate progress reports

### Required Evidence
- Task status log
- Blocker list (if any)
- Progress metrics

### Outputs
- Task status report
- Blocker escalation (if needed)
- Progress metrics

---

## Phase 9: RiskCheck

**Purpose**: Identify and mitigate potential risks before they become issues.

### Entry Gate
- Plan and current state
- Risk assessment criteria
- Historical data (if available)

### Exit Gate
- Risk landscape documented
- Mitigations identified
- Residual risks accepted

### Methods
- `identify_risks()`: Surface potential issues
- `assess_likelihood()`: Evaluate risk probability
- `plan_mitigation()`: Define risk responses

### Required Evidence
- Risk register
- Mitigation plans
- Risk acceptance documentation

### Outputs
- Risk assessment report
- Mitigation action items
- Residual risk log

---

## Phase 10: Elegance

**Purpose**: Evaluate and improve solution quality beyond functional correctness.

### Entry Gate
- Verified implementation
- Quality criteria defined
- Style guides available

### Exit Gate
- Code quality assessment complete
- Refactoring opportunities identified
- Technical debt documented

### Methods
- `assess_quality()`: Evaluate code quality metrics
- `identify_improvements()`: Find refactoring opportunities
- `document_debt()`: Catalog technical debt

### Required Evidence
- Quality metrics
- Refactoring candidates
- Technical debt catalog

### Outputs
- Quality assessment
- Refactoring recommendations
- Technical debt report

---

## Phase 11: PhaseLog

**Purpose**: Document what happened in each phase for audit and learning.

### Entry Gate
- Phase outputs available
- Timestamp and metadata

### Exit Gate
- Complete phase log entries
- Decision rationale documented
- Output artifacts referenced

### Methods
- `log_phase()`: Record phase execution
- `document_decisions()`: Capture decision rationale
- `reference_artifacts()`: Link to output artifacts

### Required Evidence
- Phase timestamps
- Decision log
- Artifact references

### Outputs
- Phase execution log
- Decision documentation
- Artifact index

---

## Phase 12: Learn

**Purpose**: Extract learnings from this execution for future improvement.

### Entry Gate
- Complete phase log
- Outcomes documented
- Baseline template available

### Entry Gate
- Complete phase log
- Outcomes documented
- Baseline template available

### Methods
- `extract_patterns()`: Identify reusable patterns
- `update_baseline()`: Refresh global baseline
- `deprecate_patterns()`: Mark outdated approaches

### Required Evidence
- Pattern extraction complete
- Baseline updated
- Deprecated patterns identified (if any)

### Outputs
- New patterns documented
- Baseline updates
- Deprecation list (if any)

---

## Parallelization Strategy

Independent phases may execute in parallel:
- Route → Brainstorm (sequential)
- Plan → TaskTracking (can parallelize after initial Plan)
- Build → RiskCheck (can run concurrently)
- Verify → Elegance (can run concurrently after Build)

---

## Confidence Gate Thresholds

| Phase | Default Threshold | Rationale |
|-------|-------------------|-----------|
| Route | 0.7 | Classification must be confident |
| Brainstorm | 0.6 | Need multiple approaches |
| PlanningAdvisor | 0.7 | Plan structure must be sound |
| Plan | 0.8 | Implementation depends on plan |
| Build | 0.9 | Must compile/test cleanly |
| Verify | 0.85 | Must meet requirements |
| Review | 0.8 | Quality bar must be met |
| TaskTracking | 0.7 | Progress must be accurate |
| RiskCheck | 0.75 | Risks must be identified |
| Elegance | 0.6 | Quality improvements are additive |
| PhaseLog | 0.9 | Documentation must be complete |
| Learn | 0.8 | Learnings must be accurate |

---

## Version

1.0.0