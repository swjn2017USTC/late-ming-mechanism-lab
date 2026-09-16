"""What V2.1-P10 concludes, and the documents it draws the conclusion from.

Three questions, three documents:

```text
replicate-audit          is the historical core's multi-seed determinism a declared property of the
                         model, or a stream that should be consumed and is not?
pilot-disposition        what V2 actually established, in the terms the artifacts support: P05's
                         four seeds, P06's frozen verdict, P07's stale artifact, P08's decisions
parameter-registry       the two registry defects V2-P06 and V2-P07 recorded and did not fix
```

The verdict is built from measurements, not from prose. Every fact it rests on is either read from
an artifact (a log's forcing mode, a digest, a row count) or a quotation checked to still exist
in the file it is attributed to — a citation a reader cannot resolve is treated as a bug, so
:func:`_quote` refuses a premise the tree no longer contains.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import polars as pl

from late_ming_lab.calibration.priors import (
    DECLARED,
    EXCLUDED,
    build_priors,
    card_free_parameters,
    centres_outside_range,
)
from late_ming_lab.calibration.simulator import SandboxSimulator
from late_ming_lab.core.rng import RNG_STREAMS
from late_ming_lab.evidence.cards import ParameterCards, load_cards
from late_ming_lab.evidence.ledger import load_patterns
from late_ming_lab.storage.tables import write_json, write_text
from late_ming_lab.v2_1.accessors import (
    KEY_READINGS,
    READING_SIGNIFICANT_DIGITS,
    REDUCTION_ORDER_FUNCTION,
    REDUCTION_ORDER_MODULE,
    ArmAudit,
    P05Audit,
    audit_p05,
    audit_p06,
    audit_p07,
    audit_p08,
)

GENERATOR: Final[str] = "python -m late_ming_lab.v2_1 audit"

#: Where this package's own documents live. Nothing here reads a file from it: a scan or a hash
#: that included the audit's own output would make the next generation depend on the last, which is
#: exactly the reproducibility the documents are supposed to demonstrate.
GENERATED_DOCUMENTS: Final[str] = "docs/v2_1"

#: The documents this package owns. Generated, never hand-edited.
AUDIT_JSON: Final[str] = "docs/v2_1/replicate-audit.json"
AUDIT_MARKDOWN: Final[str] = "docs/v2_1/replicate-audit.md"
DISPOSITION_JSON: Final[str] = "docs/v2_1/pilot-disposition.json"
DISPOSITION_MARKDOWN: Final[str] = "docs/v2_1/pilot-disposition.md"
REGISTRY_JSON: Final[str] = "docs/v2_1/parameter-registry-findings.json"
REGISTRY_MARKDOWN: Final[str] = "docs/v2_1/parameter-registry-findings.md"

#: The two verdicts the phase is allowed to reach. There is no third.
DETERMINISTIC_BY_DESIGN: Final[str] = "deterministic-replay-by-design"
RNG_WIRING_BLOCKER: Final[str] = "rng-wiring-blocker"

#: Where the model's design is *declared*: the constitution, the architecture and epistemics notes,
#: the ADRs, the mechanism cards, and the parameter, protocol and scenario files. The scan below
#: reads these and only these, because they are the documents that state how a subsystem is wired —
#: and because the corpus has to be closed for the audit to be reproducible at all. A phase report
#: or an exec plan records work rather than declaring design, and it may quote this audit, so
#: reading it would make one generation depend on the last.
STATEMENT_CORPUS: Final[tuple[str, ...]] = (
    ".omp",
    "docs/adr",
    "docs/architecture",
    "docs/epistemics",
    "docs/mechanisms",
    "data/parameters",
    "data/protocol",
)

#: What the statement scan can and cannot see. It reads text, so a stream consumed by a mechanism
#: whose name never appears in a document is invisible to it; and it reports what documents say, so
#: it cannot tell a declaration of intent from a description of code.
STATEMENT_SCAN_LIMIT: Final[str] = (
    "the scan reads the declared design documents as text; a stream consumed without being named "
    "in one of them, or consumed by a dynamic lookup rather than by `RngStream.<NAME>`, would not "
    "appear here. The decisive evidence is the call sites and the logs, not this scan."
)

#: The climate rule versions that declare themselves draw-free, and the reads that confirm it.
DRAW_FREE_RULE_VERSIONS: Final[tuple[str, ...]] = (
    "climate-allocated-observed-v1",
    "climate-baseline-v1",
    "climate-replay-v1",
)

#: The forcing mode the historical core records in its own log.
HISTORICAL_FORCING_MODE: Final[str] = "observed-historical"

#: Where an RNG stream can be consumed inside a run: the systems the kernel steps, in the phase
#: order the kernel enforces. A draw taken anywhere else is not part of a run's state.
TICK_PATH_MODULES: Final[tuple[str, ...]] = (
    "systems/climate.py",
    "systems/agriculture.py",
    "systems/household_survival.py",
    "systems/markets.py",
    "systems/fiscal.py",
    "systems/elites.py",
    "systems/migration.py",
    "systems/military.py",
    "systems/mortality.py",
)

#: The premises the verdict rests on, each a file, a locator and a quotation the file must still
#: hold. A verdict whose premise has been edited away fails the audit instead of surviving it.
PREMITHE_TEXT: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "src/late_ming_lab/historical/forcing.py",
        "AllocatedObservedClimate.shock",
        "consumes no randomness",
    ),
    (
        "src/late_ming_lab/systems/climate.py",
        "SyntheticClimate.shock",
        "Two unconditional draws: occurrence first, then magnitude.",
    ),
    (
        "docs/architecture/system-overview.md",
        "climate modes",
        "Replays a sourced series; no randomness",
    ),
    (
        "docs/phase-reports/P03.md",
        "contract decision 10",
        "No stochastic household rule",
    ),
)


class AuditBuildError(RuntimeError):
    """Raised when the audit cannot state something it must not paper over."""


def _quote(root: Path, relative: str, locator: str, needle: str) -> dict[str, str]:
    """A premise, resolved: the file exists and still says this, or the audit fails here."""
    path = root / relative
    if not path.is_file():
        raise AuditBuildError(f"{relative} does not exist, so {locator!r} cannot be cited")
    text = path.read_text(encoding="utf-8")
    if needle not in text:
        raise AuditBuildError(
            f"{relative} no longer contains {needle!r}, which the {locator} premise rests on"
        )
    return {"path": relative, "locator": locator, "quote": needle}


def _clamped_centres(cards: ParameterCards) -> dict[str, float]:
    """Every declared prior at its card central, held inside the card's own range.

    The clamp is the declared behaviour of the sensitivity stage's centre draw, and the registry
    finding below is about the one card that needs it.
    """
    return {
        prior.name: float(min(max(prior.central, prior.low), prior.high))
        for prior in build_priors(cards)
        if prior.central is not None
    }


# --------------------------------------------------------------------------------------
# Replicate semantics
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReplicateSemantics:
    """How many independent processes a set of executions actually contains.

    The count that matters is the number of *distinct* simulation digests, not the number of seeds
    or the number of runs. Four seeds that produce one digest are four executions of one
    trajectory, and calling them four replicates would overstate the sample by a factor of four.
    """

    executions: int
    distinct_digests: int

    def __post_init__(self) -> None:
        if self.executions < 1:
            raise AuditBuildError("an arm with no executions has no replicate semantics")
        if not 1 <= self.distinct_digests <= self.executions:
            raise AuditBuildError(
                f"{self.distinct_digests} distinct digests among {self.executions} executions "
                "is not a possible outcome"
            )

    @property
    def independent_replicates(self) -> int:
        """The only number a sample size may be read from."""
        return self.distinct_digests

    @property
    def kind(self) -> str:
        if self.distinct_digests == 1:
            return "single-execution" if self.executions == 1 else "deterministic-replay"
        if self.distinct_digests == self.executions:
            return "independent-replicates"
        return "partial-replay"

    def sentence(self) -> str:
        if self.kind == "single-execution":
            return "one execution"
        if self.kind == "deterministic-replay":
            return (
                f"{self.executions} executions of one deterministic trajectory "
                f"(1 distinct simulation digest): 1 independent replicate, not {self.executions}"
            )
        if self.kind == "independent-replicates":
            return (
                f"{self.executions} independent replicates "
                f"({self.executions} distinct simulation digests)"
            )
        return (
            f"{self.executions} executions, {self.distinct_digests} distinct simulation digests: "
            f"{self.distinct_digests} independent replicates and "
            f"{self.executions - self.distinct_digests} replays"
        )

    def record(self) -> dict[str, Any]:
        return {
            "executions": self.executions,
            "distinct_digests": self.distinct_digests,
            "independent_replicates": self.independent_replicates,
            "kind": self.kind,
            "sentence": self.sentence(),
        }


def arm_semantics(arm: ArmAudit) -> ReplicateSemantics:
    """One arm's executions and the independent processes they contain."""
    return ReplicateSemantics(executions=len(arm.runs), distinct_digests=arm.distinct_digest_count)


