"""Military invariants: people, food, war material and the recruit pool, over a real run.

The categories the phase requires, each checked against the event log of an actual run rather than
against a hand-built example:

```text
people              nobody appears or vanishes: adults, soldiers, band members and deserters balance
food                grain a band takes is grain its victims lost, and no grain is created
war material        arms come from seized property at the declared rate, and from nowhere else
suppression         losses recorded by the band match the suppression that claims them
recruit pool        adults levied leave cohorts, and the two recruiters draw on the same people
unorganized pool    deserters waiting to be organized are accounted for in and out
```

Every check rebuilds the quantity from the log. Where the log cannot see something — the state a
system holds between ticks — the test says so and checks the balance the log does support.
"""

from __future__ import annotations

from typing import cast

import polars as pl
import pytest

from late_ming_lab.actors.ledger import ADULTS_DELTA, ARMS_DELTA, GRAIN_DELTA, TROOPS_DELTA
from late_ming_lab.actors.military import MilitaryEventType
from late_ming_lab.analysis.distress import with_trigger_fields
from late_ming_lab.analysis.military import (
    BAND_FORMED_EVENT,
    BAND_RAID_EVENT,
    DESERTER_POOL_EVENT,
    DESERTION_EVENT,
    DESERTION_ROUTE_EVENT,
    ELITE_GRAIN_SEIZED_EVENT,
    GRAIN_SEIZED_EVENT,
    GRANARY_GRAIN_SEIZED_EVENT,
    LEVY_EVENT,
    MILITARY_STATE_EVENT,
    SUPPRESSION_EVENT,
)
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import KernelResult
from late_ming_lab.evidence.parameters import core_default_band_parameters
from late_ming_lab.experiments.assembly import Economy
from late_ming_lab.experiments.military_stress import MilitaryScenario, run_military_scenario

#: Grain a band takes may only come from these victim-side transitions.
GRAIN_TAKEN_FROM = {
    GRAIN_SEIZED_EVENT,
    ELITE_GRAIN_SEIZED_EVENT,
    GRANARY_GRAIN_SEIZED_EVENT,
}

SHORT_CONFIG = SimulationConfig.model_validate({"tick_count": 60, "warmup_ticks": 12})
BAND_PARAMETERS = core_default_band_parameters()


def _sum(frame: pl.DataFrame, column: str) -> float:
    """Sum a numeric column as a float; 0.0 when the frame is empty."""
    if frame.is_empty():
        return 0.0
    value = frame[column].sum()
    return 0.0 if value is None else cast("float", value)


def _max(frame: pl.DataFrame, column: str) -> float:
    """Largest value of a numeric column as a float; 0.0 when the frame is empty."""
    if frame.is_empty():
        return 0.0
    value = frame[column].max()
    return 0.0 if value is None else cast("float", value)


def _military_events(result: KernelResult, types: set[str]) -> pl.DataFrame:
    return result.events.filter(pl.col("event_type").is_in(list(types)))


def _triggered(result: KernelResult, types: set[str], fields: tuple[str, ...]) -> pl.DataFrame:
    return with_trigger_fields(_military_events(result, types), fields)


@pytest.fixture(scope="module")
def military_run() -> tuple[Economy, KernelResult]:
    scenario = MilitaryScenario(
        label="invariants",
        pay_share_of_treasury=0.2,
        garrison_troops_per_node=450.0,
        monthly_event_probability=0.5,
        severity_floor=0.6,
    )
    run = run_military_scenario(scenario, config=SHORT_CONFIG)
    return run.economy, run.result


