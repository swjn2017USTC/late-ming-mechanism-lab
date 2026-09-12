"""Smoke test for the console entry point."""

from typer.testing import CliRunner

from late_ming_lab import __version__
from late_ming_lab.cli import app

runner = CliRunner()


def test_version_flag_reports_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__
