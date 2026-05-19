# Sarathi Desktop Next Task

Date: 2026-05-13

## Current Goal

The organized-orchestrator desktop slice is now complete and browser-verified.

The next meaningful product/engineering slice is:

1. Move Sarathi provider execution from CLI-first bridges toward SDK-first runtime adapters for:
   - OpenAI / Codex
   - Claude / Anthropic
   - OpenCode
   - Copilot

This is now the highest-leverage follow-up because the desktop/control-tower layer is strong enough that the remaining architectural risk sits in transport/runtime consistency.

## Already Verified

- `workspace -> project -> task` flow works
- workspace project creation is persisted
- task studio opens on the correct task
- task-studio posture now exposes queue state, approval posture, checkpoint readiness, handoff posture, and next safe action
- support surfaces are hardened around organized projections
- `Inbox` now renders a real attention queue
- browser QA passed on the live connected runtime:
  - `npm --prefix desktop run validate:task-panel`
- backend projection tests passed:
  - `python3.11 -m pytest tests/test_task_dashboard.py tests/test_operational_views.py tests/test_task_studio.py -v`
- desktop build passed:
  - `npm --prefix desktop run build`

## Next Slice

Open the next implementation slice only if you are intentionally doing one of:

- provider SDK runtime abstraction and migration
- release hygiene / commit slicing
- a new desktop feature pass that depends on richer provider semantics

## Recommended Next Task

Provider-SDK migration status now:

Done:

- added a concrete design spec for SDK-first provider runtimes
- added a migration plan with milestones and file ownership
- introduced provider capability metadata and a lightweight session-oriented runtime seam in `src/runtime/providers/*`
- verified backward compatibility with:
  - `python3.11 -m pytest tests/test_dispatch.py tests/test_provider_dispatch.py -v`

Next:

1. extend the SDK-backed runtime pattern beyond OpenCode to Codex/OpenAI or Claude
2. persist provider session identifiers/checkpoints if we want resume semantics across multiple dispatches
3. keep desktop provider posture in sync as transport kinds evolve from `cli_fallback` to `sdk` or `api`

Newly completed on 2026-05-13:

- 10-task provider-runtime batch completed:
  1. added OpenCode SDK-backed adapter
  2. added OpenCode SDK helper script
  3. added OpenAI/Codex SDK-backed adapter
  4. added OpenAI helper script
  5. exported new adapters through runtime provider modules
  6. taught configured provider routing about `opencode_sdk`
  7. taught configured provider routing about `openai_sdk`
  8. integrated OpenCode service routing as SDK-first with CLI fallback
  9. integrated Codex service routing as SDK-first with CLI fallback for real `codex` binaries
  10. expanded dispatch/provider tests to cover the new SDK-first paths and guard command-shim behavior
- provider transport posture is now explicit in service payloads:
  - `transport_kind`
  - `transport_posture`
  - `degraded_reason`
- desktop provider inventory and settings now show which providers are still running through CLI fallback
- OpenCode now runs through an SDK-backed adapter first, with CLI retained only as a safety fallback
- Codex now routes through an OpenAI SDK-backed adapter first when the configured path is a real `codex` executable, with CLI retained as a safety fallback
- Codex now supports workspace-scoped SDK settings in Sarathi:
  - API key
  - optional base URL
  - optional model override
  - SDK-only mode with no CLI path required
- the SDK helper bootstraps successfully in this repo:
  - `printf '{}' | node desktop/scripts/opencode-sdk-dispatch.mjs`
- the OpenAI helper fails cleanly without credentials, which is the expected smoke behavior:
  - `printf '{}' | node desktop/scripts/openai-sdk-dispatch.mjs`
- Claude / Anthropic is now also SDK-first with CLI fallback:
  - added `src/runtime/providers/anthropic_sdk.py`
  - added `desktop/scripts/anthropic-sdk-dispatch.mjs`
  - added workspace-scoped Claude SDK settings:
    - API key
    - optional base URL
    - optional model override
    - SDK-only mode with no CLI path required
- the Anthropic helper fails cleanly without credentials, which is the expected smoke behavior:
  - `printf '{}' | node desktop/scripts/anthropic-sdk-dispatch.mjs`
- verification passed:
  - `python3.11 -m pytest tests/test_dispatch.py tests/test_provider_dispatch.py -v`
  - `npm --prefix desktop run build`

Newly completed on 2026-05-14:

- added the first real `ContextCompiler` foundation in `src/runtime/context.py`
- introduced compact context-pack contracts:
  - `AgentInputContract`
  - `AgentOutputContract`
  - `ContextPack`
