"""County government: the five capacities, the tax ledger and the relief granary."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from late_ming_lab.actors.government import (
    CAPACITY_FIELDS,
    CountyGovernment,
    GovernmentLayer,
    StateCapacity,
)
from late_ming_lab.actors.ledger import GRAIN_DELTA, SILVER_DELTA


def _county(**overrides: object) -> CountyGovernment:
    payload: dict[str, object] = {
        "node_id": "toy-sx-a",
        "capacity": StateCapacity(
            tax_collection=0.6, information=0.5, relief=0.5, coercion=0.4, logistics=0.6
        ),
        "silver_tael": 0.0,
        "grain_shi": 0.0,
        **overrides,
    }
    return CountyGovernment.model_validate(payload)


def test_state_capacity_is_five_separate_capacities() -> None:
    capacity = StateCapacity(
        tax_collection=0.1, information=0.2, relief=0.3, coercion=0.4, logistics=0.5
    )

    assert tuple(type(capacity).model_fields) == CAPACITY_FIELDS
    assert len(CAPACITY_FIELDS) == 5
    assert capacity.as_mapping() == {
        "tax_collection": 0.1,
        "information": 0.2,
        "relief": 0.3,
        "coercion": 0.4,
        "logistics": 0.5,
    }
    for aggregate in ("total", "mean", "index", "state_capacity", "overall"):
        assert not hasattr(capacity, aggregate), f"capacity must not collapse into {aggregate}"

    with pytest.raises(ValidationError):
        StateCapacity.model_validate(
            {
                "tax_collection": 1.5,
                "information": 0.5,
                "relief": 0.5,
                "coercion": 0.5,
                "logistics": 0.5,
            }
        )
    with pytest.raises(ValidationError):
        StateCapacity.model_validate(
            {
                "tax_collection": 0.5,
                "information": 0.5,
                "relief": 0.5,
                "coercion": 0.5,
                "logistics": 0.5,
                "state_capacity": 0.5,
            }
        )


def test_an_assessment_creates_an_obligation_without_moving_a_balance() -> None:
    county = _county()
    before = dict(county.ledger_deltas)

    event = county.record_assessment(
        quota_tael=100.0, taxable_land_mu=1_000.0, hidden_land_mu=200.0, assessment_rate=0.02
    )

    assert county.silver_tael == 0.0
    assert county.grain_shi == 0.0
    assert dict(county.ledger_deltas) == before
    assert county.flows["quota_tael"] == 100.0
    assert county.flows["taxable_land_mu"] == 1_000.0
    assert event.trigger["information_capacity"] == 0.5
    county.check_balances()


def test_receipts_costs_and_arrears_accumulate_in_the_month() -> None:
    county = _county(silver_tael=0.0)

    county.receive_tax(silver_tael=80.0, payer_id="somebody", channel="household")
    county.pay_collection_cost(silver_tael=5.0)
    county.record_arrears(delta_tael=20.0)

    assert county.silver_tael == 75.0
    assert county.flows["receipts_tael"] == 80.0
    assert county.flows["collection_cost_tael"] == 5.0
    assert county.flows["arrears_delta_tael"] == 20.0
    county.check_balances()


def test_a_cost_larger_than_the_treasury_is_partly_unpaid() -> None:
    county = _county(silver_tael=3.0)

    event = county.pay_collection_cost(silver_tael=10.0)

    assert county.silver_tael == 0.0
    assert event.trigger["collection_cost_tael"] == 3.0
    assert event.trigger["collection_cost_due_tael"] == 10.0
    assert event.outcome == "unpaid-in-part"
    county.check_balances()


def test_the_granary_can_only_release_what_it_holds() -> None:
    county = _county(grain_shi=10.0, silver_tael=100.0)

    released = county.release_relief(grain_shi=4.0, recipient_id="somebody")

    assert county.grain_shi == 6.0
    assert released.trigger["released_shi"] == 4.0
    assert released.trigger[GRAIN_DELTA] == -4.0

    # A plan larger than the granary releases what is there and says what was planned.
    shortfall = county.release_relief(grain_shi=100.0, recipient_id="somebody")
    assert shortfall.trigger["released_shi"] == 6.0
    assert shortfall.trigger["planned_shi"] == 100.0
    assert county.grain_shi == 0.0
    county.check_balances()

    empty = county.release_relief(grain_shi=1.0, recipient_id="somebody")
    assert empty.trigger["released_shi"] == 0.0


def test_buying_grain_moves_silver_into_the_granary_and_respects_the_treasury() -> None:
    county = _county(silver_tael=6.0)

    event = county.buy_grain(grain_shi=100.0, price_tael_per_shi=0.6)

    assert event.trigger["purchased_shi"] == pytest.approx(10.0)
    assert event.trigger["cost_tael"] == pytest.approx(6.0)
    assert county.silver_tael == 0.0
    assert county.grain_shi == pytest.approx(10.0)
    assert event.trigger[SILVER_DELTA] == pytest.approx(-6.0)
    county.check_balances()


def test_the_snapshot_reports_the_month_and_all_five_capacities() -> None:
    county = _county(silver_tael=100.0)
    county.record_assessment(
        quota_tael=100.0, taxable_land_mu=1_000.0, hidden_land_mu=0.0, assessment_rate=0.02
    )
    county.record_extraction_decision(
        pressure=0.02, effort=0.5, arrears_tael_before=0.0, quota_tael=100.0, reachable_tael=40.0
    )
    county.receive_tax(silver_tael=30.0, payer_id="somebody", channel="household")
    county.pay_collection_cost(silver_tael=2.0)

    snapshot = county.snapshot(arrears_tael=10.0)

    assert snapshot.event_type.value == "COUNTY_STATE"
    assert snapshot.trigger["net_receipts_tael"] == pytest.approx(28.0)
    assert snapshot.trigger["arrears_tael"] == 10.0
    assert snapshot.trigger["reachable_tael"] == 40.0
    for field in CAPACITY_FIELDS:
        assert snapshot.trigger[f"{field}_capacity"] == getattr(county.capacity, field)


def test_a_new_tick_resets_the_flows_but_not_the_balances() -> None:
    county = _county(silver_tael=0.0)
    county.receive_tax(silver_tael=25.0, payer_id="somebody", channel="household")
    silver = county.silver_tael

    county.begin_tick()

    assert county.flows["receipts_tael"] == 0.0
    assert county.flows["quota_tael"] == 0.0
    assert county.silver_tael == silver


def test_an_unknown_flow_name_is_refused() -> None:
    county = _county()

    with pytest.raises(KeyError, match="unknown county flow"):
        county.accumulate(income_tael=1.0)


def test_the_layer_indexes_counties_and_reconciles_them() -> None:
    layer = GovernmentLayer((_county(node_id="toy-sx-a"), _county(node_id="toy-hn-a")))

    assert len(layer) == 2
    assert layer.require("toy-sx-a").node_id == "toy-sx-a"
    assert [county.node_id for county in layer] == ["toy-hn-a", "toy-sx-a"]
    with pytest.raises(KeyError, match="no county government"):
        layer.require("nowhere")
    with pytest.raises(ValueError, match="at least one county"):
        GovernmentLayer(())
    with pytest.raises(ValueError, match="duplicate counties"):
        GovernmentLayer((_county(), _county()))
    layer.check_invariants()
