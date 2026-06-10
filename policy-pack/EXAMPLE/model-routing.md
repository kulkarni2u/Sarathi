# Model Routing Policy

Which provider executes dispatched work. `local` is the safe deterministic
default; switch to claude / codex / opencode once their CLIs are configured
(see `sarathi providers` in the desktop service).

```yaml
provider: local

# Example per-phase overrides (uncomment and adapt):
# phase_providers:
#   Build: claude
#   Review: codex
```
