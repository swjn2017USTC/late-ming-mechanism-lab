"""The V2.1 closure: the cards, the sample semantics, the translation rule and the bundle.

The properties this file defends are the ones the phase's acceptance turns on:

```text
the cards recompute        every number on every card is read through an accessor from a file whose
                           digest is recorded beside it, and every lineage locator resolves
the sample is measured     a card's independent sample count is the number of *distinct processes*
                           across the arms it reads, not the number of executions or seeds
no English fallback        a Chinese card renders a translated field or refuses; a field whose
                           English moved must be retranslated, and one that did not inherits
the bundle is bound        code, commit, lock, artifacts, cards, reports and the translation
                           version, by SHA-256, and two passes produce the same bytes
no tag                     three gates are unmet, they are published as limitations, and the
                           candidate tag is not created
```

The passes run in a scratch copy of the declared inputs, so a test never writes into the repo.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from late_ming_lab.release.bundle import evaluate_gates, unresolved_locators
from late_ming_lab.synthesis.v2 import _digest
from late_ming_lab.synthesis.v2_1 import (
    CARDS_FILE,
    PASS_INPUTS,
    REPORT_PATHS,
    TRANSLATION_VERSION,
    TRANSLATIONS_PATH,
    V2_ARTIFACTS,
    V21_ARTIFACTS,
    SampleSemantics,
    V21Card,
    _translation,
    _v2_card,
    build_cards,
    run_pass,
)

ROOT = Path(__file__).resolve().parents[2]

#: The status each card carries after V2.1. Nothing moves: P11's pre-registered rules kept both
#: cards it touched, and the other four were not touched at all.
EXPECTED_STATUS = {
    "M001": "CONDITIONAL",
    "M002": "CONDITIONAL",
    "M003": "REJECTED",
    "M004": "WEAK",
    "M005": "SUPPORTED",
    "M006": "UNIDENTIFIED",
}


@pytest.fixture(scope="module")
def cards() -> tuple[V21Card, ...]:
    return build_cards(ROOT)


def _card(cards: tuple[V21Card, ...], card_id: str) -> V21Card:
    for card in cards:
        if card.id == card_id:
            return card
    raise AssertionError(f"no {card_id} in the cards")


def test_the_six_cards_carry_the_statuses_the_evidence_supports(cards: tuple[V21Card, ...]) -> None:
    """V2.1 moved no status, and a phase that moved none must say so rather than look decisive."""
    assert [card.id for card in cards] == list(EXPECTED_STATUS)
    for card in cards:
        assert card.v21_status == EXPECTED_STATUS[card.id]
        assert not card.moved()


def test_every_card_states_a_measured_independent_sample_count(cards: tuple[V21Card, ...]) -> None:
    """The count is the number of distinct processes, and the basis says what was counted."""
    for card in cards:
        assert card.independent_samples >= 1
        assert card.independent_samples <= 5
        assert card.replicate_semantics in (
            "deterministic-replay",
            "one-run-per-structure",
        )
        basis = card.sample_basis
        assert "counted by" in basis and "independent sample" in basis


def test_the_sample_count_is_the_number_of_distinct_processes(cards: tuple[V21Card, ...]) -> None:
    """Recomputed here from the raw declarations, without calling the phase's own counter."""
    variants = json.loads((ROOT / "docs/v2/mechanism-variants.json").read_text(encoding="utf-8"))
    first_seed = variants["seeds"][0]
    p05 = {
        entry["arm"]: entry["simulation_digest"]
        for entry in variants["arms"]
        if entry["root_seed"] == first_seed
    }
    contrasts = json.loads((ROOT / "docs/v2_1/decisive-contrasts.json").read_text(encoding="utf-8"))
    p11 = {entry["arm"]: entry["simulation_digest"] for entry in contrasts["runs"]}

    # M003 reads five arms; two of them reproduce each other byte for byte: one process, not two.
    m003_arms = (
        "arrears-rules-off",
        "arrears-settlement",
        "arrears-remission",
        "arrears-recovery",
        "reference",
    )
    m003 = {p05[label] for label in m003_arms}
    assert _card(cards, "M003").independent_samples == len(m003)
    assert len(m003) == 4

    # M004 reads four P05 arms plus P11's closed-credit arm; P11 re-ran the accumulation arm to
    # P05's own digest, so that arm is one process and not two.
    m004_arms = (
        "elite-mediation-only",
        "elite-defaults-declared",
        "elite-accumulation",
        "reference",
    )
    m004 = {p05[label] for label in m004_arms} | {p11["elite-credit-closed"]}
    assert _card(cards, "M004").independent_samples == len(m004)
    assert len(m004) == 4

    # M002 is the reference and the opened gate, and P11's reference is P05's reference.
    assert p11["reference"] == p05["reference"]
    assert _card(cards, "M002").independent_samples == 2


