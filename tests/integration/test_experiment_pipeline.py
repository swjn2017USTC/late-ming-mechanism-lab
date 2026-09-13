"""The P10 pipeline end to end, at the smallest scale that still runs the real experiments.

The batch here is two replicates of the arms plus a two-trajectory Morris design, a four-base Sobol
design and a three-point grid, all at a shortened window. That is not an experiment anyone should
read — the reports say which batch they came from — but it exercises every link: the runner, the
outcome extraction, the design execution, the SALib analysis, the grid and the four generated
documents. The real batches live under `outputs/experiments/` and are what the phase report quotes.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from late_ming_lab.experiments.ablation import (
    ABLATION_LABEL,
    GRID_LABEL,
    MORRIS_LABEL,
    SOBOL_LABEL,
    run_ablation_experiment,
    run_morris,
    run_sobol,
    run_tipping_grid,
    select_parameters,
    strongest_pair,
    write_experiment_reports,
)
from late_ming_lab.experiments.runner import RUNS_FILE

REPO_ROOT = Path(__file__).resolve().parents[2]
TICKS = 36
WARMUP = 12
REPLICATES = 1


@pytest.fixture(scope="module")
def experiments(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Run one tiny batch of each kind into a temporary tree."""
    root = tmp_path_factory.mktemp("p10")
    ablations = run_ablation_experiment(
        REPO_ROOT, output_dir=root, replicates=REPLICATES, ticks=TICKS, warmup_ticks=WARMUP
    )
    morris, indices, sweep = run_morris(
        REPO_ROOT, output_dir=root, trajectories=1, ticks=TICKS, warmup_ticks=WARMUP
    )
    selected = select_parameters(indices, sweep)[:2]
    sobol, _ = run_sobol(
        REPO_ROOT, output_dir=root, selected=selected, base=2, ticks=TICKS, warmup_ticks=WARMUP
    )
    grid = run_tipping_grid(
        REPO_ROOT,
        output_dir=root,
        parameters=strongest_pair(indices, sweep),
        points=2,
        replicates=1,
        ticks=TICKS,
        warmup_ticks=WARMUP,
    )
    reports = write_experiment_reports(
        REPO_ROOT,
        output_dir=root / "reports",
        ablations=ablations.directory,
        morris=morris.directory,
        sobol=sobol.directory,
        tipping=grid.directory,
    )
    return {
        "root": root,
        "ablations": ablations.directory,
        "morris": morris.directory,
        "sobol": sobol.directory,
        "grid": grid.directory,
        "reports": reports[0].parent,
    }


def test_every_batch_is_named_for_its_experiment(experiments: dict[str, Path]) -> None:
    assert experiments["ablations"].name == ABLATION_LABEL
    assert experiments["morris"].name == MORRIS_LABEL
    assert experiments["sobol"].name == SOBOL_LABEL
    assert experiments["grid"].name == GRID_LABEL
    for key in ("ablations", "morris", "sobol", "grid"):
        assert (experiments[key] / RUNS_FILE).exists()
        manifest = json.loads((experiments[key] / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["run_count"] == pl.read_parquet(experiments[key] / RUNS_FILE).height
        assert manifest["ticks"] == TICKS
        assert manifest["design"]["kind"] in {"ablation", "morris", "sobol", "grid"}


def test_the_ablation_batch_pairs_arms_on_the_replicate(experiments: dict[str, Path]) -> None:
    runs = pl.read_parquet(experiments["ablations"] / RUNS_FILE)

    assert runs["label"].n_unique() > 9
    seeds = runs.group_by("replicate").agg(pl.col("root_seed").n_unique().alias("distinct"))
    assert seeds["distinct"].to_list() == [1] * REPLICATES


def test_the_reports_are_written_and_read_the_batches_they_name(
    experiments: dict[str, Path],
) -> None:
    reports = experiments["reports"]
    assert {path.name for path in reports.iterdir()} == {
        "ablation.md",
        "interactions.md",
        "sensitivity.md",
        "tipping.md",
    }
    ablation = (reports / "ablation.md").read_text(encoding="utf-8")
    assert ABLATION_LABEL in ablation
    for arm in (
        "BASELINE",
        "NO_DROUGHT",
        "OPEN_MIGRATION_EXIT",
        "JOINT_NO_DROUGHT+HIGH_RELIEF",
    ):
        assert f"`{arm}`" in ablation
    assert "Collapse probability" in ablation
    assert "Is the result the line or the model?" in ablation

    sensitivity = (reports / "sensitivity.md").read_text(encoding="utf-8")
    assert MORRIS_LABEL in sensitivity and SOBOL_LABEL in sensitivity
    assert "second-order" in sensitivity

    tipping = (reports / "tipping.md").read_text(encoding="utf-8")
    assert GRID_LABEL in tipping


def test_the_collapse_share_in_the_report_is_the_share_in_the_artifact(
    experiments: dict[str, Path],
) -> None:
    """A report number must be recomputable from the table it claims to describe."""
    runs = pl.read_parquet(experiments["ablations"] / RUNS_FILE)
    share = runs.filter(pl.col("label") == "BASELINE")["breakdown"].cast(pl.Float64).mean()
    expected = float(share) if isinstance(share, (int, float)) else 0.0
    ablation = (experiments["reports"] / "ablation.md").read_text(encoding="utf-8")
    row = next(line for line in ablation.splitlines() if line.startswith("| BASELINE |"))
    assert f"{expected:.4g}" in row
