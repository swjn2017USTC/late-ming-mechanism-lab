"""Mass balance invariants over a full household run.

The event log is the ledger: these tests rebuild every cohort's balances from the events alone
and compare them with the state the cohort reports. Anything that moved without an entry, any
negative balance, and any silver that appeared from nowhere would show up here.
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.actors.fixtures import toy_cohort_population
from late_ming_lab.actors.households import (
    ASSETS_DELTA,
    DEBT_DELTA,
    GRAIN_DELTA,
    LAND_DELTA,
    LEDGER_KEYS,
    SILVER_DELTA,
    CohortEventType,
    HouseholdPopulation,
)
from late_ming_lab.analysis.distress import with_trigger_fields
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.experiments.household_shock import ShockScenario, run_scenario
from late_ming_lab.networks.fixtures import toy_spatial_dataset

BALANCE_BY_KEY = {
    GRAIN_DELTA: "grain_shi",
    SILVER_DELTA: "silver_tael",
    LAND_DELTA: "land_mu",
    DEBT_DELTA: "debt_tael",
    ASSETS_DELTA: "movable_assets_tael",
}

#: Silver may only appear from these transitions.
SILVER_SOURCES = {
    CohortEventType.BORROWING_REQUEST.value,
    CohortEventType.MOVABLE_ASSET_SALE.value,
    CohortEventType.LAND_SALE.value,
}

SHORT_CONFIG = SimulationConfig.model_validate({"tick_count": 48, "warmup_ticks": 12})


@pytest.fixture(scope="module")
def run() -> tuple[pl.DataFrame, HouseholdPopulation, dict[str, dict[str, float]]]:
    nodes = toy_spatial_dataset().build().nodes
    population = toy_cohort_population(nodes)
    initial = {
        cohort.cohort_id: {
            "households": cohort.households,
            "grain_shi": cohort.grain_shi,
            "silver_tael": cohort.silver_tael,
            "land_mu": cohort.land_mu,
            "debt_tael": cohort.debt_tael,
            "movable_assets_tael": cohort.movable_assets_tael,
        }
        for cohort in population
    }
    result = run_scenario(ShockScenario("severe", 0.5, 0.6), config=SHORT_CONFIG)
    return result.result.events, result.population, initial


def test_balances_reconcile_with_the_event_ledger(
    run: tuple[pl.DataFrame, HouseholdPopulation, dict[str, dict[str, float]]],
) -> None:
    events, population, initial = run
    cohort_events = events.filter(pl.col("agent_id").is_not_null())
    ledger = (
        with_trigger_fields(cohort_events, LEDGER_KEYS)
        .group_by("agent_id")
        .agg([pl.col(key).sum() for key in LEDGER_KEYS])
    )

    for row in ledger.iter_rows(named=True):
        cohort = population.require(row["agent_id"])
        for key, attribute in BALANCE_BY_KEY.items():
            expected = initial[cohort.cohort_id][attribute] + row[key]
            assert getattr(cohort, attribute) == pytest.approx(expected, rel=1e-9, abs=1e-9), (
                f"{cohort.cohort_id} {attribute} disagrees with the event ledger"
            )


def test_no_balance_ever_goes_negative(
    run: tuple[pl.DataFrame, HouseholdPopulation, dict[str, dict[str, float]]],
) -> None:
    events, _, initial = run
    cohort_events = events.filter(pl.col("agent_id").is_not_null())
    ledger = with_trigger_fields(cohort_events.sort(["tick", "seq"]), LEDGER_KEYS)
    running = {
        cohort_id: {attribute: balances[attribute] for attribute in BALANCE_BY_KEY.values()}
        for cohort_id, balances in initial.items()
    }
    for row in ledger.iter_rows(named=True):
        balances = running[row["agent_id"]]
        for key, attribute in BALANCE_BY_KEY.items():
            balances[attribute] += row[key]
            assert balances[attribute] >= -1e-9, (
                f"{row['agent_id']} {attribute} went negative at tick {row['tick']}"
            )


def test_reported_consumption_leaves_a_ledger_trace(
    run: tuple[pl.DataFrame, HouseholdPopulation, dict[str, dict[str, float]]],
) -> None:
    """Flow conservation: every shi reported as eaten was debited from a granary.

    The balance reconciliation above cannot catch a flow that is missing on both sides; this can.
    """
    events, _, _ = run
    consumption = with_trigger_fields(
        events.filter(pl.col("event_type") == CohortEventType.CONSUMPTION.value),
        ("eaten_shi", "from_storage_shi", "from_purchases_shi", GRAIN_DELTA),
    )

    assert consumption.height > 0
    totals = consumption.select(
        pl.col(GRAIN_DELTA).sum().alias("ledger"),
        pl.col("eaten_shi").sum().alias("reported"),
        (pl.col("from_storage_shi") + pl.col("from_purchases_shi") - pl.col("eaten_shi"))
        .abs()
        .max()
        .alias("split_error"),
        pl.col(GRAIN_DELTA).max().alias("worst_delta"),
    ).row(0, named=True)

    assert abs(totals["ledger"] + totals["reported"]) < 1e-6
    assert totals["split_error"] < 1e-9
    assert totals["worst_delta"] <= 0.0


def test_silver_never_appears_without_a_recorded_source(
    run: tuple[pl.DataFrame, HouseholdPopulation, dict[str, dict[str, float]]],
) -> None:
    events, _, _ = run
    credited = with_trigger_fields(events, (SILVER_DELTA,)).filter(pl.col(SILVER_DELTA) > 0.0)

    assert credited.height > 0, "a shock run should exercise at least one silver source"
    assert set(credited["event_type"].unique()) <= SILVER_SOURCES


def test_cohort_weight_is_conserved(
    run: tuple[pl.DataFrame, HouseholdPopulation, dict[str, dict[str, float]]],
) -> None:
    _, population, initial = run

    for cohort in population:
        assert cohort.households == initial[cohort.cohort_id]["households"]


def test_no_household_is_moved_or_recruited(
    run: tuple[pl.DataFrame, HouseholdPopulation, dict[str, dict[str, float]]],
) -> None:
    events, _, _ = run
    event_types = set(events["event_type"].unique())

    assert "MIGRATION" not in event_types
    assert "RECRUITMENT" not in event_types
    assert "DESERTION" not in event_types
    assert CohortEventType.ELIGIBILITY.value in event_types

    eligibility_outcomes = set(
        events.filter(pl.col("event_type") == CohortEventType.ELIGIBILITY.value)["outcome"]
    )
    assert all(
        outcome == "none"
        or outcome == "temporary-migration+permanent-migration+recruitment"
        or set(outcome.split("+")) <= {"temporary-migration", "permanent-migration", "recruitment"}
        for outcome in eligibility_outcomes
    )


def test_every_cohort_transition_has_a_rule_version(
    run: tuple[pl.DataFrame, HouseholdPopulation, dict[str, dict[str, float]]],
) -> None:
    events, _, _ = run
    cohort_events = events.filter(pl.col("agent_id").is_not_null())

    assert cohort_events["rule_version"].null_count() == 0
    assert set(cohort_events["rule_version"].unique()) >= {
        "household-survival-v1",
        "harvest-v1",
        "debt-service-v1",
        "eligibility-v1",
        "cohort-bookkeeping-v1",
    }
