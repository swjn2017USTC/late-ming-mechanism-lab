"""The evidence reports as a test: they are generated, and they agree with the registries.

The phase's three reports are build artifacts, not prose maintained by hand, so this test writes
them into a temporary directory and checks the numbers printed in them against the registries they
were generated from. A report that drifts from the data is worse than no report: it is a summary a
reader would trust.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from late_ming_lab.evidence.coverage import grade_summary, support_summary
from late_ming_lab.experiments.evidence import (
    COVERAGE_ARTIFACT,
    GAPS_ARTIFACT,
    UNCERTAINTY_ARTIFACT,
    load_evidence_base,
    write_evidence_reports,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def written(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, str]]:
    directory = tmp_path_factory.mktemp("evidence-reports")
    paths = write_evidence_reports(REPO_ROOT, output_dir=directory)
    texts = {path.name: path.read_text(encoding="utf-8") for path in paths}
    return directory, texts


def test_the_three_reports_are_written(written: tuple[Path, dict[str, str]]) -> None:
    _, texts = written
    assert set(texts) == {COVERAGE_ARTIFACT, UNCERTAINTY_ARTIFACT, GAPS_ARTIFACT}
    for name, text in texts.items():
        assert text.startswith("# "), f"{name} has no title"
        assert len(text) > 500, f"{name} is too thin to be a report"


def test_the_coverage_report_counts_what_the_registries_hold(
    written: tuple[Path, dict[str, str]],
) -> None:
    _, texts = written
    base = load_evidence_base(REPO_ROOT)
    coverage = texts[COVERAGE_ARTIFACT]

    assert f"- sources: {len(base.registry)}" in coverage
    assert f"- ledger entries: {len(base.ledger)}" in coverage
    assert f"- parameter cards: {len(base.cards)}" in coverage
    assert f"- declared rules: {len(base.rules)}" in coverage
    assert f"- historical patterns: {len(base.patterns)}" in coverage
    grades = grade_summary(base.cards)
    rendered = ", ".join(f"{grade}:{count}" for grade, count in grades.items())
    assert rendered in coverage


def test_the_coverage_report_names_every_rule_and_cluster(
    written: tuple[Path, dict[str, str]],
) -> None:
    _, texts = written
    base = load_evidence_base(REPO_ROOT)
    coverage = texts[COVERAGE_ARTIFACT]

    for rule in base.rules:
        assert rule.name in coverage, f"{rule.name} missing from the coverage report"
    for cluster in (
        "drought_climate",
        "famine",
        "agriculture",
        "population_migration",
        "grain_market_prices",
        "land_debt_elites",
        "taxation_levies",
        "relief",
        "military_finance",
        "rebellion_armed_groups",
    ):
        assert cluster in coverage


def test_the_uncertainty_report_carries_every_card(written: tuple[Path, dict[str, str]]) -> None:
    _, texts = written
    base = load_evidence_base(REPO_ROOT)
    uncertainty = texts[UNCERTAINTY_ARTIFACT]

    for card in base.cards:
        assert f"| {card.id} | {card.parameter_set} |" in uncertainty, (
            f"{card.parameter_set}.{card.id} missing from the uncertainty report"
        )


def test_the_gap_report_states_the_separation_it_claims(
    written: tuple[Path, dict[str, str]],
) -> None:
    _, texts = written
    base = load_evidence_base(REPO_ROOT)
    gaps = texts[GAPS_ARTIFACT]

    assert "## Acquisition queue (human only)" in gaps
    assert f"{len(base.registry.human_only_ids)}" in gaps or "none" in gaps
    # Every rule that cites no claim and is not exploratory must be named as a gap.
    unexplained = [
        rule
        for rule in base.rules
        if not rule.ledger_entries and rule.support_class.value != "exploratory"
    ]
    for rule in unexplained:
        assert rule.name in gaps, f"{rule.name} is un-evidenced but missing from the gap list"


def test_the_support_summary_covers_every_rule() -> None:
    base = load_evidence_base(REPO_ROOT)
    summary = support_summary(base.rules)
    assert sum(summary.values()) == len(base.rules)
