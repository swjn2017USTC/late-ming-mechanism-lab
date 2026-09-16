"""V2.1 closure synthesis: the six cards, the sealed documents, and the handoff.

V2 recomputed the cards from its artifacts. V2.1 adds exactly two things to them, and this module is
both:

```text
the replicate semantics     every card states how many *independent processes* its evidence rests
on,
                            read from `docs/v2_1/replicate-audit.json` rather than from prose. P05's
                            four root seeds are four executions of one deterministic trajectory, and
                            a card that said "4 seeds" was overstating its sample by four
the two decisive contrasts  M002's historical-core gate contrast and M004's closed-credit
comparison,
                            read from `docs/v2_1/decisive-contrasts.json`, which is what moved the
                            two cards' uncertainty rather than their status
```

Nothing else moves. No status changes in V2.1: P11's pre-registered rules kept M002 `CONDITIONAL`
and
M004 `WEAK`, and a phase that finds no change says so rather than manufacturing one.

Three statuses the project requires to be stated plainly stay stated: simulation support is not
historical truth and every card separates the two; rejected, unidentified and unmet are results; and
every frozen pilot is named as one, with the gate it failed and the number it failed by.

The cards reuse V2's vocabulary — `CardStatus`, `EvidenceRef`, `LineageStep`, `Accessor`, `V2Card`
and
the gate evaluator — so a reader compares two phases rather than two conventions.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel, ConfigDict, Field

from late_ming_lab.core.hashing import canonical_json, hash_text
from late_ming_lab.release.bundle import evaluate_gates, unresolved_locators
from late_ming_lab.storage.tables import write_json
from late_ming_lab.synthesis.v2 import (
    CardStatus,
    EvidenceRef,
    LineageStep,
    SynthesisError,
    V2Card,
    _digest,
    _dirty_lines,
    _load,
    code_digest,
)
from late_ming_lab.synthesis.v2 import (
    build_cards as build_v2_cards,
)

#: Where the V2.1 cards and the closure documents live.
CARD_DIRECTORY: Final[str] = "docs/mechanisms/v2_1"
CARD_DIRECTORY_ZH: Final[str] = "docs/mechanisms/v2_1/zh"
CARDS_FILE: Final[str] = "docs/mechanisms/v2_1/cards.yaml"
INDEX_FILE: Final[str] = "docs/mechanisms/v2_1/index.md"
CLOSURE_PATH: Final[str] = "docs/v2_1/closure-report.md"
LIMITATIONS_PATH: Final[str] = "docs/v2_1/limitations.md"
HANDOFF_PATH: Final[str] = "docs/v2_1/handoff.md"
BUNDLE_PATH: Final[str] = "docs/v2_1/release-bundle.json"

#: The translation table: data, not code, so a translator edits one file. It holds the fields whose
#: English changed in V2.1; anything else is resolved from the V2 table, and only when the English
#: it
#: translates is byte-identical. See :func:`_translation`.
TRANSLATIONS_PATH: Final[str] = "data/mechanisms/v2_1-zh.yaml"
V2_TRANSLATIONS_PATH: Final[str] = "data/mechanisms/v2-zh.yaml"
TRANSLATION_VERSION: Final[str] = "zh-v2.1"

#: The two V2.1 artifacts the cards read.
AUDIT_PATH: Final[str] = "docs/v2_1/replicate-audit.json"
CONTRASTS_PATH: Final[str] = "docs/v2_1/decisive-contrasts.json"

#: The window every card's status holds under. One value for all six, because the protocol's
#: whole-run window is what the ensemble, the chains and the contrasts are all read on, and no
#: reserved window is read by any of them.
CARD_WINDOW: Final[str] = "whole-run (the protocol's reporting window); no reserved window is read"

#: The arms each card's evidence rests on, named here so the sample count is a measurement of these
#: arms rather than a number somebody typed. A card's count is the number of *distinct processes*
#: across them, which is why an arm P11 re-ran to the same digest is one process and not two.
CARD_ARMS: Final[dict[str, tuple[str, ...]]] = {
    "M001": ("reference",),
    "M002": ("reference",),
    "M003": (
        "arrears-rules-off",
        "arrears-settlement",
        "arrears-remission",
        "arrears-recovery",
        "reference",
    ),
    "M004": ("elite-mediation-only", "elite-defaults-declared", "elite-accumulation", "reference"),
    "M005": ("band-merge-negative-control", "band-merge-positive-control", "reference"),
    "M006": ("reference",),
}

#: The contrasts a card reads, keyed by the card. M002 and M004 are the two V2.1 ran.
CARD_CONTRASTS: Final[dict[str, str]] = {"M002": "M002", "M004": "M004"}

#: The P11 arms each contrast contributes, so the structural sample count includes them.
CONTRAST_ARMS: Final[dict[str, tuple[str, ...]]] = {
    "M002": ("reference", "gate-open"),
    "M004": ("elite-credit-closed", "elite-accumulation"),
}

#: What a V2.1 card's English fields are, so the translation resolver can compare like with like.
TRANSLATED_FIELDS: Final[tuple[str, ...]] = (
    "name",
    "summary",
    "question",
    "historical_support",
    "historical_challenge",
    "counterexample",
    "falsifier",
    "uncertainty",
    "sample_note",
)

#: The translation table's own labels, read from the same file as the fields.
LABEL_FIELDS: Final[tuple[str, ...]] = (
    "title",
    "question",
    "status",
    "applies",
    "sample",
    "kind",
    "independent_samples",
    "model_evidence",
    "record",
    "support",
    "challenge",
    "counterexample",
    "falsifier",
    "uncertainty",
    "lineage",
    "lineage_note",
    "source_note",
    "index_note",
    "col_card",
    "col_name",
    "col_status",
    "col_samples",
)

#: Everything the pass reads. Declared so a test can build a scratch copy of exactly these rather
#: than writing into the repository.
PASS_INPUTS: Final[tuple[str, ...]] = (
    "docs/mechanisms/v2/cards.yaml",
    "docs/v2/threshold-robustness.json",
    "docs/v2/hold-out-diagnosis.json",
    "docs/v2/mechanism-variants.json",
    "docs/v2_1/replicate-audit.json",
    "docs/v2_1/decisive-contrasts.json",
    "outputs/v2/p06/posterior.json",
    "outputs/v2/p07/sensitivity-manifest.json",
    "outputs/v2/p08/runtime-arms.json",
    "data/protocol/validation-protocol-v2.yaml",
    "data/protocol/threshold-ensemble-v2.yaml",
    "data/normalized/v2/historical-core-v1/manifest.json",
    "uv.lock",
    "pyproject.toml",
)

#: The V2 artifacts the V2.1 bundle binds beside its own, so a reader of either can find the other.
V2_ARTIFACTS: Final[tuple[str, ...]] = (
    "docs/v2/release-bundle.json",
    "docs/mechanisms/v2/cards.yaml",
    "docs/v2/limitations-v2.md",
    "docs/v2/unresolved-v2.md",
)

#: The V2.1 artifacts the bundle binds.
V21_ARTIFACTS: Final[tuple[str, ...]] = (
    AUDIT_PATH,
    CONTRASTS_PATH,
    "docs/v2_1/pilot-disposition.json",
    "docs/v2_1/parameter-registry-findings.json",
)

#: The reports the bundle binds, which are the documents this pass writes.
REPORT_PATHS: Final[tuple[str, ...]] = (
    CLOSURE_PATH,
    LIMITATIONS_PATH,
    HANDOFF_PATH,
    CARDS_FILE,
    INDEX_FILE,
    f"{CARD_DIRECTORY_ZH}/index.md",
)


@dataclass(frozen=True, slots=True)
class SampleSemantics:
    """How many independent processes a card's evidence rests on, and what the count counts."""

    card: str
    structures: tuple[str, ...]
    executions: int
    distinct_processes: int
    counted_by: str

    @property
    def independent_samples(self) -> int:
        return self.distinct_processes

    @property
    def replicate_kind(self) -> str:
        """Whether this card's evidence repeats a process or runs each structure once.

        Where every execution is its own process there is nothing to average over and no repeat to
        discount; where executions outnumber processes, the extra executions are replays of one
        trajectory, which is what P05's four seeds are.
        """
        if self.distinct_processes == self.executions:
            return "one-run-per-structure"
        return "deterministic-replay"

    def sentence(self) -> str:
        """The count in words a reader can act on, singular where one is what there is."""
        processes = _count(self.distinct_processes, "distinct process", "distinct processes")
        samples = _count(self.independent_samples, "independent sample", "independent samples")
        structures = _count(len(self.structures), "arm structure", "arm structures")
        if self.replicate_kind == "deterministic-replay":
            return (
                f"{structures}, {self.executions} executions, {processes} counted by "
                f"{self.counted_by}: {samples}. The declared seeds are replays of one trajectory, "
                "not independent replicates."
            )
        return (
            f"{structures}, {self.executions} executions, {processes} counted by "
            f"{self.counted_by}: one run per structure, no repeats, {samples}."
        )

    def record(self) -> dict[str, Any]:
        return {
            "structures": list(self.structures),
            "executions": self.executions,
            "distinct_processes": self.distinct_processes,
            "counted_by": self.counted_by,
            "independent_samples": self.independent_samples,
            "replicate_kind": self.replicate_kind,
            "sentence": self.sentence(),
        }


