# Contributing to Sarathi

Thanks for contributing. This guide keeps changes predictable and easy to review.

## Development Setup

```bash
git clone https://github.com/kulkarni2u/Sarathi.git
cd Sarathi

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
python3 -m pip install -e ".[dev]"
```

## Run Tests

```bash
pytest -q
```

If you change CLI behavior, run at least one manual check:

```bash
sarathi --help
sarathi validate policy-pack/EXAMPLE
```

## What to Include in a PR

- Clear problem statement
- Minimal, focused code changes
- Tests for behavior changes
- README/docs updates when commands or workflow change

## Coding Guidelines

- Keep the engine policy-driven and tool-agnostic
- Avoid introducing hidden behavior outside policy packs
- Prefer small functions with explicit inputs/outputs
- Keep user-facing CLI messages actionable

## Branch and Commit Guidance

- Branch format: `feature/<short-name>` or `fix/<short-name>`
- Commit messages: short imperative style, for example:
  - `fix: handle missing policy pack on run`
  - `docs: update quickstart for python3`

## Issues and Feature Requests

When filing issues, include:

- OS + Python version
- Exact command run
- Full error output
- Expected vs actual behavior

For feature requests, describe:

- The workflow pain point
- Proposed behavior
- Why policy/config alone cannot solve it
