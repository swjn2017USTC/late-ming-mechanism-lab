"""The HPC batch layer: a plan of single-task units, one task per array index, and a merge.

```bash
uv run python -c "from late_ming_lab.experiments.batch import plan_batch; \\
    print(plan_batch('.', family='ablations', replicates=1).to_json())"
```

A batch is one *family* of the experiments the phases already declare, cut into the smallest units
that can run on their own: one arm of one replicate, one row of one design, one scenario. The plan
is a directory of small JSON files, every task is a directory of its own, and the merge is a
concatenation of the tasks that actually ran.

Five rules decide everything here.

1. **Independent seeds.** A task's seed is ``base_seed + index`` and nothing else, so a task can be
   re-run on its own and gets the same run back. The P10 and P12 phases pair arms on common random
   numbers by replicating one seed across arms; a batch instead gives every run its own seed,
   because a Slurm array index must be able to run without its neighbours. A batch is therefore a
   fresh realization of a family, not a reproduction of the phase artifact of the same name — the
   phase's seed rule is still recorded in each task's nested family manifest.
2. **Idempotent tasks.** A task is built in a temporary directory beside its target and renamed into
   place, with its ``manifest.json`` written last, so a task directory exists only when it is
   complete. A completed task is skipped unless ``force=True``.
3. **Failure isolation.** A task that raises records why in ``failed.json`` and returns
   ``status="failed"``; the rest of the array never hears about it. Re-running it after the cause is
   removed replaces the directory, so the failure record goes with it.
4. **A merge that does not lie.** ``merge_batch`` concatenates the tables of the *completed* tasks
   and records which indices were merged, which never ran and which failed. No row is ever imputed
   for a task that did not run.
5. **No network.** This module, and everything it imports at module level, never reaches a
   transport: the runtime model is not on the path of a batch, and the ``p12`` arm that could ask
   for it refuses while ``USTC_LLM_ENABLED=0``.

The layout, under ``outputs/batches/<batch_id>/``::

    plan.json          the plan, with a digest over its task list
    tasks.jsonl        one TaskSpec per line, in array-index order
    tasks/<index>/     one task: its manifest, and the tables its family wrote
    tasks/<index>/failed.json   present only for a task that raised
    runs.parquet       the merged table, after a merge
    merge.json         what was merged, what was missing, what failed

Which families reduce to a single task, and which do not, is a fact about the existing family steps
rather than a choice made here:

* ``ablations``, ``morris``, ``p12`` and ``integrated`` reduce — their units (an arm, a design row,
  a policy, a scenario) are enumerated without running anything, and one job of one unit is exactly
  what the family step already runs.
* ``sobol`` and ``tipping`` do not. Their designs are *derived*: the Sobol parameters are
  :func:`~late_ming_lab.experiments.ablation.select_parameters` over a completed Morris
  elementary-effects table, and the tipping axes are
  :func:`~late_ming_lab.experiments.ablation.strongest_pair` over the same table. No single task
  holds that table, so no plan can enumerate them without it. ``plan_batch`` refuses those two
  families and says which step is missing rather than inventing a design.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import polars as pl

from late_ming_lab.core.config import DEFAULT_ROOT_SEED, SimulationConfig
from late_ming_lab.core.hashing import canonical_json, hash_text
from late_ming_lab.evidence.cards import load_cards
from late_ming_lab.experiments.ablation import (
    ABLATION_LABEL,
    MORRIS_LABEL,
    MORRIS_LEVELS,
    MORRIS_TRAJECTORIES,
    parameter_field_names,
)
from late_ming_lab.experiments.integrated import (
    INTEGRATED_TICK_COUNT,
    INTEGRATED_WARMUP_TICKS,
    default_scenarios,
    run_integrated_scenario,
)
from late_ming_lab.experiments.interventions import (
    baseline_configuration,
    configuration_hash,
    declared_arms,
)
from late_ming_lab.experiments.runner import (
    MANIFEST_FILE,
    RUNS_FILE,
    ExperimentBatch,
    Job,
    ablation_jobs,
    design_jobs,
    run_jobs,
)
from late_ming_lab.experiments.sensitivity import morris_design, sweep_parameters
from late_ming_lab.storage.run_store import MACRO_FILE, RunStore
from late_ming_lab.storage.tables import read_json, read_table, write_json, write_table, write_text

#: Where a plan's directories live, below the repository root the plan was made from.
BATCH_ROOT: Final[str] = "outputs/batches"

PLAN_FILE: Final[str] = "plan.json"
TASKS_FILE: Final[str] = "tasks.jsonl"
TASKS_DIR: Final[str] = "tasks"
FAILED_FILE: Final[str] = "failed.json"
MERGE_FILE: Final[str] = "merge.json"

#: The families a plan may declare. Two of them cannot be cut into tasks at all — see the module
#: docstring — and are refused by :func:`plan_batch` with the step that would be needed.
FAMILIES: Final[tuple[str, ...]] = ("ablations", "morris", "sobol", "tipping", "p12", "integrated")

#: A batch id is a directory name and a Slurm job name, so it stays inside the same alphabet the run
#: store uses for a run id.
_BATCH_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class BatchError(RuntimeError):
    """Raised when a batch cannot be planned, run or merged as declared."""


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """One unit of work: what it runs, and the seed it runs it at."""

    index: int
    family: str
    label: str
    seed: int

    def to_json(self) -> str:
        return canonical_json(asdict(self))


@dataclass(frozen=True, slots=True)
class BatchPlan:
    """A planned batch: the tasks, the seeds they derive from, and the directory they live in."""

    batch_id: str
    root: Path
    directory: Path
    family: str
    replicates: int
    base_seed: int
    tasks: tuple[TaskSpec, ...]

    def task_dir(self, index: int) -> Path:
        return self.directory / TASKS_DIR / str(index)

    def to_json(self) -> str:
        return json.dumps(_plan_payload(self), indent=2, sort_keys=True, ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    """What running one task did: it ran, it was already done, or it failed."""

    index: int
    status: str
    directory: Path
    manifest_digest: str
    detail: str


@dataclass(frozen=True, slots=True)
class MergeReport:
    """What a merge merged, and what it refused to invent."""

    directory: Path
    merged: int
    missing: tuple[int, ...]
    failed: tuple[int, ...]
    tables: tuple[Path, ...]
    note: str


@dataclass(frozen=True, slots=True)
class _FamilyOutput:
    """What a family step left in a task directory: its provenance, and its per-run table."""

    manifest: dict[str, object]
    primary: str


def plan_batch(
    root: str | Path,
    *,
    family: str,
    replicates: int,
    base_seed: int = DEFAULT_ROOT_SEED,
    label: str | None = None,
) -> BatchPlan:
    """Plan one family as independent tasks, and write the plan.

    ``root`` is the repository root, as everywhere else in the project: the plan's own directories
    live under ``<root>/outputs/batches``. Every unit of the family is planned ``replicates`` times,
    and each of those tasks gets the next index and therefore its own seed.
    """
    if family not in FAMILIES:
        raise _unknown_family(family)
    if replicates < 0:
        raise BatchError(f"replicates must not be negative, got {replicates}")
    repository_root = Path(root).resolve()
    batch_id = label if label is not None else f"{family}-{base_seed}-r{replicates}"
    if not _BATCH_ID_PATTERN.match(batch_id):
        raise BatchError(
            f"invalid batch id {batch_id!r}: expected lowercase alphanumerics, '.', '_' or '-'"
        )
    units = _units(family, repository_root, base_seed)
    repeated = tuple(unit for unit in units for _ in range(replicates))
    tasks = tuple(
        TaskSpec(index=index, family=family, label=unit, seed=base_seed + index)
        for index, unit in enumerate(repeated)
    )
    root_dir = repository_root / BATCH_ROOT
    directory = root_dir / batch_id
    plan = BatchPlan(
        batch_id=batch_id,
        root=root_dir,
        directory=directory,
        family=family,
        replicates=replicates,
        base_seed=base_seed,
        tasks=tasks,
    )
    _write_plan(plan)
    return plan


def load_plan(directory: str | Path) -> BatchPlan:
    """Read a plan back, refusing a plan whose stored task list does not match its digest."""
    return _read_plan(Path(directory))[0]


def run_task(directory: str | Path, index: int, *, force: bool = False) -> TaskOutcome:
    """Run one task of a plan, idempotently and in isolation.

    A completed task is skipped and its recorded digest returned. ``force=True`` runs it again and
    replaces it. A task that raises is not propagated: its directory records ``failed.json`` and the
    outcome says so, so one bad index never stops an array.
    """
    plan, repository_root = _read_plan(Path(directory))
    if index < 0 or index >= len(plan.tasks):
        raise BatchError(
            f"task index {index} is outside the {plan.family} plan's "
            f"0..{len(plan.tasks) - 1} ({len(plan.tasks)} tasks)"
        )
    task = plan.tasks[index]
    target = plan.task_dir(index)
    if (target / MANIFEST_FILE).is_file() and not force:
        manifest: dict[str, Any] = read_json(target / MANIFEST_FILE)
        return TaskOutcome(
            index=index,
            status="skipped",
            directory=target,
            manifest_digest=_manifest_digest(manifest),
            detail="this task is already complete; its manifest digest is unchanged",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=target.parent, prefix=f".task-{index}-"))
    # A failure is recorded here, never propagated: one index cannot stop an array.
    try:
        output = _run_task_family(plan, task, staging, repository_root)
        tables = sorted(
            str(path.relative_to(staging)) for path in staging.rglob("*") if path.is_file()
        )
        manifest = _task_manifest(plan, task, output, tables)
        # Written last, so the task directory only ever appears complete.
        write_json(staging / MANIFEST_FILE, manifest)
    except Exception as error:
        _record_failure(staging, target, index, error)
        return TaskOutcome(
            index=index,
            status="failed",
            directory=target,
            manifest_digest="",
            detail=f"{type(error).__name__}: {error}",
        )
    _replace_dir(staging, target)
    return TaskOutcome(
        index=index,
        status="ran",
        directory=target,
        manifest_digest=_manifest_digest(manifest),
        detail=(
            f"ran with seed {task.seed}; {len(tables)} file(s), "
            f"primary table {output.primary or 'none'}"
        ),
    )


def merge_batch(directory: str | Path) -> MergeReport:
    """Concatenate the completed tasks' per-run tables, and say exactly what was left out.

    The merged table carries ``task_index`` and ``task_seed`` beside each task's own columns, so a
    row can be traced back to the task that produced it. A task that did not run contributes
    nothing: there is no row for it, and the report names it as missing rather than imputing one.
    """
    target = Path(directory)
    plan, _ = _read_plan(target)
    frames: list[pl.DataFrame] = []
    merged: list[int] = []
    empty: list[int] = []
    missing: list[int] = []
    failed: list[int] = []
    primaries: dict[str, str] = {}
    for task in plan.tasks:
        task_dir = plan.task_dir(task.index)
        if not (task_dir / MANIFEST_FILE).is_file():
            if (task_dir / FAILED_FILE).is_file():
                failed.append(task.index)
            else:
                missing.append(task.index)
            continue
        manifest: dict[str, Any] = read_json(task_dir / MANIFEST_FILE)
        primary = str(manifest.get("primary_table", ""))
        primaries[str(task.index)] = primary
        if not primary:
            # A task can run and honestly produce no per-run table — the p12 arm that refuses is
            # the case this exists for. It is merged as nothing, and named as nothing.
            empty.append(task.index)
            continue
        table = task_dir / primary
        if not table.is_file():
            raise BatchError(
                f"task {task.index} records primary table {primary!r} but {table} does not exist"
            )
        frames.append(
            read_table(table).with_columns(
                pl.lit(task.index, dtype=pl.Int64).alias("task_index"),
                pl.lit(task.seed, dtype=pl.Int64).alias("task_seed"),
            )
        )
        merged.append(task.index)
    tables: tuple[Path, ...] = ()
    if frames:
        tables = (write_table(target / RUNS_FILE, pl.concat(frames, how="diagonal_relaxed")),)
    report = MergeReport(
        directory=target,
        merged=len(merged),
        missing=tuple(missing),
        failed=tuple(failed),
        tables=tables,
        note=_merge_note(plan, merged, missing, failed, empty),
    )
    write_json(
        target / MERGE_FILE,
        {
            "schema_version": "batch-merge-v1",
            "batch_id": plan.batch_id,
            "family": plan.family,
            "base_seed": plan.base_seed,
            "tasks": len(plan.tasks),
            "merged": merged,
            "empty": empty,
            "missing": missing,
            "failed": failed,
            "primary_tables": primaries,
            "merged_table": RUNS_FILE if frames else None,
            "note": report.note,
        },
    )
    return report


def _units(family: str, repository_root: Path, base_seed: int) -> tuple[str, ...]:
    """The distinct things a family runs, in the family's own declaration order."""
    if family == "ablations":
        return declared_arms()
    if family == "morris":
        return tuple(job.label for job in _morris_setup(repository_root, base_seed)[0])
    if family == "p12":
        from late_ming_lab.experiments.policy_robustness import POLICY_ARMS

        return POLICY_ARMS
    if family == "integrated":
        return tuple(scenario.label for scenario in default_scenarios())
    if family in {"sobol", "tipping"}:
        raise _unreducible(family)
    raise _unknown_family(family)


