"""The evidence bundle: the P09-P12 artifacts, read once and cited by name.

A mechanism card is only as good as what it can point at, so this module does the pointing. Every
accessor returns the quantities the phase's earlier documents were generated from: the calibration
ensemble's parameter verdicts and the pattern checks, the Morris elementary effects, the ablation's
paired comparisons, the counterfactual interaction arms, the P12 readings and verdicts, plus the P08
registry that supplies each card's historical support and historical challenge.

Nothing here runs the model. If an artifact is missing, the loader says which one, rather than
handing back an empty table that a card could quietly cite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.calibration.ensemble import Ensemble
from late_ming_lab.calibration.priors import build_priors
from late_ming_lab.calibration.summary_stats import scalar
from late_ming_lab.evidence.cards import load_cards
from late_ming_lab.evidence.ledger import HistoricalPattern, PatternRegistry, load_patterns
from late_ming_lab.experiments.ablation import (
    INTERACTION_TRIPLES,
    MORRIS_LEVELS,
    P10_BASE_SEED,
    REPORTED_METRICS,
    SENSITIVITY_OUTPUTS,
    _design_of,
    _outputs_from_runs,
    load_batch,
)
from late_ming_lab.experiments.counterfactual import (
    compare_metrics,
    interaction_effect,
    with_breakdown_lines,
)
from late_ming_lab.experiments.policy_robustness import P12Result, load_p12
from late_ming_lab.experiments.sensitivity import morris_indices, sweep_parameters

#: Where the phase's earlier artifacts live, relative to the repository root.
CALIBRATION_ROOT: Final[str] = "outputs/calibration"
EXPERIMENT_ROOT: Final[str] = "outputs/experiments"
ABLATION_BATCH: Final[str] = "p10-ablations"
MORRIS_BATCH: Final[str] = "p10-morris"
ROBUSTNESS_BATCH: Final[str] = "p12-robustness"

#: The baseline arm of the P10 ablation experiment, and the metric every card quotes most.
ABLATION_BASELINE: Final[str] = "BASELINE"
BREAKDOWN_METRIC: Final[str] = "breakdown"

#: How P08 records a pattern check: a `target` is scored on the calibration run, a `reserved`
#: pattern only in the ensemble's predictive pass, and the window says which stretch of it the check
#: asked about - `hold-out`, `extrapolation` or the run as a whole.
TARGET_KIND: Final[str] = "target"
RESERVED_KIND: Final[str] = "reserved"
HOLD_OUT_WINDOW: Final[str] = "hold-out"
EXTRAPOLATION_WINDOW: Final[str] = "extrapolation"
WHOLE_RUN_WINDOW: Final[str] = "whole-run"


#: The P12 ratchet reading as its own text records it: start and end arrears, the number of months
#: the stock declined, and the assessed value it is set against. The reading *is* the artifact's
#: record of the monthly series - the batch wrote no month-by-month table - so a figure quoted from
#: it is quoted from what the phase actually saved, and a reading that does not parse is refused
#: rather than approximated.
RATCHET_READING: Final[re.Pattern[str]] = re.compile(
    r"arrears (?P<start>[\d,]+) to (?P<end>[\d,]+) tael with (?P<declines>\d+) month\(s\) of "
    r"decline, against (?P<assessed>[\d,]+) assessed"
)


def _thousands(value: str) -> float:
    return float(value.replace(",", ""))


class EvidenceError(FileNotFoundError):
    """Raised when an artifact a card needs is not on disk."""


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Every artifact a card may cite, loaded and named."""

    root: Path
    parameter_verdicts: pl.DataFrame
    checks: pl.DataFrame
    sensitivity: pl.DataFrame
    comparisons: pl.DataFrame
    interactions: pl.DataFrame
    tipping: pl.DataFrame
    runs: pl.DataFrame
    readings: pl.DataFrame
    verdicts: pl.DataFrame
    movement: pl.DataFrame
    patterns: PatternRegistry

    def parameter(self, name: str) -> dict[str, object] | None:
        rows = self.parameter_verdicts.filter(pl.col("parameter") == name)
        return dict(rows.row(0, named=True)) if not rows.is_empty() else None

    def check_share(self, pattern_id: str, *, kind: str, window: str | None = None) -> float | None:
        """The share of draws that satisfied a pattern's checks, or None when it was not scored.

        A pattern that never entered the predictive pass has no reserved checks at all, which is a
        different statement from a share of zero: the first cannot be cited, the second can.
        """
        rows = self.checks.filter((pl.col("pattern_id") == pattern_id) & (pl.col("kind") == kind))
        if window is not None:
            rows = rows.filter(pl.col("window") == window)
        if rows.is_empty():
            return None
        return scalar(rows["satisfied"].cast(pl.Float64).mean())

    def reserved_share(self, pattern_id: str, *, window: str = HOLD_OUT_WINDOW) -> float | None:
        """How a reserved pattern scored: held-out years, extrapolation, or the run as a whole."""
        return self.check_share(pattern_id, kind=RESERVED_KIND, window=window)

    def target_share(self, pattern_id: str) -> float | None:
        return self.check_share(pattern_id, kind=TARGET_KIND)

    def check_question(self, pattern_id: str, *, kind: str) -> str | None:
        """The question a pattern check asked, so a card can quote what was actually tested."""
        rows = self.checks.filter((pl.col("pattern_id") == pattern_id) & (pl.col("kind") == kind))
        return str(rows["question"][0]) if not rows.is_empty() else None

    def morris(self, parameter: str, output: str) -> tuple[float, float] | None:
        """The elementary-effect mean and dispersion for one parameter and output."""
        rows = self.sensitivity.filter(
            (pl.col("parameter") == parameter) & (pl.col("output") == output)
        )
        if rows.is_empty():
            return None
        return scalar(rows["mu_star"][0]), scalar(rows["sigma"][0])

    def morris_rank(self, output: str) -> tuple[str, ...]:
        """Parameters ordered by their elementary-effect size on one output."""
        return tuple(
            self.sensitivity.filter(pl.col("output") == output)
            .sort("mu_star", descending=True)["parameter"]
            .to_list()
        )

    def comparison(self, arm: str, metric: str) -> dict[str, object] | None:
        rows = self.comparisons.filter((pl.col("arm") == arm) & (pl.col("metric") == metric))
        return dict(rows.row(0, named=True)) if not rows.is_empty() else None

    def interaction(self, triple: int, metric: str) -> dict[str, object] | None:
        single_a, single_b, joint = INTERACTION_TRIPLES[triple]
        rows = self.interactions.filter((pl.col("metric") == metric) & (pl.col("joint") == joint))
        if rows.is_empty():
            return None
        row = dict(rows.row(0, named=True))
        row["single_a"] = single_a
        row["single_b"] = single_b
        return row

    def presence(self, mechanism: str, policy: str) -> float | None:
        """The share of a policy's replicates in which a mechanism reading is present."""
        rows = self.readings.filter(
            (pl.col("mechanism") == mechanism) & (pl.col("label") == policy)
        )
        if rows.is_empty():
            return None
        return scalar(rows["present"].cast(pl.Float64).mean())

    def strengths(self, mechanism: str, policy: str) -> tuple[float, ...]:
        rows = self.readings.filter(
            (pl.col("mechanism") == mechanism) & (pl.col("label") == policy)
        )
        return tuple(float(value) for value in rows["strength"].to_list())

    def reading_texts(self, mechanism: str, policy: str) -> tuple[str, ...]:
        rows = self.readings.filter(
            (pl.col("mechanism") == mechanism) & (pl.col("label") == policy)
        )
        return tuple(str(text) for text in rows["reading"].to_list())

    def verdict(self, mechanism: str) -> dict[str, object] | None:
        rows = self.verdicts.filter(pl.col("mechanism") == mechanism)
        return dict(rows.row(0, named=True)) if not rows.is_empty() else None

    def region(self, policy: str) -> dict[str, object] | None:
        rows = self.movement.filter(pl.col("policy") == policy)
        return dict(rows.row(0, named=True)) if not rows.is_empty() else None

    def ratchet_figures(self, policy: str) -> tuple[tuple[float, float, int, float], ...]:
        """Per replicate: (start arrears, end arrears, decline months, assessed value)."""
        rows = self.readings.filter(
            (pl.col("mechanism") == "fiscal-military-ratchet") & (pl.col("label") == policy)
        )
        figures: list[tuple[float, float, int, float]] = []
        for text in rows["reading"].to_list():
            match = RATCHET_READING.match(str(text))
            if match is None:
                raise EvidenceError(f"a ratchet reading did not parse: {text!r}")
            figures.append(
                (
                    _thousands(match["start"]),
                    _thousands(match["end"]),
                    int(match["declines"]),
                    _thousands(match["assessed"]),
                )
            )
        if not figures:
            raise EvidenceError(f"no ratchet readings for policy {policy!r}")
        return tuple(figures)

    def pattern(self, pattern_id: str) -> HistoricalPattern:
        return self.patterns.require(pattern_id)

    def arm_aggregate(self, arm: str, column: str) -> float | None:
        """An arm's mean on one column of the P10 ablation runs, or None when the arm is absent."""
        rows = self._ablation_rows(arm)
        if rows.is_empty():
            return None
        return scalar(rows[column].cast(pl.Float64).mean())

    def arm_breakdown_month(self, arm: str) -> float | None:
        """The median tick at which an arm's replicates crossed the declared breakdown line."""
        rows = self._ablation_rows(arm).filter(pl.col("breakdown") == 1)
        if rows.is_empty():
            return None
        return scalar(rows["time_to_breakdown"].cast(pl.Float64).median())

    def _ablation_rows(self, arm: str) -> pl.DataFrame:
        return self.runs.filter(pl.col("label") == arm)


