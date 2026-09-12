"""Elite houses: rent, lending, land purchase, relief, and the mediation interface."""

from __future__ import annotations

import pytest

from late_ming_lab.actors.elites import (
    AdvanceBasedTaxMediation,
    EliteLayer,
    LocalEliteAgent,
    NoTaxMediation,
)
from late_ming_lab.actors.ledger import GRAIN_DELTA, LAND_DELTA, SILVER_DELTA, LedgerError
from late_ming_lab.evidence.parameters import core_default_elite_parameters


def _elite(**overrides: object) -> LocalEliteAgent:
    payload: dict[str, object] = {
        "node_id": "toy-sx-a",
        "households": 20.0,
        "land_mu": 9_000.0,
        "grain_shi": 4_000.0,
        "silver_tael": 3_000.0,
        **overrides,
    }
    return LocalEliteAgent.model_validate(payload)


def test_rent_arrives_in_grain_and_reconciles() -> None:
    elite = _elite()

    event = elite.receive_grain(
        grain_shi=100.0, payer_id="toy-sx-a:tenant-household", reason="rent", rule_version="t"
    )

    assert elite.grain_shi == 4_100.0
    assert event.trigger[GRAIN_DELTA] == 100.0
    assert event.outcome == "rent:toy-sx-a:tenant-household"
    elite.check_balances()


def test_a_loan_leaves_the_cash_box_and_the_claim_stays_with_the_borrower() -> None:
    elite = _elite()

    event = elite.issue_loan(
        granted_tael=500.0, borrower_id="toy-sx-a:poor-smallholder", rule_version="t"
    )

    assert elite.silver_tael == 2_500.0
    assert event.trigger[SILVER_DELTA] == -500.0
    elite.check_balances()


def test_buying_land_moves_both_balances() -> None:
    elite = _elite()

    event = elite.buy_land(mu=100.0, paid_tael=250.0, seller_id="somebody", rule_version="t")

    assert elite.land_mu == 9_100.0
    assert elite.silver_tael == 2_750.0
    assert event.trigger[LAND_DELTA] == 100.0
    elite.check_balances()


def test_relief_leaves_the_granary_and_a_house_cannot_give_what_it_lacks() -> None:
    elite = _elite(grain_shi=10.0)

    event = elite.release_relief(grain_shi=4.0, recipient_id="somebody", rule_version="t")

    assert elite.grain_shi == 6.0
    assert event.trigger[GRAIN_DELTA] == -4.0

    with pytest.raises(LedgerError, match="impossible balance change"):
        elite.release_relief(grain_shi=100.0, recipient_id="somebody", rule_version="t")
    assert elite.grain_shi == 6.0


def test_an_elite_snapshot_reports_land_grain_silver_and_claims() -> None:
    elite = _elite()
    snapshot = elite.snapshot(claims_tael=1_234.0, price_tael_per_shi=1.5, rule_version="t")

    assert snapshot.trigger["land_mu"] == 9_000.0
    assert snapshot.trigger["outstanding_claims_tael"] == 1_234.0
    assert snapshot.trigger["land_per_household_mu"] == 450.0
    assert snapshot.trigger["grain_value_tael"] == 6_000.0


def test_the_layer_indexes_and_reconciles_houses() -> None:
    layer = EliteLayer((_elite(node_id="toy-sx-a"), _elite(node_id="toy-hn-a", land_mu=100.0)))

    assert len(layer) == 2
    assert layer.total_land_mu == 9_100.0
    assert layer.require("toy-hn-a").land_mu == 100.0
    with pytest.raises(KeyError, match="no elite house"):
        layer.require("nowhere")
    with pytest.raises(ValueError, match="duplicate elite nodes"):
        EliteLayer((_elite(), _elite()))
    layer.check_invariants()


def test_tax_mediation_policies_advance_according_to_their_rule() -> None:
    parameters = core_default_elite_parameters()
    none = NoTaxMediation()
    advancing = AdvanceBasedTaxMediation(minimum_client_land_mu=50.0)

    assert (
        none.advance_tael(parameters=parameters, client_land_mu=1_000.0, demand_tael=100.0) == 0.0
    )
    assert (
        advancing.advance_tael(parameters=parameters, client_land_mu=10.0, demand_tael=100.0) == 0.0
    )
    assert advancing.advance_tael(
        parameters=parameters, client_land_mu=1_000.0, demand_tael=100.0
    ) == pytest.approx(100.0 * parameters.tax_mediation_advance_share)
    assert (
        advancing.advance_tael(parameters=parameters, client_land_mu=1_000.0, demand_tael=0.0)
        == 0.0
    )


def test_an_elite_cannot_advance_more_silver_than_it_holds() -> None:
    elite = _elite(silver_tael=40.0)

    event = elite.record_tax_mediation(
        advanced_tael=40.0, client_id="somebody", demand_tael=100.0, rule_version="t"
    )

    assert elite.silver_tael == 0.0
    assert event.trigger[SILVER_DELTA] == -40.0
    with pytest.raises(LedgerError):
        elite.record_tax_mediation(
            advanced_tael=1.0, client_id="somebody", demand_tael=100.0, rule_version="t"
        )