def _count(count: int, singular: str, plural: str) -> str:
    """A number and its noun, in the right number, so a count of one does not read as a template."""
    return f"{count} {singular if count == 1 else plural}"


class V21Card(BaseModel):
    """One mechanism card as V2.1 leaves it: the V2 card, plus what P10 and P11 established."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^M\d{3}$")
    name: str
    question: str
    v1_status: CardStatus
    v2_status: CardStatus
    v21_status: CardStatus
    change_reason: str = Field(min_length=1)
    applies_to: dict[str, str]
    replicate_semantics: str = Field(min_length=1)
    independent_samples: int = Field(ge=0)
    sample_basis: str = Field(min_length=1)
    model_evidence: tuple[EvidenceRef, ...]
    historical_support: str = Field(min_length=1)
    historical_challenge: str = Field(min_length=1)
    counterexample: str = Field(min_length=1)
    falsifier: str = Field(min_length=1)
    uncertainty: str = Field(min_length=1)
    lineage: tuple[LineageStep, ...] = Field(min_length=1)

    def moved(self) -> bool:
        return self.v2_status != self.v21_status


@dataclass(slots=True)
class Accessor:
    """Reads one number out of the V2.1 artifacts, recording the file and the digest.

    The same shape as the V2 accessor, over the V2.1 artifacts: a card cannot quote a statistic
    without naming the file it came from and the path inside it.
    """

    root: Path
    cache: dict[str, dict[str, Any]] = field(default_factory=dict)

    def payload(self, relative: str) -> dict[str, Any]:
        if relative not in self.cache:
            self.cache[relative] = _load(self.root, relative)
        return self.cache[relative]

    def ref(self, relative: str, *, accessor: str, value: float | str) -> EvidenceRef:
        return EvidenceRef(
            artifact=relative,
            artifact_digest=_digest(self.root / relative),
            accessor=accessor,
            value=value,
        )


def _number(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise SynthesisError(f"the artifact records {type(value).__name__}, not a number")


def _arm_records(accessor: Accessor) -> dict[str, Mapping[str, Any]]:
    """Every P05 arm the audit measured, keyed by label."""
    payload = accessor.payload(AUDIT_PATH)
    arms = payload.get("arms")
    if not isinstance(arms, list) or not arms:
        raise SynthesisError(f"{AUDIT_PATH} holds no arms")
    records: dict[str, Mapping[str, Any]] = {}
    for entry in arms:
        if not isinstance(entry, dict):
            raise SynthesisError(f"{AUDIT_PATH} holds an arm that is not an object")
        records[str(entry["arm"])] = entry
    return records


def _contrast_runs(accessor: Accessor) -> dict[str, Mapping[str, Any]]:
    """Every P11 arm, keyed by label, with its digest."""
    payload = accessor.payload(CONTRASTS_PATH)
    runs = payload.get("runs")
    if not isinstance(runs, list) or not runs:
        raise SynthesisError(f"{CONTRASTS_PATH} holds no runs")
    return {str(entry["arm"]): entry for entry in runs if isinstance(entry, dict)}


def _p05_digest(accessor: Accessor, label: str) -> str:
    """One P05 arm's digest at the seed the phase declared.

    Read from the phase's own declaration rather than from the audit, because the audit *counts*
    distinct digests and does not carry the digests themselves — and the digest is what decides
    whether two arms are one process.
    """
    payload = accessor.payload("docs/v2/mechanism-variants.json")
    arms = payload.get("arms", [])
    if not isinstance(arms, list):
        raise SynthesisError("docs/v2/mechanism-variants.json holds no arms")
    declared = [int(seed) for seed in payload.get("seeds", [])]
    if not declared:
        raise SynthesisError("docs/v2/mechanism-variants.json declares no seeds")
    for entry in arms:
        if isinstance(entry, dict) and entry.get("arm") == label:
            if int(entry["root_seed"]) != declared[0]:
                continue
            return str(entry["simulation_digest"])
    raise SynthesisError(
        f"docs/v2/mechanism-variants.json holds no {label!r} arm at the first seed"
    )


def _factorial_structures(accessor: Accessor) -> tuple[tuple[str, ...], int]:
    """M001's basis: the factorial cells, which ran at one seed and record no digest."""
    payload = accessor.payload("docs/v2/mechanism-variants.json")
    cells = payload.get("factorial", [])
    if not isinstance(cells, list) or not cells:
        raise SynthesisError("docs/v2/mechanism-variants.json holds no factorial cells")
    labels = tuple(sorted(str(cell["label"]) for cell in cells if isinstance(cell, dict)))
    return labels, len(labels)


