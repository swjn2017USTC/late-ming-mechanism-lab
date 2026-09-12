"""Provenance contract: a value without evidence strength cannot enter the model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from late_ming_lab.evidence.grades import DataProvenance, EvidenceGrade


def test_assumptions_must_say_what_they_assume() -> None:
    with pytest.raises(ValidationError, match="grade S requires a note"):
        DataProvenance(grade=EvidenceGrade.S)

    assumption = DataProvenance.assumption("illustrative value, not a measurement")

    assert assumption.is_assumption
    assert assumption.source_id is None


@pytest.mark.parametrize("grade", ["A", "B", "C", "D"])
def test_sourced_grades_require_a_source_and_a_locator(grade: str) -> None:
    with pytest.raises(ValidationError, match="requires both source_id and locator"):
        DataProvenance.model_validate({"grade": grade})
    with pytest.raises(ValidationError):
        DataProvenance.model_validate({"grade": grade, "source_id": "chgis-2016"})

    sourced = DataProvenance.model_validate(
        {
            "grade": grade,
            "source_id": "chgis-2016",
            "locator": "v6 counties, row 417",
            "note": "seat point",
        }
    )

    assert not sourced.is_assumption
    assert sourced.source_id == "chgis-2016"


def test_grade_must_be_one_of_the_documented_letters() -> None:
    with pytest.raises(ValidationError):
        DataProvenance.model_validate({"grade": "E", "note": "invented grade"})
