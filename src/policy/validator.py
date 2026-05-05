"""Reusable policy validation helpers."""
from __future__ import annotations

from pathlib import Path

from .compiler import compile_policy_pack
try:
    from src.runtime import (
        validate_graph_execution_config,
        validate_provider_routing_config,
        validate_quality_loop_config,
    )
except ImportError:
    from runtime import (
        validate_graph_execution_config,
        validate_provider_routing_config,
        validate_quality_loop_config,
    )


CLAIM_TO_SECTION = {
    "complexity_triggers": "complexity",
    "classification_thresholds": "complexity",
    "brainstorming_protocol": "conventions",
    "confidence_weights": "conventions",
    "checkpoint_requirements": "task_tracking",
    "dependency_tracking": "task_tracking",
    "build_commands": "commands",
    "test_commands": "commands",
    "tdd_mode": "conventions",
    "conventions": "conventions",
    "retry_budgets": "escalation",
    "severity_thresholds": "escalation",
    "auto_fix_attempts": "escalation",
    "review_criteria": "review",
    "evidence_requirements": "review",
    "hard_stop_rounds": "review",
    "task_manifest_format": "task_tracking",
    "block_resolution_options": "task_tracking",
    "devil_advocate_depth": "review",
    "elegance_criteria": "conventions",
    "auto_fix_policies": "escalation",
    "log_verbosity": "task_tracking",
    "pattern_detection": "skills",
    "evolution_threshold": "skills",
    "provider_routing": "model_routing",
    "provider_config": "model_routing",
}


def load_policy_claims(policy_pack_path: str) -> dict[str, list[str]]:
    """Map compiled policy sections to the required inputs they provide."""
    claims: dict[str, list[str]] = {}
    compiled = compile_policy_pack(policy_pack_path)
    for section_name, section in compiled.sections.items():
        provides = [
            claim
            for claim, mapped_section in CLAIM_TO_SECTION.items()
            if mapped_section == section_name
        ]
        if provides:
            claims[Path(section.path).name] = provides
    return claims


def _weight_issues(weights: Any) -> str | None:
    """Return an error string if confidence_weights are invalid, else None."""
    if not isinstance(weights, dict):
        return "confidence_weights must be a mapping of key → float"
    try:
        total = sum(float(v) for v in weights.values())
    except (TypeError, ValueError):
        return "confidence_weights values must be numeric"
    if abs(total - 1.0) > 0.01:
        return f"confidence_weights sum to {total:.3f}, expected 1.0"
    return None


def semantic_issues(policy_pack_path: str) -> dict[str, str]:
    """Return policy files that exist but do not contain parseable policy content."""
    compiled = compile_policy_pack(policy_pack_path)
    issues: dict[str, str] = dict(compiled.parse_errors)
    section_checks = {
        "complexity": ("classification_thresholds", "skip_rules"),
        "commands": ("build", "test"),
        "review": ("max_rounds", "min_coverage"),
        "escalation": ("auto_fix", "review"),
        "model_routing": ("provider", "providers"),
        "task_tracking": ("task", "options"),
    }
    for section_name, required_markers in section_checks.items():
        section = compiled.get_section(section_name)
        if section is None:
            continue
        section_text = section.raw_excerpt.lower()
        if not section.typed_data and not any(
            marker.lower() in section_text for marker in required_markers
        ):
            issues[Path(section.path).name] = (
                f"Section `{section_name}` exists but has no parseable policy content"
            )
            continue
        graph_config = section.typed_data.get("graph_execution")
        graph_issues = validate_graph_execution_config(graph_config)
        if graph_issues:
            issues[Path(section.path).name] = "; ".join(graph_issues)
            continue
        quality_issues = validate_quality_loop_config(section.typed_data.get("quality_loop"))
        if quality_issues:
            issues[Path(section.path).name] = "; ".join(quality_issues)
            continue
        if section_name == "model_routing":
            provider_issues = validate_provider_routing_config(section.typed_data)
            if provider_issues:
                issues[Path(section.path).name] = "; ".join(provider_issues)
        weights = section.typed_data.get("confidence_weights")
        if weights is not None:
            w_issue = _weight_issues(weights)
            if w_issue:
                issues[Path(section.path).name] = w_issue
                continue
            threshold = section.typed_data.get("confidence_threshold", 0.9)
            try:
                if float(threshold) > sum(float(v) for v in weights.values()) + 0.01:
                    issues[Path(section.path).name] = (
                        f"confidence_threshold {threshold} is not achievable "
                        f"(max possible: {sum(float(v) for v in weights.values()):.3f})"
                    )
            except (TypeError, ValueError):
                issues[Path(section.path).name] = "confidence_threshold must be numeric"
    return issues
