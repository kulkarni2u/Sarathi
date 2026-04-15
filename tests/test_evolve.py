import pytest
from datetime import datetime
from src.evolve import Evolver, Pattern, EvolveBaseline


def test_pattern_pass_gate():
    evolver = Evolver()
    pattern = Pattern(
        name="test-pattern",
        first_seen=datetime.now(),
        pass_rate=0.9,
    )
    assert evolver.should_promote(pattern) is True


def test_pattern_fails_below_gate():
    evolver = Evolver()
    pattern = Pattern(
        name="test-pattern",
        first_seen=datetime.now(),
        pass_rate=0.5,
    )
    assert evolver.should_promote(pattern) is False