def sample_semantics(card_id: str, accessor: Accessor) -> SampleSemantics:
    """How many independent processes one card's evidence rests on.

    The count is the number of *distinct simulation digests* across the arms the card reads, P05's
    and P11's together, because two arms that share a digest are one process: P11 re-ran the
    accumulation arm and reproduced P05's digest exactly, so that arm is one sample and not two.
    """
    if card_id == "M001":
        # The factorial ran at one seed and records no digest; its four cells are four different
        # structures, so the count is by run id and each cell is its own process.
        labels, cells = _factorial_structures(accessor)
        return SampleSemantics(
            card=card_id,
            structures=labels,
            executions=cells,
            distinct_processes=cells,
            counted_by="distinct factorial cell",
        )
    arms = _arm_records(accessor)
    runs = _contrast_runs(accessor)
    processes: dict[str, str] = {}
    structures: list[str] = []
    executions = 0
    for label in CARD_ARMS[card_id]:
        if label not in arms:
            raise SynthesisError(f"{AUDIT_PATH} holds no {label!r} arm")
        processes.setdefault(_p05_digest(accessor, label), label)
        structures.append(label)
        executions += int(arms[label]["executions"])
    contrast = CARD_CONTRASTS.get(card_id)
    if contrast is not None:
        for label in CONTRAST_ARMS[contrast]:
            if label not in runs:
                raise SynthesisError(f"{CONTRASTS_PATH} holds no {label!r} arm")
            processes.setdefault(str(runs[label]["simulation_digest"]), label)
            structures.append(label)
            executions += 1
    return SampleSemantics(
        card=card_id,
        structures=tuple(sorted(set(structures))),
        executions=executions,
        distinct_processes=len(processes),
        counted_by="distinct simulation digest",
    )


#: What each card's V2.1 reason says. The statuses do not move, so every entry either records what
#: V2.1 resolved or says plainly that nothing moved.
CHANGE_REASONS: Final[dict[str, str]] = {
    "M001": (
        "V2.1 leaves the status where V2 put it and corrects the card's own sample statement: the "
        "factorial is four cells at one seed, each cell one deterministic trajectory, so its four "
        "cells are four structures and not four seeds' worth of replicates"
    ),
    "M002": (
        "V2.1 ran the contrast the V2 card said had not been run: on the historical core, opening "
        "the gate the card names contracts the assessable base by 0.929 more than the reference "
        "does — the pre-registered direction and far above the declared effect — so the mechanism "
        "survives on the input the card is about while the card's *breakdown* half stays "
        "threshold-dependent as V2-P03 measured"
    ),
    "M003": (
        "V2.1 changes nothing: the three rules by which an arrears stock can fall were built in "
        "V2, "
        "the strong monotone claim stays rejected, and the card now states that its five arms are "
        "five structures rather than forty samples"
    ),
    "M004": (
        "V2.1 measured the card's own falsifier for the first time: the accumulating branch "
        "contracts the assessable base 0.008 further than the closed-credit arm — the direction "
        "the "
        "card predicts, at a quarter of the declared minimum substantive effect — so the branch is "
        "shown to exist, fire and point the right way, and the status stays WEAK because that is "
        "what the pre-registered rule says a sub-effect difference means"
    ),
    "M005": (
        "V2.1 changes nothing: the merger link is exercised and the concentration reading is "
        "threshold-dependent, and the card now states that its controls are three structures at "
        "one "
        "deterministic trajectory each"
    ),
    "M006": (
        "V2.1 changes nothing: the interface and the observables stay delivered, no rule is built, "
        "and the card states that the reference run it measures is one trajectory replayed four "
        "times, not four samples of an unidentified mechanism"
    ),
}

#: The policy line for the two cards V2.1 ran a contrast on, so the `applies_to` block names the
#: arms the card now rests on rather than only the pilot V2 read.
POLICY_V21: Final[dict[str, str]] = {
    "M002": (
        "the V2-P03 pilot arms, plus V2.1's historical-core contrast: the declared "
        "open-migration-exit arm against the reference"
    ),
    "M004": (
        "the credit channel with and without foreclosure, plus V2.1's contrast: closed credit "
        "against the accumulating branch"
    ),
}

#: The V2.1 uncertainty, for the two cards whose V2 text says something V2.1 made false.
UNCERTAINTY: Final[dict[str, str]] = {
    "M002": (
        "The historical-core contrast has now been run and it holds: the gate arm's contraction "
        "separates from the reference's by 0.929. What stays uncertain is the size, which is a "
        "property of the declared opening — every move cost and both eligibility lines at their "
        "open values — and of the model's land accounting, where an in-region move abandons land "
        "at "
        "the origin that the destination does not receive, so repeated moves erode the base "
        "further "
        "than the population that left would suggest. The *breakdown* half remains threshold- "
        "dependent and is reported at every declared line rather than summarised."
    ),
    "M004": (
        "The card's falsifier is now measured rather than open: the branch fires (51 foreclosures, "
        "13,063.8 mu transferred) and contracts the base 0.008 more than closed credit, which is "
        "the direction the card predicts and a quarter of the declared minimum substantive effect. "
        "Two grade-S assumptions — the foreclosure term and the land share — are what the branch "
        "is "
        "made of, and one deterministic trajectory is what the comparison rests on: a difference "
        "this size is below the level at which this project treats an effect as established."
    ),
}


def _sample_evidence(accessor: Accessor, semantics: SampleSemantics) -> EvidenceRef | None:
    """One measured number behind a card's sample count, or None where the audit holds no such arm.

    The count itself is *derived* — it is the number of distinct processes across the arms — so what
    is referenced is a value an artifact actually holds: one arm's measured independent replicates,
    or the factorial's size. A card citing the derived count as if a file recorded it would be
    quoting a number no artifact holds, which is what the accessor exists to prevent.
    """
    if semantics.card == "M001":
        return accessor.ref(
            "docs/v2/mechanism-variants.json",
            accessor="variants.factorial (cells declared)",
            value=float(semantics.executions),
        )
    arms = _arm_records(accessor)
    for label in CARD_ARMS[semantics.card]:
        if label in arms:
            return accessor.ref(
                AUDIT_PATH,
                accessor=f"replicate-audit.arms[{label}].independent_replicates",
                value=_number(arms[label]["independent_replicates"]),
            )
    return None


def _card_evidence(
    card: V2Card, accessor: Accessor, semantics: SampleSemantics
) -> tuple[EvidenceRef, ...]:
    """The V2 refs, plus what V2.1 measured about this card's sample and its contrast."""
    refs: list[EvidenceRef] = list(card.model_evidence)
    sample = _sample_evidence(accessor, semantics)
    if sample is not None:
        refs.append(sample)
    contrast = CARD_CONTRASTS.get(card.id)
    if contrast is not None:
        payload = accessor.payload(CONTRASTS_PATH)
        entry = payload["contrasts"][contrast]
        assert isinstance(entry, dict)
        refs.append(
            accessor.ref(
                CONTRASTS_PATH,
                accessor="decisive-contrasts.design.trajectories",
                value=_number(payload["design"]["trajectories"]),
            )
        )
        refs.append(
            accessor.ref(
                CONTRASTS_PATH,
                accessor=f"decisive-contrasts.contrasts[{contrast}].difference",
                value=_number(entry["difference"]),
            )
        )
        refs.append(
            accessor.ref(
                CONTRASTS_PATH,
                accessor=f"decisive-contrasts.contrasts[{contrast}].falsifier_fires",
                value="fired" if entry["falsifier_fires"] else "did not fire",
            )
        )
    return tuple(refs)


