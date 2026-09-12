"""Command-line interface for the Late Ming Mechanism Lab.

P00 shipped version reporting; P01 adds ``smoke-run``, which exercises the whole
deterministic kernel end to end — clock, RNG streams, event log, manifest and Parquet
output — without any historical content.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

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


@app.command("smoke-run")
def smoke_run(
    config_file: Annotated[
        Path | None,
        typer.Option("--config", help="Configuration YAML; defaults are used when omitted."),
    ] = None,
    output_root: Annotated[
        Path,
        typer.Option("--output-root", help="Directory that holds run directories."),
    ] = Path("outputs/runs"),
    seed: Annotated[
        int | None,
        typer.Option(
            "--seed",
            min=0,
            help=f"Override the root seed (regression default: {DEFAULT_ROOT_SEED}).",
        ),
    ] = None,
    ticks: Annotated[
        int | None,
        typer.Option("--ticks", min=1, help="Override the number of monthly ticks."),
    ] = None,
    warmup: Annotated[
        int | None,
        typer.Option("--warmup", min=0, help="Override the number of warm-up ticks."),
    ] = None,
    label: Annotated[
        str | None,
        typer.Option("--label", help="Distinguish repeated runs of the same configuration."),
    ] = None,
) -> None:
    """Run the deterministic kernel for the configured window and persist the artifacts."""
    try:
        config = SimulationConfig.from_file(config_file) if config_file else SimulationConfig()
        config = _apply_overrides(config, seed=seed, ticks=ticks, warmup=warmup)
        result = SimulationKernel(config).run(run_label=label)
        directory = RunStore(output_root).write(result)
    except (ValueError, RunConflictError) as error:
        typer.echo(f"smoke-run failed: {error}", err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"run_id: {result.manifest.run_id}")
    typer.echo(f"run_dir: {directory}")
    typer.echo(f"ticks: {result.summary.tick_count} ({config.warmup_ticks} warm-up)")
    typer.echo(f"events: {result.summary.event_count}")
    typer.echo(f"simulation_digest: {result.summary.simulation_digest}")
    typer.echo(f"manifest_digest: {result.manifest.deterministic_digest()}")


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
