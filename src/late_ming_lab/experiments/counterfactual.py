"""Distributional comparison of arms: paired differences, effect sizes, interactions and
curvature.

The phase's outputs are distributions, not means. Two arms can have the same average tax base and
completely different behaviour — one steady, one collapsing in half its runs — so every
comparison here reports quantiles, the paired difference distribution, the share of replicates
that move in the same direction, a rank-based effect size, and a bootstrap interval on the paired
median difference.
A difference is called only when that interval excludes zero; everything else is reported as
unresolved rather than as a small effect.

Three further readings come from the same tables:

- **collapse probability**, as a share with a Wilson interval, because a share of twelve runs is not
  a probability until its uncertainty is stated;
- **interaction effects**, from the two-by-two factorial the joint arms provide: the joint arm's
  paired
  difference against the sum of its two single-arm differences. Additivity is the null, and the
  interval on the difference from additivity is what the report quotes;
- **curvature**, as the second difference of a metric's binned medians along one parameter, which is
  how a non-linearity or a tipping region shows up in a design that already exists.

All of it is computed from the run tables the runner writes; nothing here runs the model, and every
random draw is seeded, so a report is reproducible from its artifact.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, cast

import numpy as np
import polars as pl

#: Bootstrap resamples for a paired interval, and the two-sided confidence level they cover.
DEFAULT_RESAMPLES: Final[int] = 2000
DEFAULT_CONFIDENCE: Final[float] = 0.95

#: The z-multiplier for a Wilson interval at the default confidence. Declared rather than computed,
#: because a 95% Wilson interval is the only one this phase reports.
WILSON_Z: Final[float] = 1.96

#: Every bootstrap in this module draws from this seed, so a report is reproducible from its
#: artifact and two runs of the same comparison agree to the last digit.
STATISTICS_SEED: Final[int] = 20_260_914


class ComparisonError(ValueError):
    """Raised when two arms cannot be compared on the replicates they share."""


@dataclass(frozen=True, slots=True)
class PairedComparison:
    """One metric, one arm against the baseline, over the replicates both have."""

    metric: str
    baseline: str
    arm: str
    replicates: int
    baseline_median: float
    baseline_q1: float
    baseline_q3: float
    arm_median: float
    arm_q1: float
    arm_q3: float
    median_difference: float
    difference_low: float
    difference_high: float
    share_increase: float
    cliffs_delta: float

    @property
    def resolved(self) -> bool:
        """Whether the paired interval excludes zero, i.e. whether a direction is claimed."""
        return self.difference_low > 0.0 or self.difference_high < 0.0

    @property
    def direction(self) -> str:
        if not self.resolved:
            return "unresolved"
        return "up" if self.median_difference > 0.0 else "down"


def _column(runs: pl.DataFrame, metric: str) -> pl.Series:
    if metric not in runs.columns:
        raise ComparisonError(f"the run table has no column {metric!r}")
    return runs[metric]


def paired_comparison(
    runs: pl.DataFrame,
    *,
    metric: str,
    baseline: str,
    arm: str,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = STATISTICS_SEED,
) -> PairedComparison:
    """Compare one arm with the baseline on the replicates they share, with an interval.

    The arms are aligned by replicate, which is the common-random-numbers pairing: replicate *r* of
    the arm and of the baseline saw the same weather, the same market draws and the same household
    draws, so their difference is the declared intervention.
    """
    left = runs.filter(pl.col("label") == baseline).select(
        "replicate", pl.col(metric).alias("left")
    )
    right = runs.filter(pl.col("label") == arm).select("replicate", pl.col(metric).alias("right"))
    joined = left.join(right, on="replicate", how="inner").sort("replicate")
    if joined.is_empty():
        raise ComparisonError(f"{baseline} and {arm} share no replicate for {metric!r}")
    if joined.height != left.height or joined.height != right.height:
        raise ComparisonError(
            f"{baseline} and {arm} have different replicate sets for {metric!r}: "
            f"{left.height} against {right.height}, {joined.height} shared"
        )
    before = np.asarray(joined["left"], dtype=float)
    after = np.asarray(joined["right"], dtype=float)
    differences = after - before
    low, high = _bootstrap_interval(
        differences, resamples=resamples, confidence=confidence, seed=seed
    )
    return PairedComparison(
        metric=metric,
        baseline=baseline,
        arm=arm,
        replicates=joined.height,
        baseline_median=float(np.median(before)),
        baseline_q1=float(np.quantile(before, 0.25)),
        baseline_q3=float(np.quantile(before, 0.75)),
        arm_median=float(np.median(after)),
        arm_q1=float(np.quantile(after, 0.25)),
        arm_q3=float(np.quantile(after, 0.75)),
        median_difference=float(np.median(differences)),
        difference_low=low,
        difference_high=high,
        share_increase=float(np.mean(differences > 0.0)),
        cliffs_delta=cliffs_delta_of(before, after),
    )


def _bootstrap_interval(
    values: np.ndarray, *, resamples: int, confidence: float, seed: int
) -> tuple[float, float]:
    """A percentile bootstrap interval for the median of a paired difference series."""
    if values.size == 0:
        raise ComparisonError("a bootstrap needs at least one difference")
    if values.size == 1:
        return float(values[0]), float(values[0])
    generator = np.random.default_rng(seed)
    picks = generator.integers(0, values.size, size=(resamples, values.size))
    medians = np.median(values[picks], axis=1)
    tail = (1.0 - confidence) / 2.0
    return float(np.quantile(medians, tail)), float(np.quantile(medians, 1.0 - tail))


def cliffs_delta_of(before: np.ndarray, after: np.ndarray) -> float:
    """Cliff's delta: the share of pairs where the arm is above the baseline, minus the reverse.

    Reported beside the paired median difference because the two answer different questions: the
    interval asks about the size of a shift, the delta about how often it happens at all.
    """
    if before.size == 0 or after.size == 0:
        return 0.0
    comparisons = after[:, None] - before[None, :]
    greater = float(np.sum(comparisons > 0.0))
    smaller = float(np.sum(comparisons < 0.0))
    total = float(comparisons.size)
    return (greater - smaller) / total if total > 0.0 else 0.0


def compare_metrics(
    runs: pl.DataFrame,
    *,
    baseline: str,
    metrics: Sequence[str],
    arms: Sequence[str] | None = None,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = STATISTICS_SEED,
) -> pl.DataFrame:
    """Every arm against the baseline on every metric, one row per pair and metric."""
    labels = list(arms) if arms is not None else sorted(set(runs["label"].to_list()) - {baseline})
    rows: list[dict[str, object]] = []
    for arm in labels:
        for metric in metrics:
            comparison = paired_comparison(
                runs, metric=metric, baseline=baseline, arm=arm, resamples=resamples, seed=seed
            )
            rows.append(
                {
                    "metric": comparison.metric,
                    "baseline": comparison.baseline,
                    "arm": comparison.arm,
                    "replicates": comparison.replicates,
                    "baseline_median": comparison.baseline_median,
                    "baseline_q1": comparison.baseline_q1,
                    "baseline_q3": comparison.baseline_q3,
                    "arm_median": comparison.arm_median,
                    "arm_q1": comparison.arm_q1,
                    "arm_q3": comparison.arm_q3,
                    "median_difference": comparison.median_difference,
                    "difference_low": comparison.difference_low,
                    "difference_high": comparison.difference_high,
                    "share_increase": comparison.share_increase,
                    "cliffs_delta": comparison.cliffs_delta,
                    "direction": comparison.direction,
                }
            )
    return pl.DataFrame(rows)


def collapse_probability(
    runs: pl.DataFrame, *, indicator: str = "breakdown", by: str = "label"
) -> pl.DataFrame:
    """The share of an arm's runs that reach the breakdown line, with a Wilson interval.

    The line itself (`BREAKDOWN_INDICATORS`) is a declared reading rule, so this share is a property
    of the model *and* of the rule. The reporting module therefore prints the distribution of the
    crossed count beside it, and the phase report says how the share moves when the line moves.
    """
    if indicator not in runs.columns:
        raise ComparisonError(f"the run table has no column {indicator!r}")
    grouped = runs.group_by(by).agg(
        [
            pl.col(indicator).cast(pl.Float64).mean().alias("share"),
            pl.len().alias("runs"),
            pl.col(indicator).cast(pl.Float64).sum().alias("hits"),
        ]
    )
    rows = []
    for row in grouped.iter_rows(named=True):
        runs_count = int(row["runs"])
        hits = int(row["hits"])
        low, high = wilson_interval(hits, runs_count)
        rows.append(
            {
                by: row[by],
                "runs": runs_count,
                "runs_in_breakdown": hits,
                "collapse_probability": hits / runs_count if runs_count else 0.0,
                "wilson_low": low,
                "wilson_high": high,
            }
        )
    return pl.DataFrame(rows).sort(by)


def wilson_interval(successes: int, trials: int, *, z: float = WILSON_Z) -> tuple[float, float]:
    """The Wilson score interval for a binomial share; (0, 0) when there are no trials."""
    if trials <= 0:
        return 0.0, 0.0
    share = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (share + z * z / (2.0 * trials)) / denominator
    spread = (
        z
        * ((share * (1.0 - share) / trials + z * z / (4.0 * trials * trials)) ** 0.5)
        / denominator
    )
    return max(0.0, centre - spread), min(1.0, centre + spread)


@dataclass(frozen=True, slots=True)
class InteractionEffect:
    """The joint arm's effect against the sum of the two single-arm effects."""

    metric: str
    single_a: str
    single_b: str
    joint: str
    effect_a: float
    effect_b: float
    effect_joint: float
    interaction: float
    difference_low: float
    difference_high: float

    @property
    def resolved(self) -> bool:
        return self.difference_low > 0.0 or self.difference_high < 0.0

    @property
    def direction(self) -> str:
        if not self.resolved:
            return "additive"
        return "super-additive" if self.interaction > 0.0 else "sub-additive"


