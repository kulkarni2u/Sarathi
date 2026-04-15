# Sarathi Engine Configuration

## Overview

This document contains all configurable options for the Sarathi engine. Values shown are defaults that can be overridden per-project or per-execution.

---

## Version

```yaml
version: "1.0.0"
```

---

## Default Phase Sequence

```yaml
phases:
  sequence:
    - Route
    - Brainstorm
    - PlanningAdvisor
    - Plan
    - Build
    - Verify
    - Review
    - TaskTracking
    - RiskCheck
    - Elegance
    - PhaseLog
    - Learn
  parallelization:
    allowed:
      - name: build-riskcheck
        phases: [Build, RiskCheck]
        conditions:
          - RiskCheck depends on Plan output
          - Build depends on approved Plan
      - name: verify-elegance
        phases: [Verify, Elegance]
        conditions:
          - Both depend on Build completion
    max_parallel: 3
```

---

## Sub-Agent Dispatch Modes

```yaml
dispatch:
  modes:
    explore:
      description: "Discovery and brainstorming mode"
      model_selection:
        preference: "high-creativity"
        latency_tolerance: "high"
        context_requirement: "large"
      phases:
        - Route
        - Brainstorm
        - PlanningAdvisor
    execute:
      description: "Implementation and production mode"
      model_selection:
        preference: "high-reliability"
        latency_tolerance: "low"
        context_requirement: "standard"
      phases:
        - Plan
        - Build
        - Verify
        - Review
        - TaskTracking
        - RiskCheck
        - Elegance
        - PhaseLog
        - Learn
  fallback:
    explore_to_execute: true
    execute_to_explore: false
```

---

## Confidence Gate Thresholds

```yaml
confidence_gates:
  defaults:
    Route: 0.7
    Brainstorm: 0.6
    PlanningAdvisor: 0.7
    Plan: 0.8
    Build: 0.9
    Verify: 0.85
    Review: 0.8
    TaskTracking: 0.7
    RiskCheck: 0.75
    Elegance: 0.6
    PhaseLog: 0.9
    Learn: 0.8
  escalation:
    below_minimum:
      action: "review"
      threshold: 0.5
    critical:
      action: "block"
      threshold: 0.3
```

---

## Parallelization Settings

```yaml
parallelization:
  enabled: true
  max_concurrent_phases: 3
  dependency_check: true
  conflict_resolution: "sequential"
  phases:
    can_parallelize:
      - [Build, RiskCheck]
      - [Verify, Elegance]
    must_sequential:
      - [Route, Brainstorm]
      - [Plan, Build]
```

---

## Logging Configuration

```yaml
logging:
  level: "info"
  destinations:
    - type: "file"
      path: "logs/sarathi.log"
      rotation:
        max_size: "10MB"
        max_files: 5
    - type: "console"
      format: "json"
  phase_logging:
    enabled: true
    detail_level: "full"
    log_transitions: true
    log_decisions: true
    log_artifacts: true
  decision_log:
    enabled: true
    format: "structured"
    retention_days: 90
```

---

## Learn-Evolve Settings

```yaml
learn_evolve:
  enabled: true
  baseline_update:
    auto_update: true
    frequency: "per_execution"
    merge_strategy: "conservative"
  pattern_extraction:
    min_occurrences: 3
    confidence_threshold: 0.8
    decay_old_patterns: true
    decay_rate: 0.1
  deprecation:
    auto_flag: true
    grace_period_days: 30
    removal_threshold: 0.5
  cross_project:
    enabled: true
    share_patterns: true
    anonymize: true
  statistics:
    track_pattern_usage: true
    track_deprecation: true
    track_success_rate: true
```

---

## Model Selection Defaults

```yaml
models:
  selection:
    default_preference: "balanced"
    latency_budget_ms: 5000
    context_window_requirement: "standard"
    fallback_enabled: true
  capabilities:
    creativity_models:
      - "reasoning"
      - "frontier"
    precision_models:
      - "fast"
      - "standard"
  cost_optimization:
    prefer_lower_cost: false
    cost_threshold: "medium"
```

---

## Error Handling

```yaml
error_handling:
  phase_failure:
    retry:
      enabled: true
      max_attempts: 2
      backoff: "exponential"
    escalate:
      enabled: true
      threshold: 3
  drift_handling:
    auto_correct: true
    require_confirmation: false
  blocked_handling:
    escalate_immediately: true
    notify_channels:
      - "console"
```

---

## Policy Pack Integration

```yaml
policy_pack:
  required_for_execution: false
  version_constraint: "compatible"
  fallback_to_defaults: true
  validation:
    strict: false
    check_required: true
```

---

## Audit and Compliance

```yaml
audit:
  enabled: true
  log_all_decisions: true
  retain_logs_days: 365
  compliance_mode: false
  phase_signatures: false
```

---

## Version

1.0.0