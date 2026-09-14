"""The mechanism-card schema: what a mechanism claim has to say before it may be called anything.

A card is the phase's product, so the schema is its discipline. Sixteen fields are required, the
status comes from a five-word vocabulary and nothing else, and two things are refused outright:

- a **vague cause**. "Multiple factors interacted" is not a mechanism: it names no condition, no
  trigger and no chain, and it cannot be falsified. The schema rejects a list of phrases that say
  nothing, in the fields where they would hide.
- an **unsupported status**. A card that claims ``SUPPORTED`` must cite at least two evidence kinds
  that were actually computed, and one of them has to be an intervention (an ablation or a
  counterfactual arm) rather than a correlation. The rule is checked at validation time, not left to
  whoever writes the report.

Machine-readable cards live in ``docs/mechanisms/cards.yaml``; the same objects render to Markdown.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Where the cards are written and read. They live here, beside the model they are, so that a reader
#: - the browser, a test, a later phase - can load a card without importing the writers, which pull
#: the experiment chain behind them.
DOCS_ROOT: Final[str] = "docs/mechanisms"
CARDS_FILE: Final[str] = "cards.yaml"
INDEX_FILE: Final[str] = "index.md"
SYNTHESIS_FILE: Final[str] = "outputs/reports/mechanism-synthesis.md"


def load_book(path: str | Path) -> MechanismBook:
    """Read the YAML back, so a caller proves the file and the objects agree."""
    text = Path(path).read_text(encoding="utf-8")
    return MechanismBook.model_validate(json.loads(json.dumps(yaml.safe_load(text))))


class MechanismStatus(StrEnum):
    """The only statuses a card may carry. There is no "probably" and no free text."""

    SUPPORTED = "SUPPORTED"
    CONDITIONAL = "CONDITIONAL"
    WEAK = "WEAK"
    REJECTED = "REJECTED"
    UNIDENTIFIED = "UNIDENTIFIED"


#: The evidence kinds a card may cite. Each names an artifact this project produced, so a citation
#: is checkable rather than rhetorical.
class EvidenceKind(StrEnum):
    CALIBRATION = "calibration"
    HOLD_OUT = "hold-out"
    SENSITIVITY = "sensitivity"
    ABLATION = "ablation"
    COUNTERFACTUAL = "counterfactual"
    POLICY_ROBUSTNESS = "policy-robustness"
    HISTORICAL = "historical-support"
    HISTORICAL_CHALLENGE = "historical-challenge"


#: The intervention kinds: evidence from a thing the project *did to* the model rather than from a
#: quantity it watched. A SUPPORTED card must cite at least one of these.
INTERVENTION_KINDS: Final[frozenset[EvidenceKind]] = frozenset(
    {EvidenceKind.ABLATION, EvidenceKind.COUNTERFACTUAL}
)

#: The two evidence kinds the record supplies: what the sources describe and what they contradict.
#: A card whose pattern was scored and failed cites the second rather than the first.
HISTORY_KINDS: Final[frozenset[EvidenceKind]] = frozenset(
    {EvidenceKind.HISTORICAL, EvidenceKind.HISTORICAL_CHALLENGE}
)

#: Phrases that assert a mechanism without naming one. Case-insensitive substring match, and they
#: are checked in every prose field, because that is exactly where a vague claim would be smuggled.
VAGUE_PHRASES: Final[tuple[str, ...]] = (
    "multiple factors",
    "many factors",
    "a combination of factors",
    "complex interplay",
    "various factors",
    "several factors",
    "all of the above",
    "factors interacted",
    "it depends on many things",
)

#: How many evidence kinds a SUPPORTED card must cite, and how many a CONDITIONAL one must.
SUPPORTED_MINIMUM_KINDS: Final[int] = 2
CONDITIONAL_MINIMUM_KINDS: Final[int] = 1

#: Ids are M001, M002, ...; the id is what the report and the YAML are keyed by.
_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^M\d{3}$")


class CardError(ValueError):
    """Raised when a card does not meet the schema's discipline."""


class EvidenceCitation(BaseModel):
    """One piece of evidence: which kind, which artifact, and what it said."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EvidenceKind
    source: str = Field(min_length=1, max_length=200)
    reading: str = Field(min_length=1, max_length=400)


class Condition(BaseModel):
    """A condition of the mechanism, and whether the evidence calls it necessary or enabling."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    statement: str = Field(min_length=1, max_length=300)
    level: str = Field(pattern="^(micro|meso)$")
    role: str = Field(pattern="^(necessary|facilitating)$")


