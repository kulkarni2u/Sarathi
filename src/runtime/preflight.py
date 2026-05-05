"""Preflight policy evaluation for policy-pack validation."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PreflightPolicy:
    """Controls which validation statuses block execution."""

    block_on_todo: bool = True
    block_on_drift: bool = False

    def should_block(self, todo_count: int, drift_count: int) -> bool:
        if self.block_on_todo and todo_count > 0:
            return True
        if self.block_on_drift and drift_count > 0:
            return True
        return False

    def warning_count(self, drift_count: int) -> int:
        return drift_count
