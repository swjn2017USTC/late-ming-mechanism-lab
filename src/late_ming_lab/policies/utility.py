"""A bounded linear objective over the observed readings: declared weights, scored actions.

A threshold table answers "which line did this reading cross?" and says nothing about how two bad
readings trade off. This policy states that trade-off instead: every reading carries a declared
weight, every action a declared direction of effect on it, and the policy scores each action in the
space it was handed and takes the best one. Nothing is fitted and nothing is hidden — a reader can
recompute any decision from the two tables in this module, and a run using it is reproducible from
the observation it was given.

The objective is a *distress* objective: each reading is declared to be a bad thing when high, so
an action's score is the distress it is declared to remove, weighted by how large each reading
currently is. ``MAINTAIN`` is declared to move nothing, so it scores zero and an action is chosen
only when it improves something the observation is actually reporting.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from late_ming_lab.policies.base import (
    DecisionRejectedError,
    InstitutionalAction,
    InstitutionalDecision,
    PolicyObservation,
    Priority,
)

#: The priority recorded for an action. The column says what the actor says it is optimizing, so an
#: action this policy has no objective for is recorded as ``MAINTAIN`` rather than given one.
_PRIORITY_BY_ACTION: Final[Mapping[InstitutionalAction, Priority]] = {
    InstitutionalAction.RELAX_EXTRACTION: Priority.STABILIZE_TAX_BASE,
    InstitutionalAction.INTENSIFY_EXTRACTION: Priority.PRESERVE_ORDER,
    InstitutionalAction.RELIEF_TRANSFER: Priority.RELIEVE_DISTRESS,
}

#: The declared weights. These are equal because the readings arrive in their own units — months and
#: shares are not commensurate, and the exchange rate between them is a judgement this policy will
#: not smuggle in: a caller that has one passes its own mapping, which overrides the declaration for
#: the readings it names. A caller's mapping may name readings no action declares an effect on; they
#: are carried and never used.
DEFAULT_WEIGHTS: Final[Mapping[str, float]] = {
    "tax_arrears_months": 1.0,
    "receipts_over_quota": 1.0,
    "unmet_need_share": 1.0,
    "armed_share_of_adults": 1.0,
    "out_migration_share": 1.0,
    "largest_band_share": 1.0,
}

#: What each action is declared to do to each reading: ``+1`` raises it, ``-1`` lowers it and ``0``
#: leaves it alone. Declared, never estimated — this is the objective the policy *states*, not a
#: result, and the phase that would test whether these directions hold is a later one.
ACTION_EFFECTS: Final[Mapping[InstitutionalAction, Mapping[str, float]]] = {
    InstitutionalAction.MAINTAIN: {
        "tax_arrears_months": 0.0,
        "receipts_over_quota": 0.0,
        "unmet_need_share": 0.0,
        "armed_share_of_adults": 0.0,
        "out_migration_share": 0.0,
        "largest_band_share": 0.0,
    },
    InstitutionalAction.RELAX_EXTRACTION: {
        "tax_arrears_months": 1.0,
        "receipts_over_quota": -1.0,
        "unmet_need_share": -1.0,
        "armed_share_of_adults": 0.0,
        "out_migration_share": -1.0,
        "largest_band_share": 0.0,
    },
    InstitutionalAction.INTENSIFY_EXTRACTION: {
        "tax_arrears_months": -1.0,
        "receipts_over_quota": 1.0,
        "unmet_need_share": 1.0,
        "armed_share_of_adults": -1.0,
        "out_migration_share": 1.0,
        "largest_band_share": -1.0,
    },
    InstitutionalAction.RELIEF_TRANSFER: {
        "tax_arrears_months": 0.0,
        "receipts_over_quota": 0.0,
        "unmet_need_share": -1.0,
        "armed_share_of_adults": -1.0,
        "out_migration_share": -1.0,
        "largest_band_share": -1.0,
    },
    InstitutionalAction.BLOCK_LINK: {
        "tax_arrears_months": 0.0,
        "receipts_over_quota": 0.0,
        "unmet_need_share": 1.0,
        "armed_share_of_adults": 0.0,
        "out_migration_share": 1.0,
        "largest_band_share": -1.0,
    },
    InstitutionalAction.REOPEN_LINK: {
        "tax_arrears_months": 0.0,
        "receipts_over_quota": 0.0,
        "unmet_need_share": -1.0,
        "armed_share_of_adults": 0.0,
        "out_migration_share": -1.0,
        "largest_band_share": 1.0,
    },
}


class UtilityPolicy:
    """A bounded linear objective over the observed readings, with declared weights.

    Each candidate action has a declared effect direction on each measure; the policy scores every
    action in the space it was given and returns the best, ties broken by the action-space order so
    the policy is deterministic. The rationale names the measure that decided it. The intensity is
    the winning score clipped to ``[0, 1]``: an actor cannot ask for more than full effort, and a
    score at or below zero leaves the actor maintaining.
    """

    name = "utility-v1"

    def __init__(self, *, weights: Mapping[str, float] | None = None) -> None:
        self._weights: Mapping[str, float] = {**DEFAULT_WEIGHTS, **(weights or {})}

    def choose_action(
        self,
        observation: PolicyObservation,
        action_space: Sequence[InstitutionalAction],
    ) -> InstitutionalDecision:
        """Choose the action with the largest declared gain, breaking ties in the space's order."""
        space = _require_space(action_space)
        readings = observation.measure_map()
        action = space[0]
        score, driver = self._score(action, readings)
        for candidate in space[1:]:
            candidate_score, candidate_driver = self._score(candidate, readings)
            if candidate_score > score:
                action, score, driver = candidate, candidate_score, candidate_driver
        if score <= 0.0:
            chosen = _maintain_or_first(space)
            note = (
                "maintaining"
                if chosen is InstitutionalAction.MAINTAIN
                else f"holding {chosen.value}"
            )
            return _decision(
                chosen,
                0.0,
                f"{self.name}: no available action lowers the weighted readings, {note}",
            )
        term = f"{driver}={readings[driver]:g}" if driver else "no single reading"
        return _decision(
            action,
            min(1.0, score),
            f"{self.name}: {term} is what favours {action.value} (objective {score:.3f})",
        )

    def _score(
        self, action: InstitutionalAction, readings: Mapping[str, float]
    ) -> tuple[float, str | None]:
        """The distress this action is declared to remove, and the reading that contributes most."""
        total = 0.0
        driver: str | None = None
        largest = 0.0
        for measure, effect in ACTION_EFFECTS[action].items():
            reading = readings.get(measure)
            if reading is None:
                continue
            contribution = -effect * self._weights.get(measure, 0.0) * reading
            total += contribution
            if abs(contribution) > largest:
                largest = abs(contribution)
                driver = measure
        return total, driver


def _require_space(action_space: Sequence[InstitutionalAction]) -> Sequence[InstitutionalAction]:
    """Refuse an empty space: there is no action to score, and no decision to invent."""
    if not action_space:
        raise DecisionRejectedError("the action space is empty; there is no action to choose")
    return action_space


def _maintain_or_first(action_space: Sequence[InstitutionalAction]) -> InstitutionalAction:
    """``MAINTAIN`` when the space allows it, otherwise the space's first action."""
    if InstitutionalAction.MAINTAIN in action_space:
        return InstitutionalAction.MAINTAIN
    return action_space[0]


def _decision(
    action: InstitutionalAction, intensity: float, rationale: str
) -> InstitutionalDecision:
    """Build the decision, with the priority its action declares."""
    return InstitutionalDecision(
        action=action,
        intensity=intensity,
        priority=_PRIORITY_BY_ACTION.get(action, Priority.MAINTAIN),
        rationale=rationale,
    )