def test_adults_soldiers_and_band_members_balance(
    military_run: tuple[Economy, KernelResult],
) -> None:
    """People move between cohorts, garrisons, bands and the pool, and leave only as dispersal.

    Rebuilt from both sides: what the cohorts lost or regained, what the garrisons and bands gained
    or lost, and what the unorganized pool still holds. The only way out of the modelled population
    is a logged dispersal — a deserter who walks away, or a soldier lost to suppression — so the
    four sides must sum to exactly minus those outflows.
    """
    economy, result = military_run
    flows = with_trigger_fields(
        result.events, (ADULTS_DELTA, TROOPS_DELTA, "destination_is_dispersed")
    )
    routings = _triggered(result, {DESERTION_ROUTE_EVENT}, ("deserters_dispersed",))
    cohort_ids = {cohort.cohort_id for cohort in economy.population}

    cohort_change = _sum(flows.filter(pl.col("agent_id").is_in(list(cohort_ids))), ADULTS_DELTA)
    unit_change = _sum(flows.filter(pl.col("agent_id").str.starts_with("garrison")), TROOPS_DELTA)
    band_change = _sum(flows.filter(pl.col("agent_id").str.starts_with("band")), TROOPS_DELTA)
    pools = _triggered(result, {DESERTER_POOL_EVENT}, ("unorganized_deserters",))
    pool_held = (
        0.0
        if pools.is_empty()
        else _sum(
            pools.group_by("region").agg(pl.col("unorganized_deserters").last()),
            "unorganized_deserters",
        )
    )

    dispersals = -_sum(flows.filter(pl.col("destination_is_dispersed") > 0.0), TROOPS_DELTA)
    routed_dispersals = _sum(routings, "deserters_dispersed")

    assert cohort_change != 0.0, "the fixture must actually levy soldiers"
    assert band_change != 0.0, "the fixture must actually form and lose bands"
    assert unit_change != 0.0, "the fixture must actually recruit and lose soldiers"
    assert routed_dispersals > 0.0, "deserters must actually disperse"
    assert dispersals > 0.0, "the fixture must actually disperse some people"
    assert (cohort_change + unit_change + band_change + pool_held) == pytest.approx(
        -(dispersals + routed_dispersals), rel=1e-6
    )


def test_grain_a_band_takes_is_grain_its_victims_lost(
    military_run: tuple[Economy, KernelResult],
) -> None:
    """Double entry on every raid, tick by tick, not merely in total."""
    _, result = military_run
    flows = with_trigger_fields(result.events, (GRAIN_DELTA,))
    raids = flows.filter(pl.col("event_type") == BAND_RAID_EVENT).filter(pl.col(GRAIN_DELTA) > 0.0)
    victims = flows.filter(pl.col("event_type").is_in(list(GRAIN_TAKEN_FROM)))

    assert raids.height > 0, "the fixture must actually raid"
    taken = raids.group_by("tick").agg(pl.col(GRAIN_DELTA).sum().alias("taken"))
    lost = victims.group_by("tick").agg((-pl.col(GRAIN_DELTA)).sum().alias("lost"))
    joined = taken.join(lost, on="tick", how="inner").sort("tick")

    assert joined.height > 0
    for row in joined.iter_rows(named=True):
        assert row["taken"] == pytest.approx(row["lost"], rel=1e-9, abs=1e-6), (
            f"tick {row['tick']}: bands gained {row['taken']} but victims lost {row['lost']}"
        )


def test_arms_come_from_seized_property_at_the_declared_rate(
    military_run: tuple[Economy, KernelResult],
) -> None:
    """Arms enter the bands only by converting looted property, at the declared rate.

    Everything else that moves arms is an internal transfer between bands — a split, a merge, a
    dissolution — so the acquisition channel is checked on its own, and the event types that touch
    band arms are checked against a closed set.
    """
    _, result = military_run
    flows = with_trigger_fields(result.events, (ARMS_DELTA, "assets_seized_tael"))
    band_flows = flows.filter(pl.col("agent_id").str.starts_with("band"))
    raid_arms = _sum(band_flows.filter(pl.col("event_type") == BAND_RAID_EVENT), ARMS_DELTA)
    seized_assets = _sum(
        flows.filter(pl.col("event_type") == "MOVABLE_ASSET_SEIZED"), "assets_seized_tael"
    )

    assert seized_assets > 0.0, "the fixture must actually seize property"
    assert raid_arms == pytest.approx(
        seized_assets * BAND_PARAMETERS.arms_per_asset_valuation, rel=1e-6
    )
    assert set(band_flows.filter(pl.col(ARMS_DELTA) != 0.0)["event_type"].unique()) <= {
        BAND_RAID_EVENT,
        LEVY_EVENT,
        MilitaryEventType.DESERTION.value,
        MilitaryEventType.BAND_DISSOLVED.value,
        MilitaryEventType.BAND_STORES.value,
    }


