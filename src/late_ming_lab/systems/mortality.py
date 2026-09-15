"""M006: the interface a mortality rule would have to satisfy, and nothing that pretends to be one.

The V1 card is `UNIDENTIFIED` and says why in its own words: the model has no mortality clock, no
arm can bind, and no artifact in the project reports the population decline the mechanism would
explain. Adding a rule that removes members on a sustained shortfall would be easy and would be
invention: the evidence the project holds supports a *direction* (population fell across the
transition, with famine among the causes — a grade-C claim that supports no parameter) and no
county-resolution mortality series whatever, and the famine cluster's own note says so.

So this module delivers what the phase's acceptance allows and nothing more:

```text
MortalityRule          the interface: what a rule would be handed and what it would return
NoMortality            the model's actual behaviour today: no member of any cohort dies
ShortfallObservable    the quantities a rule would consume, recomputed from a run by analysis
mortality_rule()       refuses to build anything but NoMortality from the evidence on hand
apply()                refuses a rule that returns deaths, because nothing can carry them
```

`NoMortality` is **not an ablation**. The card's own argument for M006 cites the `NO_BAND_MERGER`
precedent: an arm whose intervention cannot bind measures the absence of a rule, not its effect, and
calling it a control would be a category error. The gap report says what would have to exist first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol

#: What the model's population layer can carry today.
RULE_VERSION_NO_MORTALITY: Final[str] = "mortality-none-v1"


class MortalityEvidenceGap(ValueError):
    """Raised when a mortality rule is asked for and the evidence does not support one."""


@dataclass(frozen=True, slots=True)
class ShortfallObservable:
    """What a mortality rule would be handed, per cohort-month.

    Every field is a quantity the model already measures: the months a cohort has spent below its
    subsistence floor, its rolling unmet ratio, its size in households and adults, its land per
    household, and how far below the floor the last month fell. A rule that wanted something else
    would have to say so, and that would be the finding.
    """

    months_below_subsistence: int
    unmet_ratio_rolling: float
    households: float
    adults: float
    land_per_household_mu: float
    last_shortfall_shi: float

    def __post_init__(self) -> None:
        if self.months_below_subsistence < 0:
            raise ValueError("months below subsistence cannot be negative")
        if not 0.0 <= self.unmet_ratio_rolling <= 1.0:
            raise ValueError("a rolling unmet ratio lies in [0, 1]")
        if self.households < 0.0 or self.adults < 0.0:
            raise ValueError("a cohort cannot have a negative size")


class MortalityRule(Protocol):
    """A rule that would say how many members a cohort loses to hunger in one month."""

    @property
    def rule_version(self) -> str: ...

    def deaths(self, *, observable: ShortfallObservable, rule_version_ref: str) -> float: ...


@dataclass(frozen=True, slots=True)
class NoMortality:
    """The model as it stands: no member of any cohort dies, whatever the shortfall.

    This is the V1 behaviour, stated rather than implied. A rule replacing it must arrive with a
    structure and a range, and `mortality_rule_from_evidence` is what refuses one that does not.
    """

    rule_version: str = RULE_VERSION_NO_MORTALITY

    def deaths(self, *, observable: ShortfallObservable, rule_version_ref: str) -> float:
        """Zero, for every cohort and every month — and it consumes nothing to decide that."""
        return 0.0


def mortality_rule_from_evidence(*, claims: dict[str, str] | None = None) -> MortalityRule:
    """Refuse to build a mortality rule: the project's evidence does not support one.

    The check is not decorative. It reads the two claims the registry actually holds —
    `pop-ming-qing-decline`, which is grade C, asserts a direction and supports no parameter, and
    the famine cluster's own note, that no source in the registry measures a mortality or unmet-need
    series at county resolution — and refuses when the caller has nothing to add. A later phase that
    acquires a series with a level and a range changes this function's answer by giving it a claim
    to read, not by deleting the check.
    """
    if claims:
        missing = [
            name
            for name, strength in sorted(claims.items())
            if strength not in ("level", "rate", "range")
        ]
        named = ", ".join(missing)
        raise MortalityEvidenceGap(
            f"a mortality rule needs a claim carrying a level, a rate or a range; {named} carries "
            "a direction only, and a rate cannot be read from a direction"
        )
    raise MortalityEvidenceGap(
        "no claim in the registry carries a mortality level, rate or range, and none carries a "
        "county-resolution mortality or unmet-need series: M006 stays UNIDENTIFIED and the model "
        "keeps the rule it has, which is that nobody dies"
    )


def apply(rule: MortalityRule, observable: ShortfallObservable, *, rule_version_ref: str) -> float:
    """Ask a rule for its deaths, refusing any answer the population layer cannot carry.

    The refusal is the point: `HouseholdCohortAgent` has no transition that removes members without
    sending them somewhere (an army, a band, a destination), so a rule returning deaths would either
    be dropped silently or would have to be implemented as a departure — the wrong mechanism wearing
    the right name. Until a death transition exists on evidence, this raises.
    """
    deaths = rule.deaths(observable=observable, rule_version_ref=rule_version_ref)
    if deaths != 0.0:
        raise MortalityEvidenceGap(
            f"{rule.rule_version} returns {deaths} deaths, and no transition in this model can "
            "carry them: mortality is a structure decision the evidence has not supported yet"
        )
    return deaths


__all__ = [
    "RULE_VERSION_NO_MORTALITY",
    "MortalityEvidenceGap",
    "MortalityRule",
    "NoMortality",
    "ShortfallObservable",
    "apply",
    "mortality_rule_from_evidence",
]
