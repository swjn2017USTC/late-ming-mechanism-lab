"""The historical core as a run: the declared scenario, replay, and the provenance it leaves.

Two things are checked here that unit tests cannot: that the declared historical scenario reproduces
its recorded digest from the stored core, and that a run of it says which dataset and which forcing
produced it. The raw snapshots are not tracked, so both skip on a clone that has not acquired them —
and the skip says so rather than passing quietly.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import polars as pl
import pytest

from late_ming_lab.experiments.demo import load_scenario, run_demo
from late_ming_lab.experiments.historical_core import (
    HISTORICAL_OUTPUT_ROOT,
    run_historical,
)

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "data/scenarios/historical-core-v1.yaml"
CORE = ROOT / "data/normalized/v2/historical-core-v1"

pytestmark = pytest.mark.skipif(
    not (ROOT / "data/raw/private/chgis-v6/v6_time_cnty_pts_utf_wgs84.zip").is_file()
    or not CORE.is_dir(),
    reason="the raw snapshots and the built core are not present in this checkout",
)


def test_the_declared_historical_scenario_declares_the_historical_core() -> None:
    scenario = load_scenario(SCENARIO)
    assert scenario.sandbox.dataset == "historical-core-v1"
    assert scenario.sandbox.climate_mode == "observed-historical"
    assert scenario.ticks == 240


def test_the_declared_scenario_reproduces_its_recorded_digest(tmp_path: Path) -> None:
    outcome = run_demo(SCENARIO, output_root=tmp_path, root=ROOT)
    assert outcome.reproduced, outcome.details
    assert outcome.simulation_digest == load_scenario(SCENARIO).expected.simulation_digest


def test_the_smoke_window_runs_and_replays_identically() -> None:
    first = run_historical(ticks=24, warmup_ticks=6, root=ROOT)
    second = run_historical(ticks=24, warmup_ticks=6, root=ROOT)
    assert first.simulation_digest == second.simulation_digest
    assert first.event_count > 0
    assert first.county_count == 12


def test_a_written_run_carries_the_v2_provenance_beside_it(tmp_path: Path) -> None:
    outcome = run_historical(
        ticks=24,
        warmup_ticks=6,
        label="historical-core-v1-provenance-smoke",
        root=ROOT,
        output_root=tmp_path,
    )
    assert outcome.directory is not None
    sidecar = outcome.directory / "v2-provenance.json"
    assert sidecar.is_file()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "historical-run-provenance-v1"
    assert payload["dataset"] == "historical-core-v1"
    assert payload["sources"], "the run must name the source snapshots it was built from"
    assert payload["climate"]["series_id"] == "historical-core-v1"
    assert payload["climate"]["allocation_mode"] == "seasonal"
    assert payload["climate"]["imputed_node_years"] > 0
    # The V1 run manifest is untouched; the sidecar is where V2 provenance lives.
    assert (outcome.directory / "manifest.json").is_file()


def test_the_run_is_written_under_the_v2_root_and_not_into_v1() -> None:
    assert HISTORICAL_OUTPUT_ROOT.startswith("outputs/v2/")
    if not (ROOT / HISTORICAL_OUTPUT_ROOT).is_dir():
        pytest.skip("no historical run has been written in this checkout")
    runs = list((ROOT / HISTORICAL_OUTPUT_ROOT).iterdir())
    assert runs, "the historical output root exists but holds no run"
    for run in runs:
        assert (run / "agent_events.parquet").is_file()


def test_the_event_log_says_which_forcing_produced_each_shock() -> None:
    outcome = run_historical(ticks=24, warmup_ticks=6, root=ROOT)
    del outcome
    # The smoke run is written nowhere by default, so read the events from a written one.
    runs = sorted((ROOT / HISTORICAL_OUTPUT_ROOT).glob("*/agent_events.parquet"))
    if not runs:
        pytest.skip("no written historical run to read the event log from")
    events = pl.read_parquet(runs[-1])
    shocks = events.filter(pl.col("event_type") == "CLIMATE_SHOCK")
    assert shocks.height > 0
    assert set(shocks["outcome"].unique().to_list()) == {"observed-historical"}
    assert set(shocks["rule_version"].unique().to_list()) == {"climate-allocated-observed-v1"}
    counties = set(
        pl.read_parquet(CORE / "nodes.parquet").filter(pl.col("kind") == "county")["node_id"]
    )
    assert set(shocks["region"].unique().to_list()) == counties


def test_nothing_under_the_v1_output_roots_was_touched_by_a_historical_run() -> None:
    if not (ROOT / ".git").exists():
        pytest.skip("needs a git checkout")
    changed = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "outputs/runs",
            "outputs/experiments",
            "outputs/calibration",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert changed == "", f"a historical run must not touch the V1 artifact tree: {changed}"
