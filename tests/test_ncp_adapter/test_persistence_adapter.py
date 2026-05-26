"""Tests for NCPPersistenceAdapter."""
import json

import pytest

from ncp_adapter.persistence_adapter import NCPPersistenceAdapter


class TestNCPPersistenceAdapter:
    def test_init(self):
        adapter = NCPPersistenceAdapter()
        assert adapter.mode == "direct"

    def test_save_task_without_ncp_raises_error(self, tmp_path):
        run_py = tmp_path / "run.py"
        run_py.write_text("#!/usr/bin/env python3\nimport sys; sys.exit(1)")
        adapter = NCPPersistenceAdapter(mode="direct", run_path=str(run_py))
        task = type(
            "Task",
            (),
            {
                "task_id": "t1",
                "description": "test",
                "complexity": "medium",
                "current_phase": None,
                "phase_results": [],
            },
        )()
        with pytest.raises(RuntimeError, match="NCP write_memory failed"):
            adapter.save_task(task)

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

    def test_init_invalid_mode(self):
        with pytest.raises(ValueError, match="mode must be 'direct' or 'mcp'"):
            NCPPersistenceAdapter(mode="invalid")

    def test_parse_fetch_output(self):
        raw = """\
chunk:abc123 layer:episodic score:0.85
  {"_sarathi_type":"TaskContext","task_id":"t1","description":"test task","complexity":"medium","current_phase":null,"phase_results":[]}
chunk:def456 layer:episodic score:0.72
  {"_sarathi_type":"TaskContext","task_id":"t2","description":"another task","complexity":"high","current_phase":"Build","phase_results":[{"phase":"Build","status":"done"}]}
"""
        chunks = NCPPersistenceAdapter._parse_fetch_output(raw)
        assert len(chunks) == 2
        assert chunks[0].startswith("chunk:abc123")
        assert chunks[1].startswith("chunk:def456")

    def test_reconstruct_chunk_text(self):
        chunk = 'chunk:abc123 layer:episodic score:0.85\n  {"_sarathi_type":"TaskContext","task_id":"t1"}'
        text = NCPPersistenceAdapter._reconstruct_chunk_text(chunk)
        obj = json.loads(text)
        assert obj["_sarathi_type"] == "TaskContext"
        assert obj["task_id"] == "t1"

    def test_save_task_serializes_correctly(self, tmp_path):
        run_py = tmp_path / "run.py"
        call_args = []

        def fake_run(*args, **kwargs):
            call_args.append(args)
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        import subprocess
        original_run = subprocess.run
        subprocess.run = fake_run
        try:
            adapter = NCPPersistenceAdapter(mode="direct", run_path=str(run_py))
            task = type(
                "Task",
                (),
                {
                    "task_id": "t1",
                    "description": "test",
                    "complexity": "medium",
                    "current_phase": None,
                    "phase_results": [],
                },
            )()
            adapter.save_task(task)
            assert len(call_args) == 1
            cmd = call_args[0][0]
            assert cmd[-2] == "write_memory"
            payload = json.loads(cmd[-1])
            content = json.loads(payload["content"])
            assert content["_sarathi_type"] == "TaskContext"
            assert content["task_id"] == "t1"
        finally:
            subprocess.run = original_run

    def test_save_learning_uses_semantic_layer(self, tmp_path):
        run_py = tmp_path / "run.py"
        call_args = []

        def fake_run(*args, **kwargs):
            call_args.append(args)
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        import subprocess
        original_run = subprocess.run
        subprocess.run = fake_run
        try:
            adapter = NCPPersistenceAdapter(mode="direct", run_path=str(run_py))
            adapter.save_learning({"key": "value"})
            assert len(call_args) == 1
            payload = json.loads(call_args[0][0][-1])
            assert payload["layer"] == "semantic"
            assert payload["src"] == "synthesis"
            assert payload["written_by"] == "sarathi.engine.learning"
        finally:
            subprocess.run = original_run

    def test_save_phase_log_uses_reasoning_trace(self, tmp_path):
        run_py = tmp_path / "run.py"
        call_args = []

        def fake_run(*args, **kwargs):
            call_args.append(args)
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        import subprocess
        original_run = subprocess.run
        subprocess.run = fake_run
        try:
            adapter = NCPPersistenceAdapter(mode="direct", run_path=str(run_py))
            task = type("Task", (), {"task_id": "t1"})()
            adapter.save_phase_log(task, "Build", "done")
            assert len(call_args) == 1
            payload = json.loads(call_args[0][0][-1])
            assert payload["layer"] == "reasoning_trace"
            assert payload["src"] == "tool_result"
            assert payload["written_by"] == "sarathi.engine.t1"
            content = json.loads(payload["content"])
            assert content["task_id"] == "t1"
            assert content["phase"] == "Build"
            assert content["status"] == "done"
        finally:
            subprocess.run = original_run

    def test_list_tasks_deduplicates(self, tmp_path):
        run_py = tmp_path / "run.py"
        raw_stdout = """\
chunk:abc layer:episodic score:0.85
  {"_sarathi_type":"TaskContext","task_id":"t1","description":"a","complexity":"low","current_phase":null,"phase_results":[]}
chunk:def layer:episodic score:0.72
  {"_sarathi_type":"TaskContext","task_id":"t1","description":"b","complexity":"high","current_phase":null,"phase_results":[]}
chunk:ghi layer:episodic score:0.90
  {"_sarathi_type":"TaskContext","task_id":"t2","description":"c","complexity":"medium","current_phase":null,"phase_results":[]}
"""

        def fake_run(*args, **kwargs):
            return type("R", (), {"returncode": 0, "stdout": raw_stdout, "stderr": ""})()

        import subprocess
        original_run = subprocess.run
        subprocess.run = fake_run
        try:
            adapter = NCPPersistenceAdapter(mode="direct", run_path=str(run_py))
            result = adapter.list_tasks()
            assert result == ["t1", "t2"]
        finally:
            subprocess.run = original_run

    def test_load_task_deserializes(self, tmp_path):
        run_py = tmp_path / "run.py"
        raw_stdout = """\
chunk:abc layer:episodic score:0.85
  {"_sarathi_type":"TaskContext","task_id":"t1","description":"test task","complexity":"medium","current_phase":null,"phase_results":[]}
"""

        def fake_run(*args, **kwargs):
            return type("R", (), {"returncode": 0, "stdout": raw_stdout, "stderr": ""})()

        import subprocess
        original_run = subprocess.run
        subprocess.run = fake_run
        try:
            adapter = NCPPersistenceAdapter(mode="direct", run_path=str(run_py))
            result = adapter.load_task("t1")
            assert result is not None
            assert result["_sarathi_type"] == "TaskContext"
            assert result["task_id"] == "t1"
            assert result["description"] == "test task"
        finally:
            subprocess.run = original_run

    def test_load_task_returns_none_on_json_error(self, tmp_path):
        run_py = tmp_path / "run.py"
        raw_stdout = """\
chunk:abc layer:episodic score:0.85
  not valid json
"""

        def fake_run(*args, **kwargs):
            return type("R", (), {"returncode": 0, "stdout": raw_stdout, "stderr": ""})()

        import subprocess
        original_run = subprocess.run
        subprocess.run = fake_run
        try:
            adapter = NCPPersistenceAdapter(mode="direct", run_path=str(run_py))
            result = adapter.load_task("t1")
            assert result is None
        finally:
            subprocess.run = original_run
