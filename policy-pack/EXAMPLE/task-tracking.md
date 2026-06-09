# Task Tracking Policy

Manifest format, dependency tracking, and how blocked work is resolved.

```yaml
task_manifest_format: yaml

checkpoint_requirements:
  - plan_approved
  - tests_green
  - review_complete

dependency_tracking: graph

block_resolution_options:
  - retry
  - reassign_provider
  - wait_for_human

log_verbosity: summary
```
