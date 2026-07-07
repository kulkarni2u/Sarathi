# Model Routing Policy

Which provider executes dispatched work. This recipe pack declares two native
CLI providers (codex and opencode) so the bakeoff can fan out candidate
implementations in parallel worktrees, verify them with the pack's test commands,
and then run a cross-provider JUDGE to pick the winner based on measured signals.

The fanout branches run in isolated git worktrees under `.sarathi/worktrees/`.
Each provider's output is verified independently; the JUDGE compares test pass
rates, diff sizes, and execution costs to pick the strongest candidate.

Replace the `path` values with the actual paths to your installed codex and
opencode CLIs. If a CLI path is unavailable or probe fails, the recipe falls
back to local dispatch.

```yaml
provider: local

providers:
  codex:
    type: command
    command: "python3 -m src.runtime.providers.cli_bridge --provider codex --path /path/to/codex --workspace-root ."
    timeout_seconds: 300
  opencode:
    type: command
    command: "python3 -m src.runtime.providers.cli_bridge --provider opencode --path /path/to/opencode --workspace-root ."
    timeout_seconds: 300
```

## Pricing

Pricing for native CLI providers when token usage is available but cost is not
self-reported by the CLI. The numbers below are illustrative placeholders — set
your own negotiated rates before relying on `cost_usd` for budgeting.

```yaml
pricing:
  codex:
    default: {input_per_mtok: 1.25, output_per_mtok: 10.0}      # placeholder
  opencode:
    default: {input_per_mtok: 0.8, output_per_mtok: 4.0}        # placeholder
```
