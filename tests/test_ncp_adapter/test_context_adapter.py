"""Tests for NCPContextAdapter."""
import pytest
from ncp_adapter import NCPContextAdapter


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
