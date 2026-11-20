"""Tests for sending measured task outcomes back to NCP (outcome feedback)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ncp_adapter import NCPContextAdapter, NCPPersistenceAdapter
from ncp_adapter.outcome import (
    SELF_REPORTED_WEIGHT,
    VERIFIED_WEIGHT,
    NCPOutcomeLedger,
    NCPOutcomeReporter,
    derive_ncp_outcome,
    parse_chunk_ids,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_TEMPLATE = REPO_ROOT / "docs" / "ncp" / "run.py.example"


class _Phase(Enum):
    BUILD = "Build"
    VERIFY = "Verify"
    REVIEW = "Review"


def _pr(phase: _Phase, outcome: str = "pass", **artifacts):
    return SimpleNamespace(phase=phase, outcome=outcome, artifacts=artifacts)


def _usage(inp: int, out: int) -> dict:
    return {"dispatch_usage": {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}}


def _outcome(*, signals=None, provenance=None, rollback=False):
    return SimpleNamespace(
        task_id="task-1",
        task_class=SimpleNamespace(value="codegen/patch"),
        quality_signals=signals or {},
        signal_provenance=provenance or {},
        rollback_triggered=rollback,
        agent_used="claude",
    )


# ── parsing ────────────────────────────────────────────────────────────────


def test_parse_chunk_ids_reads_fetch_and_get_context_headers():
    text = (
        "[NCP:SUBCONSCIOUS]\n"
        "chunk:sub_a layer:episodic src:tool_result trust:0.7\n"
        "  content mentioning chunk:not_a_header\n"
        "chunk:sub_b\n"
        "  more\n"
        "chunk:sub_a layer:episodic\n"
    )
    assert parse_chunk_ids(text) == ["sub_a", "sub_b"]
    assert parse_chunk_ids("") == []


# ── outcome rule ───────────────────────────────────────────────────────────


def test_verified_pass_is_full_weight_success_with_token_context():
    task = SimpleNamespace(
        phase_results=[
            _pr(_Phase.BUILD, **_usage(100, 40)),
            _pr(_Phase.VERIFY, verification_summary={"command_succeeded": True}),
            _pr(_Phase.REVIEW, **_usage(30, 10)),
        ]
    )
    derived = derive_ncp_outcome(
        task,
        _outcome(signals={"test_pass_rate": 1.0}, provenance={"test_pass_rate": "measured"}),
    )
    assert derived["success"] is True
    assert derived["weight"] == VERIFIED_WEIGHT
    assert derived["ctx"] == {
        "eval_source": "verifier",
        "turns": 2,
        "task": "codegen/patch",
        "model": "claude",
        "input_tokens": 130,
        "output_tokens": 50,
    }
    assert "all phases passed" in derived["note"]


def test_failure_outcomes_are_configurable():
    task = SimpleNamespace(phase_results=[_pr(_Phase.REVIEW, "escalate")])
    assert derive_ncp_outcome(task, _outcome())["success"] is False
    lenient = derive_ncp_outcome(task, _outcome(), failure_outcomes=("fail",))
    assert lenient["success"] is True


def test_no_measured_tests_is_half_weight_self_report():
    task = SimpleNamespace(phase_results=[_pr(_Phase.BUILD)])
    derived = derive_ncp_outcome(task, _outcome(provenance={"test_pass_rate": "missing"}))
    assert derived["success"] is True
    assert derived["weight"] == SELF_REPORTED_WEIGHT
    assert derived["ctx"]["eval_source"] == "self_report"
    assert "input_tokens" not in derived["ctx"]


@pytest.mark.parametrize(
    ("phase_results", "outcome", "reason"),
    [
        ([_pr(_Phase.BUILD, "fail")], _outcome(), "failed phases: Build=fail"),
        # Escalation means the task needed a human: not a success.
        ([_pr(_Phase.REVIEW, "escalate")], _outcome(), "failed phases: Review=escalate"),
        ([_pr(_Phase.BUILD)], _outcome(rollback=True), "rollback triggered"),
        (
            [_pr(_Phase.VERIFY)],
            _outcome(signals={"test_pass_rate": 0.0}, provenance={"test_pass_rate": "measured"}),
            "tests failed",
        ),
    ],
)
def test_measured_failures_are_failures(phase_results, outcome, reason):
    derived = derive_ncp_outcome(SimpleNamespace(phase_results=phase_results), outcome)
    assert derived["success"] is False
    assert reason in derived["note"]


# ── ledger ─────────────────────────────────────────────────────────────────


def test_ledger_scopes_to_task_and_drains():
    ledger = NCPOutcomeLedger()
    ledger.begin("t1")
    ledger.note_consumed(["a", "b", "a"])
    ledger.note_produced("w1")
    ledger.begin("t1")  # same task (resume): keeps what was collected
    assert ledger.snapshot() == {"consumed": ["b", "a"], "produced": ["w1"]}
    ledger.begin("t2")  # another task: starts clean
    assert ledger.snapshot() == {"consumed": [], "produced": []}
    ledger.note_consumed(["c"])
    assert ledger.drain() == {"consumed": ["c"], "produced": []}
    assert ledger.drain() == {"consumed": [], "produced": []}


def test_ledger_is_safe_under_parallel_fanout():
    ledger = NCPOutcomeLedger()
    ledger.begin("t")

    def worker(n: int) -> None:
        for i in range(200):
            ledger.note_consumed([f"c{n}_{i}"])
            ledger.note_produced(f"p{n}_{i}")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    snap = ledger.snapshot()
    assert len(snap["consumed"]) == 1600
    assert len(snap["produced"]) == 1600


# ── reporter ───────────────────────────────────────────────────────────────


def _reporter(ledger: NCPOutcomeLedger) -> NCPOutcomeReporter:
    return NCPOutcomeReporter(mode="direct", run_path="/nonexistent/run.py", ledger=ledger)


def test_reporter_skips_when_no_ncp_chunks_shaped_the_task():
    reporter = _reporter(NCPOutcomeLedger())
    with patch.object(reporter, "_call_record_outcome") as call:
        summary = reporter.report(SimpleNamespace(phase_results=[]), _outcome())
    call.assert_not_called()
    assert summary["recorded"] is False
    assert summary["skipped"] == "no_ncp_chunks"


def test_reporter_credits_consumed_and_produced_chunks_once():
    ledger = NCPOutcomeLedger()
    ledger.begin("task-1")
    ledger.note_consumed(["sub_r1", "sub_r2"])
    ledger.note_produced("sub_w1")
    ledger.note_produced("sub_r1")  # also read: credited once
    reporter = _reporter(ledger)
    with patch.object(
        reporter,
        "_call_record_outcome",
        return_value={"recorded": True, "outcome_id": "out_1", "calibrated": True},
    ) as call:
        summary = reporter.report(SimpleNamespace(phase_results=[_pr(_Phase.BUILD)]), _outcome())

    args = call.call_args.args[0]
    assert args["chunk_ids"] == ["sub_r1", "sub_r2", "sub_w1"]
    assert args["success"] is True
    assert summary == {
        "recorded": True,
        "success": True,
        "weight": SELF_REPORTED_WEIGHT,
        "eval_source": "self_report",
        "credited_chunks": 3,
        "consumed_chunks": 2,
        "produced_chunks": 2,
        "outcome_id": "out_1",
        "calibrated": True,
    }
    assert ledger.snapshot() == {"consumed": [], "produced": []}


def test_reporter_never_raises():
    ledger = NCPOutcomeLedger()
    ledger.note_consumed(["sub_r1"])
    reporter = _reporter(ledger)
    with patch.object(reporter, "_call_record_outcome", side_effect=RuntimeError("store down")):
        summary = reporter.report(SimpleNamespace(phase_results=[]), _outcome())
    assert summary["recorded"] is False
    assert "store down" in summary["error"]


def test_old_bridge_without_record_outcome_reports_unsupported(tmp_path):
    old_bridge = tmp_path / "run.py"
    old_bridge.write_text(
        "#!/usr/bin/env python3\nimport sys\n"
        "print(f'unknown command: {sys.argv[1]!r}', file=sys.stderr)\nsys.exit(2)\n"
    )
    old_bridge.chmod(0o755)
    ledger = NCPOutcomeLedger()
    ledger.note_consumed(["sub_r1"])
    summary = NCPOutcomeReporter(mode="direct", run_path=old_bridge, ledger=ledger).report(
        SimpleNamespace(phase_results=[]), _outcome()
    )
    assert summary["recorded"] is False
    assert "sarathi init" in summary["error"]


# ── transport crediting ────────────────────────────────────────────────────


def _completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.mark.parametrize(
    ("stdout", "credited"),
    [
        ("written:{id}\n", True),
        ("suppressed:{id}\n", False),  # near-duplicate: no chunk was created
        ("", False),  # bridge v1: ignores chunk_id, prints nothing
    ],
)
def test_direct_write_credits_only_confirmed_writes(stdout, credited):
    adapter = NCPPersistenceAdapter(mode="direct", run_path="/x/run.py")
    adapter.outcome_ledger = NCPOutcomeLedger()
    sent: dict = {}

    def fake_run(cmd, **kwargs):
        sent.update(json.loads(cmd[2]))
        return _completed(stdout.format(id=sent["chunk_id"]))

    with patch("ncp_adapter._transport.subprocess.run", side_effect=fake_run):
        adapter._call_write_memory("content", "episodic", "tool_result", "sarathi")

    assert sent["chunk_id"].startswith("sub_")
    expected = [sent["chunk_id"]] if credited else []
    assert adapter.outcome_ledger.snapshot()["produced"] == expected


def test_direct_fetch_and_get_context_credit_consumed_chunks():
    ledger = NCPOutcomeLedger()
    persistence = NCPPersistenceAdapter(mode="direct", run_path="/x/run.py")
    context = NCPContextAdapter(mode="direct", run_path="/x/run.py")
    persistence.outcome_ledger = context.outcome_ledger = ledger
    with patch(
        "ncp_adapter._transport.subprocess.run",
        return_value=_completed("chunk:sub_f1\n  one\nchunk:sub_f2\n  two\n"),
    ):
        persistence._call_fetch("q", k=2)
    with patch(
        "subprocess.run",
        return_value=_completed("[NCP:SUBCONSCIOUS]\nchunk:sub_g1 layer:episodic trust:0.7\n  x\n"),
    ):
        context._call_get_context({"task": "t"})
    assert ledger.snapshot()["consumed"] == ["sub_f1", "sub_f2", "sub_g1"]


def _mcp_response(result: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
    return response


def test_mcp_write_credits_written_chunk():
    adapter = NCPPersistenceAdapter(mode="mcp", endpoint="http://127.0.0.1:1/mcp")
    adapter.outcome_ledger = NCPOutcomeLedger()
    with patch("httpx.post", return_value=_mcp_response({"written": True, "chunk_id": "sub_m1"})):
        adapter._call_write_memory("c", "episodic", "tool_result", "sarathi")
    with patch("httpx.post", return_value=_mcp_response({"written": False, "chunk_id": "sub_m2"})):
        adapter._call_write_memory("c", "episodic", "tool_result", "sarathi")
    assert adapter.outcome_ledger.snapshot()["produced"] == ["sub_m1"]


def test_mcp_get_context_returns_context_text_and_credits_retrieved_ids():
    adapter = NCPContextAdapter(mode="mcp", endpoint="http://127.0.0.1:1/mcp")
    adapter.outcome_ledger = NCPOutcomeLedger()
    pidgin = "[NCP:SUBCONSCIOUS]\nchunk:sub_c1 layer:episodic\n  fact\n"
    with patch(
        "httpx.post",
        return_value=_mcp_response(
            {"context": pidgin, "retrieved_chunk_ids": ["sub_c1"], "session_id": "s"}
        ),
    ):
        text = adapter._call_get_context({"task": "t"})
    assert text == pidgin  # not the JSON envelope
    assert adapter.outcome_ledger.snapshot()["consumed"] == ["sub_c1"]


def test_mcp_log_cost_uses_post_turn_without_acknowledging_whispers():
    adapter = NCPPersistenceAdapter(mode="mcp", endpoint="http://127.0.0.1:1/mcp")
    with patch("httpx.post", return_value=_mcp_response({"recorded": True})) as post:
        adapter._call_log_cost(agent_id="claude", model="m", input_tokens=5, output_tokens=2)
    params = post.call_args.kwargs["json"]["params"]
    assert params["name"] == "ncp_post_turn"
    assert params["arguments"]["ack_whisper_ids"] == []
    assert params["arguments"]["retrieved_chunk_ids"] == []
    assert params["arguments"]["input_tokens"] == 5


# ── bridge upgrade in sarathi init ─────────────────────────────────────────


def _sidecar(tmp_path: Path, run_py: str | None) -> tuple[Path, dict]:
    sys.path.insert(0, str(REPO_ROOT))
    from src.cli import _ensure_ncp_sidecar

    ncp_dir = tmp_path / ".ncp"
    ncp_dir.mkdir()
    if run_py is not None:
        (ncp_dir / "run.py").write_text(run_py)
    return ncp_dir, _ensure_ncp_sidecar(tmp_path)


def test_init_upgrades_outdated_sarathi_bridge_and_keeps_backup(tmp_path):
    old = '"""Direct-mode bridge: Sarathi <-> NCP (neural-context-protocol) Python API."""\n# v1\n'
    ncp_dir, created = _sidecar(tmp_path, old)
    assert created["run_py_upgraded"] is True
    assert (ncp_dir / "run.py.bak").read_text() == old
    assert (ncp_dir / "run.py").read_text() == BRIDGE_TEMPLATE.read_text()


def test_init_leaves_current_and_foreign_bridges_alone(tmp_path):
    current = BRIDGE_TEMPLATE.read_text()
    ncp_dir, created = _sidecar(tmp_path, current)
    assert created["run_py_upgraded"] is False
    assert not (ncp_dir / "run.py.bak").exists()

    foreign_dir = tmp_path / "foreign"
    foreign_dir.mkdir()
    ncp_dir, created = _sidecar(foreign_dir, "#!/usr/bin/env python3\n# my own bridge\n")
    assert created["run_py_upgraded"] is False
    assert (ncp_dir / "run.py").read_text() == "#!/usr/bin/env python3\n# my own bridge\n"


# ── LEARN wiring ───────────────────────────────────────────────────────────


def test_learn_records_ncp_outcome_as_evidence():
    from src.engine import Phase
    from src.phases.learn import LearnHandler

    reporter = MagicMock()
    reporter.report.return_value = {"recorded": True, "credited_chunks": 2}
    handler = LearnHandler(SimpleNamespace(escalation={}), ncp_outcome_reporter=reporter)
    fake_outcome = _outcome()
    task = SimpleNamespace(task_id="task-1", phase_results=[], harness_config=object())
    with patch("src.harness.measure_outcome", return_value=fake_outcome), patch.object(
        handler.learning_store,
        "build_artifacts",
        return_value={"learning_record": {}, "lessons_learned": [], "patterns_updated": False},
    ), patch.object(handler.evolver, "ingest_harness_outcome", return_value=[]), patch.object(
        handler.evolver, "generate_policy_proposals", return_value=[]
    ):
        result = handler.execute(task, Phase.LEARN)

    reporter.report.assert_called_once_with(
        task, fake_outcome, failure_outcomes=("fail", "escalate")
    )
    assert result.evidence["ncp_outcome_recorded"] is True
    assert result.artifacts["ncp_outcome"] == {"recorded": True, "credited_chunks": 2}


# ── real NCP round trip ────────────────────────────────────────────────────


def test_real_ncp_outcome_moves_trust_of_credited_chunk(tmp_path, monkeypatch):
    """Bridge template + real NCP store: write, read back, record outcomes."""
    pytest.importorskip("ncp")
    if shutil.which("git") is None:
        pytest.skip("git required for NCP project-root discovery")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    ncp_dir = tmp_path / ".ncp"
    ncp_dir.mkdir()
    (ncp_dir / "config.toml").write_text(
        '[store]\ntype = "sqlite"\npath = ".ncp/store.db"\n\n[embedding]\nenabled = false\n'
    )
    run_py = ncp_dir / "run.py"
    shutil.copyfile(BRIDGE_TEMPLATE, run_py)
    run_py.chmod(0o755)
    monkeypatch.chdir(tmp_path)

    ledger = NCPOutcomeLedger()
    ledger.begin("task-1")
    persistence = NCPPersistenceAdapter(mode="direct", run_path=run_py)
    persistence.outcome_ledger = ledger
    persistence._call_write_memory(
        "billing exports run nightly at 02:00 UTC", "episodic", "tool_result", "sarathi"
    )
    [written] = ledger.snapshot()["produced"]
    assert persistence._call_fetch("billing exports nightly", k=3)
    assert written in ledger.snapshot()["consumed"]

    def base_trust() -> float:
        probe = (
            "import sys; from pathlib import Path; from ncp import configure; "
            "from ncp.stores import create_store; "
            "s = create_store(configure(cwd=Path('.'))); "
            "print(s.get_chunks_by_ids([sys.argv[1]])[0].base_trust)"
        )
        out = subprocess.run(
            [sys.executable, "-c", probe, written], capture_output=True, text=True, check=True
        )
        return float(out.stdout.strip().splitlines()[-1])

    before = base_trust()
    reporter = NCPOutcomeReporter(mode="direct", run_path=run_py, ledger=ledger)
    verified = _outcome(signals={"test_pass_rate": 1.0}, provenance={"test_pass_rate": "measured"})
    summary = reporter.report(SimpleNamespace(phase_results=[]), verified)
    assert summary["recorded"] is True and summary["calibrated"] is True
    raised = base_trust()
    assert raised > before

    ledger.begin("task-2")
    ledger.note_consumed([written])
    failed = _outcome(signals={"test_pass_rate": 0.0}, provenance={"test_pass_rate": "measured"})
    summary = reporter.report(SimpleNamespace(phase_results=[]), failed)
    assert summary["recorded"] is True and summary["success"] is False
    assert base_trust() < raised
