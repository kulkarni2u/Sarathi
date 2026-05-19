# Sarathi Provider SDK Runtime Design

Owner: Sarathi orchestrator workspace
Date: 2026-05-13

## Goal

Move Sarathi from CLI-first provider transport toward SDK-first provider transport while preserving Sarathi-owned orchestration, approvals, checkpoints, evidence, and handoff logic.

Sarathi should treat provider SDKs as execution backends, not as the product model.

## Why This Slice Exists

The desktop/control-tower layer is now strong enough that the main architectural weakness is provider transport inconsistency:

- current live provider execution is still heavily CLI-bridge-oriented
- provider capabilities are not represented explicitly enough
- session/resume/interrupt semantics are not normalized
- runtime behavior differs more by provider transport than by Sarathi policy

The next release-quality step is to make provider runtime behavior a first-class subsystem.

## Current State

Sarathi already has a useful foundation:

- `src/runtime/providers/base.py`
  - `ProviderAdapter`
- `src/runtime/providers/configured.py`
  - deterministic external/command adapters
- `src/runtime/providers/cli_bridge.py`
  - native CLI bridges for Codex, Claude, Copilot, and OpenCode
- `src/dispatch.py`
  - `LocalDispatcher` delegating to provider adapters

This means the migration does not require a brand-new abstraction. It requires deepening the existing provider seam.

## Design Principles

1. SDK first, CLI second
   - Prefer official SDK or API integrations where they exist.
   - Keep CLI bridges only as fallback or compatibility adapters.

2. Sarathi owns orchestration
   - approvals
   - checkpoints
   - handoffs
   - audit
   - evidence
   - graph state
   - retry / reroute / recovery

3. Provider neutral task truth
   - provider transport must not redefine the task lifecycle
   - Sarathi state remains canonical even when providers differ

4. Capabilities must be explicit
   - not every provider supports the same runtime behaviors
   - the UI and orchestration policy should know those differences

5. Session-oriented runtime
   - move beyond one-shot dispatch where possible
   - allow future support for streaming, interrupt, resume, and richer event surfaces

## Proposed Architecture

### Layer 1: Provider Capability Model

Each provider adapter should expose structured capability metadata, for example:

- `transport_kind`
  - `sdk`
  - `api`
  - `cli`
- `supports_streaming`
- `supports_tool_calls`
- `supports_interrupt`
- `supports_resume`
- `supports_session_persistence`
- `supports_workspace_execution`
- `supports_structured_output`
- `supports_human_approval_callbacks`

Sarathi uses this to:

- route work safely
- choose fallback posture
- explain degraded states in desktop surfaces

### Layer 2: Session-Oriented Provider Runtime

Extend the current provider model from simple dispatch-only behavior toward session-aware runtime behavior:

- `create_session`
- `send_input`
- `stream_events`
- `wait`
- `interrupt`
- `resume`
- `close`

Dispatch-only providers can still exist, but should be treated as a constrained subset.

### Layer 3: Sarathi-Normalized Runtime Objects

Normalize provider responses into Sarathi-native artifacts:

- `Run`
- `RunEvent`
- `RunMessage`
- `ToolCall`
- `ApprovalRequest`
- `CheckpointHint`
- `HandoffHint`
- `UsageRecord`

This is important because the desktop and CLI should render Sarathi objects, not raw provider payloads.

### Layer 4: Fallback Adapters

Keep these adapters available:

- `LegacyCliRuntime`
- `NativeCliBridgeProvider`

They should be explicitly marked as compatibility transport, not default transport.

## Provider Mapping

### OpenAI / Codex

Preferred transport:

- OpenAI SDK / Responses API / Agents SDK

Use for:

- structured model execution
- future session-oriented orchestration
- tool/event normalization

### Claude / Anthropic

Preferred transport:

- Anthropic SDK
- Claude Code SDK where code-agent behavior is needed

Use for:

- structured execution
- future code-agent session continuity

### OpenCode

Preferred transport:

- OpenCode SDK

Use for:

- local agent execution with better session control than shelling out blindly

### Copilot

Preferred transport:

- Copilot SDK / custom agents integration

Use only when we intentionally need GitHub-native agent participation.

## What Sarathi Must Keep Owning

Even after SDK migration, these should remain Sarathi responsibilities:

- graph approval
- PRD / AC approval
- repository action approval
- evidence requirements
- review gate enforcement
- handoff readiness
- checkpoint creation and restart
- audit trails
- policy-pack evaluation

Provider SDKs should supply execution and events, not product truth.

## Data Model Implications

Sarathi persistence should store provider-neutral runtime identity:

- `provider_name`
- `provider_transport_kind`
- `provider_session_id`
- `provider_run_id`
- `provider_event_cursor`
- `capability_snapshot`
- `last_runtime_state`
- `degraded_reason`

This will let the desktop show:

- whether a run is live
- whether resume is possible
- whether a fallback path was used
- whether the current provider can be interrupted or rerouted

## UI / Product Implications

The desktop should eventually show provider-runtime posture in:

- `Settings`
  - provider card shows `SDK`, `API`, or `CLI fallback`
- `Agents`
  - runtime capability and degraded state
- `Task Studio`
  - whether the current run can be resumed, interrupted, or rerouted
- `Inbox`
  - provider-failure items should distinguish transport failure vs work failure

## Migration Rule

Do not rewrite the whole orchestration engine around provider SDKs.

Instead:

1. preserve the current provider adapter seam
2. enrich it with capability and session concepts
3. migrate one provider at a time behind the same Sarathi-owned contracts

## Definition of Done for This Architecture

This slice is successful when:

- Sarathi can use SDK-backed runtimes without changing task lifecycle semantics
- CLI bridges are optional fallback, not the default design center
- provider capability differences are explicit in code
- the desktop can expose degraded / fallback runtime posture truthfully

