"""Tests for the cross-provider pricing table and cost resolution."""

from src.dispatch import LocalDispatcher, TaskSpec
from src.runtime import DispatchRequest, DispatchResponse, ProviderAdapter, UsageRecord
from src.runtime.pricing import ModelPrice, PricingTable, resolve_cost


# --- PricingTable.from_config parsing ---------------------------------------


def test_from_config_parses_full_model_routing_section():
    config = {
        "provider": "local",
        "pricing": {
            "codex": {
                "default": {"input_per_mtok": 1.25, "output_per_mtok": 10.0},
                "gpt-5.2-codex": {"input_per_mtok": 1.75, "output_per_mtok": 14.0},
            },
            "opencode": {
                "default": {"input_per_mtok": 0.8, "output_per_mtok": 4.0},
            },
        },
    }
    table = PricingTable.from_config(config)
    assert table.lookup("codex", "gpt-5.2-codex") == ModelPrice(1.75, 14.0)
    assert table.lookup("codex", "default") == ModelPrice(1.25, 10.0)
    assert table.lookup("opencode", "some-other-model") == ModelPrice(0.8, 4.0)


def test_from_config_accepts_bare_pricing_mapping():
    # Callers may pass just the `pricing:` sub-mapping directly.
    table = PricingTable.from_config(
        {"codex": {"default": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}}}
    )
    assert table.lookup("codex", "anything") == ModelPrice(1.0, 2.0)


def test_from_config_handles_none_and_non_mapping():
    assert PricingTable.from_config(None).is_empty()
    assert PricingTable.from_config("not a mapping").is_empty()
    assert PricingTable.from_config({}).is_empty()


def test_from_config_skips_malformed_entries_without_raising():
    config = {
        "pricing": {
            "codex": {
                "default": {"input_per_mtok": 1.25, "output_per_mtok": 10.0},
                "broken_missing_output": {"input_per_mtok": 1.0},
                "broken_not_a_mapping": "oops",
                "broken_negative": {"input_per_mtok": -1.0, "output_per_mtok": 1.0},
                "broken_non_numeric": {"input_per_mtok": "cheap", "output_per_mtok": 1.0},
            },
            "": {"default": {"input_per_mtok": 1.0, "output_per_mtok": 1.0}},
            "not_a_mapping_provider": "oops",
            123: {"default": {"input_per_mtok": 1.0, "output_per_mtok": 1.0}},
        }
    }
    table = PricingTable.from_config(config)
    assert table.lookup("codex", "default") == ModelPrice(1.25, 10.0)
    # None of the malformed model entries were parsed, so looking them up by
    # name falls back to the provider's `default` (same as any unpriced model).
    assert table.lookup("codex", "broken_missing_output") == ModelPrice(1.25, 10.0)
    assert table.lookup("codex", "broken_not_a_mapping") == ModelPrice(1.25, 10.0)
    assert table.lookup("codex", "broken_negative") == ModelPrice(1.25, 10.0)
    assert table.lookup("codex", "broken_non_numeric") == ModelPrice(1.25, 10.0)
    assert table.lookup("", "default") is None
    assert table.lookup("not_a_mapping_provider", "default") is None


def test_lookup_returns_none_for_unknown_provider_or_unpriced_model_without_default():
    table = PricingTable.from_config(
        {"pricing": {"codex": {"gpt-5.2-codex": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}}}}
    )
    assert table.lookup("unknown-provider", "whatever") is None
    # No `default` entry and the exact model isn't priced either.
    assert table.lookup("codex", "some-unpriced-model") is None
    assert table.lookup(None, "whatever") is None


# --- resolve_cost -------------------------------------------------------------


def _usage(**overrides):
    base = dict(
        provider_id="codex",
        provider_family="codex",
        dispatch_id="d-1",
        input_tokens=1000,
        output_tokens=500,
        total_tokens=1500,
    )
    base.update(overrides)
    return UsageRecord(**base)


def test_resolve_cost_computes_dollar_amount():
    table = PricingTable.from_config(
        {"pricing": {"codex": {"default": {"input_per_mtok": 2.0, "output_per_mtok": 8.0}}}}
    )
    usage = _usage(input_tokens=1_000_000, output_tokens=500_000)
    cost = resolve_cost(usage, "codex", "any-model", table)
    assert cost == pytest_approx(2.0 * 1.0 + 8.0 * 0.5)


def test_resolve_cost_uses_model_specific_price_over_default():
    table = PricingTable.from_config(
        {
            "pricing": {
                "codex": {
                    "default": {"input_per_mtok": 1.0, "output_per_mtok": 1.0},
                    "gpt-5.2-codex": {"input_per_mtok": 10.0, "output_per_mtok": 20.0},
                }
            }
        }
    )
    usage = _usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert resolve_cost(usage, "codex", "gpt-5.2-codex", table) == pytest_approx(30.0)
    assert resolve_cost(usage, "codex", "unlisted-model", table) == pytest_approx(2.0)


def test_resolve_cost_returns_none_when_unpriced():
    table = PricingTable.from_config({"pricing": {"opencode": {"default": {"input_per_mtok": 1.0, "output_per_mtok": 1.0}}}})
    usage = _usage(provider_id="codex")
    assert resolve_cost(usage, "codex", "gpt-5.2-codex", table) is None


