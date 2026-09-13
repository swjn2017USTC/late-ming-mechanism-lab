"""Priors for P09 calibration: the P08 card range, and nothing put beside it.

A calibration has to draw parameter sets from somewhere, and this phase's rule is that the
*somewhere* is already recorded. A prior exists for a parameter exactly when its P08 card carries
a numeric range, and that range **is** the prior's support. Nothing here widens a bound to let a
draw reach a value the modeller would like, and nothing narrows one to hide a region the model
does badly in: no bound is invented in this module, so a prior cannot smuggle in a fitted number.

Every prior is uniform on its card range. That is not a modelling convenience. The card states a
range and a value in use; a uniform over the range is the only distribution that adds no
information about where inside the band the truth sits. A per-parameter shape — a beta, a
log-normal — would be a fresh claim with no evidence behind it, and this phase is not allowed to
make one, so the module has no scale or shape field to configure. A later phase that wants another
family must bring the evidence for it, not a configuration key.

Two groups of range-carrying cards are deliberately *not* calibrated, and both are reported rather
than quietly dropped. :func:`excluded_parameters` names them with the rule that excludes them: one
dict-valued card that no single draw could set, and two medium-priority cards that no target
pattern's checks reach. :func:`card_free_parameters` lists every card with no range at all, read
from the registry so a bound cannot appear by accident.

The declaration order in :data:`DECLARED` fixes the table's order. A sampler moves parameters as a
vector, so their order is part of the run's provenance; a reordering is a change to the run, not
to its presentation.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

import numpy as np

from late_ming_lab.evidence.cards import ParameterCards


class PriorError(ValueError):
    """Raised when a prior cannot be declared from the P08 parameter cards."""


@dataclass(frozen=True, slots=True)
class ParameterPrior:
    """One calibration parameter: its card range as support, and the pattern that needs it."""

    name: str
    """The field name exactly as the parameter set declares it."""

    parameter_set: str
    """The parameter set class the field belongs to, e.g. ``HouseholdParameters``."""

    card_id: str
    """The P08 card id. Equal to :attr:`name` in every card today; checked, not assumed."""

    low: float
    """The card's lower bound — the prior's lower support, unadjusted."""

    high: float
    """The card's upper bound — the prior's upper support, unadjusted."""

    central: float | None
    """The value in use when the card records one; ``None`` when it records a mapping instead."""

    support_class: str
    """The card's support class, so a report can separate assumption from evidence."""

    evidence_grade: str
    """The card's evidence grade, carried through for the same reason."""

    reason: str
    """Which target pattern's checks reach this parameter."""


#: The calibration declarations, in table order: ``(name, parameter_set, reason)``. Each reason
#: names the target pattern the parameter serves, because a parameter no target check reaches
#: cannot be calibrated — it can only be believed. The set is deliberately smaller than the
#: registry: :data:`EXCLUDED` records the range-carrying cards that are not here, and
#: :func:`card_free_parameters` the ones the registry does not bound at all.
DECLARED: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "yield_loss_scale",
        "CropParameters",
        "famine-local-price-extremes / land-abandonment-in-famine: climate damage scales the "
        "yield loss that drives both.",
    ),
    (
        "subsistence_grain_per_adult_month_shi",
        "HouseholdParameters",
        "absorption-of-deserters-and-refugees / debt-transfers-land: the subsistence floor sets "
        "distress.",
    ),
    (
        "permanent_migration_unmet_ratio",
        "HouseholdParameters",
        "land-abandonment-in-famine: the distress line that lets a household leave.",
    ),
    (
        "temporary_migration_unmet_ratio",
        "HouseholdParameters",
        "land-abandonment-in-famine: the same line for a season's absence.",
    ),
    (
        "interest_rate_monthly",
        "EliteParameters",
        "debt-transfers-land: the credit price that moves land to creditors.",
    ),
    (
        "assessed_value_tael_per_mu",
        "FiscalParameters",
        "receipts-shortfall-chronic: the assessed value sets the quota receipts fall short of.",
    ),
    (
        "elite_hidden_land_share",
        "FiscalParameters",
        "receipts-shortfall-chronic / land-abandonment-in-famine: hidden land shrinks the "
        "visible base.",
    ),
    (
        "reference_price_tael_per_shi",
        "MarketParameters",
        "famine-local-price-extremes: the external price that the local posted price is "
        "dispersed around.",
    ),
    (
        "permanent_share_of_households_per_month",
        "MigrationParameters",
        "land-abandonment-in-famine: the departure rate that abandons land.",
    ),
    (
        "temporary_share_of_adults_per_month",
        "MigrationParameters",
        "land-abandonment-in-famine: the seasonal rate that removes labour.",
    ),
    (
        "pay_tael_per_soldier_month",
        "MilitaryParameters",
        "absorption-of-deserters-and-refugees: pay arrears drive desertion, the bands' intake.",
    ),
    (
        "food_shi_per_soldier_month",
        "MilitaryParameters",
        "absorption-of-deserters-and-refugees: garrison rations are the other route to desertion.",
    ),
    (
        "food_shi_per_member_month",
        "BandParameters",
        "absorption-of-deserters-and-refugees: a band that cannot feed members cannot absorb them.",
    ),
)