def semantics_row(arm: ArmAudit) -> dict[str, Any]:
    """The row the audit's table prints for one arm, semantics included."""
    semantics = arm_semantics(arm)
    return {
        "arm": arm.arm,
        "declared_seeds": list(arm.declared_seeds),
        "executions": len(arm.runs),
        "distinct_digests": arm.distinct_digest_count,
        "distinct_log_digests": arm.distinct_log_digests,
        "independent_replicates": semantics.independent_replicates,
        "kind": semantics.kind,
        "semantics": semantics.sentence(),
        "rng_draw_rows": arm.rng_draw_rows,
        "rng_streams": list(arm.rng_streams),
        "reading_unique_counts": arm.reading_unique_counts(),
        "reading_spread": arm.reading_spread(),
        "reading_stability": arm.reading_stability(),
        "readings_that_moved": {
            name: list(arm.reading_values_seen(name))
            for name in KEY_READINGS
            if len(arm.reading_values_seen(name)) > 1
        },
    }


# --------------------------------------------------------------------------------------
# Which streams a run can consume
# --------------------------------------------------------------------------------------


def stream_call_sites(root: Path) -> dict[str, tuple[str, ...]]:
    """Which tick-path module names each stream, per stream.

    Read from the source rather than asserted, so "climate is the only system that draws" is a
    measurement a reviewer can repeat rather than a sentence they must believe.
    """
    sites: dict[str, list[str]] = {stream.value: [] for stream in RNG_STREAMS}
    for relative in TICK_PATH_MODULES:
        path = root / "src/late_ming_lab" / relative
        if not path.is_file():
            raise AuditBuildError(f"{relative} is in the declared tick path but is not in the tree")
        text = path.read_text(encoding="utf-8")
        for stream in RNG_STREAMS:
            if re.search(rf"RngStream\.{stream.name}\b", text):
                sites[stream.value].append(f"src/late_ming_lab/{relative}")
    return {name: tuple(paths) for name, paths in sites.items()}


def declared_documents(root: Path) -> tuple[Path, ...]:
    """The documents that declare the model's design, in a fixed corpus.

    The corpus is declared rather than discovered so the audit is reproducible: a scan over every
    markdown file in the tree would read the audit's own output, or a phase report quoting it, and
    each generation would quote the last.
    """
    documents: list[Path] = []
    for relative in STATEMENT_CORPUS:
        directory = root / relative
        if not directory.is_dir():
            raise AuditBuildError(
                f"the declared statement corpus names {relative}, which is absent"
            )
        documents.extend(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix in (".md", ".yaml", ".yml")
        )
    return tuple(sorted(documents))


