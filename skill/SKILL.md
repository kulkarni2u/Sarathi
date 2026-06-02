---
name: sarathi
description: "Generic workflow orchestration framework - policy-backed lifecycle (Route → Brainstorm → Plan → Build → Verify → Review → etc.) with sub-agent dispatch, learn-evolve loop, and model selection. Use when building complex tasks that need systematic execution."
---

# Sarathi - Workflow Orchestration Framework

A generic, tool-agnostic workflow orchestration framework for AI agents. Defines a canonical delivery model that policy-backed workflows inherit.

## Use anywhere (Cursor · Claude · Copilot · Codex · OpenCode)

1. **Install the CLI** (same on every machine): from the Sarathi repo run `python3 -m pip install -e .` or install a built wheel. This gives you `sarathi init`, `validate`, `run`, `list`, and `log`.
2. **Start the local service** — no token needed for local connections:
   ```bash
   python3 -m src.service --db ~/.sarathi/sarathi.db --port 8765
   ```
   The service writes `~/.sarathi/service.json` on start. No token configuration required for local connections.
3. **Attach this skill to your agent**: copy this folder (or symlink it) into the skills directory your product expects, then invoke the skill when you want the Sarathi lifecycle.
   - **Cursor**: project `.cursor/skills/sarathi/SKILL.md` (or your global skills path).
   - **Claude Code / Claude plugins**: project `.claude/skills/sarathi/SKILL.md` or `~/.claude/skills/…`.
   - **GitHub Copilot (agent mode)**: merge the workflow into repo `AGENTS.md` / agent instructions, or your org's skill bundle location. Use this repo's `skill/SKILL.md` as the Copilot skill entry and register the agent in this repo's `AGENTS.md` for repo-local discovery.
   - **OpenAI Codex CLI**: `~/.codex/skills/sarathi/SKILL.md` or workspace `.codex/skills/sarathi/SKILL.md`.
   - **OpenCode**: `~/.opencode/skills/sarathi/SKILL.md` or workspace `.opencode/skills/sarathi/SKILL.md`.

## GitHub Copilot integration

To add Sarathi to Copilot agent mode:
1. Install Sarathi from the `Sarathi/` folder in the environment Copilot uses.
2. Add `skill/SKILL.md` to your Copilot skills directory, shared skill bundle, or global Copilot skills directory.
   - For repo-local use: place the skill under the repo's Copilot skills path.
   - For org-wide use: add the skill to your shared agent bundle.
   - For global Copilot use: symlink or copy `skill/` into your global Copilot skills directory.
3. Register the Sarathi agent in `AGENTS.md` using the repo-local entry or your Copilot agent registry.

Use `--ncp` when the task would benefit from NCP-backed context management.

### Global Copilot install example

```bash
git clone https://github.com/kulkarni2u/Sarathi.git
cd Sarathi
python3 -m pip install -e .
# symlink skill/ into your global Copilot skills directory
ln -s "$(pwd)/skill" "$HOME/.copilot/skills/sarathi"
```

Example agent entry
```yaml
- name: sarathi
  description: "Sarathi workflow orchestration for complex development tasks."
  trigger:
    when: "the task requires a structured planning, build, verify, review, and learn workflow"
  command: |
    cd /path/to/Sarathi
    sarathi run "{{task_description}}" --policy-pack ./policy-pack --dry-run [--ncp] [--ncp-mode direct|mcp] [--ncp-router]
```

3. **Know the split**: `sarathi run` drives the **orchestration graph**, persists tasks under `.sarathi/tasks/`, and emits phase artifacts. Phases whose artifacts include `"execution_surface": "host_agent"` are **checklists for the model in the IDE**—they are not hidden subprocesses. Optional live test execution: set `SARATHI_EXEC_COMMANDS=1` (see Sarathi `README.md`).
4. **Policy source of truth**: keep a single `policy-pack/` per repo (from `sarathi init .`). The duplicate `policy-pack/` in this skill folder is a **template** only; prefer the pack Sarathi generated in your project.

## When to Use

Use `/sarathi` when:
- Building features that need systematic execution
- Tasks require complex multi-phase workflows
- Need sub-agent orchestration with explore/execute dispatch
- Want learn-evolve to improve over time
- Need policy-driven complexity routing

## Quick Start

