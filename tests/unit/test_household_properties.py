"""Property tests: the balance sheet holds for any endowment and any season.

These tests do not assert what the model should *do*; they assert what it must never do —
hold a negative balance, move a balance without recording it, or let cohort weight change.
The ladder is exercised over arbitrary endowments and arbitrary exogenous impact sequences.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from late_ming_lab.actors.exchange import CreditSource, GrainMarket
from late_ming_lab.actors.households import (
    CohortClass,
    HouseholdCohortAgent,
    HouseholdPopulation,
)
from late_ming_lab.actors.ledger import BALANCE_TOLERANCE
from late_ming_lab.core.tick import TickContext
from late_ming_lab.evidence.parameters import core_default_household_parameters
from late_ming_lab.networks.nodes import AgrarianZone

PARAMETERS = core_default_household_parameters()

ENDOWMENTS = st.fixed_dictionaries(
    {
        "households": st.floats(min_value=1.0, max_value=5000.0),
        "land_mu": st.floats(min_value=0.0, max_value=5000.0),
        "grain_shi": st.floats(min_value=0.0, max_value=2000.0),
        "silver_tael": st.floats(min_value=0.0, max_value=2000.0),
        "debt_tael": st.floats(min_value=0.0, max_value=500.0),
        "movable_assets_tael": st.floats(min_value=0.0, max_value=500.0),
    }
)

IMPACT_SEQUENCES = st.lists(st.floats(min_value=0.0, max_value=1.0), min_size=1, max_size=24)


def _cohort(endowment: dict[str, float], *, adults: float) -> HouseholdCohortAgent:
    cohort = HouseholdCohortAgent.model_validate(
        {
            "cohort_id": "prop:cohort",
            "node_id": "prop-node",
            "cohort_class": CohortClass.POOR_SMALLHOLDER,
            "zone": AgrarianZone.LOESS_DRYLAND,
            "adults": adults,
            **endowment,
        }
    )
    cohort.set_land_reference_value(PARAMETERS.land_reference_value_tael_per_mu)
    return cohort


@settings(
    max_examples=75,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(
    endowment=ENDOWMENTS,
    impacts=IMPACT_SEQUENCES,
    demand=st.floats(min_value=0.0, max_value=1.0),
)
def test_balances_stay_non_negative_and_reconcile(
    tick_context: TickContext,
    market: GrainMarket,
    credit: CreditSource,
    endowment: dict[str, float],
    impacts: list[float],
    demand: float,
) -> None:
    cohort = _cohort(endowment, adults=endowment["households"] * 2.0)

    for impact in impacts:
        cohort.accumulate_climate_impact(impact)
        cohort.monthly_budget(
            tick_context,
            parameters=PARAMETERS,
            labour_demand_factor=demand,
            market=market,
            credit=credit,
            rule_version="property",
        )
        cohort.check_balances()

    for balance in (
        cohort.grain_shi,
        cohort.silver_tael,
        cohort.land_mu,
        cohort.debt_tael,
        cohort.movable_assets_tael,
    ):
        assert balance >= -BALANCE_TOLERANCE


@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(endowment=ENDOWMENTS, impacts=IMPACT_SEQUENCES)
def test_consumption_never_exceeds_what_the_ladder_could_assemble(
    tick_context: TickContext,
    market: GrainMarket,
    credit: CreditSource,
    endowment: dict[str, float],
    impacts: list[float],
) -> None:
    cohort = _cohort(endowment, adults=endowment["households"] * 2.0)

    for impact in impacts:
        cohort.accumulate_climate_impact(impact)
        events = cohort.monthly_budget(
            tick_context,
            parameters=PARAMETERS,
            labour_demand_factor=0.5,
            market=market,
            credit=credit,
            rule_version="property",
        )
        consumption = next(event for event in events if event.event_type.value == "CONSUMPTION")
        need = consumption.trigger["need_shi"]
        floor = consumption.trigger["floor_shi"]
        eaten = consumption.trigger["eaten_shi"]

        assert 0.0 <= eaten <= need
        assert 0.0 <= consumption.trigger["unmet_shi"] <= floor
        assert consumption.trigger["purchased_shi"] <= eaten
        assert consumption.trigger["reduced_shi"] >= consumption.trigger["unmet_shi"]
        # Whatever was eaten was debited from the granary in the same event.
        assert consumption.trigger["grain_delta_shi"] == -eaten


@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(endowment=ENDOWMENTS, impacts=IMPACT_SEQUENCES)
def test_grain_is_conserved_across_a_sequence_of_months(
    tick_context: TickContext,
    market: GrainMarket,
    credit: CreditSource,
    endowment: dict[str, float],
    impacts: list[float],
) -> None:
    """Flow conservation: everything eaten was earned, harvested, bought or taken from stock."""
    cohort = _cohort(endowment, adults=endowment["households"] * 2.0)
    households = cohort.households
    initial_grain = cohort.grain_shi
    eaten = credited = 0.0

    for impact in impacts:
        cohort.accumulate_climate_impact(impact)
        for event in cohort.monthly_budget(
            tick_context,
            parameters=PARAMETERS,
            labour_demand_factor=0.0,
            market=market,
            credit=credit,
            rule_version="property",
        ):
            trigger = event.trigger
            if event.event_type.value == "CONSUMPTION":
                eaten += trigger["eaten_shi"]
            elif event.event_type.value == "GRAIN_PURCHASE":
                credited += trigger["purchased_shi"]

        assert cohort.households == households
        cohort.check_balances()

    assert eaten == pytest.approx(credited + initial_grain - cohort.grain_shi)
    assert eaten >= -BALANCE_TOLERANCE


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(endowment=ENDOWMENTS)
def test_population_invariants_hold_after_arbitrary_transitions(
    endowment: dict[str, float],
) -> None:
    cohort = _cohort(endowment, adults=endowment["households"] * 2.0)
    population = HouseholdPopulation((cohort,))

    for need, unmet in ((10.0, 0.0), (10.0, 3.0), (0.0, 0.0)):
        population.record_month(cohort.cohort_id, need_shi=need, unmet_shi=unmet)
        population.check_invariants()

    assert 0.0 <= population.unmet_ratio(cohort.cohort_id) <= 1.0


def test_endowments_outside_the_contract_are_rejected() -> None:
    for payload in (
        {"households": 0.0},
        {"households": -1.0},
        {"adults": 0.0},
        {"land_mu": -1.0},
        {"grain_shi": -0.01},
        {"silver_tael": -1.0},
        {"debt_tael": -1.0},
        {"movable_assets_tael": -5.0},
    ):
        base: dict[str, object] = {
            "cohort_id": "prop:cohort",
            "node_id": "prop-node",
            "cohort_class": CohortClass.POOR_SMALLHOLDER,
            "zone": AgrarianZone.LOESS_DRYLAND,
            "households": 10.0,
            "adults": 20.0,
            "land_mu": 10.0,
            "grain_shi": 10.0,
            "silver_tael": 10.0,
            "debt_tael": 0.0,
            "movable_assets_tael": 10.0,
            **payload,
        }
        with pytest.raises(ValidationError):
            HouseholdCohortAgent.model_validate(base)