def _v21_status(card: V2Card, accessor: Accessor) -> CardStatus:
    """The status P11's pre-registered rule recommends, or the V2 status where V2.1 ran no "
    "contrast."""
    contrast = CARD_CONTRASTS.get(card.id)
    if contrast is None:
        return card.v2_status
    payload = accessor.payload(CONTRASTS_PATH)
    for entry in payload["status"]:
        if isinstance(entry, dict) and entry.get("card") == contrast:
            recommended = str(entry["recommended"])
            if recommended not in ("SUPPORTED", "CONDITIONAL", "WEAK", "REJECTED", "UNIDENTIFIED"):
                raise SynthesisError(f"{CONTRASTS_PATH} recommends {recommended!r}, not a status")
            return recommended  # type: ignore[return-value]
    raise SynthesisError(f"{CONTRASTS_PATH} holds no status for {contrast}")


def build_cards(root: str | Path) -> tuple[V21Card, ...]:
    """Every card: the V2 card recomputed, extended with the V2.1 sample semantics and contrasts."""
    repository = Path(root)
    accessor = Accessor(root=repository)
    cards: list[V21Card] = []
    for card in build_v2_cards(repository):
        semantics = sample_semantics(card.id, accessor)
        applies = {
            **card.applies_to,
            **({"policy": POLICY_V21[card.id]} if card.id in POLICY_V21 else {}),
            "window": CARD_WINDOW,
            "sample_size": semantics.sentence(),
        }
        lineage = list(card.lineage)
        lineage[-1] = LineageStep(
            stage="card",
            locator=f"{CARDS_FILE}#{card.id}",
            detail="this card, as V2.1 leaves it",
        )
        cards.append(
            V21Card(
                id=card.id,
                name=card.name,
                question=card.question,
                v1_status=card.v1_status,
                v2_status=card.v2_status,
                v21_status=_v21_status(card, accessor),
                change_reason=CHANGE_REASONS[card.id],
                applies_to=applies,
                replicate_semantics=semantics.replicate_kind,
                independent_samples=semantics.independent_samples,
                sample_basis=semantics.sentence(),
                model_evidence=_card_evidence(card, accessor, semantics),
                historical_support=card.historical_support,
                historical_challenge=card.historical_challenge,
                counterexample=card.counterexample,
                falsifier=card.falsifier,
                uncertainty=UNCERTAINTY.get(card.id, card.uncertainty),
                lineage=tuple(lineage),
            )
        )
    return tuple(cards)


# --------------------------------------------------------------------------------------
# The cards as documents, in both languages
# --------------------------------------------------------------------------------------


def _english_field(card: V21Card, field_name: str) -> str:
    """The English text a translated field renders, so the resolver compares like with like."""
    if field_name == "summary":
        return card.change_reason
    if field_name == "sample_note":
        return card.sample_basis
    return str(getattr(card, field_name))


def _v2_english_field(card: V2Card, field_name: str) -> str:
    """The V2 card's English for the same field; empty where V2 had no such field."""
    if field_name == "summary":
        return card.change_reason
    if field_name == "sample_note":
        return ""
    return str(getattr(card, field_name))


def _table(root: Path, relative: str) -> Mapping[str, Any]:
    path = root / relative
    if not path.is_file():
        raise SynthesisError(f"{relative} is missing: the translation is not in the tree")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SynthesisError(f"{relative} is not a mapping")
    return payload


def _labels(root: Path) -> dict[str, str]:
    """The translated section labels, so no Chinese prose lives in this module."""
    labels = _table(root, TRANSLATIONS_PATH).get("labels", {})
    if not isinstance(labels, dict):
        raise SynthesisError(f"{TRANSLATIONS_PATH} declares no labels")
    missing = [name for name in LABEL_FIELDS if not labels.get(name)]
    if missing:
        raise SynthesisError(f"{TRANSLATIONS_PATH} leaves the labels {missing} untranslated")
    return {name: str(labels[name]) for name in LABEL_FIELDS}


def _entries(root: Path, relative: str) -> dict[str, Mapping[str, Any]]:
    cards = _table(root, relative).get("cards", [])
    if not isinstance(cards, list):
        raise SynthesisError(f"{relative} holds no card entries")
    return {str(entry["id"]): entry for entry in cards if isinstance(entry, dict)}


def _translation(root: Path, card: V21Card, v2_card: V2Card) -> dict[str, str]:
    """Every translated field of one card, or a refusal.

    Two tables, one rule: a field whose English changed in V2.1 must be translated in the V2.1
    table,
    and a field that did not change may take the V2 translation — but only when the English it
    translates is *byte-identical* to the V2 card's. A Chinese card that silently rendered English,
    or that rendered a translation of a sentence the English no longer says, would look translated
    and would not be, so both are errors rather than fallbacks.
    """
    own = _entries(root, TRANSLATIONS_PATH).get(card.id, {})
    previous = _entries(root, V2_TRANSLATIONS_PATH).get(card.id, {})
    resolved: dict[str, str] = {}
    for name in TRANSLATED_FIELDS:
        provided = own.get(name)
        if provided:
            resolved[name] = str(provided)
            continue
        inherited = previous.get(name)
        unchanged = _english_field(card, name) == _v2_english_field(v2_card, name)
        if inherited and unchanged:
            resolved[name] = str(inherited)
            continue
        raise SynthesisError(
            f"{card.id}: {name} is translated neither in {TRANSLATIONS_PATH} nor, unchanged, in "
            f"{V2_TRANSLATIONS_PATH}; rendering it in English would be a translation that is not "
            f"one"
        )
    return resolved