```bash
# Initialize a new project with policy pack
sarathi init ./my-project

# Validate existing policy pack
sarathi validate ./my-project/policy-pack

# Run a task through the lifecycle
sarathi run "Add user authentication" --policy-pack ./my-project/policy-pack

# Dry run to see phases without executing
sarathi run "Add user authentication" --policy-pack ./my-project/policy-pack --dry-run

# Specify complexity override
sarathi run "Fix critical bug" --policy-pack ./policy-pack --complexity high
```

## The 12-Phase Lifecycle

| Phase | Purpose | Gate | Skipped for |
|-------|---------|------|-------------|
| Route | Classify complexity (Low/Medium/High) | - | - |
| Brainstorm | Provider-driven dialogue → approved spec with self-review | Hard gate: spec approved | - |
| PlanningAdvisor | High-complexity only | - | LOW, MEDIUM |
| Plan | TDD-structured checkpoint list, no placeholders | 90% confidence | - |
| Build | TDD iron law: test-first, red-green-refactor | Hard TDD default | - |
| Verify | Auto-fix loop with systematic debugging escalation | Budget+severity | - |
| Review | Two-stage: spec compliance then code quality | 5-round hard stop (Stage 2) | - |
| TaskTracking | Blocked sub-agent protocol | Non-blocking siblings | - |
| RiskCheck | Devil's advocate | Non-blocking | - |
| Elegance | Pre-build clean | Auto-fix attempt | - |
| PhaseLog | Audit trail | Tabular | - |
| Learn | Post-flight introspection | >= 80% + >= best | - |

## Complexity Classification

### Low Complexity
- Single file change
- Bug fix with clear root cause
- Documentation update
- Simple refactor (rename, reformat)
- **Skips**: PlanningAdvisor phase

### Medium Complexity
- Multiple files (2-10)
- New feature with clear scope
- Dependency update
- **Skips**: PlanningAdvisor phase

### High Complexity
- Cross-cutting concern
- Architectural change
- Security-sensitive code
- Performance-critical code
- **Full lifecycle**: All phases executed

## Sub-Agent Dispatch

**Explore mode** (Brainstorm, PlanningAdvisor, RiskCheck):
- Mentor/apprentice model
- Rich Q&A interface
- Persistent context
- Can push clarifying questions back

**Execute mode** (Plan, Build, Verify, Review):
- Task-framing model
- Structured task objects (id, inputs, outputs, contextRef)
- Stateless-ish, returns artifacts
- Clear contracts

## Agent Role Names

Sarathi uses a concise Sanskrit-inspired naming system for agent roles and orchestration concepts:

| Role | Name |
|------|------|
| Orchestrator | Sarathi |
| Planner | Disha |
| Researcher | Vichara |
| Reasoner | Prajna |
| Executor | Pravaha |
| Reviewer/validator | Nirnaya |
| Coordinator | Samanvaya |
| Support | Sahayaka |
| Router | Marga |
| Workflow spine/message bus | Sutra |

## Policy Pack

Sarathi is driven by policy packs in the workspace:

```
policy-pack/
├── complexity.md      # Complexity triggers
├── conventions.md    # Coding standards + evidence requirements
├── commands.md       # Build/test commands
├── review.md         # Review criteria
├── escalation.md     # Budget + severity thresholds
├── model-routing.md  # Model selection
├── skills.md         # Skill routing
└── task-tracking.md  # Task manifest
```

### Initialize Policy Pack

```bash
sarathi init ./my-project
```

This creates a `policy-pack/` directory with template files for all required policies.

## Phase Log Format

CLI and JSON persistence use machine outcomes: `pass`, `skip`, `fail`, `escalate`. In prose you can describe those as "completed" when `pass` or non-blocking `escalate`.

```
| Phase              | Outcome (engine) | Iterations |
|--------------------|------------------|------------|
| Route              | pass             | 0          |
| Brainstorm         | pass             | 0          |
| Plan               | pass             | 0          |
| Build              | pass             | 0          |
| Verify             | pass             | 0          |
| Review             | pass             | 0          |
| TaskTracking       | pass             | 0          |
| RiskCheck          | pass             | 0          |
| Elegance           | pass             | 0          |
| PhaseLog           | pass             | 0          |
| Learn              | pass             | 0          |
```

## Evidence-Weighted Gates

Evidence requirements and weights for phase gates:

### Brainstorm Phase — Structured Dialogue

Every task starts here. No Plan, no Build until an approved spec exists.
This phase is conducted by the configured provider — the process is identical
regardless of which provider is active (Claude, Codex, OpenCode, Copilot, or custom).

**Process:**