#: Range-carrying cards that are deliberately not calibrated, as ``(name, parameter_set, reason)``.
#: Each is a decision, not an oversight, and the reason is the rule that makes it: a draw sets a
#: scalar, and a target check has to reach the parameter for its value to matter.
EXCLUDED: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "yield_shi_per_mu",
        "CropParameters",
        "the card is dict-valued, one baseline per agrarian zone, so no single draw can set it.",
    ),
    (
        "rent_share_of_harvest",
        "HouseholdParameters",
        "the card declares one range but the field in use is dict-valued, one share per cohort "
        "class: a scalar draw would not be the value the model runs, so the card's band documents "
        "the shares rather than bounds a draw.",
    ),
    (
        "land_per_adult_capacity_mu",
        "CropParameters",
        "the card's sensitivity_priority is medium and no target pattern's checks reach the "
        "labour market.",
    ),
    (
        "wage_grain_shi_per_adult_month",
        "HouseholdParameters",
        "the card's sensitivity_priority is medium and no target check reaches the wage.",
    ),
)


@dataclass(frozen=True, slots=True)
class PriorTable:
    """The declared priors in fixed order, plus the lookups and draws a sampler needs."""

    priors: tuple[ParameterPrior, ...]

    def __iter__(self) -> Iterator[ParameterPrior]:
        return iter(self.priors)

    def __len__(self) -> int:
        return len(self.priors)

    def names(self) -> tuple[str, ...]:
        return tuple(prior.name for prior in self.priors)

    def bounds(self) -> tuple[tuple[float, float], ...]:
        """The supports, aligned with :meth:`names`."""
        return tuple((prior.low, prior.high) for prior in self.priors)

    def by_name(self, name: str) -> ParameterPrior:
        for prior in self.priors:
            if prior.name == name:
                return prior
        raise PriorError(f"{name!r} is not a calibrated parameter")

    def contains(self, name: str, value: float) -> bool:
        """Whether ``value`` lies inside the named parameter's card range."""
        prior = self.by_name(name)
        return prior.low <= value <= prior.high

    def sample(self, rng: np.random.Generator) -> dict[str, float]:
        """One draw per parameter: uniform on the card range, in table order."""
        return {prior.name: float(rng.uniform(prior.low, prior.high)) for prior in self.priors}

    def centre(self) -> dict[str, float]:
        """The card central of every parameter; fails closed if any card records none."""
        centres: dict[str, float] = {}
        for prior in self.priors:
            if prior.central is None:
                raise PriorError(
                    f"{prior.name}: its P08 card records no central value, so the table has no "
                    "centre; read the cards directly rather than inventing one"
                )
            centres[prior.name] = prior.central
        return centres


