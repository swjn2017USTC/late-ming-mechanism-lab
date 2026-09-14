"""The boundary surface: what it fits, what it refuses, and what it leaves alone.

Every frame here is synthetic. The analysis reads the run tables P10 and P12 wrote, so these tests
build the tables that would carry the columns rather than running the model: the separable case is
a boundary the fit should find exactly (``x + y > 1``, with a feature that carries nothing beside
it), and the rest are the refusals and the grid conventions a report depends on.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from late_ming_lab.analysis.boundary import (
    BOOSTED_MODEL,
    BoundaryError,
    fit_boundary,
    load_run_tables,
    partial_dependence,
    tipping_surface,
)

#: A frame large enough that five folds are comfortable, with an outcome that is exactly linear.
ROWS: int = 400

#: The test's own seed: the frames are synthetic, so they have to be reproducible too.
SEED: int = 7

#: A feature that is independent of the outcome, so "x and y are on top" is a claim with a control.
NOISE: str = "noise"


def _separable(rows: int = ROWS, seed: int = SEED) -> pl.DataFrame:
    """A table whose outcome is exactly ``x + y > 1``, plus a feature that carries nothing."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(0.0, 1.0, size=rows)
    y = rng.uniform(0.0, 1.0, size=rows)
    return pl.DataFrame(
        {
            "x": x,
            "y": y,
            NOISE: rng.normal(0.0, 1.0, size=rows),
            "outcome": (x + y > 1.0).astype(np.int64),
        }
    )


def test_a_separable_boundary_is_found_out_of_sample() -> None:
    """The score the fit reports is the cross-validated one, and this boundary is exact."""
    frame = _separable()

    fit = fit_boundary(frame, target="outcome", features=("x", "y", NOISE))

    assert fit.model == "logistic"
    assert fit.cross_validated_auc > 0.9
    assert fit.rows == ROWS
    assert {name for name, _ in fit.importance()[:2]} == {"x", "y"}
    magnitudes = [abs(value) for _, value in fit.importance()]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_a_constant_target_is_refused() -> None:
    frame = _separable().with_columns(pl.lit(1).alias("outcome"))

    with pytest.raises(BoundaryError, match="does not vary"):
        fit_boundary(frame, target="outcome", features=("x", "y"))


def test_a_target_with_three_outcomes_is_refused() -> None:
    frame = _separable().with_columns((pl.int_range(pl.len()) % 3).alias("outcome"))

    with pytest.raises(BoundaryError, match="not binary"):
        fit_boundary(frame, target="outcome", features=("x", "y"))


def test_a_constant_feature_is_refused() -> None:
    frame = _separable().with_columns(pl.lit(2.0).alias("flat"))

    with pytest.raises(BoundaryError, match="is constant"):
        fit_boundary(frame, target="outcome", features=("x", "flat"))


def test_a_feature_the_frame_does_not_carry_is_refused() -> None:
    with pytest.raises(BoundaryError, match="no column 'missing'"):
        fit_boundary(_separable(), target="outcome", features=("x", "missing"))


def test_too_few_rows_for_the_folds_or_fewer_than_two_folds_is_refused() -> None:
    with pytest.raises(BoundaryError, match="fewer than the 5 folds"):
        fit_boundary(_separable(rows=4), target="outcome", features=("x", "y"), folds=5)

    with pytest.raises(BoundaryError, match="at least 2 folds"):
        fit_boundary(_separable(), target="outcome", features=("x", "y"), folds=1)


def test_an_undeclared_model_is_refused() -> None:
    with pytest.raises(BoundaryError, match="unknown model"):
        fit_boundary(_separable(), target="outcome", features=("x", "y"), model="random-forest")


def test_a_fold_holding_one_class_is_refused_rather_than_scored() -> None:
    """Two positives over five folds cannot be scored: an unguarded fold returns NaN instead."""
    frame = _separable().with_columns(
        pl.when(pl.int_range(pl.len()) < 2).then(1).otherwise(0).alias("outcome")
    )

    with pytest.raises(BoundaryError, match="carries one class"):
        fit_boundary(frame, target="outcome", features=("x", "y"), folds=5)


def test_the_same_seed_fits_the_same_boundary() -> None:
    frame = _separable()

    first = fit_boundary(frame, target="outcome", features=("x", "y", NOISE), seed=11)
    second = fit_boundary(frame, target="outcome", features=("x", "y", NOISE), seed=11)

    assert first.coefficients == second.coefficients
    assert first.cross_validated_auc == second.cross_validated_auc
    assert first.auc_std == second.auc_std
    assert first.in_sample_auc == second.in_sample_auc


