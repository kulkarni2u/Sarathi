"""Cross-provider pricing table for token-based dollar cost estimation.

Prices are policy data, not engine logic: they live in a policy pack's
``model-routing.md`` under a ``pricing:`` mapping (see
``policy-pack/EXAMPLE/model-routing.md``) and are compiled alongside the rest
of the model-routing section. This module only knows how to parse that
mapping and look prices up by (provider, model) — it never hardcodes a
provider name or a dollar figure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

try:
    from .contracts import UsageRecord
except ImportError:
    from contracts import UsageRecord


@dataclass(frozen=True)
class ModelPrice:
    """Per-million-token pricing for a single (provider, model) pair."""

    input_per_mtok: float
    output_per_mtok: float


class PricingTable:
    """Resolves (provider, model) -> :class:`ModelPrice` from policy config."""

    def __init__(self, prices: Mapping[str, Mapping[str, ModelPrice]] | None = None):
        self._prices: dict[str, dict[str, ModelPrice]] = {
            str(provider): dict(models) for provider, models in (prices or {}).items()
        }

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> "PricingTable":
        """Build a table from policy config.

        Accepts either the full model-routing mapping (which carries pricing
        under a top-level ``pricing`` key — the shape that already reaches
        ``LocalDispatcher`` as ``provider_config``) or a bare ``pricing``
        mapping directly. Malformed entries are skipped rather than raising,
        so one bad line in a policy pack doesn't take down dispatch.
        """
        if not isinstance(config, Mapping):
            return cls()
        source: Any = config.get("pricing", config) if "pricing" in config else config
        if not isinstance(source, Mapping):
            return cls()

        prices: dict[str, dict[str, ModelPrice]] = {}
        for provider_name, models in source.items():
            if not isinstance(provider_name, str) or not provider_name:
                continue
            if not isinstance(models, Mapping):
                continue
            provider_prices: dict[str, ModelPrice] = {}
            for model_name, price_cfg in models.items():
                if not isinstance(model_name, str) or not model_name:
                    continue
                price = _parse_price(price_cfg)
                if price is not None:
                    provider_prices[model_name] = price
            if provider_prices:
                prices[provider_name] = provider_prices
        return cls(prices)

    def lookup(self, provider: str | None, model: str | None) -> ModelPrice | None:
        """Return the priced entry for (provider, model), falling back to the
        provider's ``default`` price when the exact model isn't priced."""
        if not provider:
            return None
        provider_prices = self._prices.get(provider)
        if not provider_prices:
            return None
        if model and model in provider_prices:
            return provider_prices[model]
        return provider_prices.get("default")

    def is_empty(self) -> bool:
        return not self._prices


def _parse_price(price_cfg: Any) -> ModelPrice | None:
    if not isinstance(price_cfg, Mapping):
        return None
    input_per_mtok = _non_negative_float(price_cfg.get("input_per_mtok"))
    output_per_mtok = _non_negative_float(price_cfg.get("output_per_mtok"))
    if input_per_mtok is None or output_per_mtok is None:
        return None
    return ModelPrice(input_per_mtok=input_per_mtok, output_per_mtok=output_per_mtok)


def _non_negative_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result < 0:
        return None
    return result


def resolve_cost(
    usage: "UsageRecord | None",
    provider: str | None,
    model: str | None,
    table: "PricingTable | None",
) -> float | None:
    """Compute a dollar cost for ``usage`` from a priced (provider, model).

    Returns ``None`` — not ``0.0`` — when there is no usage, no table, or no
    matching price entry, so callers can distinguish "free" from "unpriced".
    """
    if usage is None or table is None:
        return None
    price = table.lookup(provider, model)
    if price is None:
        return None
    input_tokens = usage.input_tokens or 0
    output_tokens = usage.output_tokens or 0
    cost = (input_tokens / 1_000_000) * price.input_per_mtok
    cost += (output_tokens / 1_000_000) * price.output_per_mtok
    return cost
