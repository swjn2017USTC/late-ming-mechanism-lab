"""The four P04 mechanism questions, asked on the toy economy.

Each test isolates one rule change and asserts a *measured difference*, not a verdict:

| Question | Rule changed | Assertion |
| --- | --- | --- |
| A | tradability, 0x to 10x | what larger tradable capacity does to price dispersion |
| B | transport cost | costlier links carry less grain, and prohibitive ones carry none |
| C | lending on vs off | credit changes when cohorts first fall below their floor |
| D | lending on vs off, and the rate | what credit does to elite land share and land inequality |

The shock is a scenario parameter throughout. Nothing here says anything about 1625-1644.
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.experiments.market_credit import (
    MarketRun,
    MarketScenario,
    run_market_scenario,
)

SHORT_CONFIG = SimulationConfig.model_validate({"tick_count": 96, "warmup_ticks": 24})
#: Prices only separate enough for arbitrage once the forcing is severe; the moderate level is
#: enough to move prices but not enough to open a profitable margin on these links.
SEVERE = dict(monthly_event_probability=0.5, severity_floor=0.6)


def _run(label: str, **changes: object) -> MarketRun:
    scenario = MarketScenario(label=label, **{**SEVERE, **changes})  # type: ignore[arg-type]
    return run_market_scenario(scenario, config=SHORT_CONFIG)


def test_a_autarky_trades_nothing_and_open_links_trade() -> None:
    from late_ming_lab.analysis.concentration import trade_summary

    autarkic = _run("autarkic", capacity_unit_shi_per_month=0.0)
    integrated = _run("integrated")

    autarkic_trade = trade_summary(autarkic.result.events)
    integrated_trade = trade_summary(integrated.result.events)

    # Autarky produces no shipment events at all; the summary is then empty rather than zeroed.
    assert autarkic_trade.height == 0
    assert float(autarkic_trade["shipped_shi"].sum()) == 0.0
    assert integrated_trade.height > 0
    assert float(integrated_trade["shipped_shi"].sum()) > 0.0
    assert not autarkic.result.events.equals(integrated.result.events)


def test_a_integration_does_not_equalise_prices_in_this_configuration() -> None:
    """Question A, answered as measured — and the answer here is negative.

    Opening the links moves grain towards the dear nodes, which drains the cheap ones; with the
    toy merchant endowments a single export is a large share of the source's stock, so dispersion
    rises rather than falls. The report states this as a property of this price rule, this
    topology and these stocks, not as a claim about markets.
    """
    from late_ming_lab.analysis.concentration import dispersion_summary, price_dispersion

    county_nodes = tuple(node.node_id for node in _run("probe").economy.graphs.nodes.counties)
    autarkic = _run("tradability-0x", capacity_unit_shi_per_month=0.0)
    integrated = _run("tradability-1x", capacity_unit_shi_per_month=1.0)
    glutted = _run("stock-100x", merchant_stock_scale=100.0)

    autarkic_dispersion = dispersion_summary(
        price_dispersion(autarkic.result.events, county_nodes=county_nodes)
    )
    integrated_dispersion = dispersion_summary(
        price_dispersion(integrated.result.events, county_nodes=county_nodes)
    )
    glutted_dispersion = dispersion_summary(
        price_dispersion(glutted.result.events, county_nodes=county_nodes)
    )

    assert autarkic_dispersion["mean_max_min_ratio"] > 1.0
    assert integrated_dispersion["mean_max_min_ratio"] > 1.0
    assert (
        integrated_dispersion["mean_max_min_ratio"] > autarkic_dispersion["mean_max_min_ratio"]
    ), "this is the measured P04 answer; if trade ever equalises prices, this test must change"
    # Enough stock everywhere pins every node to the price floor, which is equality by glut
    # rather than by arbitrage; there is nothing left to arbitrage.
    assert glutted_dispersion["mean_max_min_ratio"] == 1.0


def test_b_higher_transport_cost_reduces_trade_flow() -> None:
    from late_ming_lab.analysis.concentration import trade_summary

    cheap = _run("cheap", transport_cost_multiplier=0.5)
    dear = _run("dear", transport_cost_multiplier=2.0)
    prohibitive = _run("prohibitive", transport_cost_multiplier=20.0)

    shipped_cheap = float(trade_summary(cheap.result.events)["shipped_shi"].sum())
    shipped_dear = float(trade_summary(dear.result.events)["shipped_shi"].sum())
    shipped_prohibitive = float(trade_summary(prohibitive.result.events)["shipped_shi"].sum())

    assert shipped_cheap > 0.0
    assert shipped_cheap > shipped_dear
    assert shipped_prohibitive == 0.0


def test_c_credit_changes_when_cohorts_first_fall_below_their_floor() -> None:
    from late_ming_lab.analysis.concentration import first_distress_ticks

    with_credit = _run("credit-on")
    without_credit = _run("credit-off", credit_enabled=False)

    first_with = first_distress_ticks(with_credit.result.events)
    first_without = first_distress_ticks(without_credit.result.events)

    assert first_with.height > 0 and first_without.height > 0
    # Credit delays the first subsistence failure and reduces forced land sales. Both are
    # measured rather than asserted as a general law about credit.
    mean_with = float(first_with.select(pl.col("first_below_floor_tick").mean()).item() or 0.0)
    mean_without = float(
        first_without.select(pl.col("first_below_floor_tick").mean()).item() or 0.0
    )
    assert mean_with >= mean_without
    assert with_credit.economy.elites.total_land_mu < without_credit.economy.elites.total_land_mu


def test_d_credit_and_land_concentration_are_measured_together() -> None:
    from late_ming_lab.analysis.concentration import land_concentration

    off = _run("credit-off", credit_enabled=False)
    low_rate = _run("credit-low", interest_rate_monthly=0.005)
    high_rate = _run("credit-high", interest_rate_monthly=0.02)

    no_credit = land_concentration(off.economy.population, off.economy.elites)
    cheap_credit = land_concentration(low_rate.economy.population, low_rate.economy.elites)
    dear_credit = land_concentration(high_rate.economy.population, high_rate.economy.elites)

    for measured in (no_credit, cheap_credit, dear_credit):
        assert 0.0 < measured["elite_land_share"] < 1.0
        assert 0.0 <= measured["cohort_land_gini"] <= 1.0

    # The direction is measured, not assumed: here credit substitutes for distress sales, so
    # concentration is lower with credit than without it, and a dearer rate adds some back.
    assert cheap_credit["elite_land_share"] < no_credit["elite_land_share"]
    assert dear_credit["cohort_land_gini"] >= cheap_credit["cohort_land_gini"] - 1e-9


def test_elite_relief_reaches_distressed_cohorts() -> None:
    without = _run("no-relief", relief_enabled=False)
    with_relief = _run("relief")

    events = with_relief.result.events
    released = events.filter(events["event_type"] == "ELITE_RELIEF")
    received = events.filter(events["event_type"] == "RELIEF_RECEIVED")

    assert released.height > 0
    assert received.height == released.height
    assert with_relief.economy.elites.total_grain_shi < without.economy.elites.total_grain_shi


def test_tax_mediation_moves_silver_only_when_a_demand_exists() -> None:
    """The P05 hook: with no demand nothing is advanced; with one, both sides record it.

    The elite advances silver, the cohort receives it and owes it: the two events must balance,
    and the cohort's new debt must equal what the elite paid out.
    """
    from late_ming_lab.actors.elites import AdvanceBasedTaxMediation
    from late_ming_lab.actors.ledger import SILVER_DELTA
    from late_ming_lab.analysis.distress import with_trigger_fields
    from late_ming_lab.core.kernel import KernelResult, SimulationKernel
    from late_ming_lab.experiments.assembly import Economy, build_toy_economy

    compact = SimulationConfig.model_validate({"tick_count": 12, "warmup_ticks": 2})
    policy = AdvanceBasedTaxMediation(minimum_client_land_mu=0.0)

    def run(demand: float) -> tuple[Economy, KernelResult]:
        economy = build_toy_economy(tax_mediation=policy, tax_demand_tael_per_household=demand)
        result = SimulationKernel(compact, list(economy.systems)).run(run_label="mediation")
        return economy, result

    inert_economy, inert = run(0.0)
    active_economy, active = run(5.0)

    for event_type in ("TAX_MEDIATION", "ELITE_TAX_MEDIATION"):
        assert inert.events.filter(inert.events["event_type"] == event_type).height == 0
    for house in inert_economy.elites:
        house.check_balances()

    paid_out = with_trigger_fields(
        active.events.filter(active.events["event_type"] == "ELITE_TAX_MEDIATION"),
        (SILVER_DELTA, "advanced_tael"),
    )
    advanced_to = with_trigger_fields(
        active.events.filter(active.events["event_type"] == "TAX_MEDIATION"),
        (SILVER_DELTA, "debt_delta_tael"),
    )

    assert paid_out.height > 0
    assert advanced_to.height == paid_out.height
    paid = float(paid_out.select(pl.col(SILVER_DELTA).sum()).item() or 0.0)
    received = float(advanced_to.select(pl.col(SILVER_DELTA).sum()).item() or 0.0)
    owed = float(advanced_to.select(pl.col("debt_delta_tael").sum()).item() or 0.0)

    assert paid < 0.0
    assert received == pytest.approx(-paid, rel=1e-9), "silver advanced must arrive somewhere"
    assert owed == pytest.approx(received, rel=1e-9), "what a client received, it owes"
    for house in active_economy.elites:
        house.check_balances()


def test_scenarios_replay_exactly() -> None:
    first = _run("replay")
    second = _run("replay")

    assert first.result.events.equals(second.result.events)
    assert first.result.summary.simulation_digest == second.result.summary.simulation_digest


def test_the_market_layer_adds_no_randomness_under_baseline_forcing() -> None:
    calm = MarketScenario("calm")
    first = run_market_scenario(calm, config=SHORT_CONFIG)
    second = run_market_scenario(
        calm,
        config=SHORT_CONFIG.with_overrides(root_seed=SHORT_CONFIG.root_seed + 1),
    )

    assert first.result.events.equals(second.result.events)


def test_blocking_a_link_stops_traffic_on_it() -> None:
    from late_ming_lab.analysis.concentration import trade_summary

    open_run = _run("open", capacity_unit_shi_per_month=10.0)
    flows = trade_summary(open_run.result.events)
    assert flows.height > 0, "the open scenario must trade, or this test proves nothing"
    busiest = flows.sort("shipped_shi", descending=True).row(0, named=True)
    link = tuple(sorted((busiest["origin"], busiest["destination"])))

    blocked_run = _run("blocked", capacity_unit_shi_per_month=10.0, blocked_links=(link,))
    blocked_flows = trade_summary(blocked_run.result.events)
    blocked_links = (
        {
            tuple(sorted((row["origin"], row["destination"])))
            for row in blocked_flows.iter_rows(named=True)
        }
        if blocked_flows.height
        else set()
    )

    assert link not in blocked_links
    assert (
        float(
            blocked_flows.filter(
                (blocked_flows["origin"] == link[0]) & (blocked_flows["destination"] == link[1])
            )["shipped_shi"].sum()
            if blocked_flows.height
            else 0.0
        )
        == 0.0
    )