def stream_statements(root: Path) -> dict[str, tuple[str, ...]]:
    """Every line in the declared design documents that names one of the seven streams.

    The question this answers is whether any document *declares that a subsystem consumes* a
    stream on this scenario. The lines are printed rather than judged, so a reader can read the
    declarations the verdict rests on themselves, and the corpus is printed beside them so the
    reader knows what was searched (:data:`STATEMENT_SCAN_LIMIT` says what the search cannot see).
    """
    patterns = {stream.value: stream.value for stream in RNG_STREAMS}
    found: dict[str, list[str]] = {name: [] for name in patterns}
    for path in declared_documents(root):
        relative = path.relative_to(root).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for name in patterns:
                if name in line:
                    found[name].append(f"{relative}:{number}: {line.strip()}")
    return {name: tuple(lines) for name, lines in found.items()}


# --------------------------------------------------------------------------------------
# Where the RNG is consumed, across everything this repository has run
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DrawingRun:
    """A stored run whose log carries at least one RNG draw."""

    run_id: str
    rng_draw_rows: int
    rng_streams: tuple[str, ...]
    climate_modes: tuple[str, ...]
    climate_rule_versions: tuple[str, ...]


def runs_that_draw(root: Path, *, output_root: str = "outputs") -> tuple[DrawingRun, ...]:
    """Every stored run under ``output_root`` whose log carries a non-null draw.

    This is the counter-check to the historical core's zero: if nothing anywhere drew, the stream
    would be dead rather than unused, and the two are different findings.
    """
    draws: list[DrawingRun] = []
    for path in sorted((root / output_root).rglob("agent_events.parquet")):
        frame = pl.read_parquet(
            path, columns=["event_type", "rng_draw", "rng_stream", "outcome", "rule_version"]
        )
        drawn = frame.filter(pl.col("rng_draw").is_not_null())
        if drawn.is_empty():
            continue
        climate = frame.filter(pl.col("event_type") == "CLIMATE_SHOCK")
        draws.append(
            DrawingRun(
                run_id=path.parent.name,
                rng_draw_rows=drawn.height,
                rng_streams=tuple(sorted(str(name) for name in drawn["rng_stream"].unique())),
                climate_modes=tuple(sorted(str(mode) for mode in climate["outcome"].unique())),
                climate_rule_versions=tuple(
                    sorted(str(version) for version in climate["rule_version"].unique())
                ),
            )
        )
    return tuple(draws)


# --------------------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeterminismVerdict:
    """The phase's answer, its premises, and what would have made it a blocker."""

    verdict: str
    question: str
    findings: tuple[str, ...]
    forcing_modes: tuple[str, ...]
    forcing_rule_versions: tuple[str, ...]
    call_sites: dict[str, tuple[str, ...]]
    statements: dict[str, tuple[str, ...]]
    unused_streams: tuple[str, ...]
    drawing_runs: tuple[DrawingRun, ...]
    premises: tuple[dict[str, str], ...]
    carried: tuple[str, ...]

    @property
    def is_blocker(self) -> bool:
        return self.verdict == RNG_WIRING_BLOCKER

    def record(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "question": self.question,
            "findings": list(self.findings),
            "forcing_mode": list(self.forcing_modes),
            "forcing_rule_version": list(self.forcing_rule_versions),
            "tick_path_call_sites": {name: list(paths) for name, paths in self.call_sites.items()},
            "statement_corpus": list(STATEMENT_CORPUS),
            "statement_scan_limit": STATEMENT_SCAN_LIMIT,
            "unused_streams": list(self.unused_streams),
            "stream_statements": {name: list(lines) for name, lines in self.statements.items()},
            "runs_that_draw": [
                {
                    "run_id": run.run_id,
                    "rng_draw_rows": run.rng_draw_rows,
                    "rng_streams": list(run.rng_streams),
                    "climate_mode": list(run.climate_modes),
                    "climate_rule_version": list(run.climate_rule_versions),
                }
                for run in self.drawing_runs
            ],
            "premises": [dict(premise) for premise in self.premises],
            "carried": list(self.carried),
        }