def _english_card(card: V21Card) -> str:
    lines = [
        f"# {card.id} — {card.name}",
        "",
        f"**Question.** {card.question}",
        "",
        f"**Status.** `{card.v1_status}` (V1) → `{card.v2_status}` (V2) → "
        f"`{card.v21_status}` (V2.1). {card.change_reason}",
        "",
        "## Where the status holds",
        "",
    ]
    lines += [f"- **{key}**: {value}" for key, value in sorted(card.applies_to.items())]
    lines += [
        "",
        "## Replicate semantics",
        "",
        f"- **kind**: `{card.replicate_semantics}`",
        f"- **independent samples**: {card.independent_samples}",
        f"- **basis**: {card.sample_basis}",
        "",
        "## Model evidence",
        "",
    ]
    lines += [f"- {ref.line()}" for ref in card.model_evidence]
    lines += [
        "",
        "## The record",
        "",
        f"**Support.** {card.historical_support}",
        "",
        f"**Challenge.** {card.historical_challenge}",
        "",
        f"**Counterexample.** {card.counterexample}",
        "",
        f"**Falsifier.** {card.falsifier}",
        "",
        f"**Uncertainty.** {card.uncertainty}",
        "",
        "## Lineage",
        "",
    ]
    lines += [
        f"{index}. **{step.stage}** — `{step.locator}`: {step.detail}"
        for index, step in enumerate(card.lineage, 1)
    ]
    lines += [
        "",
        "---",
        "",
        "Simulation support is not historical truth. The model evidence above is a statement about",
        "this model under a declared configuration; the record supplies direction, sequence and",
        "constraint, and nothing here is a finding about the past.",
        "",
    ]
    return "\n".join(lines)


def _chinese_card(root: Path, card: V21Card, v2_card: V2Card) -> str:
    """The card in Chinese, with every translated string resolved by rule rather than by "
    "fallback."""
    labels = _labels(root)
    translation = _translation(root, card, v2_card)
    lines = [
        f"# {card.id} — {translation['name']}",
        "",
        f"**{labels['question']}** {translation['question']}",
        "",
        f"**{labels['status']}** `{card.v1_status}` (V1) -> `{card.v2_status}` (V2) -> "
        f"`{card.v21_status}` (V2.1). {translation['summary']}",
        "",
        f"## {labels['applies']}",
        "",
    ]
    lines += [f"- **{key}**: {value}" for key, value in sorted(card.applies_to.items())]
    lines += [
        "",
        f"## {labels['sample']}",
        "",
        f"- **{labels['kind']}**: `{card.replicate_semantics}`",
        f"- **{labels['independent_samples']}**: {card.independent_samples}",
        f"- {translation['sample_note']}",
        "",
        f"## {labels['model_evidence']}",
        "",
    ]
    lines += [f"- {ref.line()}" for ref in card.model_evidence]
    lines += [
        "",
        f"## {labels['record']}",
        "",
        f"**{labels['support']}** {translation['historical_support']}",
        "",
        f"**{labels['challenge']}** {translation['historical_challenge']}",
        "",
        f"**{labels['counterexample']}** {translation['counterexample']}",
        "",
        f"**{labels['falsifier']}** {translation['falsifier']}",
        "",
        f"**{labels['uncertainty']}** {translation['uncertainty']}",
        "",
        f"## {labels['lineage']}",
        "",
        labels["lineage_note"],
        "",
    ]
    lines += [
        f"{index}. **{step.stage}** -- `{step.locator}`: {step.detail}"
        for index, step in enumerate(card.lineage, 1)
    ]
    lines += ["", "---", "", f"{labels['source_note']} ({TRANSLATION_VERSION})", ""]
    return "\n".join(lines)


def _index(root: Path, cards: Sequence[V21Card], *, chinese: bool) -> str:
    labels = _labels(root)
    title = f"# {labels['title']}" if chinese else "# V2.1 mechanism cards"
    note = (
        labels["index_note"]
        if chinese
        else "The Chinese translation lives in `docs/mechanisms/v2_1/zh/`."
    )
    headers = (
        (labels["col_card"], labels["col_name"], labels["col_status"], labels["col_samples"])
        if chinese
        else ("card", "name", "V1 → V2 → V2.1", "independent samples")
    )
    lines = [
        title,
        "",
        note,
        "",
        "| " + " | ".join(headers) + " |",
        "| --- | --- | --- | --- |",
    ]
    for card in cards:
        name = card.name
        if chinese:
            name = _translation(root, card, _v2_card(root, card.id))["name"]
        lines.append(
            f"| `{card.id}` | {name} | `{card.v1_status}` → `{card.v2_status}` → "
            f"`{card.v21_status}` | {card.independent_samples} |"
        )
    lines.append("")
    return "\n".join(lines)


def _v2_card(root: Path, card_id: str) -> V2Card:
    for card in build_v2_cards(root):
        if card.id == card_id:
            return card
    raise SynthesisError(f"the V2 cards hold no {card_id}")


def write_cards(root: str | Path, cards: Sequence[V21Card]) -> tuple[Path, ...]:
    """Write the cards in YAML, in English prose and in Chinese, and return the paths."""
    repository = Path(root)
    english = repository / CARD_DIRECTORY
    chinese = repository / CARD_DIRECTORY_ZH
    english.mkdir(parents=True, exist_ok=True)
    chinese.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "mechanism-cards-v2_1",
        "translation_version": TRANSLATION_VERSION,
        "cards": [card.model_dump(mode="json") for card in cards],
    }
    yaml_path = repository / CARDS_FILE
    yaml_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    written: list[Path] = [yaml_path]
    for card in cards:
        v2_card = _v2_card(repository, card.id)
        en = english / f"{card.id}.md"
        en.write_text(_english_card(card), encoding="utf-8")
        zh = chinese / f"{card.id}.md"
        zh.write_text(_chinese_card(repository, card, v2_card), encoding="utf-8")
        written.extend((en, zh))
    (english / "index.md").write_text(_index(repository, cards, chinese=False), encoding="utf-8")
    (chinese / "index.md").write_text(_index(repository, cards, chinese=True), encoding="utf-8")
    written.extend((english / "index.md", chinese / "index.md"))
    return tuple(written)


# --------------------------------------------------------------------------------------
# The closure documents
# --------------------------------------------------------------------------------------

#: What V2.1 leaves behind for the next project. Four lists, and the split is the point: what can be
#: reused, what was answered and answered negatively, what no amount of this project's compute can
#: change, and what this project already knows it should not spend more on.
REUSABLE: Final[tuple[str, ...]] = (
    "the frozen validation protocol and its window isolation, enforced in code at the one place a "
    "window's numbers are produced (`protocol/freeze.py`, `protocol/outcomes.py`)",
    "the threshold ensemble and its rule that a verdict which moves with a line is reported at "
    "every value of that line (`protocol/thresholds.py`, `protocol/robustness.py`)",
    "the historical core: the CHGIS-derived space, the observed annual climate index and its "
    "declared allocation, with a manifest of inputs, rights and hashes",
    "the event log as the state transition record, with the chain instrumentation for price, "
    "relief, migration and armed bands",
    "the typed artifact accessors and the release bundle: every number bound to a file and a "
    "digest",
    "the no-op detector and the arm declaration model, which refuse a variant that moves nothing "
    "and an ablation that moves something (`experiments/holdout.py`)",
    "the replicate semantics and the audit that measures them, so a replayed seed is never counted "
    "as a sample again (`v2_1/accessors.py`, `experiments/contrasts.py`)",
    "the translation mechanism: a Chinese card resolves every field by rule and refuses a silent "
    "fallback to English (`synthesis/v2_1.py`, `data/mechanisms/*-zh.yaml`)",
)

