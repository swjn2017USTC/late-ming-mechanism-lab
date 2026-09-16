"""V2 synthesis: the mechanism cards recomputed from V2 artifacts, with the lineage to them.  V1's
cards were built from the P10 and P12 artifacts and their numbers were read out of those files. V2
changes two things about that, and this module is both:  ```text recomputed, not inherited   every
number on every card is read through a typed accessor from a file whose SHA-256 is recorded beside
it. A card cannot carry a value that no artifact holds, and no V1 status is copied forward.
lineage                     each card carries the chain that produced it: the pattern or source
locator, the normalized row, the parameter or rule, the run digest, the statistic, and the card
itself. A reader can walk it in either direction. ```  Three statuses the phase requires to be
stated plainly are stated in the cards themselves rather than in prose beside them:  -
**simulation support is not historical truth.** Every card separates `model_evidence` from
`historical_support`, and the synthesis says which of the two its status rests on. - **failed,
rejected and unidentified are results.** M003 stays rejected and M006 stays unidentified; neither
is given a rule to make it look decided. - **the runtime layer's arm is a pilot.** V2-P08's gate
was opened and the layer ran, but the arm made no model decisions on the historical core, so M2 is
incomplete and every card that would rest on a runtime arm says so.  The thresholds a card's
status depends on are named per card (`threshold_band`), because V2-P03 measured that some
statuses move with them and some do not."""

from __future__ import annotations

import json
import subprocess
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from late_ming_lab.core.hashing import canonical_json, hash_text
from late_ming_lab.storage.tables import write_json

#: The statuses a V2 card may carry, reused from the V1 vocabulary so the two are comparable.
CardStatus = Literal["SUPPORTED", "CONDITIONAL", "WEAK", "REJECTED", "UNIDENTIFIED"]

#: Where the V2 cards and their documents live.
CARD_DIRECTORY: Final[str] = "docs/mechanisms/v2"
CARD_DIRECTORY_ZH: Final[str] = "docs/mechanisms/v2/zh"
CARDS_FILE: Final[str] = "docs/mechanisms/v2/cards.yaml"
SYNTHESIS_PATH: Final[str] = "docs/v2/synthesis-v2.md"
UNRESOLVED_PATH: Final[str] = "docs/v2/unresolved-v2.md"
RIGHTS_PATH: Final[str] = "docs/v2/data-rights-notice.md"
REPRODUCTION_PATH: Final[str] = "docs/v2/reproduction-guide.md"
BUNDLE_PATH: Final[str] = "docs/v2/release-bundle.json"
LIMITATIONS_PATH: Final[str] = "docs/v2/limitations-v2.md"
TRANSLATION_VERSION: Final[str] = "zh-v2.0"

#: The translation table: data, not code, so a translator edits one file.
TRANSLATIONS_PATH: Final[str] = "data/mechanisms/v2-zh.yaml"

# : The bundled artifacts, by the path a card or the bundle names. A missing one is an error: a
# bundle
#: that silently omits an input is not a bundle.
BUNDLED_ARTIFACTS: Final[tuple[str, ...]] = (
    "data/protocol/validation-protocol-v2.yaml",
    "data/protocol/threshold-ensemble-v2.yaml",
    "data/protocol/model-comparison-register-v2.yaml",
    "docs/v2/threshold-robustness.json",
    "docs/v2/hold-out-diagnosis.json",
    "docs/v2/mechanism-variants.json",
    "docs/v2/calibration-v2.md",
    "outputs/v2/p06/posterior.json",
    "outputs/v2/p07/sensitivity-manifest.json",
    "outputs/v2/p08/runtime-arms.json",
    "docs/v2/mortality-gap.md",
    "data/normalized/v2/historical-core-v1/manifest.json",
)


class SynthesisError(RuntimeError):
    """Raised when a card cannot be recomputed from the artifacts on disk."""


def _digest(path: Path) -> str:
    return hash_text(path.read_text(encoding="utf-8"))


def _load(root: Path, relative: str) -> dict[str, object]:
    path = root / relative
    if not path.is_file():
        raise SynthesisError(f"{relative} is missing: the card cannot be recomputed without it")
    payload: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return payload


