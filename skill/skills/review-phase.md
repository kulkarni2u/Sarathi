# Review Phase — Two-Stage Gate

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
