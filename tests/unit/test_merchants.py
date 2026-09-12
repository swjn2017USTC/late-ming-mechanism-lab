"""Merchant houses: silver, stock, and the flows that move between them."""

from __future__ import annotations

import pytest

from late_ming_lab.actors.ledger import GRAIN_DELTA, SILVER_DELTA, LedgerError
from late_ming_lab.actors.merchants import MerchantHouse, MerchantLayer


def _house(**overrides: object) -> MerchantHouse:
    payload: dict[str, object] = {
        "node_id": "toy-sx-a",
        "silver_tael": 100.0,
        "grain_shi": 50.0,
        **overrides,
    }
    return MerchantHouse.model_validate(payload)


def test_a_house_sells_grain_for_silver_and_reconciles() -> None:
    house = _house()

    event = house.sell_to_household(
        shi=10.0, price_tael_per_shi=1.5, buyer_id="toy-sx-a:poor-smallholder", rule_version="t"
    )

    assert house.grain_shi == 40.0
    assert house.silver_tael == 115.0
    assert event.trigger[GRAIN_DELTA] == -10.0
    assert event.trigger[SILVER_DELTA] == 15.0
    house.check_balances()


def test_a_sale_can_never_oversell_the_granary() -> None:
    house = _house(grain_shi=4.0)

    event = house.sell_to_household(
        shi=10.0, price_tael_per_shi=1.5, buyer_id="somebody", rule_version="t"
    )

    assert house.grain_shi == 0.0
    assert event.trigger["shi"] == 4.0
    house.check_balances()


def test_a_purchase_can_never_overdraw_the_silver() -> None:
    house = _house(silver_tael=3.0)

    event = house.buy_from_household(
        shi=10.0, price_tael_per_shi=1.5, seller_id="somebody", rule_version="t"
    )

    assert house.silver_tael == 0.0
    assert event.trigger["cost_tael"] == 3.0
    assert house.grain_shi == pytest.approx(50.0 + 2.0)
    house.check_balances()


def test_movable_goods_are_bought_with_silver_and_kept_as_goods() -> None:
    house = _house()

    house.buy_movables(proceeds_tael=20.0, seller_id="somebody", rule_version="t")

    assert house.silver_tael == 80.0
    assert house.goods_tael == 20.0
    house.check_balances()


def test_a_shipment_that_loses_grain_pays_for_what_arrives() -> None:
    house = _house(grain_shi=100.0)

    shipment, loss = house.ship_out(
        shi=20.0,
        arrived_shi=16.0,
        proceeds_tael=16.0 * 2.0,
        destination="toy-hn-a",
        rule_version="t",
    )

    assert house.grain_shi == 80.0
    assert house.silver_tael == 132.0
    assert shipment.trigger["lost_shi"] == 4.0
    assert loss.event_type == "TRADE_LOSS"
    assert loss.trigger["lost_shi"] == 4.0
    house.check_balances()


def test_a_merchant_cannot_spend_silver_it_does_not_hold_on_a_receipt() -> None:
    house = _house(silver_tael=5.0)

    house.receive(shi=10.0, paid_tael=100.0, origin="toy-hn-a", rule_version="t")

    assert house.silver_tael == 0.0
    assert house.grain_shi == 60.0
    house.check_balances()


def test_an_impossible_movement_is_refused_before_anything_changes() -> None:
    house = _house(grain_shi=1.0)
    before = (house.grain_shi, house.silver_tael, dict(house.ledger_deltas))

    with pytest.raises(LedgerError, match="impossible balance change"):
        house._apply(grain=-5.0)

    assert (house.grain_shi, house.silver_tael, dict(house.ledger_deltas)) == before


def test_the_layer_indexes_houses_by_node_and_reconciles_them() -> None:
    layer = MerchantLayer(
        (
            _house(node_id="toy-sx-a", grain_shi=10.0, silver_tael=5.0),
            _house(node_id="toy-hn-a", grain_shi=20.0, silver_tael=7.0),
        )
    )

    assert len(layer) == 2
    assert layer.total_grain_shi == 30.0
    assert layer.total_silver_tael == 12.0
    assert [house.node_id for house in layer] == ["toy-hn-a", "toy-sx-a"]
    assert layer.require("toy-hn-a").grain_shi == 20.0

    with pytest.raises(KeyError, match="no merchant house"):
        layer.require("toy-ext-sichuan")
    with pytest.raises(ValueError, match="at least one house"):
        MerchantLayer(())
    with pytest.raises(ValueError, match="duplicate merchant nodes"):
        MerchantLayer((_house(), _house()))
    layer.check_invariants()


def test_a_merchant_snapshot_reports_its_position() -> None:
    house = _house()
    snapshot = house.snapshot(price_tael_per_shi=1.5, rule_version="t")

    assert snapshot.trigger["grain_shi"] == 50.0
    assert snapshot.trigger["stock_value_tael"] == 75.0
    assert snapshot.trigger["silver_tael"] == 100.0