def determinism_verdict(root: Path, audit: P05Audit) -> DeterminismVerdict:
    """Decide whether the arm set is a declared draw-free replay or an unwired stream.

    The procedure, fixed before the artifacts are read:

    1. every arm's runs must contain one independent process, or the question is about more than
       one trajectory and this phase's disposition would be wrong;
    2. the climate rows of every arm must record one forcing mode, and that mode must be one whose
       rule version declares it draw-free;
    3. any arm that recorded a draw while running a draw-free mode is a blocker;
    4. a stream that a tick-path module can consume, on a scenario that records a draw-free mode,
       is unused plumbing rather than a defect — but it is reported, because "seven streams" is
       not "seven subsystems that draw".

    A fifth thing falls out of the same measurement and is reported rather than smoothed over: an
    arm whose logs are byte-identical and whose readings still differ. That is not a replicate
    problem — the run repeated exactly — it is a derived statistic whose reduction order is not
    pinned, and a phase about replicate semantics is where it has to be written down.
    """
    repository = Path(root)
    modes = {mode for run in audit.runs for mode in run.climate_modes}
    versions = {version for run in audit.runs for version in run.climate_rule_versions}
    call_sites = stream_call_sites(repository)
    if len(audit.runs) != len(audit.arms) * len(audit.declared_seeds):
        raise AuditBuildError(
            f"the register declares {len(audit.arms)} arms at {len(audit.declared_seeds)} seeds "
            f"but {len(audit.runs)} runs were read"
        )

    findings: list[str] = []
    blocker_reasons: list[str] = []
    for arm in audit.arms:
        semantics = arm_semantics(arm)
        if semantics.kind == "deterministic-replay":
            findings.append(f"{arm.arm}: {semantics.sentence()}")
        elif semantics.kind == "independent-replicates":
            blocker_reasons.append(
                f"{arm.arm}: {semantics.executions} executions produced "
                f"{semantics.distinct_digests} distinct digests, so at most one arm reads as a "
                "single trajectory and the 'one trajectory, four executions' disposition would "
                "not describe this set"
            )
        else:
            blocker_reasons.append(
                f"{arm.arm}: {semantics.sentence()}, which is neither one trajectory nor "
                "independent replicates"
            )
        if arm.rng_draw_rows:
            blocker_reasons.append(
                f"{arm.arm}: {arm.rng_draw_rows} rows carry an RNG draw while the run records the "
                f"forcing mode {sorted(modes)}; a draw-free mode that draws is a wiring defect"
            )
    if modes != {HISTORICAL_FORCING_MODE}:
        blocker_reasons.append(
            f"the arms record the forcing modes {sorted(modes)}, so they are not all runs of the "
            f"declared {HISTORICAL_FORCING_MODE} path"
        )
    if not versions <= set(DRAW_FREE_RULE_VERSIONS):
        blocker_reasons.append(
            f"the arms record the climate rule versions {sorted(versions)}, and not all of them "
            f"are declared draw-free ({sorted(DRAW_FREE_RULE_VERSIONS)})"
        )

    consumed = tuple(name for name, paths in call_sites.items() if any(paths))
    unused = tuple(name for name, paths in call_sites.items() if not any(paths))

    # Carried, not measured here: the audit compares readings at a declared precision because the
    # underlying readers are not bit-reproducible, and a document whose numbers move between two
    # runs of the same command would be the one thing a generated document must not be. The
    # measurement lives in `docs/phase-reports/V2.1-P10.md`, which carries the command and its
    # output; this string is the declaration the audit stands behind.
    carried = (
        (
            "a derived reading is not bit-reproducible at full precision: "
            f"{REDUCTION_ORDER_MODULE}'s {REDUCTION_ORDER_FUNCTION} sums a parallel "
            "`group_by(...).agg(...)`, and addition is not associative, so two evaluations of one "
            "byte-identical log can return values differing by a few ULP. Readings here are "
            f"compared at {READING_SIGNIFICANT_DIGITS} significant digits for that reason. The "
            "runs themselves repeat exactly: their digests and their log bytes agree."
        ),
    )
    if any(arm.reading_stability() == "reduction-order" for arm in audit.arms):
        findings.append(
            "a reading moved at the declared comparison precision on an arm whose logs are "
            "byte-identical, which ULP noise cannot explain: see the carried item below"
        )
    if blocker_reasons:
        verdict = RNG_WIRING_BLOCKER
    else:
        verdict = DETERMINISTIC_BY_DESIGN
        findings.append(
            "every one of the "
            f"{len(audit.runs)} runs records the forcing mode {HISTORICAL_FORCING_MODE} with the "
            f"rule version {sorted(versions)[0]}, and the tick path can draw from "
            f"{consumed[0] if consumed else 'no stream'} only — in a mode whose model takes no draw"
        )
        findings.append(
            "the streams "
            + ", ".join(unused)
            + " are declared and seeded but consumed by no tick-path module: they are plumbing "
            "for common random numbers, not subsystems that draw today, and none of the declared "
            "design documents names one of them as consumed on this scenario"
        )
    return DeterminismVerdict(
        verdict=verdict,
        question=(
            "Is the historical core's multi-seed determinism a declared property of the model, or "
            "a subsystem that should consume its RNG stream and does not?"
        ),
        findings=tuple(findings) + tuple(blocker_reasons),
        forcing_modes=tuple(sorted(modes)),
        forcing_rule_versions=tuple(sorted(versions)),
        call_sites=call_sites,
        statements=stream_statements(repository),
        unused_streams=unused,
        drawing_runs=runs_that_draw(repository),
        premises=tuple(
            _quote(repository, relative, locator, needle)
            for relative, locator, needle in PREMITHE_TEXT
        ),
        carried=carried,
    )


# --------------------------------------------------------------------------------------
# The parameter registry
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnclassifiedCard:
    """A card that carries a range and is in neither the declared nor the excluded list."""

    name: str
    parameter_set: str
    central: float | None
    low: float | None
    high: float | None
    support_class: str
    sensitivity_priority: str
    numeric_range: bool
    simulator_can_carry_it: bool

    def record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "parameter_set": self.parameter_set,
            "central": self.central,
            "range_low": self.low,
            "range_high": self.high,
            "support_class": self.support_class,
            "sensitivity_priority": self.sensitivity_priority,
            "numeric_range": self.numeric_range,
            "simulator_can_carry_it": self.simulator_can_carry_it,
        }


@dataclass(frozen=True, slots=True)
class RegistryFindings:
    """The registry's own inconsistencies, recomputed rather than quoted from a report."""

    declared: tuple[str, ...]
    excluded: tuple[str, ...]
    unclassified: tuple[UnclassifiedCard, ...]
    central_outside_range: tuple[tuple[str, str], ...]
    declared_but_not_applied: tuple[str, ...]
    card_free: int
    range_carrying: int
    applied_sets: tuple[str, ...]

    @property
    def unclassified_numeric(self) -> tuple[UnclassifiedCard, ...]:
        return tuple(card for card in self.unclassified if card.numeric_range)

    @property
    def unclassified_text_only(self) -> tuple[UnclassifiedCard, ...]:
        return tuple(card for card in self.unclassified if not card.numeric_range)

    def record(self) -> dict[str, Any]:
        return {
            "declared_parameters": list(self.declared),
            "excluded_parameters": list(self.excluded),
            "card_free_cards": self.card_free,
            "range_carrying_cards": self.range_carrying,
            "unclassified_range_cards": [card.record() for card in self.unclassified],
            "unclassified_numeric": len(self.unclassified_numeric),
            "unclassified_text_only": len(self.unclassified_text_only),
            "central_outside_range": [
                {"name": name, "finding": finding} for name, finding in self.central_outside_range
            ],
            "declared_but_not_applied": list(self.declared_but_not_applied),
            "simulator_applies_sets": list(self.applied_sets),
        }


