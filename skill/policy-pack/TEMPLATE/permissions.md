# Permissions

Declares the tool allowlist for each provider Sarathi invokes as a subprocess.
`sarathi init` writes these as provider-native config files so no runtime
permission-bypass flags are needed.

## Provider tool grants

```yaml
permissions:
  # Claude Code: written to .claude/settings.json (permissions.allow)
  claude:
    allowed_tools:
      - Bash
      - Read
      - Write
      - Edit
      - Glob
      - Grep
      - LS
      - WebFetch
      - WebSearch
      - TodoRead
      - TodoWrite

  # Codex: written to ~/.codex/config.yaml
  codex:
    full_auto: true
    disable_sandbox: false  # set true only for fully local, sandbox-by-Sarathi runs

  # OpenCode: written to opencode.json at workspace root
  opencode:
    auto_approve: true
```
