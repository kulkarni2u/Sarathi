"""Tests for NCPArtifactAdapter."""
import json
from unittest.mock import patch, MagicMock
import pytest
from ncp_adapter.artifact_adapter import NCPArtifactAdapter


class TestNCPArtifactAdapter:
    def test_init(self):
        adapter = NCPArtifactAdapter()
        assert adapter.mode == "direct"

    def test_init_invalid_mode(self):
        with pytest.raises(ValueError, match="mode must be 'direct' or 'mcp'"):
            NCPArtifactAdapter(mode="invalid")

    def test_save_phase_artifacts_empty(self, tmp_path):
        adapter = NCPArtifactAdapter(mode="direct", run_path=str(tmp_path / "run.py"))
        result = adapter.save_phase_artifacts("t1", "Build", {})
        assert result is None

    def test_save_phase_artifacts_calls_write_memory(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            adapter = NCPArtifactAdapter(mode="direct", run_path=str(tmp_path / "run.py"))
            result = adapter.save_phase_artifacts("t1", "Build", {"output": "built"}, {"key": "val"})
            assert result == "ncp://t1/Build"
            assert mock_run.called
            payload = json.loads(mock_run.call_args[0][0][-1])
            assert payload["layer"] == "semantic"
            assert payload["src"] == "tool_result"
            content = json.loads(payload["content"])
            assert content["_sarathi_type"] == "PhaseArtifact"
            assert content["task_id"] == "t1"
            assert content["phase"] == "Build"

    def test_load_artifacts(self, tmp_path):
        raw = 'chunk:abc layer:semantic score:0.85\n  {"_sarathi_type":"PhaseArtifact","task_id":"t1","phase":"Build","artifacts":{"output":"built"}}\n'
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=raw, stderr="")
            adapter = NCPArtifactAdapter(mode="direct", run_path=str(tmp_path / "run.py"))
            artifacts = adapter.load_artifacts("t1", "Build")
            assert artifacts == [{"output": "built"}]

    def test_list_phases(self, tmp_path):
        raw = ('chunk:a layer:semantic score:0.85\n  {"_sarathi_type":"PhaseArtifact","task_id":"t1","phase":"Build"}\n'
               'chunk:b layer:semantic score:0.72\n  {"_sarathi_type":"PhaseArtifact","task_id":"t1","phase":"Verify"}\n')
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=raw, stderr="")
            adapter = NCPArtifactAdapter(mode="direct", run_path=str(tmp_path / "run.py"))
            phases = adapter.list_phases("t1")
            assert "Build" in phases
            assert "Verify" in phases

    def test_mcp_error_raises(self):
        import httpx
        adapter = NCPArtifactAdapter(mode="mcp", endpoint="http://127.0.0.1:1/mcp")
        with patch("httpx.post") as mock_post:
            mock_post.side_effect = httpx.ConnectError("connection refused")
            with pytest.raises(RuntimeError, match="NCP MCP write_memory failed"):
                adapter._call_write_memory("{}", "semantic", "synthesis", "test")