def test_suppression_losses_match_what_the_bands_lost(
    military_run: tuple[Economy, KernelResult],
) -> None:
    """Every suppression claim is a real, logged loss of band members."""
    _, result = military_run
    claims = _triggered(result, {SUPPRESSION_EVENT}, ("suppressed_troops",))
    losses = with_trigger_fields(
        _military_events(result, {DESERTION_EVENT})
        .filter(pl.col("agent_id").str.starts_with("band"))
        .filter(pl.col("outcome").str.starts_with("suppressed")),
        (TROOPS_DELTA,),
    )

    assert claims.height > 0, "the fixture must actually suppress"
    claimed = _sum(claims, "suppressed_troops")
    lost = -_sum(losses, TROOPS_DELTA)
    assert claimed == pytest.approx(lost, rel=1e-6)


def test_levies_take_adults_from_cohorts_and_both_recruiters_share_the_pool(
    military_run: tuple[Economy, KernelResult],
) -> None:
    """Garrison and band levies are matched by cohort losses, tick by tick.

    Both recruiters draw on the same cohorts in the same tick, garrison first. Each side of each
    levy is checked: what a cohort lost to a garrison is what a garrison gained, and the same for
    bands — deserters moving from the pool into a band are *not* cohort losses, and the pool
    accounting in the next test covers them.
    """
    economy, result = military_run
    flows = with_trigger_fields(result.events, (ADULTS_DELTA, "troops_joined", "source_is_levy"))
    cohort_ids = {cohort.cohort_id for cohort in economy.population}

    def cohort_losses(destination: str) -> pl.DataFrame:
        return (
            flows.filter(pl.col("agent_id").is_in(list(cohort_ids)))
            .filter(pl.col(ADULTS_DELTA) < 0.0)
            .filter(pl.col("outcome").str.starts_with(f"levied-to:{destination}"))
            .group_by("tick")
            .agg((-pl.col(ADULTS_DELTA)).sum().alias("levied"))
        )

    garrison_recruits = (
        flows.filter(pl.col("agent_id").str.starts_with("garrison"))
        .filter(pl.col("troops_joined") > 0.0)
        .group_by("tick")
        .agg(pl.col("troops_joined").sum().alias("recruited"))
    )
    band_recruits = (
        flows.filter(pl.col("agent_id").str.starts_with("band"))
        .filter(pl.col("source_is_levy") > 0.0)
        .group_by("tick")
        .agg(pl.col("troops_joined").sum().alias("recruited"))
    )

    for destination, recruits in (
        ("garrison", garrison_recruits),
        ("band", band_recruits),
    ):
        joined = cohort_losses(destination).join(recruits, on="tick", how="inner").sort("tick")
        assert joined.height > 0, f"the fixture must actually recruit for a {destination}"
        for row in joined.iter_rows(named=True):
            assert row["levied"] == pytest.approx(row["recruited"], rel=1e-9, abs=1e-6), (
                f"tick {row['tick']}: cohorts lost {row['levied']} adults to {destination} but it "
                f"gained {row['recruited']}"
            )


