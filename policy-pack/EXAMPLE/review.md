# Review Policy

What the Review phase checks and when it hard-stops.

```yaml
max_rounds: 3
min_coverage: 80
hard_stop_rounds: 5
devil_advocate_depth: 1

review_criteria:
  - spec_met
  - code_quality_acceptable
  - no_blocking_issues

evidence_requirements:
  - tests_pass
  - no_regressions
```