def _unknown_family(family: str) -> BatchError:
    return BatchError(f"unknown family {family!r}; known families: {', '.join(FAMILIES)}")


def _unreducible(family: str) -> BatchError:
    """The two families whose design is derived from a Morris table no single task holds."""
    if family == "sobol":
        return BatchError(
            "the sobol family cannot be planned as single tasks: `run_sobol` takes its parameters "
            "from `select_parameters` over a completed Morris elementary-effects table, and no "
            "single task holds that table. A step deriving the selection from a completed Morris "
            "batch is what would be needed before this family can be cut into tasks"
        )
    return BatchError(
        "the tipping family cannot be planned as single tasks: `run_tipping_grid` takes its two "
        "axes from `strongest_pair` over a completed Morris elementary-effects table, and no "
        "single task holds that table. A step deriving the axes from a completed Morris batch is "
        "what would be needed before this family can be cut into tasks"
    )


def _morris_setup(repository_root: Path, base_seed: int) -> tuple[tuple[Job, ...], dict[str, str]]:
    """The Morris design of the P10 phase as jobs, and the arm field each swept parameter lives in.

    The design is drawn from the plan's ``base_seed``, not from a task's seed, so every task of the
    family is a row of *one* design. A task's own seed moves only the run, never the design.
    """
    sweep = sweep_parameters(load_cards(repository_root))
    design = morris_design(
        sweep, trajectories=MORRIS_TRAJECTORIES, levels=MORRIS_LEVELS, seed=base_seed
    )
    return design_jobs(design, label_prefix="MORRIS"), parameter_field_names(sweep)


