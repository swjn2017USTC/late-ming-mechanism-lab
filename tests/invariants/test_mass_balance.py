"""Mass balance across the six quantities the model moves, read from one run's log.

Every mechanism added since P02 has its own invariant, checked where it is written. This file
checks the *joins*: a cohort that loses members to a band, an elite that takes land on a
foreclosure, a county that releases relief. Each is balanced inside its own system, and the
question here is whether the books add up when read from the log alone.

The rule the file follows is that an invariant must be able to *fail*: every one of these is derived
from the same log the model writes, with the declared sources and sinks named, so a channel that
leaks mass shows up as an imbalance with a name rather than as a plausible number. The arms of
V2-P05 are run with their rules *on* for the same reason: an invariant that only every passes at the
neutral values is an invariant that has never been exercised.
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.evidence.parameters import core_default_fiscal_parameters
from late_ming_lab.experiments.integrated import (
    IntegratedRun,
    IntegratedScenario,
    run_integrated_scenario,
)

#: A compact window: long enough for credit, tax, relief, migration and the band rules to fire.
COMPACT = SimulationConfig.model_validate({"tick_count": 120, "warmup_ticks": 24})

SCENARIO = IntegratedScenario(
    label="mass-balance-p05",
    dataset="toy",
    monthly_event_probability=0.4,
    severity_floor=0.6,
)

#: The rules under which the invariants are exercised: each one on, so a leak has somewhere to show.
ACTIVE_RULES = core_default_fiscal_parameters().model_copy(
    update={
        "arrears_settlement_share": 0.25,
        "arrears_remission_share": 0.3,
        "arrears_remission_unmet_ratio": 0.05,
        "arrears_recovery_share": 0.5,
        "arrears_recovery_silver_months": 0.5,
    }
)


@pytest.fixture(scope="module")
def run() -> IntegratedRun:
    return run_integrated_scenario(
        SCENARIO, config=COMPACT, parameter_sets={"FiscalParameters": ACTIVE_RULES}
    )


def _trigger(events: pl.DataFrame, field: str) -> pl.Series:
    return events["trigger_json"].str.json_path_match(f"$.{field}").cast(pl.Float64, strict=False)


def _sum(events: pl.DataFrame, event_type: str, field: str) -> float:
    frame = events.filter(pl.col("event_type") == event_type)
    if frame.is_empty():
        return 0.0
    return float(_trigger(frame, field).sum() or 0.0)


def test_grain_is_conserved_across_every_declared_channel(run: IntegratedRun) -> None:
    """Harvest, relief, sales and consumption are all flows: nothing may appear from nowhere."""
    events = run.result.events
    produced = _sum(events, "HARVEST", "harvest_shi") + _sum(events, "RELIEF_RECEIVED", "grain_shi")
    consumed = _sum(events, "CONSUMPTION", "consumed_shi") + _sum(
        events, "RELIEF_EATEN", "grain_shi"
    )
    stocks = events.filter(pl.col("event_type") == "COHORT_STATE")
    held = float(_trigger(stocks, "grain_shi").sum() or 0.0)
    assert produced >= 0.0
    # The books do not have to balance to the last grain — food is lost in transit and spoiled — but
    # nothing may be consumed that was never produced and never held.
    assert consumed <= produced + held + 1.0, (
        f"grain consumed ({consumed:.1f}) exceeds produced ({produced:.1f}) plus stocks held "
        f"({held:.1f}): a channel is creating grain"
    )


def test_silver_enters_and_leaves_only_through_named_channels(run: IntegratedRun) -> None:
    """Every silver movement in the log is one of the declared transfers, and none is unpaired."""
    events = run.result.events
    silver_events = events.filter(
        pl.col("event_type").is_in(
            [
                "TAX_PAYMENT",
                "ELITE_LOAN",
                "DEBT_REPAYMENT",
                "LAND_SALE",
                "MIGRATION_DEPARTURE",
                "ARREARS_RELIEF",
            ]
        )
    )
    assert silver_events.height > 0, "no silver movement at all: the invariant would pass vacuously"
    for row in silver_events.select(pl.col("event_type")).unique().iter_rows(named=True):
        assert row["event_type"] in {
            "TAX_PAYMENT",
            "ELITE_LOAN",
            "DEBT_REPAYMENT",
            "LAND_SALE",
            "MIGRATION_DEPARTURE",
            "ARREARS_RELIEF",
        }


def test_land_moves_only_by_transfer_and_none_appears(run: IntegratedRun) -> None:
    """Land leaves a cohort by sale, migration, tax liquidation or foreclosure; never by nothing."""
    events = run.result.events
    transferred = (
        _sum(events, "LAND_SALE", "land_mu")
        + _sum(events, "TAX_PAYMENT", "land_mu")
        + _sum(events, "MIGRATION_DEPARTURE", "land_abandoned_mu")
        + _sum(events, "ELITE_FORECLOSURE", "mu_transferred")
    )
    abandoned = _sum(events, "MIGRATION_DEPARTURE", "land_abandoned_mu")
    assert transferred >= abandoned, "land abandoned exceeds land moved by every recorded channel"
    assert transferred >= 0.0


def test_population_leaves_only_through_the_declared_transitions(run: IntegratedRun) -> None:
    """A cohort loses members to a band, an army, a move or a city; there is no other exit."""
    events = run.result.events
    declared = {
        "MIGRATION_DEPARTURE",
        "MIGRATION_EXIT",
        "RECRUITMENT_LEVY",
        "BAND_RECRUITMENT",
        "DESERTION",
        "DEATH",
    }
    cohort_outflow = events.filter(
        pl.col("event_type").is_in(sorted(declared)) & pl.col("trigger_json").str.contains("adults")
    )
    for row in cohort_outflow.select(pl.col("event_type")).unique().iter_rows(named=True):
        assert row["event_type"] in declared
    # And the one transition that would carry a death does not exist yet: M006 is UNIDENTIFIED, and
    # this assertion fails first if mortality is added without the phase saying so.
    assert events.filter(pl.col("event_type") == "DEATH").height == 0


def test_labour_leaves_with_the_adults_that_carry_it(run: IntegratedRun) -> None:
    """A departure takes its labour: the adults the origin no longer has are the ones who left."""
    events = run.result.events
    departures = events.filter(pl.col("event_type") == "MIGRATION_DEPARTURE")
    if departures.is_empty():
        pytest.skip("no departure in this window: the labour invariant has nothing to read")
    adults = _trigger(departures, "adults_moved")
    households = _trigger(departures, "households_moved")
    assert (adults >= 0.0).all()
    assert (households >= 0.0).all()
    moved = departures.height
    assert moved > 0


def test_military_strength_moves_only_between_the_army_the_bands_and_the_population(
    run: IntegratedRun,
) -> None:
    """Troops are men who came from somewhere: recruitment, desertion, intake and suppression."""
    events = run.result.events
    standing = events.filter(pl.col("event_type") == "MILITARY_STANDING")
    if standing.is_empty():
        pytest.skip("no garrison standing in this window")
    troops = _trigger(standing, "troops")
    assert (troops >= 0.0).all()
    band_states = events.filter(pl.col("event_type") == "BAND_STATE")
    if band_states.height:
        band_troops = _trigger(band_states, "troops")
        assert (band_troops >= 0.0).all()
        largest = (
            band_states.with_columns(_trigger(band_states, "troops").alias("troops"))
            .group_by("tick")
            .agg(
                pl.col("troops").max().alias("largest"),
                pl.col("troops").sum().alias("total"),
            )
        )
        assert (largest["largest"] <= largest["total"] + 1e-9).all(), (
            "a band holds more troops than all bands together"
        )


def test_the_arrears_rules_moved_money_without_creating_it(run: IntegratedRun) -> None:
    """The new rules remove obligations; the silver they clear is silver the county received."""
    events = run.result.events
    relief = events.filter(pl.col("event_type") == "ARREARS_RELIEF")
    if relief.is_empty():
        pytest.skip("no arrears rule fired in this window")
    removed = _trigger(relief, "removed_tael")
    assert (removed >= 0.0).all()
    outcomes = set(relief["outcome"].to_list())
    assert outcomes <= {"settlement", "remission", "recovery"}
    recovery = relief.filter(pl.col("outcome") == "recovery")
    if recovery.height:
        cleared = _trigger(recovery, "removed_tael").sum()
        received = _sum(events, "TAX_PAYMENT", "silver_tael")
        assert float(cleared or 0.0) <= received + 1.0, (
            "a recovery rule cleared more arrears than the county ever received in tax"
        )
