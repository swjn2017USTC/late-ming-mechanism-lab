"""The V2 release: cards recomputed from artifacts, and a tag that is refused when a gate fails.

The properties this file defends are the ones the phase's acceptance turns on:

```text
no inherited number     a card that quotes a statistic the artifact does not hold is an error, not
                        a card with a stale value
no silent status        every card states its V1 and V2 status and why they differ, and a card that
                        changed must say what measurement moved it
the tag is earned       an unmet gate appears in the limitations report and blocks the tag; the
                        build never creates the tag itself
the bundle is bound     the manifest names the commit, the lock, the artifacts and the reports, and
                        a second build produces the same bytes
the translation covers  every card field the Chinese renderer prints has a translation, so no
                        Chinese card silently falls back to English prose
```

Building the cards is cheap here (three artifact files), so the tests build them for real rather
than against a stub. What is not paid for is the simulation behind those artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from late_ming_lab.release.bundle import (
    RELEASE_TAG,
    build_v2_release,
    evaluate_gates,
    unresolved_locators,
)
from late_ming_lab.synthesis.v2 import (
    TRANSLATED_FIELDS,
    V2Card,
    build_cards,
    write_limitations,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def cards() -> tuple[V2Card, ...]:
    return build_cards(ROOT)


def test_every_card_status_is_stated_against_its_v1_status(cards: tuple[V2Card, ...]) -> None:
    """A reader must be able to see what moved, and why, without opening V1."""
    assert [card.id for card in cards] == ["M001", "M002", "M003", "M004", "M005", "M006"]
    for card in cards:
        assert card.v1_status in {"SUPPORTED", "CONDITIONAL", "WEAK", "REJECTED", "UNIDENTIFIED"}
        assert card.v2_status in {"SUPPORTED", "CONDITIONAL", "WEAK", "REJECTED", "UNIDENTIFIED"}
        assert card.change_reason.strip(), f"{card.id} does not say what moved its status"
        assert card.model_evidence, f"{card.id} carries no model evidence"
    changed = [card for card in cards if card.v1_status != card.v2_status]
    assert changed, "a V2 pass that moved no status should be argued, not assumed"
    for card in changed:
        assert card.v2_status != "SUPPORTED", "V2 downgrades unless a measurement says otherwise"


def test_every_card_number_names_the_artifact_it_came_from(cards: tuple[V2Card, ...]) -> None:
    """The evidence line carries the digest, so a reader can check the number."""
    for card in cards:
        for reference in card.model_evidence:
            assert len(reference.artifact_digest) == 64, reference.line()
            assert reference.artifact.strip()
            assert reference.accessor.strip()
            assert reference.value is not None


def test_every_lineage_locator_resolves_to_something_in_the_tree(cards: tuple[V2Card, ...]) -> None:
    """The phase's acceptance: a reader can walk each card's chain back to a source or a run."""
    assert unresolved_locators(cards) == ()
    for card in cards:
        stages = [step.stage for step in card.lineage]
        assert stages[0] == "source", f"{card.id} does not begin at a source"
        assert stages[-1] == "card", f"{card.id} does not end at itself"
        assert "statistic" in stages and "run" in stages


def test_a_lineage_locator_that_names_nothing_is_refused(cards: tuple[V2Card, ...]) -> None:
    """A card citing a renamed registry file must fail the release rather than mislead a reader."""
    from late_ming_lab.synthesis.v2 import LineageStep

    card = cards[0]
    tampered = card.model_copy(
        update={
            "lineage": (
                LineageStep(
                    stage="source",
                    locator="sources/registry/clusters-99-nothing.yaml",
                    detail="a file that was renamed",
                ),
            )
        }
    )
    unresolved = unresolved_locators((tampered,))
    assert unresolved == (f"{card.id} source: sources/registry/clusters-99-nothing.yaml",), (
        unresolved
    )


def test_a_missing_statistic_is_an_error_rather_than_a_stale_value() -> None:
    """The accessor refuses; a card cannot carry a number no artifact holds."""
    from late_ming_lab.synthesis.v2 import SynthesisError, _criterion

    with pytest.raises(SynthesisError):
        _criterion({"report": {"criteria": []}}, "M002.breakdown-in-every-arm-replicate", line="6")


def test_the_chinese_card_reads_every_field_from_the_translation_table(
    cards: tuple[V2Card, ...],
) -> None:
    """No Chinese card may fall back to English: the table must cover each printed field."""
    import yaml

    from late_ming_lab.synthesis.v2 import TRANSLATIONS_PATH, _translation

    table = yaml.safe_load((ROOT / TRANSLATIONS_PATH).read_text(encoding="utf-8"))
    covered = {card["id"] for card in table["cards"]}
    assert covered == {card.id for card in cards}
    for card in cards:
        fields = _translation(card.id)
        assert set(fields) == set(TRANSLATED_FIELDS)
        for key, value in fields.items():
            assert value.strip(), f"{card.id}.{key} is empty in the translation table"
        assert fields["question"] != card.question, "the question was left in English"


def test_the_chinese_card_has_the_same_structure_as_the_english_one() -> None:
    """A translation that drops a section is not a translation of the card."""
    for card in ("M001", "M002", "M003", "M004", "M005", "M006"):
        english = (ROOT / f"docs/mechanisms/v2/{card}.md").read_text(encoding="utf-8")
        chinese = (ROOT / f"docs/mechanisms/v2/zh/{card}.md").read_text(encoding="utf-8")
        en_sections = [line for line in english.splitlines() if line.startswith("## ")]
        zh_sections = [line for line in chinese.splitlines() if line.startswith("## ")]
        assert len(en_sections) == len(zh_sections), (card, en_sections, zh_sections)
        assert len(english.splitlines()) > 20 and len(chinese.splitlines()) > 20


def test_an_unmet_gate_blocks_the_tag_and_is_named(tmp_path: Path) -> None:
    """The one decision the phase must not get wrong: no tag while a gate fails."""
    gates = evaluate_gates(ROOT)
    assert tuple(row["gate"] for row in gates) == (
        "Data",
        "Outcome",
        "Calibration",
        "Sensitivity",
        "Intervention",
        "Hold-out",
        "Policy",
        "Provenance",
        "Release",
    )
    for row in gates:
        assert row["status"] in {"met", "unmet"}
        assert row["evidence"].strip(), f"{row['gate']} is asserted without evidence"
    report = write_limitations(ROOT, gates)
    text = report.read_text(encoding="utf-8")
    for row in gates:
        assert row["gate"] in text
    outcome = build_v2_release(ROOT)
    unmet = outcome.unmet
    assert outcome.tagged == (not unmet)
    if unmet:
        assert "not tagged" in text, "the report must say the candidate carries no tag"
        assert f"`{RELEASE_TAG}`" in text, "the report must name the tag it withholds"
        for gate in unmet:
            assert any(gate in refusal for refusal in outcome.refusals)
    else:
        assert "not tagged" not in text


def _gate(rows: tuple[dict[str, str], ...], name: str) -> dict[str, str]:
    for row in rows:
        if row["gate"] == name:
            return row
    raise AssertionError(f"no {name} gate")


def _tampered_root(tmp_path: Path) -> Path:
    """A copy of the artifacts the gates read, so a check can be tested against a wrong value."""
    import shutil

    for relative in (
        "data/normalized/v2/historical-core-v1/manifest.json",
        "data/protocol/validation-protocol-v2.yaml",
        "data/protocol/threshold-ensemble-v2.yaml",
        "docs/v2/coverage-historical-core-v1.md",
        "docs/v2/hold-out-diagnosis.json",
        "docs/v2/mechanism-variants.json",
        "outputs/v2/p06/posterior.json",
        "outputs/v2/p07/sensitivity-manifest.json",
        "outputs/v2/p08/runtime-arms.json",
        "uv.lock",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / relative, target)
    return tmp_path


def test_a_gate_is_decided_by_content_not_by_a_file_existing(tmp_path: Path) -> None:
    """Every met gate turns on a value in the artifact; an empty shell must fail it."""
    root = _tampered_root(tmp_path)
    healthy = evaluate_gates(root, cards=build_cards(ROOT))
    assert {row["gate"] for row in healthy} == {
        "Data",
        "Outcome",
        "Calibration",
        "Sensitivity",
        "Intervention",
        "Hold-out",
        "Policy",
        "Provenance",
        "Release",
    }
    for row in healthy:
        assert row["status"] in {"met", "unmet"}
        if row["status"] == "met":
            assert row["evidence"].strip(), f"{row['gate']} passed without evidence"
    # An unclassified hold-out failure is not a diagnosis, and the gate must say so.
    diagnosis = json.loads((root / "docs/v2/hold-out-diagnosis.json").read_text())
    diagnosis["diagnosis"] = [{"check": "x", "evidence": {}} for _ in diagnosis["diagnosis"]]
    (root / "docs/v2/hold-out-diagnosis.json").write_text(json.dumps(diagnosis))
    assert _gate(evaluate_gates(root, cards=build_cards(ROOT)), "Hold-out")["status"] == "unmet"
    # An arm that declares an effect and reports no configuration diff is a no-op.
    variants = json.loads((root / "docs/v2/mechanism-variants.json").read_text())
    for arm in variants["arms"]:
        arm["configuration_diff"] = {}
    (root / "docs/v2/mechanism-variants.json").write_text(json.dumps(variants))
    assert _gate(evaluate_gates(root, cards=build_cards(ROOT)), "Intervention")["status"] == "unmet"


def test_the_sensitivity_gate_reads_every_rung_not_only_the_last_two(tmp_path: Path) -> None:
    """One unstable rung early in a ladder is the same failure as an unstable last rung."""
    root = _tampered_root(tmp_path)
    path = root / "outputs/v2/p07/sensitivity-manifest.json"
    payload = json.loads(path.read_text())
    rungs = [dict(level) for level in payload["levels"]]
    rungs[0]["stable"] = False
    for level in rungs[1:]:
        level["stable"] = True
    payload["levels"] = rungs
    path.write_text(json.dumps(payload))
    row = _gate(evaluate_gates(root, cards=build_cards(ROOT)), "Sensitivity")
    assert row["status"] == "unmet", row["evidence"]
    assert rungs[0]["ladder"] in row["evidence"]
    for level in rungs:
        level["stable"] = True
    path.write_text(json.dumps(payload))
    assert _gate(evaluate_gates(root, cards=build_cards(ROOT)), "Sensitivity")["status"] == "met"


def test_the_provenance_gate_reads_the_cards_it_just_built(tmp_path: Path) -> None:
    """Cards without evidence fail the gate, whatever file the pass wrote beside them."""
    root = _tampered_root(tmp_path)
    cards = build_cards(ROOT)
    assert _gate(evaluate_gates(root, cards=cards), "Provenance")["status"] == "met"
    stripped = tuple(card.model_copy(update={"model_evidence": ()}) for card in cards)
    assert _gate(evaluate_gates(root, cards=stripped), "Provenance")["status"] == "unmet"
    assert _gate(evaluate_gates(root, cards=()), "Provenance")["status"] == "unmet"


def test_the_release_pass_is_deterministic_and_does_not_tag_itself() -> None:
    """Same code and same artifacts imply the same bytes, and the tag stays a human step."""
    first = build_v2_release(ROOT)
    bundle = (ROOT / "docs/v2/release-bundle.json").read_text(encoding="utf-8")
    second = build_v2_release(ROOT)
    assert (ROOT / "docs/v2/release-bundle.json").read_text(encoding="utf-8") == bundle
    assert first.card_count == second.card_count == 6
    assert first.tagged == (not first.unmet)
    if first.unmet:
        assert first.refusals, "an unmet gate must produce a stated refusal"
        assert all(RELEASE_TAG in refusal for refusal in first.refusals)


def test_the_bundle_does_not_count_itself_as_a_dirty_tree() -> None:
    """Running the pass twice must not flip `tree_dirty`: the bundle is not part of the answer."""
    first = json.loads((ROOT / "docs/v2/release-bundle.json").read_text())["tree_dirty"]
    build_v2_release(ROOT)
    second = json.loads((ROOT / "docs/v2/release-bundle.json").read_text())["tree_dirty"]
    assert first == second, "the flag depended on a previous pass having run"


def test_the_bundle_binds_the_inputs_a_reader_must_check() -> None:
    """A bundle that omits an input is not a bundle; the manifest names each one."""
    import subprocess

    bundle = json.loads((ROOT / "docs/v2/release-bundle.json").read_text(encoding="utf-8"))
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert bundle["git_sha"] == head, "the bundle must carry the commit that produced it"
    assert "tree_dirty" in bundle, "the bundle must say whether the tree carried changes"
    assert len(bundle["uv_lock_sha256"]) == 64
    assert bundle["candidate"] == RELEASE_TAG
    assert len(bundle["gates"]) == 9
    for section in ("artifacts", "reports"):
        assert bundle[section], f"the bundle records no {section}"
    for entry in bundle["artifacts"]:
        assert entry["sha256"] and entry["path"] and entry["bytes"] > 0
    for entry in bundle["reports"]:
        assert entry["path"] and entry["sha256"]
    assert bundle["translation_version"] == "zh-v2.0"


def test_the_generated_documents_are_the_ones_the_bundle_binds(cards: tuple[V2Card, ...]) -> None:
    """The bundle's report list must cover the documents the cards imply.

    The test reads the tree rather than rebuilding the release: a test that wrote the bundle would
    be editing the thing it checks, and the bundle's own commit would stop describing the code.
    """
    for relative in (
        "docs/mechanisms/v2/cards.yaml",
        "docs/mechanisms/v2/M002.md",
        "docs/mechanisms/v2/zh/index.md",
        "docs/v2/synthesis-v2.md",
        "docs/v2/unresolved-v2.md",
        "docs/v2/data-rights-notice.md",
        "docs/v2/reproduction-guide.md",
    ):
        assert (ROOT / relative).is_file(), f"{relative} was never generated"
    bundle = json.loads((ROOT / "docs/v2/release-bundle.json").read_text(encoding="utf-8"))
    bound = {entry["path"] for entry in bundle["reports"]}
    assert "docs/v2/synthesis-v2.md" in bound
    assert "docs/mechanisms/v2/cards.yaml" in bound
    assert cards, "the cards must exist before their documents can be checked"