def _job_named(jobs: tuple[Job, ...], task: TaskSpec) -> Job:
    for job in jobs:
        if job.label == task.label:
            if job.replicate != 0:
                raise BatchError(
                    f"the {task.family} job {task.label!r} carries replicate {job.replicate}; a "
                    "task must run at replicate 0 so that its root seed is its own seed"
                )
            return job
    raise BatchError(f"the {task.family} family declares no unit labelled {task.label!r}")


def _run_task_family(
    plan: BatchPlan, task: TaskSpec, directory: Path, repository_root: Path
) -> _FamilyOutput:
    """The dispatch: one small branch per family, and nothing else."""
    if task.family == "ablations":
        return _run_ablation_task(plan, task, directory, repository_root)
    if task.family == "morris":
        return _run_morris_task(plan, task, directory, repository_root)
    if task.family == "p12":
        return _run_p12_task(plan, task, directory, repository_root)
    if task.family == "integrated":
        return _run_integrated_task(plan, task, directory, repository_root)
    raise _unreducible(task.family)


def _run_ablation_task(
    plan: BatchPlan, task: TaskSpec, directory: Path, repository_root: Path
) -> _FamilyOutput:
    """One arm at one replicate, through the family's own job list."""
    job = _job_named(ablation_jobs(replicates=1), task)
    batch = _run_family_batch(
        (job,),
        label=ABLATION_LABEL,
        task=task,
        directory=directory,
        repository_root=repository_root,
        design={"kind": "ablation", "replicates": 1, "arm": task.label},
    )
    return _FamilyOutput(manifest=batch.manifest, primary=RUNS_FILE)


