"""The V2-P00 acceptance audit: what V1's plan asked for, and what V1's artifacts support.

The planning document states one mechanism milestone, one policy milestone and twelve final success
criteria (``docs/OMP_ENGINEERING_PLAN.md`` sections 80-82). This module turns each of them into a
row with a status from a four-word vocabulary - ``met``, ``partial``, ``unmet``, ``not-testable`` -
a verdict, and evidence a reader can open.

Two things are deliberately different from a written audit:

- **The judgement is declared; the numbers are read.** The statuses and verdicts are written here,
  by the phase, because a status is an argument. Everything countable - which batches a mechanism
  card cites, how many rows those batches hold, how many replicates and seeds they used, which
  commit they were generated at - comes from ``docs/v2/baseline-v1.json`` and the mechanism cards,
  so a card's sample size in this matrix cannot drift from the artifact it names.
- **Every citation is a path plus a locator.** :func:`verify_audit` resolves each one, so a sentence
  that points at a file which no longer exists fails rather than being read as support.

The audit also records where V1's own prose and V1's own artifacts disagree. Those rows are the
point of a baseline audit: an unsupported sentence in a V1 document is not corrected in place (V1
is frozen), it is recorded here with the measurement that contradicts it.
"""

from __future__ import annotations

import fnmatch
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from late_ming_lab.core.hashing import canonical_json, hash_text
from late_ming_lab.experiments.integrated import IntegratedScenario, build_integrated_economy
from late_ming_lab.release.baseline import (
    BASELINE_PATH,
    ArtifactRecord,
    Baseline,
    CommitSource,
    TableRecord,
    load_baseline,
)
from late_ming_lab.synthesis.schema import CARDS_FILE, DOCS_ROOT, MechanismCard, load_book

AUDIT_SCHEMA_VERSION: Final[str] = "v1-acceptance-matrix-v1"
AUDIT_JSON_PATH: Final[str] = "docs/v2/v1-acceptance-matrix.json"
AUDIT_MARKDOWN_PATH: Final[str] = "docs/v2/v1-acceptance-matrix.md"

Status = Literal["met", "partial", "unmet", "not-testable"]
EvidenceKind = Literal["artifact", "document", "code", "registry"]

#: The tables a sample size is read from first, in order; anything else is listed by name.
PRIMARY_TABLES: Final[tuple[str, ...]] = (
    "runs.parquet",
    "ensemble.parquet",
    "levels.parquet",
    "decision_trace.parquet",
)

#: The one sandbox the P09, P10 and P12 batches ran on. Declared here as a pointer to the code that
#: builds it; the counts beside it are measured from that code by :func:`sandbox_census`.
SPACE_SOURCES: Final[tuple[str, ...]] = (
    "src/late_ming_lab/networks/fixtures.py:toy_spatial_dataset",
    "src/late_ming_lab/actors/fixtures.py:toy_cohort_population",
    "src/late_ming_lab/experiments/integrated.py:build_integrated_economy",
)

CLIMATE_SOURCE: Final[str] = "src/late_ming_lab/systems/climate.py:SyntheticClimate"
SCENARIO_SOURCE: Final[str] = "src/late_ming_lab/experiments/integrated.py:IntegratedScenario"

#: Where a cited source id is resolved: a card cites ``ray-huang-1974``, not a file path.
REGISTRY_ROOT: Final[str] = "sources/registry"

#: What a card's policy-arms cell says when none of its batches varies a decision rule.
NO_POLICY_ARM: Final[str] = (
    "no institutional policy arm in the batches this card cites: the decision rule is the "
    "sandbox's declared one, and the arm that varies is a mechanism, not a policy"
)

#: What it says when the card cites no batch at all, because nothing in the project measured it.
NO_POLICY_ARM_WITHOUT_BATCH: Final[str] = (
    "no batch and no policy arm: the card cites the record, and nothing the project ran measures "
    "this mechanism"
)


class Evidence(BaseModel):
    """One citation: a file, what in it is being read, and what it shows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1, description="A repository path; a glob is allowed.")
    kind: EvidenceKind
    locator: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class MilestoneAudit(BaseModel):
    """One of the plan's two milestones, marked and evidenced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^M[12]$")
    name: str = Field(min_length=1)
    requirement: str = Field(min_length=1)
    status: Status
    verdict: str = Field(min_length=1)
    evidence: tuple[Evidence, ...] = Field(min_length=1)


class CriterionAudit(BaseModel):
    """One of the plan's twelve final success criteria, marked and evidenced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: int = Field(ge=1, le=12)
    statement: str = Field(min_length=1)
    status: Status
    verdict: str = Field(min_length=1)
    evidence: tuple[Evidence, ...] = Field(min_length=1)


class DatasetSample(BaseModel):
    """One artifact a mechanism card cites, with the sample size read out of it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    directory: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    generation_commit: str | None = None
    generation_commit_source: CommitSource
    dirty_at_generation: bool | None = None
    primary_table: str | None = None
    primary_rows: int | None = None
    tables: tuple[TableRecord, ...] = ()
    facts: dict[str, str] = Field(default_factory=dict)

    def sample_size(self) -> str:
        """How big this batch is, in the artifact's own terms."""
        parts: list[str] = []
        if self.primary_table is not None and self.primary_rows is not None:
            parts.append(f"{self.primary_rows} rows in {self.primary_table}")
        for key, label in (("replicates", "replicates"), ("ticks", "ticks"), ("base_seed", "seed")):
            if key in self.facts:
                parts.append(f"{self.facts[key]} {label}")
        for key, label in (("labels", "declared arms"), ("policies", "policy arms")):
            if key in self.facts:
                parts.append(f"{len(self.facts[key].split(','))} {label}")
        return ", ".join(parts) if parts else "no table and no declared size"

    def describe(self) -> str:
        """The sample as one clause: directory, size, and the commit it was generated at."""
        commit = (self.generation_commit or "unrecorded")[:12]
        return f"`{self.directory}` ({self.sample_size()}, generated at {commit})"

    def brief(self) -> str:
        """The sample for a table cell: the batch's own name and how many rows it holds."""
        tag = self.directory.split("/")[-1]
        if self.primary_rows is None:
            return f"`{tag}`: no table"
        return f"`{tag}`: {self.primary_rows} rows in {self.primary_table}"


