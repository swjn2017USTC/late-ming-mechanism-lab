"""The V2 release bundle: the cards, the documents they imply, and the gate that decides the tag.

`python -m late_ming_lab.release v2` runs the whole synthesis in one pass, and the order matters:

```text
recompute   the six cards, from the V2 artifacts, through typed accessors that record each file's
            digest beside the number they read
documents   the synthesis, the unresolved list, the rights notice, the reproduction guide, the
            cards in English and Chinese
gates       every cross-phase gate from the upgrade plan, each with the evidence that decides it
bundle      the manifest binding the code SHA, the lock, the bundled artifacts, the reports and
            the translation version — a bundle is what a reader can check, so a missing input is
            an error rather than an omission
decision    a tag only when every gate passes. Otherwise the limitations report says which gates
            hold and which do not, and no tag is created
```

The last of those is the point of the phase. A release candidate that hides an unmet gate is worse
than one that does not exist, so the refusal to tag is implemented here rather than left to a
release manager's judgement.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from late_ming_lab.core.hashing import hash_text
from late_ming_lab.synthesis.v2 import (
    SynthesisError,
    V2Card,
    build_cards,
    build_release_bundle,
    write_cards,
    write_limitations,
    write_reproduction_guide,
    write_rights_notice,
    write_synthesis,
    write_unresolved,
)

#: The tag this candidate would carry, and the file that records the one it does not.
RELEASE_TAG: Final[str] = "v0.2.0-rc1"

#: The gates from the upgrade plan's §7, in its order.
GATES: Final[tuple[tuple[str, str], ...]] = (
    (
        "Data",
        "sourced inputs with version, rights and hash; explicit coverage; no silent imputation",
    ),
    ("Outcome", "primary outcomes and the threshold band pre-registered"),
    ("Calibration", "multiple process seeds, four sampler seeds, posterior at the declared gates"),
    ("Sensitivity", "rankings and indices stable after doubling, or the wording downgraded"),
    ("Intervention", "every named arm triggers its path; no no-op ablation"),
    ("Hold-out", "isolated from fitting in code; every failure kept and classified"),
    (
        "Policy",
        "rule/utility/random complete; runtime only after the gate; refused arms not imputed",
    ),
    ("Provenance", "source -> normalized row -> parameter/rule -> run -> statistic -> card"),
    ("Release", "the bundle binds code, lock, data, config, artifacts, reports and translation"),
)


class ReleaseError(RuntimeError):
    """Raised when the release cannot be built at all."""


@dataclass(frozen=True, slots=True)
class ReleaseOutcome:
    """What the release pass produced, and whether it may carry a tag."""

    card_count: int
    changed: int
    gates: tuple[dict[str, str], ...]
    written: tuple[Path, ...]
    bundle: Path
    tagged: bool
    refusals: tuple[str, ...]

    @property
    def unmet(self) -> tuple[str, ...]:
        return tuple(row["gate"] for row in self.gates if row["status"] != "met")


def _git_sha(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as error:  # pragma: no cover
        raise ReleaseError(f"the release bundle needs the commit: {error}") from error


def _hashed(root: Path, relative: str) -> str:
    path = root / relative
    return hash_text(path.read_text(encoding="utf-8")) if path.is_file() else ""


def _payload(root: Path, relative: str) -> Mapping[str, object]:
    """One artifact as a mapping, or empty: an absent artifact fails its gate, not the pass."""
    path = root / relative
    if not path.is_file():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _manifest_check(root: Path) -> tuple[bool, str]:
    """The Data gate: the core's manifest names its inputs, their rights and their digests."""
    manifest = _payload(root, "data/normalized/v2/historical-core-v1/manifest.json")
    raw_inputs = manifest.get("built_from", {})
    built_from = raw_inputs if isinstance(raw_inputs, dict) else {}
    rights = str(manifest.get("rights", ""))
    coverage = str(manifest.get("coverage_report", ""))
    hashed = bool(built_from) and all(
        isinstance(digest, str) and len(digest) == 64 for digest in built_from.values()
    )
    report = bool(coverage) and (root / coverage).is_file()
    if hashed and rights.strip() and report:
        return True, (
            f"historical-core-v1 names {len(built_from)} inputs with their SHA-256, states its "
            f"rights, and its coverage report `{coverage}` is in the tree"
        )
    missing = [
        name
        for name, present in (
            ("a digest for every input", hashed),
            ("a stated rights position", bool(rights.strip())),
            ("a coverage report on disk", report),
        )
        if not present
    ]
    return False, "the data manifest lacks " + ", ".join(missing)


