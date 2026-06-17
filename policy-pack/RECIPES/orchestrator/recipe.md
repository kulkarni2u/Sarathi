# Orchestrator Recipe

Plan, fan out implementation across two providers in parallel, then run a
cross-provider JUDGE before merge.

The static workflow declares three nodes: `plan` → `fanout` → `judge`. At
runtime the executor injects the fan-out branch children (one per provider) and
a SYNTHESIZE fan-in node (`fanout-synthesize`) that merges the branch results.
The `judge` node depends on that injected synthesize node, so it reviews the
merged candidate implementations across providers. Every dispatch records a
`UsageRecord`, so the final result is judged, merged, and measured.

```yaml
name: Orchestrator
key: orchestrator
description: Plan, fan out implementation across two providers in parallel, then cross-provider judge before merge.
providers:
  - provider-a
  - provider-b
workflow:
  nodes:
    - id: plan
      title: Decompose the task into a plan
      node_type: execute
    - id: fanout
      title: Implement across providers
      node_type: fanout
      depends_on: [plan]
      pattern_config:
        count: 2
        providers: [provider-a, provider-b]
        title_template: "Branch {i}: candidate implementation"
        synthesize_title: "Merge candidate implementations"
    - id: judge
      title: Cross-provider review of merged result
      node_type: judge
      depends_on: [fanout-synthesize]
```
