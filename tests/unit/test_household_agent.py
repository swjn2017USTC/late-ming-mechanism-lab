"""Cohort accounting and the coping ladder, one step at a time.

The ladder is exercised against test counterparties (see `tests/conftest.py`) so the assertions
are about the household's own behaviour: which rung it reaches, what it records, and that its
balance sheet still reconciles afterwards.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from late_ming_lab.actors.exchange import CreditSource, GrainMarket
from late_ming_lab.actors.households import (
    ASSETS_DELTA,
    DEBT_DELTA,
    GRAIN_DELTA,
    LAND_DELTA,
    SILVER_DELTA,
    CohortClass,
    CohortEventType,
    CopingStage,
    HouseholdCohortAgent,
    HouseholdLedgerError,
    HouseholdPopulation,
)
from late_ming_lab.core.tick import TickContext
from late_ming_lab.evidence.parameters import core_default_household_parameters
from late_ming_lab.networks.nodes import AgrarianZone

CreditSourceFactory = Callable[..., CreditSource]
GrainMarketFactory = Callable[..., GrainMarket]

PARAMETERS = core_default_household_parameters()
MARKET_PRICE = 1.5


def _cohort(**overrides: float) -> HouseholdCohortAgent:
    payload: dict[str, object] = {
        "cohort_id": "toy-sx-a:poor-smallholder",
        "node_id": "toy-sx-a",
        "cohort_class": CohortClass.POOR_SMALLHOLDER,
        "zone": AgrarianZone.LOESS_DRYLAND,
        "households": 100.0,
        "adults": 200.0,
        "land_mu": 800.0,
        "grain_shi": 400.0,
        "silver_tael": 100.0,
        "debt_tael": 0.0,
        "movable_assets_tael": 200.0,
        **overrides,
    }
    cohort = HouseholdCohortAgent.model_validate(payload)
    cohort.set_land_reference_value(PARAMETERS.land_reference_value_tael_per_mu)
    return cohort


def test_a_self_sufficient_month_eats_from_storage_and_records_no_distress(
    tick_context: TickContext, market: GrainMarket, credit: CreditSource
) -> None:
    cohort = _cohort(grain_shi=10_000.0)

    events = cohort.monthly_budget(
        tick_context,
        parameters=PARAMETERS,
        labour_demand_factor=1.0,
        market=market,
        credit=credit,
        rule_version="test",
    )

    consumption = next(e for e in events if e.event_type is CohortEventType.CONSUMPTION)
    assert consumption.trigger["unmet_shi"] == 0.0
    assert consumption.trigger["reduced_shi"] == 0.0
    assert consumption.outcome == "met-floor"
    assert cohort.coping_stage is CopingStage.SELF_SUFFICIENT
    assert all(
        event.event_type not in (CohortEventType.BORROWING_REQUEST, CohortEventType.LAND_SALE)
        for event in events
    )


def test_the_ladder_escalates_only_as_far_as_the_shortfall_requires(
    tick_context: TickContext,
    market: GrainMarket,
    credit: CreditSource,
    credit_factory: CreditSourceFactory,
) -> None:
    # Silver on hand covers the floor: the household stays at the top of the ladder.
    covered = _cohort(grain_shi=0.0, silver_tael=100.0)
    covered.monthly_budget(
        tick_context,
        parameters=PARAMETERS,
        labour_demand_factor=0.0,
        market=market,
        credit=credit,
        rule_version="test",
    )

    assert covered.coping_stage is CopingStage.REDUCING_CONSUMPTION
    assert covered.debt_tael == 0.0

    # No silver but real collateral: the household borrows rather than selling anything.
    borrowing = _cohort(grain_shi=0.0, silver_tael=0.0)
    borrowing.monthly_budget(
        tick_context,
        parameters=PARAMETERS,
        labour_demand_factor=0.0,
        market=market,
        credit=credit,
        rule_version="test",
    )

    assert borrowing.coping_stage is CopingStage.BORROWING
    assert borrowing.land_mu == 800.0
    assert borrowing.movable_assets_tael == 200.0
    assert borrowing.debt_tael > 0.0

    # No credit, no silver, no goods: land goes next.
    no_credit = credit_factory(loan_to_value=0.0)
    selling_land = _cohort(grain_shi=0.0, silver_tael=0.0, movable_assets_tael=0.0)
    selling_land.monthly_budget(
        tick_context,
        parameters=PARAMETERS,
        labour_demand_factor=0.0,
        market=market,
        credit=no_credit,
        rule_version="test",
    )

    assert selling_land.coping_stage is CopingStage.SELLING_LAND
    assert selling_land.land_mu < 800.0

    # Nothing left to sell: the floor cannot be met at all.
    destitute = _cohort(grain_shi=0.0, silver_tael=0.0, movable_assets_tael=0.0, land_mu=0.0)
    destitute.monthly_budget(
        tick_context,
        parameters=PARAMETERS,
        labour_demand_factor=0.0,
        market=market,
        credit=no_credit,
        rule_version="test",
    )

    assert destitute.coping_stage is CopingStage.DESTITUTE


def test_borrowing_requests_are_recorded_even_when_capacity_is_exhausted(
    tick_context: TickContext, market: GrainMarket, credit_factory: CreditSourceFactory
) -> None:
    no_credit = credit_factory(loan_to_value=0.0)
    cohort = _cohort(grain_shi=0.0, silver_tael=0.0, movable_assets_tael=0.0, land_mu=0.0)

    events = cohort.monthly_budget(
        tick_context,
        parameters=PARAMETERS,
        labour_demand_factor=0.0,
        market=market,
        credit=no_credit,
        rule_version="test",
    )

    request = next(e for e in events if e.event_type is CohortEventType.BORROWING_REQUEST)
    assert request.trigger["granted_tael"] == 0.0
    assert request.outcome.startswith("no-capacity:")
    assert cohort.debt_tael == 0.0


def test_a_market_that_cannot_deliver_stops_the_rung(
    tick_context: TickContext, credit: CreditSource, market_factory: GrainMarketFactory
) -> None:
    """A rung fails because the counterparty cannot deliver, not because a formula says so."""
    broke_market = market_factory(grain_shi=0.0, silver_tael=0.0)
    cohort = _cohort(grain_shi=0.0, silver_tael=100.0)

    events = cohort.monthly_budget(
        tick_context,
        parameters=PARAMETERS,
        labour_demand_factor=0.0,
        market=broke_market,
        credit=credit,
        rule_version="test",
    )

    assert not [e for e in events if e.event_type is CohortEventType.GRAIN_PURCHASE]
    assert cohort.grain_shi == 0.0
    assert cohort.coping_stage is not CopingStage.SELF_SUFFICIENT


def test_land_is_sold_last_and_only_after_movable_assets(
    tick_context: TickContext, market: GrainMarket, credit_factory: CreditSourceFactory
) -> None:
    no_credit = credit_factory(loan_to_value=0.0)
    cohort = _cohort(grain_shi=0.0, silver_tael=0.0, movable_assets_tael=10.0, land_mu=20.0)

    events = cohort.monthly_budget(
        tick_context,
        parameters=PARAMETERS,
        labour_demand_factor=0.0,
        market=market,
        credit=no_credit,
        rule_version="test",
    )
    order = [event.event_type for event in events]

    assert order.index(CohortEventType.MOVABLE_ASSET_SALE) < order.index(CohortEventType.LAND_SALE)
    assert cohort.movable_assets_tael == 0.0
    assert cohort.land_mu < 20.0
    assert cohort.coping_stage in (CopingStage.SELLING_LAND, CopingStage.DESTITUTE)


def test_distress_is_unmet_need_and_is_never_negative(
    tick_context: TickContext, market: GrainMarket, credit_factory: CreditSourceFactory
) -> None:
    no_credit = credit_factory(loan_to_value=0.0)
    cohort = _cohort(grain_shi=0.0, silver_tael=0.0, movable_assets_tael=0.0, land_mu=0.0)

    events = cohort.monthly_budget(
        tick_context,
        parameters=PARAMETERS,
        labour_demand_factor=0.0,
        market=market,
        credit=no_credit,
        rule_version="test",
    )
    consumption = next(e for e in events if e.event_type is CohortEventType.CONSUMPTION)

    assert consumption.trigger["unmet_shi"] > 0.0
    assert consumption.trigger["unmet_shi"] <= consumption.trigger["floor_shi"]
    assert consumption.trigger["eaten_shi"] == 0.0
    assert consumption.trigger["reduced_shi"] >= consumption.trigger["unmet_shi"]


def test_negative_balances_are_impossible() -> None:
    cohort = _cohort(grain_shi=0.0, silver_tael=0.0)

    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        cohort.grain_shi = -1.0
    with pytest.raises(ValidationError):
        cohort.land_mu = -0.5
    with pytest.raises(ValidationError):
        cohort.silver_tael = -0.01
    with pytest.raises(ValidationError):
        cohort.movable_assets_tael = -0.01


def test_an_unsourced_balance_change_is_detected() -> None:
    cohort = _cohort()
    cohort.grain_shi = cohort.grain_shi + 1.0  # bypasses the ledger on purpose

    with pytest.raises(HouseholdLedgerError, match="changed without an entry"):
        cohort.check_balances()


def test_every_primitive_records_its_delta_and_reconciles() -> None:
    cohort = _cohort()
    before = dict(cohort.ledger_deltas)

    cohort.receive_wage_grain(
        grain_shi=12.0, wage_shi_per_adult=0.3, labour_demand_factor=0.5, rule_version="test"
    )
    cohort.record_borrowing_request(
        requested_tael=4.0,
        granted_tael=4.0,
        capacity_tael=10.0,
        lender_id="elite::toy-sx-a",
        rule_version="test",
    )
    cohort.record_grain_purchase(
        shi=2.0, price_tael_per_shi=1.5, occasion="test", rule_version="test"
    )
    cohort.record_movable_asset_sale(proceeds_tael=3.0, rule_version="test")
    cohort.record_land_sale(mu=4.0, price_tael_per_mu=2.5, rule_version="test")
    cohort.record_debt_interest(interest_tael=0.5, rate_monthly=0.005, rule_version="test")
    cohort.record_debt_repayment(repaid_tael=1.0, rule_version="test")
    cohort.check_balances()

    deltas = cohort.ledger_deltas
    assert deltas[GRAIN_DELTA] == before[GRAIN_DELTA] + 12.0 + 2.0
    assert deltas[SILVER_DELTA] == before[SILVER_DELTA] + 4.0 - 3.0 + 3.0 + 10.0 - 1.0
    assert deltas[LAND_DELTA] == before[LAND_DELTA] - 4.0
    assert deltas[ASSETS_DELTA] == before[ASSETS_DELTA] - 3.0
    assert deltas[DEBT_DELTA] == before[DEBT_DELTA] + 4.0 + 0.5 - 1.0


def test_a_purchase_can_never_overdraw_the_silver_held() -> None:
    cohort = _cohort(silver_tael=1.0)

    event = cohort.record_grain_purchase(
        shi=100.0, price_tael_per_shi=1.5, occasion="test", rule_version="test"
    )

    assert cohort.silver_tael == 0.0
    assert event.trigger["cost_tael"] == 1.0
    assert event.trigger["purchased_shi"] < 100.0
    cohort.check_balances()


def test_a_good_harvest_repays_debt_out_of_the_surplus() -> None:
    cohort = _cohort(grain_shi=20.0, debt_tael=10.0)

    event = cohort.record_repayment_from_harvest(
        repaid_tael=6.0,
        price_tael_per_shi=0.6,
        rule_version="test",
    )

    assert event.outcome == "repaid-in-grain"
    assert cohort.debt_tael == 4.0
    assert cohort.grain_shi == 10.0
    cohort.check_balances()


def test_the_coping_stage_escalates_once_and_resets_after_a_harvest(
    tick_context: TickContext, market: GrainMarket, credit: CreditSource
) -> None:
    cohort = _cohort(grain_shi=0.0, silver_tael=0.0)

    first = cohort.monthly_budget(
        tick_context,
        parameters=PARAMETERS,
        labour_demand_factor=0.0,
        market=market,
        credit=credit,
        rule_version="test",
    )
    transitions = [e for e in first if e.event_type is CohortEventType.COPING_TRANSITION]
    assert len(transitions) == 1
    escalated = cohort.coping_stage
    assert escalated is CopingStage.BORROWING

    second = cohort.monthly_budget(
        tick_context,
        parameters=PARAMETERS,
        labour_demand_factor=0.0,
        market=market,
        credit=credit,
        rule_version="test",
    )
    assert cohort.coping_stage >= escalated
    assert all(
        e.trigger["stage_from"] >= float(escalated)
        for e in second
        if e.event_type is CohortEventType.COPING_TRANSITION
    )

    cohort.grain_shi = 10_000.0
    reset = cohort.reset_coping_stage(reason="test", rule_version="test")
    assert reset is not None
    assert cohort.coping_stage is CopingStage.SELF_SUFFICIENT
    assert cohort.reset_coping_stage(reason="test", rule_version="test") is None


def test_eligibility_events_fire_only_on_a_change() -> None:
    cohort = _cohort()

    assert (
        cohort.record_eligibility(
            unmet_ratio_12m=0.0,
            temporary=False,
            permanent=False,
            recruitment=False,
            rule_version="test",
        )
        is None
    )

    raised = cohort.record_eligibility(
        unmet_ratio_12m=0.3,
        temporary=True,
        permanent=True,
        recruitment=True,
        rule_version="test",
    )
    assert raised is not None
    assert raised.outcome == "temporary-migration+permanent-migration+recruitment"
    assert cohort.permanent_migration_eligible
    assert (
        cohort.record_eligibility(
            unmet_ratio_12m=0.3,
            temporary=True,
            permanent=True,
            recruitment=True,
            rule_version="test",
        )
        is None
    )


def test_the_snapshot_reports_the_whole_balance_sheet() -> None:
    cohort = _cohort()
    snapshot = cohort.snapshot_event(rule_version="test")

    assert snapshot.event_type is CohortEventType.COHORT_STATE
    assert snapshot.outcome == CopingStage.SELF_SUFFICIENT.token
    for key in ("households", "land_mu", "grain_shi", "silver_tael", "debt_tael", "adults"):
        assert key in snapshot.trigger


def test_market_sales_and_transfers_record_their_deltas() -> None:
    cohort = _cohort(grain_shi=1_000.0)

    sale = cohort.record_market_sale(
        shi=100.0, price_tael_per_shi=0.6, buyer_id="merchant::toy-sx-a", rule_version="test"
    )
    relief = cohort.record_relief(grain_shi=20.0, donor_id="elite::toy-sx-a", rule_version="test")
    advanced = cohort.record_tax_mediation(
        advanced_tael=5.0, mediator_id="elite::toy-sx-a", rule_version="test"
    )

    assert sale.trigger[GRAIN_DELTA] == -100.0
    assert sale.trigger[SILVER_DELTA] == 60.0
    assert relief.trigger[GRAIN_DELTA] == 20.0
    assert advanced.trigger[DEBT_DELTA] == 5.0
    assert advanced.trigger[SILVER_DELTA] == 5.0
    cohort.check_balances()


def test_surplus_for_sale_keeps_the_declared_year_of_need() -> None:
    cohort = _cohort(grain_shi=10_000.0)

    assert cohort.surplus_for_sale(parameters=PARAMETERS) == pytest.approx(
        10_000.0 - PARAMETERS.annual_need_shi(cohort.adults)
    )
    cohort.grain_shi = 10.0
    assert cohort.surplus_for_sale(parameters=PARAMETERS) == 0.0


def test_population_tracks_the_rolling_distress_window() -> None:
    cohort = _cohort()
    population = HouseholdPopulation((cohort,))

    assert population.unmet_ratio(cohort.cohort_id) == 0.0
    for _ in range(population.window_months + 3):
        population.record_month(cohort.cohort_id, need_shi=10.0, unmet_shi=2.0)

    assert population.unmet_ratio(cohort.cohort_id) == pytest.approx(0.2)
    assert population.total_households == 100.0
    assert population.require(cohort.cohort_id) is cohort
    with pytest.raises(KeyError, match="unknown cohort"):
        population.require("nowhere:nobody")
    with pytest.raises(ValueError, match="at least one cohort"):
        HouseholdPopulation(())
    with pytest.raises(ValueError, match="duplicate cohort ids"):
        HouseholdPopulation((cohort, _cohort()))


def test_population_labour_demand_averages_the_local_harvest() -> None:
    cohort = _cohort()
    population = HouseholdPopulation((cohort,))

    assert population.node_yield_factor(cohort.node_id) == 1.0
    population.set_node_yield_factor(cohort.node_id, 0.4)
    assert population.node_yield_factor(cohort.node_id) == 0.4
    with pytest.raises(ValueError, match="yield fraction"):
        population.set_node_yield_factor(cohort.node_id, 1.2)
    with pytest.raises(KeyError):
        population.node_yield_factor("toy-nowhere")


def test_population_invariants_reconcile_every_cohort() -> None:
    cohort = _cohort()
    population = HouseholdPopulation((cohort,))

    population.check_invariants()
    cohort.grain_shi = cohort.grain_shi + 5.0

    with pytest.raises(HouseholdLedgerError):
        population.check_invariants()


def test_food_bought_on_the_ladder_is_eaten_exactly_once(
    tick_context: TickContext, market: GrainMarket, credit_factory: CreditSourceFactory
) -> None:
    """Regression: a purchase must be credited once and debited once, never eaten twice."""
    no_wage = PARAMETERS.model_validate(
        {**PARAMETERS.model_dump(), "wage_grain_shi_per_adult_month": 0.0}
    )
    no_credit = credit_factory(loan_to_value=0.0)
    cohort = _cohort(grain_shi=0.0, silver_tael=1_000.0, movable_assets_tael=0.0, land_mu=0.0)
    initial_grain = cohort.grain_shi
    eaten = purchased = 0.0

    for _ in range(6):
        for event in cohort.monthly_budget(
            tick_context,
            parameters=no_wage,
            labour_demand_factor=0.0,
            market=market,
            credit=no_credit,
            rule_version="test",
        ):
            if event.event_type is CohortEventType.CONSUMPTION:
                eaten += event.trigger["eaten_shi"]
                assert event.trigger[GRAIN_DELTA] == -event.trigger["eaten_shi"]
            elif event.event_type is CohortEventType.GRAIN_PURCHASE:
                purchased += event.trigger["purchased_shi"]

    assert purchased > 0.0
    assert eaten == pytest.approx(purchased + initial_grain - cohort.grain_shi)
    assert eaten == pytest.approx(purchased)
    cohort.check_balances()


def test_an_impossible_change_leaves_the_balance_sheet_untouched() -> None:
    cohort = _cohort(grain_shi=0.0, silver_tael=1.0)
    before = (cohort.grain_shi, cohort.silver_tael, dict(cohort.ledger_deltas))

    with pytest.raises(HouseholdLedgerError, match="impossible balance change"):
        cohort._apply(grain=5.0, silver=-2.0)

    assert (cohort.grain_shi, cohort.silver_tael, dict(cohort.ledger_deltas)) == before