1. **Research first** — before asking the user anything, dispatch Explore sub-agents:
   - Vichara: scan relevant files, existing patterns, prior decisions
   - Marga: classify complexity, identify affected surfaces
   - POST findings to `/api/brainstorm/:id/research`

2. **One question at a time** — informed by research, not abstract:
   - Multiple choice preferred when options are enumerable
   - Never ask what the code already answers
   - Never ask two questions in one message

3. **Propose 2-3 approaches** with tradeoffs, lead with recommendation

4. **Build spec live** — POST `spec_update` with each turn:
   - Goal, constraints, success criteria
   - Chosen approach + rationale
   - Explicit out-of-scope
   - Risks identified

5. **Spec Self-Review (mandatory before hard gate)**
   After the spec draft is complete, scan it before advancing to the gate:
   - **Placeholder scan**: any TBD, TODO, or incomplete sections? Fix inline.
   - **Internal consistency**: do sections contradict each other? Does the architecture match the feature descriptions?
   - **Scope check**: is this one focused spec, or should it decompose into sub-specs? If the request covers multiple independent subsystems, decompose first.
   - **Ambiguity check**: can any requirement be read two different ways? Pick one interpretation, make it explicit.
   Fix all issues inline before proceeding. No re-review needed — just fix and move on.

6. **Hard gate** — no transition to Plan until:
   - All four evidence dimensions covered in spec
   - Spec self-review passed (no unresolved issues)
   - User approves (terminal `y`)
   - `POST /api/brainstorm/:id/approve` returns `{ session, task }`
   - Task record exists in SQLite

**Evidence dimensions (auto-checked, weights):**
| Evidence | Weight |
|----------|--------|
| alternative_approaches_considered | 0.3 |
| risks_identified | 0.3 |
| success_criteria_defined | 0.2 |
| reversibility_assessed | 0.2 |

Confidence must reach 0.9 before phase passes.

**Output:**
- Spec: `.sarathi/brainstorm/<id>/spec.md`
- Task: SQLite `tasks` table, linked via `brainstorm_session_id`
- Export to docs/: offered, never forced

**Provider contract:** The provider receives a `brainstorm_turn` payload
(context + evidence coverage + dialogue so far) and returns
`{ question, options?, spec_update }`. The provider does not need to know
it is inside a Sarathi lifecycle.

### Plan Phase — Spec-Driven Checkpoint List

The Plan phase reads the approved brainstorm spec as its input before generating
the checkpoint list. The spec is available at `.sarathi/brainstorm/<id>/spec.md`
and the session id is in `task.metadata.brainstorm_session_id`.

**Process:**
1. Load the spec from `.sarathi/brainstorm/<id>/spec.md`
2. Map out which files will be created or modified and what each is responsible for — lock in decomposition decisions before writing tasks. Each file should have one clear responsibility.
3. Derive the checkpoint list directly from the spec's Goal, Approach, and Out-of-scope sections
4. Build the dependency map from the spec's constraints and risks
5. Define the rollback plan based on the spec's reversibility assessment

The checkpoint list is not invented from scratch — it is a translation of the approved spec into executable steps.

**No-Placeholders Policy (plan gate failure if violated)**

These patterns are plan failures — never write them:
- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "add validation" / "handle edge cases" (without exact code)
- "Write tests for the above" (without actual test code)
- "Similar to Task N" — repeat the code; the executor may read tasks out of order
- Steps that describe what to do without showing how (code blocks required for all code steps)

**Each checkpoint step must follow TDD format:**

```
- [ ] Write failing test: [exact test code]
- [ ] Run test, verify it fails: [exact command] → expected: FAIL with "[reason]"
- [ ] Implement minimal code: [exact implementation — no more than needed to pass]
- [ ] Run test, verify it passes: [exact command] → expected: PASS
- [ ] Commit: git commit -m "[message]"
```

Exact file paths always. Complete code in every step. Exact commands with expected output.

**Type/Signature Consistency Check (before plan gate)**

After writing the full checkpoint list, scan across all tasks:
- Function/method names used in later tasks match definitions in earlier tasks
- Type signatures are consistent throughout
- No forward references to undefined types or functions
Fix any gaps inline before submitting to the plan gate.

### Plan Gate (90% confidence)
| Evidence | Weight |
|----------|--------|
| checkpoint_list | 0.35 |
| dependency_map | 0.25 |
| rollback_plan | 0.20 |
| no_placeholder_check | 0.10 |
| type_consistency_check | 0.10 |

### Build Phase — TDD Iron Law

Pravaha (executor) operates under this non-negotiable rule:

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

