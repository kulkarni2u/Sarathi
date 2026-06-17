# Permissions

Declares mode-specific tool permissions for each provider Sarathi invokes as a
subprocess. `sarathi init` writes these as provider-native config files, and
provider dispatch refreshes them from the current Sarathi permission mode.

Sarathi derives the mode from the harness permission scope:

- `read_only` — inspect/search/read only.
- `read_write` — repo file edits plus build/test commands.
- `full` — broad tool use for approved mutation/evolution work.

## Provider tool grants

```yaml
permissions:
  claude:
    modes:
      read_only:
        allowed_tools: [Read, Glob, Grep, LS, WebFetch, WebSearch, TodoRead]
      read_write:
        allowed_tools: [Read, Write, Edit, Glob, Grep, LS, WebFetch, WebSearch, TodoRead, TodoWrite]
      full:
        allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, LS, WebFetch, WebSearch, TodoRead, TodoWrite]

  codex:
    modes:
      read_only:
        full_auto: false
        disable_sandbox: false
      read_write:
        full_auto: true
        disable_sandbox: false
      full:
        full_auto: true
        disable_sandbox: true

  opencode:
    modes:
      read_only:
        permission:
          read: allow
          grep: allow
          glob: allow
          list: allow
      read_write:
        permission:
          read: allow
          grep: allow
          glob: allow
          list: allow
          edit: allow
          write: allow
      full:
        permission:
          read: allow
          grep: allow
          glob: allow
          list: allow
          edit: allow
          write: allow
          bash: allow
```
