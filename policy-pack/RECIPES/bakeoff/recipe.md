# Bakeoff Recipe

Compare two native CLI providers (codex and opencode) in isolated git worktrees,
verify each candidate with the pack's test commands, then run a cross-provider
JUDGE to pick the winner based on measured evidence (tests passed, diff size, cost).

The static workflow declares a `fanout` node that spawns branches for codex and
opencode in separate worktrees, a `verify` node that runs tests against each
candidate, and a `judge` node that compares the results on measured signals.
Every dispatch records a `UsageRecord` for cost and performance tracking.

```yaml
name: Bakeoff
key: bakeoff
description: Compare codex vs opencode in isolated worktrees with verified evidence and judged merge.
providers:
  - codex
  - opencode
workflow:
  nodes:
    - id: fanout
      title: Generate candidates in isolated worktrees
      node_type: fanout
      depends_on: []
      pattern_config:
        count: 2
        providers: [codex, opencode]
        title_template: "Candidate {i}: {provider}"
        synthesize_title: "Collect verified candidates"
    - id: verify
      title: Verify each candidate with test suite
      node_type: execute
      depends_on: [fanout-synthesize]
    - id: judge
      title: Cross-provider comparison and merge decision
      node_type: judge
      depends_on: [verify]
```