def interaction_effect(
    runs: pl.DataFrame,
    *,
    metric: str,
    baseline: str,
    single_a: str,
    single_b: str,
    joint: str,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = STATISTICS_SEED,
) -> InteractionEffect:
    """Measure two mechanisms' interaction directly, with an interval on the departure from
    additivity.

    Additivity is the null hypothesis, so the statistic is the joint paired difference minus the sum
    of the two single-arm paired differences, bootstrap-resampled over replicates.
    """
    base = (
        runs.filter(pl.col("label") == baseline)
        .select("replicate", pl.col(metric).alias("base"))
        .sort("replicate")
    )
    aligned = base
    for label, name in ((single_a, "a"), (single_b, "b"), (joint, "joint")):
        arm = (
            runs.filter(pl.col("label") == label)
            .select("replicate", pl.col(metric).alias(name))
            .sort("replicate")
        )
        aligned = aligned.join(arm, on="replicate", how="inner")
    if aligned.height != base.height:
        raise ComparisonError("the factorial arms do not share the baseline's replicates")
    effect_a = np.asarray(aligned["a"], dtype=float) - np.asarray(aligned["base"], dtype=float)
    effect_b = np.asarray(aligned["b"], dtype=float) - np.asarray(aligned["base"], dtype=float)
    joint_effect = np.asarray(aligned["joint"], dtype=float) - np.asarray(
        aligned["base"], dtype=float
    )
    interaction = joint_effect - effect_a - effect_b
    low, high = _bootstrap_interval(
        interaction, resamples=resamples, confidence=DEFAULT_CONFIDENCE, seed=seed
    )
    return InteractionEffect(
        metric=metric,
        single_a=single_a,
        single_b=single_b,
        joint=joint,
        effect_a=float(np.median(effect_a)),
        effect_b=float(np.median(effect_b)),
        effect_joint=float(np.median(joint_effect)),
        interaction=float(np.median(interaction)),
        difference_low=low,
        difference_high=high,
    )


