import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "src.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_cli_without_arguments_shows_default_home():
    result = _run_cli()
    output = result.stdout + result.stderr

    assert result.returncode == 0
    assert "Sarathi" in output
    assert "chat" in output
    assert "status" in output
    assert "resume" in output
    assert "new workspace" in output
    assert "No command specified" not in output


def test_cli_help_still_lists_existing_subcommands():
    result = _run_cli("--help")
    output = result.stdout + result.stderr

    assert result.returncode == 0
    for command in ["init", "validate", "run", "log", "status", "watch", "resume", "list", "proposals", "agents"]:
        assert command in output
    assert "OPENAI_API_KEY is not set" not in output
