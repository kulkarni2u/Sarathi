# Required Policy Inputs Per Phase

## Overview

This document specifies what each phase requires from policy packs to execute successfully. Policy packs provide domain knowledge, patterns, and guidelines that inform phase decisions.

## Validation Contract

Each phase has a status:
- **PASS**: All required inputs satisfied
- **DRIFT**: Some inputs missing or outdated
- **TODO**: Required inputs not yet available

---

## Phase 1: Route

### Required Inputs
| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| Task type patterns | policy-pack | Yes | Known patterns for task classification |
| Workflow path templates | policy-pack | Yes | Predefined paths for different task types |
| Classification confidence criteria | engine/config | Yes | Threshold values for path selection |

### Validation Contract
```
STATUS: PASS
- Task type patterns: available
- Workflow path templates: available
- Confidence criteria: defined
```

---

## Phase 2: Brainstorm

### Required Inputs
| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| Solution patterns | policy-pack | Yes | Known solution approaches |
| Tradeoff analysis framework | policy-pack | No | Guidelines for evaluating approaches |
| Risk identification patterns | policy-pack | Yes | Common risk types to check |

### Validation Contract
```
STATUS: PASS
- Solution patterns: available
- Tradeoff framework: optional (skipped)
- Risk patterns: available
```

---

## Phase 3: PlanningAdvisor

### Required Inputs
| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| Phase ordering templates | policy-pack | Yes | Standard phase sequences |
| Dependency rules | policy-pack | Yes | How phases depend on each other |
| Parallelization guidelines | policy-pack | No | When phases can run concurrently |

### Validation Contract
```
STATUS: PASS
- Phase ordering templates: available
- Dependency rules: available
- Parallelization guidelines: optional
```

---

## Phase 4: Plan

### Required Inputs
| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| Phase definition templates | policy-pack | Yes | Structure for phase definitions |
| Task sequencing rules | policy-pack | Yes | How to order tasks |
| Resource allocation patterns | policy-pack | No | Standard resource assignments |

### Validation Contract
```
STATUS: PASS
- Phase templates: available
- Sequencing rules: available
- Resource patterns: optional
```

---

## Phase 5: Build

### Required Inputs
| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| Implementation patterns | policy-pack | Yes | Standard implementation approaches |
| Style guides | policy-pack | Yes | Code style requirements |
| Test templates | policy-pack | No | Standard test structures |

### Validation Contract
```
STATUS: PASS
- Implementation patterns: available
- Style guides: available
- Test templates: optional
```

---

## Phase 6: Verify

### Required Inputs
| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| Requirements traceability template | policy-pack | Yes | Format for tracking requirements |
| Coverage criteria | policy-pack | Yes | Minimum coverage thresholds |
| Issue documentation format | policy-pack | No | Standard issue reporting format |

### Validation Contract
```
STATUS: PASS
- Requirements template: available
- Coverage criteria: available
- Issue format: optional
```

---

## Phase 7: Review

### Required Inputs
| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| Review checklist | policy-pack | Yes | Standard review criteria |
| Quality bar definition | policy-pack | Yes | Minimum quality standards |
| Findings classification | policy-pack | No | How to categorize review findings |

### Validation Contract
```
STATUS: PASS
- Review checklist: available
- Quality bar: available
- Findings classification: optional
```

---

## Phase 8: TaskTracking

### Required Inputs
| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| Status reporting format | policy-pack | Yes | Standard progress reporting |
| Blocker classification | policy-pack | No | Standard blocker categorization |
| Metrics definition | policy-pack | No | Standard progress metrics |

### Validation Contract
```
STATUS: PASS
- Status format: available
- Blocker classification: optional
- Metrics definition: optional
```

---

## Phase 9: RiskCheck

### Required Inputs
| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| Risk assessment framework | policy-pack | Yes | How to evaluate risks |
| Mitigation strategy templates | policy-pack | Yes | Standard mitigation approaches |
| Risk acceptance criteria | policy-pack | No | When risks can be accepted |

### Validation Contract
```
STATUS: PASS
- Risk framework: available
- Mitigation templates: available
- Acceptance criteria: optional
```

---

## Phase 10: Elegance

### Required Inputs
| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| Quality metrics definition | policy-pack | Yes | What to measure |
| Refactoring patterns | policy-pack | Yes | Standard refactoring approaches |
| Technical debt classification | policy-pack | No | How to categorize debt |

### Validation Contract
```
STATUS: PASS
- Quality metrics: available
- Refactoring patterns: available
- Debt classification: optional
```

---

## Phase 11: PhaseLog

### Required Inputs
| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| Log entry template | policy-pack | Yes | Standard log format |
| Decision documentation format | policy-pack | Yes | How to record decisions |
| Artifact reference format | policy-pack | Yes | Standard artifact linking |

### Validation Contract
```
STATUS: PASS
- Log template: available
- Decision format: available
- Artifact format: available
```

---

## Phase 12: Learn

### Required Inputs
| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| Baseline template | learnings/evolve-baseline | Yes | Template for documenting patterns |
| Pattern extraction rules | engine/config | Yes | How to identify patterns |
| Deprecation criteria | learnings/evolve-baseline | Yes | When to deprecate patterns |

### Validation Contract
```
STATUS: PASS
- Baseline template: available
- Pattern rules: defined
- Deprecation criteria: defined
```

---

## Cross-Cutting Requirements

### Model Selection (applies to all phases)
| Requirement | Source | Description |
|-------------|--------|-------------|
| Model capability matrix | policy-pack | Available models and their strengths |
| Latency requirements | engine/config | Phase-specific latency constraints |
| Cost optimization criteria | engine/config | When to prefer cost over capability |

### Skill Routing (applies to all phases)
| Requirement | Source | Description |
|-------------|--------|-------------|
| Skill registry | policy-pack | Available skills and their capabilities |
| Skill-to-phase mapping | policy-pack | Which skills support which phases |
| Fallback routing rules | engine/config | What to do when primary skill unavailable |

---

## Version

1.0.0