def response_curve(
    runs: pl.DataFrame,
    *,
    parameter: str,
    metric: str,
    bins: int = 5,
) -> pl.DataFrame:
    """A parameter's response in binned quantiles of the metric, plus the local curvature.

    The curvature is the second difference of the bin medians against the bin centres, normalized by
    the bin spacing, so a straight line reads as zero and a tipping region reads as a large value at
    a particular place. It is reported with the bin it belongs to, not as a single number.
    """
    if parameter not in runs.columns or metric not in runs.columns:
        raise ComparisonError(f"the run table has no column {parameter!r} or {metric!r}")
    frame = runs.select(pl.col(parameter).alias("x"), pl.col(metric).alias("y")).drop_nulls()
    if frame.height < bins:
        raise ComparisonError(f"{parameter!r} has fewer runs than bins")
    edges = _bin_edges(np.asarray(frame["x"], dtype=float), bins)
    rows: list[dict[str, object]] = []
    for index in range(bins):
        low, high = edges[index], edges[index + 1]
        last = index == bins - 1
        subset = frame.filter(
            (pl.col("x") >= low) & ((pl.col("x") <= high) if last else (pl.col("x") < high))
        )
        if subset.is_empty():
            continue
        rows.append(
            {
                "bin": index,
                "bin_low": low,
                "bin_high": high,
                "bin_centre": (low + high) / 2.0,
                "runs": subset.height,
                "median": _number(subset["y"].median()),
                "q1": _number(subset["y"].quantile(0.25)),
                "q3": _number(subset["y"].quantile(0.75)),
            }
        )
    curved = pl.DataFrame(rows)
    if curved.height < 3:
        return curved.with_columns(pl.lit(0.0).alias("curvature"))
    centres = np.asarray(curved["bin_centre"], dtype=float)
    medians = np.asarray(curved["median"], dtype=float)
    spacing = np.diff(centres)
    second = (medians[2:] - 2.0 * medians[1:-1] + medians[:-2]) / (spacing[1:] * spacing[:-1])
    curvature = np.concatenate([[0.0, 0.0], second])
    return curved.with_columns(pl.Series("curvature", curvature))


