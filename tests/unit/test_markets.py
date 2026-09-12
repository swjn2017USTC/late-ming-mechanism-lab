"""Market system: price formation, clearing, local access, trade and the disruption hook."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from late_ming_lab.actors.fixtures import toy_cohort_population
from late_ming_lab.actors.merchants import MerchantHouse, MerchantLayer
from late_ming_lab.core.tick import TickContext
from late_ming_lab.evidence.parameters import (
    core_default_household_parameters,
    core_default_market_parameters,
)
from late_ming_lab.experiments.assembly import Economy, build_toy_economy
from late_ming_lab.networks.disruption import CalmTrade, ScaledDisruption
from late_ming_lab.systems.markets import LocalGrainMarket, MarketBook, MarketPrice

PARAMETERS = core_default_market_parameters()


def _economy(**parameter_overrides: object) -> Economy:
    parameters = PARAMETERS.model_validate({**PARAMETERS.model_dump(), **parameter_overrides})
    return build_toy_economy(market_parameters=parameters)


def test_prices_rise_as_inventory_falls_and_are_bounded() -> None:
    system = _economy().market
    reference = PARAMETERS.reference_price_tael_per_shi
    need = 1_000.0
    target = need * PARAMETERS.target_cover_months

    at_target = system.price_from_inventory(inventory_shi=target, local_need_shi=need)
    scarce = system.price_from_inventory(inventory_shi=target / 4.0, local_need_shi=need)
    glutted = system.price_from_inventory(inventory_shi=target * 20.0, local_need_shi=need)

    assert at_target == pytest.approx(reference)
    assert scarce > at_target > glutted
    assert glutted == pytest.approx(reference * PARAMETERS.price_floor_ratio)
    assert system.price_from_inventory(inventory_shi=1e-9, local_need_shi=need) == pytest.approx(
        reference * PARAMETERS.price_ceiling_ratio
    )


def test_a_node_without_modelled_demand_posts_the_reference_price() -> None:
    system = _economy().market

    assert system.price_from_inventory(inventory_shi=0.0, local_need_shi=0.0) == pytest.approx(
        PARAMETERS.reference_price_tael_per_shi
    )


def _with_price_gap(
    economy: Economy, origin: str = "toy-sx-c", destination: str = "toy-hn-a"
) -> Economy:
    """Post a wide price gap between two nodes so arbitrage has something to do."""
    economy.market.book.post(
        MarketPrice(
            node_id=origin,
            price_tael_per_shi=0.7,
            inventory_shi=economy.merchants.require(origin).grain_shi,
            local_need_shi=3_000.0,
        )
    )
    economy.market.book.post(
        MarketPrice(
            node_id=destination,
            price_tael_per_shi=3.0,
            inventory_shi=economy.merchants.require(destination).grain_shi,
            local_need_shi=3_000.0,
        )
    )
    return economy


def _shipped_on(economy: Economy, origin: str, destination: str) -> float:
    return sum(
        flow.shipped_shi
        for flow in economy.market.last_flows
        if flow.origin == origin and flow.destination == destination
    )


def test_a_price_gap_moves_grain_along_the_link(tick_context: TickContext) -> None:
    economy = _with_price_gap(_economy())

    economy.market.step(tick_context)

    assert _shipped_on(economy, "toy-sx-c", "toy-hn-a") > 0.0


def test_more_transport_cost_moves_less_grain_and_autarky_moves_none(
    tick_context: TickContext,
) -> None:
    """Question B at unit scale, with everything except the link held equal."""
    cheap = _with_price_gap(_economy())
    dear = _with_price_gap(_economy(transport_cost_tael_per_cost_unit_per_shi=4.0))
    autarkic = _with_price_gap(_economy(capacity_unit_shi_per_month=0.0))

    for economy in (cheap, dear, autarkic):
        economy.market.step(tick_context)

    shipped_cheap = _shipped_on(cheap, "toy-sx-c", "toy-hn-a")
    shipped_dear = _shipped_on(dear, "toy-sx-c", "toy-hn-a")

    assert shipped_cheap > 0.0
    assert shipped_dear < shipped_cheap
    assert _shipped_on(autarkic, "toy-sx-c", "toy-hn-a") == 0.0
    assert autarkic.market.last_flows == ()


def test_the_book_holds_one_posted_price_per_node() -> None:
    book = MarketBook({"toy-sx-a": 0.6, "toy-hn-a": 0.6})

    assert book.nodes == ("toy-hn-a", "toy-sx-a")
    assert book.price("toy-sx-a") == 0.6

    book.post(
        MarketPrice(
            node_id="toy-sx-a",
            price_tael_per_shi=1.2,
            inventory_shi=10.0,
            local_need_shi=100.0,
        )
    )

    assert book.price("toy-sx-a") == 1.2
    assert book.state("toy-sx-a").inventory_shi == 10.0
    with pytest.raises(KeyError):
        book.price("toy-nowhere")
    with pytest.raises(KeyError, match="no posted price"):
        book.post(
            MarketPrice(
                node_id="toy-nowhere",
                price_tael_per_shi=1.0,
                inventory_shi=0.0,
                local_need_shi=0.0,
            )
        )
    with pytest.raises(ValueError, match="at least one price"):
        MarketBook({})


def test_the_local_market_is_bound_to_one_node(tick_context: TickContext) -> None:
    economy = _economy()
    population = toy_cohort_population(economy.graphs.nodes)
    market = LocalGrainMarket(
        node_id="toy-sx-a", book=economy.market.book, merchants=economy.merchants
    )
    local = next(cohort for cohort in population if cohort.node_id == "toy-sx-a")
    elsewhere = next(cohort for cohort in population if cohort.node_id == "toy-hn-a")

    assert market.price_tael_per_shi == economy.market.book.price("toy-sx-a")
    outcome = market.buy_grain(tick_context, local, shi_wanted=10.0, max_silver=100.0)
    assert outcome.quantity > 0.0
    assert outcome.counterparty_id == "merchant::toy-sx-a"

    with pytest.raises(ValueError, match="serves its own node"):
        market.buy_grain(tick_context, elsewhere, shi_wanted=1.0, max_silver=100.0)


def test_an_empty_market_sells_nothing(tick_context: TickContext) -> None:
    economy = _economy()
    population = toy_cohort_population(economy.graphs.nodes)
    cohort = next(c for c in population if c.node_id == "toy-sx-a")
    empty = MerchantLayer((MerchantHouse(node_id="toy-sx-a", silver_tael=0.0, grain_shi=0.0),))
    market = LocalGrainMarket(node_id="toy-sx-a", book=economy.market.book, merchants=empty)

    outcome = market.buy_grain(tick_context, cohort, shi_wanted=10.0, max_silver=100.0)

    assert (outcome.quantity, outcome.value_tael) == (0.0, 0.0)


def test_a_market_without_silver_buys_no_goods(tick_context: TickContext) -> None:
    economy = _economy()
    population = toy_cohort_population(economy.graphs.nodes)
    cohort = next(c for c in population if c.node_id == "toy-sx-a")
    broke = MerchantLayer((MerchantHouse(node_id="toy-sx-a", silver_tael=0.0, grain_shi=100.0),))
    market = LocalGrainMarket(node_id="toy-sx-a", book=economy.market.book, merchants=broke)

    outcome = market.buy_movables(
        tick_context, cohort, wanted_tael=5.0, max_tael=cohort.movable_assets_tael
    )

    assert outcome.quantity == 0.0


def test_disruption_regimes_scale_risk_and_capacity() -> None:
    calm = CalmTrade()
    cut = ScaledDisruption(
        name="cut",
        risk_scale=2.0,
        capacity_scale=0.5,
        blocked_links=(("toy-hn-a", "toy-sx-a"),),
    )

    assert calm.risk_multiplier("a", "b") == 1.0
    assert calm.capacity_multiplier("a", "b") == 1.0
    assert cut.risk_multiplier("toy-sx-a", "toy-hn-a") == 2.0
    assert cut.capacity_multiplier("toy-sx-a", "toy-hn-a") == 0.0
    assert cut.capacity_multiplier("toy-sx-a", "toy-ext-shanxi") == 0.5
    assert cut.is_blocked("toy-hn-a", "toy-sx-a")

    with pytest.raises(ValidationError, match="cannot connect"):
        ScaledDisruption(
            name="bad", risk_scale=1.0, capacity_scale=1.0, blocked_links=(("a", "a"),)
        )
    with pytest.raises(ValidationError):
        ScaledDisruption(name="bad", risk_scale=0.5, capacity_scale=1.0)


def test_the_system_installs_a_disruption_regime() -> None:
    system = _economy().market
    assert isinstance(system.disruption, CalmTrade)

    cut = ScaledDisruption(name="cut", risk_scale=1.5, capacity_scale=0.25)
    system.set_disruption(cut)

    assert isinstance(system.disruption, ScaledDisruption)
    assert system.disruption.capacity_multiplier("toy-sx-a", "toy-hn-a") == 0.25


def test_household_parameters_no_longer_carry_prices_or_credit_terms() -> None:
    """The P03 placeholders are gone; prices and credit belong to the market and the elite."""
    household = core_default_household_parameters()

    for retired in (
        "distress_grain_price_tael_per_shi",
        "grain_reference_price_tael_per_shi",
        "land_distress_price_tael_per_mu",
        "loan_to_value",
        "interest_rate_monthly",
    ):
        assert retired not in type(household).model_fields
    assert "surplus_keep_ratio_of_annual_need" in type(household).model_fields


def test_merchant_coverage_follows_the_trade_graph() -> None:
    economy = _economy()

    assert set(economy.merchants.by_node) == set(economy.graphs.trade.nodes)
    assert set(economy.merchants.by_node) >= {
        node.node_id for node in economy.graphs.nodes.counties
    }
