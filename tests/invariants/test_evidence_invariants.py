"""The evidence layer's own invariants: cards cover the model, and every reference resolves.

The phase's central rule is `docs/epistemics/evidence-grades.md`: *a parameter without a card does
not enter the model*. These tests enforce it against the live parameter models rather than against a
list someone maintains by hand, and then check that the four registries agree with each other:
every source a card or a claim cites exists, every rule that claims evidence cites entries that
exist, and every cluster the phase requires is served.

They also check the two properties that make the evidence base honest rather than merely complete:
a card's recorded value equals the value the model actually runs, and nothing in the registry
presents an unverified source at a grade the verification does not support.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from late_ming_lab.evidence import parameters as P
from late_ming_lab.evidence.cards import ParameterCards, SupportClass, load_cards
from late_ming_lab.evidence.coverage import grade_summary, support_summary
from late_ming_lab.evidence.grades import EvidenceGrade
from late_ming_lab.evidence.ledger import (
    CalibrationRole,
    EvidenceLedger,
    PatternRegistry,
    RuleClaimSet,
    load_ledger,
    load_patterns,
    load_rule_claims,
)
from late_ming_lab.evidence.registry import (
    EVIDENCE_CLUSTERS,
    SourceLayer,
    SourceRegistry,
    load_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every parameter set the model runs, with the constructor that supplies its live values.
PARAMETER_SETS = {
    "CropParameters": P.core_default_crop_parameters,
    "HouseholdParameters": P.core_default_household_parameters,
    "MarketParameters": P.core_default_market_parameters,
    "EliteParameters": P.core_default_elite_parameters,
    "FiscalParameters": P.core_default_fiscal_parameters,
    "MilitaryParameters": P.core_default_military_parameters,
    "BandParameters": P.core_default_band_parameters,
    "MigrationParameters": P.core_default_migration_parameters,
    "GovernanceIndicatorParameters": P.core_default_governance_indicators,
}


@pytest.fixture(scope="module")
def cards() -> ParameterCards:
    return load_cards(REPO_ROOT)


@pytest.fixture(scope="module")
def registry() -> SourceRegistry:
    return load_registry(REPO_ROOT)


@pytest.fixture(scope="module")
def ledger() -> EvidenceLedger:
    return load_ledger(REPO_ROOT)


@pytest.fixture(scope="module")
def rules() -> RuleClaimSet:
    return load_rule_claims(REPO_ROOT)


@pytest.fixture(scope="module")
def patterns() -> PatternRegistry:
    return load_patterns(REPO_ROOT)


def test_every_parameter_the_model_runs_has_a_card(cards: ParameterCards) -> None:
    """The doc's rule, enforced: no parameter without a card."""
    missing: list[str] = []
    for set_name in PARAMETER_SETS:
        model = getattr(P, set_name)
        fields = tuple(name for name in model.model_fields if name not in ("version", "provenance"))
        missing.extend(f"{set_name}.{field}" for field in cards.missing_for(set_name, fields))
    assert missing == [], f"parameters with no card: {', '.join(missing)}"


def test_no_card_documents_a_parameter_that_does_not_exist(cards: ParameterCards) -> None:
    """The other direction: a card for a field the model does not have is a stale record."""
    stale: list[str] = []
    for card in cards:
        model = getattr(P, card.parameter_set, None)
        assert model is not None, f"{card.id}: unknown parameter set {card.parameter_set}"
        if card.id not in model.model_fields:
            stale.append(f"{card.parameter_set}.{card.id}")
    assert stale == [], f"cards for parameters that do not exist: {', '.join(stale)}"


def test_every_card_records_the_value_the_model_actually_uses(cards: ParameterCards) -> None:
    """A card whose value has drifted from the code is worse than no card."""
    for card in cards:
        live = getattr(PARAMETER_SETS[card.parameter_set](), card.id)
        if card.central is not None:
            assert float(live) == pytest.approx(card.central), (
                f"{card.parameter_set}.{card.id}: card says {card.central}, model uses {live}"
            )
        else:
            assert isinstance(live, dict) and card.central_text, (
                f"{card.parameter_set}.{card.id}: a non-scalar value needs central_text"
            )
            for key, value in live.items():
                assert f"{getattr(key, 'value', key)}={value}" in (card.central_text or ""), (
                    f"{card.parameter_set}.{card.id}: {key} missing from the recorded value"
                )