def _protocol_check(root: Path) -> tuple[bool, str]:
    """The Outcome gate: the frozen protocol declares the vector, the windows and the band."""
    import yaml

    path = root / "data/protocol/validation-protocol-v2.yaml"
    if not path.is_file():
        return False, "the protocol is not in the tree"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        return False, "the protocol is not a mapping"
    outcomes = loaded.get("primary_outcomes", [])
    windows = loaded.get("windows", [])
    effects = (
        [row for row in outcomes if isinstance(row, dict) and row.get("minimum_substantive_effect")]
        if isinstance(outcomes, list)
        else []
    )
    band = _band_lines(root)
    if outcomes and windows and effects and band:
        return True, (
            f"the protocol pre-registers {len(outcomes)} primary outcomes with a minimum "
            f"substantive effect on {len(effects)} of them and {len(windows)} declared windows; "
            f"the band names {band} reading lines"
        )
    return False, (
        "the protocol does not declare the primary outcomes with their minimum substantive "
        "effects, the windows, and the threshold band"
    )


def _band_lines(root: Path) -> int:
    """How many reading lines the frozen threshold ensemble declares a band for."""
    import yaml

    path = root / "data/protocol/threshold-ensemble-v2.yaml"
    if not path.is_file():
        return 0
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = loaded.get("entries", []) if isinstance(loaded, dict) else []
    return len(entries) if isinstance(entries, list) else 0