class CardMatrix(BaseModel):
    """One mechanism card's dataset, climate, sample size, policy arms and extrapolation limits."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^M\d{3}$")
    name: str = Field(min_length=1)
    status: str = Field(min_length=1)
    datasets: tuple[DatasetSample, ...] = ()
    sampled_by: tuple[str, ...] = ()
    climate: str = Field(min_length=1)
    space: str = Field(min_length=1)
    policy_arms: str = Field(min_length=1)
    extrapolation_limits: str = Field(min_length=1)
    counterexample: str = Field(min_length=1)
    citations: tuple[Evidence, ...] = ()


class SandboxCensus(BaseModel):
    """The size of the sandbox the V1 experiments ran on, measured from the code that builds it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_count: int = Field(ge=0)
    county_count: int = Field(ge=0)
    external_node_count: int = Field(ge=0)
    household_cohort_count: int = Field(ge=0)
    elite_count: int = Field(ge=0)
    merchant_count: int = Field(ge=0)
    government_count: int = Field(ge=0)
    garrison_count: int = Field(ge=0)
    bands_at_start: int = Field(ge=0)
    household_count: float = Field(ge=0.0)
    sources: tuple[str, ...] = ()
    climate: str = Field(min_length=1)
    climate_source: str = Field(min_length=1)
    scenario_source: str = Field(min_length=1)

    def describe(self) -> str:
        """The census as one sentence, for a document that has to state the scale it is about."""
        return (
            f"{self.county_count} county nodes and {self.external_node_count} external nodes "
            f"({self.node_count} nodes), {self.household_cohort_count} weighted household cohorts "
            f"covering {self.household_count:,.0f} households, {self.elite_count} elite houses, "
            f"{self.merchant_count} merchant houses, {self.government_count} county governments, "
            f"{self.garrison_count} garrison units and {self.bands_at_start} armed bands at start"
        )


class Discrepancy(BaseModel):
    """A V1 sentence the V1 artifacts contradict, with the measurement that contradicts it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_path: str = Field(min_length=1)
    claim_locator: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    measured: str = Field(min_length=1)
    consequence: str = Field(min_length=1)
    evidence: tuple[Evidence, ...] = Field(min_length=1)


class Audit(BaseModel):
    """The whole audit: milestones, criteria, the card matrix, and V1's unsupported sentences."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["v1-acceptance-matrix-v1"] = "v1-acceptance-matrix-v1"
    baseline_id: str = Field(min_length=1)
    baseline_commit: str = Field(min_length=40, max_length=40)
    baseline_digest: str = Field(min_length=64, max_length=64)
    generated_at_utc: str = Field(min_length=1)
    census: SandboxCensus
    milestones: tuple[MilestoneAudit, ...] = Field(min_length=1)
    criteria: tuple[CriterionAudit, ...] = Field(min_length=12, max_length=12)
    cards: tuple[CardMatrix, ...] = Field(min_length=1)
    discrepancies: tuple[Discrepancy, ...] = ()
    reproducibility_statement: str = Field(min_length=1)
    content_digest: str = Field(min_length=64, max_length=64)

    def status_counts(self) -> dict[str, int]:
        """How many milestones and criteria carry each status."""
        counts: dict[str, int] = {}
        for status in (
            *(row.status for row in self.milestones),
            *(row.status for row in self.criteria),
        ):
            counts[status] = counts.get(status, 0) + 1
        return counts


def build_audit(
    root: str | Path,
    *,
    baseline: Baseline | None = None,
    generated_at: datetime | None = None,
) -> Audit:
    """Assemble the audit from the frozen baseline, the mechanism cards and the model's own code."""
    repository = Path(root).resolve()
    frozen = baseline or load_baseline(repository / BASELINE_PATH)
    book = load_book(repository / DOCS_ROOT / CARDS_FILE)
    census = sandbox_census()
    cards = tuple(_card_matrix(card, frozen.artifacts, census) for card in book.cards)
    payload = {
        "baseline": [frozen.baseline_id, frozen.commit],
        "milestones": [
            [row.id, row.status, row.verdict, [item.path for item in row.evidence]]
            for row in MILESTONES
        ],
        "criteria": [
            [row.number, row.status, row.verdict, [item.path for item in row.evidence]]
            for row in CRITERIA
        ],
        "cards": [[row.id, row.status, list(row.sampled_by), row.policy_arms] for row in cards],
        "discrepancies": [
            [row.claim_path, row.claim_locator, row.measured] for row in DISCREPANCIES
        ],
    }
    return Audit(
        baseline_id=frozen.baseline_id,
        baseline_commit=frozen.commit,
        baseline_digest=frozen.content_digest,
        generated_at_utc=(generated_at or datetime.now(UTC)).isoformat(),
        census=census,
        milestones=MILESTONES,
        criteria=CRITERIA,
        cards=cards,
        discrepancies=DISCREPANCIES,
        reproducibility_statement=REPRODUCIBILITY_STATEMENT,
        content_digest=hash_text(canonical_json(payload)),
    )


