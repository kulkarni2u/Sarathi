# Sarathi Implementation Plan

**Status:** Active  
**Last Updated:** April 23, 2026  
**Planning Horizon:** `v0.3` foundation, `v0.4-v0.6` platform hardening, `v1.0` orchestration release

## Objective

Turn Sarathi from a working policy-backed lifecycle runner into a fully realized orchestration platform:

- phases execute through real runtime adapters, not only host-agent checklists
- policy packs are executable contracts, not just markdown guidance
- tasks can fan out, block, resume, and converge
- verification and review produce replayable evidence artifacts
- learn/evolve improves future runs from actual outcomes

## Current Baseline

What already works in the current codebase:

- CLI commands exist for `init`, `validate`, `run`, `list`, `log`, `status`, `resume`, `proposals`, and `agents`
- the engine executes the 12-phase loop end-to-end
- phase handlers exist for every phase
- task state and phase logs persist under `.sarathi/tasks`
- structured phase artifacts persist separately from task summaries
- policy-pack markdown is loaded, compiled, and semantically validated for the current runtime seams
- dispatcher/provider abstractions exist with local deterministic, configurable deterministic, and command-backed provider paths
- graph-aware execution persists graph state, dispatches child work units through a reusable scheduler, and supports paused/resumed work
- verify/review emit structured evidence, escalation bundles, bounded recovery artifacts, and real spec/diff review inputs
- learn/evolve stores structured learning records, generates policy proposals, supports proposal accept/reject review, and feeds accepted proposal feedback into retry policy
- baseline tests pass locally

What is still missing:

- live hosted provider adapters for non-local model/tool backends
- richer file-level review annotations over full diffs

## Guiding Principles

1. Every phase must emit machine-readable artifacts.
2. Every policy rule that matters must be enforceable at runtime.
3. Every escalation must preserve enough state to resume work later.
4. The engine should orchestrate; phase modules should implement behavior; providers should stay replaceable.
5. Human-readable markdown remains a source format, but runtime uses typed compiled policies.

## Target Architecture

### Proposed module layout

```text
src/
  cli.py
  core/
    engine.py
    models.py
    state.py
    persistence.py
    task_graph.py
  policy/
    loader.py
    schema.py
    compiler.py
    validator.py
  runtime/
    dispatch/
      base.py
      explore.py
      execute.py
    providers/
      base.py
      openai.py
      anthropic.py
      local.py
    commands.py
    artifacts.py
    retries.py
  phases/
    route.py
    brainstorm.py
    planning_advisor.py
    plan.py
    build.py
    verify.py
    review.py
    task_tracking.py
    risk_check.py
    elegance.py
    phase_log.py
    learn.py
  learn/
    store.py
    analyzer.py
    proposer.py
```

### Core runtime contracts

```python
@dataclass
class DispatchRequest:
    mode: Literal["explore", "execute"]
    task_id: str
    phase: str
    prompt: str
    inputs: dict[str, Any]
    expected_outputs: list[str]
    constraints: dict[str, Any]
    timeout_seconds: int
    retry_budget: int

@dataclass
class DispatchResponse:
    success: bool
    outputs: dict[str, Any]
    evidence: dict[str, Any]
    artifacts: dict[str, Any]
    raw_transcript_ref: str | None = None
    error: str | None = None

@dataclass
class GateResult:
    passed: bool
    score: float
    threshold: float
    missing_evidence: list[str]
    decision: Literal["pass", "retry", "escalate", "fail"]
```

## Milestones

## Milestone 1: Runtime Core (`v0.3`)

### Goal

Replace checklist-style execution with real runtime dispatch while preserving the existing CLI and lifecycle behavior.

### Scope

- move phase handlers out of `src/engine.py`
- define request/response contracts for explore and execute modes
- implement real dispatcher classes
- add a provider abstraction with one working backend first
- persist phase artifacts separately from task summaries

### Code changes

- split [src/engine.py](/Users/sweethome/Work/Skills/Sarathi/src/engine.py:798) into `src/core/engine.py` and `src/phases/*`
- replace [src/dispatch.py](/Users/sweethome/Work/Skills/Sarathi/src/dispatch.py:1) with real dispatch interfaces and implementations
- introduce `runtime/artifacts.py` for storing per-phase outputs, logs, and evidence blobs

### Deliverables

- `ExploreDispatcher`
- `ExecuteDispatcher`
- `ProviderAdapter` base class
- one concrete provider adapter
- per-phase artifact persistence
- integration tests for dispatcher-backed phases

### Exit criteria

- `Brainstorm`, `Plan`, and `Review` can execute through a dispatcher
- failure paths produce structured errors rather than generic `fail`
- phase artifacts are persisted and retrievable by task and phase
- existing CLI commands still work

### Suggested tasks