def _run_morris_task(
    plan: BatchPlan, task: TaskSpec, directory: Path, repository_root: Path
) -> _FamilyOutput:
    """One row of the Morris design, at this task's seed."""
    jobs, parameter_sets = _morris_setup(repository_root, plan.base_seed)
    job = _job_named(jobs, task)
    batch = _run_family_batch(
        (job,),
        label=MORRIS_LABEL,
        task=task,
        directory=directory,
        repository_root=repository_root,
        parameter_sets=parameter_sets,
        design={
            "kind": "morris",
            "trajectories": MORRIS_TRAJECTORIES,
            "levels": MORRIS_LEVELS,
            "design_seed": plan.base_seed,
            "row": task.label,
        },
    )
    return _FamilyOutput(manifest=batch.manifest, primary=RUNS_FILE)


def _run_p12_task(
    plan: BatchPlan, task: TaskSpec, directory: Path, repository_root: Path
) -> _FamilyOutput:
    """One policy arm at one replicate.

    The import is here rather than at module level on purpose: the arm runner reaches the runtime
    policy's transport, and this module's import graph has to stay free of one. Nothing here calls a
    model — with ``USTC_LLM_ENABLED=0`` the ``ustc`` arm refuses, and the refusal is the result the
    task records.
    """
    from late_ming_lab.experiments.policy_robustness import (
        TICK_COUNT,
        WARMUP_TICKS,
        run_policy_arm,
    )

    arm = run_policy_arm(task.label, replicates=1, base_seed=task.seed)
    written: list[str] = []
    for name, frame in (
        ("mechanism_readings", arm.readings),
        ("levels", arm.levels),
        ("decisions", arm.traces),
    ):
        if not frame.is_empty():
            write_table(directory / f"{name}.parquet", frame)
            written.append(f"{name}.parquet")
    return _FamilyOutput(
        manifest={
            "schema_version": "batch-policy-arm-v1",
            "policy": arm.policy,
            "status": arm.status,
            "reason": arm.reason,
            "replicates": 1,
            "base_seed": task.seed,
            "ticks": TICK_COUNT,
            "warmup_ticks": WARMUP_TICKS,
            "arm_configuration_hash": configuration_hash(baseline_configuration()),
            "tables": written,
            "note": (
                "an arm that refused is a result about this phase's configuration, not a missing "
                "measurement, and it merges as no rows rather than as an imputed one"
            ),
        },
        primary="levels.parquet" if not arm.levels.is_empty() else "",
    )