def sandbox_census() -> SandboxCensus:
    """Measure the sandbox the P09, P10 and P12 batches ran on, by building it."""
    scenario = IntegratedScenario(label="census")
    economy = build_integrated_economy(scenario)
    governments = economy.governments
    if governments is None:
        raise RuntimeError("the census sandbox was built without its fiscal layer")
    nodes = tuple(economy.graphs.nodes)
    counties = tuple(node for node in nodes if node.is_county)
    climate = (
        "synthetic stationary: a shock month is drawn independently with probability "
        f"{scenario.monthly_event_probability:g} and severity floor {scenario.severity_floor:g}; "
        "no observed series and no trend"
    )
    return SandboxCensus(
        node_count=len(nodes),
        county_count=len(counties),
        external_node_count=len(nodes) - len(counties),
        household_cohort_count=len(economy.population.cohorts),
        elite_count=len(economy.elites.houses),
        merchant_count=len(economy.merchants.houses),
        government_count=len(governments.counties),
        garrison_count=len(economy.military.units),
        bands_at_start=len(economy.bands.bands),
        household_count=float(economy.population.total_households),
        sources=SPACE_SOURCES,
        climate=climate,
        climate_source=CLIMATE_SOURCE,
        scenario_source=SCENARIO_SOURCE,
    )


def verify_audit(root: str | Path, audit: Audit) -> tuple[str, ...]:
    """Resolve every citation; return the ones that do not exist.

    A citation is either a repository path (it contains a ``/``) or a source-registry id, which is
    resolved against the registry files rather than against the filesystem.
    """
    repository = Path(root).resolve()
    registry = _registry_text(repository)
    missing: list[str] = []
    for path in _cited_paths(audit):
        if "/" in path:
            if not any(repository.glob(path)):
                missing.append(path)
        elif path not in registry:
            missing.append(path)
    return tuple(dict.fromkeys(missing))


def _registry_text(repository: Path) -> str:
    """Every registry file's text, so a source id can be resolved to the registry holding it."""
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((repository / REGISTRY_ROOT).glob("*.yaml"))
    )


def _cited_paths(audit: Audit) -> tuple[str, ...]:
    paths: list[str] = []
    for milestone in audit.milestones:
        paths.extend(item.path for item in milestone.evidence)
    for criterion in audit.criteria:
        paths.extend(item.path for item in criterion.evidence)
    for card in audit.cards:
        paths.extend(item.path for item in card.citations)
        paths.extend(card.sampled_by)
    for discrepancy in audit.discrepancies:
        paths.append(discrepancy.claim_path)
        paths.extend(item.path for item in discrepancy.evidence)
    return tuple(paths)


def write_audit(root: str | Path, audit: Audit) -> tuple[Path, Path]:
    """Write the audit as machine-readable JSON and as a rendered document; return both paths."""
    repository = Path(root).resolve()
    json_path = repository / AUDIT_JSON_PATH
    markdown_path = repository / AUDIT_MARKDOWN_PATH
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(render_audit_json(audit), encoding="utf-8")
    markdown_path.write_text(render_audit_markdown(audit), encoding="utf-8")
    return json_path, markdown_path