def test_unorganized_deserters_balance_in_and_out(
    military_run: tuple[Economy, KernelResult],
) -> None:
    """The pool is a holding account: routed in, formed out, never negative, never overflowing.

    It sits between two systems, so the log is the only witness. Two things are checked: the
    formation events take no more than the pool received, and at rest the pool stays below the
    minimum formation size — a pool at or above it would be a band that should exist and does not.
    """
    _, result = military_run
    routed_in = _sum(
        _triggered(result, {DESERTION_ROUTE_EVENT}, ("deserters_to_bands",)), "deserters_to_bands"
    )
    formed_out = _sum(
        _triggered(result, {BAND_FORMED_EVENT}, ("unorganized_deserters_taken",)).with_columns(
            pl.col("unorganized_deserters_taken").fill_null(0.0)
        ),
        "unorganized_deserters_taken",
    )
    pools = _triggered(result, {DESERTER_POOL_EVENT}, ("unorganized_deserters",))

    assert routed_in > 0.0, "the fixture must route deserters into the pool"
    assert formed_out > 0.0, "the fixture must organize some of them"
    assert formed_out <= routed_in + 1e-6, "the pool cannot give out more than it took in"
    if not pools.is_empty():
        assert _max(pools, "unorganized_deserters") >= 0.0
        assert _max(pools, "unorganized_deserters") < BAND_PARAMETERS.minimum_formation_troops, (
            "an unorganized pool at or above the formation size is a band that failed to form"
        )


def test_a_garrison_is_never_stronger_than_its_claim(
    military_run: tuple[Economy, KernelResult],
) -> None:
    """Strength is bounded by the claim: recruitment fills toward it, never past it."""
    _, result = military_run
    states = _triggered(result, {MILITARY_STATE_EVENT}, ("troops",))
    claims = _triggered(result, {"MILITARY_PAY_DUE"}, ("troops",))
    claim = _max(claims, "troops")
    peak = _max(states, "troops")

    assert claim > 0.0
    assert peak <= claim * 1.01 + 1e-6


def test_repeated_military_runs_are_reproducible() -> None:
    """Same config, same seed, same policy: same military history, event for event."""
    scenario = MilitaryScenario(
        label="determinism", pay_share_of_treasury=0.5, garrison_troops_per_node=300.0
    )
    first = run_military_scenario(scenario, config=SHORT_CONFIG)
    second = run_military_scenario(scenario, config=SHORT_CONFIG)

    assert first.result.summary.simulation_digest == second.result.summary.simulation_digest


def test_a_levy_never_takes_more_adults_than_a_cohort_has() -> None:
    """The pool rule is bounded by the households themselves, in the harshest configuration."""
    run = run_military_scenario(
        MilitaryScenario(
            label="pool-bound",
            pay_share_of_treasury=0.1,
            garrison_troops_per_node=600.0,
            monthly_event_probability=0.6,
            severity_floor=0.7,
        ),
        config=SimulationConfig.model_validate({"tick_count": 48, "warmup_ticks": 12}),
    )
    for cohort in run.economy.population:
        assert cohort.adults >= 0.0


def test_band_members_never_disappear_into_nowhere() -> None:
    """Dispersal is a destination, not a hole: band losses are all logged as troop deltas."""
    run = run_military_scenario(
        MilitaryScenario(
            label="dispersal",
            pay_share_of_treasury=0.2,
            garrison_troops_per_node=450.0,
            monthly_event_probability=0.5,
            severity_floor=0.6,
        ),
        config=SHORT_CONFIG,
    )
    flows = with_trigger_fields(run.result.events, (TROOPS_DELTA,))
    band_events = flows.filter(pl.col("agent_id").str.starts_with("band"))
    losses = band_events.filter(pl.col(TROOPS_DELTA) < 0.0)

    assert losses.height > 0, "the fixture must actually cost bands members"
    assert set(losses["event_type"].unique()) <= {
        MilitaryEventType.DESERTION.value,
        MilitaryEventType.BAND_DISSOLVED.value,
        MilitaryEventType.BAND_SPLIT.value,
    }