def _run_integrated_task(
    plan: BatchPlan, task: TaskSpec, directory: Path, repository_root: Path
) -> _FamilyOutput:
    """One declared scenario at one replicate, persisted through the run store."""
    scenarios = {scenario.label: scenario for scenario in default_scenarios()}
    scenario = scenarios.get(task.label)
    if scenario is None:
        raise BatchError(f"the integrated family declares no scenario labelled {task.label!r}")
    config = SimulationConfig.model_validate(
        {
            "tick_count": INTEGRATED_TICK_COUNT,
            "warmup_ticks": INTEGRATED_WARMUP_TICKS,
            "root_seed": task.seed,
            "scenario_id": f"{scenario.dataset}-fixture",
            "policy_id": "integrated-v1",
        }
    )
    run = run_integrated_scenario(scenario, config=config)
    run_directory = RunStore(directory).write(run.result)
    # The run store's own layout is the family's here, so the per-run table is read back through it
    # rather than flattened into a second one.
    primary = f"{run_directory.name}/{MACRO_FILE}"
    return _FamilyOutput(
        manifest={
            "schema_version": "batch-integrated-run-v1",
            "scenario": asdict(scenario),
            "run_id": run.result.manifest.run_id,
            "run_directory": run_directory.name,
            "simulation_digest": run.result.summary.simulation_digest,
            "manifest_digest": run.result.manifest.deterministic_digest(),
            "ticks": INTEGRATED_TICK_COUNT,
            "warmup_ticks": INTEGRATED_WARMUP_TICKS,
            "base_seed": task.seed,
            "primary_table": primary,
        },
        primary=primary,
    )


def _run_family_batch(
    jobs: tuple[Job, ...],
    *,
    label: str,
    task: TaskSpec,
    directory: Path,
    repository_root: Path,
    parameter_sets: dict[str, str] | None = None,
    design: dict[str, object] | None = None,
) -> ExperimentBatch:
    """Run one job through ``run_jobs`` and move the family's files into the task directory.

    ``run_jobs`` writes a batch under ``<output_dir>/<label>``; the task owns the plan's layout, so
    the files it wrote are moved up one level and the label directory removed. The frames travel in
    memory, so moving the files afterwards changes nothing about what was measured.
    """
    holder = directory / "_family"
    batch = run_jobs(
        jobs,
        base_seed=task.seed,
        label=label,
        output_dir=holder,
        root=repository_root,
        parameter_sets=parameter_sets,
        design=design,
    )
    produced = holder / label
    for path in sorted(produced.iterdir()):
        path.rename(directory / path.name)
    produced.rmdir()
    holder.rmdir()
    return batch


def _task_manifest(
    plan: BatchPlan, task: TaskSpec, output: _FamilyOutput, tables: list[str]
) -> dict[str, object]:
    """The task's own provenance: what it ran, at which seed, and what the family said about it."""
    return {
        "schema_version": "batch-task-v1",
        "batch_id": plan.batch_id,
        "index": task.index,
        "family": task.family,
        "label": task.label,
        "seed": task.seed,
        "seed_rule": "task.seed = plan.base_seed + task.index, and it is this run's root seed",
        "plan_task_digest": _task_digest(plan.tasks),
        "primary_table": output.primary,
        "tables": tables,
        "family_manifest": output.manifest,
    }


