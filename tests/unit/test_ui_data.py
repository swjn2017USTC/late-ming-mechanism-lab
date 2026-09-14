"""The browser's loader, against the artifacts this repository has already written.

Nothing here runs the model. Two kinds of source are exercised: the real P10 batches on disk, which
are what the page opens on, and a hand-built run directory and batch directory in ``tmp_path``,
written in the layouts the storage module and the experiment runner use. The synthetic pair exists
so
the derivations can be checked against known numbers rather than against themselves — a departure of
four households has to arrive somewhere, and a share has to come back averaged while a count comes
back summed.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from late_ming_lab.storage.tables import write_json, write_table
from late_ming_lab.ui.data import (
    UiDataError,
    compare_runs,
    load_cards,
    load_run_view,
    series_catalog,
)

REPOSITORY = Path(__file__).resolve().parents[2]

#: The real batches this module reads: the P10 ablations, and a second batch to compare with.
ABLATIONS = REPOSITORY / "outputs" / "experiments" / "p10-ablations"
MORRIS = REPOSITORY / "outputs" / "experiments" / "p10-morris"

RUN_ID = "ui-fixture-20260914"
BATCH_LABEL = "ui-fixture-batch"

#: The columns of the event log the loader reads, with the identity columns a real log carries.
EVENT_SCHEMA = {
    "seq": pl.Int64,
    "tick": pl.Int64,
    "event_type": pl.String,
    "agent_id": pl.String,
    "region": pl.String,
    "trigger_json": pl.String,
    "outcome": pl.String,
}


def _events() -> pl.DataFrame:
    """Six months with one of every event the loader reads: migration, trade, a band, a garrison."""
    rows = [
        (0, "TICK", None, None, "{}", "month-advanced"),
        (
            1,
            "MIGRATION_DEPARTURE",
            "cohort-1",
            "toy-hn-a",
            '{"households_migrated":4.0,"adults_migrated":8.0,"land_abandoned_mu":12.0}',
            "migrated-to:toy-hn-b",
        ),
        (
            1,
            "MIGRATION_ARRIVAL",
            "cohort-1",
            "toy-hn-b",
            '{"households_arrived":4.0}',
            "arrived-from:toy-hn-a",
        ),
        (
            2,
            "MIGRATION_DEPARTURE",
            "cohort-2",
            "toy-sx-a",
            '{"households_migrated":6.0,"adults_migrated":12.0,"land_abandoned_mu":30.0}',
            "migrated-to:toy-hn-b",
        ),
        (
            2,
            "MIGRATION_ARRIVAL",
            "cohort-2",
            "toy-hn-b",
            '{"households_arrived":6.0}',
            "arrived-from:toy-sx-a",
        ),
        (
            3,
            "MIGRATION_EXIT",
            "cohort-3",
            "toy-sx-a",
            '{"households_exited":2.0,"adults_exited":4.0}',
            "left-region",
        ),
        (
            4,
            "TRADE_SHIPMENT",
            "merchant-1",
            "toy-hn-a",
            '{"shi":10.0,"arrived_shi":9.0}',
            "shipped-to:toy-hn-b",
        ),
        (
            5,
            "TRADE_SHIPMENT",
            "merchant-2",
            "toy-sx-a",
            '{"shi":4.0,"arrived_shi":4.0}',
            "shipped-to:toy-hn-b",
        ),
        (
            5,
            "TRADE_SHIPMENT",
            "merchant-1",
            "toy-hn-a",
            '{"shi":6.0,"arrived_shi":6.0}',
            "shipped-to:toy-hn-b",
        ),
        (5, "BAND_STATE", "band-1", "toy-sx-a", '{"troops":40.0,"cohesion":0.4}', "band-standing"),
        (
            5,
            "MILITARY_STATE",
            "garrison-1",
            "toy-sx-a",
            '{"troops":100.0,"grain_shi":50.0,"pay_arrears_tael":12.0,"morale":0.5}',
            "garrison-state",
        ),
        (
            2,
            "COUNTY_STATE",
            "county-1",
            "toy-hn-a",
            '{"quota_tael":100.0,"receipts_tael":80.0,"taxable_land_mu":1000.0}',
            "county-state",
        ),
        (
            3,
            "COUNTY_STATE",
            "county-1",
            "toy-hn-a",
            '{"quota_tael":100.0,"receipts_tael":70.0,"taxable_land_mu":900.0}',
            "county-state",
        ),
    ]
    return pl.DataFrame(
        {
            "seq": list(range(len(rows))),
            "tick": [row[0] for row in rows],
            "event_type": [row[1] for row in rows],
            "agent_id": [row[2] for row in rows],
            "region": [row[3] for row in rows],
            "trigger_json": [row[4] for row in rows],
            "outcome": [row[5] for row in rows],
        },
        schema=EVENT_SCHEMA,
    )


def _macro() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "tick": list(range(6)),
            "month": [f"1625-{month:02d}" for month in range(1, 7)],
            "year": [1625] * 6,
            "month_of_year": list(range(1, 7)),
            "period": ["warmup"] * 6,
        }
    )


def _run(
    directory: Path,
    *,
    events: pl.DataFrame | None = None,
    events_file: str = "events.parquet",
    macro_file: str = "macro.parquet",
) -> Path:
    """A run directory in the documented layout, written with the storage module's own writers."""
    directory.mkdir(parents=True)
    write_json(
        directory / "manifest.json",
        {
            "schema_version": "run-manifest-v1",
            "run_id": RUN_ID,
            "engine_version": "0.1.0",
            "git_sha": "0" * 40,
            "config_hash": "0" * 64,
            "root_seed": 20260914,
            "scenario_id": "ui-fixture",
            "policy_id": "noop-v1",
            "tick_count": 6,
            "llm_enabled": False,
        },
    )
    write_json(
        directory / "summary.json",
        {"schema_version": "run-summary-v1", "run_id": RUN_ID, "tick_count": 6, "event_count": 12},
    )
    write_table(directory / events_file, _events() if events is None else events)
    write_table(directory / macro_file, _macro())
    return directory