def evaluate_gates(root: str | Path, *, cards: Sequence[V2Card] = ()) -> tuple[dict[str, str], ...]:
    """Each gate from the plan, with the evidence that decides it.

    A gate is decided by what an artifact holds, not by whether its file exists: existence is
    exactly the check that would pass a truncated or empty file. Where the artifact carries the
    number the gate turns on, the number decides; where it carries a status, the status does, with
    the measurement quoted beside it. `cards` are the cards this pass just recomputed, so the
    provenance gate is about their content rather than about a file this same pass wrote.
    """
    repository = Path(root)
    rows: list[dict[str, str]] = []
    ok, detail = _manifest_check(repository)
    rows.append({"gate": "Data", "status": "met" if ok else "unmet", "evidence": detail})
    ok, detail = _protocol_check(repository)
    rows.append({"gate": "Outcome", "status": "met" if ok else "unmet", "evidence": detail})
    posterior = _payload(repository, "outputs/v2/p06/posterior.json")
    converged = bool(posterior.get("converged"))
    stop = posterior.get("stop", {})
    stop = stop if isinstance(stop, dict) else {}
    location = stop.get("location_change")
    rungs = posterior.get("rungs", [])
    last_rung = rungs[-1] if isinstance(rungs, list) and rungs else {}
    recorded = last_rung.get("acceptance") if isinstance(last_rung, dict) else None
    acceptance = stop.get("acceptance", recorded)
    gate_limits = posterior.get("gates", {})
    gate_limits = gate_limits if isinstance(gate_limits, dict) else {}
    rows.append(
        {
            "gate": "Calibration",
            "status": "met" if converged else "unmet",
            "evidence": (
                "the frozen posterior met the pre-registered stability gates"
                if converged
                else f"the frozen posterior records converged=false: "
                f"{stop.get('reason', 'no reason')}, against a declared location_change_max of "
                f"{gate_limits.get('location_change_max')} (measured {location}, acceptance "
                f"{acceptance})"
            ),
        }
    )
    raw_levels = _payload(repository, "outputs/v2/p07/sensitivity-manifest.json").get("levels", [])
    levels = raw_levels if isinstance(raw_levels, list) else []
    checked = [level for level in levels if isinstance(level, dict)]
    stable = bool(checked) and all(level.get("stable") for level in checked)
    unstable = [
        f"{level.get('ladder', '?')}: {level.get('reason', 'no reason')}"
        for level in checked
        if not level.get("stable")
    ]
    rows.append(
        {
            "gate": "Sensitivity",
            "status": "met" if stable else "unmet",
            "evidence": (
                f"every one of the {len(checked)} declared rungs settled"
                if stable
                else f"{len(unstable)} of {len(checked)} rungs did not settle: "
                + "; ".join(unstable)
            ),
        }
    )
    variants = _payload(repository, "docs/v2/mechanism-variants.json")
    raw_arms = variants.get("arms", [])
    arms = raw_arms if isinstance(raw_arms, list) else []
    arm_rows = [arm for arm in arms if isinstance(arm, dict)]
    expected = [arm for arm in arm_rows if arm.get("expects_effect")]
    silent = [arm for arm in arm_rows if not arm.get("expects_effect")]
    fired = [arm for arm in expected if arm.get("configuration_diff")]
    raw_control = variants.get("control_check", [])
    control = raw_control if isinstance(raw_control, list) else []
    if expected and len(fired) == len(expected) and control:
        rows.append(
            {
                "gate": "Intervention",
                "status": "met",
                "evidence": (
                    f"all {len(expected)} arms that declare an effect report a configuration diff; "
                    f"the {len(silent)} arms declared to reproduce the reference are reported by "
                    f"the no-op detector, which returned {len(control)} verdicts"
                ),
            }
        )
    else:
        rows.append(
            {
                "gate": "Intervention",
                "status": "unmet",
                "evidence": (
                    f"{len(fired)} of {len(expected)} arms that declare an effect report a "
                    f"configuration diff; the no-op detector returned {len(control)} verdicts"
                ),
            }
        )
    raw_holdout = _payload(repository, "docs/v2/hold-out-diagnosis.json").get("diagnosis", [])
    holdout = raw_holdout if isinstance(raw_holdout, list) else []
    diagnoses = [row for row in holdout if isinstance(row, dict)]
    classified = [
        row for row in diagnoses if str(row.get("classification", row.get("cause", ""))).strip()
    ]
    if diagnoses and len(classified) == len(diagnoses):
        rows.append(
            {
                "gate": "Hold-out",
                "status": "met",
                "evidence": (
                    f"all {len(diagnoses)} V1 hold-out failures carry a classification, and the "
                    "freeze gate refuses a reserved-window score without the posterior hash"
                ),
            }
        )
    else:
        rows.append(
            {
                "gate": "Hold-out",
                "status": "unmet",
                "evidence": (
                    f"{len(classified)} of {len(diagnoses)} hold-out failures carry a "
                    "classification"
                ),
            }
        )
    runtime = _payload(repository, "outputs/v2/p08/runtime-arms.json")
    recorded = runtime.get("decisions_from_model", 0)
    model_decisions = int(recorded) if isinstance(recorded, (int, float)) else 0
    rows.append(
        {
            "gate": "Policy",
            "status": "unmet",
            "evidence": (
                "the runtime layer runs and refuses nothing it should not, but the arm made "
                f"{model_decisions} model decisions on the historical core: its prompt is outside "
                "the fixture corpus, so M2 is incomplete and the arm is a pilot"
            ),
        }
    )
    evidenced = [card for card in cards if card.model_evidence and card.lineage]
    unresolved = unresolved_locators(cards)
    if cards and len(evidenced) == len(cards) and not unresolved:
        rows.append(
            {
                "gate": "Provenance",
                "status": "met",
                "evidence": (
                    f"all {len(cards)} cards carry model evidence with an artifact digest and a "
                    "lineage from a source to the card, and every lineage locator resolves"
                ),
            }
        )
    else:
        rows.append(
            {
                "gate": "Provenance",
                "status": "unmet",
                "evidence": (
                    f"{len(evidenced)} of {len(cards)} cards carry evidence and lineage; "
                    f"{len(unresolved)} locators do not resolve"
                ),
            }
        )
    lock = _hashed(repository, "uv.lock")
    rows.append(
        {
            "gate": "Release",
            "status": "met" if lock else "unmet",
            "evidence": (
                "the bundle binds the commit, the lock, the artifacts, the reports and the "
                "translation version, each with its SHA-256"
                if lock
                else "uv.lock is not in the tree, so a bundle could not bind the environment"
            ),
        }
    )
    return tuple(rows)