- [ ] extract `PhaseHandler` classes into dedicated modules
- [ ] add typed `DispatchRequest` and `DispatchResponse`
- [ ] implement `NullDispatcher` as test-only fallback
- [ ] implement one real provider-backed explore path
- [ ] implement one real provider-backed execute path
- [ ] add artifact references to `PhaseResult`
- [ ] add tests for success, timeout, and provider failure

## Milestone 2: Executable Policy (`v0.3`)

### Goal

Turn policy-pack markdown into typed runtime policy objects with schema and semantic validation.

### Scope

- parse markdown and YAML into normalized policy models
- validate required fields, types, and allowed values
- compile cross-file policy into phase-ready structures
- wire gate evaluation and skip rules to compiled policy

### Code changes

- replace [src/validate.py](/Users/sweethome/Work/Skills/Sarathi/src/validate.py:23) with schema-driven validation
- move policy loading out of the engine loader at [src/engine.py](/Users/sweethome/Work/Skills/Sarathi/src/engine.py:819)
- add `policy/compiler.py` to merge per-file policy into phase-specific views

### Deliverables

- typed policy models
- policy schema validator
- semantic validator for inconsistent or incomplete packs
- compiled policy pack object
- richer `sarathi validate` output

### Exit criteria

- invalid policy packs fail with actionable messages
- skip rules come from compiled policy, not hardcoded fallback alone
- gates use policy-provided thresholds and evidence requirements
- `DRIFT` is backed by real semantic comparison logic

### Suggested tasks

- [ ] define data models for complexity, commands, review, escalation, tracking, and routing
- [ ] implement markdown loader with YAML extraction and fallback rules
- [ ] implement semantic checks for missing evidence weights, bad thresholds, unknown phase names
- [ ] update `sarathi init` output to satisfy schema by default
- [ ] add tests for valid, incomplete, and contradictory policy packs

## Milestone 3: Task Graph Orchestration (`v0.4`)

### Goal

Move from a single linear run loop to a dependency-aware task graph with resumability.

### Scope

- introduce child tasks and dependency edges
- support blocked, waiting, running, complete, failed states
- allow sibling tasks to continue when one branch blocks
- add resume, cancel, and status inspection

### Code changes

- evolve [run_task()](/Users/sweethome/Work/Skills/Sarathi/src/engine.py:896) into graph execution
- extend [PersistenceManager](/Users/sweethome/Work/Skills/Sarathi/src/engine.py:665) into graph-aware persistence
- move task tracking semantics out of checklist-only phase behavior

### Deliverables

- task graph model
- scheduler/state transition rules
- resumable persistence format
- CLI support for `status`, `resume`, and `cancel`

### Exit criteria

- high-complexity tasks can decompose into sub-tasks
- blocked tasks do not stall unrelated branches
- interrupted execution can resume safely from persisted state
- task-tracking phase updates real graph state

### Suggested tasks

- [ ] define `TaskNode`, `TaskEdge`, and graph status enums
- [ ] add dependency manifest artifact from `Plan`
- [ ] implement scheduler rules for ready vs blocked work
- [ ] add graph persistence and migration from current flat task records
- [ ] add CLI commands for graph inspection

## Milestone 4: Operational Build, Verify, and Review (`v0.5`)

### Goal

Replace synthetic verification and lightweight review with operational evidence-based execution.

### Scope

- run declared commands and capture structured outputs
- attach logs, exit codes, test summaries, and coverage to artifacts
- make review consume diffs, specs, and verify outputs
- support bounded auto-fix loops

### Code changes

- extend verification path currently centered in [VerifyHandler](/Users/sweethome/Work/Skills/Sarathi/src/engine.py:283)
- upgrade `ReviewHandler` from score-only logic at [src/engine.py](/Users/sweethome/Work/Skills/Sarathi/src/engine.py:359)
- add artifact-backed escalation bundles

### Deliverables

- command runner with timeouts and log capture
- verify artifact schema
- structured review findings
- escalation bundles containing evidence and context

### Exit criteria

- verify produces replayable evidence from actual commands
- review emits findings and verdicts, not only a numeric score
- auto-fix loops obey retry and severity policy
- `sarathi log` can surface artifact references and summarized evidence

### Suggested tasks

- [ ] add command execution abstraction with stdout/stderr capture
- [ ] store verify results as structured artifacts
- [ ] define review result schema with findings, severity, and evidence refs
- [ ] implement retry policy from escalation rules
- [ ] add tests for flaky command, timeout, and review escalation cases

## Milestone 5: Learn / Evolve Loop (`v0.6`)

### Goal

Make Sarathi measurably improve from historical outcomes while keeping humans in control of policy changes.

### Scope

- persist run histories and phase-level outcomes
- detect repeated failure and success patterns
- propose policy or routing changes
- promote patterns only when thresholds and review gates are met

