"""Tests for NCPPersistenceAdapter."""
import json
from unittest.mock import patch, MagicMock

import pytest

from ncp_adapter.persistence_adapter import NCPPersistenceAdapter


def _task_stub(task_id: str = "t1", **overrides: str | list | None) -> object:
    fields = {"task_id": task_id, "description": "test", "complexity": "medium",
              "current_phase": None, "phase_results": []}
    fields.update(overrides)
    return type("TaskStub", (), fields)()


class TestNCPPersistenceAdapter:
    def test_init(self):
        adapter = NCPPersistenceAdapter()
        assert adapter.mode == "direct"

    def test_init_invalid_mode(self):
        with pytest.raises(ValueError, match="mode must be 'direct' or 'mcp'"):
            NCPPersistenceAdapter(mode="invalid")

    def test_save_task_without_ncp_raises_error(self, tmp_path):
        run_py = tmp_path / "run.py"
        run_py.write_text("#!/usr/bin/env python3\nimport sys; sys.exit(1)")
        adapter = NCPPersistenceAdapter(mode="direct", run_path=str(run_py))
        with pytest.raises(RuntimeError, match="NCP write_memory failed"):
            adapter.save_task(_task_stub("t1"))

    def test_save_task_raises_on_missing_task_id(self, tmp_path):
        adapter = NCPPersistenceAdapter(mode="direct", run_path=str(tmp_path / "run.py"))
        with pytest.raises(ValueError, match="non-empty 'task_id'"):
            adapter.save_task({"description": "no id"})

    def test_load_task_returns_none_when_missing(self, tmp_path):
        run_py = tmp_path / "run.py"
        run_py.write_text("#!/usr/bin/env python3\nimport sys; sys.exit(0)")
        adapter = NCPPersistenceAdapter(mode="direct", run_path=str(run_py))
        result = adapter.load_task("nonexistent")
        assert result is None

    def test_list_tasks_returns_empty_when_no_output(self, tmp_path):
        run_py = tmp_path / "run.py"
        run_py.write_text("#!/usr/bin/env python3\nimport sys; sys.exit(0)")
        adapter = NCPPersistenceAdapter(mode="direct", run_path=str(run_py))
        result = adapter.list_tasks()
        assert result == []

    def test_parse_fetch_output(self):
        raw = "chunk:abc layer:episodic score:0.85\n  {\"task_id\":\"t1\"}\nchunk:def layer:episodic score:0.72\n  {\"task_id\":\"t2\"}\n"
        chunks = NCPPersistenceAdapter._parse_fetch_output(raw)
        assert len(chunks) == 2

    def test_reconstruct_chunk_text(self):
        text = NCPPersistenceAdapter._reconstruct_chunk_text(
            'chunk:abc layer:episodic score:0.85\n  {"task_id":"t1"}')
        assert json.loads(text)["task_id"] == "t1"

    def test_save_task_serializes(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            adapter = NCPPersistenceAdapter(mode="direct", run_path=str(tmp_path / "run.py"))
            adapter.save_task(_task_stub("t1"))
            cmd = mock_run.call_args[0][0]
            assert cmd[-2] == "write_memory"

    def test_save_learning_uses_semantic(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            adapter = NCPPersistenceAdapter(mode="direct", run_path=str(tmp_path / "run.py"))
            adapter.save_learning({"key": "value"})
            payload = json.loads(mock_run.call_args[0][0][-1])
            assert payload["layer"] == "semantic"
            assert payload["src"] == "synthesis"

    def test_save_phase_log_uses_reasoning_trace(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            adapter = NCPPersistenceAdapter(mode="direct", run_path=str(tmp_path / "run.py"))
            adapter.save_phase_log(_task_stub("t1"), "Build", "done")
            payload = json.loads(mock_run.call_args[0][0][-1])
            assert payload["layer"] == "reasoning_trace"
            assert payload["written_by"] == "sarathi.engine.t1"

    def test_list_tasks_deduplicates(self, tmp_path):
        raw = "chunk:abc layer:episodic score:0.85\n  {\"_sarathi_type\":\"TaskContext\",\"task_id\":\"t1\"}\nchunk:def layer:episodic score:0.72\n  {\"_sarathi_type\":\"TaskContext\",\"task_id\":\"t1\"}\nchunk:ghi layer:episodic score:0.90\n  {\"_sarathi_type\":\"TaskContext\",\"task_id\":\"t2\"}\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=raw, stderr="")
            adapter = NCPPersistenceAdapter(mode="direct", run_path=str(tmp_path / "run.py"))
            assert adapter.list_tasks() == ["t1", "t2"]

    def test_load_task_deserializes(self, tmp_path):
        raw = "chunk:abc layer:episodic score:0.85\n  {\"_sarathi_type\":\"TaskContext\",\"task_id\":\"t1\"}\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=raw, stderr="")
            adapter = NCPPersistenceAdapter(mode="direct", run_path=str(tmp_path / "run.py"))
            assert adapter.load_task("t1")["task_id"] == "t1"

    def test_load_task_returns_none_on_json_error(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="chunk:abc layer:episodic score:0.85\n  bad json\n", stderr="")
            adapter = NCPPersistenceAdapter(mode="direct", run_path=str(tmp_path / "run.py"))
            assert adapter.load_task("t1") is None

    def test_save_phase_log_with_dict_task(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            adapter = NCPPersistenceAdapter(mode="direct", run_path=str(tmp_path / "run.py"))
            adapter.save_phase_log({"task_id": "t1"}, "Build", "done")
            payload = json.loads(mock_run.call_args[0][0][-1])
            assert payload["written_by"] == "sarathi.engine.t1"

    def test_mcp_write_memory_error_raises(self):
        import httpx
        adapter = NCPPersistenceAdapter(mode="mcp", endpoint="http://127.0.0.1:1/mcp")
        with patch("httpx.post") as mock_post:
            mock_post.side_effect = httpx.ConnectError("connection refused")
            with pytest.raises(RuntimeError, match="NCP MCP write_memory failed"):
                adapter._call_write_memory("{}", "semantic", "synthesis", "test")

    def test_mcp_fetch_returns_empty_on_error(self):
        import httpx
        adapter = NCPPersistenceAdapter(mode="mcp", endpoint="http://127.0.0.1:1/mcp")
        with patch("httpx.post") as mock_post:
            mock_post.side_effect = httpx.ConnectError("connection refused")
            assert adapter._call_fetch("test", k=1) == []

    def test_mcp_fetch_parses_response(self):
        adapter = NCPPersistenceAdapter(mode="mcp", endpoint="http://127.0.0.1:1/mcp")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"content": [{"text": '{"task_id":"t1"}'}]}}
        with patch("httpx.post", return_value=mock_response):
            result = adapter._call_fetch("test", k=1)
            assert "task_id" in result[0]

    def test_mcp_save_learning(self):
        import httpx
        adapter = NCPPersistenceAdapter(mode="mcp", endpoint="http://127.0.0.1:1/mcp")
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = {"result": {}}
        with patch("httpx.post", return_value=mock_response):
            adapter.save_learning({"key": "value"})
