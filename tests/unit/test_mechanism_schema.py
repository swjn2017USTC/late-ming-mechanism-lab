"""The card schema's discipline: what a card may claim, and what it is refused for claiming."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from late_ming_lab.synthesis.schema import (
    VAGUE_PHRASES,
    Condition,
    EvidenceCitation,
    EvidenceKind,
    MechanismBook,
    MechanismCard,
    MechanismStatus,
)


def _card(**overrides: object) -> MechanismCard:
    """A card that validates, so a test can change exactly one thing about it."""
    fields: dict[str, object] = {
        "id": "M001",
        "name": "A candidate",
        "question": "Does the declared condition move the declared outcome?",
        "status": MechanismStatus.WEAK,
        "micro_conditions": ("A household can leave.",),
        "meso_conditions": ("The county assesses a base it can lose.",),
        "causal_chain": ("Distress rises.", "Departures follow and the base contracts."),
        "trigger": "A distress line being crossed.",
        "macro_outcome": "A smaller assessable base.",
        "conditions": (
            Condition(statement="A base that can move.", level="meso", role="necessary"),
        ),
        "time_lag": "Not resolved: the run is the unit.",
        "sensitivity_evidence": "The parameter sits below the Morris floor.",
        "ablation_evidence": "No arm isolates it.",
        "hold_out_evidence": "No reserved pattern scores it.",
        "policy_robustness": "Not measured by the P12 readings.",
        "historical_support": "The record describes the sequence.",
        "historical_challenge": "The record does not describe the mechanism.",
        "counterexample": "No run shows the opposite.",
        "falsifiable_prediction": "An arm that removes the trigger should remove the effect.",
        "uncertainty": "One arm, four replicates.",
        "citations": (
            EvidenceCitation(
                kind=EvidenceKind.ABLATION,
                source="outputs/experiments/p10-ablations/runs.parquet",
                reading="breakdown +1.00 [+1.00, +1.00] up",
            ),
        ),
    }
    fields.update(overrides)
    return MechanismCard(**fields)  # type: ignore[arg-type]


def test_a_card_that_says_nothing_specific_is_refused() -> None:
    """The vagueness check is the schema's whole reason for existing: it names the phrase."""
    for phrase in VAGUE_PHRASES:
        with pytest.raises(ValidationError) as error:
            _card(causal_chain=("Distress rises.", f"The outcome follows from {phrase}."))
        assert "asserts a mechanism without naming one" in str(error.value)


def test_supported_needs_an_intervention_and_two_kinds() -> None:
    """A claim supported only by quantities that were watched is not supported, it is correlated."""
    watched = (
        EvidenceCitation(
            kind=EvidenceKind.HOLD_OUT,
            source="outputs/calibration/p09-*/predictive_checks.parquet",
            reading="held-out 0.94",
        ),
        EvidenceCitation(
            kind=EvidenceKind.SENSITIVITY,
            source="outputs/experiments/p10-morris/runs.parquet",
            reading="mu* = 0.75",
        ),
    )
    with pytest.raises(ValidationError) as error:
        MechanismBook(cards=(_card(status=MechanismStatus.SUPPORTED, citations=watched),))
    assert "needs an intervention" in str(error.value)

    with_intervention = (
        *watched,
        EvidenceCitation(
            kind=EvidenceKind.ABLATION,
            source="outputs/experiments/p10-ablations/runs.parquet",
            reading="breakdown +1.00 [+1.00, +1.00] up",
        ),
    )
    book = MechanismBook(
        cards=(_card(status=MechanismStatus.SUPPORTED, citations=with_intervention),)
    )
    assert book.status_counts() == {"SUPPORTED": 1}


def test_conditional_needs_the_condition_and_weak_needs_its_evidence() -> None:
    """The two middling statuses are not a place to put a claim whose evidence is missing."""
    with pytest.raises(ValidationError) as error:
        MechanismBook(
            cards=(
                _card(
                    status=MechanismStatus.CONDITIONAL,
                    conditions=(
                        Condition(
                            statement="A base that can move.", level="meso", role="necessary"
                        ),
                    ),
                    citations=(),
                ),
            )
        )
    assert "at least one piece of evidence" in str(error.value)

    with pytest.raises(ValidationError) as error:
        MechanismBook(cards=(_card(status=MechanismStatus.WEAK, citations=()),))
    assert "makes it weak" in str(error.value)


def test_rejected_needs_the_measurement_that_rejects_it() -> None:
    """'Rejected' is a result, so the card has to carry the arm or the run that produced it."""
    with pytest.raises(ValidationError) as error:
        MechanismBook(
            cards=(
                _card(
                    status=MechanismStatus.REJECTED,
                    citations=(
                        EvidenceCitation(
                            kind=EvidenceKind.HOLD_OUT,
                            source="outputs/calibration/p09-*/predictive_checks.parquet",
                            reading="held-out 0.94",
                        ),
                    ),
                ),
            )
        )
    assert "rejects it" in str(error.value)

    book = MechanismBook(cards=(_card(status=MechanismStatus.REJECTED),))
    assert book.by_id("M001").status is MechanismStatus.REJECTED


def test_unidentified_may_cite_only_the_record() -> None:
    """A card with no measurement cannot cite one: that would make it a measured claim."""
    with pytest.raises(ValidationError) as error:
        MechanismBook(
            cards=(
                _card(
                    status=MechanismStatus.UNIDENTIFIED,
                    citations=(
                        EvidenceCitation(
                            kind=EvidenceKind.HISTORICAL,
                            source="sources/registry/patterns.yaml",
                            reading="the record describes it",
                        ),
                        EvidenceCitation(
                            kind=EvidenceKind.SENSITIVITY,
                            source="outputs/experiments/p10-morris/runs.parquet",
                            reading="mu* = 0.75",
                        ),
                    ),
                ),
            )
        )
    assert "no measurement exists" in str(error.value)

    book = MechanismBook(
        cards=(
            _card(
                status=MechanismStatus.UNIDENTIFIED,
                citations=(
                    EvidenceCitation(
                        kind=EvidenceKind.HISTORICAL,
                        source="sources/registry/patterns.yaml",
                        reading="the record describes it",
                    ),
                ),
            ),
        )
    )
    assert book.by_id("M001").evidence_kinds() == frozenset({EvidenceKind.HISTORICAL})


def test_ids_are_unique_and_ordered() -> None:
    """The book is the machine-readable index, so its order cannot depend on insertion luck."""
    first = _card(id="M001")
    second = _card(id="M002")
    assert MechanismBook(cards=(first, second)).cards[0].id == "M001"
    with pytest.raises(ValidationError) as error:
        MechanismBook(cards=(first, first))
    assert "unique" in str(error.value)
    with pytest.raises(ValidationError) as error:
        MechanismBook(cards=(second, first))
    assert "id order" in str(error.value)


def test_every_prose_field_is_required() -> None:
    """Sixteen fields means sixteen: a card missing one is refused rather than half-written."""
    with pytest.raises(ValidationError):
        MechanismCard(  # type: ignore[call-arg]
            id="M001",
            name="A candidate",
            question="Does it move?",
            status=MechanismStatus.WEAK,
        )