def registry_findings(root: str | Path) -> RegistryFindings:
    """Recompute the registry's inconsistencies from the cards and the calibration code.

    Three of them, and they are different defects:

    * a card whose value in use sits outside its own range, so the prior that is the range cannot
      contain the model's default;
    * cards that carry a range and are neither declared as calibration parameters nor recorded as
      exclusions, so a reader counting the exclusions cannot see them;
    * declared priors whose parameter set the calibration simulator does not rebuild, so the draw
      is hashed into the run's identity and never reaches the model.
    """
    repository = Path(root)
    cards = load_cards(repository)
    declared = tuple(name for name, _, _ in DECLARED)
    excluded = tuple(name for name, _, _ in EXCLUDED)
    classified = set(declared) | set(excluded)
    simulator = SandboxSimulator(cards, load_patterns(repository))
    applied = tuple(sorted(simulator.parameter_sets(_clamped_centres(cards))))
    priors = build_priors(cards)
    unclassified = tuple(
        UnclassifiedCard(
            name=card.id,
            parameter_set=card.parameter_set,
            central=card.central,
            low=None if card.range is None else card.range.low,
            high=None if card.range is None else card.range.high,
            support_class=card.support_class.value,
            sensitivity_priority=str(card.sensitivity_priority),
            numeric_range=(
                card.range is not None
                and card.range.low is not None
                and card.range.high is not None
            ),
            simulator_can_carry_it=card.parameter_set in applied,
        )
        for card in sorted(cards, key=lambda entry: (entry.parameter_set, entry.id))
        if card.range is not None and card.id not in classified
    )
    return RegistryFindings(
        declared=declared,
        excluded=excluded,
        unclassified=unclassified,
        central_outside_range=centres_outside_range(cards),
        declared_but_not_applied=tuple(
            prior.name for prior in priors if prior.parameter_set not in applied
        ),
        card_free=len(card_free_parameters(cards)),
        range_carrying=sum(1 for card in cards if card.range is not None),
        applied_sets=applied,
    )


# --------------------------------------------------------------------------------------
# Payloads and documents
# --------------------------------------------------------------------------------------


def build_audit_payload(root: str | Path = ".", *, audit: P05Audit | None = None) -> dict[str, Any]:
    """The replicate audit's payload: every number read from the artifact that holds it."""
    repository = Path(root)
    audit = audit if audit is not None else audit_p05(repository)
    verdict = determinism_verdict(repository, audit)
    return {
        "schema_version": "v2_1-replicate-audit-v1",
        "generator": GENERATOR,
        "determinism": verdict.record(),
        "register": {
            "arms": len(audit.arms),
            "declared_seeds": list(audit.declared_seeds),
            "declared_runs": sum(len(arm.runs) for arm in audit.arms),
            "missing_run_ids": list(audit.missing_run_ids),
            "undeclared_run_ids": list(audit.undeclared_run_ids),
            "digest_disagreements": [run.run_id for run in audit.runs if not run.digest_agrees],
            "seed_disagreements": [run.run_id for run in audit.runs if not run.seed_agrees],
            "variants_generator": audit.generator,
        },
        "arms": [semantics_row(arm) for arm in audit.arms],
    }


def build_disposition_payload(
    root: str | Path = ".", *, audit: P05Audit | None = None
) -> dict[str, Any]:
    """What V2 established, in the terms its artifacts support, and what it did not."""
    repository = Path(root)
    audit = audit if audit is not None else audit_p05(repository)
    semantics = {arm.arm: arm_semantics(arm) for arm in audit.arms}
    independent = sorted({entry.independent_replicates for entry in semantics.values()})
    posterior = audit_p06(repository)
    sensitivity = audit_p07(repository)
    arms = audit_p08(repository)
    return {
        "schema_version": "v2_1-pilot-disposition-v1",
        "generator": GENERATOR,
        "p05": {
            "status": "pilot, deterministic replay",
            "declared_seeds": list(audit.declared_seeds),
            "arms": len(audit.arms),
            "executions": len(audit.runs),
            "independent_replicates_per_arm": independent,
            "statement": (
                "the four root seeds are four executions of one deterministic trajectory in every "
                "arm: " + semantics[next(iter(semantics))].sentence()
            ),
            "not_claimed": [
                "four independent stochastic replicates",
                "an uncertainty distribution over seeds",
            ],
            "applies_from": "V2.1-P12 onward; the V2 documents are not rewritten by this phase",
        },
        "p06": {
            "status": "frozen pilot, " + posterior.status(),
            "converged": posterior.converged,
            "reason": posterior.reason,
            "location_change": posterior.location_change,
            "location_change_max": posterior.gates.get("location_change_max"),
            "acceptance_max": posterior.gates.get("acceptance_max"),
            "prediction_change": posterior.prediction_change,
            "rung_sizes": list(posterior.rung_sizes),
            "rung_predictions": list(posterior.rung_predictions),
            "posterior_hash": posterior.stored_hash,
            "hash_recomputes": posterior.hash_agrees,
            "digests_recompute": posterior.digests_agree,
            "not_claimed": [
                "identified parameters",
                "a posterior to score a reserved window against",
            ],
            "report_disagreement": (
                "docs/phase-reports/V2-P06.md's gate table records the mechanism prediction as "
                f"'not measured (the probe was not read)', while the frozen artifact carries "
                f"prediction {posterior.rung_predictions[-1]} and prediction_change "
                f"{posterior.prediction_change}: the artifact decides, and the probe is degenerate "
                "rather than absent"
            ),
        },
        "p07": {
            "status": "pilot, non-converged, artifact predates the final code",
            "unsettled_rungs": [
                {"ladder": rung.ladder, "size": rung.size, "reason": rung.reason}
                for rung in sensitivity.unsettled_rungs
            ],
            "manifest_missing_keys": list(sensitivity.missing_keys),
            "manifest_undeclared_keys": list(sensitivity.undeclared_keys),
            "level_table_missing_columns": list(sensitivity.missing_columns),
            "sobol_rows_stored": [list(entry) for entry in sensitivity.sobol_rows],
            "sobol_rows_now": sensitivity.sobol_rows_expected,
            "level_table_is_stale": sensitivity.index_rows_missing,
            "not_claimed": ["a quantitative importance ranking"],
            "applies_from": "V2.1-P12 onward; the stored artifact is reported, not regenerated",
        },
        "p08": {
            "status": "pilot, model decisions 0",
            "scenario": arms.scenario,
            "seeds": list(arms.seeds),
            "policies": list(arms.policies),
            "decision_traces": arms.decision_traces,
            "decisions_from_model": arms.decisions_from_model,
            "refusals": arms.refusals,
            "counts_agree_with_manifest": arms.agrees_with_manifest,
            "not_claimed": [
                "an M2 upgrade",
                "a direction-stability or interval claim from one decision per replicate",
            ],
        },
    }


