"""Command-line interface for the Late Ming Mechanism Lab.

The commands are the surfaces P14 ships, in the order a reader meets them:

```text
run         one run: the configured kernel window, or a declared scenario
replay      the decision layer driven by recorded fixtures, with no network
experiment  one declared experiment family, from the ablations to the policy arms
calibrate   one SMC batch, and optionally the posterior predictive pass
analyze     read what a run or a batch produced and report its headline numbers
doctor      the environment: python, the lock, the artifacts, and the secret rules
bench       measure the model against the declared development thresholds
batch       plan a task list, run one array task, merge the finished tasks
ui          serve the artifact browser
```

Every command fails closed: an unknown family, a missing artifact, a fixture that was never recorded
or a threshold that was missed is an error with a non-zero exit, not a warning.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Final

import typer

from late_ming_lab import __version__
from late_ming_lab.core.config import DEFAULT_ROOT_SEED, SimulationConfig
from late_ming_lab.core.kernel import SimulationKernel
from late_ming_lab.storage.run_store import RunConflictError, RunStore

app = typer.Typer(
    name="late-ming-lab",
    help="Late Ming Mechanism Lab: historical mechanism simulation for 1625-1644 Shaanxi-Henan.",
    no_args_is_help=True,
    add_completion=False,
)

#: Where a batch writes unless a caller says otherwise, and where the demo scenario is declared.
OUTPUT_ROOT: Final[str] = "outputs/runs"
EXPERIMENT_ROOT: Final[str] = "outputs/experiments"
CALIBRATION_ROOT: Final[str] = "outputs/calibration"
SCENARIO_FILE: Final[str] = "data/scenarios/demo.yaml"
FIXTURE_ROOT: Final[str] = "tests/fixtures/llm"
BATCH_ACTIONS: Final[tuple[str, ...]] = ("plan", "run", "merge")

#: The browser's entry point, found inside the installed package rather than by a repository path,
#: so the command works from a wheel and from a source checkout alike.
UI_MODULE: Final[str] = str(Path(__file__).with_name("ui") / "app.py")


def _print_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Print the package version and exit.",
        callback=_print_version,
        is_eager=True,
    ),
) -> None:
    """Late Ming Mechanism Lab command line."""


@app.command("run")
def run(
    scenario: Annotated[
        Path | None,
        typer.Option(
            "--scenario",
            help=f"A declared scenario file, e.g. {SCENARIO_FILE}. Without one, the configured "
            "kernel window runs.",
        ),
    ] = None,
    config_file: Annotated[
        Path | None, typer.Option("--config", help="Read the simulation configuration from here.")
    ] = None,
    output_root: Annotated[
        Path, typer.Option("--output-root", help="Where the run directory is written.")
    ] = Path(OUTPUT_ROOT),
    seed: Annotated[
        int | None,
        typer.Option(
            "--seed", min=0, help=f"Override the root seed (default {DEFAULT_ROOT_SEED})."
        ),
    ] = None,
    ticks: Annotated[
        int | None, typer.Option("--ticks", min=1, help="Override the number of monthly ticks.")
    ] = None,
    warmup: Annotated[
        int | None, typer.Option("--warmup", min=0, help="Override the number of warm-up ticks.")
    ] = None,
    label: Annotated[
        str | None,
        typer.Option("--label", help="Distinguish repeated runs of the same configuration."),
    ] = None,
) -> None:
    """Run the model once and persist its artifacts.

    With ``--scenario`` the run is the declared sandbox scenario and its digest is compared with the
    digest the file records, so a demonstration that no longer reproduces is an error rather than a
    different number nobody notices.
    """
    if scenario is not None:
        _run_declared_scenario(scenario, output_root=output_root)
        return
    try:
        config = SimulationConfig.from_file(config_file) if config_file else SimulationConfig()
        config = _apply_overrides(config, seed=seed, ticks=ticks, warmup=warmup)
        result = SimulationKernel(config).run(run_label=label)
        directory = RunStore(output_root).write(result)
    except (ValueError, RunConflictError) as error:
        typer.echo(f"run failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    _echo_run(
        run_id=result.manifest.run_id,
        directory=directory,
        tick_count=result.summary.tick_count,
        warmup=config.warmup_ticks,
        event_count=result.summary.event_count,
        simulation_digest=result.summary.simulation_digest,
        manifest_digest=result.manifest.deterministic_digest(),
    )


def _run_declared_scenario(scenario: Path, *, output_root: Path) -> None:
    from late_ming_lab.experiments.demo import DemoError, run_demo

    try:
        outcome = run_demo(scenario, output_root=output_root)
    except (DemoError, ValueError, RunConflictError) as error:
        typer.echo(f"run failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"scenario: {outcome.scenario.id}")
    typer.echo(f"simulation_digest: {outcome.simulation_digest}")
    typer.echo(f"events: {outcome.event_count}")
    typer.echo(f"run_dir: {outcome.directory}")
    if not outcome.reproduced:
        for detail in outcome.details:
            typer.echo(f"reproduced: no - {detail}", err=True)
        raise typer.Exit(code=1)
    typer.echo("reproduced: yes")


def _echo_run(
    *,
    run_id: str,
    directory: Path,
    tick_count: int,
    warmup: int,
    event_count: int,
    simulation_digest: str,
    manifest_digest: str,
) -> None:
    """What a completed run prints: its identity, its size, and the two digests."""
    typer.echo(f"run_id: {run_id}")
    typer.echo(f"run_dir: {directory}")
    typer.echo(f"ticks: {tick_count} ({warmup} warm-up)")
    typer.echo(f"events: {event_count}")
    typer.echo(f"simulation_digest: {simulation_digest}")
    typer.echo(f"manifest_digest: {manifest_digest}")


@app.command("replay")
def replay(
    fixtures: Annotated[
        Path, typer.Option("--fixtures", help="The recorded exchanges to replay from.")
    ] = Path(FIXTURE_ROOT),
    output_root: Annotated[
        Path, typer.Option("--output-root", help="Where the replayed run is written.")
    ] = Path("outputs/replay"),
    ticks: Annotated[int, typer.Option("--ticks", min=1)] = 48,
    warmup: Annotated[int, typer.Option("--warmup", min=0)] = 8,
    seed: Annotated[int, typer.Option("--seed", min=0)] = 20_260_915,
) -> None:
    """Drive the decision layer from recorded fixtures: no network, no model, no API key."""
    from late_ming_lab.experiments.replay import ReplayError, replay_run

    try:
        outcome = replay_run(
            fixtures=fixtures,
            output_root=output_root,
            ticks=ticks,
            warmup_ticks=warmup,
            seed=seed,
        )
    except (ReplayError, ValueError, FileNotFoundError) as error:
        typer.echo(f"replay failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"run_id: {outcome.run_id}")
    typer.echo(f"decisions: {outcome.decisions}")
    typer.echo(f"refusals: {outcome.refusals}")
    typer.echo(f"fixtures: {outcome.fixtures}")
    typer.echo(f"fixture_digest: {outcome.fixture_digest}")
    typer.echo(f"run_dir: {outcome.directory}")


@app.command("experiment")
def experiment(
    family: Annotated[
        str, typer.Argument(help="ablations, morris, sobol, tipping, p10, p12, integrated.")
    ],
    root: Annotated[Path, typer.Option("--root", help="The repository root.")] = Path("."),
    replicates: Annotated[
        int | None,
        typer.Option("--replicates", min=1, help="Override the family's replicate count."),
    ] = None,
    seed: Annotated[
        int | None, typer.Option("--seed", min=0, help="Override the family's base seed.")
    ] = None,
) -> None:
    """Run one declared experiment family and write its artifacts and reports."""
    from late_ming_lab.experiments.families import FAMILIES, ExperimentError, run_family

    if family not in FAMILIES:
        typer.echo(
            f"experiment failed: unknown family {family!r}; expected one of "
            + ", ".join(sorted(FAMILIES)),
            err=True,
        )
        raise typer.Exit(code=2)
    try:
        written = run_family(family, root=root, replicates=replicates, seed=seed)
    except (ExperimentError, ValueError) as error:
        typer.echo(f"experiment failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    for path in written:
        typer.echo(f"wrote: {path}")


@app.command("calibrate")
def calibrate(
    root: Annotated[Path, typer.Option("--root", help="The repository root.")] = Path("."),
    particles: Annotated[
        int | None, typer.Option("--particles", min=1, help="Override the particle count.")
    ] = None,
    chains: Annotated[int, typer.Option("--chains", min=1)] = 1,
    sampler_seed: Annotated[int, typer.Option("--sampler-seed", min=0)] = 20_260_913,
    predictive: Annotated[
        bool, typer.Option("--predictive", help="Also run the posterior predictive pass.")
    ] = False,
) -> None:
    """Run one SMC calibration batch and write the ensemble."""
    from late_ming_lab.experiments.calibration import (
        run_calibration_batch,
        run_posterior_predictive,
    )

    try:
        if particles is None:
            ensemble, diagnostics, directory = run_calibration_batch(
                root, chains=chains, sampler_seed=sampler_seed, progressbar=True
            )
        else:
            ensemble, diagnostics, directory = run_calibration_batch(
                root,
                particles=particles,
                chains=chains,
                sampler_seed=sampler_seed,
                progressbar=True,
            )
        if predictive:
            run_posterior_predictive(root, batch_dir=directory)
    except (ValueError, FileNotFoundError) as error:
        typer.echo(f"calibrate failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"batch: {directory}")
    typer.echo(f"draws: {len(ensemble.draws)}")
    typer.echo(f"stages: {diagnostics.stages}")
    typer.echo(f"distinct_draws: {diagnostics.distinct_draws}")
    typer.echo(f"simulations: {diagnostics.simulations}")


@app.command("analyze")
def analyze(
    target: Annotated[
        Path, typer.Argument(help="A run directory, a batch directory, or the root.")
    ],
    report: Annotated[
        bool, typer.Option("--report", help="Regenerate the documents the artifacts support.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print the summary as JSON.")] = False,
) -> None:
    """Read what a run or a batch produced and report its headline numbers."""
    from late_ming_lab.analysis.summary import AnalysisError, summarize, write_reports

    try:
        summary = summarize(target)
        written = write_reports(target) if report else ()
    except (AnalysisError, ValueError, FileNotFoundError) as error:
        typer.echo(f"analyze failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    if as_json:
        typer.echo(summary.to_json())
    else:
        typer.echo(f"kind: {summary.kind}")
        typer.echo(f"source: {summary.source}")
        for name, value in summary.headline:
            typer.echo(f"{name}: {value}")
    for path in written:
        typer.echo(f"wrote: {path}")


@app.command("doctor")
def doctor(
    root: Annotated[Path, typer.Option("--root", help="The repository root.")] = Path("."),
    as_json: Annotated[bool, typer.Option("--json", help="Print the report as JSON.")] = False,
) -> None:
    """Check the environment: python, the lock, the artifacts, and the secret rules."""
    from late_ming_lab.env_checks import check_environment

    report = check_environment(root)
    if as_json:
        typer.echo(report.to_json())
    else:
        for finding in report.findings:
            mark = "ok  " if finding.ok else f"{finding.severity.upper()}"
            typer.echo(f"[{mark}] {finding.name}: {finding.detail}")
    if not report.ok():
        raise typer.Exit(code=1)


@app.command("bench")
def bench(
    report: Annotated[
        Path, typer.Option("--report", help="Where the benchmark report is written.")
    ] = Path("outputs/reports/benchmark.md"),
    profile: Annotated[
        bool, typer.Option("--profile/--no-profile", help="Profile the same workload.")
    ] = True,
    enforce: Annotated[
        bool,
        typer.Option("--enforce", help="Exit non-zero when a development threshold is missed."),
    ] = False,
    hpc: Annotated[
        bool, typer.Option("--hpc", help="Include the declared cluster budget in the report.")
    ] = True,
) -> None:
    """Measure the model against the declared thresholds and write the benchmark report."""
    from late_ming_lab.experiments.benchmark import run_benchmarks

    bench_report, path = run_benchmarks(path=report, with_profile=profile, with_hpc=hpc)
    measurement = bench_report.measurement
    typer.echo(f"ticks_per_second: {measurement.ticks_per_second:.1f}")
    typer.echo(f"seconds: {measurement.seconds:.2f}")
    typer.echo(f"peak_mib: {measurement.peak_mib:.0f}")
    typer.echo(f"report: {path}")
    failures = bench_report.failures()
    for failure in failures:
        typer.echo(
            f"threshold missed: {failure.threshold.name} {failure.measured:.2f} "
            f"against {failure.threshold.direction} {failure.threshold.bound:g}",
            err=True,
        )
    if failures and enforce:
        raise typer.Exit(code=1)


@app.command("batch")
def batch(
    action: Annotated[str, typer.Argument(help="plan, run or merge.")],
    family: Annotated[
        str, typer.Option("--family", help="The family to plan, e.g. integrated or p12.")
    ] = "integrated",
    root: Annotated[
        Path,
        typer.Option("--root", help="The repository root; batches go under its outputs/batches."),
    ] = Path("."),
    plan: Annotated[
        Path | None, typer.Option("--plan", help="The batch directory a task or merge works in.")
    ] = None,
    replicates: Annotated[int, typer.Option("--replicates", min=1)] = 1,
    base_seed: Annotated[int, typer.Option("--base-seed", min=0)] = DEFAULT_ROOT_SEED,
    task_index: Annotated[
        int | None, typer.Option("--task-index", min=0, help="The array index to run.")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Re-run a finished task.")] = False,
) -> None:
    """Plan a task list, run one array task, or merge the tasks that finished."""
    from late_ming_lab.experiments.batch import BatchError, merge_batch, plan_batch, run_task

    if action not in BATCH_ACTIONS:
        typer.echo(
            f"batch failed: unknown action {action!r}; expected " + ", ".join(BATCH_ACTIONS),
            err=True,
        )
        raise typer.Exit(code=2)
    try:
        if action == "plan":
            made = plan_batch(root, family=family, replicates=replicates, base_seed=base_seed)
            typer.echo(f"batch: {made.directory}")
            typer.echo(f"tasks: {len(made.tasks)}")
            return
        if plan is None:
            typer.echo(f"batch {action} needs --plan", err=True)
            raise typer.Exit(code=2)
        if action == "run":
            if task_index is None:
                typer.echo("batch run needs --task-index", err=True)
                raise typer.Exit(code=2)
            outcome = run_task(plan, task_index, force=force)
            typer.echo(f"task: {outcome.index} {outcome.status}")
            typer.echo(f"manifest_digest: {outcome.manifest_digest}")
            typer.echo(f"detail: {outcome.detail}")
            if outcome.status == "failed":
                raise typer.Exit(code=1)
            return
        if action == "merge":
            merged = merge_batch(plan)
            typer.echo(f"merged: {merged.merged}")
            typer.echo(f"missing: {list(merged.missing)}")
            typer.echo(f"failed: {list(merged.failed)}")
            for table in merged.tables:
                typer.echo(f"table: {table}")
            typer.echo(merged.note)
            return
    except (BatchError, ValueError, FileNotFoundError) as error:
        typer.echo(f"batch failed: {error}", err=True)
        raise typer.Exit(code=1) from error


@app.command("ui")
def ui(
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8876,
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    runs: Annotated[
        str | None,
        typer.Option("--runs", help="Colon-separated run or batch directories to offer."),
    ] = None,
) -> None:
    """Serve the artifact browser: county nodes, flows, bands, series, comparison and cards."""
    module = Path(UI_MODULE)
    if not module.exists():
        typer.echo(f"ui failed: {module} is missing", err=True)
        raise typer.Exit(code=1)
    command = [
        sys.executable,
        "-m",
        "solara",
        "run",
        str(module),
        "--port",
        str(port),
        "--host",
        host,
    ]
    environment = {"LATE_MING_UI_RUNS": runs} if runs else {}
    typer.echo(f"serving: http://{host}:{port}/")
    raise typer.Exit(code=subprocess.call(command, env={**os.environ, **environment}))


def _apply_overrides(
    config: SimulationConfig,
    *,
    seed: int | None,
    ticks: int | None,
    warmup: int | None,
) -> SimulationConfig:
    changes: dict[str, object] = {}
    if seed is not None:
        changes["root_seed"] = seed
    if ticks is not None:
        changes["tick_count"] = ticks
    if warmup is not None:
        changes["warmup_ticks"] = warmup
    return config.with_overrides(**changes) if changes else config


def main() -> None:
    """Console-script entry point."""
    app()
