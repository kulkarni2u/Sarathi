"""Tests for the resident worker CLI (`sarathi worker start/stop/status`,
`sarathi run --background`) -- src/cli.py.
"""

from __future__ import annotations

import os
import signal
from argparse import Namespace

from src import cli
from src.storage import Storage, connect


class _FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid


def test_handle_worker_start_writes_pidfile_and_spawns_process(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeProcess(pid=999999)

    import subprocess as real_subprocess

    monkeypatch.setattr(real_subprocess, "Popen", fake_popen)

    cli.handle_worker(Namespace(worker_action="start", db=None))

    pidfile = tmp_path / ".sarathi" / "worker.pid"
    assert pidfile.exists()
    assert pidfile.read_text().strip() == "999999"
    assert captured["kwargs"]["start_new_session"] is True
    out = capsys.readouterr().out
    assert "Worker started (pid 999999)" in out


def test_handle_worker_start_when_already_running_is_noop(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    pidfile = tmp_path / ".sarathi" / "worker.pid"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text(str(os.getpid()))  # our own process: guaranteed alive

    import subprocess as real_subprocess

    def _explode(*args, **kwargs):
        raise AssertionError(
            "Popen should not be called when a worker is already running"
        )

    monkeypatch.setattr(real_subprocess, "Popen", _explode)

    cli.handle_worker(Namespace(worker_action="start", db=None))

    out = capsys.readouterr().out
    assert "already running" in out
    assert pidfile.read_text().strip() == str(os.getpid())


def test_handle_worker_start_replaces_stale_pidfile(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    pidfile = tmp_path / ".sarathi" / "worker.pid"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text("99999999")  # almost certainly not a live pid

    import subprocess as real_subprocess

    monkeypatch.setattr(real_subprocess, "Popen", lambda *a, **k: _FakeProcess(pid=42))

    cli.handle_worker(Namespace(worker_action="start", db=None))

    assert pidfile.read_text().strip() == "42"


def test_handle_worker_stop_sends_sigint_and_removes_pidfile(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    pidfile = tmp_path / ".sarathi" / "worker.pid"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text(str(os.getpid()))

    sent = {}

    def fake_kill(pid, sig):
        sent["pid"] = pid
        sent["sig"] = sig

    monkeypatch.setattr(os, "kill", fake_kill)

    cli.handle_worker(Namespace(worker_action="stop", db=None))

    assert sent == {"pid": os.getpid(), "sig": signal.SIGINT}
    assert not pidfile.exists()


def test_handle_worker_stop_without_pidfile_is_noop(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    cli.handle_worker(Namespace(worker_action="stop", db=None))

    out = capsys.readouterr().out
    assert "nothing to stop" in out


def test_handle_worker_status_variants(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    cli.handle_worker(Namespace(worker_action="status", db=None))
    assert "not running (no pidfile)" in capsys.readouterr().out

    pidfile = tmp_path / ".sarathi" / "worker.pid"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text(str(os.getpid()))
    cli.handle_worker(Namespace(worker_action="status", db=None))
    assert f"running (pid {os.getpid()})" in capsys.readouterr().out

    pidfile.write_text("99999999")
    cli.handle_worker(Namespace(worker_action="status", db=None))
    assert "stale pidfile" in capsys.readouterr().out


def test_run_background_creates_queued_full_engine_task(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "commands.md").write_text("# Commands\n")

    args = Namespace(task_description="Fix the login bug", complexity="low")
    cli._run_background(args, str(policy_dir))

    out = capsys.readouterr().out
    assert "Submitted task" in out
    assert "sarathi watch --follow" in out
    assert "No resident worker detected" in out

    conn = connect(tmp_path / ".sarathi" / "sarathi.db")
    storage = Storage(conn)
    tasks = storage.list_tasks()
    assert len(tasks) == 1
    task = tasks[0]
    assert task["status"] == "queued"
    assert task["metadata"]["execution_mode"] == "full_engine"
    assert task["metadata"]["complexity"] == "low"
    assert task["metadata"]["engine_task_id"].startswith("bg-")


def test_run_background_reuses_existing_workspace_for_same_root(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()

    cli._run_background(
        Namespace(task_description="First", complexity="low"), str(policy_dir)
    )
    cli._run_background(
        Namespace(task_description="Second", complexity="low"), str(policy_dir)
    )

    conn = connect(tmp_path / ".sarathi" / "sarathi.db")
    storage = Storage(conn)
    workspaces = storage.list_workspaces()
    assert len(workspaces) == 1
    assert len(storage.list_tasks()) == 2
