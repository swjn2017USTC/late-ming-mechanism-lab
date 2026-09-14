"""A seeded control: a uniform draw over whatever actions the actor is allowed.

A declared rule can only be read against a floor that has no rule at all, and this is that floor.
It never looks at the readings, so a difference between it and a declared policy is a difference the
decision rule made rather than one the observation forced — useful as a control, never as a claim
about what an actor would have done.

The draw is derived from the declared seed and the exact situation (the observation and the action
space it was handed) instead of being carried in a generator between calls. A control has to be
replayable from its inputs: two runs that reach the same observation must draw the same action,
whatever else happened in between.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

import numpy as np

from late_ming_lab.core.hashing import canonical_json, hash_text
from late_ming_lab.policies.base import (
    DecisionRejectedError,
    InstitutionalAction,
    InstitutionalDecision,
    PolicyObservation,
    Priority,
)

#: The priority recorded for an action. The column says what the actor says it is optimizing, and
#: this control has no objective of its own, so it records the action's declared priority instead of
#: claiming one: a trace from a control then reads like a trace from any other policy.
_PRIORITY_BY_ACTION: Final[Mapping[InstitutionalAction, Priority]] = {
    InstitutionalAction.RELAX_EXTRACTION: Priority.STABILIZE_TAX_BASE,
    InstitutionalAction.INTENSIFY_EXTRACTION: Priority.PRESERVE_ORDER,
    InstitutionalAction.RELIEF_TRANSFER: Priority.RELIEVE_DISTRESS,
}


class RandomPolicy:
    """A seeded uniform choice over the allowed actions; useful as a control, never as a claim."""

    name = "random-v1"

    def __init__(self, *, seed: int) -> None:
        self._seed = seed

    def choose_action(
        self,
        observation: PolicyObservation,
        action_space: Sequence[InstitutionalAction],
    ) -> InstitutionalDecision:
        """Draw one action uniformly from the space, and an intensity uniformly in ``[0, 1]``.

        ``MAINTAIN`` is drawn at zero intensity: an actor that maintains is spending nothing, and a
        control must not record effort the action does not spend.
        """
        space = _require_space(action_space)
        generator = np.random.default_rng(_situation_seed(self._seed, observation, space))
        action = space[int(generator.integers(len(space)))]
        intensity = 0.0 if action is InstitutionalAction.MAINTAIN else float(generator.random())
        rationale = (
            f"{self.name}: seed {self._seed} drew {action.value} "
            f"from {len(space)} available actions"
        )
        return _decision(action, intensity, rationale)


def _situation_seed(
    seed: int,
    observation: PolicyObservation,
    action_space: Sequence[InstitutionalAction],
) -> int:
    """The declared seed, mixed with the situation the draw is for.

    The tick is part of the situation on purpose: an actor whose readings have not moved between
    two ticks should still draw again, or the control would freeze on one action for a whole run.
    """
    situation = {
        "seed": seed,
        "tick": observation.tick,
        "observation": observation.payload(),
        "action_space": [action.value for action in action_space],
    }
    return int(hash_text(canonical_json(situation)), 16)


def _require_space(action_space: Sequence[InstitutionalAction]) -> Sequence[InstitutionalAction]:
    """Refuse an empty space: there is no action to draw, and no decision to invent."""
    if not action_space:
        raise DecisionRejectedError("the action space is empty; there is no action to choose")
    return action_space


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