def test_every_card_declares_which_kind_of_claim_it_is(cards: ParameterCards) -> None:
    """Evidence-backed, theoretically assumed or exploratory — with no unlabelled middle."""
    assert len(cards) > 0
    for card in cards:
        assert card.support_class in set(SupportClass)
        assert card.reasoning.strip(), f"{card.parameter_set}.{card.id}: no reasoning recorded"
        assert card.uncertainty.strip(), f"{card.parameter_set}.{card.id}: no uncertainty stated"


def test_an_evidence_backed_value_cites_evidence_and_an_assumption_does_not(
    cards: ParameterCards,
) -> None:
    for card in cards:
        if card.support_class is SupportClass.EVIDENCE_BACKED:
            assert card.sources, f"{card.parameter_set}.{card.id}: evidence-backed without sources"
        if card.evidence_grade is EvidenceGrade.S:
            assert not card.sources, (
                f"{card.parameter_set}.{card.id}: a grade-S value must not cite sources"
            )


def test_every_referenced_source_exists(
    registry: SourceRegistry,
    cards: ParameterCards,
    ledger: EvidenceLedger,
    patterns: PatternRegistry,
) -> None:
    """Referential integrity across all four registries."""
    referenced: set[str] = set()
    for card in cards:
        referenced.update(card.sources)
    for entry in ledger:
        referenced.update(entry.sources)
    for pattern in patterns:
        referenced.update(pattern.sources)
    unknown = sorted(source_id for source_id in referenced if not registry.has(source_id))
    assert unknown == [], f"references to unregistered sources: {', '.join(unknown)}"


def test_an_unverified_source_never_carries_a_strong_grade(registry: SourceRegistry) -> None:
    """The doubt travels with the claim: unverified records cannot be graded A or B."""
    for source in registry:
        if source.verification.value == "unverified":
            assert source.grade in {EvidenceGrade.C, EvidenceGrade.D, EvidenceGrade.S}


def test_every_rule_is_related_to_evidence_or_declared_exploratory(
    rules: RuleClaimSet, ledger: EvidenceLedger
) -> None:
    """The phase's requirement, checked both ways."""
    entry_ids = {entry.id for entry in ledger}
    for rule in rules:
        if rule.support_class is SupportClass.EVIDENCE_BACKED:
            assert rule.ledger_entries, (
                f"{rule.name}: declared evidence-backed with no ledger entry"
            )
        for entry_id in rule.ledger_entries:
            assert entry_id in entry_ids, f"{rule.name}: cites missing ledger entry {entry_id}"
    counts = support_summary(rules)
    assert sum(counts.values()) == len(rules)


GRADE_RANK = {
    EvidenceGrade.S: 0,
    EvidenceGrade.D: 1,
    EvidenceGrade.C: 2,
    EvidenceGrade.B: 3,
    EvidenceGrade.A: 4,
}


def _best_source_grade(registry: SourceRegistry, source_ids: tuple[str, ...]) -> EvidenceGrade:
    return max(
        (registry.require(source_id).grade for source_id in source_ids),
        key=lambda grade: GRADE_RANK[grade],
    )


def test_no_claim_pattern_or_card_is_graded_above_its_best_source(
    registry: SourceRegistry,
    ledger: EvidenceLedger,
    cards: ParameterCards,
    patterns: PatternRegistry,
) -> None:
    """A grade may not claim more than the strongest thing it rests on.

    Cross-support can lift a claim above a single source's grade when several independent sources
    agree — that is what grade B means — but never above the *best* source cited for it. This is the
    check that catches a grade inflated by writing a confident sentence.
    """
    inflated: list[str] = []
    for entry in ledger:
        best = _best_source_grade(registry, entry.sources)
        if GRADE_RANK[entry.evidence_grade] > GRADE_RANK[best]:
            inflated.append(f"claim {entry.id} ({entry.evidence_grade.value} > {best.value})")
    for pattern in patterns:
        best = _best_source_grade(registry, pattern.sources)
        if GRADE_RANK[pattern.evidence_grade] > GRADE_RANK[best]:
            inflated.append(f"pattern {pattern.id} ({pattern.evidence_grade.value} > {best.value})")
    for card in cards:
        if not card.sources:
            continue
        best = _best_source_grade(registry, card.sources)
        if GRADE_RANK[card.evidence_grade] > GRADE_RANK[best]:
            inflated.append(
                f"card {card.parameter_set}.{card.id} ({card.evidence_grade.value} > {best.value})"
            )
    assert inflated == [], f"grades above their best source: {', '.join(inflated)}"