SEALED_NEGATIVE: Final[tuple[str, ...]] = (
    "M001 stays CONDITIONAL: the inversion follows the extraction policy rather than the price "
    "structure, and one of four factorial cells has no inversion at all",
    "M002's breakdown half stays threshold-dependent: it holds in 0.461 of the ensemble at the "
    "protocol's declared line of six and in 0.000 of it at eight",
    "M003 stays REJECTED: the arrears stock falls under all three rules V2 built, so the strong "
    "monotone claim is contradicted rather than merely unsupported",
    "M004 stays WEAK: the accumulating branch fires and points the right way, and contracts the "
    "base 0.008 further than closed credit — a quarter of the declared minimum substantive effect",
    "M006 stays UNIDENTIFIED: the interface, the observables and the refusal are delivered, and no "
    "source in the registry bounds a mortality rate",
    "V2-P06's calibration ladder is frozen non-converged: location moved 0.449 of the prior range "
    "against a declared 0.1, acceptance 1.000",
    "V2-P07's sensitivity ladders are frozen non-converged: the Morris bootstrap agreed with its "
    "own "
    "top-4 set in 0.00 and 0.01 of resamples, and the largest S1 move was 12.07x the previous "
    "level",
    "V2-P08's runtime arm is a pilot with zero model decisions on the historical core, so M2 is "
    "incomplete rather than met",
    "all four V1 hold-out failures are classified in `docs/v2/hold-out-diagnosis.md`; one was the "
    "forcing, three are structural",
)

NEW_DATA_ONLY: Final[tuple[str, ...]] = (
    "M006 needs a county-resolution mortality or unmet-need series with a level and a range; "
    "without one the card stays UNIDENTIFIED no matter how the model is run",
    "the reserved windows need a posterior that converged before they can be scored; a larger "
    "ladder of the same size of evidence does not make the question different, a new objective "
    "does",
    "regional extrapolation needs data from outside Shaanxi-Henan: the current core's trade, "
    "migration and military links are the model's own construction, not measurements",
    "two declared priors never reach the calibration run (`MilitaryParameters` is not rebuilt by "
    "`SandboxSimulator`), and 19 range-carrying cards are in neither the declared nor the excluded "
    "list; both are registry decisions that need a judgement about what each parameter is for",
    "`interest_rate_monthly`'s central value sits below its own declared range, and "
    "`fiscal_base`'s declared unit and its measurement disagree; both are defects in frozen files "
    "this phase may not edit",
)

NOT_WORTH_MORE: Final[tuple[str, ...]] = (
    "another calibration or sensitivity ladder at the same evidence: the ladders did not fail for "
    "want of particles, and the sensitivity gate's own criterion is the brittle part",
    "a wider runtime fixture corpus: with no historical core coverage the arm is a pilot whatever "
    "its corpus holds, and M2 would still rest on one decision per replicate",
    "national geography before the Shaanxi-Henan mechanisms are decided: it multiplies nodes, not "
    "identifiability",
    "another reader pass over the numbers already published: the band readings carry run-to-run "
    "last-bit variability, and re-reading them changes nothing a reader could act on",
    "re-tuning the historical core's parameters to make a reserved window turn green: that is "
    "fitting to the window the protocol reserves for falsification",
)


def _gate_table(gates: Sequence[Mapping[str, str]]) -> list[str]:
    lines = ["| gate | status | evidence |", "| --- | --- | --- |"]
    lines += [
        f"| {row.get('gate')} | **{row.get('status')}** | {row.get('evidence')} |" for row in gates
    ]
    return lines


def write_closure(
    root: str | Path, cards: Sequence[V21Card], gates: Sequence[Mapping[str, str]]
) -> Path:
    """The closure report: the six cards, what V2.1 established, and what it did not move."""
    repository = Path(root)
    accessor = Accessor(root=repository)
    contrasts = accessor.payload(CONTRASTS_PATH)
    design = contrasts["design"]
    m002 = contrasts["contrasts"]["M002"]
    m004 = contrasts["contrasts"]["M004"]
    statuses = {str(row["card"]): row for row in contrasts["status"]}
    moved = [card for card in cards if card.moved()]
    lines = [
        "<!-- generated by: python -m late_ming_lab.release v2_1 -->",
        "",
        "# V2.1 closure report",
        "",
        "What V2.1 established, and what it leaves where it found it. The project is sealed here: "
        "six mechanism cards recomputed from the artifacts, two contrasts that had not been run, a "
        "replicate semantics that was wrong, and a release candidate that is still not tagged.",
        "",
        "## The six cards",
        "",
    ]
    lines += [
        "| card | name | V1 | V2 | V2.1 | independent samples |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| `{card.id}` | {card.name} | `{card.v1_status}` | `{card.v2_status}` | "
        f"`{card.v21_status}` | {card.independent_samples} |"
        for card in cards
    ]
    lines += [
        "",
        f"**{len(moved)} of {len(cards)} cards changed status in V2.1.** "
        + (
            "V2.1 moved none: the two contrasts it ran were decided by pre-registered rules that "
            "kept M002 `CONDITIONAL` and M004 `WEAK`, and the other four cards were not touched. "
            "A closing phase that finds no change says so."
            if not moved
            else "Moved: " + ", ".join(f"{card.id} → {card.v21_status}" for card in moved)
        ),
        "",
        "## What V2.1 established",
        "",
        "### The replicate semantics were wrong, and are now measured",
        "",
        f"Every historical-core arm is one deterministic trajectory executed once per declared "
        f"seed: "
        f"{design['trajectories']} trajectories carry the two contrasts, and the audit found "
        "`1 independent replicate, not 4` on each of P05's ten arms. A card that said `4 seeds` "
        "was "
        "overstating its sample four-fold. Every card now carries its own count and the basis the "
        "count was taken on, and no V2.1 document renders a one-digest multi-seed execution as "
        "independent process replicates.",
        "",
        "### M002's gate contrast, on the historical core",
        "",
        f"- the assessable base contracts {m002['value_a']:.6f} in the reference and "
        f"{m002['value_b']:.6f} with the gate the card names opened: a paired difference of "
        f"**{m002['difference']:+.6f}**",
        f"- the falsifier — {m002['falsifier']} — "
        f"**{'fired' if m002['falsifier_fires'] else 'did not fire'}**",
        f"- recommendation: `{statuses['M002']['recommended']}` against a V2 status of "
        f"`{statuses['M002']['v2_status']}`; the rule is {statuses['M002']['rule']}",
        "",
        "Both caveats travel with that number: the arm is the declared intervention at its open "
        "values, so its 179,769 cumulative household-moves are 240 months of flow over the same 60 "
        "cohorts rather than distinct households; and an in-region move abandons land at the "
        "origin "
        "that the destination does not receive, so repeated moves erode the base further than the "
        "population that left would suggest.",
        "",
        "### M004's falsifier, measured for the first time",
        "",
        f"- the assessable base contracts {m004['value_a']:.6f} with credit closed and "
        f"{m004['value_b']:.6f} with the accumulating branch: a paired difference of "
        f"**{m004['difference']:+.6f}**",
        f"- the falsifier — {m004['falsifier']} — "
        f"**{'fired' if m004['falsifier_fires'] else 'did not fire'}**, and the branch transfers "
        "13,063.8 mu of land over 51 foreclosures",
        f"- recommendation: `{statuses['M004']['recommended']}` against a V2 status of "
        f"`{statuses['M004']['v2_status']}`, because the difference is below the declared minimum "
        "substantive effect: the branch's existence is measured and its effect is not",
        "",
        "### What stayed shut",
        "",
        "The reserved windows are still unscored. V2-P06's posterior is frozen non-converged and "
        "the isolation rule refuses a hold-out score without its hash, so the hold-out and "
        "extrapolation windows remain what they were: a test this model has not passed.",
        "",
        "## The gates, as the artifacts decide them",
        "",
    ]
    lines += _gate_table(gates)
    unmet = [row for row in gates if row.get("status") != "met"]
    lines += [
        "",
        f"**{len(gates) - len(unmet)} of {len(gates)} gates are met**, exactly as in V2: V2.1 adds "
        "no measurement to the calibration, sensitivity or policy question, and it does not move a "
        "gate to make the seal look better. `docs/v2_1/limitations.md` states each one.",
        "",
        "## What this report is not",
        "",
        "- not a claim about the past: every number above is a statement about this model under a "
        "declared configuration, and the cards separate model evidence from the record",
        "- not a converged result: three gates are unmet and are carried as limitations",
        "- not a release: no tag is created, here or by any other V2.1 document",
        "",
    ]
    return _write(repository / CLOSURE_PATH, lines)


