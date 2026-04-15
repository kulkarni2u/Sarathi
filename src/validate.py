from enum import Enum
from dataclasses import dataclass, field
from typing import Any


class ValidationStatus(Enum):
    PASS = "pass"
    DRIFT = "drift"
    TODO = "todo"


@dataclass
class ValidationResult:
    status: ValidationStatus
    required_input: list[str] = field(default_factory=list)
    policy_file: str | None = None
    issue: str | None = None


class PolicyValidator:
    def load_required_list(self) -> list[str]:
        return []

    def load_policy_claims(self) -> dict[str, Any]:
        return {}

    def validate(self, required_list: list[str], policy_claims: dict[str, Any]) -> ValidationResult:
        return ValidationResult(status=ValidationStatus.PASS, required_input=required_list)