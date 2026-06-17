# Debate Recipe

Two providers independently draft answers, then an adversarial judge picks or
merges the strongest.

The static workflow declares a `debate` FANOUT node and a `judge` node. At
runtime the executor injects one branch per provider plus a `debate-synthesize`
fan-in node that collects the drafts; the `judge` node depends on it and runs
the adversarial judgment. Every dispatch records a `UsageRecord` for a measured
result.

```yaml
name: Debate
key: debate
description: Two providers independently draft answers, then an adversarial judge picks/merges the strongest.
providers:
  - provider-a
  - provider-b
workflow:
  nodes:
    - id: debate
      title: Independent drafts from two providers
      node_type: fanout
      depends_on: []
      pattern_config:
        count: 2
        providers: [provider-a, provider-b]
        title_template: "Debater {i}: independent draft"
        synthesize_title: "Collect drafts"
    - id: judge
      title: Adversarial judgment of drafts
      node_type: judge
      depends_on: [debate-synthesize]
```
