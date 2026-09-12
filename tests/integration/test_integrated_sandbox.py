"""The integrated sandbox as a test: two spaces, both climates, one metric row each.

This is the phase's acceptance test. It runs the whole wired model — every mechanism from P02 to
P06 plus migration — on the five-county and twelve-county fixtures, and asserts the properties the
phase's question is about:

- it runs at both scales, and produces every metric the phase promised;
- the same scenario twice produces identical events (reproducibility);
- the governance indicators agree with the measurements they were read from, cross-checked between
  two analysis modules that compute them independently;
- the medium fixture's extra counties show up in the metrics rather than being silently ignored.

It is deliberately not a test of *outcomes*: nothing here asserts that distress rose, that bands
formed or that receipts fell, because none of that is this phase's question.
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.analysis.integrated import METRIC_COLUMNS
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.experiments.integrated import (
    IntegratedRun,
    IntegratedScenario,
    run_integrated_experiment,
    run_integrated_scenario,
)

#: Long enough for the distress window to make cohorts eligible, so both scales really do migrate.
COMPACT_CONFIG = SimulationConfig.model_validate({"tick_count": 120, "warmup_ticks": 12})

TOY = IntegratedScenario(
    label="toy-integration", dataset="toy", monthly_event_probability=0.4, severity_floor=0.6
)
MEDIUM = IntegratedScenario(
    label="medium-integration", dataset="medium", monthly_event_probability=0.4, severity_floor=0.6
)


@pytest.fixture(scope="module")
def both_scales() -> tuple[IntegratedRun, IntegratedRun]:
    toy = run_integrated_scenario(TOY, config=COMPACT_CONFIG)
    medium = run_integrated_scenario(MEDIUM, config=COMPACT_CONFIG)
    return toy, medium


def test_both_scales_run_and_produce_every_promised_metric(
    both_scales: tuple[IntegratedRun, IntegratedRun],
) -> None:
    for run in both_scales:
        assert run.result.summary.event_count > 0
        assert run.result.summary.tick_count == COMPACT_CONFIG.tick_count
        assert run.economy.migration is not None, "the sandbox must wire migration"
        events = run.result.events
        # Every mechanism the phase claims to connect actually wrote something.
        for event_type in (
            "CLIMATE_SHOCK",
            "HARVEST",
            "CONSUMPTION",
            "MARKET_STATE",
            "TAX_RECEIPT",
            "OFFICIAL_RELIEF",
            "MILITARY_PAY_DUE",
            "DESERTERS_LEFT",
            "BAND_STATE",
            "SUPPRESSION",
        ):
            assert events.filter(pl.col("event_type") == event_type).height > 0, (
                f"{run.scenario.label}: {event_type} never fired, so the sandbox is not wired"
            )


def test_the_medium_fixture_is_actually_bigger(
    both_scales: tuple[IntegratedRun, IntegratedRun],
) -> None:
    toy, medium = both_scales
    toy_nodes = len(toy.economy.graphs.nodes.counties)
    medium_nodes = len(medium.economy.graphs.nodes.counties)

    assert toy_nodes == 5
    assert medium_nodes == 12
    assert medium.result.summary.event_count > toy.result.summary.event_count
    assert medium.starting_households > toy.starting_households * 2


def test_the_same_scenario_run_twice_is_the_same_run() -> None:
    first = run_integrated_scenario(TOY, config=COMPACT_CONFIG)
    second = run_integrated_scenario(TOY, config=COMPACT_CONFIG)

    assert first.result.summary.simulation_digest == second.result.summary.simulation_digest
    assert first.result.events.equals(second.result.events)


def test_the_metric_table_reports_every_column_for_every_scenario() -> None:
    results = run_integrated_experiment(scenarios=(TOY, MEDIUM), config=COMPACT_CONFIG)

    assert results.metrics.height == 2
    assert list(results.metrics.columns) == list(METRIC_COLUMNS)
    for column in METRIC_COLUMNS:
        assert results.metrics[column].null_count() == 0, f"{column} has holes in it"
    assert set(results.metrics["scenario"]) == {"toy-integration", "medium-integration"}
    assert (
        results.metrics.filter(
            pl.col("population_households_end") <= pl.col("population_adults_end")
        ).height
        == results.metrics.height
    )


def test_the_governance_count_agrees_with_the_indicators_it_counts() -> None:
    results = run_integrated_experiment(scenarios=(TOY,), config=COMPACT_CONFIG)
    metrics = results.metrics.row(0, named=True)
    governance = results.governance.filter(pl.col("scenario") == "toy-integration")

    assert governance.height == int(metrics["indicators_reported"])
    assert governance.filter(pl.col("crossed")).height == int(metrics["indicators_crossed"])
    named = set(filter(None, str(metrics["indicators_crossed_names"]).split(",")))
    assert named == set(governance.filter(pl.col("crossed"))["indicator"].to_list())


def test_every_series_the_report_promises_is_written() -> None:
    results = run_integrated_experiment(scenarios=(TOY, MEDIUM), config=COMPACT_CONFIG)

    for frame in (
        results.governance,
        results.governance_series,
        results.distress,
        results.price_dispersion,
        results.migration_flows,
        results.migration_nodes,
        results.band_series,
        results.tax_base,
    ):
        assert not frame.is_empty()
        assert "scenario" in frame.columns
        assert set(frame["scenario"].unique()) == {"toy-integration", "medium-integration"}


def test_the_regional_migration_columns_cancel_except_for_the_exits() -> None:
    results = run_integrated_experiment(scenarios=(TOY,), config=COMPACT_CONFIG)
    metrics = results.metrics.row(0, named=True)
    nodes = results.migration_nodes.filter(pl.col("scenario") == "toy-integration")

    net = float(nodes["net_households"].sum() or 0.0)
    assert net == pytest.approx(-float(metrics["households_exited"]), rel=1e-6), (
        "within the region migration only moves households about; the exits are the loss"
    )
