import pytest
from src.validate import PolicyValidator, ValidationStatus


def test_validation_pass():
    validator = PolicyValidator()
    result = validator.validate([], {})
    assert result.status == ValidationStatus.PASS