"""Parameter cards: the bridge between a simulation value and the evidence behind it.

`docs/epistemics/evidence-grades.md` states the rule this module enforces: *a parameter without a
card does not enter the model*. The card is the record of where a number came from, what it is
uncertain by, and — the part this phase adds — **which kind of claim it is**:

```text
evidence_backed        the value is constrained by evidence in the registry; a reviewer can check it
theoretically_assumed  the form of the rule is argued, the value is a declared prior
exploratory            the rule exists to see what happens; the value is a placeholder
```

The class is not a grade. A parameter can be grade `C` and theoretically assumed (derived by
inference from a source that does not measure it), or grade `S` and evidence-backed in *form* (a
rule whose structure follows the literature while its constants are ours). Both statements are
recorded, because collapsing them is how an assumption starts looking like a measurement.

Cards live in `data/parameters/*.yaml`, one file per parameter set, and are checked against the
live parameter models (`late_ming_lab.evidence.parameters`): a card whose id is not a field of the
set it names is an error, and so is a parameter field with no card.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from late_ming_lab.evidence.grades import SOURCED_GRADES, EvidenceGrade

CARDS_SCHEMA_VERSION: Final[str] = "parameter-cards-v1"
CARDS_GLOB: Final[str] = "data/parameters/*.yaml"


class SupportClass(StrEnum):
    """Which kind of claim a value is. Required for every parameter, without exception."""

    EVIDENCE_BACKED = "evidence-backed"
    THEORETICALLY_ASSUMED = "theoretically-assumed"
    EXPLORATORY = "exploratory"


class UncertainRange(BaseModel):
    """What the value could be instead, and where that range comes from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    low: float | None = None
    high: float | None = None
    basis: str = Field(
        min_length=1,
        max_length=512,
        description="why this range: a source that reports a spread, a unit conversion, or a "
        "declared prior width",
    )
    conflicts: str = Field(
        default="",
        max_length=1000,
        description="sources that disagree, recorded rather than averaged away",
    )

    @model_validator(mode="after")
    def _range_is_ordered(self) -> UncertainRange:
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError("a range's low bound cannot exceed its high bound")
        return self

    @property
    def has_bounds(self) -> bool:
        return self.low is not None and self.high is not None


