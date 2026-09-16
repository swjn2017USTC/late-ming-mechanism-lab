"""Read-only accessors over the V2 artifacts V2.1 audits.

Every number this package prints is read here, from the artifact that holds it: a run's manifest,
its summary, its event log, the frozen posterior, the sensitivity manifest and the runtime arms.
Nothing in this module writes to `outputs/v2`, runs a simulation, or accepts a count from a caller.

The one thing it does not do is interpret. Whether four seeds under one digest are four replicates
or one trajectory executed four times is :mod:`late_ming_lab.v2_1.audit`'s question, and it is asked
there so the accessor stays a description of what is on disk.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import polars as pl

from late_ming_lab.analysis.band_chain import band_chain_summary
from late_ming_lab.analysis.chains import chain_summary
from late_ming_lab.calibration.freeze import evidence_digest, objective_digest, prior_digest
from late_ming_lab.calibration.v2 import _objective_checks, _prior_bounds
from late_ming_lab.core.hashing import canonical_json, hash_text
from late_ming_lab.evidence.cards import ParameterCards, load_cards
from late_ming_lab.experiments.sensitivity import sobol_design, sobol_indices, sweep_parameters
from late_ming_lab.experiments.sensitivity_v2 import DECLARED_MANIFEST_KEYS
from late_ming_lab.storage.run_store import RunStore

#: The artifacts this package reads, and the paths a reader is told to open.
VARIANTS_DOCUMENT: Final[str] = "docs/v2/mechanism-variants.json"
P05_ROOT: Final[str] = "outputs/v2/p05"
P06_POSTERIOR: Final[str] = "outputs/v2/p06/posterior.json"
P07_MANIFEST: Final[str] = "outputs/v2/p07/sensitivity-manifest.json"
P07_LEVELS: Final[str] = "outputs/v2/p07/sensitivity-levels.parquet"
P08_ARMS: Final[str] = "outputs/v2/p08/runtime-arms.json"
P08_TRACES: Final[str] = "outputs/v2/p08/policy-arm-traces.parquet"
P08_REFUSALS: Final[str] = "outputs/v2/p08/policy-arm-refusals.parquet"

#: The readings every P05 arm is audited on, fixed here so that a reading cannot be chosen after
#: seeing which one happened to move. The first is the log's own size; the rest are one number from
#: each instrumented chain, recomputed from the events by the same readers the phase used.
KEY_READINGS: Final[tuple[str, ...]] = (
    "event_rows",
    "band_chain_largest_share_end",
    "price_max_tael_per_shi",
    "relief_coverage_share",
    "migration_movers_households",
)

#: The precision at which a reading is compared between executions. A reading is a floating-point
#: reduction, and a reduction whose order is not pinned returns a last-bit-different value for
#: byte-identical input; comparing at full precision would report that as a behavioural
#: difference, which it is not. Twelve significant digits is far coarser than the artefact (a few
#: ULP, relative spread ~1e-16) and far finer than any effect this project reads.
READING_SIGNIFICANT_DIGITS: Final[int] = 12

#: The modules and functions behind the carried finding below, named so a reader can reproduce it.
REDUCTION_ORDER_MODULE: Final[str] = "src/late_ming_lab/analysis/military.py"
REDUCTION_ORDER_FUNCTION: Final[str] = "band_series"


def compared(value: float) -> float:
    """A reading at the declared comparison precision."""
    return float(f"%.{READING_SIGNIFICANT_DIGITS}g" % value)


class AuditError(RuntimeError):
    """Raised when an artifact this audit declares is absent or cannot be read as declared."""


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AuditError(f"{path} does not exist: this audit reads it rather than assuming it")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AuditError(f"{path} is not a JSON object")
    return payload


@dataclass(frozen=True, slots=True)
class DeclaredRun:
    """One P05 run as `docs/v2/mechanism-variants.json` declares it."""

    arm: str
    run_id: str
    root_seed: int
    simulation_digest: str
    expects_effect: bool


@dataclass(frozen=True, slots=True)
class RunAudit:
    """One P05 run as the artifacts on disk describe it."""

    run_id: str
    arm: str
    root_seed: int
    declared_digest: str
    observed_digest: str
    manifest_seed: int
    rng_draw_rows: int
    rng_streams: tuple[str, ...]
    climate_modes: tuple[str, ...]
    climate_rule_versions: tuple[str, ...]
    log_digest: str
    readings: dict[str, float]

    @property
    def digest_agrees(self) -> bool:
        return self.declared_digest == self.observed_digest

    @property
    def seed_agrees(self) -> bool:
        return self.root_seed == self.manifest_seed


@dataclass(frozen=True, slots=True)
class ArmAudit:
    """One arm's declared seeds and the runs that carry them."""

    arm: str
    declared_seeds: tuple[int, ...]
    runs: tuple[RunAudit, ...]

    @property
    def distinct_digests(self) -> tuple[str, ...]:
        return tuple(sorted({run.observed_digest for run in self.runs}))

    @property
    def distinct_digest_count(self) -> int:
        return len(self.distinct_digests)

    @property
    def rng_draw_rows(self) -> int:
        return sum(run.rng_draw_rows for run in self.runs)

    @property
    def rng_streams(self) -> tuple[str, ...]:
        return tuple(sorted({stream for run in self.runs for stream in run.rng_streams}))

    @property
    def distinct_log_digests(self) -> int:
        """How many byte-distinct event logs the arm's executions left behind."""
        return len({run.log_digest for run in self.runs})

    def reading_unique_counts(self) -> dict[str, int]:
        """How many distinct values each declared reading takes across the arm's runs."""
        return {
            name: len({compared(run.readings[name]) for run in self.runs}) for name in KEY_READINGS
        }

    def reading_values(self, name: str) -> tuple[float, ...]:
        return tuple(run.readings[name] for run in self.runs)

    def reading_values_seen(self, name: str) -> tuple[float, ...]:
        """The distinct values a reading took at the declared precision, so the spread is shown."""
        return tuple(sorted({compared(run.readings[name]) for run in self.runs}))

    def reading_spread(self) -> dict[str, float]:
        """Each reading's spread across the arm's executions, relative to its largest value."""
        spread: dict[str, float] = {}
        for name in KEY_READINGS:
            seen = self.reading_values_seen(name)
            scale = max(abs(value) for value in seen)
            spread[name] = 0.0 if scale == 0.0 else (seen[-1] - seen[0]) / scale
        return spread

    def reading_stability(self) -> str:
        """Whether the arm's readings repeated, and if not, at which level it moved.

        ``identical-bytes``    every execution left the same log and every reading repeated;
        ``reduction-order``    the logs are byte-identical and a reading still moved at the
                               declared precision, which a floating-point reduction cannot explain;
        ``different-runs``     the executions are not the same run, so their readings need not
                               agree.
        """
        if self.distinct_log_digests > 1:
            return "different-runs"
        if any(count > 1 for count in self.reading_unique_counts().values()):
            return "reduction-order"
        return "identical-bytes"


