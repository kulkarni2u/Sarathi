# Conventions Policy

Team conventions the Build and Elegance phases must follow, plus the
brainstorming protocol used to weigh approaches.

```yaml
conventions:
  style: follow existing file style and naming
  comments: only where the code cannot explain itself
  errors: no silent exception swallowing; log with context

tdd_mode: encouraged

brainstorming_protocol:
  min_approaches: 2
  require_risks: true
  require_success_criteria: true

confidence_weights:
  alternative_approaches_considered: 0.3
  risks_identified: 0.3
  success_criteria_defined: 0.2
  reversibility_assessed: 0.2

elegance_criteria:
  - no dead code introduced
  - duplication folded into helpers
  - public names read clearly at the call site
```
