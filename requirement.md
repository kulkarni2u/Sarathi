# Sarathi - A Generic Workflow Orchestration.
I am planning to create a generic workflow orchestration called Sarathi. This is generic and tool agnostic, can work in OpenCode, Claude, Copilot, Cursor etc. 
​
## The Engine

Defines a canonical delivery model that every policy-backed workflow inherits.

- Sub-agent first mandate - Heavy exploration, planning, implementation and reviews must be delegated to subagents. Main agent thread is available for user at all time for any back-n-forth communication.
- Lifecycle - Complexity routing -> brainstorm -> planning advisor -> checkpoints -> TDD -> build/test/debug -> escalation -> review loop -> task tracking -> devil's advocate -> permissions -> elegance check -> phase log -> model selection
- Quality recovery - auto-fix-loop
- Profile/SLO Mechanism - Safe/Fast/High-Risk execution profiles. SLO targets per complexity tier. model selection based on effort requirement.
- Policy-backed design - Domain specific tool routing/coding conventions, flow-checks entirely supplied as a policy pack.

## Lifecycle - Phases

1. Route: Classify complexity Low/Medium/High.
2. Brainstorm: Confidence gate, 
3. Planning advisor (High complexity tasks)
4. Plan: Multiple Checkpoints. Post CP Q1/Q2. 90% confidence gate before any code.
5. Build: TDD Loop -> elegance chk -> implement. 
6. Verify: Build/Test/debug loop. auto-fix-loop with escalation bounds. Evidence artifacts generated.
7. Review: Per-unit parallel: spec compliance + code. Quality: 5-rounds hard stop. 
8. Task tracking: task model via task-tracking.md file. Blocked sub-agent protocol
9. Risk Check: Non-blocking risk assessment via Devil's advocate. Flags concerns, but doesnt block.
10. Elegance: Pre-build clean code ates via the elegance-check.md. Runs before build loop entry.
11. Phase Log: phase transition logging for audit trail.
12. Learn: Post-flight introspection, learning.md file updates. skill-evolve feeds back into the workflow.

At each phase the core workflow has to check the required inputs from the active policy pack based on the core-policy-interface mapping. The build/test/review loops are never skipped. 

## Engine Core vs Policy Pack

The Engine is reusable by design, it has zero domain knowledge, it defines HOW to deliver - not what to build, how to test or which tools to use.

What policy pack must supply:
- domain specific complexity triggers
- language/framework/module knowledge
- build/test commands
- coding conventions
- domain flow & integration checks
- review evidence requirements (what it means to be "reviewed")
- Escalation threshold (retry-counts, surface-to-user roles)
- SLO targets based on complexity
- domain specific skill routing (app wiki etc)

The core engine exposes a config.md, required-input list. a policy pack is valid when it satisfies the core-policy-interface-mapping contract for every required input. Any team/project that gets this mapping right gets the full engine for use.

## Sarathi --init - A way to onboard 

Default path to get any team/project on-board, exposed as a skill in the engine.

1. Inspect: Scan target repo(s). Detect language, framework, build tools, test patterns. Be a devil's advocate ask user when in doubt.
2. Interview: Ask only missing high-value questions: policy key, task tracking, Git source etc. domain constraints. review evidence shape etc.
3. Generate: Create policy-pack, core-policy-interface-mapping all the necessary files, markdown based wiki, loop until confidence gate is met.
4. Validate: Validate the generated content against the core engines config/required-input list. Runs parity-traceability checklist. Reports PASS/DRIFT/TODO per required input. Fixes gaps before hand-off
5. Evolve: learning loop + skill-evolv run after every task completion. Policy hardens from real patterns overtime.

Output: A structurally valid workflow that inhertits the core engine's workflow- TDD, review loops, escalation bounds, model selection - with domain specific rules from day one.

## The learn-evolve loop.

A mechanism that turns a structurally complete harness into an operationally expert one - over time, automatically.

Flow:

1. Task Completes:  This phase fires end of every task irrespective of complexity. 
2. Learnings.md: documents patterns, failures, missed edge-case and validated aproaches filled with confidence rating
3. skill-evolve: detects recurring patterns across learning.md. Propogates skill/policy updates. Regression gate: >= 80% pass rate AND >= best seen.
4. Policy Hardens: High-confidence evolutions auto-apply. Policy refences tighten. Future tasks start with accumulated wisdome.