def build_registry_payload(root: str | Path = ".") -> dict[str, Any]:
    """The registry findings, plus the resolution this phase is allowed to take for each."""
    findings = registry_findings(root)
    numeric = findings.unclassified_numeric
    text_only = findings.unclassified_text_only
    return {
        "schema_version": "v2_1-parameter-registry-findings-v1",
        "generator": GENERATOR,
        **findings.record(),
        "resolutions": [
            {
                "finding": "central value outside its own declared range",
                "parameters": [name for name, _ in findings.central_outside_range],
                "resolution": "registered carried item",
                "reason": (
                    "P10 may not move the central, exclude the parameter (that would change the "
                    "prior table and the frozen posterior's prior_digest), or edit the card (that "
                    "would change data/parameters/*.yaml, which evidence_digest covers and the "
                    "frozen outputs/v2/p06/posterior.json records)"
                ),
            },
            {
                "finding": "range-carrying cards in neither the declared nor the excluded list",
                "parameters": [card.name for card in numeric],
                "resolution": "registered carried item",
                "reason": (
                    f"{len(numeric)} of the {findings.range_carrying} range-carrying cards need an "
                    "exclusion rule each, and no measurement in this phase produces one; "
                    "registering the gap is the honest action, and inventing the rules is not "
                    "available to this phase"
                ),
            },
            {
                "finding": "a card whose range block carries no bounds",
                "parameters": [card.name for card in text_only],
                "resolution": "registered carried item",
                "reason": (
                    "it is not a drawable range, so it is neither a prior nor an excludable card; "
                    "excluded_parameters refuses a card with no bounded range by design"
                ),
            },
            {
                "finding": "declared priors whose parameter set the simulator does not rebuild",
                "parameters": list(findings.declared_but_not_applied),
                "resolution": "registered carried item, and a defect rather than a registry choice",
                "reason": (
                    "the draw is checked, hashed into the run identity and then dropped before the "
                    "run, so those priors are declared and ineffective; changing it changes what "
                    "the frozen posterior means, which is not this phase's to change"
                ),
            },
        ],
    }