class ParameterCard(BaseModel):
    """One parameter's evidence record; the schema is the one the epistemics doc declares."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    parameter_set: str = Field(
        min_length=1,
        max_length=128,
        description="the parameter set class the card documents, e.g. 'HouseholdParameters'",
    )
    definition: str = Field(min_length=1, max_length=1000)
    unit: str = Field(min_length=1, max_length=64)
    mechanism: str = Field(
        min_length=1,
        max_length=200,
        description="the model mechanism that consumes it, and the phase that built it",
    )
    level: str = Field(pattern=r"^(macro|meso|local|micro)$")
    support_class: SupportClass
    evidence_grade: EvidenceGrade
    central: float | None = Field(
        default=None, description="the value in use, when it is a single number"
    )
    central_text: str | None = Field(
        default=None,
        max_length=300,
        description=(
            "the value in use when it is not a single number, e.g. a per-class or per-zone "
            "mapping written out; exactly one of central and central_text is present"
        ),
    )
    range: UncertainRange | None = None
    distribution: str | None = Field(default=None, max_length=300)
    sources: tuple[str, ...] = Field(
        default=(), description="sources that bear on the value itself"
    )
    ledger_entries: tuple[str, ...] = Field(
        default=(),
        description=(
            "claims that frame or constrain the parameter without fixing its value — the common "
            "case in this model, where a source establishes that a mechanism existed and by what "
            "order of magnitude while the constant remains ours"
        ),
    )
    reasoning: str = Field(min_length=1, max_length=2000)
    uncertainty: str = Field(min_length=1, max_length=1000)
    sensitivity_priority: str = Field(pattern=r"^(high|medium|low|screened-first)$")
    version: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def _card_is_checkable(self) -> ParameterCard:
        if (self.central is None) == (self.central_text is None):
            raise ValueError(
                f"{self.id}: a card states the value in use, either as central (a number) or as "
                "central_text (a mapping), and not both"
            )
        if self.evidence_grade in SOURCED_GRADES and not self.sources:
            raise ValueError(
                f"{self.id}: grade {self.evidence_grade.value} needs at least one source; an "
                "unsourced value may only be graded S"
            )
        if self.support_class is SupportClass.EVIDENCE_BACKED and not self.sources:
            raise ValueError(
                f"{self.id}: a value cannot be called evidence-backed without citing evidence"
            )
        if self.evidence_grade is EvidenceGrade.S and self.sources:
            raise ValueError(
                f"{self.id}: a grade-S value cites no sources; if there is evidence, grade it"
            )
        return self

    @property
    def is_assumption(self) -> bool:
        return self.evidence_grade is EvidenceGrade.S

    @property
    def is_framed_by_evidence(self) -> bool:
        """True when claims inform the parameter even though no source fixes its value."""
        return bool(self.ledger_entries)

    @property
    def value_in_use(self) -> str:
        """The value as the model holds it, for reports and for checking against the code."""
        if self.central is not None:
            return f"{self.central:g}"
        return self.central_text or ""

    @property
    def needs_sensitivity(self) -> bool:
        """D and S values are the ones a conclusion must not rest on unexamined."""
        return self.evidence_grade in {EvidenceGrade.D, EvidenceGrade.S}


class ParameterCards:
    """Every card, indexed by (parameter set, field name)."""

    def __init__(self, cards: tuple[ParameterCard, ...], *, schema_version: str) -> None:
        if schema_version != CARDS_SCHEMA_VERSION:
            raise ValueError(f"cards schema {schema_version!r} is not {CARDS_SCHEMA_VERSION!r}")
        ordered = tuple(sorted(cards, key=lambda card: (card.parameter_set, card.id)))
        keys = [(card.parameter_set, card.id) for card in ordered]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            rendered = ", ".join(f"{set_name}.{name}" for set_name, name in duplicates)
            raise ValueError(f"duplicate parameter cards: {rendered}")
        self._cards = ordered
        self._by_key = {(card.parameter_set, card.id): card for card in ordered}
        self._schema_version = schema_version

    def __iter__(self) -> Iterator[ParameterCard]:
        return iter(self._cards)

    def __len__(self) -> int:
        return len(self._cards)

    @property
    def cards(self) -> tuple[ParameterCard, ...]:
        return self._cards

    @property
    def schema_version(self) -> str:
        return self._schema_version

    def for_set(self, parameter_set: str) -> tuple[ParameterCard, ...]:
        return tuple(card for card in self._cards if card.parameter_set == parameter_set)

    def get(self, parameter_set: str, parameter: str) -> ParameterCard | None:
        return self._by_key.get((parameter_set, parameter))

    def require(self, parameter_set: str, parameter: str) -> ParameterCard:
        card = self.get(parameter_set, parameter)
        if card is None:
            raise KeyError(f"no card for {parameter_set}.{parameter}")
        return card

    def missing_for(self, parameter_set: str, fields: tuple[str, ...]) -> tuple[str, ...]:
        """Fields of a live parameter set that have no card — the model's admission of silence."""
        return tuple(field for field in fields if (parameter_set, field) not in self._by_key)

    @property
    def unsourced_assumptions(self) -> tuple[ParameterCard, ...]:
        return tuple(card for card in self._cards if card.is_assumption)

    @property
    def sensitivity_candidates(self) -> tuple[ParameterCard, ...]:
        return tuple(card for card in self._cards if card.needs_sensitivity)


def load_cards(root: str | Path, *, glob: str = CARDS_GLOB) -> ParameterCards:
    """Read every card file under ``root`` and return the merged, validated set."""
    directory = Path(root)
    files = sorted(directory.glob(glob))
    if not files:
        raise FileNotFoundError(f"no parameter card files matched {glob!r} under {directory}")
    cards: list[ParameterCard] = []
    schema_versions: set[str] = set()
    for path in files:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "cards" not in payload:
            raise ValueError(f"{path}: card files must hold a 'cards' list")
        schema_versions.add(str(payload.get("schema_version", "")))
        for raw in payload["cards"]:
            cards.append(ParameterCard.model_validate(raw))
    if len(schema_versions) != 1:
        raise ValueError(f"card files disagree on schema_version: {sorted(schema_versions)}")
    return ParameterCards(tuple(cards), schema_version=schema_versions.pop())
