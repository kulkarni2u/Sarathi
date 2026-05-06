# Sarathi CLI Default Home and Quiet Startup Design

Owner: Sarathi orchestrator workspace
Date: 2026-05-06

## Goal

Sarathi CLI should feel ready to orchestrate work when launched with no arguments. Instead of printing a noisy warning and exiting with `No command specified`, the default entrypoint should open a calm CLI home experience that surfaces the most useful next actions.

This is about the first impression of Sarathi CLI:

- quiet startup
- no hard failure on bare `sarathi`
- quick access to chat, status, run, resume, and workspace actions
- provider warnings only when they matter for the chosen action

## Design Principles

1. Quiet by default
   - Do not print startup warnings unless they are relevant to the current command.
   - Avoid cluttering the first screen with env diagnostics unless the user is trying to run a provider-backed action.

2. Helpful on bare launch
   - `sarathi` with no subcommand should show an interactive home instead of an error.
   - The home should make it obvious how to start a task, inspect status, or resume work.

3. OpenCode-like feel
   - The CLI should feel like an orchestrator shell, not a strict argument parser.
   - The user should be able to enter the product from the command line without memorizing subcommands first.

4. Token-efficient guidance
   - If the CLI needs to explain itself, keep the copy short.
   - Prefer one-screen guidance and direct actions over long help text.

## User-Facing Behavior

When the user runs `sarathi` with no arguments:

- show a branded but compact home screen
- list the primary actions:
  - `chat`
  - `run`
  - `status`
  - `resume`
  - `new workspace`
- provide one-line hints for each action
- do not print `No command specified`

When the user runs a provider-backed command, such as `run`, `chat`, or a checkpoint restart:

- only show provider/environment warnings if they block or alter that action
- keep non-blocking hints out of the main path

## CLI Home Model

The default home can be implemented as a small command router or an interactive prompt. The important requirement is that the top-level `sarathi` entry becomes a useful starting place, not an error.

Recommended home sections:

- current workspace or `no workspace selected`
- recent task / checkpoint shortcut if available
- primary actions
- one short tip on how to start

Recommended action labels:

- `chat` - start brainstorming or create a task
- `run` - execute a task through Sarathi
- `status` - inspect task progress
- `resume` - continue a saved task
- `new workspace` - create or select a workspace

## Startup Warning Rules

- Do not show `Tip: OpenAI is active but OPENAI_API_KEY is not set` on every startup.
- Show provider auth warnings only when the user invokes a provider-dependent command and that provider is actually needed.
- If a warning is shown, keep it short and action-oriented.

## Data Flow

1. User runs `sarathi` with no args.
2. CLI resolves the default home view.
3. The home view shows the calm action set and current context.
4. If the user picks an action, Sarathi routes into the existing command flow.
5. If the user explicitly runs a provider-backed action, provider checks happen at that point.

This keeps the default entry experience simple while preserving existing subcommand behavior.

## Error and Safety Rules

- No bare-CLI crash or usage error on `sarathi` with no args.
- Provider warnings must not hide task/workspace context.
- Existing subcommands must continue to work.
- The change must not alter task execution semantics, only the startup and fallback UX.

## Non-Goals

- Rewriting the entire CLI argument system
- Building a graphical UI in the terminal
- Changing Sarathi runtime execution semantics
- Removing subcommands

## Current Gap Summary

Sarathi already has the execution commands it needs. What is missing is the top-level default experience:

- no noisy startup warning
- no `No command specified` error
- a calm, useful home screen that feels ready to orchestrate work