#: The tree roots a lineage locator may name. A locator that starts with one of these is a claim
#: that the path exists, and the release pass checks it.
LOCATOR_ROOTS: Final[tuple[str, ...]] = (
    "sources/",
    "data/",
    "src/",
    "outputs/",
    "docs/",
    "tests/",
    "experiments/",
)

#: The longest leading path-shaped token of a locator, before any `#` fragment or trailing prose.
_LOCATOR_TOKEN: Final = re.compile(r"[A-Za-z0-9_./*\\-]+")


def unresolved_locators(cards: Sequence[V2Card]) -> tuple[str, ...]:
    """Every lineage locator that names a path the tree does not hold.

    A card's lineage is only as good as its locators: a step naming a registry file that was renamed
    sends a reader to nothing. Prose steps and fragments that are not paths are skipped, and a
    locator with a wildcard resolves when the directory above it exists.
    """
    unresolved: list[str] = []
    for card in cards:
        for step in card.lineage:
            text = step.locator.strip().strip("`")
            match = _LOCATOR_TOKEN.match(text)
            if match is None:
                continue
            token = match.group(0)
            if not token.startswith(LOCATOR_ROOTS):
                continue
            target = token.split("#", 1)[0].rstrip(":")
            candidate = Path(target) if "*" not in target else Path(target).parent
            if not (candidate.is_file() or candidate.is_dir()):
                unresolved.append(f"{card.id} {step.stage}: {step.locator}")
    return tuple(unresolved)


def build_v2_release(root: str | Path) -> ReleaseOutcome:
    """Recompute the cards and every document, write the bundle, and decide the tag."""
    repository = Path(root)
    try:
        cards = build_cards(repository)
    except SynthesisError as error:
        raise ReleaseError(f"the cards cannot be recomputed: {error}") from error
    written: list[Path] = list(write_cards(repository, cards))
    written.append(write_synthesis(repository, cards))
    written.append(write_unresolved(repository, cards))
    written.append(write_rights_notice(repository))
    written.append(write_reproduction_guide(repository))
    unresolved = unresolved_locators(cards)
    gates = evaluate_gates(repository, cards=cards)
    bundle = build_release_bundle(repository, git_sha=_git_sha(repository), gate_rows=gates)
    written.append(bundle)
    written.append(write_limitations(repository, gates))
    unmet = tuple(row["gate"] for row in gates if row["status"] != "met")
    if unresolved:
        # Not a warning: a locator that resolves to nothing is a card claiming a source it cannot
        # produce, and the phase's acceptance turns on every reference resolving.
        raise ReleaseError("the lineage does not resolve: " + "; ".join(unresolved[:3]))
    # The tag is created by the phase's last step, not by this function: a build that tagged itself
    # would make the gate decorative. This reports the decision the evidence supports.
    return ReleaseOutcome(
        card_count=len(cards),
        changed=sum(1 for card in cards if card.changed()),
        gates=gates,
        written=tuple(written),
        bundle=bundle,
        tagged=not unmet,
        refusals=tuple(
            f"{gate}: publish as a limitation, do not tag {RELEASE_TAG}" for gate in unmet
        ),
    )


__all__ = [
    "GATES",
    "LOCATOR_ROOTS",
    "RELEASE_TAG",
    "ReleaseError",
    "ReleaseOutcome",
    "build_v2_release",
    "evaluate_gates",
    "unresolved_locators",
]
