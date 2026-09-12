"""Fiscal invariants: accounting, sources, no double collection, relief conservation.

The four categories the phase requires, each checked against the event log of a real extraction
run rather than against a hand-built example:

```text
fiscal accounting      quota, effort, cost, receipts and arrears reconcile
tax sources            county silver and granary grain enter only from recorded sources
no double collection   one obligation is collected once, by one channel, in one tick
relief conservation    grain released is grain received, and the granary never goes negative
```
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.actors.government import GovernmentLayer
from late_ming_lab.actors.households import CohortEventType
from late_ming_lab.actors.ledger import GRAIN_DELTA, SILVER_DELTA, TAX_ARREARS_DELTA
from late_ming_lab.analysis.distress import with_trigger_fields
from late_ming_lab.analysis.fiscal import county_fiscal_series
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import KernelResult
from late_ming_lab.experiments.assembly import Economy
from late_ming_lab.experiments.extraction import ExtractionScenario, run_extraction_scenario

#: Silver may only enter a county treasury from these receipts; a grant from nowhere is a defect.
COUNTY_SILVER_SOURCES = {
    "TAX_RECEIPT",
}
COUNTY_SILVER_SINKS = {
    "TAX_COLLECTION_COST",
    "OFFICIAL_RELIEF_COST",
    "GOVERNMENT_GRAIN_PURCHASE",
    "MILITARY_PAY_OUTLAY",
}
COUNTY_GRAIN_SOURCES = {
    "GOVERNMENT_GRAIN_PURCHASE",
}
COUNTY_GRAIN_SINKS = {
    "OFFICIAL_RELIEF",
    "GOVERNMENT_GRAIN_ISSUE",
    "GRANARY_GRAIN_SEIZED",
}

#: Channels a household can pay through; one payment per channel per tick is the rule.
PAYMENT_CHANNELS = {"silver", "liquidation", "mediator"}

#: One collection attempt walks at most these steps: mediation, silver, grain, goods, land, loan.
MAX_COLLECTION_STEPS = 6

SHORT_CONFIG = SimulationConfig.model_validate({"tick_count": 72, "warmup_ticks": 12})


def _governments(economy: Economy) -> GovernmentLayer:
    """The fiscal layer must be present in these tests; fail loudly if it is not."""
    if economy.governments is None:
        raise AssertionError("the fiscal invariant fixture must build county governments")
    return economy.governments


@pytest.fixture(scope="module")
def fiscal_run() -> tuple[Economy, KernelResult]:
    scenario = ExtractionScenario(
        label="invariants",
        nominal_pressure=0.32,
        policy="escalating",
        monthly_event_probability=0.5,
        severity_floor=0.6,
    )
    run = run_extraction_scenario(scenario, config=SHORT_CONFIG)
    return run.economy, run.result


def test_fiscal_accounting_reconciles_quota_effort_receipts_and_arrears(
    fiscal_run: tuple[Economy, KernelResult],
) -> None:
    _, result = fiscal_run
    series = county_fiscal_series(result.events)

    assert series.height > 0
    for row in series.iter_rows(named=True):
        assert row["receipts_tael"] >= 0.0
        assert row["collection_cost_tael"] >= 0.0
        assert row["net_receipts_tael"] == pytest.approx(
            row["receipts_tael"] - row["collection_cost_tael"], abs=1e-9
        ), "net receipts must be receipts minus the cost of collecting them"
        assert row["quota_tael"] >= 0.0
        assert row["receipts_tael"] <= row["reachable_tael"] + 1e-6, (
            "a county cannot take more than it pursued"
        )
        assert row["reachable_tael"] <= row["quota_tael"] + 1e-6, (
            "pursuit cannot exceed the assessed quota"
        )
        assert row["arrears_tael"] >= 0.0
        assert 0.0 <= row["collection_effort"] <= 1.0
        assert row["assessment_rate"] >= 0.0


def test_arrears_grow_by_exactly_what_pursuit_failed_to_take(
    fiscal_run: tuple[Economy, KernelResult],
) -> None:
    """Every pursued tael either reaches the treasury or is recorded as arrears."""
    _, result = fiscal_run
    series = county_fiscal_series(result.events)
    checked = series.filter(pl.col("quota_tael") > 0.0)

    assert checked.height > 0
    for row in checked.iter_rows(named=True):
        assert row["receipts_tael"] + row["arrears_delta_tael"] == pytest.approx(
            row["reachable_tael"], rel=1e-9, abs=1e-6
        ), f"{row['region']} tick {row['tick']}: pursued taels must be taken or owed"


def test_county_silver_and_grain_enter_only_from_recorded_sources(
    fiscal_run: tuple[Economy, KernelResult],
) -> None:
    economy, result = fiscal_run
    county_ids = [county.government_id for county in _governments(economy)]
    county_events = with_trigger_fields(
        result.events.filter(pl.col("agent_id").is_in(county_ids)),
        (SILVER_DELTA, GRAIN_DELTA),
    )

    credited = county_events.filter(pl.col(SILVER_DELTA) > 0.0)
    debited = county_events.filter(pl.col(SILVER_DELTA) < 0.0)
    grain_in = county_events.filter(pl.col(GRAIN_DELTA) > 0.0)
    grain_out = county_events.filter(pl.col(GRAIN_DELTA) < 0.0)

    assert set(credited["event_type"].unique()) <= COUNTY_SILVER_SOURCES
    assert set(debited["event_type"].unique()) <= COUNTY_SILVER_SINKS
    assert set(grain_in["event_type"].unique()) <= COUNTY_GRAIN_SOURCES
    assert set(grain_out["event_type"].unique()) <= COUNTY_GRAIN_SINKS


def test_every_receipt_has_a_household_or_elite_payment_behind_it(
    fiscal_run: tuple[Economy, KernelResult],
) -> None:
    """Double entry at the treasury: the county takes exactly what somebody paid."""
    economy, result = fiscal_run
    county_ids = [county.government_id for county in _governments(economy)]
    cohort_ids = [cohort.cohort_id for cohort in economy.population]
    elite_ids = [house.elite_id for house in economy.elites]

    flows = with_trigger_fields(result.events, (SILVER_DELTA,))
    receipts = float(
        flows.filter(
            (pl.col("event_type") == "TAX_RECEIPT") & (pl.col("agent_id").is_in(county_ids))
        )[SILVER_DELTA].sum()
        or 0.0
    )
    paid_directly = float(
        flows.filter(
            (pl.col("event_type") == CohortEventType.TAX_PAYMENT.value)
            & (pl.col("agent_id").is_in(cohort_ids))
        )[SILVER_DELTA].sum()
        or 0.0
    )
    advanced = float(
        flows.filter(
            (pl.col("event_type") == "ELITE_TAX_MEDIATION") & (pl.col("agent_id").is_in(elite_ids))
        )[SILVER_DELTA].sum()
        or 0.0
    )

    assert receipts > 0.0
    assert receipts == pytest.approx(-(paid_directly + advanced), rel=1e-9)


def test_an_elite_advance_becomes_a_claim_on_the_household(
    fiscal_run: tuple[Economy, KernelResult],
) -> None:
    """Mediation moves silver and creates debt in the same breath; the two must match."""
    economy, result = fiscal_run
    cohort_ids = [cohort.cohort_id for cohort in economy.population]
    elite_ids = [house.elite_id for house in economy.elites]
    flows = with_trigger_fields(result.events, (SILVER_DELTA, "debt_delta_tael"))

    advanced_by_elites = float(
        flows.filter(
            (pl.col("event_type") == "ELITE_TAX_MEDIATION") & (pl.col("agent_id").is_in(elite_ids))
        )[SILVER_DELTA].sum()
        or 0.0
    )
    owed_by_households = float(
        flows.filter(
            (pl.col("event_type") == "TAX_MEDIATION") & (pl.col("agent_id").is_in(cohort_ids))
        )["debt_delta_tael"].sum()
        or 0.0
    )
    received_by_households = float(
        flows.filter(
            (pl.col("event_type") == "TAX_MEDIATION") & (pl.col("agent_id").is_in(cohort_ids))
        )[SILVER_DELTA].sum()
        or 0.0
    )

    assert advanced_by_elites < 0.0, "the fixture must actually mediate tax"
    assert received_by_households == pytest.approx(-advanced_by_elites, rel=1e-9)
    assert owed_by_households == pytest.approx(-advanced_by_elites, rel=1e-9)


def test_an_obligation_is_collected_once_through_a_bounded_number_of_steps(
    fiscal_run: tuple[Economy, KernelResult],
) -> None:
    """One obligation, one collection attempt: bounded steps, all channels known.

    A household may pay in several instalments in one month — silver first, then whatever selling
    grain, goods and land raised, then a loan — so the guard is the number of declared steps, not
    the number of events. A loop that collected one obligation repeatedly would break it.
    """
    economy, result = fiscal_run
    cohort_ids = [cohort.cohort_id for cohort in economy.population]
    payments = result.events.filter(
        (pl.col("event_type") == CohortEventType.TAX_PAYMENT.value)
        & (pl.col("agent_id").is_in(cohort_ids))
    ).with_columns(pl.col("outcome").str.split(":").list.last().alias("channel"))

    assert payments.height > 0
    assert set(payments["channel"].unique()) <= PAYMENT_CHANNELS

    steps = payments.group_by(["agent_id", "tick"]).len()
    assert steps.height > 0
    worst = float(steps.select(pl.col("len").max()).item() or 0)
    assert worst <= MAX_COLLECTION_STEPS, (
        "a household was collected more times in one tick than there are collection steps"
    )


def test_no_household_pays_more_than_its_share_of_what_was_pursued(
    fiscal_run: tuple[Economy, KernelResult],
) -> None:
    economy, result = fiscal_run
    cohort_ids = {cohort.cohort_id for cohort in economy.population}
    county_by_node = {county.node_id: county.government_id for county in _governments(economy)}
    series = county_fiscal_series(result.events).select(
        ["tick", "region", "reachable_tael", "taxable_land_mu"]
    )

    # A tick's snapshot is written after that tick's collections, so the land held *during*
    # collection is the previous tick's snapshot.
    land = (
        with_trigger_fields(
            result.events.filter(pl.col("event_type") == "COHORT_STATE"),
            ("land_mu",),
        )
        .filter(pl.col("agent_id").is_in(sorted(cohort_ids)))
        .select(["tick", "agent_id", "region", "land_mu"])
        .with_columns((pl.col("tick") + 1).alias("tick"))
    )
    paid = with_trigger_fields(
        result.events.filter(
            (pl.col("event_type") == CohortEventType.TAX_PAYMENT.value)
            & (pl.col("agent_id").is_in(sorted(cohort_ids)))
        ),
        (SILVER_DELTA,),
    )
    paid_by_tick = paid.group_by(["tick", "agent_id"]).agg(
        (-pl.col(SILVER_DELTA)).sum().alias("paid_tael")
    )
    joined = (
        paid_by_tick.join(land, on=["tick", "agent_id"], how="left")
        .join(
            series.rename({"region": "node_id"}),
            left_on=["tick", "region"],
            right_on=["tick", "node_id"],
            how="left",
        )
        .with_columns(
            (
                pl.col("reachable_tael") * (pl.col("land_mu") / pl.col("taxable_land_mu")) + 1e-6
            ).alias("share_ceiling")
        )
    )

    overpaid = joined.filter(pl.col("paid_tael") > pl.col("share_ceiling"))
    assert overpaid.height == 0, overpaid.head(3)
    assert county_by_node, "the fixture must have counties"


def test_relief_grain_released_is_grain_received(
    fiscal_run: tuple[Economy, KernelResult],
) -> None:
    economy, result = fiscal_run
    county_ids = [county.government_id for county in _governments(economy)]
    cohort_ids = [cohort.cohort_id for cohort in economy.population]
    courier = with_trigger_fields(result.events, (GRAIN_DELTA,))

    released = float(
        courier.filter(
            (pl.col("event_type") == "OFFICIAL_RELIEF") & (pl.col("agent_id").is_in(county_ids))
        )[GRAIN_DELTA].sum()
        or 0.0
    )
    received = float(
        courier.filter(
            (pl.col("event_type") == CohortEventType.RELIEF_RECEIVED.value)
            & (pl.col("agent_id").is_in(cohort_ids))
            & (pl.col("outcome").str.ends_with(":official"))
        )[GRAIN_DELTA].sum()
        or 0.0
    )

    assert released < 0.0, "the fixture must actually release relief"
    assert received == pytest.approx(-released, rel=1e-9)


def test_the_county_granary_never_goes_negative_and_reconciles(
    fiscal_run: tuple[Economy, KernelResult],
) -> None:
    economy, result = fiscal_run
    governments = _governments(economy)
    county_ids = [county.government_id for county in governments]
    courier = with_trigger_fields(result.events, (GRAIN_DELTA,))
    county_grain = courier.filter(pl.col("agent_id").is_in(county_ids))

    for county in governments:
        deltas = county_grain.filter(pl.col("agent_id") == county.government_id)[GRAIN_DELTA]
        running = county.initial_balances["grain_shi"]
        for delta in deltas.to_list():
            running += float(delta or 0.0)
            assert running >= -1e-9, f"{county.node_id} granary went negative"
        assert abs(running - county.grain_shi) < 1e-6

    governments.check_invariants()
    economy.population.check_invariants()
    economy.elites.check_invariants()


def test_household_arrears_match_the_county_stock(
    fiscal_run: tuple[Economy, KernelResult],
) -> None:
    economy, result = fiscal_run
    cohort_ids = [cohort.cohort_id for cohort in economy.population]
    governments = _governments(economy)
    county_ids = [county.government_id for county in governments]

    household = (
        with_trigger_fields(
            result.events.filter(
                (pl.col("event_type") == "TAX_ARREARS_ASSESSED")
                & (pl.col("agent_id").is_in(cohort_ids))
            ),
            (TAX_ARREARS_DELTA,),
        )
        .group_by("region")
        .agg(pl.col(TAX_ARREARS_DELTA).sum().alias("household_arrears_tael"))
    )
    county = (
        with_trigger_fields(
            result.events.filter(
                (pl.col("event_type") == "TAX_ARREARS") & (pl.col("agent_id").is_in(county_ids))
            ),
            ("arrears_delta_tael",),
        )
        .group_by("region")
        .agg(pl.col("arrears_delta_tael").sum().alias("county_arrears_tael"))
    )
    joined = household.join(county, on="region", how="inner")

    assert joined.height == len(county_ids)
    for row in joined.iter_rows(named=True):
        assert row["household_arrears_tael"] == pytest.approx(
            row["county_arrears_tael"], rel=1e-9, abs=1e-6
        ), f"{row['region']}: the county's arrears stock is not what its households owe"


def test_no_capacity_ever_collapses_into_one_number() -> None:
    """A scalar 'state capacity' does not exist anywhere in the fiscal layer."""
    from late_ming_lab.actors.fixtures import toy_capacity

    capacity = toy_capacity(
        tax_collection=0.9, information=0.1, relief=0.2, coercion=0.3, logistics=0.4
    )

    assert capacity.tax_collection != capacity.information
    assert capacity.as_mapping()["tax_collection"] == 0.9
    for aggregate in ("total", "mean", "index", "state_capacity"):
        assert not hasattr(capacity, aggregate)