@dataclass(frozen=True, slots=True)
class P05Audit:
    """The whole P05 arm register: what was declared, what is on disk, and what disagrees."""

    generator: str
    declared_arms: tuple[str, ...]
    arms: tuple[ArmAudit, ...]
    missing_run_ids: tuple[str, ...]
    undeclared_run_ids: tuple[str, ...]

    @property
    def declared_seeds(self) -> tuple[int, ...]:
        return tuple(sorted({seed for arm in self.arms for seed in arm.declared_seeds}))

    @property
    def runs(self) -> tuple[RunAudit, ...]:
        return tuple(run for arm in self.arms for run in arm.runs)


def declared_p05_runs(root: str | Path) -> tuple[str, tuple[DeclaredRun, ...]]:
    """The P05 arms the phase's own document declares, and the generator that wrote it."""
    payload = _read_json(Path(root) / VARIANTS_DOCUMENT)
    raw = payload.get("arms")
    if not isinstance(raw, list) or not raw:
        raise AuditError(f"{VARIANTS_DOCUMENT} declares no arms")
    runs: list[DeclaredRun] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise AuditError(f"{VARIANTS_DOCUMENT} holds an arm that is not an object")
        runs.append(
            DeclaredRun(
                arm=str(entry["arm"]),
                run_id=str(entry["run_id"]),
                root_seed=int(entry["root_seed"]),
                simulation_digest=str(entry["simulation_digest"]),
                expects_effect=bool(entry["expects_effect"]),
            )
        )
    generator = str(payload.get("generator", ""))
    if not generator:
        raise AuditError(f"{VARIANTS_DOCUMENT} does not name its generator")
    return generator, tuple(runs)


