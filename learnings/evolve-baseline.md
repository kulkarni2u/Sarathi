# Evolve Baseline Template

## Overview

This document is the global baseline template for cross-project learnings. It captures reusable patterns, tracks deprecated approaches, and maintains statistics across all Sarathi projects.

---

## Pattern Structure

### Pattern Definition

Every pattern in this baseline follows this structure:

```yaml
pattern:
  id: "PAT-XXX"
  name: "pattern-name"
  category:
    - phase category
    - implementation type
  description: "What the pattern does"
  context: "When to apply this pattern"
  evidence:
    - occurrence_1
    - occurrence_2
    - occurrence_3
  outcome:
    success: "What worked"
    lessons: "What was learned"
  confidence: 0.XX
  first_observed: "YYYY-MM-DD"
  last_observed: "YYYY-MM-DD"
  usage_count: N
  source_projects:
    - project_1
    - project_2
```

### Pattern Categories

| Category | Description |
|----------|-------------|
| `routing` | Task classification and routing patterns |
| `brainstorming` | Solution exploration approaches |
| `planning` | Plan structure and sequencing |
| `implementation` | Code and feature implementation |
| `verification` | Testing and validation approaches |
| `review` | Code review and quality assurance |
| `risk` | Risk identification and mitigation |
| `elegance` | Code quality and refactoring |
| `meta` | Patterns about using the framework itself |

---

## Active Patterns

### Routing Patterns

```yaml
PAT-001:
  name: "route-by-task-type"
  category: [routing, classification]
  description: "Classify task by type (feature/bug/refactor/docs/deploy) before selecting workflow"
  context: "All new tasks entering the system"
  evidence:
    - project_alpha: reduced misrouted tasks by 40%
    - project_beta: improved first-pass accuracy
  outcome:
    success: "High classification accuracy when policy pack has type patterns"
    lessons: "Needs task type patterns in policy pack for best results"
  confidence: 0.85
  first_observed: "2026-01-15"
  last_observed: "2026-04-14"
  usage_count: 47
  source_projects: [alpha, beta, gamma]
```

### Planning Patterns

```yaml
PAT-002:
  name: "plan-before-build"
  category: [planning, sequencing]
  description: "Always complete Plan phase before starting Build phase"
  context: "Any implementation task"
  evidence:
    - project_alpha: 3x reduction in rework
    - project_beta: earlier blocker detection
  outcome:
    success: "Significant reduction in implementation rework"
    lessons: "Skipping planning leads to 2-3x more iteration"
  confidence: 0.92
  first_observed: "2026-01-20"
  last_observed: "2026-04-14"
  usage_count: 89
  source_projects: [alpha, beta, gamma, delta]
```

### Build Patterns

```yaml
PAT-003:
  name: "test-after-compile"
  category: [implementation, verification]
  description: "Run tests immediately after successful compile, before considering build complete"
  context: "Build phase completion criteria"
  evidence:
    - project_beta: caught 60% of bugs in build phase
    - project_gamma: test failures surface faster
  outcome:
    success: "Bugs caught earlier in cycle"
    lessons: "Compile-only checks are insufficient"
  confidence: 0.88
  first_observed: "2026-02-01"
  last_observed: "2026-04-14"
  usage_count: 63
  source_projects: [beta, gamma]
```

### Review Patterns

```yaml
PAT-004:
  name: "review-before-ship"
  category: [review, quality]
  description: "All changes must pass review phase before being shipped"
  context: "Any code or documentation change"
  evidence:
    - project_alpha: 70% reduction in post-deploy bugs
    - project_delta: improved consistency
  outcome:
    success: "Catch issues before they reach production"
    lessons: "Review overhead pays for itself in bug reduction"
  confidence: 0.90
  first_observed: "2026-01-10"
  last_observed: "2026-04-14"
  usage_count: 156
  source_projects: [alpha, beta, delta]
```

### Risk Patterns

