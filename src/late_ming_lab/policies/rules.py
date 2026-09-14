"""Declared threshold rules: the reading that crosses a line picks the action.

A declared policy exists so that a decision layer can be argued with. Nothing here is fitted and
nothing is searched: the table below *is* the policy, every number in it is a declaration someone
can point at, and a run using it is replayable from the table and the observation alone. That is
what the project needs before it can ask anything about institutions — a floor of declared
behaviour the runtime model can be compared against, and a decision source that works with no
network at all.

The rule table, in priority order. A row fires when its reading has crossed its line; the first row
that fires decides, and the response is ``scale`` per unit past the line, capped at ``cap``, so the
reading exactly at the line picks the action at zero intensity and the response grows from there.
A row marked ``*`` fires only when its action is in the action space the policy was handed.

| # | fires when | action | response | capped at |
|---|------------|--------|----------|-----------|
| 1 | ``tax_arrears_months >= 6.0`` | ``RELAX_EXTRACTION`` | 0.10 per month past | 0.60 |
| 1 | ``receipts_over_quota <= 0.30`` | ``RELAX_EXTRACTION`` | 2.00 per unit below | 0.60 |
| 2* | ``unmet_need_share >= 0.35`` | ``RELIEF_TRANSFER`` | 2.00 per unit past | 0.80 |
| 3* | ``armed_share_of_adults >= 0.02`` | ``INTENSIFY_EXTRACTION`` | 10.0 per unit past | 0.50 |
| 4 | ``out_migration_share >= 0.05`` | ``RELAX_EXTRACTION`` | 5.00 per unit past | 0.60 |
| — | nothing crossed | ``MAINTAIN`` | — | 0.00 |

The priority a row records is read off the action it picks: ``RELIEF_TRANSFER`` says
``RELIEVE_DISTRESS``, ``INTENSIFY_EXTRACTION`` says ``PRESERVE_ORDER``, ``RELAX_EXTRACTION`` says
``STABILIZE_TAX_BASE``, and anything else says ``MAINTAIN``.

Rows 2 and 3 are gated on their own action being available, so an actor that cannot relieve
distress falls through to a rule it *can* act on. Rows 1 and 4 are not gated: they name the action
they want, and an actor that cannot do the indicated thing maintains rather than doing something
else instead. A reading the observation does not carry cannot cross a line, so its row is skipped,
and an observation with no readable measure maintains at zero intensity.

``largest_band_share`` is a reading this table does not use. Consolidation is something the rules
react to through the migration and arms readings; a row keyed on it would be asserting a mechanism
the project has not measured.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from late_ming_lab.policies.base import (
    MAX_RATIONALE_CHARS,
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


class _Comparison(StrEnum):
    """Which side of its line counts as crossing it."""

    AT_LEAST = ">="
    AT_MOST = "<="


@dataclass(frozen=True, slots=True)
class _Rule:
    """One row of the table: a reading, the line it crosses, and what crossing it picks."""

    measure: str
    comparison: _Comparison
    line: float
    action: InstitutionalAction
    scale: float
    cap: float
    needs_action_available: bool = False

    def distance_past(self, reading: float) -> float | None:
        """How far the reading is past the line, or ``None`` while it has not crossed it."""
        if self.comparison is _Comparison.AT_LEAST:
            return reading - self.line if reading >= self.line else None
        return self.line - reading if reading <= self.line else None


#: The table itself, in priority order: the first row whose reading has crossed its line decides.
_RULES: Final[tuple[_Rule, ...]] = (
    _Rule(
        measure="tax_arrears_months",
        comparison=_Comparison.AT_LEAST,
        line=6.0,
        action=InstitutionalAction.RELAX_EXTRACTION,
        scale=0.10,
        cap=0.60,
    ),
    _Rule(
        measure="receipts_over_quota",
        comparison=_Comparison.AT_MOST,
        line=0.30,
        action=InstitutionalAction.RELAX_EXTRACTION,
        scale=2.00,
        cap=0.60,
    ),
    _Rule(
        measure="unmet_need_share",
        comparison=_Comparison.AT_LEAST,
        line=0.35,
        action=InstitutionalAction.RELIEF_TRANSFER,
        scale=2.00,
        cap=0.80,
        needs_action_available=True,
    ),
    _Rule(
        measure="armed_share_of_adults",
        comparison=_Comparison.AT_LEAST,
        line=0.02,
        action=InstitutionalAction.INTENSIFY_EXTRACTION,
        scale=10.0,
        cap=0.50,
        needs_action_available=True,
    ),
    _Rule(
        measure="out_migration_share",
        comparison=_Comparison.AT_LEAST,
        line=0.05,
        action=InstitutionalAction.RELAX_EXTRACTION,
        scale=5.00,
        cap=0.60,
    ),
)


class RulePolicy:
    """A declared threshold table: the reading that crosses a line picks the action.

    Every rule is printed in the module docstring as a table so a reader can see the policy without
    reading code, and the rationale quotes the rule that fired. No rule looks at anything but the
    observation's own measures: the action space decides what is *possible*, never what is chosen.
    """

    name = "rule-v1"

    def __init__(self, *, rationale_prefix: str = "rule") -> None:
        self._prefix = rationale_prefix

    def choose_action(
        self,
        observation: PolicyObservation,
        action_space: Sequence[InstitutionalAction],
    ) -> InstitutionalDecision:
        """Choose the action of the first rule whose reading has crossed its line."""
        space = _require_space(action_space)
        readings = observation.measure_map()
        for rule in _RULES:
            reading = readings.get(rule.measure)
            if reading is None:
                continue
            distance = rule.distance_past(reading)
            if distance is None:
                continue
            if rule.needs_action_available and rule.action not in space:
                continue
            fired = (
                f"rule {rule.measure} {rule.comparison.value} {rule.line:g} fired at {reading:g}"
            )
            if rule.action in space:
                intensity = min(rule.cap, rule.scale * distance)
                return _decision(
                    rule.action,
                    intensity,
                    _rationale(
                        self._prefix, f"{fired}, choosing {rule.action.value} at {intensity:.2f}"
                    ),
                )
            return _decision(
                _maintain_or_first(space),
                0.0,
                _rationale(
                    self._prefix,
                    f"{fired} but {rule.action.value} is not in this action space, standing down",
                ),
            )
        action = _maintain_or_first(space)
        note = (
            "maintaining" if action is InstitutionalAction.MAINTAIN else f"holding {action.value}"
        )
        return _decision(action, 0.0, _rationale(self._prefix, f"no rule fired, {note}"))


def _require_space(action_space: Sequence[InstitutionalAction]) -> Sequence[InstitutionalAction]:
    """Refuse an empty space: there is no action to choose, and no decision to invent."""
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


def _rationale(prefix: str, sentence: str) -> str:
    """One sentence, never longer than the decision schema accepts.

    The sentence is the policy's own text and is kept whole; the prefix is the caller's tag, so the
    prefix is what gets clipped when the two do not fit together.
    """
    separator = ": " if prefix else ""
    room = MAX_RATIONALE_CHARS - len(sentence) - len(separator)
    if room <= 0:
        return sentence[:MAX_RATIONALE_CHARS]
    return f"{prefix[:room]}{separator}{sentence}"