def write_limitations(root: str | Path, gates: Sequence[Mapping[str, str]]) -> Path:
    """The limitations: the nine gates, and every defect V2.1 found and did not repair."""
    repository = Path(root)
    accessor = Accessor(root=repository)
    registry = accessor.payload("docs/v2_1/parameter-registry-findings.json")
    unmet = [row for row in gates if row.get("status") != "met"]
    lines = [
        "<!-- generated by: python -m late_ming_lab.release v2_1 -->",
        "",
        "# V2.1 limitations, and why the candidate is still not tagged",
        "",
        "A tag is created only when every declared gate passes, and the gates are the ones V2 "
        "declared. V2.1 adds evidence to two cards and corrects one sample statement; it closes no "
        "gate, and this file says which ones hold and which do not.",
        "",
        "## The gates",
        "",
    ]
    lines += _gate_table(gates)
    lines += [
        "",
        f"**{len(gates) - len(unmet)} of {len(gates)} gates are met.** The unmet ones are carried "
        "as limitations rather than closed by argument:",
        "",
    ]
    lines += [f"- **{row.get('gate')}** — {row.get('evidence')}" for row in unmet]
    lines += [
        "",
        "## What V2.1 corrected, and what it did not",
        "",
        "- **A sample statement on every card was wrong.** P05's four root seeds are four "
        "executions of one deterministic trajectory — one independent replicate, not four — and "
        "the V2 cards described them as `4 seeds`. Every V2.1 card carries the measured count and "
        "its basis. The V2 documents themselves are not rewritten: they are the record of what V2 "
        "said.",
        "- **Two contradictions were resolved by measurement.** M002's card said the historical "
        "core's gate contrast had not been run and M004's said its falsifier had not been "
        "measured; "
        "both are now run and both cards carry the result. Neither status moved.",
        "- **Three defects are reported rather than repaired**, because repairing them would "
        "change "
        "a frozen artifact:",
        f"  - `interest_rate_monthly`'s central value sits below its own declared range, and "
        f"{registry['unclassified_numeric']} range-carrying cards are in neither the calibration "
        "declaration nor the excluded list",
        "  - two declared priors never reach the calibration run: `SandboxSimulator` cannot "
        "rebuild `MilitaryParameters`, so the draw is hashed into the run's identity and dropped",
        "  - a derived band reading is not bit-reproducible: `analysis/military.py::band_series` "
        "reduces a parallel `group_by`, so two evaluations of one byte-identical log can differ in "
        "the last bit. The audit compares readings at 12 significant digits for that reason",
        f"- **The Chinese cards are a translation of the English originals at "
        f"`{TRANSLATION_VERSION}`**, and the resolver refuses a fallback: a field whose English "
        "moved in V2.1 must be retranslated, and a field that did not inherits the V2 translation "
        "only when the English it translates is byte-identical. Locators, digests and statistics "
        "stay in their source form.",
        "- **`fiscal_base` declares a unit its measurement does not have.** The protocol says "
        "`share of starting mu` and `form: vector` over mu measurements, so the 0.02 minimum "
        "substantive effect has to be applied to the relative change by hand. Every phase reading "
        "this outcome makes the same choice; the protocol is frozen and is not edited here.",
        "",
        "## What may still be released",
        "",
        "The tag is withheld; the artifacts are not. Every document in `docs/v2_1/` and "
        "`docs/mechanisms/v2_1/` is reproducible offline from the tree, the bundle binds them by "
        "SHA-256, and the unmet gates are printed above with the number that failed each one.",
        "",
    ]
    return _write(repository / LIMITATIONS_PATH, lines)


def write_handoff(root: str | Path) -> Path:
    """The handoff: what to reuse, what is answered, what needs new data, what not to repeat."""
    repository = Path(root)
    accessor = Accessor(root=repository)
    audit = accessor.payload(AUDIT_PATH)
    register = audit["register"]
    lines = [
        "<!-- generated by: python -m late_ming_lab.release v2_1 -->",
        "",
        "# Handoff",
        "",
        "V2.1 is this project's last phase. This is what the next one should take, what it should "
        "not repeat, and what no further work on *this* repository can settle.",
        "",
        "The split is the deliverable. A handoff that listed only accomplishments would invite the "
        "next project to re-run what already failed, and one that listed only failures would throw "
        "away the parts that work.",
        "",
        "## 1. Reusable infrastructure",
        "",
    ]
    lines += [f"- {item}" for item in REUSABLE]
    lines += [
        "",
        "## 2. Sealed negative results",
        "",
        "These are results, not gaps. Each was measured, each is published with the number that "
        "decided it, and none should be re-run hoping for a different answer from the same "
        "evidence.",
        "",
    ]
    lines += [f"- {item}" for item in SEALED_NEGATIVE]
    lines += [
        "",
        "## 3. Only new data can change these",
        "",
    ]
    lines += [f"- {item}" for item in NEW_DATA_ONLY]
    lines += [
        "",
        "## 4. Not worth more compute on this model",
        "",
    ]
    lines += [f"- {item}" for item in NOT_WORTH_MORE]
    lines += [
        "",
        "## The state of the artifacts",
        "",
        f"- P05's arm register: {register['arms']} arms, {register['declared_runs']} runs, "
        f"{len(register['declared_seeds'])} declared seeds, "
        f"{len(register['missing_run_ids'])} missing and "
        f"{len(register['undeclared_run_ids'])} undeclared",
        f"- the two contrasts: {accessor.payload(CONTRASTS_PATH)['design']['trajectories']} "
        "trajectories at one seed, `seed_is_a_replicate_axis: false`",
        "- the frozen pilots: `outputs/v2/p06/posterior.json` (non-converged), "
        "`outputs/v2/p07/sensitivity-manifest.json` (four unsettled rungs), "
        "`outputs/v2/p08/runtime-arms.json` (zero model decisions)",
        "- the bundles: `docs/v2/release-bundle.json` for V2, `docs/v2_1/release-bundle.json` for "
        "V2.1, each binding its own artifacts and reports by SHA-256",
        "",
        "## One recommendation",
        "",
        "If this work continues, it should continue as a new project with a new question: the "
        "infrastructure above is reusable, the mechanism statuses are settled at the level this "
        "evidence supports, and the reserved windows are a test this model has not passed rather "
        "than a result it can be argued into.",
        "",
    ]
    return _write(repository / HANDOFF_PATH, lines)