- wired service-backed subtask dispatch through compiled, token-budget-aware context packs
- persisted compiled context packs into dispatch metadata for later inspection and audit
- recorded a first-class `context.compiled` lifecycle event before provider dispatch
- taught the provider CLI bridge prompt to prefer `context_pack` plus `token_budget` over reconstructing chat history
- extended the same compiler pattern into graph-executor child-node dispatch, so runtime graph work now also carries compiled context packs
- stamped compact `context_pack_summary` data onto graph nodes and provider results for lightweight operator visibility
- exposed context-pack summary hints in CLI supervision output and Task Studio dispatch cards
- added focused regression coverage for:
  - compact task-tracking context compilation
  - low-budget trimming behavior
  - persisted compiled context in subtask dispatch flow
  - graph-executor child-task dispatch carrying compiled context
  - CLI supervision rendering compact context-pack summaries
- added normalized retrieval helpers in `src/runtime/output_index.py`
- Sarathi now persists a compact `agent_output` contract beside raw provider outputs for subtask dispatches
- Sarathi now persists an `artifact_index` with:
  - `files_changed`
  - `tests_run`
  - `known_risks`
  - `review_findings`
- successful dispatch evidence records now carry the same normalized `agent_output` and `artifact_index` payloads
- graph-executor child-node results now stamp normalized `agent_output` and `artifact_index` onto provider results and graph nodes
- added focused regression coverage for:
  - artifact-index extraction across outputs, evidence, and review traces
  - compact `agent_output` normalization
  - dispatch persistence of normalized retrieval fields
  - graph-node propagation of normalized retrieval fields
- normalized retrieval now carries richer review/handoff traces in `artifact_index.review_findings`, including:
  - diff hunks
  - spec references
  - provider/source attribution
  - line ranges and confidence where available
- later-stage consumers now prefer normalized contracts before raw provider blobs:
  - context compilation relevant-file lookup reads `artifact_index.files_changed` first
  - review generation reads normalized changed files, findings, diff hunks, and spec references first
  - handoff generation stores and reuses a normalized completion context instead of reconstructing completion evidence from raw payloads
- raw `response_evidence` remains available only as a compatibility fallback while older dispatch records still exist
- added regression coverage proving review still succeeds even when raw trace structures are stripped from evidence metadata, as long as normalized `artifact_index` data remains
- Task Studio now exposes an operator-facing artifact inspector:
  - Evidence tab shows normalized summaries for:
    - changed files
    - tests run
    - review findings
    - known risks
  - dispatch cards now surface:
    - compiled objective
    - token budget posture
    - compact summary
    - next recommended agent
    - normalized artifact counts
    - preview findings
  - handoff now surfaces normalized completion context with:
    - completion summaries
    - decision trace
    - files changed
    - tests run
    - known risks
    - reviewer signals
- desktop verification passed:
  - `npm --prefix desktop run build`
- browser QA notes:
  - refreshed `desktop/scripts/validate-task-panel.mjs` for the current Workspace -> project -> task studio journey
  - fixed stale landing and workspace-create selectors
  - fixed the isolated API bootstrap bug where the validator tried to spawn the service with Node `process.execPath` instead of Python
  - full validator now passes again:
    - `BASE_URL=http://127.0.0.1:5174 CLEANUP_DB_PATH=true desktop/scripts/validate-task-panel.sh`
  - the validator now also asserts the live project-view artifact inspector directly:
    - `Artifact overview`
    - `Changed files`
    - `Tests run`
    - `Known risks`
- normalized artifact inspector is now exposed in the live `ProjectDetail` studio view, not only in the older App-level Task Studio
- live `Evidence and events` now surfaces:
  - artifact overview counts
  - changed files
  - tests run
  - known risks
  - dispatch inspector summaries when available
- live `ProjectDetail` artifact inspector now exposes normalized review-finding detail rows instead of only counts
- review findings are now severity-sorted and keep scan-read inline metadata compact:
  - severity
  - file location
  - check name
- deeper operator audit is now available without raw payload dumping:
  - expandable `Trace and remediation` details per finding
  - expandable `Artifact provenance` section showing normalized-first vs compatibility fallback sources
- browser validator now also asserts:
  - `Review findings`
  - `Artifact provenance`
- live `ProjectDetail` now exposes a real Release 2 `Delivery spine` card on the studio surface
- the delivery spine surfaces:
  - PRD brief
  - acceptance-criteria checklist with coverage posture
  - governed-handoff readiness and missing requirements
  - compact completion-context counts once a handoff exists
- Release 2 synthesis is now shown on the live task page instead of being split between backend metadata and the older App-level demo task view
- browser validator now also asserts:
  - `Delivery spine`
- live `ProjectDetail` now exposes a richer `Final handoff dossier` for reviewed tasks:
  - repository-action posture
  - AC coverage section
  - completion-context counts
  - compact summaries and known risks
