"""Tests for NCPWhisperRouter."""
from unittest.mock import patch, MagicMock
import pytest
from ncp_adapter.whisper_router import NCPWhisperRouter


class TestNCPWhisperRouter:
    def test_init(self):
        router = NCPWhisperRouter()
        assert router is not None
        assert router.mode == "direct"

    def test_init_invalid_mode(self):
        with pytest.raises(ValueError, match="mode must be 'direct' or 'mcp'"):
            NCPWhisperRouter(mode="invalid")

    def test_emit_creates_signal(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            router = NCPWhisperRouter(mode="direct", run_path=str(tmp_path / "run.py"))
            router.emit("s.pravaha", "s.samanvaya", "consolidation_ready",
                         "task:t1:phase:Build:status:pass", 0.95)
            assert mock_run.called

    def test_emit_validates_payload_length(self):
        router = NCPWhisperRouter()
        with pytest.raises(ValueError, match="<= 600"):
            router.emit("a", "b", "alert", "x" * 601, 0.9)

    def test_poll_returns_list(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            router = NCPWhisperRouter(mode="direct", run_path=str(tmp_path / "run.py"))
            result = router.poll("s.samanvaya")
            assert isinstance(result, list)

    def test_mcp_emit_error_raises(self):
        import httpx
        router = NCPWhisperRouter(mode="mcp", endpoint="http://127.0.0.1:1/mcp")
        with patch("httpx.post") as mock_post:
            mock_post.side_effect = httpx.ConnectError("connection refused")
            with pytest.raises(RuntimeError, match="NCP MCP whisper emit failed"):
                router.emit("a", "b", "nudge", "hello", 0.8)