def read_p05_run(store: RunStore, declared: DeclaredRun) -> RunAudit:
    """One declared run, read from its own directory through the typed run store.

    The log's own SHA-256 is recorded beside its summary digest: the two answer different
    questions, and a reading that moves while the bytes do not is a different finding from a run
    that did not repeat.
    """
    manifest = store.read_manifest(declared.run_id)
    summary = store.read_summary(declared.run_id)
    events = store.read_events(declared.run_id)
    log_path = store.run_dir(declared.run_id) / "agent_events.parquet"
    summary_values = {**chain_summary(events), **band_chain_summary(events)}
    readings: dict[str, float] = {"event_rows": float(events.height)}
    for name in KEY_READINGS[1:]:
        if name not in summary_values:
            raise AuditError(f"{declared.run_id}: the log yields no reading {name!r}")
        readings[name] = float(summary_values[name])
    drawn = events.filter(pl.col("rng_draw").is_not_null())
    climate = events.filter(pl.col("event_type") == "CLIMATE_SHOCK")
    if climate.is_empty():
        raise AuditError(f"{declared.run_id}: the log holds no CLIMATE_SHOCK row")
    return RunAudit(
        run_id=declared.run_id,
        arm=declared.arm,
        root_seed=declared.root_seed,
        declared_digest=declared.simulation_digest,
        observed_digest=summary.simulation_digest,
        manifest_seed=manifest.root_seed,
        rng_draw_rows=drawn.height,
        rng_streams=tuple(sorted(str(name) for name in drawn["rng_stream"].unique().to_list())),
        climate_modes=tuple(sorted(str(mode) for mode in climate["outcome"].unique().to_list())),
        climate_rule_versions=tuple(
            sorted(str(version) for version in climate["rule_version"].unique().to_list())
        ),
        log_digest=hashlib.sha256(log_path.read_bytes()).hexdigest(),
        readings=readings,
    )


def audit_p05(root: str | Path, *, output_root: str | Path = P05_ROOT) -> P05Audit:
    """Every declared P05 arm, re-read from its run directory, in declaration order."""
    generator, declared = declared_p05_runs(root)
    store = RunStore(Path(root) / output_root)
    on_disk = set(store.list_runs())
    missing = tuple(entry.run_id for entry in declared if entry.run_id not in on_disk)

    by_arm: dict[str, list[DeclaredRun]] = {}
    order: list[str] = []
    for entry in declared:
        if entry.arm not in by_arm:
            by_arm[entry.arm] = []
            order.append(entry.arm)
        by_arm[entry.arm].append(entry)

    arms: list[ArmAudit] = []
    for arm in order:
        entries = by_arm[arm]
        runs = tuple(read_p05_run(store, entry) for entry in entries if entry.run_id in on_disk)
        arms.append(
            ArmAudit(
                arm=arm,
                declared_seeds=tuple(sorted(entry.root_seed for entry in entries)),
                runs=runs,
            )
        )
    declared_ids = {entry.run_id for entry in declared}
    return P05Audit(
        generator=generator,
        declared_arms=tuple(order),
        arms=tuple(arms),
        missing_run_ids=missing,
        undeclared_run_ids=tuple(sorted(on_disk - declared_ids)),
    )


@dataclass(frozen=True, slots=True)
class PosteriorAudit:
    """The frozen calibration posterior, with its own hashes recomputed from the tree."""

    converged: bool
    reason: str
    location_change: float
    prediction_change: float | None
    gates: dict[str, float]
    rung_sizes: tuple[int, ...]
    rung_predictions: tuple[float | None, ...]
    rung_posteriors: tuple[dict[str, float], ...]
    process_seeds: tuple[int, ...]
    sampler_seeds: tuple[int, ...]
    mode: str
    stored_hash: str
    recomputed_hash: str
    digests_agree: dict[str, bool]

    @property
    def hash_agrees(self) -> bool:
        return self.stored_hash == self.recomputed_hash

    def status(self) -> str:
        """The frozen verdict, in the artifact's own words rather than a summary of them."""
        return "non-converged" if not self.converged else "converged"