**Red-Green-Refactor cycle (mandatory for every unit of work):**

1. **RED** — Write one failing test for the target behavior. Run it. Confirm it fails for the right reason (feature missing, not a syntax error or typo). If it passes immediately, the test is wrong — fix it.
2. **GREEN** — Write the minimum code to make the test pass. Nothing more. No extra features, no refactoring other code.
3. **VERIFY GREEN** — Run the test. Confirm it passes. Confirm no other tests broke.
4. **REFACTOR** — Clean up only. No new behavior. Keep tests green. Run tests again after refactoring.
5. **Repeat** for the next behavior.

**If code was written before the test: delete it. Start over with the test. No exceptions.**

Red flags — stop and restart with TDD:
- Code exists before a failing test was written
- Test passes immediately on first run (proves it tests nothing)
- "I'll add tests after" — no
- "This is too simple to test" — no
- "I already manually tested it" — no
- "Tests after achieve the same goals" — no. Tests-after answer "what does this do?" Tests-first answer "what should this do?"
- "Keep as reference while writing the test" — no. Delete means delete.

### Verify Phase — Auto-Fix Loop with Systematic Debugging Escalation

Nirnaya runs the auto-fix loop bounded by the budget and severity thresholds in `policy-pack/escalation.md`.

**Systematic Debugging Escalation:**

When fix iterations ≥ 3 with no progress on the same failure, **stop the fix loop**. Root cause investigation is required before the next fix attempt:

1. Read error messages completely — full stack traces, don't skim past them
2. Reproduce the failure consistently before proposing fixes
3. Check what changed (git diff, recent commits, env differences) that could cause this
4. In multi-component systems: add diagnostic instrumentation at each component boundary to find WHERE it breaks before deciding HOW to fix:
   ```
   For each component boundary:
     - Log what data enters the component
     - Log what data exits the component
     - Verify environment/config propagation at each layer
   Run once to gather evidence → find the failing boundary → investigate that boundary
   ```
5. Form one specific hypothesis: "X is the root cause because Y" — write it down
6. Test minimally — one variable at a time. Make the smallest possible change to test the hypothesis.
7. If hypothesis fails: form a new one. Do not stack multiple fixes at once.
8. If 5+ iterations with no progress: this is likely an architectural problem, not a fixable symptom. Escalate to the user — present the pattern of failures and ask whether to rethink the approach.

**Verification Before Claiming Pass:**

Nirnaya must not claim Verify passed without fresh evidence. Before stating any completion or success:

```
1. IDENTIFY: What exact command proves this claim?
2. RUN: Execute the full command now (fresh run, complete output)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does the output confirm the claim?
5. ONLY THEN: State the result, quoting the evidence
```

Forbidden before running verification: "should pass", "probably works", "seems to", "looks good", "Done!", "Perfect!", "Great!" — any wording implying success without having run the check is a verification failure.

### Review Phase — Two-Stage Gate

**Stage 1: Spec Compliance (must pass before Stage 2)**

Nirnaya checks the implementation against the approved spec at `.sarathi/brainstorm/<id>/spec.md`:
- **No under-building**: every spec requirement has a corresponding implementation — point to it by file and line
- **No over-building**: no features added beyond what the spec specifies
- Produce a line-by-line spec coverage checklist as evidence

Stage 1 must pass before Stage 2 begins. If it fails: Pravaha fixes the gaps, then Stage 1 re-runs. Spec compliance failures do **not** count against the 5-round review clock.

**Stage 2: Code Quality**

After spec compliance is confirmed:
- Code structure, naming, readability
- Test coverage and quality (are the right things tested?)
- Error handling (at system boundaries only — no defensive code for impossible cases)
- No unnecessary complexity
- Evidence required: quality review summary with specific findings

The 5-round hard stop applies to Stage 2 only. Post-hard-stop options:
1. **force_approve** — Accept current state
2. **request_changes** — Iterate with specific feedback
3. **abort** — Abandon task
4. **delegate_to_agent** — Let AI resolve remaining issues

### Provider Contracts

All three provider modes use the same structured turn protocol. The provider does
not need to know it is inside a Sarathi lifecycle — the skill instructs the process.

**brainstorm_turn** (Brainstorm phase):
```json
// Receives:
{ "mode": "brainstorm_turn", "context": { "title": "...", "research_findings": [...],
  "dialogue_so_far": [...], "spec_draft": "...", "evidence_coverage": {...} },
  "instructions": "Ask one question. Multiple choice if enumerable. Update spec draft." }
// Returns:
{ "question": "...", "options": ["A", "B", "C"], "spec_update": "## Approach\n..." }
```