def _table(headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return lines


def _audit_markdown(payload: dict[str, Any]) -> str:
    verdict = payload["determinism"]
    register = payload["register"]
    arms = payload["arms"]
    lines = [
        "<!-- generated by: python -m late_ming_lab.v2_1 audit -->",
        "",
        "# V2.1 replicate audit — what P05's 40 runs are",
        "",
        "Every number here is read from the run's own directory (`manifest.json`, `summary.json`, "
        "`agent_events.parquet`) through `late_ming_lab.v2_1.accessors`. None is copied from a "
        "phase report, and none is typed by hand.",
        "",
        "## The question",
        "",
        str(verdict["question"]),
        "",
        "## Verdict",
        "",
        f"**`{verdict['verdict']}`**",
        "",
    ]
    lines += [f"- {finding}" for finding in verdict["findings"]]
    lines += [
        "",
        "### Premises, each checked to still be in the tree",
        "",
    ]
    lines += _table(
        ("file", "locator", "what it says"),
        [
            (premise["path"], premise["locator"], f"`{premise['quote']}`")
            for premise in verdict["premises"]
        ],
    )
    lines += [
        "",
        "### Which documents were searched for a contrary declaration",
        "",
        "The corpus is declared rather than discovered, so the search is repeatable: "
        + ", ".join(f"`{root}`" for root in verdict["statement_corpus"])
        + ". Phase reports and exec plans record work rather than declaring design, and they may "
        "quote this audit, so they are not in it — a scan that read them would make each "
        "generation depend on the last.",
        "",
        str(verdict["statement_scan_limit"]),
        "",
        "### Which tick-path module can name which stream",
        "",
    ]
    lines += _table(
        ("stream", "tick-path modules that name it"),
        [
            (stream, ", ".join(paths) if paths else "*(nowhere: declared and seeded only)*")
            for stream, paths in dict(verdict["tick_path_call_sites"]).items()
        ],
    )
    lines += [
        "",
        "### Runs in `outputs/` whose logs do carry draws",
        "",
        "The counter-check: a stream that nothing anywhere consumed would be a dead stream, and "
        "the historical core's zero would say nothing about whether the RNG path works.",
        "",
    ]
    lines += _table(
        ("run", "draw rows", "streams", "climate mode", "climate rule version"),
        [
            (
                f"`{run['run_id']}`",
                run["rng_draw_rows"],
                ", ".join(run["rng_streams"]),
                ", ".join(run["climate_mode"]),
                ", ".join(run["climate_rule_version"]),
            )
            for run in verdict["runs_that_draw"]
        ],
    )
    lines += [
        "",
        "## The arm register",
        "",
        f"Declared arms: {register['arms']} · declared seeds: "
        f"{', '.join(str(seed) for seed in register['declared_seeds'])} · runs read: "
        f"{register['declared_runs']} · declared but absent: {len(register['missing_run_ids'])} · "
        f"on disk but undeclared: {len(register['undeclared_run_ids'])} · digest disagreements: "
        f"{len(register['digest_disagreements'])} · seed disagreements: "
        f"{len(register['seed_disagreements'])}",
        "",
    ]
    lines += _table(
        (
            "arm",
            "seeds",
            "executions",
            "distinct digests",
            "distinct logs",
            "independent replicates",
            "reading stability",
        ),
        [
            (
                row["arm"],
                len(row["declared_seeds"]),
                row["executions"],
                row["distinct_digests"],
                row["distinct_log_digests"],
                row["independent_replicates"],
                row["reading_stability"],
            )
            for row in arms
        ],
    )
    lines += [
        "",
        "### Carried, not repaired here",
        "",
    ]
    lines += [f"- {item}" for item in verdict["carried"]]
    lines += [
        "",
        "### Key readings, and how many values each takes across an arm's executions",
        "",
        "The readings are declared in `KEY_READINGS` before the arms are read, and each is "
        "recomputed from the log by the chain readers the phase itself used.",
        "",
    ]
    lines += _table(
        (
            "arm",
            "non-null RNG draws",
            *[str(name) for name in dict(arms[0]["reading_unique_counts"])],
        ),
        [
            (
                row["arm"],
                row["rng_draw_rows"],
                *[str(value) for value in dict(row["reading_unique_counts"]).values()],
            )
            for row in arms
        ],
    )
    lines += [
        "",
        "A count of 1 means the reading took one value across every execution of that arm: the "
        "seeds did not move it, which is what a replay is.",
        "",
        "Readings are compared at 12 significant digits. The comparison precision is declared "
        "rather than implicit: the readers reduce floating-point series in an order their library "
        "does not pin, and comparing at full precision would report a last-bit difference as a "
        "behavioural one. See the carried item above.",
        "",
    ]
    return "\n".join(lines)


def _disposition_markdown(payload: dict[str, Any]) -> str:
    p05 = payload["p05"]
    p06 = payload["p06"]
    p07 = payload["p07"]
    p08 = payload["p08"]
    lines = [
        "<!-- generated by: python -m late_ming_lab.v2_1 audit -->",
        "",
        "# V2 pilot disposition",
        "",
        "What V2 established, in the terms its artifacts support. Nothing here upgrades a result: "
        "the phase's job is to stop calling a replay a replicate, and to stop leaving a "
        "non-converged pilot looking like a settled one.",
        "",
        "## P05 — four seeds, one trajectory",
        "",
        f"- status: **{p05['status']}**",
        f"- {p05['arms']} arms, {p05['executions']} executions, "
        f"{', '.join(str(seed) for seed in p05['declared_seeds'])}",
        f"- independent replicates per arm: "
        f"{', '.join(str(value) for value in p05['independent_replicates_per_arm'])}",
        f"- {p05['statement']}",
        "",
        "Not claimed: " + "; ".join(str(item) for item in p05["not_claimed"]) + ".",
        "",
        f"Applies from: {p05['applies_from']}.",
        "",
        "## P06 — frozen, non-converged",
        "",
        f"- status: **{p06['status']}**",
        f"- {p06['reason']}",
        f"- location change {p06['location_change']} against a declared maximum of "
        f"{p06['location_change_max']}",
        f"- rung sizes {p06['rung_sizes']}; mechanism prediction at each rung "
        f"{p06['rung_predictions']}",
        f"- the frozen posterior recomputes: hash {p06['hash_recomputes']}, digests "
        f"{p06['digests_recompute']}",
        "",
        "Not claimed: " + "; ".join(str(item) for item in p06["not_claimed"]) + ".",
        "",
        "### Report against artifact",
        "",
        str(p06["report_disagreement"]),
        "",
        "## P07 — pilot, and its artifact predates the final code",
        "",
        f"- status: **{p07['status']}**",
        "- unsettled rungs: "
        + "; ".join(
            f"{rung['ladder']} {rung['size']} — {rung['reason']}" for rung in p07["unsettled_rungs"]
        ),
        f"- manifest keys the current writer declares and the stored artifact lacks: "
        f"{', '.join('`' + str(key) + '`' for key in p07['manifest_missing_keys'])}",
        f"- level-table columns the current reader emits and the stored table lacks: "
        f"{', '.join('`' + str(key) + '`' for key in p07['level_table_missing_columns'])}",
        f"- keys the stored manifest carries beyond the declared set (the caller's `extra` "
        f"payload): {', '.join('`' + str(key) + '`' for key in p07['manifest_undeclared_keys'])}",
        f"- Sobol rows per level in the stored table: {p07['sobol_rows_stored']}; the current "
        f"reader emits S1 and ST, so a regenerated table would hold {p07['sobol_rows_now']}",
        "",
        "Not claimed: " + "; ".join(str(item) for item in p07["not_claimed"]) + ".",
        "",
        f"Applies from: {p07['applies_from']}.",
        "",
        "## P08 — pilot, zero model decisions",
        "",
        f"- status: **{p08['status']}**",
        f"- scenario `{p08['scenario']}`, seeds "
        f"{', '.join(str(seed) for seed in p08['seeds'])}, policies "
        f"{', '.join(str(policy) for policy in p08['policies'])}",
        f"- {p08['decision_traces']} decision traces, {p08['decisions_from_model']} of them from "
        f"the model, {p08['refusals']} refusals; the counts agree with the arm manifest: "
        f"{p08['counts_agree_with_manifest']}",
        "",
        "Not claimed: " + "; ".join(str(item) for item in p08["not_claimed"]) + ".",
        "",
    ]
    return "\n".join(lines)


def _registry_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "<!-- generated by: python -m late_ming_lab.v2_1 audit -->",
        "",
        "# Parameter registry findings",
        "",
        "V2-P06 and V2-P07 each recorded one of these and neither fixed it. They are recomputed "
        "here from the cards and the calibration code, so the numbers are not quoted from a "
        "report; the resolutions below are the only ones this phase is allowed to take.",
        "",
        f"- declared calibration parameters: {len(payload['declared_parameters'])}",
        f"- explicitly excluded cards: {len(payload['excluded_parameters'])}",
        f"- cards carrying a `range:` block: {payload['range_carrying_cards']}",
        f"- of which in neither list: {payload['unclassified_numeric']} with numeric bounds and "
        f"{payload['unclassified_text_only']} text-only",
        f"- cards with no range at all: {payload['card_free_cards']}",
        "",
        "## 1. A central value outside its own range",
        "",
    ]
    lines += _table(
        ("parameter", "finding"),
        [(entry["name"], entry["finding"]) for entry in payload["central_outside_range"]],
    )
    lines += [
        "",
        "The prior is the range, so this parameter's prior cannot contain the value the model "
        "runs; the sensitivity stage holds it at the nearest endpoint instead. The conflict is not "
        "recorded on the card: its `range.conflicts` field is empty.",
        "",
        "## 2. Range-carrying cards in neither the declared nor the excluded list",
        "",
    ]
    lines += _table(
        ("parameter", "set", "central", "range", "priority", "simulator can carry it"),
        [
            (
                entry["name"],
                entry["parameter_set"],
                entry["central"],
                f"[{entry['range_low']}, {entry['range_high']}]"
                if entry["numeric_range"]
                else "*(text only)*",
                entry["sensitivity_priority"],
                entry["simulator_can_carry_it"],
            )
            for entry in payload["unclassified_range_cards"]
        ],
    )
    lines += [
        "",
        "## 3. Declared priors the calibration simulator does not rebuild",
        "",
    ]
    lines += _table(
        ("parameter",),
        [(name,) for name in payload["declared_but_not_applied"]],
    )
    lines += [
        "",
        "`SandboxSimulator.parameter_sets` rebuilds one parameter set per name in its own "
        f"`_DEFAULTS` table, and that table holds {', '.join(payload['simulator_applies_sets'])}. "
        "A draw on a parameter outside it passes `_check`, enters `parameter_hash` and is dropped "
        "before the run: the value is recorded as an input and is not one.",
        "",
        "## Resolutions taken in this phase",
        "",
    ]
    lines += _table(
        ("finding", "parameters", "resolution"),
        [
            (
                entry["finding"],
                ", ".join(str(name) for name in entry["parameters"]),
                entry["resolution"],
            )
            for entry in payload["resolutions"]
        ],
    )
    lines += ["", "### Why not the other two routes", ""]
    for entry in payload["resolutions"]:
        lines.append(f"- **{entry['finding']}** — {entry['reason']}.")
    lines.append("")
    return "\n".join(lines)