def _batch(directory: Path, *, ticks: list[int]) -> Path:
    """A batch directory with two labels of two replicates, in the runner's own file names."""
    directory.mkdir(parents=True)
    write_json(
        directory / "manifest.json",
        {
            "schema_version": "experiment-batch-v1",
            "label": BATCH_LABEL,
            "labels": ["A", "B"],
            "replicates": [0, 1],
            "ticks": 30,
        },
    )
    rows: list[dict[str, object]] = []
    for label, base, shares in (("A", 1, (0.1, 0.3)), ("B", 4, (0.5, 0.5))):
        for replicate in (0, 1):
            for offset, tick in enumerate(ticks):
                rows.append(
                    {
                        "label": label,
                        "replicate": replicate,
                        "tick": tick,
                        "crossed": base + offset,
                        "largest_band_share": shares[replicate],
                    }
                )
    runs = pl.DataFrame(rows).unique(subset=["label", "replicate"], maintain_order=True)
    write_table(
        directory / "runs.parquet",
        runs.select(["label", "replicate", pl.col("crossed").alias("breakdown")]),
    )
    write_table(
        directory / "governance_timeline.parquet",
        pl.DataFrame(rows).select(["label", "replicate", "tick", "crossed", "largest_band_share"]),
    )
    return directory


@pytest.fixture
def run_directory(tmp_path: Path) -> Path:
    return _run(tmp_path / RUN_ID)


def test_a_run_directory_loads_in_the_documented_layout(run_directory: Path) -> None:
    """The layout the phase documents is the layout the loader recognises as a run."""
    view = load_run_view(run_directory)

    assert view.kind == "run"
    assert view.label == RUN_ID
    assert view.source == run_directory
    assert view.manifest["run_id"] == RUN_ID
    assert view.summary["tick_count"] == 6
    assert view.runs.height == 0
    assert view.county_nodes == ("toy-hn-a", "toy-hn-b", "toy-sx-a")
    assert len(series_catalog(view)) > 10


@pytest.mark.parametrize(
    ("events_file", "macro_file"),
    [("events.parquet", "macro.parquet"), ("agent_events.parquet", "macro_timeseries.parquet")],
)
def test_the_storage_module_names_and_the_documented_names_load_alike(
    tmp_path: Path, events_file: str, macro_file: str
) -> None:
    """One artifact has two spellings, and both are this run's log and macro frame."""
    view = load_run_view(_run(tmp_path / RUN_ID, events_file=events_file, macro_file=macro_file))

    assert view.kind == "run"
    assert view.series.height == 6