def _number(value: object) -> float:
    """A polars aggregate as a float; 0.0 when it is null."""
    return 0.0 if value is None else float(cast("float", value))


def _bin_edges(values: np.ndarray, bins: int) -> list[float]:
    """Equal-width edges over the value range, widened so the top value is included."""
    low = float(np.min(values))
    high = float(np.max(values))
    if high <= low:
        return [low, high]
    step = (high - low) / bins
    edges = [low + index * step for index in range(bins + 1)]
    edges[-1] = high + abs(high) * 1e-9 + 1e-12
    return edges


def crossed_count_distribution(
    runs: pl.DataFrame, *, column: str = "indicators_crossed_end", by: str = "label"
) -> pl.DataFrame:
    """How many of the eight declared lines each arm crosses, as a distribution rather than a mean.

    The breakdown share depends on a declared line; this table is what a reader looks at to see how
    far from that line an arm actually sits, and whether the line is doing the work.
    """
    if column not in runs.columns:
        raise ComparisonError(f"the run table has no column {column!r}")
    return (
        runs.group_by(by, column)
        .agg(pl.len().alias("runs"))
        .sort(by, column)
        .with_columns((pl.col("runs") / pl.col("runs").sum().over(by)).alias("share"))
    )


#: The candidate breakdown lines a report reads the run against, from strict to loose. The declared
#: line is one of them; the rest show how much of the result is the line rather than the model.
BREAKDOWN_LINES: Final[tuple[int, ...]] = (3, 4, 5, 6, 7, 8)


def with_breakdown_lines(
    runs: pl.DataFrame, governance: pl.DataFrame, *, lines: Sequence[int] = BREAKDOWN_LINES
) -> pl.DataFrame:
    """Add each run's peak crossed count and one indicator column per candidate line.

    The declared breakdown reading asks whether a run *ever* holds the declared number of crossed
    lines at a sampled tick, so the peak over the run's own timeline is the quantity the line is
    compared against. Carrying every candidate line lets the report show what the choice costs.
    """
    peak = governance.group_by("label", "replicate").agg(
        pl.col("crossed").max().alias("peak_crossed")
    )
    enriched = runs.join(peak, on=["label", "replicate"], how="left").with_columns(
        pl.col("peak_crossed").fill_null(0.0)
    )
    return enriched.with_columns(
        [
            (pl.col("peak_crossed") >= line).cast(pl.Float64).alias(f"peak_at_least_{line}")
            for line in lines
        ]
    )


