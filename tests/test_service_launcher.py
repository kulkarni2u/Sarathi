import subprocess
import sys


def test_service_module_exposes_help():
    result = subprocess.run(
        [sys.executable, "-m", "src.service", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Run the Sarathi local desktop service." in result.stdout
    assert "--db" in result.stdout
    assert "--token" in result.stdout
