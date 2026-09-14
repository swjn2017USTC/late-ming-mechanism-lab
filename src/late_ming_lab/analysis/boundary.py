"""Where the model's own output changes: fitted boundaries, partial dependence, tipping surfaces.

P13's cards aggregate the evidence P09-P12 produced; this module adds the one reading those
artifacts do not carry, the *shape* of the run tables. Which declared features separate a binary
outcome, how much of that separation survives out of sample, what the fitted boundary says as one
feature moves while the rest are held, and where a two-feature grid turns over.

Nothing here runs the model. Every frame is a table P10 or P12 already wrote, every fit is a
function of that table plus a declared seed, and there is no clock, network or shared state in it:
the seed governs the fold split and the permutation draws, and both declared estimators are
deterministic on a given table, so a boundary can be reproduced from the table it was read from.

A fitted surface is a description, not a cause. It says what separates the runs that were made,
which is a property of this model under this design; it cannot say what an intervention would do.
:data:`CAUSAL_DISCLAIMER` states that difference in the words a report has to render beside any
surface it quotes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

import numpy as np
import numpy.typing as npt
import polars as pl

# The installed scikit-learn ships no `py.typed` marker, so mypy reads it as untyped: one ignore
# per submodule, as `experiments.sensitivity` does for SALib. Nothing here leans on a signature the
# library would have declared: every value it hands back is re-read through float() or np.asarray().
from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore[import-untyped]
from sklearn.inspection import permutation_importance  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.metrics import roc_auc_score  # type: ignore[import-untyped]
from sklearn.model_selection import StratifiedKFold  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

#: Rendered into every report that quotes a fitted surface, so the phase cannot present a
#: description of simulation output as if it were a causal finding.
CAUSAL_DISCLAIMER: Final[str] = (
    "A boundary, a partial dependence or a tipping surface describes these runs; it is not "
    "evidence about the past. What separates the runs that were made is a property of this model "
    "under this design, and no coefficient, importance or AUC here measures what an intervention "
    "would do. A historical claim needs an intervention this table cannot supply."
)

#: The seed a fit draws from unless the caller declares another. It seeds the fold split and the
#: permutation draws; the estimators themselves draw nothing.
DEFAULT_SEED: Final[int] = 20_260_917

#: The folds a boundary is scored on. Fewer than two is refused, because a single fold is the
#: in-sample score wearing the name of the out-of-sample one.
DEFAULT_FOLDS: Final[int] = 5

#: The declared models, named as :func:`fit_boundary` takes them.
LINEAR_MODEL: Final[str] = "logistic"
BOOSTED_MODEL: Final[str] = "hist-gradient-boosting"
MODELS: Final[tuple[str, ...]] = (LINEAR_MODEL, BOOSTED_MODEL)

#: Iterations the linear model may take on standardized features. The library default of a hundred
#: warns rather than converging on tables of this width.
LINEAR_MAX_ITER: Final[int] = 1000

#: Permutation draws per fold behind a boosted model's feature ranking; the fit reports the mean
#: over the repeats and the folds.
PERMUTATION_REPEATS: Final[int] = 5


class BoundaryError(ValueError):
    """Raised when a table cannot be read as a boundary, a surface or a grid."""


@dataclass(frozen=True, slots=True)
class BoundaryFit:
    """One fitted boundary: what separated the two outcomes, and how well it did out of sample.

    ``coefficients`` holds one pair per feature, in the order the caller declared them. For the
    linear model the value is a coefficient on standardized features, so the pairs compare in
    magnitude. A boosted model has no coefficients, so the pairs hold permutation importances
    measured on the cross-validated folds instead — same shape, and :meth:`importance` is the one
    reading that means the same thing for both.
    """

    target: str
    features: tuple[str, ...]
    rows: int
    model: str
    in_sample_auc: float
    cross_validated_auc: float
    auc_std: float
    coefficients: tuple[tuple[str, float], ...]

    def importance(self) -> tuple[tuple[str, float], ...]:
        """Features ordered by |coefficient|, strongest first."""
        return tuple(sorted(self.coefficients, key=lambda pair: abs(pair[1]), reverse=True))


def fit_boundary(
    frame: pl.DataFrame,
    *,
    target: str,
    features: Sequence[str],
    model: str = LINEAR_MODEL,
    folds: int = DEFAULT_FOLDS,
    seed: int = DEFAULT_SEED,
) -> BoundaryFit:
    """Fit a boundary between two outcomes over features the caller declares.

    Refuses: a target that is not binary, a target with no variation (every row the same), a
    feature that is absent or constant, fewer rows than folds, and folds < 2. The score reported is
    the cross-validated one; the in-sample score is reported beside it so a reader can see the gap.
    Features are standardized (for the linear model) using statistics computed inside each fold.

    With ``model="hist-gradient-boosting"`` the reported pairs are instead permutation importances
    of the cross-validated folds, averaged: the boosted model has no coefficients, and an
    importance read on its own training rows would only restate the overfitting the in-sample score
    already shows. Rows missing the target or any feature are dropped before anything is fitted,
    and ``rows`` is what is left.

    The models are the library's own: a logistic regression with no penalty tuning and a raised
    iteration cap, and a histogram gradient booster that does not hold out for early stopping,
    because a split drawn from a seed the fit does not record would make the surface
    irreproducible.
    """
    if model not in MODELS:
        raise BoundaryError(f"unknown model {model!r}; the declared models are {', '.join(MODELS)}")
    if folds < 2:
        raise BoundaryError(f"a boundary needs at least 2 folds, not {folds}")
    if not features:
        raise BoundaryError("no features were declared, so there is nothing to separate on")
    prepared = _prepared(frame, target, features)
    if prepared.height < folds:
        raise BoundaryError(
            f"the {prepared.height} rows carrying {target!r} and every feature are fewer than the "
            f"{folds} folds they would be scored on"
        )
    labels = _binary_labels(prepared, target)
    for name in features:
        if prepared[name].n_unique() < 2:
            raise BoundaryError(
                f"the feature {name!r} is constant over the {prepared.height} rows, so it cannot "
                "separate a boundary"
            )
    matrix = _matrix(prepared, features)
    scores, importances = _cross_validated(matrix, labels, model=model, folds=folds, seed=seed)
    fitted = _unfitted(model).fit(matrix, labels)
    in_sample_auc = float(roc_auc_score(labels, fitted.predict_proba(matrix)[:, 1]))
    if model == LINEAR_MODEL:
        coefficients = _standardized_coefficients(fitted, features)
    else:
        ranked = np.mean(importances, axis=0)
        coefficients = tuple(zip(features, (float(value) for value in ranked), strict=True))
    return BoundaryFit(
        target=target,
        features=tuple(features),
        rows=prepared.height,
        model=model,
        in_sample_auc=in_sample_auc,
        cross_validated_auc=float(np.mean(scores)),
        auc_std=float(np.std(scores)),
        coefficients=coefficients,
    )


def partial_dependence(
    fit: BoundaryFit, frame: pl.DataFrame, *, feature: str, values: Sequence[float]
) -> pl.DataFrame:
    """Mean predicted probability as one feature is set to each value and the rest are held.

    Returns columns ['feature','value','mean_probability','runs']. The probabilities come from the
    fit's declared model refitted on ``frame``, because a :class:`BoundaryFit` is a summary and
    carries no estimator; both models are deterministic functions of the table they are fitted on,
    so the refit reproduces the surface the fit describes. ``frame`` is not modified: the feature
    is set on a copy of the design, so a value no run carries is still predicted.
    """
    if feature not in fit.features:
        raise BoundaryError(f"{feature!r} is not one of the fitted features: {list(fit.features)}")
    prepared = _prepared(frame, fit.target, fit.features)
    matrix = _matrix(prepared, fit.features)
    fitted = _unfitted(fit.model).fit(matrix, _binary_labels(prepared, fit.target))
    column = fit.features.index(feature)
    rows: list[dict[str, object]] = []
    for value in values:
        held = matrix.copy()
        held[:, column] = float(value)
        probability = fitted.predict_proba(held)[:, 1]
        rows.append(
            {
                "feature": feature,
                "value": float(value),
                "mean_probability": float(np.mean(probability)),
                "runs": held.shape[0],
            }
        )
    return pl.DataFrame(rows)


def tipping_surface(
    frame: pl.DataFrame, *, target: str, x: str, y: str, bins: int = 3
) -> pl.DataFrame:
    """Observed rate and counts per cell of a two-feature grid, for describing where a region sits.

    Returns columns ['x_bin','y_bin','x_centre','y_centre','runs','observed_rate'] and refuses a
    frame without both columns or with fewer rows than cells. Every cell of the grid is reported,
    including one no run falls in: ``observed_rate`` is null there, because an empty cell is not a
    rate of zero. ``target`` has to be binary here as well, or "rate" has no meaning.

    Bins are equal-width over each column's own range and half-open below their top edge, the last
    one carrying the maximum — the convention of
    :func:`late_ming_lab.experiments.counterfactual.response_curve`.
    """
    prepared = _prepared(frame, target, (x, y))
    cells = bins * bins
    if prepared.height < cells:
        raise BoundaryError(
            f"the frame holds {prepared.height} rows, fewer than the {cells} cells of a {bins} by "
            f"{bins} grid"
        )
    for name in (x, y):
        if prepared[name].n_unique() < 2:
            raise BoundaryError(
                f"the axis {name!r} is constant over the {prepared.height} rows, so it cannot "
                "place a grid"
            )
    outcome = _binary_labels(prepared, target)
    labelled = prepared.with_columns(pl.Series("_outcome", outcome))
    x_edges = _bin_edges(np.asarray(prepared[x], dtype=np.float64), bins)
    y_edges = _bin_edges(np.asarray(prepared[y], dtype=np.float64), bins)
    rows: list[dict[str, object]] = []
    for x_index in range(bins):
        x_low, x_high = x_edges[x_index], x_edges[x_index + 1]
        last_x = x_index == bins - 1
        for y_index in range(bins):
            y_low, y_high = y_edges[y_index], y_edges[y_index + 1]
            last_y = y_index == bins - 1
            cell = labelled.filter(
                (pl.col(x) >= x_low)
                & ((pl.col(x) <= x_high) if last_x else (pl.col(x) < x_high))
                & (pl.col(y) >= y_low)
                & ((pl.col(y) <= y_high) if last_y else (pl.col(y) < y_high))
            )
            rows.append(
                {
                    "x_bin": x_index,
                    "y_bin": y_index,
                    "x_centre": (x_low + x_high) / 2.0,
                    "y_centre": (y_low + y_high) / 2.0,
                    "runs": cell.height,
                    "observed_rate": (
                        None if cell.is_empty() else float(cast("float", cell["_outcome"].mean()))
                    ),
                }
            )
    return pl.DataFrame(rows, schema_overrides={"observed_rate": pl.Float64})


def load_run_tables(
    paths: Sequence[str | Path], *, features: Sequence[str], target: str
) -> pl.DataFrame:
    """Stack existing run tables on a common feature set, keeping only rows that carry them all.

    The tables are the batches P10 and P12 wrote (runs.parquet, tipping_grid.parquet). A table
    whose columns do not include every feature and the target is skipped with its name collected,
    as is a path that is not on disk: a phase report may be written before every batch exists. The
    returned frame carries the union of the kept rows — rows missing any of the declared columns
    dropped — and a ``source`` column naming the table each row came from. If no table survives,
    the error names every one that was skipped, because an empty frame cannot be told apart from a
    batch that simply has no rows.
    """
    kept: list[pl.DataFrame] = []
    skipped: list[str] = []
    columns = [*features, target]
    for path in paths:
        source = Path(path)
        if not source.exists():
            skipped.append(str(source))
            continue
        frame = pl.read_parquet(source)
        missing = [name for name in columns if name not in frame.columns]
        if missing:
            skipped.append(f"{source} (no {', '.join(missing)})")
            continue
        kept.append(
            frame.select(columns).drop_nulls().with_columns(pl.lit(str(source)).alias("source"))
        )
    if not kept:
        named = "; ".join(skipped) if skipped else "no path was given"
        raise BoundaryError(f"no run table could be stacked on the declared features: {named}")
    return pl.concat(kept, how="vertical_relaxed")


def _prepared(frame: pl.DataFrame, target: str, features: Sequence[str]) -> pl.DataFrame:
    """The declared target and features, with every row missing one of them dropped."""
    missing = [name for name in (target, *features) if name not in frame.columns]
    if missing:
        noun = "column" if len(missing) == 1 else "columns"
        raise BoundaryError(f"the frame has no {noun} {', '.join(repr(name) for name in missing)}")
    return frame.select([*features, target]).drop_nulls()


def _binary_labels(prepared: pl.DataFrame, target: str) -> npt.NDArray[np.int8]:
    """The target as 0 and 1, refusing anything that is not exactly two outcomes.

    The lower of the two values becomes 0 and the higher 1, so the encoding does not depend on the
    column's type: an indicator written as a boolean, an integer or a float reads the same.
    """
    values = prepared[target].unique().sort()
    if values.len() < 2:
        carried = f"the single value {values[0]!r}" if values.len() == 1 else "no value at all"
        raise BoundaryError(f"{target!r} does not vary: its {prepared.height} rows carry {carried}")
    if values.len() > 2:
        listed = ", ".join(repr(value) for value in values.to_list())
        raise BoundaryError(
            f"{target!r} is not binary: it carries {values.len()} values ({listed})"
        )
    return np.asarray(prepared[target].eq(values[1]).cast(pl.Int8).to_numpy(), dtype=np.int8)


def _matrix(prepared: pl.DataFrame, features: Sequence[str]) -> npt.NDArray[np.float64]:
    return np.asarray(prepared.select(list(features)).to_numpy(), dtype=np.float64)


def _unfitted(model: str) -> Pipeline:
    """An unfitted pipeline for one declared model.

    The linear model's standardization is the pipeline's first step, so its statistics are computed
    on whatever rows it is fitted on — inside a fold, the fold's training rows, never its test rows.
    Neither estimator draws: the solver and the histogram grower are deterministic on a given
    table, so the seed governs only the fold split and the permutation draws. The booster does not
    hold out for early stopping, for the same reason.
    """
    if model == LINEAR_MODEL:
        return Pipeline(
            [
                ("standardize", StandardScaler()),
                ("boundary", LogisticRegression(max_iter=LINEAR_MAX_ITER)),
            ]
        )
    return Pipeline([("boundary", HistGradientBoostingClassifier(early_stopping=False))])


def _cross_validated(
    matrix: npt.NDArray[np.float64],
    labels: npt.NDArray[np.int8],
    *,
    model: str,
    folds: int,
    seed: int,
) -> tuple[list[float], list[npt.NDArray[np.float64]]]:
    """The fold scores, and for the boosted model each fold's permutation importances."""
    scores: list[float] = []
    importances: list[npt.NDArray[np.float64]] = []
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    for index, (train_rows, test_rows) in enumerate(splitter.split(matrix, labels)):
        train_labels = labels[train_rows]
        test_labels = labels[test_rows]
        if np.unique(test_labels).size < 2:
            raise BoundaryError(
                f"fold {index} of {folds} carries one class in its {test_labels.size} test rows, "
                f"so it cannot be scored: the smaller outcome needs at least {folds} rows"
            )
        fitted = _unfitted(model).fit(matrix[train_rows], train_labels)
        probability = fitted.predict_proba(matrix[test_rows])[:, 1]
        scores.append(float(roc_auc_score(test_labels, probability)))
        if model == BOOSTED_MODEL:
            ranking = permutation_importance(
                fitted,
                matrix[test_rows],
                test_labels,
                scoring="roc_auc",
                n_repeats=PERMUTATION_REPEATS,
                random_state=seed,
            )
            importances.append(np.asarray(ranking.importances_mean, dtype=np.float64))
    return scores, importances


def _standardized_coefficients(
    fitted: Pipeline, features: Sequence[str]
) -> tuple[tuple[str, float], ...]:
    """The linear model's coefficients, one per feature, on the standardized design."""
    linear = cast("LogisticRegression", fitted.named_steps["boundary"])
    return tuple(zip(features, (float(weight) for weight in linear.coef_[0]), strict=True))


def _bin_edges(values: npt.NDArray[np.float64], bins: int) -> list[float]:
    """Equal-width edges over the value range, widened so the top value is included.

    The same convention as :func:`late_ming_lab.experiments.counterfactual.response_curve`: every
    bin is half-open below its top edge except the last, and the top edge is pushed past the
    maximum so the runs sitting at the maximum stay inside the grid. The caller refuses a column
    that does not vary, so the range here is never empty.
    """
    low = float(np.min(values))
    high = float(np.max(values))
    step = (high - low) / bins
    edges = [low + index * step for index in range(bins + 1)]
    edges[-1] = high + abs(high) * 1e-9 + 1e-12
    return edges
