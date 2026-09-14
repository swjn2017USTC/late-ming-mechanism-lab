"""The phase's products, generated from the real artifacts and checked as documents.

These read the P09-P12 batches and write the cards; they never run the model. What they defend is
that the three products agree with each other and with the evidence: the YAML loads back into the
same objects, every card's Markdown has the brief's sixteen fields in the brief's order, every
citation points at something that exists, and the synthesis renders the boundary disclaimer verbatim
beside the fitted surface it qualifies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from late_ming_lab.analysis.boundary import CAUSAL_DISCLAIMER
from late_ming_lab.evidence.registry import load_registry
from late_ming_lab.synthesis.cards import build_cards
from late_ming_lab.synthesis.evidence import EvidenceBundle, load_evidence
from late_ming_lab.synthesis.report import (
    BRIEF_FIELDS,
    CARDS_FILE,
    DOCS_ROOT,
    INDEX_FILE,
    SYNTHESIS_FILE,
    card_slug,
    load_book,
    render_synthesis,
    write_mechanism_docs,
    write_synthesis,
)
from late_ming_lab.synthesis.schema import MechanismBook

REPOSITORY = Path(__file__).resolve().parents[2]

#: Sources a card may cite that are not a single file: a batch glob, or the source registry.
GLOB_SOURCES = ("outputs/calibration/p09-*", "sources/registry")


@pytest.fixture(scope="module")
def bundle() -> EvidenceBundle:
    return load_evidence(REPOSITORY)


@pytest.fixture(scope="module")
def book(bundle: EvidenceBundle) -> MechanismBook:
    return build_cards(bundle)


def test_the_six_candidates_are_assessed_and_not_alike(book: MechanismBook) -> None:
    """The phase must not report five mechanisms as if they had all been confirmed."""
    cards = book.cards
    assert [card.id for card in cards] == ["M001", "M002", "M003", "M004", "M005", "M006"]
    statuses = book.status_counts()
    assert statuses == {
        "CONDITIONAL": 1,
        "SUPPORTED": 2,
        "REJECTED": 1,
        "WEAK": 1,
        "UNIDENTIFIED": 1,
    }


def test_every_card_carries_the_briefs_sixteen_fields(book: MechanismBook) -> None:
    """A missing field would be a claim with one of its own conditions left unstated."""
    for card in book.cards:
        body = card.model_dump(mode="json")
        for _, attribute in BRIEF_FIELDS:
            assert body[attribute], f"{card.id}: {attribute} is empty"
        assert len(card.citations) >= 1, f"{card.id}: no evidence cited"


def test_every_citation_points_at_something_that_exists(book: MechanismBook) -> None:
    """A card that cites a batch the project never wrote is a card that cannot be checked.

    A citation is either a path - a batch, or a batch glob - or a source-registry key, which is
    resolved against the P08 registry rather than against the filesystem.
    """
    registry = load_registry(REPOSITORY)
    for card in book.cards:
        for citation in card.citations:
            source = citation.source
            if source.startswith(GLOB_SOURCES):
                assert sorted(REPOSITORY.glob(source)), f"{card.id}: {source} matches nothing"
            elif "/" in source:
                assert (REPOSITORY / source).exists(), f"{card.id}: {source} does not exist"
            else:
                assert registry.require(source).id == source, f"{card.id}: unknown source {source}"


def test_the_yaml_and_the_objects_agree(tmp_path: Path, book: MechanismBook) -> None:
    """The YAML is the same book: a later phase loads it instead of re-deriving the cards."""
    written = write_mechanism_docs(tmp_path, book)
    names = {path.name for path in written}
    assert CARDS_FILE in names and INDEX_FILE in names
    loaded = load_book(tmp_path / DOCS_ROOT / CARDS_FILE)
    assert loaded == book


def test_each_card_markdown_numbers_the_briefs_fields(tmp_path: Path, book: MechanismBook) -> None:
    """The human-readable card is checkable against the brief without a map."""
    write_mechanism_docs(tmp_path, book)
    for card in book.cards:
        slug = f"{card_slug(card)}.md"
        text = (tmp_path / DOCS_ROOT / slug).read_text(encoding="utf-8")
        assert f"**Status: {card.status.value}**" in text
        for number, (heading, _) in enumerate(BRIEF_FIELDS, start=1):
            assert f"## {number}. {heading}" in text, f"{card.id}: missing field {number}"


def test_the_synthesis_renders_the_disclaimer_beside_the_surface(
    book: MechanismBook, bundle: EvidenceBundle
) -> None:
    """ML describes these runs; the report has to say so where it quotes the fit, not in a note."""
    text = render_synthesis(book, bundle, REPOSITORY)
    assert CAUSAL_DISCLAIMER in text
    assert "not evidence about the past" in text
    assert "Cross-validated AUC" in text
    for card in book.cards:
        assert f"{card.id} {card.name}" in text
        assert card.status.value in text
    assert "docs/mechanisms/index.md" in text


def test_the_synthesis_is_written_where_the_phase_says(
    tmp_path: Path, book: MechanismBook, bundle: EvidenceBundle
) -> None:
    """The path is part of the phase's contract, so the writer is checked against it."""
    target = write_synthesis(tmp_path, book, bundle, artifacts_root=REPOSITORY)
    assert target == tmp_path / SYNTHESIS_FILE
    assert target.exists() and target.stat().st_size > 0
