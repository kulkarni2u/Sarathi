# Commands Policy

Shell commands Sarathi may run for this repository. The Verify phase only
executes `test.command` when `SARATHI_EXEC_COMMANDS=1` is set; otherwise the
phase reports `unverified`. Build and test commands run in each isolated worktree.

```yaml
build:
  command: "python3 -m pip install -e ."
  timeout_seconds: 600

test:
  command: "python3 -m pytest -q"
  timeout_seconds: 600
```