def _write(path: Path, lines: Sequence[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# --------------------------------------------------------------------------------------
# The bundle, and the pass
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClosureOutcome:
    """What the closure pass produced, and the gates it did not close."""

    card_count: int
    moved: int
    gates: tuple[dict[str, str], ...]
    written: tuple[Path, ...]
    bundle: Path
    refusals: tuple[str, ...]

    @property
    def unmet(self) -> tuple[str, ...]:
        return tuple(row["gate"] for row in self.gates if row["status"] != "met")


def _tree_dirty(root: Path) -> bool:
    """Whether the working tree carries uncommitted changes, with this bundle excluded.

    The bundle's own bytes are never part of the answer: including them would flip the flag between
    two consecutive passes, which is the one thing a generated artifact must not do.
    """
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):  # pragma: no cover
        return False
    return bool(_dirty_lines(completed.stdout, bundle_path=BUNDLE_PATH))


def _git_sha(root: Path) -> str:
    """The commit the bundle was built at, or empty outside a repository."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):  # pragma: no cover
        return ""


def build_bundle(
    root: str | Path,
    *,
    git_sha: str,
    gate_rows: Sequence[Mapping[str, str]],
    tree_dirty: bool | None = None,
) -> Path:
    """Write the V2.1 bundle: code, commit, lock, artifacts, cards, reports and translation version.

    The candidate tag V2 withheld is the same one here, and it is still not created. What the bundle
    adds to V2's is the V2.1 artifacts and reports, so a reader of either release can find the other
    and check that the cards' numbers come from files that exist.
    """
    repository = Path(root)
    artifacts: list[dict[str, object]] = []
    for release, paths in (("V2", V2_ARTIFACTS), ("V2.1", V21_ARTIFACTS)):
        for relative in paths:
            candidate = repository / relative
            if not candidate.is_file():
                raise SynthesisError(f"the bundle names {relative}, which is not on disk")
            artifacts.append(
                {
                    "path": relative,
                    "release": release,
                    "sha256": _digest(candidate),
                    "bytes": candidate.stat().st_size,
                }
            )
    reports = []
    for relative in REPORT_PATHS:
        candidate = repository / relative
        reports.append(
            {
                "path": relative,
                "sha256": _digest(candidate) if candidate.is_file() else "",
                "present": candidate.is_file(),
            }
        )
        if not candidate.is_file():
            raise SynthesisError(f"the bundle names the report {relative}, which is not on disk")
    lock = repository / "uv.lock"
    sources_digest, code_files = code_digest(repository)
    payload: dict[str, object] = {
        "schema_version": "release-bundle-v2_1",
        "candidate": "v0.2.0-rc1",
        "tag_created": False,
        "git_sha": git_sha,
        "tree_dirty": _tree_dirty(repository) if tree_dirty is None else tree_dirty,
        "code_digest": sources_digest,
        "code_files": code_files,
        "pyproject_sha256": _digest(repository / "pyproject.toml")
        if (repository / "pyproject.toml").is_file()
        else "",
        "uv_lock_sha256": _digest(lock) if lock.is_file() else "",
        "artifacts": artifacts,
        "reports": reports,
        "cards": [f"{CARD_DIRECTORY}/{card}.md" for card in _card_ids()],
        "translation_version": TRANSLATION_VERSION,
        "gates": [dict(row) for row in gate_rows],
    }
    payload["bundle_hash"] = hash_text(canonical_json(payload))
    path = repository / BUNDLE_PATH
    write_json(path, payload)
    return path


def _card_ids() -> tuple[str, ...]:
    return tuple(f"M{index:03d}" for index in range(1, 7))


def run_pass(root: str | Path = ".") -> ClosureOutcome:
    """Recompute the cards, write every document and the bundle, and report the gates.

    The tag is decided here but never created: a pass that tagged itself would make the gate
    decorative, and the decision this evidence supports is that there is no tag.
    """
    repository = Path(root)
    cards = build_cards(repository)
    written: list[Path] = list(write_cards(repository, cards))
    gates = tuple(evaluate_gates(repository, cards=cards))
    written.append(write_closure(repository, cards, gates))
    written.append(write_limitations(repository, gates))
    written.append(write_handoff(repository))
    unresolved = unresolved_locators(cards)
    if unresolved:
        raise SynthesisError("the lineage does not resolve: " + "; ".join(unresolved[:3]))
    written.append(build_bundle(repository, git_sha=_git_sha(repository), gate_rows=gates))
    unmet = tuple(row["gate"] for row in gates if row["status"] != "met")
    return ClosureOutcome(
        card_count=len(cards),
        moved=sum(1 for card in cards if card.moved()),
        gates=gates,
        written=tuple(written),
        bundle=repository / BUNDLE_PATH,
        refusals=tuple(f"{gate}: publish as a limitation, do not tag v0.2.0-rc1" for gate in unmet),
    )


__all__ = [
    "AUDIT_PATH",
    "BUNDLE_PATH",
    "CARDS_FILE",
    "CARD_ARMS",
    "CARD_CONTRASTS",
    "CARD_DIRECTORY",
    "CARD_DIRECTORY_ZH",
    "CARD_WINDOW",
    "CLOSURE_PATH",
    "CONTRASTS_PATH",
    "HANDOFF_PATH",
    "INDEX_FILE",
    "LIMITATIONS_PATH",
    "NEW_DATA_ONLY",
    "NOT_WORTH_MORE",
    "PASS_INPUTS",
    "REPORT_PATHS",
    "REUSABLE",
    "SEALED_NEGATIVE",
    "TRANSLATED_FIELDS",
    "TRANSLATIONS_PATH",
    "TRANSLATION_VERSION",
    "V2_ARTIFACTS",
    "V21_ARTIFACTS",
    "Accessor",
    "ClosureOutcome",
    "SampleSemantics",
    "V21Card",
    "build_bundle",
    "build_cards",
    "run_pass",
    "sample_semantics",
    "write_cards",
    "write_closure",
    "write_handoff",
    "write_limitations",
]
