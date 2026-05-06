# Sarathi CLI Default Home and Quiet Startup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `sarathi` with no arguments open a calm, useful home view instead of printing a noisy warning and exiting, while keeping existing subcommands intact.

**Architecture:** Keep the current subcommand execution model, but add a top-level default home path that renders when no command is provided. The home should be short, branded, and action-oriented. Provider/auth warnings should move out of startup and only appear when a provider-backed command needs them.

**Tech Stack:** Python CLI (`src/cli.py`), stdlib `argparse`, existing runtime/provider helpers, Pytest for command-line behavior tests.

---

## File Structure

- Modify: `src/cli.py` to make bare `sarathi` route to a default home handler and to suppress irrelevant startup warnings.
- Modify: `tests/test_service_launcher.py` only if a new CLI smoke test fits there; otherwise add a new CLI-focused test file.
- Create: `tests/test_cli_default_home.py` if that keeps the startup behavior isolated and easy to verify.

## Task 1: Add a failing test for bare `sarathi`

**Files:**
- Create: `tests/test_cli_default_home.py`
- Modify: `src/cli.py`

- [ ] **Step 1: Write the failing CLI test**

```python
import subprocess
import sys


def test_cli_with_no_arguments_shows_default_home():
    result = subprocess.run(
        [sys.executable, "-m", "src.cli"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Sarathi" in result.stdout
    assert "chat" in result.stdout.lower()
    assert "status" in result.stdout.lower()
    assert "No command specified" not in result.stdout
```

Run: `cd /Users/sweethome/Work/Skills/Sarathi && python3 -m pytest tests/test_cli_default_home.py -v`
Expected: fail because the parser currently requires a subcommand.

- [ ] **Step 2: Add a second test for provider-warning suppression**

```python
def test_cli_help_does_not_print_openai_key_warning():
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "OPENAI_API_KEY is not set" not in result.stdout
```

Run: `cd /Users/sweethome/Work/Skills/Sarathi && python3 -m pytest tests/test_cli_default_home.py -v`
Expected: both tests fail until the CLI default path is implemented.

## Task 2: Implement a quiet default home in `src/cli.py`

**Files:**
- Modify: `src/cli.py`
- Modify: `tests/test_cli_default_home.py`

- [ ] **Step 1: Replace the required subparser behavior with a default home path**

Use `required=False` on the subparser collection and add a `handle_home()` function that prints a compact landing view when no command is supplied.

```python
def handle_home() -> None:
    print("S A R A T H I  -  Your AI Charioteer")
    print("")
    print("Workspace: no workspace selected")
    print("Actions:")
    print("  chat         start brainstorming or create a task")
    print("  run          execute a task through Sarathi")
    print("  status       inspect task progress")
    print("  resume       continue a saved task")
    print("  new workspace create or select a workspace")
```

Route `args.command is None` to `handle_home()` instead of raising a usage error.

- [ ] **Step 2: Remove the always-on startup warning**

The startup banner should no longer print `Tip: OpenAI is active but OPENAI_API_KEY is not set.` by default. Any provider/auth warning should be deferred to the command that actually needs it.

- [ ] **Step 3: Keep all existing subcommands working**

`init`, `validate`, `run`, `log`, `status`, `watch`, `resume`, `list`, `proposals`, and `agents` should continue to dispatch exactly as they do today.

- [ ] **Step 4: Re-run the CLI tests**

Run: `cd /Users/sweethome/Work/Skills/Sarathi && python3 -m pytest tests/test_cli_default_home.py -v`
Expected: PASS.

## Task 3: Add a smoke check for the current command set

**Files:**
- Modify: `tests/test_cli_default_home.py`

- [ ] **Step 1: Add a subcommand preservation test**

```python
def test_cli_help_still_lists_existing_subcommands():
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    for command in ["init", "validate", "run", "status", "watch", "resume", "list", "proposals", "agents"]:
        assert command in result.stdout
```

- [ ] **Step 2: Re-run the CLI tests**

Run: `cd /Users/sweethome/Work/Skills/Sarathi && python3 -m pytest tests/test_cli_default_home.py -v`
Expected: PASS.

## Spec Coverage Check

- Quiet by default: Task 2 removes the always-on warning.
- Helpful on bare launch: Task 1 and Task 2 add the default home.
- OpenCode-like feel: Task 2 routes bare `sarathi` into an action-oriented landing view.
- Token-efficient guidance: Task 2 keeps the copy short and direct.
- Error and safety rules: Task 2 preserves the existing commands and changes only startup UX.

## Notes for Implementers

- Keep the default home small and readable; this is not a full TUI.
- Do not change runtime/task semantics or provider dispatch logic in this slice.
- The worker should preserve the current subcommand behavior and only adjust the top-level fallback.

