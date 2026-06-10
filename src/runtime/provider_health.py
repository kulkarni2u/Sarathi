"""Persisted provider health tracking from measured task outcomes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_HEALTH_FLOOR = 0.1
_DEFAULT_SCORE = 1.0


class ProviderHealthStore:
    """Tracks per-provider success/failure counts and a derived health score.

    Persists to ``<base_dir>/provider_health.json``. Reads tolerate a missing
    or corrupt file (start fresh); writes are atomic (write to a temp file
    then ``os.replace``).
    """

    def __init__(self, base_dir: str | os.PathLike[str]):
        self.base_dir = Path(base_dir)
        self.path = self.base_dir / "provider_health.json"
        self._data: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            raw = self.path.read_text()
        except OSError:
            return {}
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
        if not isinstance(parsed, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for provider_id, stats in parsed.items():
            if not isinstance(provider_id, str) or not isinstance(stats, dict):
                continue
            successes = stats.get("successes", 0)
            failures = stats.get("failures", 0)
            if not isinstance(successes, int) or not isinstance(failures, int):
                continue
            result[provider_id] = {
                "successes": successes,
                "failures": failures,
                "health_score": _compute_score(successes, failures),
            }
        return result

    def record(self, provider_id: str, success: bool) -> None:
        """Record a dispatch outcome for ``provider_id`` and persist."""
        stats = self._data.setdefault(provider_id, {"successes": 0, "failures": 0, "health_score": _DEFAULT_SCORE})
        if success:
            stats["successes"] += 1
        else:
            stats["failures"] += 1
        stats["health_score"] = _compute_score(stats["successes"], stats["failures"])
        self._save()

    def score(self, provider_id: str) -> float:
        """Return the current health score for ``provider_id`` (1.0 if unseen)."""
        stats = self._data.get(provider_id)
        if stats is None:
            return _DEFAULT_SCORE
        return stats["health_score"]

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Return a deep-ish copy of the current provider stats."""
        return {provider_id: dict(stats) for provider_id, stats in self._data.items()}

    def _save(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self._data, indent=2))
        os.replace(tmp_path, self.path)


def _compute_score(successes: int, failures: int) -> float:
    total = successes + failures
    if total <= 0:
        return _DEFAULT_SCORE
    return max(_HEALTH_FLOOR, successes / total)
