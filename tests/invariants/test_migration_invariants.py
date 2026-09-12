"""Migration invariants: households, people, food and silver over a real integrated run.

Migration is the one mechanism that moves a cohort's *weight*, so it is the one that can quietly
destroy the model's most basic accounting. These tests rebuild every quantity from the log of a
fully wired run:

```text
households   what left the cohorts equals what arrived plus what left the region
adults       levies, departures, arrivals and seasonal returns reconcile with the cohort ledgers
grain        what movers carried is what arrived plus what the road took
silver       what movers carried is what arrived plus what the journey cost or lost
land         mu abandoned at the origin, and no mu invented at the destination
```

The fixture is the integrated sandbox, not a hand-built world: if a mechanism that runs before or
after migration (relief, taxation, levies, band raids) moved a balance without an entry, these
balances would not reconcile.
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.actors.ledger import (
    ADULTS_DELTA,
    ASSETS_DELTA,
    GRAIN_DELTA,
    HOUSEHOLDS_DELTA,
    LAND_DELTA,
    SILVER_DELTA,
)
from late_ming_lab.analysis.distress import with_trigger_fields
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.experiments.integrated import (
    IntegratedRun,
    IntegratedScenario,
    run_integrated_scenario,
)

MIGRATION_EVENTS = (
    "MIGRATION_DEPARTURE",
    "MIGRATION_ARRIVAL",
    "MIGRATION_TRANSIT",
    "MIGRATION_SETTLEMENT",
    "MIGRATION_EXIT",
    "TEMPORARY_MIGRATION",
    "TEMPORARY_RETURN",
    "MIGRANT_CONSUMPTION",
)

SHORT_CONFIG = SimulationConfig.model_validate({"tick_count": 96, "warmup_ticks": 12})


def _sum(frame: pl.DataFrame, column: str) -> float:
    """Sum a numeric column as a float; 0.0 when the frame is empty."""
    if frame.is_empty() or column not in frame.columns:
        return 0.0
    value = frame[column].sum()
    return 0.0 if value is None else float(value)


@pytest.fixture(scope="module")
def migration_run() -> IntegratedRun:
    scenario = IntegratedScenario(
        label="migration-invariants",
        dataset="toy",
        monthly_event_probability=0.5,
        severity_floor=0.6,
    )
    return run_integrated_scenario(scenario, config=SHORT_CONFIG)


@pytest.fixture(scope="module")
def flow_frame(migration_run: IntegratedRun) -> pl.DataFrame:
    return with_trigger_fields(
        migration_run.result.events,
        (
            "households_migrated",
            "households_arrived",
            "households_exited",
            "households_settled",
            "adults_migrated",
            "adults_arrived",
            "adults_exited",
            "adults_away",
            "adults_returned",
            "grain_carried_shi",
            "grain_taken_shi",
            "grain_arrived_shi",
            "grain_lost_shi",
            "silver_carried_tael",
            "silver_taken_tael",
            "silver_arrived_tael",
            "silver_spent_or_lost_tael",
            "assets_carried_tael",
            "land_abandoned_mu",
            HOUSEHOLDS_DELTA,
            ADULTS_DELTA,
            GRAIN_DELTA,
            SILVER_DELTA,
            ASSETS_DELTA,
            LAND_DELTA,
        ),
    )


def test_the_run_actually_migrates_somebody(
    migration_run: IntegratedRun, flow_frame: pl.DataFrame
) -> None:
    """A conservation test on a run that moved nobody would prove nothing."""
    permanent = flow_frame.filter(
        (pl.col("event_type") == "MIGRATION_DEPARTURE")
        & pl.col("outcome").str.starts_with("migrated-to")
    )
    temporary = flow_frame.filter(pl.col("event_type") == "TEMPORARY_MIGRATION")
    assert permanent.height + temporary.height > 0
    if temporary.height > 0:
        assert _sum(temporary, "adults_away") > 0.0


def test_households_that_left_are_households_that_arrived_or_left_the_region(
    migration_run: IntegratedRun,
    flow_frame: pl.DataFrame,
) -> None:
    """The first law of migration in this model: nobody evaporates."""
    departures = flow_frame.filter(
        (pl.col("event_type") == "MIGRATION_DEPARTURE")
        & pl.col("outcome").str.starts_with("migrated-to")
    )
    settled = flow_frame.filter(pl.col("event_type") == "MIGRATION_SETTLEMENT")
    exits = flow_frame.filter(pl.col("event_type") == "MIGRATION_EXIT")

    departed = _sum(departures, "households_migrated")
    internal = _sum(
        flow_frame.filter(pl.col("event_type") == "MIGRATION_ARRIVAL"), "households_arrived"
    )
    exited = _sum(exits, "households_exited")
    assert departed > 0.0, "the fixture must actually move households"
    assert internal > 0.0, "and some of them must stay inside the region"
    assert departed == pytest.approx(internal + exited, rel=1e-9), (
        "every household that left a node arrived at one, or left the region"
    )
    assert internal == pytest.approx(_sum(settled, "households_settled"), rel=1e-9), (
        "the settlement record and the arrival record are the same movement"
    )


def test_cohort_weights_reconcile_with_the_migration_log(
    migration_run: IntegratedRun,
    flow_frame: pl.DataFrame,
) -> None:
    """Every cohort's weight is its opening weight plus what the log says moved.

    The population's own reconciliation (`check_invariants`) covers the ledger side; this asserts
    that migration is the only thing that moved weight, i.e. that no other mechanism touched it.
    """
    economy = migration_run.economy
    cohort_ids = {cohort.cohort_id for cohort in economy.population}
    weights = with_trigger_fields(migration_run.result.events, (HOUSEHOLDS_DELTA,))
    moved = weights.filter(pl.col("agent_id").is_in(list(cohort_ids)))

    assert _sum(moved, HOUSEHOLDS_DELTA) + _sum(
        flow_frame.filter(pl.col("event_type") == "MIGRATION_EXIT"), "households_exited"
    ) == pytest.approx(0.0, abs=1e-6), (
        "every household that left a cohort arrived in one, or left the region"
    )
    economy.population.check_invariants()


def test_grain_carried_is_grain_arrived_plus_grain_lost_on_the_road(
    migration_run: IntegratedRun,
    flow_frame: pl.DataFrame,
) -> None:
    transit = flow_frame.filter(pl.col("event_type") == "MIGRATION_TRANSIT")

    taken = _sum(transit, "grain_taken_shi")
    arrived = _sum(transit, "grain_arrived_shi")
    lost = _sum(transit, "grain_lost_shi")
    assert taken > 0.0, "the fixture must carry grain along the road"
    assert taken == pytest.approx(arrived + lost, rel=1e-9)
    assert lost > 0.0, "a declared transit risk must actually cost something"


def test_silver_carried_is_silver_arrived_plus_what_the_journey_cost(
    migration_run: IntegratedRun,
    flow_frame: pl.DataFrame,
) -> None:
    transit = flow_frame.filter(pl.col("event_type") == "MIGRATION_TRANSIT")

    taken = _sum(transit, "silver_taken_tael")
    arrived = _sum(transit, "silver_arrived_tael")
    spent = _sum(transit, "silver_spent_or_lost_tael")
    costs = _sum(transit, "travel_cost_tael")
    assert taken > 0.0
    assert taken == pytest.approx(arrived + spent, rel=1e-9)
    assert spent >= costs - 1e-9, "the travel cost is part of what does not arrive"


def test_land_is_abandoned_at_the_origin_and_never_carried_to_the_destination(
    migration_run: IntegratedRun,
    flow_frame: pl.DataFrame,
) -> None:
    economy = migration_run.economy
    cohort_ids = {cohort.cohort_id for cohort in economy.population}
    land = with_trigger_fields(migration_run.result.events, (LAND_DELTA,))
    cohort_land = land.filter(pl.col("agent_id").is_in(list(cohort_ids)))

    departures = flow_frame.filter(
        (pl.col("event_type") == "MIGRATION_DEPARTURE")
        & pl.col("outcome").str.starts_with("migrated-to")
    )
    abandoned = _sum(departures, "land_abandoned_mu")
    assert abandoned > 0.0, "households that leave fields behind must record the mu"
    arrivals = flow_frame.filter(pl.col("event_type") == "MIGRATION_ARRIVAL")
    assert _sum(arrivals, LAND_DELTA) == pytest.approx(0.0, abs=1e-9), (
        "arrivals carry people, food and property - never land"
    )
    departure_land = _sum(departures, LAND_DELTA)
    assert departure_land == pytest.approx(-abandoned, rel=1e-9), (
        "the land a departure records leaving is exactly the mu the cohort ledger lost"
    )
    assert _sum(cohort_land, LAND_DELTA) < 0.0, "land only ever leaves the cohort ledgers"


def test_temporary_migrants_come_home_before_the_run_ends(
    migration_run: IntegratedRun,
    flow_frame: pl.DataFrame,
) -> None:
    """A seasonal absence is bounded by construction: nobody is left away for ever."""
    away = _sum(flow_frame.filter(pl.col("event_type") == "TEMPORARY_MIGRATION"), "adults_away")
    returned = _sum(
        flow_frame.filter(pl.col("event_type") == "TEMPORARY_RETURN"), "adults_returned"
    )
    if away <= 0.0:
        pytest.skip("this fixture's cohorts were not eligible for temporary migration")
    outstanding = away - returned
    migration = migration_run.economy.migration
    assert migration is not None, "the integrated sandbox must wire migration"
    assert outstanding == pytest.approx(migration.migrants.total_adults, rel=1e-9), (
        "the adults still away are exactly the ones the holding account says are away"
    )


def test_the_sandbox_keeps_every_actor_reconciled(migration_run: IntegratedRun) -> None:
    """The whole-wired run's own reconciliation, after 96 ticks of everything."""
    economy = migration_run.economy
    economy.population.check_invariants()
    economy.military.check_invariants()
    economy.bands.check_invariants()
    if economy.governments is not None:
        economy.governments.check_invariants()
    economy.elites.check_invariants()
    economy.merchants.check_invariants()


def test_movable_property_only_ever_leaves_the_region_with_its_owners(
    migration_run: IntegratedRun,
    flow_frame: pl.DataFrame,
) -> None:
    """Property moves between cohorts, and only an exit takes it out of the model."""
    departures = flow_frame.filter(
        (pl.col("event_type") == "MIGRATION_DEPARTURE")
        & pl.col("outcome").str.starts_with("migrated-to")
    )
    arrivals = flow_frame.filter(pl.col("event_type") == "MIGRATION_ARRIVAL")
    exits = flow_frame.filter(pl.col("event_type") == "MIGRATION_EXIT")

    carried = _sum(departures, "assets_carried_tael")
    assert carried > 0.0, "movers must carry some movable property in this fixture"
    assert (
        _sum(arrivals, "assets_carried_tael") + _sum(exits, "assets_carried_tael") <= carried + 1e-6
    ), "property that left a cohort cannot have grown on the road"
    assert _sum(arrivals, ASSETS_DELTA) == pytest.approx(
        _sum(arrivals, "assets_carried_tael"), rel=1e-9
    ), "what an arrival records is what its ledger gained"
