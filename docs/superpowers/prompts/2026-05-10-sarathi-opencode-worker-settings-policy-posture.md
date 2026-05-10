You are an OpenCode implementation worker for Sarathi desktop.

Scope:

- Add the Settings trust-surface for the already-implemented backend `auto_approve_preference` contract.
- Primary files you may own:
  - `desktop/src/pages/Settings.tsx`
  - `desktop/src/apiClient.ts` only if a small client type/helper addition is needed
- You may touch one related desktop file only if required for compilation.

Read first:

- `docs/superpowers/status/2026-05-09-sarathi-desktop-orchestration-studio-status.md`
- `docs/superpowers/specs/2026-05-09-auto-approve-policy-contract-design.md`
- `policy-pack/approval.md`
- current `desktop/src/pages/Settings.tsx`

Goal:

- Surface backend truth for `auto_approve_preference` in Settings.
- Keep repository safety primary.
- Present auto-approve as governed workflow posture, not as a convenience toggle.

Required behavior:

1. Read the current workspace metadata from the existing Settings data path.
2. Show:
   - current auto-approve mode
   - threshold summary when mode is `below_threshold`
   - brief explanation that critical governance gates remain manual
3. If editing is already straightforward and backed by the current workspace PATCH contract, allow bounded editing.
4. If editing would require broader client/backend changes than expected, keep this pass read-first and ship the posture display only.
5. Do not invent UI-only controls that are not backed by backend truth.

Constraints:

- Preserve current primary desktop flow.
- Do not rewrite provider transport.
- Do not revert unrelated user changes.
- Keep the write scope bounded to Settings unless strictly necessary.

Verification required:

- `npm --prefix desktop run build`

Report back with:

- files changed
- exact verification result
- whether the surface is read-only or editable