- browser validator now seeds a real reviewed task with handoff metadata through the isolated API and then verifies the live dossier surface
- the validator now proves both halves of Release 2 in one run:
  - fresh request -> task studio creation still works
  - reviewed task -> handoff dossier rendering works from persisted review/handoff data
- validator-side API helpers now unwrap Sarathi's standard `{ ok, data }` envelope so QA uses the same persisted objects the desktop uses

Roadmap status update:

- Release 1 exit criteria are satisfied in the live product
- Release 2 exit criteria are now satisfied in the live product and verified through browser QA plus handoff regression tests
- Release 3 exit criteria are now satisfied in the live product:
  - workspace governance metadata now persists provider priority and emits governance events
  - operational views now expose policy posture, provider routing and fallback visibility, override history, and repository-action governance
  - Settings now surfaces governance posture, persisted dispatch order, fallback routing, override history, and repository-action audit counts
  - Inbox now surfaces governance and repository-action counts alongside operational queues
  - ProjectDetail now surfaces governance posture, override timelines, and repository-action audit context directly in Task Studio and History
  - browser QA now proves both task-level governance and the Settings governance surface end to end
- Release 4 is now started in the live product:
  - new workspace `reuse-kit` service surface returns built-in workflow templates, saved role-based views, and learning-derived playbooks with provenance
  - Workspace dashboard now renders reusable workflow templates, saved views, and learned playbooks from live workspace data instead of mock-only cards
  - accepted workspace learnings in `learnings.md` now promote into reusable playbooks with recommended template and view hints
  - browser QA now proves the new workspace reuse surface before continuing through the existing project/task workflow
- Release 4 progressed further:
  - saved-view selection now persists as workspace reuse state instead of being ephemeral UI-only state
  - reuse preference changes emit `workspace.reuse_updated` events and no longer pollute governance history
  - workspace project summaries now carry approval/checkpoint/handoff counts so reusable views can filter on real delivery posture
  - template cards can now prefill the project create form and launch a seeded brainstorm prompt
  - learned playbooks can now launch seeded brainstorm prompts built from accepted learning provenance
  - custom saved-view definitions are now persisted in workspace reuse preferences and returned by the live `reuse-kit` surface with computed counts
  - Workspace dashboard now lets operators save the current view as a reusable team-specific card and remove custom saved views without leaving the workspace surface
  - browser QA now proves the custom saved-view flow as part of the Release 4 workspace validation path
- Release 4 is now satisfied in the live product:
  - active saved-view semantics now carry across the workspace dashboard, task dashboard, inbox, and task studio surfaces
  - template and playbook launches now persist recommended-view posture before brainstorming begins, so teams do not reconfigure their operator context manually
  - brainstorm sessions now preserve workflow-template and playbook provenance in durable metadata, and approved tasks keep that reuse context for later inspection
  - brainstorm UI now surfaces the reusable workflow source and recommended views explicitly instead of burying them inside the launch prompt
  - backend tests, desktop build, and browser QA now cover the reusable workflow flow end to end
- Next-wave provenance polish is now in progress:
  - task studio now surfaces a dedicated `Task origin` summary built from durable launch and reuse metadata instead of expecting operators to infer it from prompts or brainstorm history
  - dispatch inspectors now surface trace sources such as compiled context packs, normalized agent output, normalized artifact indexes, and raw provider evidence retention
  - browser QA now asserts the new provenance language so operator-trust regressions fail visibly
- Release-candidate hardening is now in progress:
  - `sarathi` now exposes the desktop launcher as a first-class entrypoint instead of making the product feel split between `sarathi` and `sarathi-desktop`
  - desktop launcher now supports a configurable service startup timeout and normalizes wildcard bind hosts to a loopback connect URL for health checks and runtime wiring
  - `sarathi resume` now fails early with a clean policy-pack error instead of falling through to a confusing downstream engine failure
  - `sarathi reuse` now surfaces live workflow templates, saved views, and learned playbooks from the running local service so CLI/dogfood flows can discover the same reusable workflow assets as the desktop
- Knowledge-center restoration is now in progress:
  - new read-only workspace surfaces now exist for `Knowledge Center`, `Wiki`, `Skills Registry`, and `Context Inspector`
  - service routes now expose workspace guide coverage, wiki pages, policy-pack skill routing, and recent compiled context bundles from persisted dispatch metadata
  - nested wiki pages now round-trip through the API correctly via URL-decoded page paths
  - skill registry data now reflects the real `policy-pack/skills.md` YAML structure instead of brittle markdown header counting
  - context inspector now shows compiled objective, constraints, acceptance criteria, artifact index, normalized output, and provenance sources from the stored context-pack metadata
  - focused backend tests, desktop build, and browser QA now cover the new knowledge-center slice end to end
