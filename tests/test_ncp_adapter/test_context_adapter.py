"""Tests for NCPContextAdapter."""
import pytest
from ncp_adapter import NCPContextAdapter


SAMPLE_PIDGIN = """\
[NCP:BUDGET] ctx_used:0.00 steps:0/? elapsed:0s pressure:low

[NCP:CONSCIOUS]
id:s.pravaha role:build ncp_v:1.0
owns:[code] must-not:[deploy]
task:test_task
slot:Build slot_age:0 slot_conf:1.00
intent:build_feature

[NCP:SUBCONSCIOUS]
chunk:sub_abc layer:semantic score:0.85 src:tool_result trust:0.70
  previous build output here
chunk:sub_def layer:episodic score:0.72 src:synthesis trust:0.60
  earlier task summary
"""


class TestNCPContextAdapter:
    def test_init_direct_mode(self):
        adapter = NCPContextAdapter(mode="direct")
        assert adapter.mode == "direct"
        assert adapter.run_path is not None

    def test_init_mcp_mode(self):
        adapter = NCPContextAdapter(mode="mcp", endpoint="http://127.0.0.1:4242/mcp")
        assert adapter.mode == "mcp"
        assert adapter.endpoint == "http://127.0.0.1:4242/mcp"

    def test_init_invalid_mode(self):
        with pytest.raises(ValueError, match="mode must be 'direct' or 'mcp'"):
            NCPContextAdapter(mode="invalid")

    def test_check_available_direct_returns_false_when_no_ncp(self):
        adapter = NCPContextAdapter(mode="direct", run_path="/nonexistent/run.py")
        assert adapter.check_available() is False

    def test_map_to_context_pack_parses_pidgin(self):
        adapter = NCPContextAdapter()
        result = adapter._map_to_context_pack(
            SAMPLE_PIDGIN, "Pravaha", "Build",
            {"goal": "Build feature X", "review_criteria": ["tests pass"]},
            token_budget=4000,
        )
        assert result["role"] == "Pravaha"
        assert result["phase"] == "Build"
        assert result["agent_input"]["objective"] == "Build feature X"
        assert "tests pass" in result["agent_input"]["constraints"]
        assert result["agent_input"]["token_budget"] == 4000
        assert len(result["agent_input"]["prior_findings"]) == 4

    def test_map_to_context_pack_default_budget(self):
        adapter = NCPContextAdapter()
        result = adapter._map_to_context_pack(
            SAMPLE_PIDGIN, "Pravaha", "Build", {}, token_budget=None,
        )
        assert result["agent_input"]["token_budget"] == 3000

    def test_map_to_context_pack_zero_budget(self):
        adapter = NCPContextAdapter()
        result = adapter._map_to_context_pack(
            SAMPLE_PIDGIN, "Pravaha", "Build", {}, token_budget=0,
        )
        assert result["agent_input"]["token_budget"] == 0

    def test_check_available_mcp_returns_false_when_no_server(self):
        adapter = NCPContextAdapter(mode="mcp", endpoint="http://127.0.0.1:1/mcp")
        assert adapter.check_available() is False
