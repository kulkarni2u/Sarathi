# Permissions Policy

Provider-native permission surfaces written by `ensure_provider_permissions`.
Only providers listed here get a config file written.

```yaml
permissions:
  claude:
    allowed_tools:
      - Bash
      - Read
      - Write
      - Edit
      - Glob
      - Grep
```