- Proposal-inbox productization is now in progress:
  - the desktop sidebar now exposes a dedicated `Proposals` surface for self-evolving knowledge and policy review
  - service routes now support `GET /workspaces/{id}/proposals` and real accept/reject actions against the workspace policy pack
  - proposal generation reuses the existing `Evolver` and `ProposalReviewStore` engine instead of a parallel implementation
  - workspace proposal candidates are synthesized deterministically from persisted task, dispatch, and rejected-review signals
  - already-reviewed proposal IDs are filtered out using `.sarathi-proposals` so only pending decisions stay in the inbox
  - focused service tests, desktop build, and browser QA now cover the proposals route and decision loop
- Knowledge-center proposal posture is now surfaced:
  - the `Knowledge Center` summary now includes proposal posture from the same persisted proposal-review store used by the Proposals inbox
  - service responses now report pending, accepted, rejected, and last-reviewed proposal counts for the workspace
  - the desktop knowledge-center page now shows `Evolution inbox` and `Proposal posture` cards so operators can see self-evolution state at a glance
  - the reuse-kit regression fixture now seeds the policy-pack files needed to persist an accepted proposal decision without changing production behavior
  - focused reuse-kit tests and desktop build now cover this proposal-summary slice
  - the desktop app now preserves locally created projects when an older empty `listWorkspaceProjects` response arrives, preventing the first project from disappearing during the workspace-to-dashboard transition
  - browser QA for `workspace -> project -> task studio` is green again after the project-create race fix
- Proposal review is now more trustworthy:
  - service routes now expose a single-proposal detail endpoint with the current policy file content and a read-only acceptance preview built from the same `ProposalReviewStore` logic used for real acceptance
  - the desktop `Proposals` page can now expand each proposal into a preview panel that shows current policy text beside the accepted preview before the operator decides
  - focused service tests now cover the proposal-detail endpoint, and the main browser validator remains green as a no-regression check
- Workspace wiki is no longer read-only:
  - service routes now support saving wiki pages through the workspace API, including creation of nested markdown pages under `wiki/`
  - the desktop `Wiki` page now supports creating a new page, editing markdown inline, saving it, and resetting local changes
  - focused reuse-kit coverage now proves saving and reading a wiki page back through the API, and the main browser validator remains green as a no-regression check
- Skills Registry is now writable as a minimal Skill Studio:
  - service routes now support saving the raw workspace skills pack back to `policy-pack/skills.md`
  - the desktop `Skills` page now exposes an editable source panel with save and reset actions alongside the grouped routed-skill view
  - focused reuse-kit coverage now proves saving and reading the skills pack back through the API
  - the project-list race on first project creation is guarded again via workspace mutation versioning, and browser QA for `workspace -> project -> task studio` is green after the no-regression check
- Proposal inbox metadata is now closer to a governed evolution review surface:
  - proposal payloads now expose `proposal_kind`, `impacted_assets`, and `risk_level` in both list and detail responses
  - accepted proposal previews now persist the same metadata into `accepted_proposals` entries, so the applied policy record stays inspectable
  - the desktop `Proposals` page now surfaces proposal kind, risk, and impacted assets inline without losing the existing policy preview flow
  - focused service coverage, desktop build, and browser QA remain green after the additive metadata contract change
- Proposal generation now reaches real workspace assets beyond policy notes:
  - current workspace signals now synthesize a `wiki/review-loop.md` escalation playbook proposal and a `skills.md` iteration-guard proposal, instead of only policy-pack suggestions
  - proposal preview and accept now work for non-policy assets too, including creating a missing wiki page on acceptance
  - the desktop `Proposals` page now uses asset-generic preview language so wiki and skills proposals do not read like policy-only records
  - focused service coverage, desktop build, and browser QA remain green after the multi-asset proposal slice
- Context-compiler improvement proposals are now in progress:
  - workspace proposal synthesis now turns trimmed or near-budget compiled context packs into reviewable `context_update` proposals targeting `wiki/context-compiler.md`
  - accepting a context proposal can now create the target wiki asset through the same generic proposal preview/apply path used for other non-policy assets
  - the `Proposals` page now keeps its heading visible while loading, so route state is legible even when proposal fetches are still in flight
  - focused service coverage, desktop build, and browser QA are green for the context-proposal slice
  - a stale partial OpenCode merge path around `context_trimming` was removed from `src/evolve.py`, which restored the live proposals API and fixed the empty-workspace proposals validation path
- Guided Skill Studio is now in place:
  - the skills API now returns normalized routing metadata with `secondary` as a string array, including comma-separated compatibility for older policy-pack content
  - the desktop `Skills` page now keeps guided routing edits in separate draft state, regenerates the routing block safely, and resets both raw source and guided routes from the last saved payload
  - task-type routing can now be added or removed even when the workspace currently has zero rules, while the raw `skills.md` editor remains available beside it
  - focused reuse-kit coverage now proves route round-tripping, `npm --prefix desktop run build` passes, and browser QA for `workspace -> project -> task studio` remains green after the Skill Studio change
  - OpenCode produced the first-pass patch for this slice, but the final integration required a local cleanup in `desktop/src/pages/Skills.tsx`; the Claude Sonnet review lane was unavailable due quota