def test_the_series_are_read_from_the_log(tmp_path: Path) -> None:
    """Every per-tick number is a reduction of the log, so a departure of four reads as four."""
    view = load_run_view(_run(tmp_path / RUN_ID))

    assert view.series.sort("tick")["households_departed"].to_list() == [
        0.0,
        4.0,
        6.0,
        0.0,
        0.0,
        0.0,
    ]
    assert view.series["households_exited"].sum() == 2.0
    assert view.series["households_arrived"].sum() == 10.0
    assert view.series["quota_tael"].sum() == 200.0
    assert view.series["garrison_troops"].to_list()[-1] == 100.0
    assert view.series.sort("tick")["number_of_bands"].to_list() == [0, 0, 0, 0, 0, 1]


def test_the_node_frame_carries_the_tick_and_the_net_that_follows(tmp_path: Path) -> None:
    """A departure and an exit belong to the origin, an arrival to the destination."""
    view = load_run_view(_run(tmp_path / RUN_ID))
    at_tick_two = view.migration.filter(pl.col("tick") == 2)
    origin = at_tick_two.filter(pl.col("node_id") == "toy-sx-a")

    assert set(at_tick_two["node_id"].to_list()) == {"toy-hn-b", "toy-sx-a"}
    assert origin["net_households"].to_list() == [-6.0]
    assert origin["land_abandoned_mu"].to_list() == [30.0]
    assert at_tick_two.filter(pl.col("node_id") == "toy-hn-b")["net_households"].to_list() == [6.0]
    exited = view.migration.filter(pl.col("tick") == 3)
    assert exited["households_gone"].to_list() == [2.0]
    assert exited["net_households"].to_list() == [0.0]


def test_the_trade_frame_measures_the_runs_own_links(tmp_path: Path) -> None:
    """Two links among three nodes: one group of three when both carry, two when only one does."""
    view = load_run_view(_run(tmp_path / RUN_ID))
    series = view.series.sort("tick")
    trade = view.trade.sort("tick")

    assert series["links_observed"].to_list() == [2] * 6
    assert series["nodes_observed"].to_list() == [3] * 6
    assert series["active_links"].to_list() == [0, 0, 0, 0, 1, 2]
    assert trade["active_link_share"].to_list() == [0.0, 0.0, 0.0, 0.0, 0.5, 1.0]
    assert trade["largest_component_share"][-1] == 1.0
    assert trade["largest_component_share"][0] == pytest.approx(1 / 3)


def test_a_measure_the_log_cannot_support_is_absent_rather_than_invented(tmp_path: Path) -> None:
    """A log with no county state and no garrison has neither series, and says so by omission."""
    migration_only = _events().filter(
        ~pl.col("event_type").is_in(["COUNTY_STATE", "MILITARY_STATE", "BAND_STATE"])
    )
    view = load_run_view(_run(tmp_path / RUN_ID, events=migration_only))
    keys = {spec.key for spec in series_catalog(view)}

    assert "households_departed" in keys
    assert "households_departed" in view.series.columns
    assert "receipts_tael" not in keys
    assert "garrison_troops" not in keys


def test_a_run_refuses_a_label(tmp_path: Path) -> None:
    """A run holds no arms, so selecting one is a mistake rather than an empty selection."""
    with pytest.raises(UiDataError, match="single run"):
        load_run_view(_run(tmp_path / RUN_ID), label="BASELINE")


def test_a_directory_with_neither_layout_is_refused(tmp_path: Path) -> None:
    """The refusal names what it found, so a wrong path is visible rather than empty."""
    directory = tmp_path / "neither"
    directory.mkdir()
    (directory / "notes.txt").write_text("not an artifact", encoding="utf-8")

    with pytest.raises(UiDataError) as raised:
        load_run_view(directory)

    assert "notes.txt" in str(raised.value)
    assert "neither a run" in str(raised.value)


def test_a_missing_source_is_refused(tmp_path: Path) -> None:
    with pytest.raises(UiDataError, match="not a directory"):
        load_run_view(tmp_path / "absent")


def test_a_batch_directory_loads_its_label_set_and_a_catalog() -> None:
    """The batch on disk loads with the arms its own manifest declares."""
    view = load_run_view(ABLATIONS)

    assert view.kind == "batch"
    assert view.label == "p10-ablations"
    assert view.summary["labels"] == tuple(view.manifest["labels"])
    assert len(view.summary["labels"]) == 13
    assert view.runs.height == 52
    catalog = series_catalog(view)
    assert catalog
    assert {spec.scope for spec in catalog} == {"tick", "node"}