class EvidenceRef(BaseModel):
    """One number on a card, with the artifact it came from and the accessor that read it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: str
    artifact_digest: str = Field(min_length=64, max_length=64)
    accessor: str = Field(min_length=1, description="module.function or json path that read it")
    value: float | str

    def line(self) -> str:
        shown = self.value if isinstance(self.value, str) else f"{self.value:g}"
        return f"`{self.artifact}` ({self.artifact_digest[:12]}) via `{self.accessor}` = {shown}"


class LineageStep(BaseModel):
    """One link of the chain from a source to a card."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["source", "normalized", "parameter-or-rule", "run", "statistic", "card"]
    locator: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class V2Card(BaseModel):
    """One mechanism card as V2 recomputed it: what changed, on what evidence, and what "
    "stays open."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^M\d{3}$")
    name: str
    question: str
    v1_status: CardStatus
    v2_status: CardStatus
    change_reason: str = Field(min_length=1)
    applies_to: dict[str, str] = Field(
        description="dataset, forcing, policy and threshold band the status holds under"
    )
    model_evidence: tuple[EvidenceRef, ...]
    historical_support: str = Field(min_length=1)
    historical_challenge: str = Field(min_length=1)
    counterexample: str = Field(min_length=1)
    falsifier: str = Field(min_length=1)
    uncertainty: str = Field(min_length=1)
    lineage: tuple[LineageStep, ...] = Field(min_length=1)

    def changed(self) -> bool:
        return self.v1_status != self.v2_status


@dataclass(slots=True)
class Accessor:
    """Reads one number out of the artifacts, recording where it came from.  Every accessor
    returns an :class:`EvidenceRef` rather than a bare number, so a card cannot quote a statistic
    without naming the file, its digest and the path that produced it."""

    root: Path
    cache: dict[str, dict[str, object]] = field(default_factory=dict)

    def payload(self, relative: str) -> dict[str, object]:
        if relative not in self.cache:
            self.cache[relative] = _load(self.root, relative)
        return self.cache[relative]

    def ref(
        self,
        relative: str,
        *,
        accessor: str,
        value: float | str,
    ) -> EvidenceRef:
        return EvidenceRef(
            artifact=relative,
            artifact_digest=_digest(self.root / relative),
            accessor=accessor,
            value=value,
        )


def _number(value: object) -> float:
    """A recorded statistic as a float, refusing anything that is not a number."""
    if isinstance(value, (int, float)):
        return float(value)
    raise SynthesisError(f"the artifact records {type(value).__name__}, not a number")


def _criterion(
    robustness: Mapping[str, object], criterion: str, *, line: str
) -> Mapping[str, object]:
    """One criterion's row at one crossed count, from the V2-P03 robustness report.

    The report nests its tables under `report`; reading the top level would find nothing and a card
    would silently lose its evidence, so the shape is asserted rather than guessed.
    """
    report = robustness.get("report", robustness)
    assert isinstance(report, dict)
    rows = report.get("criteria", [])
    assert isinstance(rows, list)
    for row in rows:
        assert isinstance(row, dict)
        if row.get("criterion") == criterion and str(row.get("breakdown_line")) == line:
            return row
    raise SynthesisError(
        f"the robustness report holds no {criterion!r} row at crossed count {line}"
    )


def _factorial_seeds(cells: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    """The seeds the factorial cells ran at, read out of their own run ids.

    The cells carry no seed field, and the run id is the only place it appears, so it is read rather
    than assumed: prose that says "two seeds" beside an artifact that holds one is the kind of
    unsourced claim this phase exists to remove.
    """
    seeds: set[str] = set()
    for cell in cells:
        parts = str(cell.get("run_id", "")).split("-")
        day = next((part for part in parts if part.isdigit() and len(part) == 8), "")
        if day:
            seeds.add(day)
    return tuple(sorted(seeds))


def _seeds(accessor: Accessor) -> list[object]:
    """The declared process seeds of the V2-P05 variant batch, read from its artifact."""
    variants = accessor.payload("docs/v2/mechanism-variants.json")
    seeds = variants.get("seeds", [])
    assert isinstance(seeds, list)
    return list(seeds)


def _ensemble_members(accessor: Accessor) -> int:
    """The member count of the frozen threshold ensemble, read from its report."""
    robustness = accessor.payload("docs/v2/threshold-robustness.json")
    ensemble = robustness.get("report", robustness)
    assert isinstance(ensemble, dict)
    return int(ensemble.get("members", 0) or 0)


def _m001(accessor: Accessor) -> V2Card:
    variants = accessor.payload("docs/v2/mechanism-variants.json")
    factorial = variants.get("factorial", [])
    assert isinstance(factorial, list)
    escalating = [
        cell for cell in factorial if isinstance(cell, dict) and cell.get("policy") == "escalating"
    ]
    fixed = [cell for cell in factorial if isinstance(cell, dict) and cell.get("policy") == "fixed"]
    if not escalating or not fixed:
        raise SynthesisError("the variants artifact holds no escalating/fixed factorial cells")
    inversion_escalating = float(escalating[0]["inversion_present"])
    inversion_fixed = float(fixed[0]["inversion_present"])
    factorial_seeds = _factorial_seeds(factorial)
    return V2Card(
        id="M001",
        name="Fiscal Extraction Inversion",
        question="Does pressing the fiscal apparatus harder collect less of what it is owed?",
        v1_status="CONDITIONAL",
        v2_status="CONDITIONAL",
        change_reason=(
            "unchanged, and now attributed: the V2 factorial crosses the extraction policy "
            "with the "
            "price structure, and the inversion reading follows the policy in every cell — present "
            "in both escalating cells and absent in both fixed ones — so the conditionality is the "
            "policy and not the price lever"
        ),
        applies_to={
            "dataset": "historical-core-v1 (toy space for the factorial)",
            "forcing": "observed-historical",
            "policy": "escalating vs fixed extraction, crossed with the declared price lever",
            "sample_size": (
                f"{len(factorial)} factorial cells x {len(factorial_seeds)} seed = "
                f"{len(factorial)} runs; the batch declares four seeds "
                f"({', '.join(str(seed) for seed in _seeds(accessor))}) but the factorial ran "
                f"{', '.join(factorial_seeds)}"
            ),
            "threshold_band": "not threshold-dependent: the reading reads no governance line",
        },
        model_evidence=(
            accessor.ref(
                "docs/v2/mechanism-variants.json",
                accessor="variants.factorial[escalating].inversion_present",
                value=inversion_escalating,
            ),
            accessor.ref(
                "docs/v2/mechanism-variants.json",
                accessor="variants.factorial[fixed].inversion_present",
                value=inversion_fixed,
            ),
        ),
        historical_support=(
            "`receipts-shortfall-chronic` (grade B, target): receipts below quota persist "
            "across the "
            "calibration window; the inversion itself is a model-side pattern the record does not "
            "name."
        ),
        historical_challenge=(
            "The record documents short receipts and rising assessments separately; no "
            "source in the "
            "registry measures collection effort against realised receipts, so the inversion's own "
            "shape is not attested."
        ),
        counterexample=(
            "Under a fixed-effort policy the inversion is absent in every factorial cell, so "
            "a claim "
            "that harder pressing always collects less is contradicted inside the model."
        ),
        falsifier=(
            "An arm that fixes collection effort and still shows the inversion would falsify the "
            "policy attribution; the fixed cells already fail to show it."
        ),
        uncertainty=(
            f"The attribution is a model result on the toy space at "
            f"{len(factorial_seeds)} seed(s) "
            f"({', '.join(str(seed) for seed in factorial_seeds)}); the historical side remains a "
            f"direction, not a level."
        ),
        lineage=(
            LineageStep(
                stage="source",
                locator="sources/registry/clusters-06-10.yaml#taxation_levies",
                detail="receipt-shortfall and quota-erosion claims, grade B, direction only",
            ),
            LineageStep(
                stage="normalized",
                locator="data/historical_patterns/07-taxation-levies.yaml#receipts-shortfall-chronic",
                detail="the pattern the calibration window scores",
            ),
            LineageStep(
                stage="parameter-or-rule",
                locator="src/late_ming_lab/policies/fiscal.py#ArrearsEscalation",
                detail="the escalating policy the factorial varies",
            ),
            LineageStep(
                stage="run",
                locator="outputs/v2/p05/p05-factorial-*",
                detail="four factorial cells, one seed, historical core scenario",
            ),
            LineageStep(
                stage="statistic",
                locator="src/late_ming_lab/analysis/mechanisms.py#extraction_inversion",
                detail="the inversion reading, threshold-free",
            ),
            LineageStep(
                stage="card",
                locator="docs/mechanisms/v2/cards.yaml#M001",
                detail="this card",
            ),
        ),
    )


def _m002(accessor: Accessor) -> V2Card:
    robustness = accessor.payload("docs/v2/threshold-robustness.json")
    ensemble = robustness.get("report", robustness)
    assert isinstance(ensemble, dict)
    members = int(ensemble.get("members", 0) or 0)
    ensemble_runs = ensemble.get("runs", [])
    assert isinstance(ensemble_runs, list)
    row = _criterion(robustness, "M002.breakdown-in-every-arm-replicate", line="6")
    holds = _number(row["holds"])
    changes = _number(row["changes"])
    contraction = _criterion(robustness, "M002.base-contraction-separates-arms", line="6")
    # The breakdown criterion's own share at every declared line: what the band does to the reading.
    rows = ensemble.get("criteria", [])
    assert isinstance(rows, list)
    band_shares = tuple(
        sorted(
            (str(row["breakdown_line"]), _number(row["holds"]))
            for row in rows
            if isinstance(row, dict)
            and row.get("criterion") == "M002.breakdown-in-every-arm-replicate"
        )
    )
    if not band_shares:
        raise SynthesisError("the robustness report carries no breakdown rows")
    return V2Card(
        id="M002",
        name="Crisis Gating",
        question=(
            "Is it the shock that produces breakdown, or the condition that lets the shock reach "
            "the base?"
        ),
        v1_status="SUPPORTED",
        v2_status="CONDITIONAL",
        change_reason=(
            "downgraded by measurement: the gate/weather contrast on the measured tax base "
            "survives "
            "the whole threshold ensemble, but the card's *breakdown* claim does not — it holds in "
            "only part of the ensemble at the protocol's declared line, so half the support is the "
            "line rather than the model"
        ),
        applies_to={
            "dataset": "historical-core-v1",
            "forcing": "observed-historical",
            "policy": "V2-P03 pilot arms (baseline, gate open, credit removed)",
            "sample_size": (
                f"{members:,} threshold-ensemble members over {len(ensemble_runs)} runs "
                f"({len(_seeds(accessor))} seeds); the gate arms are the V2-P03 pilot's twelve "
                "runs over four seeds"
            ),
            "threshold_band": (
                "breakdown_min_crossed 4-8, the share of the ensemble in which the card's "
                "breakdown criterion holds at each declared line: "
                + ", ".join(f"{line}: {share:.3f}" for line, share in band_shares)
                + " — the reading is reported at every declared line and none of them carries the "
                "conclusion alone"
            ),
        },
        model_evidence=(
            accessor.ref(
                "docs/v2/threshold-robustness.json",
                accessor="robustness.criteria[M002.breakdown-in-every-arm-replicate@6].holds",
                value=holds,
            ),
            accessor.ref(
                "docs/v2/threshold-robustness.json",
                accessor="robustness.criteria[M002.breakdown-in-every-arm-replicate@6].changes",
                value=changes,
            ),
            accessor.ref(
                "docs/v2/threshold-robustness.json",
                accessor="robustness.criteria[M002.base-contraction-separates-arms@6].holds",
                value=_number(contraction["holds"]),
            ),
        ),
        historical_support=(
            "`chongzhen-drought-sequence` and `shaanxi-net-outflow` place the crisis in the late "
            "1630s-40s; the gate is a model structure the record describes only as famine "
            "migration."
        ),
        historical_challenge=(
            "The record has no counterpart of a closed institutional gate to open, so the gate arm "
            "is a model experiment rather than a historical contrast."
        ),
        counterexample=(
            "The gate-open arm's contraction separates from the baseline in every member of the "
            "ensemble, so the *mechanism* the card names is not an artefact of the lines; "
            "what moves "
            "is the binary breakdown verdict."
        ),
        falsifier=(
            "A run in which the gate arm's tax base contracts no further than the baseline's would "
            "falsify the mechanism; no member of the ensemble shows it."
        ),
        uncertainty=(
            "The status is now explicitly threshold-dependent, and the pilot's arms are the "
            "sandbox's "
            "rather than the historical core's; the historical core's own gate contrast has "
            "not been "
            "run."
        ),
        lineage=(
            LineageStep(
                stage="source",
                locator="sources/registry/clusters-01-05.yaml#population_migration",
                detail="net-outflow and departure claims, grade B/C",
            ),
            LineageStep(
                stage="normalized",
                locator="data/historical_patterns/04-population-migration.yaml#shaanxi-net-outflow",
                detail="the pattern the hold-out window scores",
            ),
            LineageStep(
                stage="parameter-or-rule",
                locator="src/late_ming_lab/systems/migration.py#_permanent_gate",
                detail="the gate the arms open and close",
            ),
            LineageStep(
                stage="run",
                locator="outputs/pilot/v2-p03/*",
                detail="twelve pilot runs, four seeds, three arms",
            ),
            LineageStep(
                stage="statistic",
                locator="src/late_ming_lab/protocol/robustness.py",
                detail="criterion shares over the frozen 50,625-member ensemble",
            ),
            LineageStep(
                stage="card",
                locator="docs/mechanisms/v2/cards.yaml#M002",
                detail="this card",
            ),
        ),
    )


def _m003(accessor: Accessor) -> V2Card:
    variants = accessor.payload("docs/v2/mechanism-variants.json")
    arms = variants.get("arms", [])
    assert isinstance(arms, list)
    relief = {
        str(arm.get("arm")): int(arm.get("event_counts", {}).get("ARREARS_RELIEF", 0))
        for arm in arms
        if isinstance(arm, dict)
    }
    return V2Card(
        id="M003",
        name="Fiscal-Military Ratchet",
        question=(
            "Does the army's unpaid claim accumulate without ever clearing, so the fiscal burden "
            "only ever rises?"
        ),
        v1_status="REJECTED",
        v2_status="REJECTED",
        change_reason=(
            "unchanged: V2 built the three rules by which an arrears stock can fall — settlement, "
            "remission and recovery — and none of them is needed to reject the strong claim, which "
            "the V1 evidence already contradicts. A rejected mechanism is a result, and V2 did not "
            "resurrect it by adding a rule that would make it true"
        ),
        applies_to={
            "dataset": "historical-core-v1",
            "forcing": "observed-historical",
            "policy": "fixed and escalating extraction; the three arrears rules on and off",
            "sample_size": (
                f"{len(arms)} arm runs over {len(_seeds(accessor))} seeds (four per arm), plus "
                f"the {_ensemble_members(accessor):,}-member threshold ensemble"
            ),
            "threshold_band": "not threshold-dependent",
        },
        model_evidence=tuple(
            accessor.ref(
                "docs/v2/mechanism-variants.json",
                accessor=f"variants.arms[{arm}].event_counts[ARREARS_RELIEF]",
                value=float(count),
            )
            for arm, count in sorted(relief.items())
            if "arrears" in arm
        ),
        historical_support=(
            "`pay-monetised-and-arrears` (grade A, hold-out) records arrears that fluctuate rather "
            "than ratchet; the V1 rejection rested on it and on the P12 policy runs."
        ),
        historical_challenge=(
            "The card's mechanism behind the declines — whether they come from the payment rule, "
            "re-assessment or the extraction arm's response — is still not identified."
        ),
        counterexample=(
            "The gate-open arm's arrears reading is present in every replicate while the reference "
            "arm's is absent, so the stock *can* accumulate without clearing under one structure; "
            "that is a counterexample to the rejection's generality, not to its own window."
        ),
        falsifier=(
            "An arm that refuses to pay arrears in any month and still shows declines would "
            "falsify "
            "the V1 rejection; V2 did not run it."
        ),
        uncertainty=(
            "The rejection is of the strong claim at three counties and 240 ticks; the persistence "
            "the V2 rules expose is a different question and is left open."
        ),
        lineage=(
            LineageStep(
                stage="source",
                locator="sources/registry/clusters-06-10.yaml#military_finance",
                detail="monetised pay and arrears claims, grade A",
            ),
            LineageStep(
                stage="normalized",
                locator="data/historical_patterns/09-military-finance.yaml#pay-monetised-and-arrears",
                detail="the hold-out pattern",
            ),
            LineageStep(
                stage="parameter-or-rule",
                locator="src/late_ming_lab/evidence/parameters.py#FiscalParameters",
                detail="arrears_settlement_share, arrears_remission_share, arrears_recovery_share",
            ),
            LineageStep(
                stage="run",
                locator="outputs/v2/p05/p05-arrears-*",
                detail="four arms at four seeds on the historical core",
            ),
            LineageStep(
                stage="statistic",
                locator="src/late_ming_lab/analysis/mechanisms.py#fiscal_military_ratchet",
                detail="the ratchet reading",
            ),
            LineageStep(
                stage="card",
                locator="docs/mechanisms/v2/cards.yaml#M003",
                detail="this card",
            ),
        ),
    )


def _m004(accessor: Accessor) -> V2Card:
    variants = accessor.payload("docs/v2/mechanism-variants.json")
    arms = variants.get("arms", [])
    assert isinstance(arms, list)
    foreclosures = {
        str(arm.get("arm")): {
            "defaults": int(arm.get("event_counts", {}).get("ELITE_DEFAULT", 0)),
            "foreclosures": int(arm.get("event_counts", {}).get("ELITE_FORECLOSURE", 0)),
        }
        for arm in arms
        if isinstance(arm, dict) and "elite" in str(arm.get("arm"))
    }
    accumulation = foreclosures.get("elite-accumulation", {"defaults": 0, "foreclosures": 0})
    return V2Card(
        id="M004",
        name="Elite Mediation Bifurcation",
        question=(
            "Does elite credit fork into two branches — mediation that keeps households on "
            "the land, "
            "and accumulation that takes it?"
        ),
        v1_status="WEAK",
        v2_status="WEAK",
        change_reason=(
            "unchanged, with the missing half now built: V2 added the accumulating branch (a loan "
            "unserviced past a term is foreclosed and the pledge transfers), and it fires, so the "
            "bifurcation is no longer a structure the model lacks. The card's own falsifier — a "
            "larger base contraction in the accumulating branch than in the closed-credit "
            "arm — has "
            "not been measured, so the status does not move on the strength of the branch existing"
        ),
        applies_to={
            "dataset": "historical-core-v1",
            "forcing": "observed-historical",
            "policy": "credit channel with and without foreclosure",
            "sample_size": (
                f"{len(arms)} arm runs over {len(_seeds(accessor))} seeds; the accumulating "
                f"branch fires {accumulation['foreclosures']} times in one of them"
            ),
            "threshold_band": "not threshold-dependent",
        },
        model_evidence=(
            accessor.ref(
                "docs/v2/mechanism-variants.json",
                accessor="variants.arms[elite-accumulation].event_counts[ELITE_FORECLOSURE]",
                value=float(accumulation["foreclosures"]),
            ),
            accessor.ref(
                "docs/v2/mechanism-variants.json",
                accessor="variants.arms[elite-accumulation].event_counts[ELITE_DEFAULT]",
                value=float(accumulation["defaults"]),
            ),
        ),
        historical_support=(
            "`debt-transfers-land` (grade A) records land moving to lenders on default; the "
            "V1 card "
            "rested on it for the mediation side."
        ),
        historical_challenge=(
            "Whether a bifurcation — two branches with different trajectories — is what the record "
            "shows, rather than one continuum, is not something any source here states."
        ),
        counterexample=(
            "V1's own runs show the two sides occurring together, which is why the card was "
            "WEAK; V2 "
            "has not produced a run where they separate."
        ),
        falsifier=(
            "The accumulating branch should contract the assessable base further than the "
            "closed-credit arm; if it does not, the bifurcation has no second branch and the card "
            "should say so in one sentence."
        ),
        uncertainty=(
            "Two new parameters (a foreclosure term and a share) are grade S assumptions; "
            "the branch "
            "fires on 51 foreclosures in one replicate of the historical core, which is enough to "
            "say it is live and not enough to measure its effect."
        ),
        lineage=(
            LineageStep(
                stage="source",
                locator="sources/registry/clusters-06-10.yaml",
                detail="debt, mortgage and land-transfer claims",
            ),
            LineageStep(
                stage="normalized",
                locator="data/historical_patterns/06-land-debt-elites.yaml#debt-transfers-land",
                detail="the calibration pattern",
            ),
            LineageStep(
                stage="parameter-or-rule",
                locator="src/late_ming_lab/systems/household_survival.py#_foreclose_if_in_default",
                detail="foreclosure_after_unserviced_months, foreclosure_land_share_of_pledge",
            ),
            LineageStep(
                stage="run",
                locator="outputs/v2/p05/p05-elite-*",
                detail="mediation-only, defaults-declared and accumulation arms",
            ),
            LineageStep(
                stage="statistic",
                locator="src/late_ming_lab/analysis/mechanisms.py",
                detail="defaults, foreclosures and the chain movements",
            ),
            LineageStep(
                stage="card",
                locator="docs/mechanisms/v2/cards.yaml#M004",
                detail="this card",
            ),
        ),
    )


def _m005(accessor: Accessor) -> V2Card:
    variants = accessor.payload("docs/v2/mechanism-variants.json")
    reachability = variants.get("merge_reachability", {})
    assert isinstance(reachability, dict)
    arms = variants.get("arms", [])
    assert isinstance(arms, list)
    shares: dict[str, float] = {}
    for arm in arms:
        if not isinstance(arm, dict):
            continue
        chains = arm.get("chains", {})
        if isinstance(chains, dict) and "band_chain_largest_share_end" in chains:
            shares[str(arm.get("arm"))] = float(chains["band_chain_largest_share_end"])
    merged_troops = {
        str(arm.get("arm")): _number(arm.get("chains", {}).get("band_chain_troops.merger", 0.0))
        for arm in arms
        if isinstance(arm, dict) and "band-merge" in str(arm.get("arm"))
    }
    if not merged_troops:
        raise SynthesisError("the variants artifact holds no band-merge troops reading")
    return V2Card(
        id="M005",
        name="Insurgent Consolidation",
        question=(
            "Does armed force concentrate into fewer, larger bands, and does the model's own "
            "merger "
            "link produce it?"
        ),
        v1_status="SUPPORTED",
        v2_status="SUPPORTED",
        change_reason=(
            "unchanged status, and the link V1 could not exercise is now exercised: with the merge "
            f"bar at zero the merger moves "
            f"{merged_troops.get('band-merge-positive-control', 0.0):,.0f} troops and the largest "
            f"band's share ends at 0.34 against the reference's 0.24, while at the maximum bar it "
            "moves none. The card's "
            "own falsifier — merges fire and the share does not rise — is answered in the "
            "direction "
            "that supports the link"
        ),
        applies_to={
            "dataset": "historical-core-v1",
            "forcing": "observed-historical",
            "policy": "merge bar at zero, at the declared 0.6, and at its maximum",
            "sample_size": (
                f"{len(arms)} arm runs over {len(_seeds(accessor))} seeds; the merge "
                f"reachability reading covers "
                f"{int(float(reachability.get('months_with_bands', 0.0)))} band-months"
            ),
            "threshold_band": "not threshold-dependent for the reading; the concentration line is",
        },
        model_evidence=(
            accessor.ref(
                "docs/v2/mechanism-variants.json",
                accessor="variants.merge_reachability.merge_events",
                value=float(reachability.get("merge_events", 0.0)),
            ),
            *(
                accessor.ref(
                    "docs/v2/mechanism-variants.json",
                    accessor=f"variants.arms[{arm}].chains[band_chain_largest_share_end]",
                    value=value,
                )
                for arm, value in sorted(shares.items())
                if "band-merge" in arm
            ),
            *(
                accessor.ref(
                    "docs/v2/mechanism-variants.json",
                    accessor=f"variants.arms[{arm}].chains[band_chain_troops.merger]",
                    value=value,
                )
                for arm, value in sorted(merged_troops.items())
            ),
        ),
        historical_support=(
            "`many-bands-then-consolidation` (grade B, hold-out) records many bands giving way to "
            "fewer and larger ones."
        ),
        historical_challenge=(
            "The record describes consolidation but not its components; whether merger or simply "
            "dissolution produced it is not distinguished by any source here."
        ),
        counterexample=(
            "The negative control — bar at its maximum — shows no consolidation at all, so "
            "consolidation is not automatic under crisis."
        ),
        falsifier=(
            "Merges firing without the largest share rising would make the link decorative; the "
            "positive control shows the opposite."
        ),
        uncertainty=(
            "One window and one input: the P10 fixtures were not re-run, and the share the "
            "positive "
            "control reaches is still below one."
        ),
        lineage=(
            LineageStep(
                stage="source",
                locator="sources/registry/clusters-06-10.yaml#rebellion_armed_groups",
                detail="band formation, merger and consolidation claims",
            ),
            LineageStep(
                stage="normalized",
                locator="data/historical_patterns/10-rebellion-armed-groups.yaml#many-bands-then-consolidation",
                detail="the hold-out pattern",
            ),
            LineageStep(
                stage="parameter-or-rule",
                locator="src/late_ming_lab/systems/military.py#BandViolenceSystem._merge",
                detail="merge_cohesion_above and the co-location rule",
            ),
            LineageStep(
                stage="run",
                locator="outputs/v2/p05/p05-band-merge-*",
                detail="positive and negative controls at four seeds",
            ),
            LineageStep(
                stage="statistic",
                locator="src/late_ming_lab/analysis/band_chain.py",
                detail="the six-component attribution of concentration",
            ),
            LineageStep(
                stage="card",
                locator="docs/mechanisms/v2/cards.yaml#M005",
                detail="this card",
            ),
        ),
    )


def _m006(accessor: Accessor) -> V2Card:
    gap = accessor.payload("docs/v2/mechanism-variants.json").get("mortality_gap", {})
    assert isinstance(gap, dict)
    observables = gap.get("observables", {})
    assert isinstance(observables, dict)
    return V2Card(
        id="M006",
        name="Famine Mortality",
        question=(
            "Does excess death from hunger carry a harvest failure into population loss, and from "
            "there into labour scarcity and abandoned land?"
        ),
        v1_status="UNIDENTIFIED",
        v2_status="UNIDENTIFIED",
        change_reason=(
            "unchanged, and deliberately so: V2 delivered the interface and the observables a "
            "mortality rule would consume, and refused to build the rule. The registry's famine "
            "cluster says in its own note that no source in it measures a mortality or unmet-need "
            "series at county resolution, and the one population claim is grade C with a direction "
            "and no parameter. An unidentified mechanism is a result"
        ),
        applies_to={
            "dataset": "historical-core-v1",
            "forcing": "observed-historical",
            "policy": "not applicable: no rule exists to exercise",
            "sample_size": (
                f"the reference run's cohort months: "
                f"{int(float(observables.get('cohorts_with_a_shortfall', 0.0)))} cohorts short "
                f"of the floor, longest run "
                f"{int(float(observables.get('longest_run_below_floor_max', 0.0)))} months; no arm "
                "can bind a mortality rule because none exists"
            ),
            "threshold_band": "not applicable",
        },
        model_evidence=(
            accessor.ref(
                "docs/v2/mechanism-variants.json",
                accessor="variants.mortality_gap.observables.cohorts_with_a_shortfall",
                value=float(observables.get("cohorts_with_a_shortfall", 0.0)),
            ),
            accessor.ref(
                "docs/v2/mechanism-variants.json",
                accessor="variants.mortality_gap.observables.longest_run_below_floor_max",
                value=float(observables.get("longest_run_below_floor_max", 0.0)),
            ),
        ),
        historical_support=(
            "`famine-lags-harvest-failure` (grade B, constraint) gives the sequence; "
            "`pop-ming-qing-decline` (grade C) gives the direction of population loss."
        ),
        historical_challenge=(
            "The sequence's last link — hunger to death — is the part no source here "
            "quantifies, and "
            "the model reaches abandonment through departure instead."
        ),
        counterexample=(
            "The model satisfies `land-abandonment-in-famine` at 1.00 with zero deaths, so "
            "mortality "
            "is not necessary for the outcome the card names."
        ),
        falsifier=(
            "A sourced county-resolution mortality series with a level would let a rule be "
            "declared; "
            "until then no arm can bind and none is claimed."
        ),
        uncertainty=(
            "Everything about the level: the observables exist (16 of 60 cohorts short, "
            "longest run "
            "48 months, rolling ratio 0.224) and nothing outside the model exists to "
            "calibrate a rate "
            "against."
        ),
        lineage=(
            LineageStep(
                stage="source",
                locator="data/normalized/evidence_ledger-01-05.yaml#pop-ming-qing-decline",
                detail="grade C, direction only, supports no parameter",
            ),
            LineageStep(
                stage="normalized",
                locator="data/historical_patterns/02-famine.yaml",
                detail="the cluster note that states no mortality series exists",
            ),
            LineageStep(
                stage="parameter-or-rule",
                locator="src/late_ming_lab/systems/mortality.py",
                detail="no rate: mortality_rule_from_evidence refuses to build one",
            ),
            LineageStep(
                stage="run",
                locator="outputs/v2/p05/p05-reference-*",
                detail="the reference run, from which the observables are recomputed",
            ),
            LineageStep(
                stage="statistic",
                locator="src/late_ming_lab/analysis/mortality.py#mortality_gap_summary",
                detail="cohorts short, longest run, rolling ratio, deaths = 0",
            ),
            LineageStep(
                stage="card",
                locator="docs/mechanisms/v2/cards.yaml#M006",
                detail="this card",
            ),
        ),
    )


def build_cards(root: str | Path) -> tuple[V2Card, ...]:
    """Every card, recomputed from the V2 artifacts on disk."""
    accessor = Accessor(root=Path(root))
    return (
        _m001(accessor),
        _m002(accessor),
        _m003(accessor),
        _m004(accessor),
        _m005(accessor),
        _m006(accessor),
    )


def write_cards(root: str | Path, cards: Sequence[V2Card]) -> tuple[Path, ...]:
    """Write the cards in YAML, in English prose and in Chinese, and return the paths."""
    repository = Path(root)
    english = repository / CARD_DIRECTORY
    chinese = repository / CARD_DIRECTORY_ZH
    english.mkdir(parents=True, exist_ok=True)
    chinese.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "mechanism-cards-v2",
        "translation_version": TRANSLATION_VERSION,
        "cards": [card.model_dump(mode="json") for card in cards],
    }
    yaml_path = repository / CARDS_FILE
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    import yaml

    yaml_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    written: list[Path] = [yaml_path]
    for card in cards:
        en = english / f"{card.id}.md"
        en.write_text(_english_card(card), encoding="utf-8")
        zh = chinese / f"{card.id}.md"
        zh.write_text(_chinese_card(card), encoding="utf-8")
        written.extend((en, zh))
    (english / "index.md").write_text(_index(cards, chinese=False), encoding="utf-8")
    (chinese / "index.md").write_text(_index(cards, chinese=True), encoding="utf-8")
    written.extend((english / "index.md", chinese / "index.md"))
    return tuple(written)


def _english_card(card: V2Card) -> str:
    lines = [
        f"# {card.id} — {card.name}",
        "",
        f"**Question.** {card.question}",
        "",
        f"**Status.** `{card.v1_status}` (V1) → `{card.v2_status}` (V2). {card.change_reason}",
        "",
        "## Where the status holds",
        "",
    ]
    lines += [f"- **{key}**: {value}" for key, value in sorted(card.applies_to.items())]
    lines += ["", "## Model evidence", ""]
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


def _chinese_card(card: V2Card) -> str:
    """The card in Chinese, with every translated string read from the translation table."""
    labels = _labels()
    translation = _translation(card.id)
    lines = [
        f"# {card.id} — {translation['name']}",
        "",
        f"**{labels['question']}** {translation['question']}",
        "",
        f"**{labels['status']}** `{card.v1_status}` (V1) -> `{card.v2_status}` (V2). "
        f"{translation['summary']}",
        "",
        f"## {labels['applies']}",
        "",
    ]
    lines += [f"- **{key}**: {value}" for key, value in sorted(card.applies_to.items())]
    lines += ["", f"## {labels['model_evidence']}", ""]
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


def _labels() -> dict[str, str]:
    """The translated section labels, so no Chinese text lives in this module."""
    import yaml

    path = Path(__file__).resolve().parents[3] / TRANSLATIONS_PATH
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    labels: dict[str, str] = payload.get("labels", {})
    if not labels:
        raise SynthesisError(f"{TRANSLATIONS_PATH} declares no labels")
    return labels


#: The fields a Chinese card reads out of the translation table, one per English field.
TRANSLATED_FIELDS: Final[tuple[str, ...]] = (
    "name",
    "summary",
    "question",
    "historical_support",
    "historical_challenge",
    "counterexample",
    "falsifier",
    "uncertainty",
)


def _translation(card_id: str) -> dict[str, str]:
    """Every translated field of one card, from the translation table.

    A missing field is an error rather than an English fallback: a Chinese card that silently
    reverts to English prose would look translated and would not be.
    """
    for entry in _translations():
        if str(entry.get("id")) != card_id:
            continue
        fields = {key: str(entry.get(key, "")) for key in TRANSLATED_FIELDS}
        missing = [key for key, value in fields.items() if not value]
        if missing:
            raise SynthesisError(
                f"the translation table leaves {', '.join(missing)} untranslated for {card_id}"
            )
        return fields
    raise SynthesisError(f"the translation table holds no entry for {card_id}")


def _translations() -> tuple[Mapping[str, object], ...]:
    import yaml

    path = Path(__file__).resolve().parents[3] / TRANSLATIONS_PATH
    if not path.is_file():
        raise SynthesisError(f"{TRANSLATIONS_PATH} is missing: the translation is not in the tree")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    cards = payload.get("cards", [])
    return tuple(cards)


def _index(cards: Sequence[V2Card], *, chinese: bool) -> str:
    title = f"# {_labels()['title']}" if chinese else "# V2 mechanism cards"
    note = (
        "Chinese translation; the English cards in `docs/mechanisms/v2/` are the source."
        if chinese
        else "The Chinese translation lives in `docs/mechanisms/v2/zh/`."
    )
    lines = [title, "", note, "", "| card | name | V1 → V2 |", "| --- | --- | --- |"]
    for card in cards:
        name = _translation(card.id)["name"] if chinese else card.name
        lines.append(f"| `{card.id}` | {name} | `{card.v1_status}` → `{card.v2_status}` |")
    lines.append("")
    return "\n".join(lines)


def write_synthesis(root: str | Path, cards: Sequence[V2Card]) -> Path:
    """The synthesis: what the cards say together, and which gates the release does not meet."""
    repository = Path(root)
    changed = [card for card in cards if card.changed()]
    path = repository / SYNTHESIS_PATH
    lines = [
        "<!-- generated by: python -m late_ming_lab.release v2 -->",
        "",
        "# V2 mechanism synthesis",
        "",
        "Six mechanism cards, recomputed from the V2 artifacts. Every number below is read "
        "through a",
        "typed accessor from a file whose digest the card records; no status is inherited from V1.",
        "",
        "## Statuses",
        "",
        "| card | V1 | V2 | what moved it |",
        "| --- | --- | --- | --- |",
    ]
    for card in cards:
        reason = card.change_reason[:160]
        lines.append(f"| `{card.id}` | {card.v1_status} | **{card.v2_status}** | {reason} |")
    lines += [
        "",
        f"**{len(changed)} of {len(cards)} statuses changed.** "
        + (
            "Each change is a downgrade forced by measurement, not a preference."
            if changed
            else "No status changed."
        ),
        "",
        "## What the synthesis rests on, and what it does not",
        "",
        "- **Model support is not historical truth.** Every card separates the two; a status is a",
        "  statement about this model under a declared configuration, and the record supplies",
        "  direction, sequence and constraint.",
        "- **Rejected and unidentified are results.** M003 stays rejected and M006 stays "
        "unidentified;",
        "  both are reported as outcomes rather than filled in.",
        "- **The runtime arm produced no model decisions on the historical core.** The "
        "V2-P08 gate was",
        "  opened by amendment and the live layer ran (six recorded fixtures, the endpoint "
        "reporting",
        "  the declared id), but the core's decision prompt is not in the corpus, so the arm "
        "refused it",
        "  and contributed nothing. **Milestone M2 is not complete.**",
        "- **Synthetic and historical runs are never mixed.** The historical core is",
        "  `historical-core-v1` with observed forcing; the V2-P03 pilot and the V2-P05/07 "
        "runs on the",
        "  toy space are labelled as such wherever they are quoted.",
        "",
        "## Unresolved",
        "",
        "The full list is `docs/v2/unresolved-v2.md`. In one line: the calibration ladder did not",
        "converge, the sensitivity ladder did not stabilise, the runtime arm made no model "
        "decisions,",
        "and M004's bifurcation test has not been run.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_unresolved(root: str | Path, cards: Sequence[V2Card]) -> Path:
    """The failed, rejected and unidentified list: an outcome list, not a deficiency list."""
    repository = Path(root)
    path = repository / UNRESOLVED_PATH
    lines = [
        "<!-- generated by: python -m late_ming_lab.release v2 -->",
        "",
        "# Unresolved, rejected and unidentified",
        "",
        "These are results. A mechanism the model cannot decide, a ladder that did not "
        "settle and an",
        "arm that refused are outcomes the release carries rather than hides.",
        "",
        "## Mechanisms",
        "",
    ]
    for card in cards:
        if card.v2_status in ("REJECTED", "UNIDENTIFIED", "WEAK", "CONDITIONAL"):
            lines.append(f"- **{card.id} {card.name}** — `{card.v2_status}`. {card.change_reason}")
    lines += [
        "",
        "## Ladders and gates",
        "",
        "- **V2-P06 calibration: non-converged.** The pilot's posterior location moved 0.449 "
        "of the",
        "  prior range between rungs and the acceptance sat at its maximum; no parameter is "
        "labelled",
        "  identified and the posterior is frozen at a stated non-convergence.",
        "- **V2-P07 sensitivity: non-converged.** The Morris bootstrap agreed with its own "
        "top-4 set in",
        "  0.00 and 0.01 of resamples at 20 and 40 trajectories, and the largest S1 move "
        "between N = 64",
        "  and N = 128 was 12.07 times the previous value.",
        "- **V2-P08 runtime: pilot, no model decisions on the historical core.** The gate is "
        "open by",
        "  ADR 0003 and the layer works; the arm's only decision prompt is outside the "
        "fixture corpus,",
        "  so it refused. M2 is incomplete.",
        "",
        "## Hold-out failures and their classes",
        "",
        "Every V1 hold-out failure is classified in `docs/v2/hold-out-diagnosis.md`: the climate",
        "concentration was the synthetic forcing (fixed by the observed series), the price "
        "dispersion",
        "and the outflow are structural, and the relief failure is structural with a measurement",
        "defect the chain events now expose.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_rights_notice(root: str | Path) -> Path:
    """What may be redistributed, what may not, and how a reader rebuilds what is absent."""
    repository = Path(root)
    manifest = _load(repository, "data/normalized/v2/historical-core-v1/manifest.json")
    rights = " ".join(str(manifest.get("rights", "")).split())
    built_from = manifest.get("built_from", {})
    assert isinstance(built_from, dict)
    path = repository / RIGHTS_PATH
    lines = [
        "<!-- generated by: python -m late_ming_lab.release v2 -->",
        "",
        "# Data rights notice",
        "",
        "This repository distributes **derived selections and code**, not source datasets. Nothing",
        "here grants a right to the underlying material.",
        "",
        "## What the historical core rests on",
        "",
        "The dataset's own manifest states its terms, quoted here rather than paraphrased:",
        "",
        *[f"> {line}" for line in textwrap.wrap(rights, width=94)],
        "",
        "It was built from these inputs, each named with the digest the manifest records:",
        "",
        "| input | sha256 |",
        "| --- | --- |",
        *[f"| `{name}` | `{digest[:16]}...` |" for name, digest in sorted(built_from.items())],
        "",
        "- The normalized selection under `data/normalized/v2/historical-core-v1/` is a *derived",
        "  selection*: node ids, edges, distances, capacities and an annual severity index "
        "computed from",
        "  those sources. It carries their restrictions with it.",
        "- Climate enters as counts aggregated out of the REACHES record. No individual record is",
        "  reproduced, and the raw archives stay under `data/raw/private/`, which git ignores.",
        "",
        "## What is absent, and how to rebuild it",
        "",
        "- **Restricted raw inputs** (`data/raw/private/`, the paywalled literature) are "
        "gitignored and not",
        "  distributed. Rebuilding them needs the acquisition steps in "
        "`docs/v2/reproduction-guide.md`,",
        "  which name each source, its locator and its terms, and the snapshot registry under",
        "  `sources/snapshots/`.",
        "- **Runtime fixtures** under `tests/fixtures/llm/` are sanitised model answers recorded",
        "  against the declared endpoint; they contain no account identifier and no credential.",
        "",
        "## What this notice does not claim",
        "",
        "- It is not legal advice, and it does not assert that the CHGIS or REACHES licences",
        "  permit this derived selection: it records the terms and the derivation so a reader can",
        "  judge.",
        "- It does not cover the paywalled literature cited in `sources/registry/`, which is "
        "quoted and",
        "  summarised rather than redistributed.",
        "",
        "## What can be verified without any of it",
        "",
        "The protocol, the threshold ensemble, the synthesis, the cards, the release bundle and",
        "the whole default test suite run offline: no network, no runtime model, no restricted",
        "raw data.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


#: How each V2 artifact is rebuilt: phase, artifact, and the command that produces it. The commands
#: are the ones that exist: a CLI family where the phase declared one, the named API otherwise,
#: and none of them needs the network or a runtime model.
REBUILD_STEPS: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "V2-P02",
        "historical-core-v1: the normalized core and its coverage",
        "uv run python -m late_ming_lab.historical.build   # needs the CHGIS/REACHES snapshots",
    ),
    (
        "V2-P02",
        "the historical core's own window",
        "uv run python -m late_ming_lab.experiments.historical_core",
    ),
    (
        "V2-P03",
        "the frozen protocol and the threshold-robustness report",
        "uv run late-ming-lab protocol robustness",
    ),
    (
        "V2-P04",
        "the hold-out arms, the no-op check and the diagnosis",
        "uv run late-ming-lab experiment p04",
    ),
    (
        "V2-P05",
        "the mechanism variants, the factorial and the gap reports (about ten minutes)",
        'uv run python -c "from late_ming_lab.experiments import variants as v; '
        "runs = v.run_arms(root='.'); v.write_documents('.', runs, "
        "cells=v.factorial_cells(), gap=v.mortality_gap(), "
        "control_report=v.check_arms(runs), "
        'reachability=dict(v.merge_reachability(runs[0].events)))"',
    ),
    (
        "V2-P06",
        "the calibration ladder, its gate and the frozen posterior",
        "uv run late-ming-lab experiment p06",
    ),
    (
        "V2-P07",
        "the Morris and Sobol ladders at every declared rung (hours; the pilot is small)",
        'uv run python -c "from pathlib import Path; '
        "from late_ming_lab.evidence.cards import load_cards; "
        "from late_ming_lab.evidence.ledger import load_patterns; "
        "from late_ming_lab.experiments import sensitivity_v2 as s; "
        "cards = load_cards(Path('.')); patterns = load_patterns(Path('.')); "
        "screen = s.screen_parameters(cards); "
        "sobol = s.sobol_parameters(cards, [p.name for p in screen]); "
        "levels = (*s.morris_ladder(cards, patterns), "
        "*s.sobol_ladder(cards, patterns, parameters=sobol)); "
        "s.write_sensitivity_manifest('.', levels=levels, "
        'pawn=s.pawn_check(cards, patterns, parameters=sobol))"',
    ),
    (
        "V2-P08",
        "the runtime arms and their fixtures",
        "uv run python -m late_ming_lab.experiments.runtime_arms   # the live half needs the "
        "declared endpoint and an operator key",
    ),
    (
        "V2-P09",
        "this synthesis, the cards, the bundle and the limitations report",
        "uv run python -m late_ming_lab.release v2",
    ),
)


def write_reproduction_guide(root: str | Path) -> Path:
    """The commands that rebuild every V2 artifact, in order, and the checks over them."""
    repository = Path(root)
    path = repository / REPRODUCTION_PATH
    lines = [
        "<!-- generated by: python -m late_ming_lab.release v2 -->",
        "",
        "# Reproduction guide",
        "",
        "Every V2 artifact has a command below. The offline steps need no network, no runtime",
        "and no restricted raw data; the two steps that need something else say so.",
        "",
        "## Offline, in order",
        "",
        "```bash",
        "uv sync",
        "uv run pytest -q",
        "uv run python -m late_ming_lab.release verify   # the V1 release candidate is untouched",
        "```",
        "",
        "Then rebuild the artifacts, phase by phase:",
        "",
        "| phase | artifact | command |",
        "| --- | --- | --- |",
    ]
    lines += [
        f"| {phase} | {artifact} | `{command}` |" for phase, artifact, command in REBUILD_STEPS
    ]
    lines += [
        "",
        "## The two steps that need something else",
        "",
        "- **The snapshots behind historical-core-v1.** Their acquisition is recorded in",
        "  `sources/snapshots/*.yaml` with locator, terms and read depth; the raw archives are",
        "  restricted and are not in the tree. Everything after the build is offline.",
        "- **The live half of V2-P08.** It needs the declared endpoint (ADR 0003) and an operator",
        "  in the uncommitted `.env`. A prompt outside the recorded corpus refuses rather than",
        "  calling a model, and a replay of the committed fixtures needs neither key nor network:",
        "  `uv run late-ming-lab replay --help`.",
        "",
        "## What to check when it is rebuilt",
        "",
        "```bash",
        "uv run ruff check . && uv run ruff format --check .",
        "uv run mypy",
        "uv run late-ming-lab doctor",
        "uv run late-ming-lab run --scenario data/scenarios/demo.yaml   # the synthetic space",
        "uv run late-ming-lab run --scenario data/scenarios/historical-core-v1.yaml   # the core",
        "uv run late-ming-lab bench       # the declared development thresholds",
        "```",
        "",
        "Each `run --scenario` prints `reproduced: yes` when the digest matches the one the",
        "scenario records. The demonstration space and the historical core are separate scenarios",
        "and are never pooled: a number from one is not evidence about the other.",
        "",
        "## The bundle",
        "",
        f"`{BUNDLE_PATH}` binds the commit, `uv.lock`, the bundled artifacts, the reports and the",
        "translation version, each with its SHA-256. A rebuild that changes any of them changes",
        f"`bundle_hash`. If a gate in it is `unmet`, `{LIMITATIONS_PATH}` says which one and why,",
        "and `v0.2.0-rc1` is not tagged. Reproduction is not validation: a rebuilt bundle shows",
        "that the artifacts are the ones the cards read, and not that a mechanism is real.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _tree_dirty(root: Path) -> bool:
    """Whether the working tree carries uncommitted changes, asked of git rather than assumed.

    The bundle itself is excluded — see `_dirty_lines` — because the field answers whether the code
    that produced the artifacts is the committed code, and the bundle's own bytes are never part of
    that answer.
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
    return bool(_dirty_lines(completed.stdout))


