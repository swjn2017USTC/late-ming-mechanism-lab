"""Command-line interface for the Late Ming Mechanism Lab.

Phase P00 provides only the CLI skeleton and version reporting. Simulation commands
(for example ``smoke-run``) arrive in later phases.
"""

from __future__ import annotations

import typer

from late_ming_lab import __version__

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


def main() -> None:
    """Console-script entry point."""
    app()
