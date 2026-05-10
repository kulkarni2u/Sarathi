Continue Sarathi desktop from the repo state only.

Read first:

- `docs/superpowers/status/2026-05-09-sarathi-desktop-orchestration-studio-status.md`
- `docs/superpowers/status/2026-05-10-sarathi-desktop-release-handoff.md`
- `docs/superpowers/tasks/2026-05-10-sarathi-desktop-next.md`

Context:

- The main desktop ship pass is effectively complete.
- Primary flow, support surfaces, QA hygiene, backend auto-approve contract, and read-only Settings policy posture are already implemented.
- The project-creation entry-point regression was fixed in `desktop/src/pages/WorkspaceDashboard.tsx` by scrolling the create form into view and focusing `Project name`.
- Unsandboxed browser QA passed on May 10, 2026.

Operating mode:

- Be a thin controller.
- Do not rediscover already-closed work.
- Do not reopen the broad desktop refactor unless a new regression is reproduced.
- Prefer bounded slices and verification.

Default next decision:

- Decide whether to leave `auto_approve_preference` read-only in `Settings`, or open a new bounded pass for editable controls.

If you touch code:

- run the smallest relevant verification
- update the main status file with exact outcomes