def audit_p06(root: str | Path) -> PosteriorAudit:
    """The frozen posterior, plus every digest it records recomputed from the current tree."""
    repository = Path(root)
    payload = _read_json(repository / P06_POSTERIOR)
    stop = payload["stop"]
    if not isinstance(stop, dict):
        raise AuditError(f"{P06_POSTERIOR} has no stop record")
    rungs = payload["rungs"]
    if not isinstance(rungs, list) or not rungs:
        raise AuditError(f"{P06_POSTERIOR} holds no rungs")
    body = {key: value for key, value in payload.items() if key != "posterior_hash"}
    cards: ParameterCards = load_cards(repository)
    recomputed = {
        "prior_digest": prior_digest(
            (name, "", low, high) for name, low, high in _prior_bounds(cards)
        ),
        "objective_digest": objective_digest(
            (check.pattern_id, check.check_id, str(check.kind.value), str(check.statistic))
            for check in _objective_checks(repository)
        ),
        "evidence_digest": evidence_digest(repository),
    }
    digests_agree = {key: str(payload.get(key)) == value for key, value in recomputed.items()}
    return PosteriorAudit(
        converged=bool(payload["converged"]),
        reason=str(stop["reason"]),
        location_change=float(stop["location_change"]),
        prediction_change=(
            None if stop.get("prediction_change") is None else float(stop["prediction_change"])
        ),
        gates={str(name): float(value) for name, value in dict(payload["gates"]).items()},
        rung_sizes=tuple(int(rung["particles"]) for rung in rungs),
        rung_predictions=tuple(
            None if rung.get("prediction") is None else float(rung["prediction"]) for rung in rungs
        ),
        rung_posteriors=tuple(
            {str(name): float(value) for name, value in dict(rung["posterior"]).items()}
            for rung in rungs
        ),
        process_seeds=tuple(int(seed) for seed in payload["process_seeds"]),
        sampler_seeds=tuple(int(seed) for seed in payload["sampler_seeds"]),
        mode=str(payload["mode"]),
        stored_hash=str(payload["posterior_hash"]),
        recomputed_hash=hash_text(canonical_json(body)),
        digests_agree=digests_agree,
    )


@dataclass(frozen=True, slots=True)
class LadderRung:
    """One rung of one sensitivity ladder, as the manifest records it."""

    ladder: str
    size: int
    runs: int
    stable: bool
    reason: str


@dataclass(frozen=True, slots=True)
class SensitivityAudit:
    """The P07 manifest and level table, and what the current writer declares that they lack."""

    rungs: tuple[LadderRung, ...]
    declared_sobol_ladder: tuple[int, ...]
    run_sobol_ladder: tuple[int, ...]
    sobol_parameters: tuple[str, ...]
    pawn_parameters: tuple[str, ...]
    stored_keys: tuple[str, ...]
    declared_keys: tuple[str, ...]
    missing_keys: tuple[str, ...]
    undeclared_keys: tuple[str, ...]
    stored_columns: tuple[str, ...]
    reader_columns: tuple[str, ...]
    missing_columns: tuple[str, ...]
    sobol_rows: tuple[tuple[int, int], ...]
    sobol_rows_expected: int
    pilot_seconds: float

    @property
    def unsettled_rungs(self) -> tuple[LadderRung, ...]:
        return tuple(rung for rung in self.rungs if not rung.stable)

    @property
    def index_rows_missing(self) -> bool:
        """Whether the stored table holds the S1 rows only, where the reader now emits S1 and ST."""
        return any(rows < self.sobol_rows_expected for _, rows in self.sobol_rows)


def _sobol_reader_columns(cards: ParameterCards) -> tuple[str, ...]:
    """The columns the current Sobol reader emits, read off a design that never touches the model.

    A level's indices are what the level table is made of, so whether the stored table predates a
    change to the reader is a question about this column set — and it can be answered by asking the
    reader directly on a design of two parameters rather than by re-running a ladder.
    """
    chosen = tuple(sweep_parameters(cards))[:2]
    design = sobol_design(chosen, base=1, second_order=False, seed=1)
    outputs = {"largest_band_share_end": [float(index) for index in range(design.height)]}
    indices = sobol_indices(chosen, outputs, base=1, second_order=False, seed=1)
    stacked = pl.concat(
        [
            indices["S1"].with_columns(pl.lit("S1").alias("index")),
            indices["ST"].with_columns(pl.lit("ST").alias("index")),
        ],
        how="diagonal_relaxed",
    ).with_columns(pl.lit("sobol").alias("ladder"), pl.lit(1, dtype=pl.Int64).alias("level"))
    return tuple(sorted(stacked.columns))