def test_a_replayed_seed_is_not_rendered_as_an_independent_replicate() -> None:
    """The regression V2.1 exists for: four executions of one digest are one sample."""
    semantics = SampleSemantics(
        card="M002",
        structures=("reference",),
        executions=4,
        distinct_processes=1,
        counted_by="distinct simulation digest",
    )
    sentence = semantics.sentence()

    assert semantics.independent_samples == 1
    assert semantics.replicate_kind == "deterministic-replay"
    assert "1 independent sample." in sentence
    assert "replays of one trajectory, not independent replicates" in sentence
    assert "4 independent" not in sentence

    one_each = SampleSemantics(
        card="M001",
        structures=("a", "b"),
        executions=2,
        distinct_processes=2,
        counted_by="distinct factorial cell",
    )
    assert one_each.replicate_kind == "one-run-per-structure"
    assert one_each.independent_samples == 2


def test_every_document_that_states_a_sample_states_the_measured_one(
    cards: tuple[V21Card, ...],
) -> None:
    """A card whose executions outnumber its processes must say so where a reader will see it."""
    for card in cards:
        path = ROOT / f"docs/mechanisms/v2_1/{card.id}.md"
        text = path.read_text(encoding="utf-8")
        assert path.is_file()
        assert "## Replicate semantics" in text
        expected = card.independent_samples
        assert f"- **independent samples**: {expected}" in text
    report = (ROOT / "docs/v2_1/closure-report.md").read_text(encoding="utf-8")
    assert "not 4" in report, "the closure report must state the replicate semantics it corrected"


def test_every_evidence_ref_names_a_file_whose_digest_matches(cards: tuple[V21Card, ...]) -> None:
    """A card quoting a number must name the file it came from, and the file must be that one."""
    for card in cards:
        assert card.model_evidence, card.id
        for ref in card.model_evidence:
            path = ROOT / ref.artifact
            assert path.is_file(), ref.artifact
            digest = ref.artifact_digest
            assert digest == _digest(path), (card.id, ref.artifact)
            assert ref.accessor and ref.value != ""


def test_every_lineage_locator_resolves(cards: tuple[V21Card, ...]) -> None:
    """The V2.1 cards keep V2's chain and end it at their own file."""
    assert unresolved_locators(cards) == ()
    for card in cards:
        assert card.lineage[-1].locator == f"{CARDS_FILE}#{card.id}"


def test_a_changed_english_field_must_be_retranslated(cards: tuple[V21Card, ...]) -> None:
    """The no-fallback rule: text that moved without a new translation is refused, not rendered."""
    card = _card(cards, "M001")
    v2_card = _v2_card(ROOT, "M001")

    resolved = _translation(ROOT, card, v2_card)
    assert resolved["uncertainty"] == _v2_card_text("M001", "uncertainty")

    changed = card.model_copy(update={"uncertainty": "a sentence the translator never saw"})
    with pytest.raises(Exception, match="translated neither"):
        _translation(ROOT, changed, v2_card)


def _v2_card_text(card_id: str, field_name: str) -> str:
    """The V2 translation of one field, read from the V2 table rather than typed here."""
    import yaml

    payload = yaml.safe_load((ROOT / "data/mechanisms/v2-zh.yaml").read_text(encoding="utf-8"))
    for entry in payload["cards"]:
        if entry["id"] == card_id:
            return str(entry[field_name])
    raise AssertionError(f"the V2 table holds no {card_id}")


def test_the_chinese_cards_render_every_translated_field(cards: tuple[V21Card, ...]) -> None:
    """One field per translated name, in the file a reader opens."""
    for card in cards:
        path = ROOT / f"docs/mechanisms/v2_1/zh/{card.id}.md"
        text = path.read_text(encoding="utf-8")
        assert f"# {card.id} — " in text
        for label in ("问题", "状态", "样本语义", "独立样本数", "史料部分", "可否证预测"):
            assert label in text, (card.id, label)
        assert "English" not in text.split("## 史料部分")[1].split("## 证据链")[0]


