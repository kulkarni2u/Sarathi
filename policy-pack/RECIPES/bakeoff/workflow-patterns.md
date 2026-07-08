# Workflow Patterns

Enables the patterns this recipe pack relies on: fan-out-and-synthesize (for
parallel candidate work in isolated worktrees) and adversarial-verification
(for the JUDGE node that compares candidates on measured evidence).

When HarnessConfig declares `isolation_mode="worktree"` (set by the policy
compiler or ROUTE phase), each fanout branch runs in an isolated git worktree
under `.sarathi/worktrees/<task_id>/<node_id>/` with its own shallow index.
After all branches complete, the VERIFY node runs the pack's test commands
against each retained candidate, and the JUDGE node picks the winner based on
test pass rate, diff size, and token cost.

## Patterns

```yaml
patterns:

  # Classify-And-Act — always on; used by the Route phase.
  classify_and_act:
    enabled: true

  # Fanout-And-Synthesize — required: the recipe fans branch work across codex/opencode.
  fanout_and_synthesize:
    enabled: true
    max_branches: 2

  # Adversarial Verification — required: the JUDGE node reviews measured evidence.
  adversarial_verification:
    enabled: true
    verifier_count: 2
    pass_threshold: 2

  # Generate-And-Filter — off.
  generate_and_filter:
    enabled: false
    generator_count: 4
    min_score: 0.7

  # Tournament — off.
  tournament:
    enabled: false
    attempts: 4
    judge_rounds: 2

  # Loop-Until-Done — on; used by the Verify phase auto-recovery.
  loop_until_done:
    enabled: true
    max_iterations: 5
    condition_key: new_findings
```

## Worktree Isolation

Fanout branches run in isolated git worktrees when `HarnessConfig.isolation_mode`
is set to `"worktree"`. Set this in the ROUTE phase policy compiler or via
explicit HarnessConfig instantiation when dispatching the recipe. The graph
executor will:

1. Create a worktree for each branch at `.sarathi/worktrees/<task_id>/<node_id>/`
2. Set `DispatchRequest.constraints["isolation_mode"] = "worktree"`
3. Invoke the provider CLI bridge with `--workspace-root` set to the worktree path
4. Clean up worktrees after the task (or retain them if `isolation_cleanup: manual`)

For example:

```python
from src.harness import HarnessConfig
from src.runtime.graph_executor import TaskGraphExecutor

harness = HarnessConfig(
    task_id="bake-1",
    isolation_mode="worktree",  # Enable per-branch isolation
    isolation_cleanup="auto",    # Clean up after task (or "manual" to retain)
)
executor = TaskGraphExecutor(
    harness_config=harness,
    isolation_repo_root="/path/to/repo",
)
```