**explore** (PlanningAdvisor, RiskCheck sub-agents — Vichara, Marga roles):
```json
// Receives:
{ "mode": "explore", "task_id": "...", "phase": "brainstorm",
  "prompt": "Research the existing auth patterns in this codebase",
  "inputs": { "task_description": "...", "complexity": "medium" },
  "expected_outputs": ["findings", "refs", "risks"],
  "ncp_context": { "agent_id": "vichara", "prior_refs": [], "layer": "episodic" } }
// Returns:
{ "findings": ["Existing sessions in src/auth.py:42"], "refs": ["src/auth.py:42"],
  "risks": ["Session migration required"], "success": true }
```

**execute** (Plan, Build, Verify, Review — Pravaha, Nirnaya roles):
```json
// Receives:
{ "mode": "execute", "task_id": "...", "phase": "build",
  "task_packet": { "goal": "...", "context": "...", "review_criteria": ["..."] },
  "inputs": { "spec_path": ".sarathi/brainstorm/<id>/spec.md" },
  "ncp_context": { "agent_id": "pravaha", "prior_refs": ["<plan-ref>"], "layer": "episodic" } }
// Returns:
{ "artifact": "path/to/output", "evidence": { "tests_passed": true, "coverage": 0.85 },
  "success": true, "usage": { "input_tokens": 1200, "output_tokens": 800 } }
```

## NCP Context Spine

When `--ncp` is active (or NCP is available via `.ncp/run.py`), each phase reads prior context and writes its outcomes to NCP. This is the cross-phase memory that makes multi-session and multi-subagent runs coherent — without it, each phase starts cold.

**Phase read/write contract:**

| Phase | Read from NCP | Write to NCP |
|-------|--------------|-------------|
| Brainstorm start | prior task patterns (semantic) | — |
| Brainstorm end | — | spec → semantic; research findings → episodic |
| Plan start | spec from Brainstorm (semantic) | — |
| Plan end | — | checkpoint list + dependency map → semantic |
| Build (per task, start) | plan checkpoint (semantic) | — |
| Build (per task, end) | — | build evidence + test results → episodic |
| Verify start | build evidence (episodic) | — |
| Verify end | — | failure patterns → procedural (if failures occurred) |
| Review start | spec + build evidence | — |
| Review end | — | review findings → episodic |
| Learn end | — | learnings → procedural; full phase log → semantic |

### Pre-Dispatch Spec Seeding (mandatory before any Execute dispatch)

Before dispatching any Pravaha (execute-mode) subagent, the orchestrator MUST write the task spec to NCP:

```bash
python3 .ncp/run.py write_memory '{
  "content": "<full structured spec — file paths, interfaces, acceptance criteria, TDD steps>",
  "layer": "semantic",
  "src": "agent_inferred",
  "written_by": "sarathi",
  "pipeline_id": "<task-slug>"
}'
```

The spec content must be retrievable: include the task slug, file names, function signatures, and acceptance criteria verbatim so BM25 retrieval surfaces it when the subagent queries with the task name.

**Dispatch instruction template (5-8 lines only):**

```
Work in <repo-path> on branch <branch>.

FIRST: python3 .ncp/run.py get_context '{"agent_id":"pravaha","role":"pravaha","task":"<task-slug>","slot":"build","intent":"<one-phrase-intent>"}'

Read the files named in your context. Implement the spec. Follow TDD: test first.
Run: python3 -m pytest -q after each change.

LAST: python3 .ncp/run.py write_memory '{"content":"<summary>","layer":"episodic","src":"tool_result","written_by":"pravaha"}'
```

**Self-check before dispatching any subagent:**
- [ ] Has the full spec been written to NCP with `write_memory` (not just a one-line summary)?
- [ ] Is the dispatch instruction ≤ 10 lines?
- [ ] Does it contain only: working dir, branch, `get_context` call, "implement per context", test command, `write_memory` call?
- [ ] Does it NOT include file lists, code templates, interfaces, or TDD steps (those are in NCP)?

If any box is unchecked — seed NCP with the full spec first, then rewrite the dispatch instruction.

**Every dispatched subagent (Vichara, Pravaha, Nirnaya, etc.) must:**

**THIS IS A HARD REQUIREMENT — not optional documentation. If you are constructing
an instruction for `ncp handoff opencode`, `codex exec`, or any external agent,
you MUST include both calls verbatim in the instruction text you write. Skipping
them means the subagent starts cold and its findings are lost on compaction.**