def test_the_boosted_model_reports_importances_over_the_held_out_folds() -> None:
    """A boosted fit has no coefficients; the pairs it reports come from the fold test sets."""
    frame = _separable()

    fit = fit_boundary(frame, target="outcome", features=("x", "y", NOISE), model=BOOSTED_MODEL)

    assert fit.model == BOOSTED_MODEL
    assert fit.cross_validated_auc > 0.9
    assert {name for name, _ in fit.importance()[:2]} == {"x", "y"}


def test_partial_dependence_reads_the_values_it_is_given_and_leaves_the_frame_alone() -> None:
    frame = _separable()
    fit = fit_boundary(frame, target="outcome", features=("x", "y", NOISE))
    before = frame.clone()

    surface = partial_dependence(fit, frame, feature="x", values=(0.0, 0.5, 1.2345))

    assert surface.columns == ["feature", "value", "mean_probability", "runs"]
    assert surface["value"].to_list() == [0.0, 0.5, 1.2345]
    assert surface["runs"].to_list() == [ROWS] * 3
    probabilities = surface["mean_probability"].to_list()
    assert probabilities[0] < probabilities[1] < probabilities[2]
    assert frame.equals(before)


def test_tipping_surface_counts_every_row_and_carries_the_top_row_into_the_last_bin() -> None:
    """Eight runs at the bottom of both axes, one at the maximum, which the last bin must take."""
    frame = pl.DataFrame(
        {
            "pressure": [0.0] * 8 + [10.0],
            "severity": [0.0] * 8 + [10.0],
            "outcome": [0, 1, 0, 1, 0, 1, 0, 1, 1],
        }
    )

    surface = tipping_surface(frame, target="outcome", x="pressure", y="severity", bins=3)

    assert surface.columns == ["x_bin", "y_bin", "x_centre", "y_centre", "runs", "observed_rate"]
    assert surface["runs"].sum() == frame.height
    top = surface.filter((pl.col("x_bin") == 2) & (pl.col("y_bin") == 2))
    assert top["runs"].to_list() == [1]
    assert top["observed_rate"].to_list() == [1.0]
    bottom = surface.filter((pl.col("x_bin") == 0) & (pl.col("y_bin") == 0))
    assert bottom["runs"].to_list() == [8]
    assert bottom["observed_rate"].to_list() == [0.5]
    empty = surface.filter((pl.col("x_bin") == 1) & (pl.col("y_bin") == 1))
    assert empty["observed_rate"].to_list() == [None]


def test_tipping_surface_refuses_a_frame_it_cannot_grid() -> None:
    frame = pl.DataFrame(
        {"pressure": [1.0, 2.0, 3.0], "severity": [1.0, 2.0, 3.0], "outcome": [0, 1, 0]}
    )
    with pytest.raises(BoundaryError, match="no column 'severity'"):
        tipping_surface(frame.drop("severity"), target="outcome", x="pressure", y="severity")

    with pytest.raises(BoundaryError, match="fewer than the 9 cells"):
        tipping_surface(frame, target="outcome", x="pressure", y="severity", bins=3)

    graded = _separable(rows=9).with_columns((pl.int_range(pl.len()) % 3).alias("outcome"))
    with pytest.raises(BoundaryError, match="not binary"):
        tipping_surface(graded, target="outcome", x="x", y="y", bins=3)

    flat = _separable(rows=9).with_columns(pl.lit(1.0).alias("flat"))
    with pytest.raises(BoundaryError, match="is constant"):
        tipping_surface(flat, target="outcome", x="flat", y="y", bins=3)


def test_load_run_tables_stacks_what_exists_and_names_each_source(tmp_path: Path) -> None:
    """A narrow batch and an absent batch are skipped, and the kept rows say where they came from.

    A phase report may be written before every batch exists, so a table it cannot use is not an
    error — unless none can be used at all.
    """
    good = tmp_path / "runs.parquet"
    _separable(rows=6).write_parquet(good)
    narrow = tmp_path / "tipping_grid.parquet"
    _separable(rows=6).select(["x", NOISE, "outcome"]).write_parquet(narrow)

    frame = load_run_tables(
        [good, narrow, tmp_path / "absent.parquet"], features=("x", "y"), target="outcome"
    )

    assert frame.columns == ["x", "y", "outcome", "source"]
    assert frame.height == 6
    assert frame["source"].unique().to_list() == [str(good)]


def test_load_run_tables_names_what_it_could_not_use(tmp_path: Path) -> None:
    with pytest.raises(BoundaryError, match=r"absent\.parquet"):
        load_run_tables([tmp_path / "absent.parquet"], features=("x", "y"), target="outcome")
