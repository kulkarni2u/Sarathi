# Brainstorm Phase — Structured Dialogue

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
it is inside a Sarathi lifecycle. See `provider-contracts.md` for the payload shape.
