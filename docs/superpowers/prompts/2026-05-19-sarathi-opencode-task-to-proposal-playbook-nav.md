You are the primary orchestrator and implementor for one bounded Sarathi slice.

Repo:
- /Users/sweethome/Work/Skills/Sarathi

Goal:
Make task-side related learnings actionable.

Owned files:
- /Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/ProjectDetail.tsx

Do not edit:
- App.tsx
- KnowledgeCenter.tsx
- Proposals.tsx
- validate-task-panel.mjs

Acceptance criteria:
1. `Related learnings` on the task surface expose at least one direct action when linkage exists.
2. Prefer direct task-side actions to:
   - open the relevant proposal when derivable
   - open the promoted playbook/workflow target when derivable
3. The card stays compact and secondary to main task work.
4. Empty-state behavior remains clean.

Implementation guidance:
- Reuse existing task metadata, learning linkage, evidence refs, and playbook lineage.
- If only one of proposal/playbook can be derived reliably, implement that one well rather than inventing brittle fake actions.
- Keep changes localized to ProjectDetail.

Verification required:
- `npm --prefix desktop run build`

Deliver:
- changed files
- concise summary
- verification result
- blockers
