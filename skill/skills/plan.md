# Plan Phase — Spec-Driven Checkpoint List

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