def test_resolve_cost_returns_none_for_missing_usage_or_table():
    table = PricingTable.from_config({"pricing": {"codex": {"default": {"input_per_mtok": 1.0, "output_per_mtok": 1.0}}}})
    assert resolve_cost(None, "codex", "model", table) is None
    assert resolve_cost(_usage(), "codex", "model", None) is None


# --- UsageRecord round-trip with/without cost_usd ----------------------------


def test_usage_record_round_trip_without_cost_usd():
    usage = _usage()
    assert usage.cost_usd is None
    artifact = usage.to_artifact()
    assert artifact["cost_usd"] is None
    restored = UsageRecord.from_mapping(artifact)
    assert restored is not None
    assert restored.cost_usd is None
    assert restored.input_tokens == usage.input_tokens


def test_usage_record_round_trip_with_cost_usd():
    usage = _usage(cost_usd=1.23)
    artifact = usage.to_artifact()
    assert artifact["cost_usd"] == pytest_approx(1.23)
    restored = UsageRecord.from_mapping(artifact)
    assert restored is not None
    assert restored.cost_usd == pytest_approx(1.23)


def test_usage_record_from_mapping_tolerates_malformed_cost_usd():
    usage = _usage()
    artifact = usage.to_artifact()
    artifact["cost_usd"] = "not-a-number"
    restored = UsageRecord.from_mapping(artifact)
    assert restored is not None
    assert restored.cost_usd is None


# --- Self-reported cost precedence over table-computed cost ------------------


class _StubProvider(ProviderAdapter):
    """Deterministic provider stub that returns a pre-built DispatchResponse."""

    def __init__(self, response: DispatchResponse):
        self._response = response

    @property
    def name(self) -> str:
        return "stub"

    @property
    def capabilities(self):
        from src.runtime.providers import ProviderCapabilities

        return ProviderCapabilities(transport_kind="stub", supports_structured_output=True)

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        return self._response


def _dispatch_request() -> DispatchRequest:
    return DispatchRequest(mode="execute", task_id="t-1", phase="Build", prompt="do work")


def test_dispatcher_prefers_self_reported_artifact_cost_over_pricing_table():
    usage = _usage(provider_id="claude", input_tokens=1_000_000, output_tokens=1_000_000)
    response = DispatchResponse(
        success=True,
        artifacts={"total_cost_usd": 0.0042},
        usage=usage,
    )
    provider_config = {
        "provider": "claude",
        "providers": {"claude": {"model": "some-model"}},
        # If the table were used instead, this would compute a very different cost.
        "pricing": {"claude": {"default": {"input_per_mtok": 999.0, "output_per_mtok": 999.0}}},
    }
    dispatcher = LocalDispatcher(provider=_StubProvider(response), provider_config=provider_config)
    result = dispatcher.dispatch(_dispatch_request())
    assert result.usage.cost_usd == pytest_approx(0.0042)


def test_dispatcher_prefers_usage_level_cost_over_artifacts_and_table():
    usage = _usage(provider_id="claude", cost_usd=7.0)
    response = DispatchResponse(
        success=True,
        artifacts={"total_cost_usd": 0.0042},
        usage=usage,
    )
    dispatcher = LocalDispatcher(
        provider=_StubProvider(response),
        provider_config={"pricing": {"claude": {"default": {"input_per_mtok": 1.0, "output_per_mtok": 1.0}}}},
    )
    result = dispatcher.dispatch(_dispatch_request())
    assert result.usage.cost_usd == pytest_approx(7.0)


def test_dispatcher_falls_back_to_pricing_table_when_no_self_reported_cost():
    usage = _usage(provider_id="opencode", input_tokens=1_000_000, output_tokens=1_000_000)
    response = DispatchResponse(success=True, artifacts={}, usage=usage)
    provider_config = {
        "providers": {"opencode": {"model": "some-opencode-model"}},
        "pricing": {"opencode": {"default": {"input_per_mtok": 0.8, "output_per_mtok": 4.0}}},
    }
    dispatcher = LocalDispatcher(provider=_StubProvider(response), provider_config=provider_config)
    result = dispatcher.dispatch(_dispatch_request())
    assert result.usage.cost_usd == pytest_approx(0.8 + 4.0)


def test_dispatcher_leaves_cost_usd_none_when_unpriced_and_not_self_reported():
    usage = _usage(provider_id="mystery-provider")
    response = DispatchResponse(success=True, artifacts={}, usage=usage)
    dispatcher = LocalDispatcher(
        provider=_StubProvider(response),
        provider_config={"pricing": {"codex": {"default": {"input_per_mtok": 1.0, "output_per_mtok": 1.0}}}},
    )
    result = dispatcher.dispatch(_dispatch_request())
    assert result.usage.cost_usd is None


def test_dispatcher_with_no_provider_config_does_not_price_or_raise():
    usage = _usage()
    response = DispatchResponse(success=True, artifacts={}, usage=usage)
    dispatcher = LocalDispatcher(provider=_StubProvider(response))
    result = dispatcher.dispatch(_dispatch_request())
    assert result.usage.cost_usd is None


def pytest_approx(value, rel=1e-6):
    import pytest

    return pytest.approx(value, rel=rel)
