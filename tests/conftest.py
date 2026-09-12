"""Test configuration for stable local imports."""
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os
import shlex
import subprocess

import pytest


@pytest.fixture(autouse=True)
def block_unrequested_live_provider_processes(monkeypatch, request, tmp_path_factory):
    """Block real model execution; allow fake CLIs and read-only version/auth probes."""
    live_dir = ROOT / "tests" / "live"
    if os.environ.get("SARATHI_LIVE_TESTS") == "1" and live_dir in Path(str(request.node.path)).parents:
        return
    test_root = tmp_path_factory.getbasetemp().resolve()
    original_popen = subprocess.Popen
    provider_commands = {"claude", "codex", "opencode", "copilot"}

    def guarded_popen(args, *positional, **kwargs):
        words = shlex.split(args) if isinstance(args, str) else list(args)
        if words and Path(os.fsdecode(words[0])).name in provider_commands:
            if words[1:] in (["--version"], ["auth", "status"], ["auth", "list"]):
                return original_popen(args, *positional, **kwargs)
            executable = Path(os.fsdecode(words[0])).resolve()
            if executable.is_relative_to(test_root):
                return original_popen(args, *positional, **kwargs)
            raise RuntimeError("Live provider process blocked in unit tests; use an explicit tests/live run.")
        return original_popen(args, *positional, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", guarded_popen)
