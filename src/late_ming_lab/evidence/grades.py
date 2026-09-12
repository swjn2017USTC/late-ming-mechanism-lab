"""Evidence grading for every value that enters the model.

A number in this project is only meaningful together with the strength of the evidence
behind it (`docs/epistemics/evidence-grades.md`). :class:`DataProvenance` is the lightweight
carrier of that statement: grade, source, locator, and the reasoning when the value is an
assumption rather than a sourced measurement.

Two rules are enforced here rather than documented only:

- grades ``A`` to ``D`` require both a source id and a locator, so a sourced value can be
  checked later against the evidence ledger;
- grade ``S`` requires an explicit note, because an unlabelled assumption is
  indistinguishable from a measurement.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

SOURCE_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"


class EvidenceGrade(StrEnum):
    """Quality of the evidence behind a value; never how convenient the value is."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    S = "S"


#: Grades that assert something about the historical record and therefore need a source.
SOURCED_GRADES: Final[frozenset[EvidenceGrade]] = frozenset(
    {EvidenceGrade.A, EvidenceGrade.B, EvidenceGrade.C, EvidenceGrade.D}
)


class DataProvenance(BaseModel):
    """Where a value comes from, and how strong the evidence is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    grade: EvidenceGrade
    source_id: str | None = Field(default=None, pattern=SOURCE_ID_PATTERN, max_length=128)
    locator: str | None = Field(default=None, max_length=512)
    note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _validate_grade_requirements(self) -> DataProvenance:
        if self.grade in SOURCED_GRADES:
            if self.source_id is None or self.locator is None:
                raise ValueError(
                    f"grade {self.grade.value} requires both source_id and locator "
                    "(an unsourced value may only be graded S)"
                )
        elif not self.note.strip():
            raise ValueError(
                "grade S requires a note stating the assumption, so it cannot be "
                "mistaken for a measurement"
            )
        return self

    @classmethod
    def assumption(cls, note: str) -> DataProvenance:
        """Provenance for a value that is a model assumption and nothing more."""
        return cls(grade=EvidenceGrade.S, note=note)

    @property
    def is_assumption(self) -> bool:
        return self.grade is EvidenceGrade.S
