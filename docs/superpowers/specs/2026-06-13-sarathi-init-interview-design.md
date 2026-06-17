# Sarathi Init Interview Design

## Goal

Close the gap between what `sarathi init` communicates and what it currently
does. The command should produce a policy pack that reflects the target repo and
the user's delivery preferences, while remaining safe for scripts and CI.

## Current Behavior

`sarathi init` scans the target repository, returns hard-coded interview
defaults, writes policy-pack files, writes provider permission config, validates
the result, and optionally bootstraps NCP. The interview phase is not truly
interactive, and generated policy files overwrite existing files without a
confirmation gate.

## Target Behavior

`sarathi init` should be interactive when attached to a real terminal. In
non-interactive contexts it should keep today's automation-friendly behavior by
using defaults. Users should also be able to force non-interactive behavior with
`--defaults` or `--yes`.

The interactive interview should be short and inspection-driven. It should ask
only for policy choices Sarathi cannot infer confidently:

- Confirm detected build, test, lint, and format commands.
- Capture team conventions when no repo-local convention file gives a clear answer.
- Capture PR and review requirements.
- Capture domain constraints or risk posture.
- Confirm provider permission config writes before touching `.claude/settings.json`,
  `opencode.json`, or global Codex config.
- Preserve existing `policy-pack/*.md` by default unless the user confirms
  overwrite or passes `--force`.

## CLI Contract

- `sarathi init [target_path]`: interactive on TTY, defaults on non-TTY.
- `sarathi init [target_path] --defaults`: use inferred defaults with no prompts.
- `sarathi init [target_path] --yes`: alias for `--defaults` for common CLI ergonomics.
- `sarathi init [target_path] --force`: allow overwriting existing generated files.
- `sarathi init [target_path] --ncp`: keeps the existing NCP behavior, with any
  NCP-related prompt skipped when `--defaults` or non-TTY mode is active.

If `--defaults` or `--yes` conflicts with a future explicitly interactive flag,
the command should fail fast with a clear argument error.

## Policy Generation

The interview result should become structured input to `InitWorkflow.generate`
rather than display-only data. Generated files should include the user's answers
where they materially affect policy:

- `commands.md`: confirmed command strings and timeouts.
- `conventions.md`: team conventions, domain constraints, and evidence style.
- `review.md`: PR/review requirements and quality bars.
- `escalation.md`: risk posture and escalation preferences.
- `permissions.md`: provider permission choices.

Existing files should be preserved unless overwrite is explicitly allowed.
Preserved files should be reported in CLI output so users know what Sarathi did
and did not change.

## Error Handling

- Missing target path remains a non-destructive inspection error.
- Invalid prompt answers re-prompt in TTY mode.
- Non-TTY mode never blocks for input.
- Permission config writes should be reported honestly. If Codex global config is
  skipped because it is user-managed, CLI output should say skipped rather than
  written.
- Validation warnings should remain visible after generation.

## Testing

Add focused regression tests for:

- TTY interactive mode uses answers in generated policy files.
- Non-TTY mode uses defaults without reading stdin.
- `--defaults` and `--yes` do not prompt.
- Existing policy files are preserved by default.
- `--force` overwrites existing policy files.
- Provider permission writes distinguish written versus skipped configs.
- `--ncp` still creates `.ncp` artifacts when NCP is available.

Run targeted tests first, then the broader Sarathi test/build sequence used for
policy-pack surfaces:

```bash
python3 -m pytest tests/test_cli.py tests/test_workspace_intake.py tests/test_policy_runtime.py -q
python3 -m pytest -q
python3 -m build --sdist --wheel
```

## Out Of Scope

- A full desktop/TUI onboarding wizard.
- LLM-generated interview questions.
- Reworking validation semantics.
- Changing the Sarathi runtime lifecycle outside init.