- Knowledge and skills IA is now defined explicitly:
  - a new IA spec locks the product model to `Knowledge Center` as the parent for wiki, context, proposals, and learnings, while `Skills` remains the separate behavior studio
  - the current top-level overlap between `Knowledge`, `Wiki`, `Context`, and `Proposals` is now treated as a migration state, not the intended final navigation
  - the recommended next UI slice is to move toward internal Knowledge Center section navigation while keeping deep-link compatibility during migration
- Knowledge Center IA migration has now started in the live desktop:
  - the left nav now exposes `Knowledge Center` and `Skills` as the top-level library surfaces, while `Wiki`, `Context`, and `Proposals` remain route-compatible but are no longer peer nav concepts
  - legacy `wiki`, `context`, and `proposals` routes now render through the Knowledge Center model with internal section switching instead of separate peer pages
  - the Knowledge Center page now provides an explicit internal section switcher for `Overview`, `Wiki`, `Context`, and `Proposals`, making the intended parent-child IA visible in the product
  - desktop build and the main browser validator remain green after the route and nav migration
  - OpenCode produced the initial nav and route patch, but the final `KnowledgeCenter.tsx` integration required a local cleanup after its partial edit drifted structurally
- Knowledge Center now owns the real internal library surfaces:
  - the `Wiki`, `Context`, and `Proposals` sections inside Knowledge Center now render the real live product surfaces instead of temporary summary placeholders
  - the existing route compatibility remains intact, but the user-visible IA now matches the intended model: these are Knowledge Center sections, not separate library peers
  - the browser validator now checks the proposals path through Knowledge Center instead of expecting a top-level proposals button
  - desktop build and the main browser validator remain green after the internal-panel migration
  - backend note: the default local API on `127.0.0.1:8765` was not running during this slice; browser validation still passed via the validator's isolated backend path
- Skill Studio now explains behavior more clearly:
  - the skills API now returns `role_mappings` derived from the live Sarathi runtime role registry and phase mapping, instead of a hand-maintained UI-only list
  - the skills API now also returns deterministic `behavior_assets` for the main workspace files that shape execution behavior, including `policy-pack/skills.md`, `SARATHI.md`, `learnings.md`, and `wiki/context-compiler.md`
  - the desktop `Skills` page now shows a summary-first `Role mappings` card and a `Behavior provenance` card alongside the existing source editor and task-type routing editor
  - focused reuse-kit coverage, desktop build, and the main browser validator remain green after this Skill Studio expansion
  - backend note: the default local API on `127.0.0.1:8765` is now running again during this slice and returns healthy status
- Proposal-backed skill evolution is now live inside Skill Studio:
  - the skills API now returns a filtered `evolution_proposals` list that includes only behavior-change proposals relevant to skills and routing, instead of making the Skills surface re-read the full generic proposal inbox
  - the desktop `Skills` page now shows a summary-first `Pending evolution` card with proposal kind, risk, primary asset, inline preview, and direct accept/reject controls
  - direct decisions reuse the existing proposal detail and accept/reject endpoints, so accepted or rejected behavior changes disappear from the local Skills view without inventing a second workflow
  - focused service coverage, desktop build, and the main browser validator remain green after the governed skill-evolution slice
  - OpenCode provided the initial service/UI direction for this slice, but the final integration required local cleanup for preview support, empty-state handling, and type-safe demo fixtures
- Context-compiler evolution proposals are now more specific:
  - workspace context-gap synthesis now preserves `estimated_tokens` and `token_budget` alongside trimmed sections, and it records both omission and near-budget pressure when they happen together
  - `context_update` proposals now distinguish omission risk from pure budget pressure, and their rationale/suggested change text now names the actual affected sections and token pressure instead of only saying the compiler was under pressure
  - the focused service suite and the main browser validator remain green after the context-proposal specificity upgrade
- OpenCode produced the first-pass backend direction for this slice, and the final local cleanup ensured near-budget pressure is retained when trimmed sections and budget pressure occur at the same time
- Richer provenance is now displayed in the Skills evolution history:
  - the Skills API now returns `source` and `impacted_assets` fields alongside each accepted/rejected decision, pulling the trigger source and affected files from the persisted proposal store
  - the Skills UI now displays proposal kind pills, the trigger source (e.g., "repeated_failures", "provider_failures"), rejection reasons when available, and impacted asset list in the evolution history card
  - the history card now shows up to 10 items (up from 5) with richer inline provenance instead of just title and date
  - focused service tests pass, desktop build passes, browser validation passes:
    - `python3.11 -m pytest tests/test_service_api.py::test_workspace_skills_payload_includes_evolution_history -v`
    - `npm --prefix desktop run build`
    - `BASE_URL=http://127.0.0.1:5177 CLEANUP_DB_PATH=true node desktop/scripts/validate-task-panel.mjs`
  - final local seam fixes ensured reviewed `impacted_assets` are parsed correctly from persisted JSON arrays and that accepting/rejecting a pending proposal updates the in-page evolution history immediately