def render_audit_json(audit: Audit) -> str:
    """The audit as pretty, key-sorted JSON."""
    payload = audit.model_dump(mode="json")
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_audit_markdown(audit: Audit) -> str:
    """The audit as a document: milestones, criteria, one block per card, and discrepancies."""
    lines: list[str] = [
        "# V1 acceptance audit",
        "",
        "Generated by `python -m late_ming_lab.release audit` from "
        f"`{BASELINE_PATH}` and `{DOCS_ROOT}/{CARDS_FILE}`. Do not edit by hand.",
        "",
        f"- Baseline: `{audit.baseline_id}`, commit `{audit.baseline_commit}`",
        f"- Baseline content digest: `{audit.baseline_digest}`",
        f"- Audit content digest: `{audit.content_digest}`",
        f"- Generated: {audit.generated_at_utc}",
        "",
        "Statuses: `met` (the criterion is satisfied by evidence in the release), `partial` (part "
        "of it holds and part does not), `unmet` (the evidence contradicts it), `not-testable` (no "
        "artifact in the release can decide it).",
        "",
        "## 1. The sandbox this audit is about",
        "",
        f"{audit.census.describe()}.",
        "",
        f"- Space: built by `{audit.census.sources[0]}`, `{audit.census.sources[1]}` and "
        f"`{audit.census.sources[2]}`",
        f"- Climate: {audit.census.climate} (`{audit.census.climate_source}`)",
        f"- Scenario knobs: `{audit.census.scenario_source}`",
        "",
        "## 2. Milestones",
        "",
        "| id | milestone | status | verdict |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {row.id} | {row.name} | **{row.status}** | {row.verdict} |" for row in audit.milestones
    )
    lines.append("")
    for milestone in audit.milestones:
        lines.extend(_milestone_lines(milestone))
    lines.extend(
        [
            "## 3. Final success criteria",
            "",
            "| # | criterion | status | verdict |",
            "| --- | --- | --- | --- |",
        ]
    )
    lines.extend(
        f"| {row.number} | {row.statement} | **{row.status}** | {row.verdict} |"
        for row in audit.criteria
    )
    lines.append("")
    for criterion in audit.criteria:
        lines.extend(_criterion_lines(criterion))
    lines.extend(
        [
            "## 4. Mechanism cards: dataset, sample size, policy arms, extrapolation limits",
            "",
            "| card | status | datasets | sample size | policy arms |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for card in audit.cards:
        datasets = ", ".join(f"`{sample.directory}`" for sample in card.datasets) or "none"
        size = "; ".join(sample.brief() for sample in card.datasets) or "none"
        lines.append(f"| {card.id} | {card.status} | {datasets} | {size} | {card.policy_arms} |")
    lines.append("")
    for card in audit.cards:
        lines.extend(_card_lines(card))
    lines.extend(
        [
            "## 5. Where V1 prose and V1 artifacts disagree",
            "",
            "V1 is frozen and is not corrected in place. Each row names the V1 sentence, what the "
            "release's own artifacts measure, and what a V2 phase should do about it.",
            "",
        ]
    )
    for discrepancy in audit.discrepancies:
        lines.extend(_discrepancy_lines(discrepancy))
    lines.extend(["## 6. Reproducibility", "", audit.reproducibility_statement, ""])
    return "\n".join(lines)


def _milestone_lines(row: MilestoneAudit) -> list[str]:
    lines = [
        f"### {row.id} - {row.name}",
        "",
        f"**Requirement.** {row.requirement}",
        "",
        f"**Status: {row.status}.** {row.verdict}",
        "",
        "**Evidence.**",
        "",
    ]
    lines.extend(_evidence_lines(row.evidence))
    lines.append("")
    return lines


def _criterion_lines(row: CriterionAudit) -> list[str]:
    lines = [
        f"### Criterion {row.number} - {row.statement}",
        "",
        f"**Status: {row.status}.** {row.verdict}",
        "",
        "**Evidence.**",
        "",
    ]
    lines.extend(_evidence_lines(row.evidence))
    lines.append("")
    return lines


def _card_lines(card: CardMatrix) -> list[str]:
    datasets = ", ".join(f"`{sample.directory}`" for sample in card.datasets)
    size = "; ".join(sample.describe() for sample in card.datasets)
    lines = [
        f"### {card.id} - {card.name} ({card.status})",
        "",
        f"- **Dataset.** {datasets or NO_DATASET}",
        f"- **Sample size.** {size or 'none'}",
        f"- **Space.** {card.space}",
        f"- **Climate.** {card.climate}",
        f"- **Policy arms.** {card.policy_arms}",
        f"- **Extrapolation limits.** {card.extrapolation_limits}",
        f"- **Counterexample.** {card.counterexample}",
        "- **Evidence.**",
        "",
    ]
    lines.extend(_evidence_lines(card.citations, indent="  "))
    lines.append("")
    return lines


def _discrepancy_lines(row: Discrepancy) -> list[str]:
    lines = [
        f"### `{row.claim_path}` - {row.claim_locator}",
        "",
        f"**Claim.** {row.claim}",
        "",
        f"**Measured.** {row.measured}",
        "",
        f"**Consequence.** {row.consequence}",
        "",
        "**Evidence.**",
        "",
    ]
    lines.extend(_evidence_lines(row.evidence))
    lines.append("")
    return lines


def _evidence_lines(evidence: tuple[Evidence, ...], *, indent: str = "") -> list[str]:
    return [
        f"{indent}- `{item.path}` - {item.kind}: {item.locator} - {item.detail}"
        for item in evidence
    ]


def _card_matrix(
    card: MechanismCard, artifacts: tuple[ArtifactRecord, ...], census: SandboxCensus
) -> CardMatrix:
    records = _cited_directories(card, artifacts)
    samples = tuple(_dataset_sample(record) for record in records)
    return CardMatrix(
        id=card.id,
        name=card.name,
        status=card.status.value,
        datasets=samples,
        sampled_by=tuple(record.directory for record in records),
        climate=(
            f"{census.climate} - every batch this card cites ran on it, so no claim in the card is "
            "about observed climate"
        ),
        space=(
            f"{census.describe()}; the sandbox is a declared fixture graded S, not a reconstruction"
        ),
        policy_arms=(_policy_arms(samples) if samples else NO_POLICY_ARM_WITHOUT_BATCH),
        extrapolation_limits=card.uncertainty,
        counterexample=card.counterexample,
        citations=tuple(
            Evidence(
                path=citation.source,
                kind="artifact" if citation.source.startswith("outputs/") else "registry",
                locator=f"{citation.kind.value} citation on {card.id}",
                detail=citation.reading,
            )
            for citation in card.citations
        ),
    )


def _cited_directories(
    card: MechanismCard, artifacts: tuple[ArtifactRecord, ...]
) -> tuple[ArtifactRecord, ...]:
    wanted: list[str] = []
    for citation in card.citations:
        directory = _artifact_directory(citation.source)
        if directory is not None and directory not in wanted:
            wanted.append(directory)
    resolved: list[ArtifactRecord] = []
    for pattern in sorted(wanted):
        for record in artifacts:
            if fnmatch.fnmatch(record.directory, pattern) and record not in resolved:
                resolved.append(record)
    return tuple(resolved)


def _artifact_directory(source: str) -> str | None:
    """The artifact directory a citation points inside, or ``None`` for a non-artifact source."""
    parts = source.split("/")
    if len(parts) < 3 or parts[0] != "outputs":
        return None
    return "/".join(parts[:3])


def _dataset_sample(record: ArtifactRecord) -> DatasetSample:
    primary = _primary(record.tables)
    return DatasetSample(
        directory=record.directory,
        kind=record.kind,
        generation_commit=record.generation_commit,
        generation_commit_source=record.generation_commit_source,
        dirty_at_generation=record.git_dirty_at_generation,
        primary_table=None if primary is None else primary.name,
        primary_rows=None if primary is None else primary.rows,
        tables=record.tables,
        facts=record.facts,
    )


def _primary(tables: tuple[TableRecord, ...]) -> TableRecord | None:
    for name in PRIMARY_TABLES:
        for table in tables:
            if table.name == name:
                return table
    return sorted(tables, key=lambda table: table.name)[0] if tables else None


def _policy_arms(samples: tuple[DatasetSample, ...]) -> str:
    parts: list[str] = []
    for sample in samples:
        tag = sample.directory.split("/")[-1]
        if "policies" in sample.facts:
            refused = [
                pair.split("=")[0]
                for pair in sample.facts.get("arm_status", "").split(";")
                if pair.endswith("=refused")
            ]
            suffix = f"; refused: {', '.join(refused)}" if refused else ""
            parts.append(f"{tag}: {sample.facts['policies']}{suffix}")
        elif sample.facts.get("design_kind") == "ablation":
            labels = sample.facts.get("labels")
            count = len(labels.split(",")) if labels else 0
            replicates = sample.facts.get("design_replicates", "?")
            parts.append(f"{tag}: {count} declared arms, {replicates} replicates each")
        elif "design_kind" in sample.facts:
            parts.append(f"{tag}: {sample.facts['design_kind']} design")
    return "; ".join(parts) if parts else NO_POLICY_ARM


#: What a card's dataset cell says when it cites the record rather than an artifact.
NO_DATASET: Final[str] = "none: this card cites the record, not an artifact"

REPRODUCIBILITY_STATEMENT: Final[str] = (
    "Every path in this document names a file in the repository, and `verify_audit` resolves "
    "all of them. Every sample size in section 4 is read from `docs/v2/baseline-v1.json`, which "
    "stores each artifact's own byte hashes, row counts and recorded generation commit; no "
    "number here was typed from a report. The statuses in sections 2 and 3 are the phase's "
    "judgement and are declared in `src/late_ming_lab/release/audit.py`; changing one changes "
    "this document's content digest. Nothing in this audit re-runs the model, reads a licensed "
    "source, or writes inside a V1 artifact directory."
)

#: The two milestones, from ``docs/OMP_ENGINEERING_PLAN.md`` sections 80-81.
MILESTONES: Final[tuple[MilestoneAudit, ...]] = (
    MilestoneAudit(
        id="M1",
        name="Mechanism-capable deterministic model",
        requirement=(
            "Without any LLM, a calibrated multilayer ABM produces several independent historical "
            "patterns in the hold-out window, and for at least one candidate mechanism the "
            "sensitivity, ablation and counterfactual tests have all been done."
        ),
        status="partial",
        verdict=(
            "The LLM-free half holds and the triple test exists. What does not hold is the first "
            "half: the ensemble is a 32-particle pipeline rather than a posterior, two of thirteen "
            "parameters are unpinned across sampler seeds, and the hold-out window does not "
            "produce several independent patterns - three of the eight reserved patterns are "
            "contradicted "
            "by the model's own recorded falsifier, and the contradiction traces to a stationary "
            "synthetic climate, so those claims are untestable in this model rather than wrong in "
            "it."
        ),
        evidence=(
            Evidence(
                path="docs/calibration/prediction.md",
                kind="document",
                locator="the reserved-pattern table",
                detail="three of eight reserved patterns fail their own falsifier over the run",
            ),
            Evidence(
                path="docs/calibration/stability.md",
                kind="document",
                locator="seed comparison",
                detail="two of thirteen parameters move by over a quarter of their prior range",
            ),
            Evidence(
                path="docs/calibration/posterior.md",
                kind="document",
                locator="identifiability table",
                detail="one SMC batch per seed: a particle set, not a posterior",
            ),
            Evidence(
                path="outputs/experiments/p10-ablations/runs.parquet",
                kind="artifact",
                locator="52 rows; arm OPEN_MIGRATION_EXIT",
                detail="the mechanism-side intervention: breakdown in 4 of 4 replicates",
            ),
            Evidence(
                path="outputs/experiments/p10-morris/runs.parquet",
                kind="artifact",
                locator="32 rows, 2 trajectories",
                detail="the sensitivity screen behind the same card",
            ),
            Evidence(
                path="outputs/experiments/p12-robustness/manifest.json",
                kind="artifact",
                locator="arm_status",
                detail=(
                    "three declared policies ran; the runtime arm is refused, so no LLM decided "
                    "anything"
                ),
            ),
        ),
    ),
    MilestoneAudit(
        id="M2",
        name="Policy-robust mechanism model",
        requirement=(
            "Core mechanisms are robust across several institutional decision models: rule, "
            "utility and the USTC DeepSeek V4.1 runtime policy."
        ),
        status="partial",
        verdict=(
            "Not met as stated, because the arm the milestone names by model never ran: the P11 "
            "gate refused the configured id and P12 recorded the refusal rather than imputing a "
            "result. What does hold is narrower: with the world, the parameters and the random "
            "numbers held fixed, armed-band consolidation appears in five of six replicates under "
            "each of the three declared offline policies, extraction inversion reaches the "
            "declared presence bar under exactly one of them (utility 6 of 6 replicates, against "
            "random 2 of 6 and rule 0 of 6), and the tipping region moves with the policy. No "
            "statement is made about a model-backed policy."
        ),
        evidence=(
            Evidence(
                path="docs/experiments/policy-robustness.md",
                kind="document",
                locator="the matrix and its verdict rules",
                detail=(
                    "consolidation robust at three arms; inversion policy-dependent; ratchet absent"
                ),
            ),
            Evidence(
                path="outputs/experiments/p12-robustness/manifest.json",
                kind="artifact",
                locator="arm_status.ustc",
                detail="status refused, 0 decisions, with the gate's reason recorded",
            ),
            Evidence(
                path="outputs/experiments/p12-robustness/mechanism_readings.parquet",
                kind="artifact",
                locator="54 rows = 18 runs x 3 mechanisms",
                detail="the per-run readings the matrix is the share of",
            ),
            Evidence(
                path="docs/architecture/runtime-llm-boundary.md",
                kind="document",
                locator="the fail-closed contract",
                detail=(
                    "one confirmed model id or nothing; no fallback, recording and offline replay"
                ),
            ),
        ),
    ),
)

#: The twelve final success criteria, from ``docs/OMP_ENGINEERING_PLAN.md`` section 82.
CRITERIA: Final[tuple[CriterionAudit, ...]] = (
    CriterionAudit(
        number=1,
        statement="every key rule has provenance",
        status="met",
        verdict=(
            "Twenty-four declared rules each carry a support class and the claims that bear on "
            "them, and the referential chain is enforced in both directions by the invariant suite "
            "- which is how two claims pointing at rule names the code does not have were caught "
            "and recorded in the phase that built the registry. The weaker half is what the "
            "provenance is worth: eleven rules are evidence-backed, seven theoretically assumed "
            "and six exploratory, and thirteen of twenty-five sources were never opened."
        ),
        evidence=(
            Evidence(
                path="data/normalized/rule_claims.yaml",
                kind="registry",
                locator="24 rule records",
                detail="each rule with its support class and citing claims",
            ),
            Evidence(
                path="tests/invariants/test_evidence_invariants.py",
                kind="code",
                locator="claims to rules and rules to claims",
                detail="the reverse-direction check that caught the non-canonical rule names",
            ),
            Evidence(
                path="docs/phase-reports/P08.md",
                kind="document",
                locator="what this phase found (and fixed), items 1 to 3",
                detail="the eighteen citations trimmed and the two rule names that do not exist",
            ),
            Evidence(
                path="docs/evidence/coverage.md",
                kind="document",
                locator="coverage by cluster",
                detail="sources, claims and patterns per cluster, with the layer mix",
            ),
            Evidence(
                path="docs/evidence/gaps.md",
                kind="document",
                locator="the acquisition queue",
                detail="what could not be verified openly and is left to a human",
            ),
        ),
    ),
    CriterionAudit(
        number=2,
        statement="multi-scale historical patterns are explained together",
        status="unmet",
        verdict=(
            "Not achieved, and measured so. Five target patterns are scored in the calibration "
            "window: two are satisfied by every posterior draw, one by 0.81, and two are "
            "systematically unsatisfied on their own checks. Of the eight reserved patterns, three "
            "are contradicted with the pattern's own falsifier as the failure "
            "(chongzhen-drought-sequence 0.00, famine-worst-years-1639-43 0.00, "
            "price-spike-concentration 0.44 over the whole run), four are satisfied "
            "(many-bands-then-consolidation 0.94, pay-monetised-and-arrears 1.00, "
            "quota-erosion-and-surcharge 1.00, relief-overwhelmed-in-worst-years 0.84), and one "
            "passes on timing while the quantity it measures is near zero (shaanxi-net-outflow, "
            "whose exits are zero inside the hold-out window)."
        ),
        evidence=(
            Evidence(
                path="docs/calibration/mismatch.md",
                kind="document",
                locator="failing checks by pattern",
                detail="which target checks fail and in what share of draws",
            ),
            Evidence(
                path="outputs/calibration/p09-*/predictive_checks.parquet",
                kind="artifact",
                locator="reserved-pattern checks",
                detail="the hold-out scores the failure shares are computed from",
            ),
            Evidence(
                path="docs/calibration/prediction.md",
                kind="document",
                locator="what the ensemble fails at",
                detail=(
                    "the three contradicted reserved patterns and the reason they are contradicted"
                ),
            ),
        ),
    ),
    CriterionAudit(
        number=3,
        statement="calibration and hold-out are separated",
        status="met",
        verdict=(
            "Enforced structurally rather than by convention: the objective refuses every window "
            "but the calibration window, the predictive checks refuse the calibration window, and "
            "a test runs a real sandbox run, deletes every event after the split, and asserts the "
            "score does not move. The reserved patterns were fixed in P08, before any of them was "
            "scored."
        ),
        evidence=(
            Evidence(
                path="src/late_ming_lab/calibration/windows.py",
                kind="code",
                locator="the three-way split",
                detail="calibration / hold-out / extrapolation, tiling the run with no gap",
            ),
            Evidence(
                path="src/late_ming_lab/calibration/targets.py",
                kind="code",
                locator="Objective.score",
                detail="refuses any window but the calibration window",
            ),
            Evidence(
                path="tests/invariants/test_calibration_invariants.py",
                kind="code",
                locator="blindness test",
                detail="the score does not move when post-split events are deleted",
            ),
            Evidence(
                path="docs/calibration/objective.md",
                kind="document",
                locator="the frozen objective",
                detail="frozen bounds, checks and registry digest",
            ),
        ),
    ),
    CriterionAudit(
        number=4,
        statement="model results are explicitly sensitive to parameter perturbation",
        status="partial",
        verdict=(
            "A ranking exists and is readable on the migration output; the sensitivity claim is "
            "not yet a quantitative one. The Morris screen is two trajectories over fifteen "
            "parameters, so most rankings rest on one or two elementary effects, and the Sobol "
            "design at four base samples returns four undefined first-order indices and nine of "
            "the twelve finite ones outside [0, 1] - the phase reports it as a failed attempt "
            "rather than as an estimate."
        ),
        evidence=(
            Evidence(
                path="docs/experiments/sensitivity.md",
                kind="document",
                locator="Morris table and Sobol verdict",
                detail="the ranking, the NaN indices and the out-of-range values, with intervals",
            ),
            Evidence(
                path="outputs/experiments/p10-morris/runs.parquet",
                kind="artifact",
                locator="32 rows, 2 trajectories x 15 parameters",
                detail="the design the screen is computed from",
            ),
            Evidence(
                path="outputs/experiments/p10-sobol/runs.parquet",
                kind="artifact",
                locator="40 rows, base N=4",
                detail="the Sobol design that cannot estimate a variance share at this size",
            ),
        ),
    ),
    CriterionAudit(
        number=5,
        statement="real interventions are possible",
        status="met",
        verdict=(
            "Thirteen arms - one declared baseline, nine ablations and three joint arms - are "
            "computed differences from that baseline under common random numbers, and the reports "
            "carry the counters that show whether an arm bound: elite loans 74 to 0, suppressions "
            "936.5 to 0. Paired intervals, direction stability and Cliff's delta are reported "
            "rather than a mean, so an unresolved arm is visible as unresolved."
        ),
        evidence=(
            Evidence(
                path="src/late_ming_lab/experiments/interventions.py",
                kind="code",
                locator="BASELINE and the arm functions",
                detail="every arm is a function of one declared baseline",
            ),
            Evidence(
                path="docs/experiments/ablation.md",
                kind="document",
                locator="the binding table",
                detail="a counter per mechanism, so a no-op arm is reported as a no-op",
            ),
            Evidence(
                path="outputs/experiments/p10-ablations/runs.parquet",
                kind="artifact",
                locator="52 rows = 13 arms x 4 replicates",
                detail="the runs the paired differences are computed from",
            ),
        ),
    ),
    CriterionAudit(
        number=6,
        statement="key mechanisms can be removed by ablation",
        status="partial",
        verdict=(
            "For the mechanisms that have a removable rule, yes: removing elite credit and "
            "suppression both bind and both move the outputs their mechanism reaches. For three of "
            "the six cards, no arm can bind at all - the band-merger rule produced zero merges "
            "anywhere in the batch, so its ablation is a structural no-op; elite accumulation was "
            "never built, so the bifurcation has no second branch to remove; and famine mortality "
            "has no rule, parameter or output to delete."
        ),
        evidence=(
            Evidence(
                path="docs/experiments/ablation.md",
                kind="document",
                locator="did the ablations actually bind",
                detail="band_merges 0 against 0: nothing to remove",
            ),
            Evidence(
                path="docs/mechanisms/M004-elite-mediation-bifurcation.md",
                kind="document",
                locator="ablation evidence",
                detail="the accumulating branch has no arm to remove",
            ),
            Evidence(
                path="docs/mechanisms/M006-famine-mortality.md",
                kind="document",
                locator="ablation evidence",
                detail="no mortality rule exists, so removing it would be a no-op by construction",
            ),
        ),
    ),
    CriterionAudit(
        number=7,
        statement="the parameter regions in which a mechanism holds can be given",
        status="partial",
        verdict=(
            "One region is published and it is a cell, not a surface: the P10 grid is three by "
            "three at one run per cell, and exactly one cell breaks down, which is one run rather "
            "than a probability. The P12 grid places a region per policy at two replicates per "
            "cell and shows it moving with the policy. The parameter-side boundary is refused "
            "rather than forced, because the five-fold split cannot be scored at this sample size."
        ),
        evidence=(
            Evidence(
                path="docs/experiments/tipping.md",
                kind="document",
                locator="the grid",
                detail="one breakdown cell at one run per cell",
            ),
            Evidence(
                path="docs/experiments/policy-robustness.md",
                kind="document",
                locator="cells with breakdown, per policy",
                detail="the region per arm at two replicates per cell",
            ),
            Evidence(
                path="outputs/reports/mechanism-synthesis.md",
                kind="document",
                locator="section 4.3",
                detail="the parameter-side fit is refused, and says why",
            ),
        ),
    ),
    CriterionAudit(
        number=8,
        statement="the tipping surface can be identified",
        status="partial",
        verdict=(
            "A surface can be fitted and its limits are measured: on the P12 grid the "
            "cross-validated AUC is 0.754 against an in-sample 0.723 over 54 runs, but per policy "
            "the random arm gives 0.550 with a spread of 0.400, which separates almost nothing. "
            "The P10 grid cannot resolve a region at one run per cell, and its parameter-side fit "
            "is refused, so the identification is partial at 18 to 54 rows per surface."
        ),
        evidence=(
            Evidence(
                path="outputs/reports/mechanism-synthesis.md",
                kind="document",
                locator="sections 4.1 to 4.4",
                detail=(
                    "cross-validated fits, per-policy coefficients, and what they do not decide"
                ),
            ),
            Evidence(
                path="outputs/experiments/p12-robustness/tipping_grid.parquet",
                kind="artifact",
                locator="the grid rows",
                detail="the runs the scenario surface is fitted on",
            ),
            Evidence(
                path="src/late_ming_lab/analysis/boundary.py",
                kind="code",
                locator="the refusal on a single-class fold",
                detail="a fit the table cannot carry is refused, not forced",
            ),
        ),
    ),
    CriterionAudit(
        number=9,
        statement="historical counterexamples can be listed",
        status="met",
        verdict=(
            "Every card carries a counterexample field, and they are real ones: the rule policy "
            "shows no extraction inversion at the same parameter draws; the ratchet's strongest "
            "replicate still declines in 37 months; consolidation appears unchanged when the "
            "merger rule it names is removed. The review of the phase that wrote them found no "
            "fabricated number and rewrote the prose that reached past its artifact: a "
            "counterexample that cited the wrong replicate, a status moved from CONDITIONAL to "
            "WEAK, and a sensitivity ranking that named parameters the card's own table does not "
            "rank first."
        ),
        evidence=(
            Evidence(
                path="docs/mechanisms/cards.yaml",
                kind="registry",
                locator="the counterexample field of all six cards",
                detail="one recorded counterexample per card, checked in review",
            ),
            Evidence(
                path="docs/phase-reports/P13.md",
                kind="document",
                locator="the review findings table",
                detail="the counterexample and figure corrections the review forced",
            ),
            Evidence(
                path="outputs/experiments/p12-robustness/mechanism_readings.parquet",
                kind="artifact",
                locator="presence per run and policy",
                detail="the measurement the inversion counterexample rests on",
            ),
        ),
    ),
    CriterionAudit(
        number=10,
        statement="new predictions that return to the historical sources can be proposed",
        status="met",
        verdict=(
            "Each card carries a falsifiable prediction naming the arm or observation that would "
            "refute it, and several are already decisive: shut the gate and breakdown should not "
            "occur; fix collection effort and the inversion should disappear. They are predictions "
            "rather than results - the review records that the arms they describe do not exist "
            "yet, which is what makes them predictions."
        ),
        evidence=(
            Evidence(
                path="docs/mechanisms/cards.yaml",
                kind="registry",
                locator="the falsifiable_prediction field of all six cards",
                detail="six predictions, each naming the measurement that would refute the card",
            ),
            Evidence(
                path="data/historical_patterns",
                kind="registry",
                locator="22 patterns with signatures and falsifiers",
                detail=(
                    "the observations that would count against the model, recorded before scoring"
                ),
            ),
            Evidence(
                path="docs/evidence/gaps.md",
                kind="document",
                locator="the acquisition queue",
                detail="which sources would discriminate between the surviving candidates",
            ),
        ),
    ),
    CriterionAudit(
        number=11,
        statement="LLM decisions do not become an unexplainable black box",
        status="partial",
        verdict=(
            "By construction the layer is inspectable: a bounded action space per role, an "
            "anonymized observation with no date, place or person, Pydantic-validated output, an "
            "inert rationale, a recorded prompt and response hash, and no tools - all enforced "
            "offline by tests, including one that drives a hostile rationale and gets the benign "
            "world effect. It is also untested at runtime, because zero live decisions exist: the "
            "gate is closed, the recorded corpus is empty, and the two decisions in the smoke "
            "trace were made by the declared rule policy."
        ),
        evidence=(
            Evidence(
                path="docs/architecture/runtime-llm-boundary.md",
                kind="document",
                locator="the sixteen requirements",
                detail="where each requirement is enforced, and that the live model is closed",
            ),
            Evidence(
                path="tests/policies/test_live_ustc.py",
                kind="code",
                locator="the refusal",
                detail="a closed gate fails rather than skipping, so it cannot read as green",
            ),
            Evidence(
                path=(
                    "outputs/institutional/"
                    "institutional-smoke-20260915-d7f738698fbc-institutional-smoke/"
                    "decision_trace.parquet"
                ),
                kind="artifact",
                locator="2 decision rows",
                detail=("prompt and response hashes recorded, made by policy rule-v1, not a model"),
            ),
        ),
    ),
    CriterionAudit(
        number=12,
        statement="any result can be replayed from its run manifest",
        status="partial",
        verdict=(
            "The provenance machinery exists and one end-to-end case is proven: the declared demo "
            "reproduces the digest recorded in its scenario file. Three gaps are measured in this "
            "phase's own freeze. parameter_hash is null in every run manifest, because the kernel "
            "does not know the parameter sets. Seven of the nine artifact families with a manifest "
            "were generated from a dirty tree, so the recorded commit does not fully determine "
            "their code. And outputs/analysis carries nine Parquet files with no manifest at all, "
            "so those results have no recorded generating commit to replay from."
        ),
        evidence=(
            Evidence(
                path="docs/v2/baseline-v1.json",
                kind="artifact",
                locator="artifacts[].generation_commit, git_dirty_at_generation",
                detail="what commit each artifact recorded, and whether the tree was dirty",
            ),
            Evidence(
                path=(
                    "outputs/runs/"
                    "kernel-smoke-20260912-9153567ed602-p05-pressure-0.16/manifest.json"
                ),
                kind="artifact",
                locator="parameter_hash",
                detail="null, with config hash, subsystem seeds and tick order present",
            ),
            Evidence(
                path="docs/phase-reports/P09.md",
                kind="document",
                locator="what this phase found (and fixed), item 6",
                detail="the parameter_hash gap, recorded and left open by the phase that found it",
            ),
            Evidence(
                path="data/scenarios/demo.yaml",
                kind="registry",
                locator="the recorded digest",
                detail="the one reproducibility claim a test exercises end to end",
            ),
        ),
    ),
)

#: V1 sentences the V1 artifacts contradict. The audit records them; it does not edit V1.
DISCREPANCIES: Final[tuple[Discrepancy, ...]] = (
    Discrepancy(
        claim_path="docs/mechanisms/cards.yaml",
        claim_locator=(
            "M001 and M002 uncertainty fields; docs/mechanisms/M001-*, M002-* and index.md; "
            "docs/mechanisms/zh/cards.yaml, zh/M001-*, zh/M002-* and zh/index.md; "
            "outputs/reports/mechanism-synthesis.md section 5 and its zh translation. M003 "
            "states 'three counties and 240 ticks' instead, which is the same county miscount "
            "without the cohort sentence."
        ),
        claim=(
            "The mechanism documents state the sandbox the evidence rests on as 'three counties, "
            "thirty-two cohorts', in English and in Chinese."
        ),
        measured=(
            "The sandbox those cards cite is the toy fixture: five county nodes plus three "
            "external nodes, twenty-five weighted household cohorts. Neither count is three; "
            "thirty-two is the P09 particle count, not a cohort count."
        ),
        consequence=(
            "The card's scale statement is wrong in the direction that matters for extrapolation, "
            "and the confusion with the particle count means a reader cannot tell which 32 is "
            "being quoted. V2-P02 records a space census in the run manifest so this can never "
            "again be written from memory; V2-P09 restates the scale from the artifact."
        ),
        evidence=(
            Evidence(
                path="docs/v2/v1-acceptance-matrix.json",
                kind="artifact",
                locator="census",
                detail=(
                    "the measured census: 8 nodes, 5 counties, 25 cohorts, from the built sandbox"
                ),
            ),
            Evidence(
                path="src/late_ming_lab/networks/fixtures.py",
                kind="code",
                locator="toy_spatial_dataset",
                detail="five county nodes and three external nodes",
            ),
            Evidence(
                path="outputs/experiments/p10-ablations/runs.parquet",
                kind="artifact",
                locator="52 rows, all from that sandbox",
                detail="the runs the cards' ablation evidence is read from",
            ),
        ),
    ),
    Discrepancy(
        claim_path="outputs/reports/mechanism-synthesis.md",
        claim_locator="section 5 first bullet; docs/mechanisms/M005-insurgent-consolidation.md",
        claim=(
            "'Six cards over three counties and thirty-two cohorts' is offered as the limit of the "
            "causal claim, and M005 names the merger rule as part of consolidation's chain."
        ),
        measured=(
            "The cards' own ablation evidence records zero band merges in every arm of the batch, "
            "including the arm built to prevent them, so no arm exercised the named link."
        ),
        consequence=(
            "The status SUPPORTED rests on the outcome - fewer, larger bands across policies - not "
            "on the chain the card narrates. V2-P05 must make the link fire and measure it, or "
            "rewrite the chain around formation and dissolution; V1's own counterexample already "
            "says so, so this is a mismatch between the card's chain and its evidence rather than "
            "a missing finding."
        ),
        evidence=(
            Evidence(
                path="docs/experiments/ablation.md",
                kind="document",
                locator="the binding table",
                detail="band_merges 0 in the baseline and 0 in the arm",
            ),
            Evidence(
                path="outputs/experiments/p10-ablations/runs.parquet",
                kind="artifact",
                locator="band_merges column",
                detail="zero merges in every arm's four replicates",
            ),
        ),
    ),
)
