# Provider Contracts

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