- Knowledge Center overview now shows section-level health:
  - the knowledge center API now returns a `section_health` object with metrics for wiki (page count, deep links, last updated), context (total bundles, unique tasks, recent count), and proposals (pending/accepted/rejected counts, last reviewed)
  - the helper functions `_count_wiki_deep_links`, `_get_most_recent_wiki_update`, and `_count_unique_task_contexts` compute these metrics from workspace files and dispatch records
  - the Knowledge Center overview now displays a 3-column health card showing page count and deep links for wiki, bundle count and unique tasks for context, and pending/accepted/rejected counts for proposals
  - the desktop UI only shows the health cards when the API returns section_health (backward compatible with older mock data), and the health cards display above the existing summary cards for at-a-glance section status
  - all 47 service API tests pass, desktop build passes, browser validation passes
- Accepted context-compiler proposals now feed retrieval-source guidance into the live Context Inspector:
  - the knowledge center API now returns a `context_compiler_guidance` array containing accepted `context_update` proposals with their title, policy file, suggested change, impacted assets, and review timestamp
  - the `_accepted_context_proposals` helper scans policy-pack markdown files for `accepted_proposals` entries matching `context_update` kind and extracts the relevant guidance
  - the Knowledge Center overview health card for Context now shows a "guidance" metric when context compiler rules are available
  - the Context Inspector now fetches and displays an inline "Context compiler guidance" card at the top of the detail view when accepted context proposals exist, showing up to 3 rules with their title and suggested change, and indicating how many more rules are available
  - this makes accepted context-compiler proposals visible during actual context inspection, giving operators insight into the retrieval-source guidance that informed the current bundle
  - all 47 service API tests pass, desktop build passes, browser validation passes
- Evolution history card improved for operator scanability:
  - added accepted/rejected summary counts near header showing both counts and total
  - changed timestamp from date-only to full datetime (e.g., "May 18, 10:30 AM")
  - styled rejection reason with distinct border-left accent for quick visual identification
  - changed "Assets" label to "Affected" for clarity
  - keeps summary-first design, no modal or second workflow introduced
  - verification: `npm --prefix desktop run build` passed, browser validator passed

Roadmap status:

- Release 1 exit criteria are satisfied in the live product
- Release 2 exit criteria are satisfied in the live product
- Release 3 exit criteria are satisfied in the live product
- Release 4 exit criteria are now satisfied in the live product

Recommended next:

1. add richer provenance and review history inside the Skills evolution card so accepted/rejected behavior decisions stay legible without leaving Skill Studio (DONE: improved with summary counts, exact timestamp, styled rejection reason)
2. make the Knowledge Center overview smarter by surfacing section-level health and deep-link counts from the embedded wiki, context, and proposal surfaces (DONE)
3. let accepted context-compiler proposals feed stronger retrieval-source guidance back into the live Context Inspector and dispatch summaries (DONE)
4. enhance the task studio delivery spine to show checkpoint readiness status directly on each spine item (DONE: added checkpoint-ready pill to PRD brief, Acceptance criteria, Ready for governed handoff, and Completion context sections)
5. make Learnings a real Knowledge Center section (DONE: added Learnings section with accepted learning summaries, provenance, and promoted playbook/view linkage)
6. make Learnings cards actionable (DONE: fixed the `learnings` route through Knowledge Center, added `Open task` and `Open playbooks` actions on learning cards, and kept browser validation green on the live app)

- [organized orchestrator sprint design](/Users/sweethome/Work/Skills/Sarathi/docs/superpowers/specs/2026-05-12-sarathi-organized-orchestrator-sprint-design.md)
- [agent-agnostic supervision design](/Users/sweethome/Work/Skills/Sarathi/docs/superpowers/specs/2026-05-06-agent-agnostic-cli-supervision-design.md)
- [provider SDK runtime design](/Users/sweethome/Work/Skills/Sarathi/docs/superpowers/specs/2026-05-13-provider-sdk-runtime-design.md)
- [provider SDK migration plan](/Users/sweethome/Work/Skills/Sarathi/docs/superpowers/plans/2026-05-13-provider-sdk-migration.md)
- [OpenCode takeover prompt](/Users/sweethome/Work/Skills/Sarathi/docs/superpowers/prompts/2026-05-18-sarathi-opencode-takeover.md)

