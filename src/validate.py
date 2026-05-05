"""Policy validation for Sarathi - Dual-source truth validation."""
from enum import Enum
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .policy import CLAIM_TO_SECTION, load_policy_claims, semantic_issues
except ImportError:
    from policy import CLAIM_TO_SECTION, load_policy_claims, semantic_issues


class ValidationStatus(Enum):
    PASS = "PASS"
    DRIFT = "DRIFT"
    TODO = "TODO"


@dataclass
class ValidationResult:
    status: ValidationStatus
    required_input: str
    phase: str
    policy_file: str | None = None
    issue: str | None = None


class PolicyValidator:
    """Dual-source truth policy validation."""
    CLAIM_TO_SECTION = CLAIM_TO_SECTION

    def __init__(self, engine_path: str, policy_pack_path: str):
        self.engine_path = Path(engine_path)
        self.policy_pack_path = Path(policy_pack_path)

    def load_required_list(self) -> dict[str, list[str]]:
        return {
            "Route": ["complexity_triggers", "classification_thresholds"],
            "Brainstorm": ["brainstorming_protocol", "confidence_weights"],
            "Plan": ["checkpoint_requirements", "dependency_tracking"],
            "Build": ["build_commands", "test_commands", "tdd_mode", "conventions"],
            "Verify": ["retry_budgets", "severity_thresholds", "auto_fix_attempts"],
            "Review": ["review_criteria", "evidence_requirements", "hard_stop_rounds"],
            "TaskTracking": ["task_manifest_format", "block_resolution_options"],
            "RiskCheck": ["devil_advocate_depth"],
            "Elegance": ["elegance_criteria", "auto_fix_policies"],
            "PhaseLog": ["log_verbosity"],
            "Learn": ["pattern_detection", "evolution_threshold"],
        }

    def load_policy_claims(self) -> dict[str, list[str]]:
        return load_policy_claims(str(self.policy_pack_path))

    def _semantic_issues(self) -> dict[str, str]:
        return semantic_issues(str(self.policy_pack_path))

    def validate(
        self,
        required_list: dict[str, list[str]] | None = None,
        policy_claims: dict[str, list[str]] | None = None
    ) -> list[ValidationResult]:
        user_supplied_claims = policy_claims is not None
        if required_list is None:
            required_list = self.load_required_list()
        if policy_claims is None:
            policy_claims = self.load_policy_claims()

        results = []
        all_claims = {item: fname for fname, provides in policy_claims.items() for item in provides}
        semantic_issues = {} if user_supplied_claims else self._semantic_issues()

        for phase, inputs in required_list.items():
            for inp in inputs:
                if inp in all_claims:
                    policy_file = all_claims[inp]
                    if policy_file in semantic_issues:
                        results.append(
                            ValidationResult(
                                ValidationStatus.DRIFT,
                                inp,
                                phase,
                                policy_file,
                                semantic_issues[policy_file],
                            )
                        )
                    else:
                        results.append(ValidationResult(ValidationStatus.PASS, inp, phase, policy_file))
                else:
                    results.append(ValidationResult(ValidationStatus.TODO, inp, phase, None, "Not provided"))

        return results

    def validate_all(self) -> dict[str, Any]:
        results = self.validate()
        return {
            "total": len(results),
            "passed": sum(1 for r in results if r.status == ValidationStatus.PASS),
            "drift": sum(1 for r in results if r.status == ValidationStatus.DRIFT),
            "todo": sum(1 for r in results if r.status == ValidationStatus.TODO),
            "results": [{"status": r.status.value, "input": r.required_input, "phase": r.phase} for r in results],
        }
