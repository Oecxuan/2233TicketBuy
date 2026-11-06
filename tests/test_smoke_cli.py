"""CLI 入口冒烟测试：确保 main.py 能被正常调用。"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"


def run_cli(args, cwd=None, timeout=120):
    return subprocess.run(
        [sys.executable, str(MAIN), *args],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


@pytest.mark.smoke
class TestCli:
    def test_help(self):
        result = run_cli(["--help"])
        assert result.returncode == 0
        assert "2233TicketBuy" in result.stdout
        assert "--grab" in result.stdout

    def test_create_example(self, tmp_path):
        result = run_cli(["--create-example"], cwd=tmp_path)
        assert result.returncode == 0

        example = tmp_path / "config.yaml.example"
        assert example.exists()

        import yaml

        data = yaml.safe_load(example.read_text(encoding="utf-8"))
        assert "user" in data
        assert "event" in data
        assert "strategy" in data
        assert data["strategy"]["enable_stock_check"] is True