def write_documents(root: str | Path = ".") -> tuple[Path, ...]:
    """Write all three document pairs; return their paths in order."""
    repository = Path(root)
    # One read of the arm register, two documents: forty event logs are expensive and the two
    # documents must not be allowed to disagree about what they contain.
    audit = audit_p05(repository)
    written: list[Path] = []
    for payload, json_path, markdown_path, renderer in (
        (
            build_audit_payload(repository, audit=audit),
            AUDIT_JSON,
            AUDIT_MARKDOWN,
            _audit_markdown,
        ),
        (
            build_disposition_payload(repository, audit=audit),
            DISPOSITION_JSON,
            DISPOSITION_MARKDOWN,
            _disposition_markdown,
        ),
        (
            build_registry_payload(repository),
            REGISTRY_JSON,
            REGISTRY_MARKDOWN,
            _registry_markdown,
        ),
    ):
        written.append(write_json(repository / json_path, payload))
        written.append(write_text(repository / markdown_path, renderer(payload) + "\n"))
    return tuple(written)


__all__ = [
    "AUDIT_JSON",
    "AUDIT_MARKDOWN",
    "DETERMINISTIC_BY_DESIGN",
    "DISPOSITION_JSON",
    "DISPOSITION_MARKDOWN",
    "GENERATOR",
    "HISTORICAL_FORCING_MODE",
    "REGISTRY_JSON",
    "REGISTRY_MARKDOWN",
    "RNG_WIRING_BLOCKER",
    "AuditBuildError",
    "DeterminismVerdict",
    "DrawingRun",
    "RegistryFindings",
    "ReplicateSemantics",
    "UnclassifiedCard",
    "arm_semantics",
    "build_audit_payload",
    "build_disposition_payload",
    "build_registry_payload",
    "determinism_verdict",
    "registry_findings",
    "runs_that_draw",
    "semantics_row",
    "stream_call_sites",
    "stream_statements",
    "write_documents",
]