def load_evidence(root: str | Path) -> EvidenceBundle:
    """Read every artifact the cards cite, or say which one is missing."""
    directory = Path(root)
    p12 = load_p12(directory / EXPERIMENT_ROOT / ROBUSTNESS_BATCH)
    return EvidenceBundle(
        root=directory,
        parameter_verdicts=_parameter_verdicts(directory),
        checks=_checks(directory),
        sensitivity=_sensitivity(directory),
        comparisons=_comparisons(directory),
        interactions=_interactions(directory),
        tipping=p12.summary,
        runs=_ablation_runs(directory),
        readings=_readings(p12),
        verdicts=p12.verdicts,
        movement=p12.movement,
        patterns=load_patterns(directory),
    )


def _int_or(value: object, default: int) -> int:
    """A manifest field as an int, falling back to the declared default when it is absent."""
    return value if isinstance(value, int) else default


def _require(path: Path) -> Path:
    if not path.exists():
        raise EvidenceError(
            f"{path} is missing; a card that needs it cannot be written from the artifact"
        )
    return path


def _calibration_batch(directory: Path) -> Path:
    batches = sorted((directory / CALIBRATION_ROOT).glob("p09-*"))
    if not batches:
        raise EvidenceError(f"no P09 calibration batch under {directory / CALIBRATION_ROOT}")
    return batches[0]


