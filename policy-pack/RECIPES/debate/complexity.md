# Complexity Policy

How tasks are classified into low / medium / high complexity, and which
phases may be skipped for each tier.

```yaml
complexity_triggers:
  low:
    - single file change
    - documentation update
    - configuration tweak
  medium:
    - multi-file change
    - new feature slice
    - bug fix with tests
  high:
    - cross-cutting refactor
    - schema or API migration
    - security-sensitive change

classification_thresholds:
  low_max_files: 1
  medium_max_files: 5
  keywords_high:
    - migration
    - refactor
    - security
    - infra

skip_rules:
  low:
    - PlanningAdvisor
    - RiskCheck
  medium:
    - PlanningAdvisor
```
