# Sarathi Auto-Approve Policy Contract Design

Date: 2026-05-09

## Goal

Define a real policy-backed `auto_approve_preference` contract for Sarathi so any future desktop control is governed, persisted, validated, and auditable.

This design is intentionally backend-first. The desktop must not expose an auto-approve toggle until this contract exists.

## Problem

Sarathi already has:

- approval gates
- a `POST /api/tasks/{id}/auto-approve` endpoint
- strong precedent for governed preferences via `repository_action_preference`

But it does **not** yet have:

- a persisted auto-approve preference model
- a policy-pack section defining allowed auto-approve posture
- backend validation that consults policy before auto-approving gates

Without that contract, a desktop control would be UI-deep and would effectively create a loose “skip approvals” shortcut.

## Design Principles

- Default to manual approval.
- Auto-approve must be policy-bounded, not purely user-bounded.
- Repository safety and human review remain first-class.
- Every auto-approved decision must remain visible in history.
- The model should mirror the shape and precedence style of `repository_action_preference` where practical.

## Proposed Contract

### Preference name

`auto_approve_preference`

### Persistence locations

- workspace metadata
- optionally project/task metadata later if needed

Initial implementation should support workspace scope first.

### Shape

```json
{
  "scope": "workspace",
  "mode": "manual_only",
  "allowed_modes": [
    "manual_only",
    "below_threshold"
  ],
  "threshold": {
    "complexity": "low",
    "max_node_count": 3
  }
}
```

### Fields

- `scope`
  - `default` | `workspace` | `project` | `task`
- `mode`
  - `manual_only`
  - `below_threshold`
  - optional future mode: `policy_defined`
- `allowed_modes`
  - list of modes permitted by policy
- `threshold`
  - optional object used only when `mode == "below_threshold"`
  - initial bounded fields:
    - `complexity`: `low` | `medium`
    - `max_node_count`: integer

## Policy-Pack Contract

Add a new policy-pack section, preferably:

- `policy-pack/approval.md`

This section should define:

- default mode
- allowed modes
- permitted threshold bounds
- gate classes that may never be auto-approved

Example policy concept:

```md
# Approval Policy

default_mode: manual_only
allowed_modes:
  - manual_only
  - below_threshold

max_threshold:
  complexity: low
  max_node_count: 3

never_auto_approve_gates:
  - PRD/AC
  - Repository action
  - Final handoff
```

## Backend Requirements

### Normalization helpers

Add helpers analogous to repository action preference handling:

- `_default_auto_approve_preference()`
- `_normalize_auto_approve_preference()`
- `_effective_auto_approve_preference()`

### Enforcement

`POST /api/tasks/{id}/auto-approve` must:

1. load the effective preference
2. refuse when `mode == manual_only`
3. refuse when the target gates are in the denylist
4. refuse when threshold conditions are not satisfied
5. record auto-approved decisions in lifecycle history with explicit metadata

### Event / audit payload

Auto-approved gate events should include:

- `auto_approved: true`
- `preference_scope`
- `preference_mode`
- `policy_source`
- `threshold_evaluation`

## Desktop Implications

Only after backend support exists should `Settings` expose:

- current auto-approve posture
- why the mode is allowed or disallowed
- threshold summary when applicable

The desktop should not present this as a convenience toggle. It should read as workflow governance.

## Non-Goals

- provider transport changes
- blanket approval skipping
- per-user personal overrides without policy support
- auto-approving repository-action or final governance gates

## Implementation Order

1. Add `policy-pack/approval.md` contract.
2. Add backend preference model and normalization.
3. Enforce preference in `POST /api/tasks/{id}/auto-approve`.
4. Add tests for manual-only, threshold-allowed, and denylisted gates.
5. Only then add the Settings surface.

## Acceptance

- Auto-approve is impossible unless policy explicitly permits it.
- Manual-only is the safe default.
- Denylisted gates cannot be auto-approved.
- Every auto-approved decision is auditable in history.
- The desktop reflects backend truth instead of inventing policy.
