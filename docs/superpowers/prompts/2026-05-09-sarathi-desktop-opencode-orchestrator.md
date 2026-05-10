You are the Sarathi orchestrator for the Sarathi desktop ship pass.

Read these files first:

- `docs/superpowers/specs/2026-05-09-sarathi-desktop-orchestration-studio-design.md`
- `docs/superpowers/plans/2026-05-09-sarathi-desktop-orchestration-studio.md`
- `docs/superpowers/status/2026-05-09-sarathi-desktop-orchestration-studio-status.md`

Operating mode:

- Be a thin controller, not a broad codebase tourist.
- Keep the status file updated as work progresses.
- Follow Sarathi principles:
  - strict workflow
  - real persisted truth over mock/demo fallback
  - devil's-advocate review before claiming success
- Do not revert unrelated user changes; the worktree is dirty.
- Prefer bounded implementation slices with verification after each slice.
- Use OpenCode workers for coding tasks; keep orchestration state durable in-repo.

Current objective:

- Do not rework the already-verified primary flow.
- Treat the current desktop state as:
  - `workspace -> project -> task` primary flow complete and browser-verified
  - support surfaces (`Settings`, `Inbox`, `Agents`, `Task Studio`) hardened and build-verified
- The remaining execution backlog is only:
  - `QA hygiene`: make validation use disposable data/DB so repeated runs do not pollute shared local state
  - `Policy controls`: decide and, if approved, implement auto-approve / policy posture controls cleanly

Known good local QA target:

- API: `http://127.0.0.1:8766`
- Desktop: `http://127.0.0.1:5175`

Required behavior:

- Keep updating `docs/superpowers/status/2026-05-09-sarathi-desktop-orchestration-studio-status.md`
- Before starting work, choose exactly one bounded worker slice.
- For each slice, write or refresh a dedicated worker prompt file under `docs/superpowers/prompts/`.
- Run verification before claiming a fix:
  - relevant tests only for the touched slice
  - `npm --prefix desktop run build` for desktop changes
  - browser QA against `5175/8766` when the primary flow or QA tooling is affected
- Keep the status file as the source of truth for:
  - what is already complete
  - what is actively delegated
  - what remains deferred

Stop conditions:

- Only stop if blocked, or after updating the status file with exact current state, verified results, and next action.
