import json
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
            mock_run.return_value = MagicMock(returncode=0, stdout='{"whisper_id": "wsp_1"}', stderr="")
            router = NCPWhisperRouter(mode="direct", run_path=str(tmp_path / "run.py"))
            whisper_id = router.emit("s.pravaha", "s.samanvaya", "consolidation_ready",
                                     "task:t1:phase:Build:status:pass", 0.95, pipeline_id="sarathi_t1")
            assert whisper_id == "wsp_1"
            cmd = mock_run.call_args.args[0]
            assert cmd[1] == "emit_whisper"
            sent = json.loads(cmd[2])
            assert sent["target"] == "s.samanvaya" and sent["pipeline_id"] == "sarathi_t1"
            assert sent["whisper_type"] == "nudge"  # Sarathi's kind travels in the payload
            assert json.loads(sent["payload"]) == {
                "kind": "consolidation_ready", "text": "task:t1:phase:Build:status:pass"
            }

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


def test_real_ncp_whispers_are_targeted_task_scoped_and_acknowledged(tmp_path, monkeypatch):
    """Bridge template + real NCP store: no cross-task or unaddressed delivery."""
    import shutil
    import subprocess
    from pathlib import Path

    pytest.importorskip("ncp")
    if shutil.which("git") is None:
        pytest.skip("git required for NCP project-root discovery")
    from ncp_adapter import NCPContextAdapter, NCPPersistenceAdapter
    from ncp_adapter.whisper_router import pipeline_for_task

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    ncp_dir = tmp_path / ".ncp"
    ncp_dir.mkdir()
    (ncp_dir / "config.toml").write_text(
        '[store]\ntype = "sqlite"\npath = ".ncp/store.db"\n\n[embedding]\nenabled = false\n'
    )
    template = Path(__file__).resolve().parents[2] / "docs" / "ncp" / "run.py.example"
    shutil.copyfile(template, ncp_dir / "run.py")
    (ncp_dir / "run.py").chmod(0o755)
    monkeypatch.chdir(tmp_path)
    run_path = ncp_dir / "run.py"
    router = NCPWhisperRouter(mode="direct", run_path=run_path)
    context = NCPContextAdapter(mode="direct", run_path=run_path)
    NCPPersistenceAdapter(mode="direct", run_path=run_path)._call_write_memory(
        "database credentials rotate every 30 days", "episodic", "tool_result", "sarathi"
    )

    task_a, task_b = pipeline_for_task("A"), pipeline_for_task("B")
    router.emit("s.sarathi", "s.n1-branch-1", "fanout_context", json.dumps({"from_task": "A"}), pipeline_id=task_a)
    router.emit("s.sarathi", "s.n1-branch-1", "classify_context", json.dumps({"from_task": "B"}), pipeline_id=task_b)

    signals_a, ids_a = context._fetch_node_whispers("n1-branch-1", task_a)
    signals_b, _ = context._fetch_node_whispers("n1-branch-1", task_b)
    assert len(signals_a) == 1 and '"from_task": "A"' in signals_a[0]
    assert len(signals_b) == 1 and '"from_task": "B"' in signals_b[0]
    # A node nobody addressed gets nothing (not unrelated memory).
    assert context._fetch_node_whispers("n9-branch-1", task_a) == ([], [])

    assert router.ack("s.n1-branch-1", ids_a) == 1
    assert context._fetch_node_whispers("n1-branch-1", task_a) == ([], [])
    assert len(context._fetch_node_whispers("n1-branch-1", task_b)[0]) == 1
