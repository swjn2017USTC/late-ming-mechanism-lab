"""The prior table's observable contract: card ranges only, and refusal everywhere else.

The phase's rule is that priors are bounded by the P08 parameter cards, so these tests attack the
ways that rule could quietly stop holding: a declared name that is not a field of the model it
names, a range widened past its card, a card deleted or re-filed and thereby silently dropped from
calibration, and a "uniform" prior that is really a point mass. None of them is checked by reading
the module's own constants back; each is checked against the registry and the live parameter
models, which are the things that would have to agree with the priors for a run to be trustworthy.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from late_ming_lab.calibration.priors import (
    PriorError,
    build_priors,
    card_free_parameters,
    centres_outside_range,
    excluded_parameters,
)
from late_ming_lab.evidence import parameters as P
from late_ming_lab.evidence.cards import ParameterCard, ParameterCards, load_cards

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The declared table, in the order the sampler will move it. Order is provenance, so it is pinned.
DECLARED_NAMES = (
    "yield_loss_scale",
    "subsistence_grain_per_adult_month_shi",
    "permanent_migration_unmet_ratio",
    "temporary_migration_unmet_ratio",
    "interest_rate_monthly",
    "assessed_value_tael_per_mu",
    "elite_hidden_land_share",
    "reference_price_tael_per_shi",
    "permanent_share_of_households_per_month",
    "temporary_share_of_adults_per_month",
    "pay_tael_per_soldier_month",
    "food_shi_per_soldier_month",
    "food_shi_per_member_month",
)

UNADJUSTED_NAMES = (
    "yield_shi_per_mu",
    "rent_share_of_harvest",
    "land_per_adult_capacity_mu",
    "wage_grain_shi_per_adult_month",
)

DRAWS = 2_000
SEED = 20_260_913


@pytest.fixture(scope="module")
def cards() -> ParameterCards:
    return load_cards(REPO_ROOT)


def _without(cards: ParameterCards, parameter_set: str, parameter: str) -> ParameterCards:
    kept = tuple(
        card for card in cards if (card.parameter_set, card.id) != (parameter_set, parameter)
    )
    return ParameterCards(kept, schema_version=cards.schema_version)


def _replacing(
    cards: ParameterCards, original: ParameterCard, replacement: ParameterCard
) -> ParameterCards:
    kept = tuple(
        card
        for card in cards
        if (card.parameter_set, card.id) != (original.parameter_set, original.id)
    )
    return ParameterCards((*kept, replacement), schema_version=cards.schema_version)


def test_priors_are_exactly_the_declared_card_ranges(cards: ParameterCards) -> None:
    table = build_priors(cards)

    assert table.names() == DECLARED_NAMES
    assert len(table) == len(DECLARED_NAMES)
    for prior in table:
        card = cards.require(prior.parameter_set, prior.name)
        assert card.range is not None
        assert (prior.low, prior.high) == (card.range.low, card.range.high)
        assert prior.card_id == prior.name == card.id
        assert prior.central == card.central
        assert prior.support_class == card.support_class.value
        assert prior.evidence_grade == card.evidence_grade.value
        assert prior.reason
    assert len(table.bounds()) == len(table.names())


def test_declared_names_are_fields_of_their_parameter_set(cards: ParameterCards) -> None:
    """A typo must fail here and not merely leave a parameter at its default for ever."""
    for prior in build_priors(cards):
        model = getattr(P, prior.parameter_set)
        assert prior.name in model.model_fields, (
            f"{prior.parameter_set}.{prior.name} is not a field"
        )


def test_the_table_answers_by_name_and_by_membership(cards: ParameterCards) -> None:
    table = build_priors(cards)

    assert table.by_name("yield_loss_scale").parameter_set == "CropParameters"
    assert table.contains("yield_loss_scale", 0.5)
    assert table.contains("yield_loss_scale", 2.0)
    assert not table.contains("yield_loss_scale", 0.4999)
    assert not table.contains("yield_loss_scale", 2.0001)
    assert table.contains("elite_hidden_land_share", 0.0)
    with pytest.raises(PriorError, match="yield_loss_scales"):
        table.by_name("yield_loss_scales")
    with pytest.raises(PriorError, match="not-a-parameter"):
        table.contains("not-a-parameter", 1.0)


def test_sample_is_uniform_on_the_ranges_and_not_a_point_mass(cards: ParameterCards) -> None:
    table = build_priors(cards)
    rng = np.random.default_rng(SEED)
    draws = [table.sample(rng) for _ in range(DRAWS)]

    for draw in draws:
        assert tuple(draw) == table.names()
    for name, (low, high) in zip(table.names(), table.bounds(), strict=True):
        values = np.array([draw[name] for draw in draws])
        assert float(values.min()) >= low
        assert float(values.max()) <= high
        # Empirical support should approach the declared support, not sit on the central value.
        assert float(values.min()) < low + 0.02 * (high - low)
        assert float(values.max()) > high - 0.02 * (high - low)


def test_a_card_without_a_range_cannot_be_calibrated(cards: ParameterCards) -> None:
    for parameter_set, name in (
        ("CropParameters", "yield_loss_scale"),
        ("EliteParameters", "interest_rate_monthly"),
    ):
        original = cards.require(parameter_set, name)
        unbound = original.model_copy(update={"range": None})
        with pytest.raises(PriorError, match=name):
            build_priors(_replacing(cards, original, unbound))


def test_a_missing_card_cannot_be_calibrated(cards: ParameterCards) -> None:
    with pytest.raises(PriorError, match="assessed_value_tael_per_mu"):
        build_priors(_without(cards, "FiscalParameters", "assessed_value_tael_per_mu"))


def test_a_card_filed_under_another_set_cannot_be_calibrated(cards: ParameterCards) -> None:
    original = cards.require("MigrationParameters", "permanent_share_of_households_per_month")
    moved = original.model_copy(update={"parameter_set": "HouseholdParameters"})

    with pytest.raises(PriorError, match="permanent_share_of_households_per_month"):
        build_priors(_replacing(cards, original, moved))


def test_card_free_parameters_are_the_unbounded_cards(cards: ParameterCards) -> None:
    free = card_free_parameters(cards)

    assert free == tuple(sorted(card.id for card in cards if card.range is None))
    assert free
    assert "yield_loss_scale" not in free
    assert not set(free) & set(UNADJUSTED_NAMES)


def test_excluded_parameters_are_the_rules_not_taken(cards: ParameterCards) -> None:
    excluded = excluded_parameters(cards)

    assert tuple(name for name, _ in excluded) == UNADJUSTED_NAMES
    for name, reason in excluded:
        assert reason
        card = next(card for card in cards if card.id == name)
        assert card.range is not None


def test_the_registry_records_a_central_outside_its_own_range_where_it_does(
    cards: ParameterCards,
) -> None:
    """The prior is the band, so a default outside the band is reported, never widened away.

    The finding is computed from the registry rather than listed here; the assertion pins the
    registry's current state, so an edit to the band or to the value in use surfaces as a change to
    this finding instead of passing unnoticed.
    """
    findings = centres_outside_range(cards)

    assert tuple(name for name, _ in findings) == ("interest_rate_monthly",)
    assert "below its own range" in findings[0][1]
    table = build_priors(cards)
    prior = table.by_name("interest_rate_monthly")
    assert prior.central is not None
    assert not table.contains("interest_rate_monthly", prior.central)