```yaml
PAT-005:
  name: "risk-check-early"
  category: [risk, planning]
  description: "Run RiskCheck phase early in planning to identify blockers before investment"
  context: "Complex or uncertain tasks"
  evidence:
    - project_gamma: avoided 2 major blockers
    - project_beta: better resource allocation
  outcome:
    success: "Early risk identification enables mitigation planning"
    lessons: "Late risk discovery is 5x more expensive to fix"
  confidence: 0.87
  first_observed: "2026-02-15"
  last_observed: "2026-04-14"
  usage_count: 34
  source_projects: [beta, gamma]
```

### Meta Patterns

```yaml
PAT-006:
  name: "policy-pack-accuracy"
  category: [meta, configuration]
  description: "Engine performance correlates with policy pack completeness"
  context: "Framework deployment"
  evidence:
    - deployment_alpha: policy pack v2.0 → 40% better outcomes
    - deployment_beta: policy pack v1.5 → baseline outcomes
  outcome:
    success: "Better policy packs directly improve results"
    lessons: "Invest in policy pack quality"
  confidence: 0.82
  first_observed: "2026-03-01"
  last_observed: "2026-04-14"
  usage_count: 12
  source_projects: [alpha, beta]
```

---

## Deprecated Patterns

### Decommissioned Approaches

```yaml
DEP-001:
  name: "skip-planning-for-small-tasks"
  deprecated: "2026-02-20"
  reason: "Small tasks without planning had 2x higher rework rate"
  replacement: "PAT-002: plan-before-build"
  migrated: "2026-03-15"
  legacy_warning: "Do not use for any task size. See PAT-002 for current guidance."
```

```yaml
DEP-002:
  name: "build-first-debug-later"
  deprecated: "2026-01-30"
  reason: "Debug during build leads to exponential time waste"
  replacement: "PAT-003: test-after-compile"
  migrated: "2026-03-01"
  legacy_warning: "Always verify during build phase. See PAT-003."
```

```yaml
DEP-003:
  name: "review-optional"
  deprecated: "2026-02-10"
  reason: "Optional review led to production issues in 3 projects"
  replacement: "PAT-004: review-before-ship"
  migrated: "2026-03-10"
  legacy_warning: "Review is mandatory. See PAT-004."
```

```yaml
DEP-004:
  name: "risk-check-at-end"
  deprecated: "2026-02-28"
  reason: "Risk check at end of project surfaces risks too late to mitigate"
  replacement: "PAT-005: risk-check-early"
  migrated: "2026-03-20"
  legacy_warning: "Run risk check early. See PAT-005."
```

---

## Statistics

### Pattern Usage Summary

| Metric | Value |
|--------|-------|
| Total active patterns | 6 |
| Total deprecated patterns | 4 |
| Patterns with high confidence (>0.85) | 4 |
| Patterns with medium confidence (0.70-0.85) | 2 |
| Average pattern usage count | 66.8 |
| Most used pattern | PAT-004 (review-before-ship) with 156 uses |
| Least used pattern | PAT-006 (policy-pack-accuracy) with 12 uses |

### Deprecation Summary

| Metric | Value |
|--------|-------|
| Total deprecated patterns | 4 |
| Average time to deprecation | 45 days |
| Average migration time | 23 days |
| Patterns successfully migrated | 4/4 (100%) |

### Project Coverage

| Category | Coverage |
|----------|----------|
| Routing | 100% |
| Brainstorming | 40% |
| Planning | 100% |
| Implementation | 85% |
| Verification | 70% |
| Review | 100% |
| Risk | 60% |
| Elegance | 30% |
| Meta | 50% |

---

## Maintenance Guidelines

### Adding New Patterns

1. Observe pattern across multiple executions
2. Document in appropriate category
3. Assign PAT-XXX identifier
4. Record initial evidence
5. Set confidence based on evidence count
6. Update statistics

### Deprecating Patterns

1. Identify pattern failure modes
2. Document deprecation reason
3. Assign replacement pattern (if available)
4. Set grace period (default 30 days)
5. Update legacy_warning
6. Track migration progress

### Confidence Decay

Patterns lose confidence over time if not observed:
- 0.1 decay per quarter after last_observed
- Minimum confidence: 0.5
- Below minimum: consider deprecation

---

## Version

1.0.0