---

## Learning Loop Links Slice (2026-05-19)

**Goal**: Close the next learning-loop gap by linking Learnings back into Task Studio and Proposals.

**Completed**:

1. **Task Studio "Related learnings" surface** (`ProjectDetail.tsx`):
   - Shows compact card when selected task ID matches accepted learning task_id
   - Displays learning title, summary, and tags
   - Summary-first, clearly secondary to main task work

2. **Proposals learning-source linkage** (`Proposals.tsx`):
   - Shows lightweight "Learning link" annotation when proposal evidence_refs can be traced to accepted learning context
   - Matches by task ID in evidence refs (e.g., "task-1:repeated_failures:Build")
   - Clean empty-state when no matches exist

**Verification**:
- `npm --prefix desktop run build` - passed
- `BASE_URL=http://127.0.0.1:5173 CLEANUP_DB_PATH=true node desktop/scripts/validate-task-panel.mjs` - passed

```
validate-task-panel: workspace -> project -> task studio flow passed
```

**QA Slice (2026-05-19)**: Extended browser QA coverage for learning-loop interactions
- Added Learnings surface validation in Knowledge Center section (lines 311-317 in validate-task-panel.mjs)
- Validates "learnings" heading and accepts both "accepted learnings" and "no accepted learnings" states
- Fixed `goToKnowledgeSection` to use `.first()` for strict mode compliance with dual headings
- Verification: `BASE_URL=http://127.0.0.1:5173 CLEANUP_DB_PATH=true node desktop/scripts/validate-task-panel.mjs` - passed

**Navigation Slice (2026-05-19)**: Closed the first cross-surface learning-loop links
- Proposal `Learning link` annotations can now route into the Learnings section of Knowledge Center
- Task Studio `Related learnings` now expose direct actions to open linked proposals and promoted playbooks when derivable
- Verification: `npm --prefix desktop run build` and `BASE_URL=http://127.0.0.1:5173 CLEANUP_DB_PATH=true node desktop/scripts/validate-task-panel.mjs` - passed

**Learning Linkage Metadata Slice (2026-05-19)**: Added durable provenance fields to accepted learnings
- Backend (`src/service/__init__.py`):
  - Added `_enrich_learnings_with_linkages()` function to link learnings to proposals and playbooks
  - Added `linked_proposal_id`, `linked_proposal_title`, `linked_playbook_id`, `linked_playbook_name` fields to accepted learnings
  - Links proposals by matching learning task_id in proposal evidence_refs
  - Links playbooks by reusing the existing workspace learned-playbook derivation and its `provenance.task_id`
- Frontend API (`desktop/src/apiClient.ts`):
  - Updated `KnowledgeCenterSummary` type to include new linkage fields
- UI (`desktop/src/pages/KnowledgeCenter.tsx`):
  - Updated learning cards to prefer durable `linked_proposal_id`/`linked_proposal_title` before falling back to inference
  - Updated "Promoted playbook" display to prefer `linked_playbook_name` over `recommended_template_id`
  - Updated mock data to include new fields for demo mode
- Verification:
  - `python3.11 -m pytest tests/test_reuse_kit.py tests/test_service_api.py -q` - passed (55 tests)
  - `npm --prefix desktop run build` - passed
  - `BASE_URL=http://127.0.0.1:5173 CLEANUP_DB_PATH=true node desktop/scripts/validate-task-panel.mjs` - passed

**Exact Proposal Cross-link Slice (2026-05-19)**: Tightened learning-loop navigation to open the precise proposal object
- `Knowledge Center`:
  - learning cards can open the exact linked proposal through the existing durable `linked_proposal_id`
- `Proposals`:
  - proposal focus now accepts durable IDs and prefixed variants
  - focused proposals auto-expand, auto-scroll into view, and eagerly load detail preview when needed
  - learning annotations now prefer durable learning-to-proposal links before falling back to evidence-ref inference
- `Task Studio`:
  - `Related learnings` now derive proposal actions from durable `linked_proposal_id` first
  - when a single exact proposal is known, the action label uses that exact proposal title instead of a generic `View proposal`
- Verification:
  - `npm --prefix desktop run build`
  - `BASE_URL=http://127.0.0.1:5173 CLEANUP_DB_PATH=true node desktop/scripts/validate-task-panel.mjs`

**Exact Playbook View Slice (2026-05-19)**: Made learning/playbook actions route to the most relevant saved view instead of a generic workspace landing
- `App` and `Workspace Dashboard`:
  - carry a focused saved-view ID through routing so the workspace opens with the intended saved view active
- `Knowledge Center`:
  - `Open playbooks` now forwards the first recommended saved view from the learning metadata when available
- `Task Studio`:
  - `Related learnings` now prefer the task reuse metadata's recommended saved view, falling back to related learning recommendations
  - the action label names the exact saved view when one is known
