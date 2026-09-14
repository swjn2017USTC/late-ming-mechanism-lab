"""The experiment runner: arms and parameter designs, each run under common random numbers.

One entry point runs both kinds of P10 experiment, because they differ only in where the
configuration comes from. An **arm** run starts from a declared :class:`ArmConfiguration` — the
baseline or an ablation of it — and an **design** run starts from the same baseline with a
parameter draw applied. Everything else is shared: the same fixture, the same window, the same
kernel, the same outcome extraction, and the same seeding rule.

The seeding rule is the phase's methodological core:

```text
root_seed = base_seed + replicate
```

Every arm at replicate *r* draws its climate, market, household, migration, military and rebel
random numbers from the same root seed, so a difference between two arms at the same replicate is
attributable to the declared difference between them rather than to a fresh weather sequence. The
runner records the root seed per run, and the tests assert the pairing.

A *design* row (Morris, Sobol, or a grid cell) keeps replicate 0 unless the design says otherwise,
so every row of a sensitivity design is run under the same random numbers as every other row: the
variation across the design is the parameters and nothing else.

Artifacts are written per batch into ``outputs/experiments/<label>/``: one row per run with its
outcome scalars, the three trajectories behind them, and a manifest that names every arm, its
computed difference from the baseline and the code revision.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.analysis.outcomes import (
    BREAKDOWN_INDICATORS,
    BREAKDOWN_SAMPLE_EVERY,
    governance_timeline,
    outcome_frames,
    outcome_scalars,
)
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import SimulationKernel
from late_ming_lab.evidence.parameters import core_default_governance_indicators
from late_ming_lab.evidence.provenance import git_provenance
from late_ming_lab.experiments.counterfactual import (
    DEFAULT_CONFIDENCE,
    DEFAULT_RESAMPLES,
    STATISTICS_SEED,
)
from late_ming_lab.experiments.integrated import build_integrated_economy
from late_ming_lab.experiments.interventions import (
    BASELINE,
    ArmConfiguration,
    apply_parameter_draw,
    arm_configuration,
    baseline_configuration,
    configuration_diff,
    configuration_hash,
    declared_arms,
    note_for,
    question_for,
)
from late_ming_lab.storage.tables import write_table

EXPERIMENT_ROOT: Final[str] = "outputs/experiments"
RUNS_FILE: Final[str] = "runs.parquet"
TAX_BASE_FILE: Final[str] = "tax_base.parquet"
MIGRATION_FILE: Final[str] = "migration_nodes.parquet"
GOVERNANCE_FILE: Final[str] = "governance_timeline.parquet"
MANIFEST_FILE: Final[str] = "manifest.json"

#: The window every P10 run covers: the same 1625-1644 window the sandbox and the calibration ran.
RUN_TICK_COUNT: Final[int] = 240
RUN_WARMUP_TICKS: Final[int] = 24

#: How many replicates an arm gets by default. Four pairs every arm with every other on a common
#: random number, which is what makes the paired comparisons meaningful; the report prints the
#: interval on every paired difference and a Wilson interval on every share, so a reader can see
#: exactly what four runs buys rather than having to trust it.
DEFAULT_REPLICATES: Final[int] = 4

#: The columns a design frame carries beside its parameters: the row id SALib's samplers emit, and
#: the replicate a grid cell may specify. Neither is a parameter, and neither is applied as a draw.
DESIGN_COLUMNS: Final[tuple[str, ...]] = ("run", "replicate")


class RunnerError(ValueError):
    """Raised when a job cannot be turned into a run."""


@dataclass(frozen=True, slots=True)
class Job:
    """One run to make: the arm it starts from, the draw it applies, and its replicate."""

    label: str
    base_arm: str = BASELINE
    replicate: int = 0
    draw: tuple[tuple[str, float], ...] = ()

    def draw_map(self) -> dict[str, float]:
        return dict(self.draw)


@dataclass(frozen=True, slots=True)
class RunRecord:
    """What one run produced: its identity, its scalar outcomes and the trajectories behind them."""

    job: Job
    root_seed: int
    run_id: str
    simulation_digest: str
    outcomes: dict[str, float]
    tax_base: pl.DataFrame
    migration_nodes: pl.DataFrame
    governance: pl.DataFrame


@dataclass(frozen=True, slots=True)
class ExperimentBatch:
    """One batch of runs and the manifest that identifies it."""

    label: str
    runs: pl.DataFrame
    tax_base: pl.DataFrame
    migration_nodes: pl.DataFrame
    governance: pl.DataFrame
    manifest: dict[str, object]
    directory: Path = field(default_factory=Path)

    def write(self, directory: str | Path | None = None) -> tuple[Path, ...]:
        """Write the four tables and the manifest; returns the paths written."""
        target = Path(directory) if directory is not None else self.directory
        if not str(target):
            raise RunnerError("a batch needs a directory to write into")
        target.mkdir(parents=True, exist_ok=True)
        written = (
            write_table(target / RUNS_FILE, self.runs),
            write_table(target / TAX_BASE_FILE, self.tax_base),
            write_table(target / MIGRATION_FILE, self.migration_nodes),
            write_table(target / GOVERNANCE_FILE, self.governance),
        )
        manifest_path = target / MANIFEST_FILE
        manifest_path.write_text(
            json.dumps(self.manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        return (*written, manifest_path)


def run_job(
    job: Job,
    *,
    base_seed: int,
    parameter_sets: Mapping[str, str] | None = None,
    ticks: int = RUN_TICK_COUNT,
    warmup_ticks: int = RUN_WARMUP_TICKS,
) -> RunRecord:
    """Build the arm, apply the draw, run the window and read the outcomes out of the log."""
    config = arm_configuration(job.base_arm)
    if job.draw:
        if parameter_sets is None:
            raise RunnerError("a job with a parameter draw needs the name-to-set mapping")
        config = apply_parameter_draw(config, job.draw_map(), dict(parameter_sets))
    root_seed = base_seed + job.replicate
    run_config = SimulationConfig.model_validate(
        {
            "tick_count": ticks,
            "warmup_ticks": warmup_ticks,
            "root_seed": root_seed,
            "scenario_id": _scenario_id(job.label),
            "policy_id": "p10-experiment-v1",
        }
    )
    economy = build_integrated_economy(
        config.scenario,
        parameter_sets=arm_parameter_sets(config),
        disruption=config.disruption,
        extraction_policy=config.extraction_policy,
        capacity=config.capacity,
    )
    # The run id pattern is lower case; the declared arm label keeps its own spelling in artifacts.
    result = SimulationKernel(run_config, list(economy.systems)).run(
        run_label=_scenario_id(job.label)
    )
    thresholds = core_default_governance_indicators()
    starting_households = sum(cohort.households for cohort in economy.population)
    starting_adults = sum(cohort.adults for cohort in economy.population)
    trade_graph = economy.graphs.trade
    timeline = governance_timeline(
        result.events,
        thresholds=thresholds,
        population_adults=starting_adults,
        starting_households=starting_households,
    )
    scalars = outcome_scalars(
        result.events,
        thresholds=thresholds,
        population_adults=starting_adults,
        starting_households=starting_households,
        trade_graph=trade_graph,
        timeline=timeline,
    )
    frames = outcome_frames(result.events, trade_graph=trade_graph)
    governance = pl.DataFrame(
        {
            "tick": list(timeline.ticks),
            "crossed": list(timeline.crossed_counts),
        }
    )
    return RunRecord(
        job=job,
        root_seed=root_seed,
        run_id=result.manifest.run_id,
        simulation_digest=result.summary.simulation_digest,
        outcomes=scalars,
        tax_base=frames["tax_base"],
        migration_nodes=frames["migration_nodes"],
        governance=governance,
    )


def _scenario_id(label: str) -> str:
    """A run identifier the config accepts, derived from the arm label."""
    cleaned = "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in label.lower()
    )
    return cleaned[:64]


def arm_parameter_sets(config: ArmConfiguration) -> dict[str, object]:
    """An arm's eight parameter sets, keyed by the class name `build_integrated_economy` wants.

    Public because a caller outside the batch path — a protocol pilot, say — has to build the
    same economy the batch builds; a second copy of this mapping would be a second wiring.
    """
    return {
        "CropParameters": config.crop,
        "HouseholdParameters": config.household,
        "MarketParameters": config.market,
        "EliteParameters": config.elite,
        "FiscalParameters": config.fiscal,
        "MilitaryParameters": config.military,
        "BandParameters": config.band,
        "MigrationParameters": config.migration,
    }


def _run_task(payload: tuple[Job, int, Mapping[str, str] | None, int, int]) -> RunRecord:
    """One job of a batch, as a picklable unit so a batch can use more than one process."""
    job, base_seed, parameter_sets, ticks, warmup_ticks = payload
    return run_job(
        job,
        base_seed=base_seed,
        parameter_sets=parameter_sets,
        ticks=ticks,
        warmup_ticks=warmup_ticks,
    )


def run_jobs(
    jobs: Sequence[Job],
    *,
    base_seed: int,
    label: str,
    output_dir: str | Path,
    root: str | Path,
    parameter_sets: Mapping[str, str] | None = None,
    ticks: int = RUN_TICK_COUNT,
    warmup_ticks: int = RUN_WARMUP_TICKS,
    questions: Mapping[str, str] | None = None,
    design: Mapping[str, object] | None = None,
    progress: Callable[[int, Job], None] | None = None,
    workers: int = 1,
) -> ExperimentBatch:
    """Run every job, collect one row per run, and write the batch.

    Runs are independent and each is fully seeded, so a batch may spread them over `workers`
    processes: the arms still differ only in their declared configuration, and every replicate
    keeps the root seed its pairing depends on. `progress` fires as each run is dispatched (in
    order, one process) or completes (in parallel), so a long batch is legible while it runs.
    """
    if not jobs:
        raise RunnerError("a batch needs at least one job")
    records: list[RunRecord] = []
    if workers <= 1:
        for index, job in enumerate(jobs, start=1):
            if progress is not None:
                progress(index, job)
            records.append(_run_task((job, base_seed, parameter_sets, ticks, warmup_ticks)))
    else:
        payloads = [(job, base_seed, parameter_sets, ticks, warmup_ticks) for job in jobs]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_run_task, payload): payload[0] for payload in payloads}
            for index, future in enumerate(as_completed(futures), start=1):
                if progress is not None:
                    progress(index, futures[future])
                records.append(future.result())
        records.sort(key=lambda record: (record.job.label, record.job.replicate))
    runs = _runs_frame(records)
    tax_base = _tagged(records, "tax_base")
    migration = _tagged(records, "migration_nodes")
    governance = _tagged(records, "governance")
    directory = Path(output_dir) / label
    manifest = batch_manifest(
        label=label,
        jobs=jobs,
        records=records,
        base_seed=base_seed,
        root=root,
        ticks=ticks,
        warmup_ticks=warmup_ticks,
        questions=questions,
        design=design,
    )
    batch = ExperimentBatch(
        label=label,
        runs=runs,
        tax_base=tax_base,
        migration_nodes=migration,
        governance=governance,
        manifest=manifest,
        directory=directory,
    )
    batch.write(directory)
    return batch


def _runs_frame(records: Sequence[RunRecord]) -> pl.DataFrame:
    first = records[0]
    draw_names = sorted({name for record in records for name, _ in record.job.draw})
    scalar_names = sorted(first.outcomes)
    collisions = set(draw_names) & set(scalar_names)
    if collisions:
        raise RunnerError(f"a draw column collides with an outcome: {sorted(collisions)}")
    rows = [
        {
            "label": record.job.label,
            "base_arm": record.job.base_arm,
            "replicate": record.job.replicate,
            "root_seed": record.root_seed,
            "run_id": record.run_id,
            "simulation_digest": record.simulation_digest,
            **{name: record.job.draw_map().get(name, 0.0) for name in draw_names},
            **record.outcomes,
        }
        for record in records
    ]
    return pl.DataFrame(rows, infer_schema_length=None).select(
        [
            "label",
            "base_arm",
            "replicate",
            "root_seed",
            "run_id",
            "simulation_digest",
            *draw_names,
            *scalar_names,
        ]
    )


def _tagged(records: Sequence[RunRecord], attribute: str) -> pl.DataFrame:
    """Stack one per-run frame across the batch.

    `diagonal_relaxed` because an analysis frame's columns depend on which events a run produced —
    a run with no migration has fewer columns than one with migration — and the union with nulls is
    what makes the batch comparable.
    """
    frames = [
        getattr(record, attribute)
        .with_columns(
            pl.lit(record.job.label).alias("label"),
            pl.lit(record.job.replicate).alias("replicate"),
        )
        .select("label", "replicate", pl.all().exclude("label", "replicate"))
        for record in records
    ]
    return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()


def batch_manifest(
    *,
    label: str,
    jobs: Sequence[Job],
    records: Sequence[RunRecord],
    base_seed: int,
    root: str | Path,
    ticks: int,
    warmup_ticks: int,
    questions: Mapping[str, str] | None = None,
    design: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """The provenance of a batch: the arms, their computed diffs, the seeds and the revision."""
    provenance = git_provenance(root)
    baseline = baseline_configuration()
    arms: dict[str, dict[str, object]] = {}
    for arm in declared_arms():
        config = arm_configuration(arm)
        arms[arm] = {
            "question": (questions or {}).get(arm, question_for(arm)),
            "note": note_for(arm),
            "configuration_hash": configuration_hash(config),
            "differences_from_baseline": [
                {"field": name, "baseline": before, "arm": after}
                for name, before, after in configuration_diff(baseline, config)
            ],
        }
    return {
        "schema_version": "experiment-batch-v1",
        "label": label,
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": provenance.git_sha,
        "git_dirty": provenance.git_dirty,
        "base_seed": base_seed,
        "seed_rule": "root_seed = base_seed + replicate (common random numbers across arms)",
        "ticks": ticks,
        "warmup_ticks": warmup_ticks,
        "jobs": len(jobs),
        "design": dict(design) if design is not None else {"kind": "arms"},
        "replicates": sorted({job.replicate for job in jobs}),
        "labels": sorted({job.label for job in jobs}),
        "breakdown_indicators": BREAKDOWN_INDICATORS,
        "breakdown_sample_every": BREAKDOWN_SAMPLE_EVERY,
        "statistics": {
            "bootstrap_resamples": DEFAULT_RESAMPLES,
            "confidence": DEFAULT_CONFIDENCE,
            "seed": STATISTICS_SEED,
            "note": (
                "every paired interval, interaction interval and effect size in the reports is "
                "computed at these settings, so a report is reproducible from its artifact"
            ),
        },
        "run_count": len(records),
        "arms": arms,
    }


def ablation_jobs(*, replicates: int = DEFAULT_REPLICATES) -> tuple[Job, ...]:
    """The baseline, the nine ablations and the three joint arms, each at every replicate."""
    jobs: list[Job] = []
    for arm in declared_arms():
        for replicate in range(replicates):
            jobs.append(Job(label=arm, base_arm=arm, replicate=replicate))
    return tuple(jobs)


def design_jobs(
    design: pl.DataFrame, *, base_arm: str = BASELINE, label_prefix: str = "DESIGN"
) -> tuple[Job, ...]:
    """Turn a design matrix into jobs: one row is one run, at the row's own replicate if it has one.

    A design frame carries one column per swept parameter plus the columns named in
    :data:`DESIGN_COLUMNS`. The label of a job is the design row's index, so a design run can be
    traced back to its row.
    """
    if design.is_empty():
        raise RunnerError("an empty design has no rows to run")
    parameter_columns = [name for name in design.columns if name not in DESIGN_COLUMNS]
    if not parameter_columns:
        raise RunnerError("a design needs at least one parameter column")
    jobs: list[Job] = []
    for index, row in enumerate(design.iter_rows(named=True)):
        replicate = int(row.get("replicate", 0) or 0)
        jobs.append(
            Job(
                label=f"{label_prefix}-{index:05d}",
                base_arm=base_arm,
                replicate=replicate,
                draw=tuple((name, float(row[name])) for name in parameter_columns),
            )
        )
    return tuple(jobs)


def grid_jobs(
    parameters: Sequence[str],
    values: Mapping[str, Sequence[float]],
    *,
    replicates: int = 1,
    base_arm: str = BASELINE,
    label_prefix: str = "GRID",
) -> tuple[Job, ...]:
    """A full grid over two parameters, with replicates, as capped jobs.

    Only the two named parameters move; every other parameter stays at the baseline's value. The
    grid exists to show a tipping region as a surface rather than as a pair of one-dimensional
    curves, which is why it is a Cartesian product rather than a design of its own.
    """
    if len(parameters) != 2:
        raise RunnerError("a grid is over exactly two parameters")
    first, second = parameters
    jobs: list[Job] = []
    for first_value in values[first]:
        for second_value in values[second]:
            for replicate in range(replicates):
                jobs.append(
                    Job(
                        label=f"{label_prefix}-{first_value:g}-{second_value:g}",
                        base_arm=base_arm,
                        replicate=replicate,
                        draw=((first, float(first_value)), (second, float(second_value))),
                    )
                )
    return tuple(jobs)
