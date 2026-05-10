You are an OpenCode implementation worker for Sarathi.

Scope:

- Implement the backend-first auto-approve policy contract from the approved spec.
- Primary files you may own:
  - `policy-pack/approval.md`
  - `src/service/__init__.py`
  - relevant tests under `tests/`
- You may touch a small related policy/parser file only if required for this slice.

Read first:

- `docs/superpowers/status/2026-05-09-sarathi-desktop-orchestration-studio-status.md`
- `docs/superpowers/specs/2026-05-09-auto-approve-policy-contract-design.md`
- current `policy-pack/`

Goal:

- Add a real persisted and enforced `auto_approve_preference` contract.
- Keep the default posture safe: `manual_only`.
- Make auto-approve impossible unless policy explicitly permits it.
- Do not add the desktop `Settings` surface yet unless it is trivial and fully backed by the new contract. Backend truth comes first.

Required implementation:

1. Add `policy-pack/approval.md` with a coherent default contract.
2. Add normalization / effective-preference handling analogous to `repository_action_preference`.
3. Enforce the preference in `POST /api/tasks/{id}/auto-approve`.
4. Denylist governance gates such as:
   - `PRD/AC`
   - `Repository action`
   - `Final handoff` or equivalent final governance gate if present
5. Record auditable lifecycle metadata for auto-approved decisions.
6. Add or update tests for:
   - manual-only refusing auto-approve
   - allowed threshold path succeeding
   - denylisted gates refusing auto-approve

Constraints:

- Preserve current primary desktop flow.
- Do not rewrite provider transport.
- Do not introduce a loose convenience toggle.
- Do not revert unrelated user changes.
- Keep the write scope bounded.

Verification required before claiming success:

- relevant pytest slices for the touched backend/policy logic
- `npm --prefix desktop run build` only if desktop code changed

Report back with:

- files changed
- exact verification commands and results
- any contract decisions that differ from the spec and why