def _record_failure(staging: Path, target: Path, index: int, error: Exception) -> None:
    """Replace the task with the one thing a failed task has to say: what went wrong."""
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    write_json(
        staging / FAILED_FILE,
        {"index": index, "error_type": type(error).__name__, "message": str(error)},
    )
    _replace_dir(staging, target)


def _replace_dir(staging: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)


def _manifest_digest(manifest: dict[str, Any]) -> str:
    return hash_text(canonical_json(manifest))


def _task_digest(tasks: tuple[TaskSpec, ...]) -> str:
    """A digest over the task list: a plan whose tasks changed is not the plan that was recorded."""
    return hash_text(canonical_json([asdict(task) for task in tasks]))


def _plan_payload(plan: BatchPlan) -> dict[str, object]:
    return {
        "schema_version": "batch-plan-v1",
        "batch_id": plan.batch_id,
        "repository_root": str(plan.root.parent.parent),
        "root": str(plan.root),
        "directory": str(plan.directory),
        "family": plan.family,
        "replicates": plan.replicates,
        "base_seed": plan.base_seed,
        "seed_rule": "task.seed = base_seed + index",
        "tasks": [asdict(task) for task in plan.tasks],
        "task_digest": _task_digest(plan.tasks),
    }


def _write_plan(plan: BatchPlan) -> None:
    """Write ``plan.json`` and ``tasks.jsonl``, and refuse to replan a batch into something else.

    Both files are a pure function of the plan: no timestamp, no ambient state. Replanning the same
    family with the same seed and replicate count rewrites the same bytes, and replanning it into a
    *different* task list is refused rather than silently re-pointing a batch that may be running.
    """
    destination = plan.directory / PLAN_FILE
    text = f"{plan.to_json()}\n"
    if destination.is_file() and destination.read_text(encoding="utf-8") != text:
        raise BatchError(
            f"{plan.directory} already holds a different plan; a batch is planned once, so plan it "
            "under another label or remove the directory"
        )
    write_json(destination, _plan_payload(plan))
    write_text(plan.directory / TASKS_FILE, "".join(f"{task.to_json()}\n" for task in plan.tasks))


def _read_plan(directory: Path) -> tuple[BatchPlan, Path]:
    """Read a plan and the repository root it was made from, checking the task list's digest."""
    payload: dict[str, Any] = read_json(directory / PLAN_FILE)
    if Path(payload["directory"]).resolve() != directory.resolve():
        raise BatchError(
            f"{directory} holds a plan made for {payload['directory']}: a plan names the directory "
            "its tasks belong to, so a copied plan would write its tasks somewhere else. Plan the "
            "batch under the root it will run from"
        )
    tasks = tuple(TaskSpec(**entry) for entry in payload["tasks"])
    if _task_digest(tasks) != payload["task_digest"]:
        raise BatchError(
            f"{directory / PLAN_FILE} does not match its own task digest; the plan was edited "
            "after it was written"
        )
    plan = BatchPlan(
        batch_id=str(payload["batch_id"]),
        root=Path(payload["root"]),
        directory=Path(payload["directory"]),
        family=str(payload["family"]),
        replicates=int(payload["replicates"]),
        base_seed=int(payload["base_seed"]),
        tasks=tasks,
    )
    return plan, Path(payload["repository_root"])


def _merge_note(
    plan: BatchPlan,
    merged: list[int],
    missing: list[int],
    failed: list[int],
    empty: list[int],
) -> str:
    parts = [
        f"merged {len(merged)} of {len(plan.tasks)} {plan.family} tasks ({plan.batch_id}) into "
        f"{RUNS_FILE} with task_index and task_seed"
    ]
    if missing:
        parts.append(
            f"indices {_indices(missing)} did not run: no row was imputed for them and their "
            f"directories are absent"
        )
    if failed:
        parts.append(
            f"indices {_indices(failed)} failed at run time and are recorded in {FAILED_FILE}"
        )
    if empty:
        parts.append(
            f"indices {_indices(empty)} ran and produced no per-run table, so they merged as "
            f"nothing: their task manifests say why"
        )
    if not merged:
        parts.append(f"no task contributed a table, so no {RUNS_FILE} was written")
    return "; ".join(parts)


def _indices(indices: list[int]) -> str:
    return ", ".join(str(index) for index in indices)
