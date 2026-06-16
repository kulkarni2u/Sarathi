# Sarathi Repo Wiki Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Sarathi-native, language-agnostic repo wiki generator that writes `.sarathi/wiki/` and runs from `sarathi init`.

**Architecture:** Implement a small `src/repo_wiki/` package that inventories a repository, enriches known languages with standard-library text parsing, and renders Markdown plus JSON. Wire it into `sarathi wiki` and `sarathi init --no-wiki`.

**Tech Stack:** Python standard library, argparse CLI, pytest.

---

### Task 1: Repo Wiki Generator

**Files:**
- Create: `src/repo_wiki/__init__.py`
- Create: `src/repo_wiki/generator.py`
- Create: `tests/test_repo_wiki.py`

- [ ] Write failing tests for wiki file creation, Java extraction, and write safety.
- [ ] Run `python3 -m pytest tests/test_repo_wiki.py -q` and confirm failures.
- [ ] Implement standard-library inventory, renderers, and generated-file overwrite rules.
- [ ] Run `python3 -m pytest tests/test_repo_wiki.py -q` and confirm pass.

### Task 2: CLI Integration

**Files:**
- Modify: `src/cli.py`
- Modify: `tests/test_repo_wiki.py`

- [ ] Write failing tests for `sarathi wiki`, `sarathi wiki --check`, `sarathi init` wiki generation, and `sarathi init --no-wiki`.
- [ ] Run targeted tests and confirm failures.
- [ ] Add CLI parser entries and handlers.
- [ ] Add init-time wiki generation after policy-pack generation.
- [ ] Run targeted tests and confirm pass.

### Task 3: Skill Pack And Docs

**Files:**
- Create: `skill/reference/repo-wiki.md`
- Modify: `skill/SKILL.md`
- Modify: `README.md`

- [ ] Add a concise agent-facing reference for `.sarathi/wiki/`.
- [ ] Link it from the portable Sarathi skill.
- [ ] Document `sarathi wiki` and init-time wiki generation in README.
- [ ] Run focused docs/package tests if available.

### Task 4: Verification

**Files:**
- No new files.

- [ ] Run `python3 -m pytest tests/test_repo_wiki.py tests/test_cli.py -q`.
- [ ] Run `python3 -m pytest -q`.
- [ ] Run `python3 -m build --sdist --wheel`.
- [ ] Report any failures or skipped checks clearly.
