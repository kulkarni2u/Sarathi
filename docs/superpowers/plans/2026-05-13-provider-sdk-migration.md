# Sarathi Provider SDK Migration Plan

Date: 2026-05-13

## Goal

Implement the first provider-runtime migration slice so Sarathi can evolve from CLI bridges to SDK-backed runtimes without breaking the current orchestration model.

## Strategy

Use the existing `ProviderAdapter` seam and extend it in small, safe steps.

Do not start with provider-specific rewrites. Start with capability and runtime contracts that all providers can share.

## Milestone 1: Runtime Contract Hardening

Files:

- `src/runtime/providers/base.py`
- `src/runtime/contracts.py`
- `src/dispatch.py`
- `tests/*` as needed

Tasks:

- [x] add provider capability metadata
- [x] add a session/runtime-oriented interface beside dispatch-only behavior
- [x] preserve backward compatibility for current adapters
- [x] add tests proving dispatch-only adapters still work

Definition of done:

- current local + command adapters still function
- capabilities are available to callers
- no desktop regressions

Verification completed on 2026-05-13:

- `python3.11 -m pytest tests/test_dispatch.py tests/test_provider_dispatch.py -v`

## Milestone 2: CLI Bridge Demotion

Files:

- `src/runtime/providers/cli_bridge.py`
- `src/runtime/providers/configured.py`
- `src/runtime/providers/__init__.py`

Tasks:

- [x] reframe CLI bridge as fallback transport in service posture
- [x] label CLI adapters explicitly with transport kind = `cli`
- [x] normalize failure/degraded metadata for desktop/telemetry use

Definition of done:

- provider transport kind is explicit
- fallback behavior is visible in artifacts

Verification completed on 2026-05-13:

- `python3.11 -m pytest tests/test_provider_dispatch.py -v`
- `python3.11 -m pytest tests/test_dispatch.py tests/test_provider_dispatch.py -v`

## Milestone 3: First SDK Runtime

Recommended first provider:

- `OpenCode` or `OpenAI`

Files:

- new adapter module under `src/runtime/providers/`
- provider config handling
- tests

Tasks:

- [x] implement one SDK-backed adapter
- [x] map SDK session/run identifiers into Sarathi runtime artifacts
- [x] prove that Sarathi still owns approvals/checkpoints/handoffs

Definition of done:

- one provider runs without shelling out to CLI
- runtime state is normalized into Sarathi contracts

Verification completed on 2026-05-13:

- `python3.11 -m pytest tests/test_dispatch.py tests/test_provider_dispatch.py -v`
- `printf '{}' | node desktop/scripts/opencode-sdk-dispatch.mjs`
- `printf '{}' | node desktop/scripts/openai-sdk-dispatch.mjs`

## Milestone 4: Provider Settings + Desktop Posture

Files:

- `desktop/src/apiClient.ts`
- `desktop/src/pages/Agents.tsx`
- `desktop/src/pages/Settings.tsx`
- `src/service/__init__.py`

Tasks:

- [x] expose transport kind and capability summary through service APIs
- [x] show `SDK`, `API`, or `CLI fallback` posture in desktop provider surfaces
- [x] show degraded provider runtime reasons clearly

Definition of done:

- users can tell how a provider is connected
- degraded transport states are no longer hidden

Verification completed on 2026-05-13:

- `npm --prefix desktop run build`

## Milestone 5: Broader Provider Migration

Recommended order:

1. OpenAI / Codex
2. Claude / Anthropic
3. OpenCode
4. Copilot

This order can change if implementation friction or ROI changes.

## Risks

- mixing provider runtime truth with Sarathi task truth
- partially migrating one provider while desktop assumes capability parity
- over-designing session abstractions before a first SDK adapter is proven

## Guardrails

- no lifecycle changes without tests
- no provider-specific UI assumptions in desktop state labels
- keep CLI fallback paths intact until at least one SDK adapter is stable

## Immediate Next Engineering Task

Completed on 2026-05-13:

- OpenCode migrated to an SDK-first runtime with CLI fallback
- OpenAI / Codex migrated to an SDK-first runtime with CLI fallback
- Claude / Anthropic migrated to an SDK-first runtime with CLI fallback
- workspace settings now expose SDK auth/config for both Codex and Claude

Next:

- migrate Copilot onto a first-class SDK or GitHub-native adapter path
- persist richer provider session lifecycle if we want multi-turn resume instead of single-dispatch sessions
- standardize provider health and credential posture across all remaining adapters

That is the best next code slice because Sarathi now has three SDK-first providers behind one contract, so the remaining leverage is closing the last provider gap and deepening session continuity.
