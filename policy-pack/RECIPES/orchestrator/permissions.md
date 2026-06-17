# Permissions Policy

Provider-native permission surfaces written by `ensure_provider_permissions`.
Only providers listed here get a config file written.

```yaml
permissions:
  claude:
    modes:
      read_only:
        allowed_tools: [Read, Glob, Grep, LS, TodoRead]
      read_write:
        allowed_tools: [Read, Write, Edit, Glob, Grep, LS, TodoRead, TodoWrite]
      full:
        allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, LS, WebFetch, WebSearch, TodoRead, TodoWrite]
  codex:
    modes:
      read_only: {full_auto: false, disable_sandbox: false}
      read_write: {full_auto: true, disable_sandbox: false}
      full: {full_auto: true, disable_sandbox: true}
  opencode:
    modes:
      read_only:
        permission: {read: allow, grep: allow, glob: allow, list: allow}
      read_write:
        permission: {read: allow, grep: allow, glob: allow, list: allow, edit: allow, write: allow}
      full:
        permission: {read: allow, grep: allow, glob: allow, list: allow, edit: allow, write: allow, bash: allow}
```