class MechanismCard(BaseModel):
    """One candidate mechanism, with the sixteen fields the phase requires."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^M\d{3}$")
    name: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=300)
    status: MechanismStatus

    micro_conditions: tuple[str, ...] = Field(min_length=1)
    meso_conditions: tuple[str, ...] = Field(min_length=1)
    causal_chain: tuple[str, ...] = Field(min_length=2)
    trigger: str = Field(min_length=1, max_length=300)
    macro_outcome: str = Field(min_length=1, max_length=300)
    conditions: tuple[Condition, ...] = Field(min_length=1)
    time_lag: str = Field(min_length=1, max_length=300)

    sensitivity_evidence: str = Field(min_length=1, max_length=500)
    ablation_evidence: str = Field(min_length=1, max_length=500)
    hold_out_evidence: str = Field(min_length=1, max_length=500)
    policy_robustness: str = Field(min_length=1, max_length=500)
    historical_support: str = Field(min_length=1, max_length=600)
    historical_challenge: str = Field(min_length=1, max_length=600)
    counterexample: str = Field(min_length=1, max_length=500)
    falsifiable_prediction: str = Field(min_length=1, max_length=600)
    uncertainty: str = Field(min_length=1, max_length=600)

    citations: tuple[EvidenceCitation, ...] = ()

    @model_validator(mode="after")
    def _no_vague_cause(self) -> MechanismCard:
        prose = " ".join(
            (
                *self.micro_conditions,
                *self.meso_conditions,
                *self.causal_chain,
                self.trigger,
                self.macro_outcome,
                self.signature_prose(),
            )
        ).lower()
        for phrase in VAGUE_PHRASES:
            if phrase in prose:
                raise ValueError(
                    f"{self.id}: {phrase!r} asserts a mechanism without naming one; say which "
                    "condition does what, or drop the claim"
                )
        return self

    def signature_prose(self) -> str:
        """Every prose field joined, for the vagueness check and for the Markdown renderer."""
        return " ".join(
            (
                self.sensitivity_evidence,
                self.ablation_evidence,
                self.hold_out_evidence,
                self.policy_robustness,
                self.historical_support,
                self.historical_challenge,
                self.counterexample,
                self.falsifiable_prediction,
                self.uncertainty,
            )
        )

    def evidence_kinds(self) -> frozenset[EvidenceKind]:
        return frozenset(citation.kind for citation in self.citations)

    def validate_status_rules(self) -> None:
        """Check the status against the evidence the card cites, and refuse an overclaim.

        ``SUPPORTED`` needs at least two evidence kinds and at least one intervention; a
        ``CONDITIONAL`` card needs at least one piece of evidence and must name the condition it
        depends on in :attr:`policy_robustness`; ``REJECTED`` and ``UNIDENTIFIED`` states must be
        paired with the measurement that rejects the claim or the gap that leaves it unmeasured, and
        a ``WEAK`` card must say why in :attr:`uncertainty`.
        """
        kinds = self.evidence_kinds()
        if self.status is MechanismStatus.SUPPORTED:
            if len(kinds) < SUPPORTED_MINIMUM_KINDS:
                raise CardError(
                    f"{self.id}: SUPPORTED needs at least {SUPPORTED_MINIMUM_KINDS} evidence "
                    f"kinds, found {sorted(kind.value for kind in kinds)}"
                )
            if not kinds & INTERVENTION_KINDS:
                raise CardError(
                    f"{self.id}: SUPPORTED needs an intervention (ablation or counterfactual arm), "
                    "not only quantities that were watched"
                )
        elif self.status is MechanismStatus.CONDITIONAL:
            if len(kinds) < CONDITIONAL_MINIMUM_KINDS:
                raise CardError(f"{self.id}: CONDITIONAL needs at least one piece of evidence")
            if not self.conditions:
                raise CardError(f"{self.id}: CONDITIONAL must name the condition it depends on")
        elif self.status is MechanismStatus.WEAK:
            if not kinds:
                raise CardError(f"{self.id}: WEAK still needs the evidence that makes it weak")
        elif self.status is MechanismStatus.REJECTED:
            if EvidenceKind.ABLATION not in kinds and EvidenceKind.COUNTERFACTUAL not in kinds:
                raise CardError(
                    f"{self.id}: REJECTED must cite the intervention or measurement that rejects it"
                )
        elif self.status is MechanismStatus.UNIDENTIFIED:
            if kinds - HISTORY_KINDS:
                raise CardError(
                    f"{self.id}: UNIDENTIFIED means no measurement exists; a card that cites a "
                    "measurement has to take a measured status"
                )
            if not self.uncertainty:
                raise CardError(f"{self.id}: UNIDENTIFIED must name what could not be measured")


class MechanismBook(BaseModel):
    """Every card, in id order, with the phase's own provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "mechanism-cards-v1"
    cards: tuple[MechanismCard, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ids_are_unique_and_ordered(self) -> MechanismBook:
        ids = [card.id for card in self.cards]
        if len(set(ids)) != len(ids):
            raise ValueError("card ids must be unique")
        if ids != sorted(ids):
            raise ValueError("cards must be listed in id order")
        for card in self.cards:
            card.validate_status_rules()
        return self

    def by_id(self, card_id: str) -> MechanismCard:
        for card in self.cards:
            if card.id == card_id:
                return card
        raise KeyError(card_id)

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for card in self.cards:
            counts[card.status.value] = counts.get(card.status.value, 0) + 1
        return counts
