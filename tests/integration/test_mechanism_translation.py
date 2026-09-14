"""The Chinese translation beside the cards: a translation, not a second source of truth.

The English files are what loads, what the browser serves and what the CLI regenerates; the Chinese
files are a reading aid. That relationship is checkable, so these tests check it rather than
trusting it: the two books must hold the same cards with the same statuses, every Chinese file must
carry the same numbers as its English original, and every Chinese file must say in its own text
that the English original governs.

What the number check catches is drift - the English card revised after the translation was made,
which would otherwise leave a Chinese reader with figures the project no longer supports. It
compares numeric tokens, which are language-independent, so it needs no glossary and cannot be
satisfied by a clever turn of phrase.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from late_ming_lab.synthesis.schema import CARDS_FILE, DOCS_ROOT, MechanismBook, load_book

REPOSITORY = Path(__file__).resolve().parents[2]
ZH_ROOT = REPOSITORY / "docs/mechanisms/zh"

#: The English file and its Chinese counterpart, in the order the phase produced them.
PAIRS: tuple[tuple[str, str], ...] = (
    ("docs/mechanisms/cards.yaml", "docs/mechanisms/zh/cards.yaml"),
    ("docs/mechanisms/index.md", "docs/mechanisms/zh/index.md"),
    (
        "docs/mechanisms/M001-fiscal-extraction-inversion.md",
        "docs/mechanisms/zh/M001-fiscal-extraction-inversion.md",
    ),
    ("docs/mechanisms/M002-crisis-gating.md", "docs/mechanisms/zh/M002-crisis-gating.md"),
    (
        "docs/mechanisms/M003-fiscal-military-ratchet.md",
        "docs/mechanisms/zh/M003-fiscal-military-ratchet.md",
    ),
    (
        "docs/mechanisms/M004-elite-mediation-bifurcation.md",
        "docs/mechanisms/zh/M004-elite-mediation-bifurcation.md",
    ),
    (
        "docs/mechanisms/M005-insurgent-consolidation.md",
        "docs/mechanisms/zh/M005-insurgent-consolidation.md",
    ),
    ("docs/mechanisms/M006-famine-mortality.md", "docs/mechanisms/zh/M006-famine-mortality.md"),
    (
        "outputs/reports/mechanism-synthesis.md",
        "outputs/reports/mechanism-synthesis.zh.md",
    ),
)

#: Numeric tokens: integers, thousands-separated integers and decimals, as both files write them.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

#: The lines that announce the translation. They carry no claim and are not part of the translation.
_HEADER_MARKERS = ("英文原稿为准", "中文译稿")


def _numbers(text: str) -> list[str]:
    """Every numeric token of the translated body, with the announcement lines removed."""
    body = "\n".join(
        line for line in text.splitlines() if not any(mark in line for mark in _HEADER_MARKERS)
    )
    return sorted(_NUMBER.findall(body))


@pytest.fixture(scope="module")
def english() -> MechanismBook:
    return load_book(REPOSITORY / DOCS_ROOT / CARDS_FILE)


def test_the_translation_is_the_same_book(english: MechanismBook) -> None:
    """A translation that gained or lost a card, or changed a status, is not a translation."""
    translated: MechanismBook = load_book(ZH_ROOT / "cards.yaml")
    assert [card.id for card in translated.cards] == [card.id for card in english.cards]
    assert [card.name for card in translated.cards] == [card.name for card in english.cards]
    assert translated.status_counts() == english.status_counts()
    for original, mirror in zip(english.cards, translated.cards, strict=True):
        assert mirror.status is original.status
        assert len(mirror.citations) == len(original.citations)
        assert [c.kind for c in mirror.citations] == [c.kind for c in original.citations]


def test_every_chinese_file_carries_the_same_numbers_as_its_original() -> None:
    """The check that makes drift visible: figures are language-independent, so they must match."""
    for english_path, chinese_path in PAIRS:
        original = (REPOSITORY / english_path).read_text(encoding="utf-8")
        translated = (REPOSITORY / chinese_path).read_text(encoding="utf-8")
        assert _numbers(translated) == _numbers(original), (
            f"{chinese_path} does not carry the same numbers as {english_path}; a card revised in "
            "English after the translation was made would look like this"
        )


def test_every_chinese_file_says_which_one_governs() -> None:
    """A translation that does not say so invites a reader to treat it as the source."""
    for _, chinese_path in PAIRS:
        text = (REPOSITORY / chinese_path).read_text(encoding="utf-8")
        assert "英文原稿为准" in text, (
            f"{chinese_path} does not state that the English original governs"
        )


def test_the_chinese_cards_keep_the_briefs_field_count() -> None:
    """Sixteen numbered fields per card, in the brief's order, in Chinese too."""
    headings = re.compile(r"^## (\d{1,2})\. ", re.M)
    for english_path, chinese_path in PAIRS:
        if "M0" not in chinese_path or chinese_path.endswith(".yaml"):
            continue
        original = headings.findall((REPOSITORY / english_path).read_text(encoding="utf-8"))
        translated = headings.findall((REPOSITORY / chinese_path).read_text(encoding="utf-8"))
        assert translated == original, f"{chinese_path} renumbers or drops a field"
        assert len(translated) == 16
