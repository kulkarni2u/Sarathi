"""Persisted provider health tracking from measured task outcomes."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_HEALTH_FLOOR = 0.1
_DEFAULT_SCORE = 1.0

# Exponential decay applied to accumulated successes/failures based on
# calendar time elapsed since a provider was last recorded — not on call
# count. A provider that failed once a month ago and has since been quiet
# gradually forgets that failure; a provider hammered with calls seconds
# apart (the common case inside a single task, and in fast unit tests)
# barely decays at all, since almost no wall-clock time has elapsed. This
# is what fixes "one ancient failure depresses the score forever" without
# making the score jumpy across a single task's rapid-fire dispatches.
_DECAY_FACTOR = 0.95
_DECAY_PERIOD_SECONDS = 3600.0  # one full decay step per hour of quiet

# EWMA smoothing factor for latency: higher = more weight on the newest
# sample. 0.2 means the average takes roughly 5 samples to mostly track a
# step change in latency.
_LATENCY_ALPHA = 0.2


class ProviderHealthStore:
    """Tracks per-provider success/failure counts and a derived health score.

    Persists to ``<base_dir>/provider_health.json``. Reads tolerate a missing
    or corrupt file (start fresh); writes are atomic (write to a temp file
    then ``os.replace``).

    Two views of the same underlying signal are kept per provider:

    - ``successes`` / ``failures``: raw lifetime counters, kept for
      observability/debugging — never decayed.
    - ``decayed_successes`` / ``decayed_failures``: floats that age out old
      outcomes over calendar time (see ``_DECAY_FACTOR`` /
      ``_DECAY_PERIOD_SECONDS`` above). ``health_score`` is derived from
      these, not from the raw counters.

    ``latency_ewma_ms`` tracks a per-provider exponential moving average of
    reported latency, ``None`` until a caller first reports one.
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
        now = time.time()
        for provider_id, stats in parsed.items():
            if not isinstance(provider_id, str) or not isinstance(stats, dict):
                continue
            successes = stats.get("successes", 0)
            failures = stats.get("failures", 0)
            if not isinstance(successes, int) or not isinstance(failures, int):
                continue
            # Migration from the old on-disk format (plain ints, no decayed
            # fields, no latency): treat the existing lifetime counts as the
            # starting decayed values rather than fabricating history.
            decayed_successes = _coerce_float(stats.get("decayed_successes"), default=float(successes))
            decayed_failures = _coerce_float(stats.get("decayed_failures"), default=float(failures))
            latency_ewma_ms = stats.get("latency_ewma_ms")
            if not isinstance(latency_ewma_ms, (int, float)):
                latency_ewma_ms = None
            last_updated = stats.get("last_updated")
            if not isinstance(last_updated, (int, float)):
                last_updated = now
            result[provider_id] = {
                "successes": successes,
                "failures": failures,
                "decayed_successes": decayed_successes,
                "decayed_failures": decayed_failures,
                "health_score": _compute_score(decayed_successes, decayed_failures),
                "latency_ewma_ms": float(latency_ewma_ms) if latency_ewma_ms is not None else None,
                "last_updated": float(last_updated),
            }
        return result

    def record(self, provider_id: str, success: bool, latency_ms: float | None = None) -> None:
        """Record a dispatch outcome for ``provider_id`` and persist.

        ``latency_ms`` is optional so existing 2-arg call sites keep working
        unchanged; when provided it folds into the provider's latency EWMA.
        """
        now = time.time()
        stats = self._data.get(provider_id)
        if stats is None:
            stats = {
                "successes": 0,
                "failures": 0,
                "decayed_successes": 0.0,
                "decayed_failures": 0.0,
                "health_score": _DEFAULT_SCORE,
                "latency_ewma_ms": None,
                "last_updated": now,
            }
            self._data[provider_id] = stats

        elapsed = max(0.0, now - stats.get("last_updated", now))
        decay = _DECAY_FACTOR ** (elapsed / _DECAY_PERIOD_SECONDS)
        decayed_successes = stats.get("decayed_successes", float(stats["successes"])) * decay
        decayed_failures = stats.get("decayed_failures", float(stats["failures"])) * decay

        if success:
            stats["successes"] += 1
            decayed_successes += 1.0
        else:
            stats["failures"] += 1
            decayed_failures += 1.0

        stats["decayed_successes"] = decayed_successes
        stats["decayed_failures"] = decayed_failures
        stats["health_score"] = _compute_score(decayed_successes, decayed_failures)
        stats["last_updated"] = now

        if latency_ms is not None:
            previous = stats.get("latency_ewma_ms")
            stats["latency_ewma_ms"] = (
                float(latency_ms)
                if previous is None
                else (_LATENCY_ALPHA * float(latency_ms) + (1 - _LATENCY_ALPHA) * previous)
            )

        self._save()

    def score(self, provider_id: str) -> float:
        """Return the current health score for ``provider_id`` (1.0 if unseen)."""
        stats = self._data.get(provider_id)
        if stats is None:
            return _DEFAULT_SCORE
        return stats["health_score"]

    def latency_ms(self, provider_id: str) -> float | None:
        """Return the current latency EWMA for ``provider_id``, or None if unknown."""
        stats = self._data.get(provider_id)
        if stats is None:
            return None
        return stats.get("latency_ewma_ms")

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Return a deep-ish copy of the current provider stats."""
        return {provider_id: dict(stats) for provider_id, stats in self._data.items()}

    def _save(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self._data, indent=2))
        os.replace(tmp_path, self.path)


def _compute_score(successes: float, failures: float) -> float:
    total = successes + failures
    if total <= 0:
        return _DEFAULT_SCORE
    return max(_HEALTH_FLOOR, successes / total)


def _coerce_float(value: Any, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return default
