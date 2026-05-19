# Sarathi Knowledge And Skills Information Architecture

Date: 2026-05-18

Owner role: Product Designer

Status: Proposed IA decision

## 1. Decision Summary

Sarathi should not keep `Knowledge`, `Wiki`, `Context`, and `Proposals` as separate peer-level top-nav concepts forever.

The cleaner model is:

- `Knowledge Center` = workspace context, memory, docs, learnings, proposals, and compiled context visibility
- `Skills` = execution behavior, skill packs, routing, role mappings, and skill evolution

`Wiki` should remain a real product surface, but it should become a section inside `Knowledge Center`, not a competing top-level concept.

## 2. Why This Matters

Today the product is drifting toward five adjacent library surfaces:

- Knowledge
- Wiki
- Skills
- Context
- Proposals

That is too many top-level nouns for one underlying mental model.

Users should not have to infer whether a workspace rule belongs in:

- a wiki page
- a skill
- a proposal
- a context bundle

Sarathi should make the distinction explicit:

- `Knowledge` tells the system what the workspace knows
- `Skills` tells the system how to act

## 3. Object Model

### Knowledge Center owns

- `workspace_guide`
- `wiki_page`
- `learning_record`
- `knowledge_document`
- `proposal`
- `context_bundle`
- `retrieval_hit`

### Skills owns

- `skill_pack`
- `skill_family`
- `task_type_route`
- `role_mapping`
- `skill_version`
- `skill_proposal`

## 4. User Questions Each Surface Must Answer

### Knowledge Center

This surface should answer:

- What does this workspace know?
- Which guide and wiki documents are missing?
- What learnings are available for reuse?
- What proposals are waiting for review?
- What context did Sarathi actually send to agents?
- Which sources were selected or omitted?

### Skills

This surface should answer:

- Which skills exist in this workspace?
- Which task types route to which skill families or providers?
- Which role instructions affect behavior?
- Which skill changes are proposed?
- Why did a routing rule or skill pack change?

## 5. Recommended Navigation Model

### Left nav

Keep top-level nav compact:

- Workspace
- Dashboard
- Inbox
- Agents
- Knowledge Center
- Skills
- Settings

### Remove as peer-level top-nav over time

- Wiki
- Context
- Proposals

Those should become internal sections or tabs.

## 6. Knowledge Center Internal IA

The `Knowledge Center` page should become the home for workspace intelligence.

Recommended internal tabs or segmented navigation:

1. `Overview`
   - guide health
   - wiki coverage
   - learnings summary
   - pending proposals
   - recent context bundles

2. `Wiki`
   - page browser
   - page editor
   - provenance and page status

3. `Context`
   - context bundles
   - selected sources
   - token budget posture
   - omitted sections

4. `Proposals`
   - pending/accepted/rejected evolution proposals
   - diff preview
   - risk and impacted assets

5. `Learnings`
   - accepted learnings
   - promoted playbooks
   - reuse provenance

## 7. Skills Internal IA

The `Skills` surface should become the behavior studio.

Recommended internal tabs or segmented navigation:

1. `Registry`
   - skill families
   - installed skills
   - source and provenance

2. `Routing`
   - task-type routing rules
   - guided editor
   - raw source fallback

3. `Roles`
   - role-to-skill mapping
   - provider preferences
   - phase and workflow behavior

4. `Evolution`
   - skill-specific proposals
   - routing proposals
   - accepted changes history

## 8. Screen Responsibilities

### Knowledge Center overview

This should be summary-first and operational:

- not a document editor
- not a long list of pages
- not a raw artifact browser

It should route the user into the correct knowledge workflow quickly.

### Wiki

The wiki should stay editable, but it should be positioned as governed workspace knowledge.

It should eventually support:

- page provenance
- proposal-backed edits
- generated-vs-human-authored markers
- section-level diff review

### Context inspector

This should not feel like a separate product forever.

It belongs inside Knowledge Center because it explains how Sarathi used workspace knowledge in actual dispatches.

### Proposals

Proposals are cross-cutting, but they conceptually belong under Knowledge Center first because they are the review surface for workspace self-evolution.

The Skills page can still deep-link into filtered skill proposals.

## 9. What Not To Do

- Do not merge Knowledge and Skills into one long page.
- Do not keep Wiki as a fully separate top-level destination forever.
- Do not make Context Inspector feel like an operator-only debug tool.
- Do not leave Proposals floating as an orphan noun without its parent model.
- Do not treat raw markdown editing as the final Skill Studio interaction model.

## 10. Minimal Implementation Path

### Slice 1

Change the IA without destabilizing the product:

- rename nav `Knowledge` to `Knowledge Center`
- keep current route IDs working
- make the Knowledge Center page show internal section entry cards:
  - Wiki
  - Context
  - Proposals
  - Learnings

### Slice 2

Move from sibling routes to sectional navigation:

- add local section tabs inside Knowledge Center
- treat `wiki`, `context`, and `proposals` as subroutes or internal panels
- keep deep links for direct access during migration

### Slice 3

Deepen Skills into a real studio:

- registry
- routing
- roles
- evolution

### Slice 4

Add provenance-aware review flows:

- wiki proposal diff review
- skill proposal diff review
- context-compiler proposal review

## 11. Acceptance Criteria

- Users can explain the difference between `Knowledge Center` and `Skills` in one sentence each.
- `Wiki`, `Context`, and `Proposals` no longer feel like overlapping top-level concepts.
- The Knowledge Center home summarizes knowledge health before the user drills down.
- Skills clearly reads as the place where Sarathi behavior is defined and reviewed.
- Proposal review remains visible and attributable across knowledge and skills evolution.

## 12. Recommended Next Build

The next UI slice should not add more peer-level pages.

It should:

1. keep `Skills` as a top-level surface
2. treat `Knowledge Center` as the parent of `Wiki`, `Context`, and `Proposals`
3. implement internal section navigation inside `Knowledge Center`
4. leave deep-link compatibility in place while the nav transitions