Start of turn — prepend to every instruction:
```bash
First run: .ncp/run.py get_context '{"agent_id":"<role>","role":"<role>","task":"<phase-task>","slot":"build","intent":"<phase-goal>"}'
```

End of turn — append to every instruction:
```bash
When done run: .ncp/run.py write_memory '{"content":"<one_sentence_summary>","layer":"episodic","src":"tool_result","written_by":"<role>"}'
```

**Self-check before sending any handoff instruction:**
- [ ] Does the instruction start with a `.ncp/run.py get_context` call?
- [ ] Does the instruction end with a `.ncp/run.py write_memory` call?
- [ ] Are agent_id, role, task, and intent filled in (not left as `<placeholders>`)?
- [ ] Was the full spec written to NCP **before** this dispatch (not a one-liner summary)?

If any box is unchecked — rewrite the instruction before dispatching.

All execute-mode and explore-mode task packets include `ncp_context`:
```json
{
  "ncp_context": {
    "agent_id": "<role-name>",
    "prior_refs": ["<ref-from-previous-phase>"],
    "layer": "episodic|semantic|procedural"
  }
}
```

## Error Handling

### Phase Fails
- Log failure in phase log
- Move to Learn phase
- Document failure patterns for evolution

### Review Hard Stop (after 5 rounds on Stage 2)
Post-hard-stop options presented to user:
1. **force_approve** - Accept current state
2. **request_changes** - Iterate with specific feedback
3. **abort** - Abandon task
4. **delegate_to_agent** - Let AI resolve remaining issues

### Task Blocked
Non-blocking siblings continue; blocked task presents options:
- Wait for block
- Skip task
- Substitute alternative
- Continue anyway

### Confidence Gate Not Met
- Log evidence gap
- Retry phase with guidance
- Escalate if repeated failures

## Learn-Evolve Loop

After every task:
1. Document patterns in `learnings.md`
2. skill-evolve detects recurring patterns
3. High-confidence evolutions auto-apply
4. Regression gate: >= 80% pass rate AND >= best seen

## Example Usage

### Example 1: Simple Bug Fix
```bash
sarathi run "Fix null pointer exception in user service" \
  --policy-pack ./my-project/policy-pack \
  --complexity low
```

Expected phases (LOW complexity):
1. Route
2. Brainstorm (+ spec self-review)
3. Plan (TDD-structured, no placeholders)
4. Build (TDD iron law)
5. Verify (with debugging escalation)
6. Review (two-stage)
7. TaskTracking
8. RiskCheck
9. Elegance
10. PhaseLog
11. Learn
*(PlanningAdvisor skipped)*

### Example 2: New Feature
```bash
sarathi run "Add OAuth2 authentication" \
  --policy-pack ./my-project/policy-pack \
  --complexity high
```

Expected phases (HIGH complexity):
1. Route
2. Brainstorm (+ spec self-review)
3. PlanningAdvisor *(executed for high)*
4. Plan (TDD-structured, no placeholders)
5. Build (TDD iron law)
6. Verify (with debugging escalation)
7. Review (two-stage)
8. TaskTracking
9. RiskCheck
10. Elegance
11. PhaseLog
12. Learn

### Example 3: Validate Policy Pack
```bash
# Quick check
sarathi validate ./my-project/policy-pack

# Detailed output
sarathi validate ./my-project/policy-pack --verbose
```

Output:
```
Summary: 8 PASS, 0 DRIFT, 2 TODO

Detailed Results:
------------------------------------------------------------
  ✓ [PASS] Route: complexity_triggers
      → complexity.md
  ✓ [PASS] Route: classification_thresholds
      → complexity.md
  ...
  ✗ [TODO] Learn: evolution_threshold
      → Not provided
```

## Key Principles

1. **Engine has zero domain knowledge** - Policy packs provide WHAT
2. **Sub-agent first** - Main thread available for communication
3. **Never skip build/test/review loops** - Even under pressure
4. **Non-blocking siblings** - Parallel tasks continue while one waits
5. **Evidence-weighted gates** - Explicit evidence, not subjective confidence
6. **Policy drives routing** - Complexity, skip, model selection
7. **Test-first always** - No production code without a failing test first
8. **Root cause before fix** - Never apply a 4th fix without root cause investigation
9. **Spec compliance before quality** - Review Stage 1 must pass before Stage 2 starts
10. **NCP as context spine** - Every subagent reads and writes NCP at turn boundaries