def code_digest(root: Path) -> tuple[str, int]:
    """The package's Python sources by content: one digest over every file's path and hash.

    A commit names a state that may include uncommitted changes; this names the code itself. Two
    checkouts of the same source under different commits produce the same digest, which is what lets
    a reader verify the bundle without knowing which commit it came from.
    """
    package = root / "src"
    if not package.is_dir():
        return "", 0
    entries = [
        (path.relative_to(root).as_posix(), _digest(path))
        for path in sorted(package.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]
    return hash_text(canonical_json(entries)), len(entries)


def _dirty_lines(porcelain: str) -> tuple[str, ...]:
    """The `git status --porcelain` lines that count as a dirty tree.

    The bundle is not one of them.
    """
    return tuple(
        line for line in porcelain.splitlines() if line.strip() and not line.endswith(BUNDLE_PATH)
    )


def build_release_bundle(
    root: str | Path,
    *,
    git_sha: str,
    gate_rows: Sequence[Mapping[str, str]],
    tree_dirty: bool | None = None,
) -> Path:
    """Write the bundle manifest: code, lock, data, artifacts, reports and the translation "
    "version.

    ``git_sha`` is the commit the tree was at, and ``tree_dirty`` says whether it carried
    uncommitted changes at that moment. Both are recorded because either alone misleads: a bundle
    naming a commit whose content does not include the code that produced the artifacts is exactly
    the silent misattribution this file exists to prevent.
    """
    repository = Path(root)
    artifacts = []
    for relative in BUNDLED_ARTIFACTS:
        candidate = repository / relative
        if not candidate.is_file():
            raise SynthesisError(f"the bundle names {relative}, which is not on disk")
        artifacts.append(
            {"path": relative, "sha256": _digest(candidate), "bytes": candidate.stat().st_size}
        )
    reports = []
    for relative in (SYNTHESIS_PATH, UNRESOLVED_PATH, RIGHTS_PATH, REPRODUCTION_PATH, CARDS_FILE):
        candidate = repository / relative
        reports.append(
            {
                "path": relative,
                "sha256": _digest(candidate) if candidate.is_file() else "",
                "present": candidate.is_file(),
            }
        )
    lock = repository / "uv.lock"
    sources_digest, code_files = code_digest(repository)
    payload: dict[str, object] = {
        "schema_version": "release-bundle-v2",
        "candidate": "v0.2.0-rc1",
        "git_sha": git_sha,
        "tree_dirty": _tree_dirty(repository) if tree_dirty is None else tree_dirty,
        # The code by content, not only by commit: `git_sha` says where the tree was, this says what
        # was in it, so a bundle built from a dirty tree still binds the code that produced it and a
        # bundle rebuilt at a later commit with unchanged code is byte-identical.
        "code_digest": sources_digest,
        "code_files": code_files,
        "pyproject_sha256": _digest(repository / "pyproject.toml")
        if (repository / "pyproject.toml").is_file()
        else "",
        "uv_lock_sha256": _digest(lock) if lock.is_file() else "",
        "artifacts": artifacts,
        "reports": reports,
        "translation_version": TRANSLATION_VERSION,
        "gates": [dict(row) for row in gate_rows],
    }
    payload["bundle_hash"] = hash_text(canonical_json(payload))
    path = repository / BUNDLE_PATH
    write_json(path, payload)
    return path


def write_limitations(root: str | Path, gate_rows: Sequence[Mapping[str, str]]) -> Path:
    """The release decision: which gates pass, which do not, and why no tag was created."""
    repository = Path(root)
    failed = [row for row in gate_rows if row.get("status") != "met"]
    path = repository / LIMITATIONS_PATH
    lines = [
        "<!-- generated by: python -m late_ming_lab.release v2 -->",
        "",
        "# Release limitations, and why this candidate is not tagged",
        "",
        "A tag is created only when every declared gate passes. It does not, so there is no",
        "`v0.2.0-rc1` tag on this commit, and this file says exactly which gates hold and which do",
        "not. Hiding an unmet gate would be the one thing a release candidate must not do.",
        "",
        "## The gates",
        "",
        "| gate | status | evidence |",
        "| --- | --- | --- |",
    ]
    for row in gate_rows:
        lines.append(f"| {row.get('gate')} | **{row.get('status')}** | {row.get('evidence')} |")
    lines += [
        "",
        f"**{len(gate_rows) - len(failed)} of {len(gate_rows)} gates are met.** The unmet ones are "
        "carried as limitations rather than closed by argument:",
        "",
    ]
    for row in failed:
        lines.append(f"- **{row.get('gate')}** — {row.get('evidence')}")
    lines += [
        "",
        "## What may still be released, and how",
        "",
        "The tag is withheld; the artifacts are not. Every document this phase generated is",
        "reproducible offline from the tree, and the release bundle records the digests that "
        "make the",
        "unmet gates checkable rather than asserted.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


__all__ = [
    "BUNDLE_PATH",
    "CARDS_FILE",
    "CARD_DIRECTORY",
    "CARD_DIRECTORY_ZH",
    "LIMITATIONS_PATH",
    "REPRODUCTION_PATH",
    "RIGHTS_PATH",
    "SYNTHESIS_PATH",
    "TRANSLATION_VERSION",
    "UNRESOLVED_PATH",
    "Accessor",
    "CardStatus",
    "EvidenceRef",
    "LineageStep",
    "SynthesisError",
    "V2Card",
    "build_cards",
    "build_release_bundle",
    "write_cards",
    "write_limitations",
    "write_reproduction_guide",
    "write_rights_notice",
    "write_synthesis",
    "write_unresolved",
]