def audit_p07(root: str | Path) -> SensitivityAudit:
    """The P07 ladder, and the key and column differences between it and the current writer."""
    repository = Path(root)
    payload = _read_json(repository / P07_MANIFEST)
    levels = payload["levels"]
    if not isinstance(levels, list) or not levels:
        raise AuditError(f"{P07_MANIFEST} holds no levels")
    rungs = tuple(
        LadderRung(
            ladder=str(entry["ladder"]),
            size=int(entry["size"]),
            runs=int(entry["runs"]),
            stable=bool(entry["stable"]),
            reason=str(entry["reason"]),
        )
        for entry in levels
    )
    stored_keys = tuple(payload)
    declared_keys = (*DECLARED_MANIFEST_KEYS, "manifest_hash")
    table_path = repository / P07_LEVELS
    if not table_path.is_file():
        raise AuditError(f"{P07_LEVELS} does not exist")
    stored_columns = tuple(sorted(pl.read_parquet(table_path).columns))
    reader_columns = _sobol_reader_columns(load_cards(repository))
    table = pl.read_parquet(table_path).filter(pl.col("ladder") == "sobol")
    sobol_rows = tuple(
        (int(row["level"]), int(row["len"]))
        for row in table.group_by("level").len().sort("level").iter_rows(named=True)
    )
    return SensitivityAudit(
        rungs=rungs,
        declared_sobol_ladder=tuple(int(size) for size in payload["sobol_ladder"]),
        run_sobol_ladder=tuple(int(size) for size in payload["sobol_ladder_run"]),
        sobol_parameters=tuple(str(name) for name in payload["sobol_parameters"]),
        pawn_parameters=tuple(sorted({str(entry["parameter"]) for entry in payload["pawn"]})),
        stored_keys=stored_keys,
        declared_keys=declared_keys,
        missing_keys=tuple(key for key in declared_keys if key not in stored_keys),
        undeclared_keys=tuple(key for key in stored_keys if key not in declared_keys),
        stored_columns=stored_columns,
        reader_columns=reader_columns,
        missing_columns=tuple(column for column in reader_columns if column not in stored_columns),
        sobol_rows=sobol_rows,
        sobol_rows_expected=2 * len(tuple(str(name) for name in payload["sobol_parameters"])),
        pilot_seconds=float(payload.get("pilot_seconds", 0.0)),
    )


@dataclass(frozen=True, slots=True)
class RuntimeArmAudit:
    """The P08 runtime arms: what the model decided, and what it refused, recomputed from traces."""

    scenario: str
    seeds: tuple[int, ...]
    policies: tuple[str, ...]
    decision_traces: int
    decisions_from_model: int
    refusals: int
    declared_decisions_from_model: int
    declared_refusals: int

    @property
    def agrees_with_manifest(self) -> bool:
        return (
            self.decisions_from_model == self.declared_decisions_from_model
            and self.refusals == self.declared_refusals
        )


def audit_p08(root: str | Path) -> RuntimeArmAudit:
    """The runtime arms, with the model-decision and refusal counts read from the arm's own rows."""
    repository = Path(root)
    payload = _read_json(repository / P08_ARMS)
    traces = pl.read_parquet(repository / P08_TRACES)
    refusals = pl.read_parquet(repository / P08_REFUSALS)
    return RuntimeArmAudit(
        scenario=str(payload["scenario"]),
        seeds=tuple(int(seed) for seed in payload["seeds"]),
        policies=tuple(sorted({str(policy) for policy in payload["policies"]})),
        decision_traces=traces.height,
        decisions_from_model=traces.filter(pl.col("model_id").is_not_null()).height,
        refusals=refusals.height,
        declared_decisions_from_model=int(payload["decisions_from_model"]),
        declared_refusals=int(payload["refusals"]),
    )


__all__ = [
    "KEY_READINGS",
    "P05_ROOT",
    "P06_POSTERIOR",
    "P07_LEVELS",
    "P07_MANIFEST",
    "P08_ARMS",
    "P08_REFUSALS",
    "P08_TRACES",
    "READING_SIGNIFICANT_DIGITS",
    "REDUCTION_ORDER_FUNCTION",
    "REDUCTION_ORDER_MODULE",
    "VARIANTS_DOCUMENT",
    "ArmAudit",
    "AuditError",
    "DeclaredRun",
    "LadderRung",
    "P05Audit",
    "PosteriorAudit",
    "RunAudit",
    "RuntimeArmAudit",
    "SensitivityAudit",
    "audit_p05",
    "audit_p06",
    "audit_p07",
    "audit_p08",
    "compared",
    "declared_p05_runs",
    "read_p05_run",
]
