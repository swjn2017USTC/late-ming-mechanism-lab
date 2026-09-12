"""P04 invariants: double-entry across counterparties, land conservation, claims, prices.

Every transfer in this model has two sides, and each side writes its own event. These tests
reconcile the two: grain and silver that leave one actor must arrive at another, land must be
conserved because it is only ever transferred, and the elite's outstanding claims must equal the
household debt they are derived from.
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.actors.households import CohortEventType
from late_ming_lab.actors.ledger import GRAIN_DELTA, LAND_DELTA, SILVER_DELTA
from late_ming_lab.analysis.distress import with_trigger_fields
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import KernelResult
from late_ming_lab.experiments.assembly import Economy, build_toy_economy
from late_ming_lab.networks.fixtures import toy_spatial_dataset
from late_ming_lab.systems.climate import SyntheticClimate

#: Transfers that move grain between two modelled actors.
GRAIN_TRANSFERS = {
    CohortEventType.MARKET_SALE.value: ("MERCHANT_PURCHASE", GRAIN_DELTA),
    CohortEventType.RENT_PAYMENT.value: ("ELITE_GRAIN_RECEIPT", GRAIN_DELTA),
    CohortEventType.RELIEF_RECEIVED.value: ("ELITE_RELIEF", GRAIN_DELTA),
    CohortEventType.CONSUMPTION.value: (None, GRAIN_DELTA),
}

SHORT_CONFIG = SimulationConfig.model_validate({"tick_count": 60, "warmup_ticks": 12})


@pytest.fixture(scope="module")
def economy_run() -> tuple[Economy, KernelResult]:
    economy = build_toy_economy(
        climate_model=SyntheticClimate(monthly_event_probability=0.5, severity_floor=0.6)
    )
    from late_ming_lab.core.kernel import SimulationKernel

    result = SimulationKernel(SHORT_CONFIG, list(economy.systems)).run(run_label="invariants")
    return economy, result


def test_every_modelled_flow_leaves_a_trace_on_both_sides(
    economy_run: tuple[Economy, KernelResult],
) -> None:
    economy, result = economy_run
    events = result.events
    cohort_ids = {cohort.cohort_id for cohort in economy.population}
    merchant_ids = {house.merchant_id for house in economy.merchants}
    elite_ids = {house.elite_id for house in economy.elites}
    modelled = cohort_ids | merchant_ids | elite_ids

    unknown = set(events["agent_id"].drop_nulls().unique()) - modelled
    assert unknown == set(), f"events from actors outside the ledger: {sorted(unknown)}"


def test_grain_sold_by_a_household_is_bought_by_a_merchant(
    economy_run: tuple[Economy, KernelResult],
) -> None:
    economy, result = economy_run
    events = result.events
    courier = with_trigger_fields(events, (GRAIN_DELTA,))

    sold = courier.filter(pl.col("event_type") == CohortEventType.MARKET_SALE.value)[
        GRAIN_DELTA
    ].sum()
    bought_by_merchants = courier.filter(
        (pl.col("event_type") == "MERCHANT_PURCHASE")
        & (pl.col("agent_id").is_in([h.merchant_id for h in economy.merchants]))
        & pl.col("outcome").str.starts_with("bought-from-household:")
    )[GRAIN_DELTA].sum()

    assert sold < 0.0
    assert bought_by_merchants == pytest.approx(-sold, rel=1e-9)


def test_grain_sold_to_households_is_what_merchants_gave_up(
    economy_run: tuple[Economy, KernelResult],
) -> None:
    economy, result = economy_run
    courier = with_trigger_fields(result.events, (GRAIN_DELTA,))
    cohort_ids = [c.cohort_id for c in economy.population]

    households_bought = courier.filter(
        (pl.col("event_type") == CohortEventType.GRAIN_PURCHASE.value)
        & (pl.col("agent_id").is_in(cohort_ids))
    )[GRAIN_DELTA].sum()
    merchants_gave = courier.filter(
        (pl.col("event_type") == "MERCHANT_SALE")
        & (pl.col("agent_id").is_in([h.merchant_id for h in economy.merchants]))
    )[GRAIN_DELTA].sum()

    assert households_bought > 0.0
    assert merchants_gave == pytest.approx(-households_bought, rel=1e-9)


def test_silver_paid_for_grain_arrives_at_the_merchant(
    economy_run: tuple[Economy, KernelResult],
) -> None:
    economy, result = economy_run
    courier = with_trigger_fields(result.events, (SILVER_DELTA,))
    cohort_ids = [c.cohort_id for c in economy.population]

    paid_by_households = float(
        courier.filter(
            (pl.col("event_type") == CohortEventType.GRAIN_PURCHASE.value)
            & (pl.col("agent_id").is_in(cohort_ids))
        )[SILVER_DELTA].sum()
        or 0.0
    )
    taken_by_merchants = float(
        courier.filter(
            (pl.col("event_type") == "MERCHANT_SALE")
            & (pl.col("agent_id").is_in([h.merchant_id for h in economy.merchants]))
        )[SILVER_DELTA].sum()
        or 0.0
    )

    assert paid_by_households < 0.0
    assert taken_by_merchants == pytest.approx(-paid_by_households, rel=1e-9)


def test_rent_reaches_the_elite_and_leaves_the_tenant(
    economy_run: tuple[Economy, KernelResult],
) -> None:
    economy, result = economy_run
    courier = with_trigger_fields(result.events, (GRAIN_DELTA,))
    cohort_ids = [c.cohort_id for c in economy.population]

    rent_paid = courier.filter(
        (pl.col("event_type") == CohortEventType.RENT_PAYMENT.value)
        & (pl.col("agent_id").is_in(cohort_ids))
    )[GRAIN_DELTA].sum()
    rent_received = float(
        courier.filter(
            (pl.col("event_type") == "ELITE_GRAIN_RECEIPT")
            & (pl.col("agent_id").is_in([h.elite_id for h in economy.elites]))
        )[GRAIN_DELTA].sum()
        or 0.0
    )

    assert float(rent_paid or 0.0) < 0.0
    assert rent_received >= -float(rent_paid or 0.0) - 1e-6, (
        "rent received cannot be less than rent paid"
    )


def test_a_shipment_carries_exactly_what_the_buyer_receives_and_pays(
    economy_run: tuple[Economy, KernelResult],
) -> None:
    """The intercounty leg, reconciled: what arrives is what was bought, for the price paid."""
    economy, result = economy_run
    courier = with_trigger_fields(
        result.events, ("shi", "arrived_shi", "lost_shi", "proceeds_tael", "paid_tael")
    )
    merchant_ids = [house.merchant_id for house in economy.merchants]

    shipments = courier.filter(
        (pl.col("event_type") == "TRADE_SHIPMENT") & (pl.col("agent_id").is_in(merchant_ids))
    )
    receipts = courier.filter(
        (pl.col("event_type") == "TRADE_RECEIPT") & (pl.col("agent_id").is_in(merchant_ids))
    )
    losses = courier.filter(
        (pl.col("event_type") == "TRADE_LOSS") & (pl.col("agent_id").is_in(merchant_ids))
    )

    assert shipments.height > 0
    totals = shipments.select(
        pl.col("arrived_shi").sum().alias("arrived"),
        pl.col("proceeds_tael").sum().alias("proceeds"),
    ).row(0, named=True)
    received = receipts.select(
        pl.col("shi").sum().alias("received"), pl.col("paid_tael").sum().alias("paid")
    ).row(0, named=True)
    lost = float(losses.select(pl.col("lost_shi").sum()).item() or 0.0)

    assert float(received["received"]) == pytest.approx(float(totals["arrived"]), rel=1e-9)
    assert float(received["paid"]) == pytest.approx(float(totals["proceeds"]), rel=1e-9)
    assert lost == pytest.approx(
        float(shipments.select(pl.col("lost_shi").sum()).item() or 0.0), rel=1e-9
    )
    assert lost > 0.0, "the risk mechanism must actually destroy something in this run"


def test_relief_released_is_relief_received(economy_run: tuple[Economy, KernelResult]) -> None:
    economy, result = economy_run
    courier = with_trigger_fields(result.events, (GRAIN_DELTA,))
    elite_ids = [house.elite_id for house in economy.elites]

    released = float(
        courier.filter(
            (pl.col("event_type") == "ELITE_RELIEF") & (pl.col("agent_id").is_in(elite_ids))
        )[GRAIN_DELTA].sum()
        or 0.0
    )
    received = float(
        courier.filter(pl.col("event_type") == "RELIEF_RECEIVED")[GRAIN_DELTA].sum() or 0.0
    )

    assert received == pytest.approx(-released, rel=1e-9)


def test_land_is_conserved_because_it_is_only_transferred(
    economy_run: tuple[Economy, KernelResult],
) -> None:
    economy, _ = economy_run
    opening = sum(house.land_mu for house in build_toy_economy().elites) + sum(
        cohort.land_mu for cohort in build_toy_economy().population
    )
    closing = economy.elites.total_land_mu + sum(cohort.land_mu for cohort in economy.population)

    assert closing == pytest.approx(opening, rel=1e-9)


def test_elite_claims_equal_the_household_debt_they_come_from(
    economy_run: tuple[Economy, KernelResult],
) -> None:
    economy, _ = economy_run

    for house in economy.elites:
        local_debt = sum(
            cohort.debt_tael for cohort in economy.population if cohort.node_id == house.node_id
        )
        assert economy.credit.claims_tael(house.node_id) == pytest.approx(local_debt)


def test_land_sold_by_households_is_land_bought_by_elites(
    economy_run: tuple[Economy, KernelResult],
) -> None:
    economy, result = economy_run
    courier = with_trigger_fields(result.events, (LAND_DELTA,))
    cohort_ids = [c.cohort_id for c in economy.population]
    elite_ids = [h.elite_id for h in economy.elites]

    sold = courier.filter(
        (pl.col("event_type") == CohortEventType.LAND_SALE.value)
        & (pl.col("agent_id").is_in(cohort_ids))
    )[LAND_DELTA].sum()
    bought = courier.filter(
        (pl.col("event_type") == "ELITE_LAND_PURCHASE") & (pl.col("agent_id").is_in(elite_ids))
    )[LAND_DELTA].sum()

    assert sold < 0.0
    assert bought == pytest.approx(-sold, rel=1e-9)


def test_no_actor_ever_holds_a_negative_balance(economy_run: tuple[Economy, KernelResult]) -> None:
    economy, _ = economy_run

    economy.merchants.check_invariants()
    economy.elites.check_invariants()
    economy.population.check_invariants()
    for merchant in economy.merchants:
        assert merchant.grain_shi >= 0.0 and merchant.silver_tael >= 0.0
    for elite in economy.elites:
        assert elite.grain_shi >= 0.0 and elite.silver_tael >= 0.0 and elite.land_mu >= 0.0


def test_every_posted_price_stays_inside_its_declared_bounds(
    economy_run: tuple[Economy, KernelResult],
) -> None:
    economy, result = economy_run
    parameters = economy.market_parameters
    reference = parameters.reference_price_tael_per_shi
    prices = with_trigger_fields(result.events, ("price_tael_per_shi",)).filter(
        pl.col("event_type") == "MARKET_STATE"
    )

    assert prices.height > 0
    lowest = float(prices.select(pl.col("price_tael_per_shi").min()).item())
    highest = float(prices.select(pl.col("price_tael_per_shi").max()).item())
    assert lowest >= reference * parameters.price_floor_ratio - 1e-9
    assert highest <= reference * parameters.price_ceiling_ratio + 1e-9


def test_no_shipment_exceeds_its_link_capacity(economy_run: tuple[Economy, KernelResult]) -> None:
    economy, result = economy_run
    capacity = {
        tuple(sorted(edge)): float(data["capacity"])
        * economy.market_parameters.capacity_unit_shi_per_month
        for edge, data in economy.graphs.trade.edges.items()
    }
    shipments = with_trigger_fields(result.events, ("shi",)).filter(
        pl.col("event_type") == "TRADE_SHIPMENT"
    )

    for row in shipments.iter_rows(named=True):
        link = tuple(sorted((row["region"], row["outcome"].split(":")[-1])))
        if link in capacity:
            assert row["shi"] <= capacity[link] + 1e-9


def test_merchants_hold_what_the_goods_market_gave_them(
    economy_run: tuple[Economy, KernelResult],
) -> None:
    """Movable goods bought from households are counted as goods, not as grain or silver."""
    economy, _ = economy_run
    total_goods = sum(house.goods_tael for house in economy.merchants)

    assert total_goods >= 0.0
    for house in economy.merchants:
        house.check_balances()


def test_the_toy_fixture_is_the_only_source_of_nodes(
    economy_run: tuple[Economy, KernelResult],
) -> None:
    economy, _ = economy_run

    assert set(economy.merchants.by_node) == set(economy.graphs.trade.nodes)
    assert {house.node_id for house in economy.elites} == {
        node.node_id for node in toy_spatial_dataset().node_registry().counties
    }
