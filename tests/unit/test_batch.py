"""The batch layer's observable contract: seeds, idempotence, isolation, and a merge that adds up.

Nothing here runs a simulation. The families are exercised through the pinned dispatch seam with a
stubbed runner that writes one row per task, so what is under test is the batch layer itself —
planning, seeding, task directories, failure records and the merge — and not the model.

The family enumeration is tested against the families' own declarations (the arms, the policy
list, the scenarios), so a plan that drifted from what a family actually runs would fail here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from late_ming_lab.experiments import batch
from late_ming_lab.experiments.batch import (
    MERGE_FILE,
    PLAN_FILE,
    TASKS_FILE,
    BatchError,
    BatchPlan,
    TaskSpec,
    _FamilyOutput,
    load_plan,
    merge_batch,
    plan_batch,
    run_task,
)
from late_ming_lab.experiments.integrated import default_scenarios
from late_ming_lab.experiments.interventions import declared_arms
from late_ming_lab.experiments.policy_robustness import POLICY_ARMS
from late_ming_lab.experiments.runner import RUNS_FILE
from late_ming_lab.hpc.slurm_array import render_slurm_script
from late_ming_lab.storage.tables import write_table

REPO_ROOT = Path(__file__).resolve().parents[2]

#: What the batch layer's dispatch looks like, so the stub below can stand in for a family.
Runner = Callable[[BatchPlan, TaskSpec, Path, Path], _FamilyOutput]


class _StubRunner:
    """One row per task, and a switch that makes it fail instead."""

    def __init__(self, *, fails: bool = False, rows: bool = True) -> None:
        self.fails = fails
        self.rows = rows
        self.calls: list[int] = []

    def __call__(
        self, plan: BatchPlan, task: TaskSpec, directory: Path, repository_root: Path
    ) -> _FamilyOutput:
        self.calls.append(task.index)
        if self.fails:
            raise RuntimeError("the stubbed runner broke")
        if not self.rows:
            # The shape of a task that ran and honestly has nothing to merge, e.g. a policy arm
            # that refused.
            return _FamilyOutput(manifest={"status": "refused"}, primary="")
        write_table(
            directory / RUNS_FILE,
            pl.DataFrame({"label": [task.label], "root_seed": [task.seed]}),
        )
        return _FamilyOutput(manifest={"label": task.label, "seed": task.seed}, primary=RUNS_FILE)


@pytest.fixture
def batch_root(tmp_path: Path) -> Path:
    """A root the morris family can plan from: it reads the parameter cards under it."""
    (tmp_path / "data").mkdir()
    shutil.copytree(REPO_ROOT / "data/parameters", tmp_path / "data" / "parameters")
    return tmp_path


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> _StubRunner:
    runner = _StubRunner()
    monkeypatch.setattr(batch, "_run_task_family", runner)
    return runner


def _completed(plan: BatchPlan, indices: tuple[int, ...], runner: _StubRunner) -> None:
    for index in indices:
        outcome = run_task(plan.directory, index)
        assert outcome.status == "ran"


def test_a_plan_gives_every_task_its_own_seed_and_round_trips(batch_root: Path) -> None:
    plan = plan_batch(batch_root, family="ablations", replicates=2, base_seed=1000)

    assert [task.index for task in plan.tasks] == list(range(len(plan.tasks)))
    assert all(task.seed == 1000 + task.index for task in plan.tasks)
    assert [task.label for task in plan.tasks][:3] == [
        declared_arms()[0],
        declared_arms()[0],
        declared_arms()[1],
    ]
    assert len(plan.tasks) == 2 * len(declared_arms())

    lines = (plan.directory / TASKS_FILE).read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [
        json.loads(task.to_json()) for task in plan.tasks
    ]
    stored = load_plan(plan.directory)
    assert stored == plan
    assert stored.tasks == tuple(TaskSpec(**json.loads(line)) for line in lines)
    assert stored.to_json() == plan.to_json()
    assert json.loads((plan.directory / PLAN_FILE).read_text(encoding="utf-8"))["task_digest"]
    assert plan.task_dir(2) == plan.directory / "tasks" / "2"


def test_every_reducible_family_plans_its_own_units(batch_root: Path) -> None:
    ablations = plan_batch(batch_root, family="ablations", replicates=1)
    assert [task.label for task in ablations.tasks] == list(declared_arms())

    p12 = plan_batch(batch_root, family="p12", replicates=1)
    assert [task.label for task in p12.tasks] == list(POLICY_ARMS)

    integrated = plan_batch(batch_root, family="integrated", replicates=1)
    assert [task.label for task in integrated.tasks] == [
        scenario.label for scenario in default_scenarios()
    ]

    morris = plan_batch(batch_root, family="morris", replicates=1)
    assert morris.tasks[0].label == "MORRIS-00000"
    assert len({task.label for task in morris.tasks}) == len(morris.tasks)


def test_sobol_and_tipping_are_refused_with_the_step_that_is_missing(batch_root: Path) -> None:
    for family, needed in (("sobol", "select_parameters"), ("tipping", "strongest_pair")):
        with pytest.raises(BatchError) as error:
            plan_batch(batch_root, family=family, replicates=1)
        assert needed in str(error.value)


def test_plan_batch_refuses_an_unknown_family_and_a_negative_replicate_count(
    batch_root: Path,
) -> None:
    with pytest.raises(BatchError, match="unknown family"):
        plan_batch(batch_root, family="regression", replicates=1)
    with pytest.raises(BatchError, match="must not be negative"):
        plan_batch(batch_root, family="ablations", replicates=-1)


def test_a_plan_is_not_repointed_at_a_different_task_list(batch_root: Path) -> None:
    plan_batch(batch_root, family="ablations", replicates=1, label="replanned")
    again = plan_batch(batch_root, family="ablations", replicates=1, label="replanned")
    assert again.tasks  # replanning the same batch is idempotent

    with pytest.raises(BatchError, match="already holds a different plan"):
        plan_batch(batch_root, family="ablations", replicates=2, label="replanned")


def test_run_task_refuses_an_index_the_plan_does_not_hold(batch_root: Path) -> None:
    plan = plan_batch(batch_root, family="integrated", replicates=1)
    for index in (-1, len(plan.tasks)):
        with pytest.raises(BatchError, match="outside"):
            run_task(plan.directory, index)


def test_a_plan_is_not_relocatable(batch_root: Path) -> None:
    """A task directory is where the plan says it is; a copied plan must not write elsewhere."""
    plan = plan_batch(batch_root, family="integrated", replicates=1)
    copied = batch_root / "copied"
    shutil.copytree(plan.directory, copied)

    with pytest.raises(BatchError, match="holds a plan made for"):
        load_plan(copied)
    with pytest.raises(BatchError, match="holds a plan made for"):
        run_task(copied, 0)


def test_a_completed_task_is_skipped_until_it_is_forced(
    batch_root: Path, stub: _StubRunner
) -> None:
    plan = plan_batch(batch_root, family="ablations", replicates=1)

    first = run_task(plan.directory, 3)
    assert first.status == "ran"
    assert (first.directory / "manifest.json").is_file()
    assert json.loads((first.directory / "manifest.json").read_text())["seed"] == (
        plan.base_seed + 3
    )

    second = run_task(plan.directory, 3)
    assert second.status == "skipped"
    assert second.manifest_digest == first.manifest_digest
    assert stub.calls == [3]

    forced = run_task(plan.directory, 3, force=True)
    assert forced.status == "ran"
    assert stub.calls == [3, 3]
    assert run_task(plan.directory, 3).manifest_digest == forced.manifest_digest


def test_a_failed_task_is_recorded_isolated_and_recoverable(
    batch_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = plan_batch(batch_root, family="ablations", replicates=1)
    runner = _StubRunner(fails=True)
    monkeypatch.setattr(batch, "_run_task_family", runner)

    failed = run_task(plan.directory, 0)
    assert failed.status == "failed"
    assert failed.manifest_digest == ""
    record = json.loads((failed.directory / "failed.json").read_text(encoding="utf-8"))
    assert record == {
        "index": 0,
        "error_type": "RuntimeError",
        "message": "the stubbed runner broke",
    }
    assert not (failed.directory / "manifest.json").exists()

    runner.fails = False
    neighbour = run_task(plan.directory, 1)
    assert neighbour.status == "ran"
    untouched = plan.task_dir(2)
    assert not untouched.exists()

    report = merge_batch(plan.directory)
    assert report.merged == 1
    assert report.failed == (0,)
    assert report.missing == tuple(range(2, len(plan.tasks)))

    recovered = run_task(plan.directory, 0)
    assert recovered.status == "ran"
    assert not (recovered.directory / "failed.json").exists()
    assert merge_batch(plan.directory).failed == ()


def test_merge_concatenates_only_the_completed_tasks(batch_root: Path, stub: _StubRunner) -> None:
    plan = plan_batch(batch_root, family="ablations", replicates=1)
    _completed(plan, (0, 1), stub)

    report = merge_batch(plan.directory)
    assert report.merged == 2
    assert report.missing == tuple(range(2, len(plan.tasks)))
    assert report.failed == ()
    assert report.tables == (plan.directory / RUNS_FILE,)

    merged = pl.read_parquet(plan.directory / RUNS_FILE)
    assert merged["task_index"].to_list() == [0, 1]
    assert merged["task_seed"].to_list() == [plan.base_seed, plan.base_seed + 1]
    assert merged["root_seed"].to_list() == [plan.base_seed, plan.base_seed + 1]
    assert merged.height == 2  # no row for the eleven tasks that did not run

    recorded = json.loads((plan.directory / MERGE_FILE).read_text(encoding="utf-8"))
    assert recorded["merged"] == [0, 1]
    assert recorded["missing"] == list(range(2, len(plan.tasks)))
    assert recorded["failed"] == []

    before = (plan.directory / RUNS_FILE).read_bytes(), (plan.directory / MERGE_FILE).read_bytes()
    merge_batch(plan.directory)
    after = (plan.directory / RUNS_FILE).read_bytes(), (plan.directory / MERGE_FILE).read_bytes()
    assert before == after


def test_merge_records_a_task_that_ran_without_a_table(
    batch_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = plan_batch(batch_root, family="p12", replicates=1)
    runner = _StubRunner(rows=False)
    monkeypatch.setattr(batch, "_run_task_family", runner)

    assert run_task(plan.directory, 0).status == "ran"
    monkeypatch.setattr(batch, "_run_task_family", _StubRunner())
    assert run_task(plan.directory, 1).status == "ran"

    report = merge_batch(plan.directory)
    assert report.merged == 1
    assert report.failed == ()
    recorded = json.loads((plan.directory / MERGE_FILE).read_text(encoding="utf-8"))
    assert recorded["empty"] == [0]
    assert recorded["primary_tables"] == {"0": "", "1": "runs.parquet"}
    assert pl.read_parquet(plan.directory / RUNS_FILE)["task_index"].to_list() == [1]


def test_the_batch_import_graph_holds_no_transport() -> None:
    probe = (
        "import sys, late_ming_lab.experiments.batch;"
        "print(sorted(m for m in sys.modules"
        " if m.split('.')[0] in {'httpx', 'openai'} or 'ustc' in m))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "[]"


def test_render_slurm_script_declares_the_array_and_the_per_task_walltime(
    batch_root: Path,
) -> None:
    plan = plan_batch(batch_root, family="ablations", replicates=1, label="slurm-smoke")
    script = render_slurm_script(
        plan,
        partition="compute",
        walltime="04:00:00",
        cpus=4,
        concurrency=3,
        seconds_per_task=600.0,
    )

    assert "#SBATCH --array=0-12%3" in script
    assert "#SBATCH --time=00:15:00" in script  # 600s x 1.5, inside the declared ceiling
    assert "#SBATCH --cpus-per-task=4" in script
    assert "#SBATCH --partition=compute" in script
    assert "#SBATCH --export=NONE" in script
    assert f"#SBATCH --job-name=lm-{plan.batch_id}" in script
    assert f"--output={plan.directory}/logs/{plan.batch_id}-%A_%a.log" in script
    assert "export UV_OFFLINE=1" in script
    assert "export USTC_LLM_ENABLED=0" in script
    assert f'--plan "{plan.directory}"' in script
    assert '--task-index "${SLURM_ARRAY_TASK_ID:' in script
    assert "{{" not in script

    syntax = subprocess.run(
        ["bash", "-n"], input=script, capture_output=True, text=True, check=False
    )
    assert syntax.returncode == 0, syntax.stderr


def test_render_slurm_script_refuses_a_budget_the_plan_cannot_meet(batch_root: Path) -> None:
    plan = plan_batch(batch_root, family="ablations", replicates=1, label="slurm-refusal")
    with pytest.raises(BatchError, match=r"at least 1\.0"):
        render_slurm_script(
            plan,
            partition="compute",
            walltime="04:00:00",
            cpus=4,
            concurrency=2,
            seconds_per_task=600.0,
            safety=0.5,
        )
    with pytest.raises(BatchError, match="declared walltime"):
        render_slurm_script(
            plan,
            partition="compute",
            walltime="00:10:00",
            cpus=4,
            concurrency=2,
            seconds_per_task=600.0,
        )


def test_the_rendered_time_limit_never_falls_below_a_minute(batch_root: Path) -> None:
    """An estimate under a minute is rounded up: schedulers reject a sub-minute limit outright."""
    plan = plan_batch(batch_root, family="ablations", replicates=1, label="slurm-floor")
    script = render_slurm_script(
        plan,
        partition="normal",
        walltime="04:00:00",
        cpus=1,
        concurrency=1,
        seconds_per_task=2.0,
    )
    assert "#SBATCH --time=00:01:00" in script