### Code changes

- expand [src/evolve.py](/Users/sweethome/Work/Skills/Sarathi/src/evolve.py:1) into storage, analysis, and proposal generation
- keep `learnings.md` as human-facing output while storing structured history separately

### Deliverables

- learning store
- pattern analyzer
- proposal generator
- promotion gate implementation
- CLI surfaces for viewing learnings and proposals

### Exit criteria

- repeated failure modes are surfaced from run history
- validated patterns can be proposed for promotion
- model routing and policy suggestions can reference historical evidence
- learn/evolve is no longer a stubbed summary phase

### Suggested tasks

- [ ] define structured run history store
- [ ] record phase outcomes, retries, escalations, and artifacts used
- [ ] implement pattern scoring and trend tracking
- [ ] generate policy update proposals instead of auto-mutating policy
- [ ] add review flow for accepting or rejecting proposals

## Milestone 6: Productization And Integrations (`v1.0`)

### Goal

Ship Sarathi as a stable orchestration product that different agent surfaces can use consistently.

### Scope

- stable public runtime and policy interfaces
- first-class support for skill-pack consumers
- stronger observability, docs, and upgrade paths
- compatibility guarantees for policy-pack schema

### Deliverables

- public architecture docs
- migration guide for policy-pack changes
- stable provider adapter interface
- integration guidance for Copilot, Codex, Claude, and Cursor
- packaged `Sarathi-Skill` alignment with runtime contracts

### Exit criteria

- `Sarathi-Skill` docs match actual runtime behavior
- platform integrations are documented against a stable API
- users can adopt Sarathi without reading the source to infer behavior

## Cross-Cutting Workstreams

### Testing

- unit tests for policy, dispatch, scheduling, and evolution logic
- integration tests for real phase execution paths
- CLI tests for `run`, `validate`, `list`, `log`, `status`, and `resume`
- fixture policy-packs for valid, partial, and invalid cases

### Observability

- per-phase timing and retry metrics
- artifact IDs and correlation IDs per task
- structured logs for dispatch requests, retries, escalations, and resumes

### Backward Compatibility

- keep current CLI surface working during internal refactors
- provide migration path from current `.sarathi/tasks/*.json`
- preserve markdown policy-pack authoring experience

## Recommended Execution Order

1. Runtime core
2. Executable policy
3. Task graph orchestration
4. Operational verify/review
5. Learn/evolve
6. Productization and skill-pack alignment

This order keeps the foundation stable: first make phases real, then make policy enforceable, then add orchestration depth, then add operational quality loops, and only then freeze product boundaries.

## Immediate Next Sprint

### Sprint objective

Create the next platform-ready quality loop: evidence-backed review and escalation bundles that consume build, graph, and verify artifacts.

### Sprint backlog

- [x] extract phase handlers into `src/phases/`
- [x] add `DispatchRequest`, `DispatchResponse`, and `GateResult`
- [x] wire engine to compiled policy and typed policy sections
- [x] add provider abstraction and local provider path
- [x] persist phase artifacts outside the summary task JSON
- [x] add policy-driven graph execution controls
- [x] make review consume build, graph, and verify artifacts directly
- [x] add artifact-backed escalation bundles for failed or waiting-human work
- [x] add bounded retry/autofix policy hooks for verify and review output
- [x] expose escalation bundle summaries through `sarathi log` or `sarathi status`
- [x] turn retry/autofix policy hooks into executable bounded recovery actions
- [x] add direct links from escalation summaries to exact artifact files
- [x] add configurable deterministic provider routing from model-routing policy
- [x] add policy proposal generation and CLI proposal viewing from learnings
- [x] connect recovery actions to provider-backed recovery-fix dispatch
- [x] add human review flow for accepting/rejecting policy proposals
- [x] feed accepted proposal feedback into retry strategy
- [x] add reusable scheduler API outside the build handler
- [x] add command-backed provider adapter
- [x] add schema validation for provider routing policy

### Sprint exit criteria

- review verdicts reference concrete build/verify evidence
- failed or waiting-human graph work emits a durable escalation bundle
- retry/autofix decisions are policy-controlled rather than hardcoded
- escalation summaries can be inspected without reading raw task JSON
- retry/autofix recommendations execute bounded recovery actions
- next sprint: live hosted providers and richer file-level review annotations

## Definition Of Done For The Platform

Sarathi becomes a fully realized orchestration platform when all of the following are true:

- phases execute through runtime adapters and emit structured artifacts
- policy packs compile into validated runtime contracts
- tasks can split, block, resume, and converge
- verify and review consume and emit evidence, not just summaries
- learn/evolve uses historical data to improve routing and policy proposals
- external agent surfaces can integrate through stable interfaces rather than custom glue