def test_a_batch_without_a_label_combines_the_labels_and_a_label_selects_one() -> None:
    """The aggregate is stated and every run of the batch is behind it; an arm is its own runs."""
    view = load_run_view(ABLATIONS)
    arm = load_run_view(ABLATIONS, label="BASELINE")

    assert view.summary["run_count"] == view.runs.height == 52
    assert "13 labels" in str(view.summary["aggregation"])
    assert view.series.height == 30
    assert arm.runs.height == 4
    assert set(arm.runs["label"].to_list()) == {"BASELINE"}
    assert "label BASELINE" in str(arm.summary["aggregation"])
    assert bool((arm.series["crossed"] <= view.series["crossed"]).all())


def test_the_aggregate_sums_counts_and_averages_shares(tmp_path: Path) -> None:
    """The pinned rule: four runs of one tick sum a count and average a share."""
    view = load_run_view(_batch(tmp_path / BATCH_LABEL, ticks=[0, 10, 20]))

    assert view.summary["aggregation"].startswith("combined over 2 labels and 2 replicated runs")
    assert view.series.sort("tick")["crossed"].to_list() == [10, 14, 18]
    assert view.series.sort("tick")["largest_band_share"].to_list() == pytest.approx(
        [0.35, 0.35, 0.35]
    )


def test_a_label_narrows_a_batch_to_that_arm(tmp_path: Path) -> None:
    """One arm's own runs and its own per-tick numbers, not the batch's total."""
    view = load_run_view(_batch(tmp_path / BATCH_LABEL, ticks=[0, 10, 20]), label="A")
    whole = load_run_view(_batch(tmp_path / "whole", ticks=[0, 10, 20]))

    assert view.label == f"{BATCH_LABEL} / A"
    assert view.runs.height == 2
    assert set(view.runs["label"].to_list()) == {"A"}
    assert view.series.sort("tick")["crossed"].to_list() == [2, 4, 6]
    assert view.series.sort("tick")["largest_band_share"].to_list() == pytest.approx(
        [0.2, 0.2, 0.2]
    )
    assert bool((view.series["crossed"] <= whole.series["crossed"]).all())


def test_a_batch_refuses_a_label_it_does_not_hold(tmp_path: Path) -> None:
    with pytest.raises(UiDataError, match="no label"):
        load_run_view(_batch(tmp_path / BATCH_LABEL, ticks=[0, 10, 20]), label="C")


def test_a_comparison_is_refused_across_different_tick_counts(tmp_path: Path) -> None:
    """A batch sampled on another grid is not comparable, and says so rather than aligning."""
    short = _batch(tmp_path / BATCH_LABEL, ticks=[0, 10, 20])

    with pytest.raises(UiDataError) as raised:
        compare_runs(short, ABLATIONS)

    assert "carries 3 ticks" in str(raised.value)
    assert "carries 30" in str(raised.value)


def test_a_comparison_reports_the_two_sides_and_their_provenance() -> None:
    """Two real batches share the series their tables have in common and differ in provenance."""
    comparison = compare_runs(ABLATIONS, MORRIS)

    assert comparison.series == (
        "arrears_tael",
        "crossed",
        "receipts_tael",
        "taxable_land_mu",
        "year",
    )
    for key in comparison.series:
        assert f"{key}@left" in comparison.aligned.columns
        assert f"{key}@right" in comparison.aligned.columns
    assert comparison.aligned.height == 30
    fields = [field for field, _, _ in comparison.manifest_differences]
    assert fields == sorted(fields)
    assert ("label", "p10-ablations", "p10-morris") in comparison.manifest_differences
    assert all(left != right for _, left, right in comparison.manifest_differences)


def test_the_catalog_lists_only_columns_the_frames_carry() -> None:
    """A series a source does not record is absent, never offered as an empty line."""
    view = load_run_view(ABLATIONS)
    catalog = series_catalog(view)

    assert len({spec.key for spec in catalog}) == len(catalog)
    for spec in catalog:
        frame = view.series if spec.scope == "tick" else view.migration
        assert spec.key in frame.columns
        assert spec.label
    units = {spec.key: spec.unit for spec in catalog}
    assert units["crossed"] == "lines"
    assert units["receipts_tael"] == "tael"
    assert units["net_households"] == "households"


def test_the_cards_are_the_six_the_phase_wrote(tmp_path: Path) -> None:
    """The six candidates, in id order, read the way the report module reads them."""
    book = load_cards(REPOSITORY)

    assert [card.id for card in book.cards] == ["M001", "M002", "M003", "M004", "M005", "M006"]

    with pytest.raises(UiDataError, match="no mechanism cards"):
        load_cards(tmp_path)