def _parameter_verdicts(directory: Path) -> pl.DataFrame:
    ensemble = Ensemble.load(_calibration_batch(directory))
    priors = build_priors(load_cards(directory))
    return pl.DataFrame(
        [
            {
                "parameter": verdict.name,
                "prior_low": verdict.prior_low,
                "prior_high": verdict.prior_high,
                "median": verdict.posterior_median,
                "contraction": verdict.contraction,
                "verdict": verdict.verdict.value,
            }
            for verdict in ensemble.verdicts(priors)
        ]
    )


def _checks(directory: Path) -> pl.DataFrame:
    return pl.read_parquet(_calibration_batch(directory) / "predictive_checks.parquet")


def _morris_runs(directory: Path) -> tuple[pl.DataFrame, dict[str, object]]:
    runs, _, manifest = load_batch(directory / EXPERIMENT_ROOT / MORRIS_BATCH)
    return runs, manifest


def _sensitivity(directory: Path) -> pl.DataFrame:
    """The Morris elementary effects, recomputed exactly as the P10 report computes them."""
    runs, manifest = _morris_runs(directory)
    sweep = sweep_parameters(load_cards(directory))
    design = _design_of(manifest)
    return morris_indices(
        sweep,
        pl.DataFrame({parameter.name: runs[parameter.name] for parameter in sweep}),
        _outputs_from_runs(runs),
        levels=_int_or(design.get("levels"), MORRIS_LEVELS),
        seed=_int_or(manifest.get("base_seed"), P10_BASE_SEED),
    )


def _ablation_runs(directory: Path) -> pl.DataFrame:
    batch = directory / EXPERIMENT_ROOT / ABLATION_BATCH
    runs = pl.read_parquet(_require(batch / "runs.parquet"))
    governance = pl.read_parquet(_require(batch / "governance_timeline.parquet"))
    return with_breakdown_lines(runs, governance)


def _comparisons(directory: Path) -> pl.DataFrame:
    return compare_metrics(
        _ablation_runs(directory), baseline=ABLATION_BASELINE, metrics=REPORTED_METRICS
    )


def _interactions(directory: Path) -> pl.DataFrame:
    runs = _ablation_runs(directory)
    rows: list[dict[str, object]] = []
    for single_a, single_b, joint in INTERACTION_TRIPLES:
        for metric in REPORTED_METRICS:
            effect = interaction_effect(
                runs,
                metric=metric,
                baseline=ABLATION_BASELINE,
                single_a=single_a,
                single_b=single_b,
                joint=joint,
            )
            rows.append(
                {
                    "metric": metric,
                    "single_a": single_a,
                    "single_b": single_b,
                    "joint": joint,
                    "effect_a": effect.effect_a,
                    "effect_b": effect.effect_b,
                    "effect_joint": effect.effect_joint,
                    "interaction": effect.interaction,
                    "difference_low": effect.difference_low,
                    "difference_high": effect.difference_high,
                    "verdict": effect.direction,
                }
            )
    return pl.DataFrame(rows)


def _readings(result: P12Result) -> pl.DataFrame:
    frames = [arm.readings for arm in result.arms if not arm.readings.is_empty()]
    if not frames:
        raise EvidenceError("the P12 batch carries no mechanism readings")
    return pl.concat(frames)


#: The outputs the sensitivity findings are reported against, re-exported for the cards.
SENSITIVITY_TARGETS: Final[tuple[str, ...]] = SENSITIVITY_OUTPUTS