def line_sensitivity(
    runs: pl.DataFrame, *, lines: Sequence[int] = BREAKDOWN_LINES, by: str = "label"
) -> pl.DataFrame:
    """The breakdown share per arm at every candidate line, so the declared line can be judged."""
    rows: list[dict[str, object]] = []
    for line in lines:
        column = f"peak_at_least_{line}"
        if column not in runs.columns:
            raise ComparisonError(f"the run table has no column {column!r}")
        shares = collapse_probability(runs, indicator=column, by=by)
        for row in shares.iter_rows(named=True):
            rows.append({"line": line, **row})
    return pl.DataFrame(rows).sort(by, "line")


def response_by_value(runs: pl.DataFrame, *, parameter: str, metric: str) -> pl.DataFrame:
    """A response read at the design's own values, for a grid rather than a sample.

    A grid samples a handful of exact values, so binning them into equal-width intervals would label
    each median with a centre it was not measured at. This groups by the value itself, and the
    curvature is the second difference of those medians against the true spacing.
    """
    if parameter not in runs.columns or metric not in runs.columns:
        raise ComparisonError(f"the run table has no column {parameter!r} or {metric!r}")
    frame = runs.select(pl.col(parameter).alias("x"), pl.col(metric).alias("y")).drop_nulls()
    grouped = (
        frame.group_by("x")
        .agg(
            [
                pl.col("y").median().alias("median"),
                pl.col("y").quantile(0.25).alias("q1"),
                pl.col("y").quantile(0.75).alias("q3"),
                pl.len().alias("runs"),
            ]
        )
        .sort("x")
    )
    rows = grouped.to_dicts()
    centres = np.asarray([float(row["x"]) for row in rows], dtype=float)
    medians = np.asarray([_number(row["median"]) for row in rows], dtype=float)
    curvature = np.zeros(len(rows), dtype=float)
    if len(rows) >= 3:
        spacing = np.diff(centres)
        curvature[2:] = (medians[2:] - 2.0 * medians[1:-1] + medians[:-2]) / (
            spacing[1:] * spacing[:-1]
        )
    return pl.DataFrame(
        [
            {
                "value": float(row["x"]),
                "runs": int(row["runs"]),
                "median": _number(row["median"]),
                "q1": _number(row["q1"]),
                "q3": _number(row["q3"]),
                "curvature": float(curvature[index]),
            }
            for index, row in enumerate(rows)
        ]
    )


def time_to_breakdown_summary(runs: pl.DataFrame, *, by: str = "label") -> pl.DataFrame:
    """When each arm broke down, among the runs that actually did.

    The sentinel that marks "never" is kept out of the paired statistics on purpose: a median of
    -1.0 is not a time, and subtracting it from a real tick would make an arm that broke down look
    like an arm that held out longer. This table reports the count that never reached the line
    beside the quantiles of the ones that did, so the timing question is answerable without the
    sentinel ever entering an arithmetic operation.
    """
    if "time_to_breakdown" not in runs.columns:
        raise ComparisonError("the run table has no column 'time_to_breakdown'")
    reached = runs.filter(pl.col("time_to_breakdown") >= 0.0)
    rows: list[dict[str, object]] = []
    for label in sorted(runs[by].unique().to_list()):
        arm = runs.filter(pl.col(by) == label)
        times = reached.filter(pl.col(by) == label)["time_to_breakdown"]
        rows.append(
            {
                by: label,
                "runs": arm.height,
                "runs_reaching_the_line": times.len(),
                "runs_never_reaching": arm.height - times.len(),
                "median_tick": _number(times.median()) if times.len() else None,
                "q1_tick": _number(times.quantile(0.25)) if times.len() else None,
                "q3_tick": _number(times.quantile(0.75)) if times.len() else None,
            }
        )
    return pl.DataFrame(rows).sort(by)