def build_priors(cards: ParameterCards) -> PriorTable:
    """Declare the calibration priors, or refuse because the registry does not bound one.

    The support is exactly the card range: a card with no bounded range, a missing card, an
    unordered range, a card filed under another set or under another id all fail here. That is
    the phase's whole safeguard — a bound cannot enter calibration except through the evidence
    registry, where a reviewer can see it.
    """
    priors: list[ParameterPrior] = []
    for name, parameter_set, reason in DECLARED:
        card = cards.get(parameter_set, name)
        if card is None:
            moved = tuple(existing for existing in cards if existing.id == name)
            if moved:
                raise PriorError(
                    f"{name}: its P08 card is filed under {moved[0].parameter_set!r}, but the "
                    f"prior declaration names {parameter_set!r}"
                )
            raise PriorError(f"no P08 card for {parameter_set}.{name}, so it cannot be calibrated")
        # The index keys on (set, id); these two checks state the invariant rather than assume it.
        if card.parameter_set != parameter_set:
            raise PriorError(
                f"{name}: its P08 card declares the set {card.parameter_set!r}, but the prior "
                f"declaration names {parameter_set!r}"
            )
        if card.id != name:
            raise PriorError(
                f"{parameter_set}.{name}: the P08 card's id is {card.id!r}, not the field name"
            )
        card_range = card.range
        if card_range is None or card_range.low is None or card_range.high is None:
            raise PriorError(
                f"{parameter_set}.{name}: its P08 card declares no bounded range, so there is "
                "nothing to calibrate against"
            )
        low, high = card_range.low, card_range.high
        if low >= high:
            raise PriorError(
                f"{parameter_set}.{name}: the card range [{low:g}, {high:g}] is not a support"
            )
        priors.append(
            ParameterPrior(
                name=name,
                parameter_set=parameter_set,
                card_id=card.id,
                low=low,
                high=high,
                central=card.central,
                support_class=card.support_class.value,
                evidence_grade=card.evidence_grade.value,
                reason=reason,
            )
        )
    return PriorTable(tuple(priors))


def excluded_parameters(cards: ParameterCards) -> tuple[tuple[str, str], ...]:
    """The range-carrying cards deliberately left out of calibration, as ``(name, reason)``.

    The registry is asked for each one so that an exclusion cannot outlive the card that
    justified it: a name here whose card has lost its range is an error, not a stale note.
    """
    excluded: list[tuple[str, str]] = []
    for name, parameter_set, reason in EXCLUDED:
        card = cards.get(parameter_set, name)
        if card is None:
            raise PriorError(f"no P08 card for {parameter_set}.{name}, which is listed as excluded")
        card_range = card.range
        if card_range is None or card_range.low is None or card_range.high is None:
            raise PriorError(
                f"{parameter_set}.{name}: it is listed as excluded as a choice, but its card "
                "carries no range to choose against"
            )
        excluded.append((name, reason))
    return tuple(excluded)


def card_free_parameters(cards: ParameterCards) -> tuple[str, ...]:
    """Every card id with no range, sorted — the parameters the registry does not bound."""
    return tuple(sorted(card.id for card in cards if card.range is None))


def centres_outside_range(cards: ParameterCards) -> tuple[tuple[str, str], ...]:
    """Calibrated parameters whose card records a value in use outside its own range.

    A card states a band and the value the model runs. When the second sits outside the first, the
    prior — which is the band, unadjusted — will not contain the model's current default. That is a
    property of the evidence registry, not something this phase may paper over by widening the band
    to reach the default, so it is reported here and recorded in the calibration report.
    """
    findings: list[tuple[str, str]] = []
    for name, parameter_set, _ in DECLARED:
        card = cards.get(parameter_set, name)
        if card is None or card.range is None or card.central is None:
            continue
        low, high = card.range.low, card.range.high
        if low is None or high is None:
            continue
        if not low <= card.central <= high:
            side = "below" if card.central < low else "above"
            findings.append(
                (
                    name,
                    f"the card records {card.central:g}, {side} its own range [{low:g}, {high:g}]",
                )
            )
    return tuple(findings)
