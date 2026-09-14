"""CLI contract: version reporting and the end-to-end ``run``."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from late_ming_lab import __version__
from late_ming_lab.cli import app
from late_ming_lab.core.config import DEFAULT_ROOT_SEED, SimulationConfig
from late_ming_lab.storage.run_store import EVENTS_FILE, RunStore

runner = CliRunner()


def test_version_flag_reports_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_run_command_writes_a_complete_run_directory(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["run", "--output-root", str(tmp_path), "--ticks", "6", "--warmup", "2"],
    )

    assert result.exit_code == 0, result.output
    run_ids = RunStore(tmp_path).list_runs()
    assert len(run_ids) == 1
    assert f"run_id: {run_ids[0]}" in result.stdout
    assert "events: 6" in result.stdout
    manifest = RunStore(tmp_path).read_manifest(run_ids[0])
    assert (manifest.tick_count, manifest.llm_enabled) == (6, False)


def test_run_command_reports_the_regression_seed_by_default(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["run", "--output-root", str(tmp_path), "--ticks", "3", "--warmup", "1"],
    )

    assert result.exit_code == 0, result.output
    manifest = RunStore(tmp_path).read_manifest(RunStore(tmp_path).list_runs()[0])
    assert manifest.root_seed == DEFAULT_ROOT_SEED
    assert manifest.llm_enabled is False
    assert manifest.git_sha is not None


def test_run_command_is_reproducible_through_the_cli(tmp_path: Path) -> None:
    arguments = ["run", "--ticks", "6", "--warmup", "2"]
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"

    assert runner.invoke(app, [*arguments, "--output-root", str(first_root)]).exit_code == 0
    assert runner.invoke(app, [*arguments, "--output-root", str(second_root)]).exit_code == 0

    first = RunStore(first_root)
    second = RunStore(second_root)
    run_id = first.list_runs()[0]

    assert second.list_runs() == [run_id]
    assert (first.run_dir(run_id) / EVENTS_FILE).read_bytes() == (
        second.run_dir(run_id) / EVENTS_FILE
    ).read_bytes()
    assert first.read_summary(run_id).simulation_digest == (
        second.read_summary(run_id).simulation_digest
    )


def test_run_command_label_creates_a_distinct_run(tmp_path: Path) -> None:
    arguments = ["run", "--output-root", str(tmp_path), "--ticks", "3", "--warmup", "1"]

    assert runner.invoke(app, arguments).exit_code == 0
    labelled = runner.invoke(app, [*arguments, "--label", "repeat-2"])

    assert labelled.exit_code == 0, labelled.output
    assert len(RunStore(tmp_path).list_runs()) == 2


def test_run_command_reads_a_config_file_and_snapshots_it(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        SimulationConfig(
            scenario_id="kernel-smoke-file", tick_count=5, warmup_ticks=1, root_seed=11
        ).to_yaml(),
        encoding="utf-8",
    )

    result = runner.invoke(
        app, ["run", "--config", str(config_path), "--output-root", str(tmp_path / "runs")]
    )

    assert result.exit_code == 0, result.output
    store = RunStore(tmp_path / "runs")
    manifest = store.read_manifest(store.list_runs()[0])
    assert (manifest.root_seed, manifest.scenario_id, manifest.tick_count) == (
        11,
        "kernel-smoke-file",
        5,
    )
    assert store.read_config_snapshot(manifest.run_id) == config_path.read_text(encoding="utf-8")


def test_run_command_rejects_invalid_overrides(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["run", "--output-root", str(tmp_path), "--ticks", "4", "--warmup", "9"],
    )

    assert result.exit_code == 1
    assert "run failed" in result.output
    assert RunStore(tmp_path).list_runs() == []