def _scratch_root(tmp_path: Path) -> Path:
    """A copy of what the pass reads, so the determinism check never writes into the repository."""
    for relative in (*PASS_INPUTS, *V2_ARTIFACTS, *V21_ARTIFACTS, *REPORT_PATHS):
        source = ROOT / relative
        if source.is_file():
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, target)
    for relative in (
        "src",
        "sources/registry",
        "data/historical_patterns",
        "data/mechanisms",
        "data/normalized/v2",
        "docs/mechanisms/v2",
        "docs/v2",
        "docs/v2_1",
    ):
        if (ROOT / relative).is_dir():
            shutil.copytree(
                ROOT / relative,
                tmp_path / relative,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
    return tmp_path


def test_the_pass_is_deterministic_and_binds_what_it_should(tmp_path: Path) -> None:
    """Two passes, same bytes, and a bundle that names code, commit, lock, artifacts and reports."""
    root = _scratch_root(tmp_path)
    first = run_pass(root)
    before = (root / first.bundle).read_bytes()
    second = run_pass(root)
    after = (root / second.bundle).read_bytes()

    assert before == after, "the closure pass is not deterministic"
    assert first.card_count == 6 and first.moved == 0
    assert first.unmet == ("Calibration", "Sensitivity", "Policy")

    bundle = json.loads(after.decode("utf-8"))
    assert bundle["candidate"] == "v0.2.0-rc1"
    assert bundle["tag_created"] is False
    assert len(bundle["code_digest"]) == 64 and bundle["code_files"] > 100
    assert len(bundle["uv_lock_sha256"]) == 64
    assert len(bundle["pyproject_sha256"]) == 64
    assert bundle["translation_version"] == TRANSLATION_VERSION
    assert {entry["release"] for entry in bundle["artifacts"]} == {"V2", "V2.1"}
    assert all(entry["sha256"] and entry["bytes"] > 0 for entry in bundle["artifacts"])
    assert all(entry["present"] for entry in bundle["reports"])
    assert len(bundle["cards"]) == 6
    assert len(bundle["gates"]) == 9
    assert len(bundle["bundle_hash"]) == 64


def test_a_bundle_hash_covers_the_manifest_it_names(tmp_path: Path) -> None:
    """An edited field changes the hash, so a rebuilt bundle that differs anywhere is visible."""
    from late_ming_lab.core.hashing import canonical_json, hash_text

    root = _scratch_root(tmp_path)
    run_pass(root)
    bundle = json.loads((root / "docs/v2_1/release-bundle.json").read_text(encoding="utf-8"))
    recorded = bundle.pop("bundle_hash")

    assert hash_text(canonical_json(bundle)) == recorded


def test_three_gates_are_still_unmet_and_no_candidate_tag_exists(
    cards: tuple[V21Card, ...],
) -> None:
    """The point of the phase: the seal is honest, and the tag V2 withheld is still withheld."""
    gates = {row["gate"]: row["status"] for row in evaluate_gates(ROOT, cards=cards)}

    assert gates["Calibration"] == "unmet"
    assert gates["Sensitivity"] == "unmet"
    assert gates["Policy"] == "unmet"
    assert sum(1 for status in gates.values() if status == "met") == 6
    tags = subprocess.run(
        ["git", "tag", "-l"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert not [tag for tag in tags if tag.startswith("v0.2")]


def test_the_limitations_page_names_the_unmet_gates_and_the_defects() -> None:
    """A closure that hid the unmet gates or the carried defects would be a seal on nothing."""
    text = (ROOT / "docs/v2_1/limitations.md").read_text(encoding="utf-8")

    for gate in ("Calibration", "Sensitivity", "Policy"):
        assert gate in text
    assert "still not tagged" in text
    assert "not bit-reproducible" in text
    assert TRANSLATIONS_PATH in text or "v2_1-zh.yaml" in text or "translation" in text


def test_the_handoff_separates_the_four_lists() -> None:
    """The handoff's value is the split: reuse, answered-negative, new-data-only, not-worth-more."""
    text = (ROOT / "docs/v2_1/handoff.md").read_text(encoding="utf-8")

    for heading in (
        "## 1. Reusable infrastructure",
        "## 2. Sealed negative results",
        "## 3. Only new data can change these",
        "## 4. Not worth more compute on this model",
    ):
        assert heading in text
