# Sarathi Provider-Agnostic Token Budget Design

Owner: Sarathi orchestrator workspace
Date: 2026-05-06

## Goal

Sarathi should track token budgets and usage in a provider-agnostic way so the orchestrator can stay token-efficient across Claude, Codex, OpenCode, and any future provider. The budget model should be compact, normalized, and usable both for live supervision and for policy routing.

The feature is not meant to expose long transcripts or provider-specific accounting details. It is meant to answer one question quickly: are we still within budget, and if not, what should Sarathi do next?

## Design Principles

1. Provider agnostic
   - A provider may be native CLI, HTTP bridge, command adapter, or future custom adapter.
   - Sarathi should normalize usage into the same schema regardless of provider family.

2. Reported or estimated
   - If the provider reports token usage, store it directly.
   - If the provider does not report usage, store an estimate and mark it as estimated.
   - The system should always have a usable budget signal, even when provider telemetry is partial.

3. Compact by default
   - Status output should show a single budget line, not a detailed accounting dump.
   - Task panel entries should surface only the warning state and a short summary.

4. Budget-aware orchestration
   - Budget state should influence routing, retries, and escalation.
   - Sarathi should prefer smaller or cheaper providers when a task is nearing its budget limit, if policy allows that.

## Canonical Usage Schema

Every dispatch should be able to record a normalized usage object:

- `provider_id`
- `provider_family`
- `dispatch_id`
- `input_tokens`
- `output_tokens`
- `total_tokens`
- `estimated`
- `budget_limit`
- `budget_remaining`
- `budget_state`
- `usage_source`

Field rules:

- `provider_id` is the concrete adapter name, such as `claude`, `codex`, `opencode`, or `local`.
- `provider_family` groups equivalent dispatch paths when useful.
- `estimated` is `true` when token counts are inferred rather than reported.
- `usage_source` must be one of `reported`, `estimated`, or `mixed`.
- `budget_state` must be one of `ok`, `warning`, `near_limit`, `exhausted`, or `unknown`.

## Budget Scopes

Budgets should work at three scopes:

1. Dispatch scope
   - One execution by one provider.
   - Used to decide whether a single run is too large.

2. Task scope
   - Aggregate usage for the whole task or task graph.
   - Used to supervise long-running work and child tasks.

3. Workspace scope
   - Aggregate usage for the workspace.
   - Used to prevent runaway orchestration across many tasks.

Policy may define any or all of these scopes. If a scope is absent, Sarathi should still track usage and show it in status output without enforcing a hard stop.

## Data Flow

1. Sarathi dispatches work to a provider adapter.
2. The adapter returns a normalized response.
3. Sarathi records usage on the dispatch record, or on the task graph if dispatch-level usage is unavailable.
4. The CLI and task panel render a compact budget summary.
5. If the budget state crosses a threshold, Sarathi can reroute, pause, or escalate based on policy.

## CLI and UI Surfaces

### `sarathi status <task_id>`

Print a compact usage line such as:

- `tokens: 12.4k / 20k`
- `budget: warning`
- `usage source: reported`

### `sarathi watch <task_id>`

Watch should show budget changes as state transitions, not as a live accounting dump. Examples:

- `tokens: 12.4k / 20k`
- `budget: near_limit`
- `next action: finish build before retrying`

### Desktop task panel

The task panel should expose the same compact budget line as a status chip or short row in the evidence/events area. It should not show raw token-by-token logs.

## Provider Adapter Contract

Provider adapters should not need to know the whole budget system. They only need a way to return usage when available.

Expected adapter behavior:

- report usage if the provider exposes it
- set `estimated=false` when usage is reported
- allow Sarathi to estimate usage when the provider cannot report it
- preserve provider identity and family for later analysis

The contract should remain stable so new providers can plug in without changing the budget model.

## Budget Actions

When budget pressure is detected, Sarathi can:

- continue if policy says the task is still safe
- warn the user that the task is nearing a limit
- reduce context or send a smaller follow-up prompt
- reroute future work to a cheaper provider if policy allows
- pause and ask for human approval if the budget is exhausted

These actions should be policy-driven, not hard-coded to a provider name.

## Non-Goals

- Full transcript accounting
- Provider-specific billing dashboards
- Detailed per-message token inspection in the UI
- A separate budget system that bypasses the existing task graph or dispatch records

## Current Gap Summary

Sarathi already has the right architecture for budgets and retry limits, but the token signal is not yet standardized as a first-class provider-agnostic usage record. This design fills that gap by making token tracking:

- generic across providers
- compact in the UI and CLI
- useful even when the provider only gives partial telemetry
- suitable for orchestration decisions without creating prompt bloat

That keeps Claude, Codex, OpenCode, and future providers on the same supervision contract.