- Verification:
  - `npm --prefix desktop run build`
  - `BASE_URL=http://127.0.0.1:5173 CLEANUP_DB_PATH=true node desktop/scripts/validate-task-panel.mjs`

**Durable Learning Loop Provenance Slice (2026-05-19)**: Turned reviewed proposal decisions into real navigable history and proved the click paths in browser QA
- Backend:
  - reviewed proposal decisions now persist `confidence`, `suggested_change`, and `evidence_refs`, so learning-to-proposal linkage survives acceptance/rejection as durable provenance
  - `/api/workspaces/{id}/proposals` now returns `reviewed_history` alongside pending proposals
- Proposals surface:
  - reviewed proposal history is rendered even when the inbox is otherwise empty
  - focused proposal routing can land on either a pending proposal or a reviewed-history card
  - reviewed-history cards can route back to the matching learning through durable linkage
- Workspace / Knowledge loop QA:
  - isolated browser validation now seeds a deterministic accepted learning plus reviewed proposal fixture
  - validator clicks `Learning link`, `Open proposal`, and `Open playbooks` and confirms the expected destination behavior
  - `WorkspaceDashboard` now preserves a focused saved-view ID over the fetched active-view default so route-driven playbook jumps actually land on the intended posture
- Verification:
  - `python3.11 -m pytest tests/test_reuse_kit.py tests/test_service_api.py -q`
  - `npm --prefix desktop run build`
  - `BASE_URL=http://127.0.0.1:5173 CLEANUP_DB_PATH=true node desktop/scripts/validate-task-panel.mjs`

**Task Studio Linked Proposal Summary Slice (2026-05-19)**:
- `ProjectDetail` now shows a compact inline `Linked proposal` summary inside `Related learnings`
- the card surfaces title, rationale, risk, confidence, and primary impacted asset before the user leaves Task Studio
- the exact `Open proposal` action still exists, but operators can now scan the proposal in place instead of only jumping away
- Verification:
  - `npm --prefix desktop run build`
  - `BASE_URL=http://127.0.0.1:5173 CLEANUP_DB_PATH=true node desktop/scripts/validate-task-panel.mjs`

**Hygiene Slice (2026-05-19)**:
- ignored transient root-level AI scratch packs via `.gitignore`:
  - `.opencode-*.md`
  - `.claude-*.md`
- removed obvious generated junk from the worktree:
  - `docs/superpowers/.DS_Store`
  - local `__pycache__/` directories
- kept the hygiene pass intentionally narrow so it would not disturb the already-dirty tracked product work

**Browser QA Learning Link Extension Slice (2026-05-19)**:
- Extended browser QA (`desktop/scripts/validate-task-panel.mjs`) to validate learning-loop navigation paths:
  - Added "Open playbooks" button validation in Knowledge Center Learnings section (lines 336-346)
  - Added "Open proposal" button validation in Knowledge Center Learnings section (lines 348-358)
  - Added "Learning link" button validation in Proposals section (lines 310-326)
- Validations are conditional - they check for button presence and log appropriate messages for demo mode vs live API mode
- The existing linkage implementation is already in place:
  - Backend `_enrich_learnings_with_linkages()` adds `linked_proposal_id`, `linked_proposal_title`, `linked_playbook_id`, `linked_playbook_name` to accepted learnings
  - Frontend API types include linkage fields in `KnowledgeCenterSummary`
  - KnowledgeCenter UI renders "Open proposal" and "Open playbooks" buttons based on linkage
  - Proposals UI renders "Learning link" button when learning matches proposal evidence refs
- Verification:
  - `python3.11 -m pytest tests/test_reuse_kit.py tests/test_service_api.py -q` - passed (55 tests)
  - `npm --prefix desktop run build` - passed

**Task Studio Inline Proposal Summary Slice (2026-05-19)**:
- **Goal**: Replace the action button for linked proposals in Task Studio "Related learnings" with a compact inline linked proposal summary card
- **Implementation** (`ProjectDetail.tsx`):
  - Added `proposalTone()` and `riskTone()` helper functions (mirrors Proposals.tsx)
  - Modified the "Related learnings" section to show an inline proposal summary card instead of just a button when a primary linked proposal exists
  - The card displays: proposal kind pill, risk level pill, title, truncated rationale, confidence pill, and primary impacted asset
  - Card is clickable and navigates to the proposal detail when clicked
  - Added a secondary "View more proposals" button when there are additional linked proposals beyond the primary one
- **Verification**:
  - `npm --prefix desktop run build` - passed

---

## Changed Files

- `desktop/src/pages/ProjectDetail.tsx` - Added inline proposal summary card for "Related learnings" section
- `docs/superpowers/tasks/2026-05-10-sarathi-desktop-next.md` - Updated task log