def test_no_unverified_source_carries_a_claim_graded_above_it(
    registry: SourceRegistry, ledger: EvidenceLedger, patterns: PatternRegistry
) -> None:
    """An unverified record cannot support a claim stronger than itself.

    A source whose identity was confirmed but whose pages were never opened may be cited for a
    claim at or below its own grade; it may not be listed as support for a bolder claim, because a
    reader would take the citation list as agreement between sources when part of it was never
    read. Verified sources of any grade may corroborate freely: they can be opened and checked.
    """
    offending: list[str] = []
    for entry in ledger:
        for source_id in entry.sources:
            source = registry.require(source_id)
            if (
                source.verification.value == "unverified"
                and GRADE_RANK[entry.evidence_grade] > GRADE_RANK[source.grade]
            ):
                offending.append(
                    f"claim {entry.id} ({entry.evidence_grade.value}) cites unread "
                    f"{source_id} ({source.grade.value})"
                )
    for pattern in patterns:
        for source_id in pattern.sources:
            source = registry.require(source_id)
            if (
                source.verification.value == "unverified"
                and GRADE_RANK[pattern.evidence_grade] > GRADE_RANK[source.grade]
            ):
                offending.append(
                    f"pattern {pattern.id} ({pattern.evidence_grade.value}) cites unread "
                    f"{source_id} ({source.grade.value})"
                )
    assert offending == [], "; ".join(offending)


def test_every_ledger_entry_names_a_cluster_and_a_locator_for_every_source(
    ledger: EvidenceLedger,
) -> None:
    for entry in ledger:
        assert entry.cluster in EVIDENCE_CLUSTERS
        assert len(entry.locators) == len(entry.sources)


def test_the_ten_required_clusters_are_served(
    registry: SourceRegistry, ledger: EvidenceLedger, patterns: PatternRegistry
) -> None:
    """A cluster with nothing behind it is a gap, and the phase may not have ten of them."""
    assert registry.clusters_without_sources() == ()
    assert ledger.clusters_without_entries() == ()
    assert patterns.clusters_without_patterns() == ()


def test_patterns_declare_their_calibration_role_and_a_signature(patterns: PatternRegistry) -> None:
    """Nothing may be fitted later that was not marked now."""
    assert len(patterns) > 0
    assert patterns.hold_out_ids, "at least one pattern must be held out of any future fit"
    for pattern in patterns:
        assert pattern.calibration_role in set(CalibrationRole)
        assert pattern.signatures, f"{pattern.id}: a pattern with no observable signature"
        for signature in pattern.signatures:
            assert signature.scoring.strip()


def test_the_registry_keeps_primary_and_modern_material_layered(registry: SourceRegistry) -> None:
    """Modern scholarship and primary material are different kinds of claim, never merged."""
    layers = {source.layer for source in registry}
    assert SourceLayer.PRIMARY in layers, "the registry must hold primary material"
    assert SourceLayer.MODERN_SCHOLARSHIP in layers, "and modern scholarship beside it"


def test_human_only_acquisition_is_recorded_not_bypassed(registry: SourceRegistry) -> None:
    """Restricted sources state their condition, and no locator is a path to an acquired file.

    A locator may be a URL, a DOI, an ISBN or a shelfmark — including a public URL that ends in
    `.pdf`, because that identifies where a source lives. What it may not be is a path inside this
    repository or a machine: a local path would mean the material was acquired, which for restricted
    sources is a human act and for licensed material is not permitted here at all.
    """
    for source in registry:
        if source.acquisition_is_human_only:
            assert source.rights_note.strip(), f"{source.id}: restricted access without a note"
        locator = source.locator
        assert not locator.startswith("/"), f"{source.id}: locator is an absolute local path"
        assert "private/" not in locator, f"{source.id}: locator points into private material"
        assert not locator.startswith(("sources/", "data/", "./")), (
            f"{source.id}: locator is a path inside the repository, so the file was acquired"
        )


def test_the_grade_and_support_summaries_cover_every_card(cards: ParameterCards) -> None:
    grades = grade_summary(cards)
    assert sum(grades.values()) == len(cards)
