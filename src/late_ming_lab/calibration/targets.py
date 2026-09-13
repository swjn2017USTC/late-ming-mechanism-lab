"""The calibration objective: every ``target`` pattern turned into checks a run can pass or fail.

P08 recorded the target patterns as *shapes* — "dispersion rising as the crisis deepens", "receipts
persistently below the assessed quota" — not as series. A least-squares distance to a historical
number therefore does not exist for them, and inventing one would be exactly the fitting this
project forbids. What exists is a comparison of signs: a check reads a statistic or a pair of series
out of the run, compares it against a threshold that the pattern's own wording fixes (below the
quota; rising; co-moving), and comes back satisfied or violated. Each pattern's score is the share
of its checks that failed, so the objective is a vector of six numbers in ``[0, 1]``, and every one
of them stays visible in the ensemble rather than being collapsed into a single fit.

Three properties are enforced here rather than left to the caller:

- **Only ``target`` patterns may be scored.** A hold-out or extrapolation pattern is refused with
  :class:`CalibrationObjectiveError`; the eight patterns P08 reserved cannot enter an objective even
  by accident.
- **An objective is bound to the calibration window.** :meth:`Objective.score` refuses any other
  window, so the events it reads are the calibration window's by construction — the blindness test
  in the suite deletes every later event and asserts the scores do not move.
- **Every check cites the P08 signature it reads.** The declaration carries a signature index, and
  building the objective fails if that signature does not exist, so no check can describe a claim
  the evidence layer does not make.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import polars as pl

from late_ming_lab.calibration.summary_stats import (
    scalar,
    tick_series,
    yearly_series,
)
from late_ming_lab.calibration.windows import CalibrationWindow, WindowRole
from late_ming_lab.evidence.ledger import CalibrationRole, PatternRegistry


class CalibrationObjectiveError(ValueError):
    """Raised when an objective is asked to read something it must not read."""


def rank_correlation(x: Sequence[float], y: Sequence[float]) -> float:
    """Spearman's rho over two equally long series; 0.0 when either side has no variation.

    Ties are averaged, so a series that is zero in most years still contributes its ordering rather
    than a spurious perfect correlation.
    """
    if len(x) != len(y):
        raise CalibrationObjectiveError("rank correlation needs two equally long series")
    if len(x) < 3:
        return 0.0
    left = pl.Series("x", [float(value) for value in x]).rank(method="average")
    right = pl.Series("y", [float(value) for value in y]).rank(method="average")
    mean_left = scalar(left.mean())
    mean_right = scalar(right.mean())
    centred_left = [float(value) - mean_left for value in left]
    centred_right = [float(value) - mean_right for value in right]
    numerator = sum(a * b for a, b in zip(centred_left, centred_right, strict=True))
    denominator = (sum(a * a for a in centred_left) * sum(b * b for b in centred_right)) ** 0.5
    return 0.0 if denominator == 0.0 else numerator / denominator


class CheckKind(StrEnum):
    """How a check reads the run."""

    #: The series rises across the window (last year above first year).
    RISES = "rises"
    #: The series falls across the window (last year below first year).
    FALLS = "falls"
    #: Two yearly series move together (Spearman rho above zero).
    CO_MOVES_POSITIVE = "co-moves-positive"
    #: The series stays below a natural line for most of the window's ticks.
    MOSTLY_BELOW = "mostly-below"
    #: The series is above zero in the years whose distress is above the window median.
    PRESENT_IN_CRISIS_YEARS = "present-in-crisis-years"
    #: The series is above a line for most of the window's ticks.
    MOSTLY_ABOVE = "mostly-above"
    #: Two yearly series move apart (Spearman rho below zero).
    CO_MOVES_NEGATIVE = "co-moves-negative"
    #: The series' worst year falls in the last years of the window.
    PEAK_IN_LAST_YEARS = "peak-in-last-years"
    #: More than a declared share of the series' total falls in the last years of the window.
    SHARE_IN_LAST_YEARS = "share-in-last-years"
    #: More than a declared share of the series' total falls after a declared tick.
    SHARE_AFTER_TICK = "share-after-tick"


class SeriesShape(StrEnum):
    """Which per-tick series the check reads."""

    TICK = "tick"
    YEARLY = "yearly"


@dataclass(frozen=True, slots=True)
class Check:
    """One declared comparison, anchored to the P08 signature it reads."""

    check_id: str
    pattern_id: str
    signature_index: int
    kind: CheckKind
    #: The series column the check reads; for a co-movement check, the first of the two.
    statistic: str
    #: The second series column of a co-movement check.
    against: str | None = None
    #: The natural line for :attr:`CheckKind.MOSTLY_BELOW`.
    line: float | None = None
    #: The share of ticks a :attr:`CheckKind.MOSTLY_BELOW` check requires below the line.
    share: float | None = None
    question: str = ""

    def __post_init__(self) -> None:
        co_movement = {CheckKind.CO_MOVES_POSITIVE, CheckKind.CO_MOVES_NEGATIVE}
        if self.kind in co_movement and self.against is None:
            raise CalibrationObjectiveError(f"{self.check_id}: a co-movement check needs a partner")
        if self.kind not in co_movement and self.against is not None:
            raise CalibrationObjectiveError(
                f"{self.check_id}: only a co-movement check takes 'against'"
            )
        needs_a_line = {CheckKind.MOSTLY_BELOW, CheckKind.MOSTLY_ABOVE}
        if self.kind in needs_a_line and (self.line is None or self.share is None):
            raise CalibrationObjectiveError(
                f"{self.check_id}: a {self.kind.value} check needs a line and a share"
            )


def _distress_column() -> str:
    return "unmet_ratio"


#: The declared checks, in pattern order. Each reads a statistic or a series and cites the P08
#: signature whose wording fixes the comparison. Nothing here carries a fitted magnitude: the
#: thresholds are signs (above zero), the quota (a ratio below one) and a share below a line.
CHECKS: Final[tuple[Check, ...]] = (
    Check(
        "intake-tracks-desertion",
        "absorption-of-deserters-and-refugees",
        signature_index=0,
        kind=CheckKind.CO_MOVES_POSITIVE,
        statistic="band_intake_adults",
        against="deserted_troops",
        question="does band in-take rise in the years when more soldiers desert?",
    ),
    Check(
        "intake-tracks-distress",
        "absorption-of-deserters-and-refugees",
        signature_index=0,
        kind=CheckKind.CO_MOVES_POSITIVE,
        statistic="band_intake_adults",
        against=_distress_column(),
        question="does band in-take rise in the years when households are in greater distress?",
    ),
    Check(
        "bands-grow",
        "absorption-of-deserters-and-refugees",
        signature_index=0,
        kind=CheckKind.RISES,
        statistic="band_troops",
        question="does total band strength grow across the window?",
    ),
    Check(
        "elite-share-rises",
        "debt-transfers-land",
        signature_index=0,
        kind=CheckKind.RISES,
        statistic="elite_land_share",
        question="does the elite's share of land rise across the window?",
    ),
    Check(
        "household-inequality-rises",
        "debt-transfers-land",
        signature_index=0,
        kind=CheckKind.RISES,
        statistic="cohort_land_gini",
        question="does inequality in land per household rise across the window?",
    ),
    Check(
        "transfer-tracks-distress",
        "debt-transfers-land",
        signature_index=0,
        kind=CheckKind.CO_MOVES_POSITIVE,
        statistic="elite_land_share",
        against=_distress_column(),
        question="does the elite's land share rise as distress rises?",
    ),
    Check(
        "dispersion-tracks-distress",
        "famine-local-price-extremes",
        signature_index=0,
        kind=CheckKind.CO_MOVES_POSITIVE,
        statistic="price_cv",
        against=_distress_column(),
        question="does cross-node price dispersion widen as distress rises?",
    ),
    Check(
        "dispersion-widens",
        "famine-local-price-extremes",
        signature_index=0,
        kind=CheckKind.RISES,
        statistic="price_cv",
        question="is the worst year's dispersion above the first year's?",
    ),
    Check(
        "abandonment-present-in-crisis-years",
        "land-abandonment-in-famine",
        signature_index=0,
        kind=CheckKind.PRESENT_IN_CRISIS_YEARS,
        statistic="land_abandoned_mu",
        question="is any land abandoned in the years whose distress is above the window median?",
    ),
    Check(
        "abandonment-tracks-distress",
        "land-abandonment-in-famine",
        signature_index=0,
        kind=CheckKind.CO_MOVES_POSITIVE,
        statistic="land_abandoned_mu",
        against=_distress_column(),
        question="does abandonment appear in the worse years rather than the better ones?",
    ),
    Check(
        "visible-base-contracts",
        "land-abandonment-in-famine",
        signature_index=0,
        kind=CheckKind.FALLS,
        statistic="taxable_land_mu",
        question="does the visible tax base contract across the window?",
    ),
    Check(
        "receipts-below-quota-persistent",
        "receipts-shortfall-chronic",
        signature_index=0,
        kind=CheckKind.MOSTLY_BELOW,
        statistic="receipts_over_quota",
        line=1.0,
        share=0.5,
        question="do receipts stay below the assessed quota in most months of the window?",
    ),
    Check(
        "arrears-accumulate",
        "receipts-shortfall-chronic",
        signature_index=0,
        kind=CheckKind.RISES,
        statistic="arrears_tael",
        question="does the arrears stock accumulate across the window?",
    ),
)


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """One check's measurement in one run, with the reading the report quotes."""

    check_id: str
    pattern_id: str
    question: str
    value: float
    satisfied: bool
    reading: str


@dataclass(frozen=True, slots=True)
class PatternScore:
    """One target pattern's result: its checks and the share of them that failed."""

    pattern_id: str
    checks: tuple[CheckOutcome, ...]

    @property
    def score(self) -> float:
        if not self.checks:
            return 0.0
        failed = sum(1 for check in self.checks if not check.satisfied)
        return failed / len(self.checks)


@dataclass(frozen=True, slots=True)
class TargetScores:
    """The objective vector of one run: one score per target pattern, in a fixed order."""

    patterns: tuple[PatternScore, ...]

    def vector(self) -> tuple[float, ...]:
        return tuple(pattern.score for pattern in self.patterns)

    def total(self) -> float:
        """The mean pattern score, the scalar view the sampler's distance scalarises."""
        if not self.patterns:
            raise CalibrationObjectiveError("no target patterns to score")
        return sum(pattern.score for pattern in self.patterns) / len(self.patterns)

    def failing_checks(self) -> tuple[CheckOutcome, ...]:
        return tuple(
            check for pattern in self.patterns for check in pattern.checks if not check.satisfied
        )


def target_pattern_ids(registry: PatternRegistry) -> tuple[str, ...]:
    """The ids of every pattern P08 marked as a calibration target, in a stable order."""
    return tuple(sorted(pattern.id for pattern in registry.by_role(CalibrationRole.TARGET)))


def objective_payload() -> tuple[tuple[str, str, str, str], ...]:
    """The declared checks as ``(pattern_id, check_id, kind, statistic)``, for the freeze digest."""
    return tuple(
        (check.pattern_id, check.check_id, check.kind.value, check.statistic) for check in CHECKS
    )


@dataclass(frozen=True, slots=True)
class Objective:
    """The target patterns, bound to the registry that declared them."""

    registry: PatternRegistry

    @property
    def pattern_ids(self) -> tuple[str, ...]:
        return target_pattern_ids(self.registry)

    @classmethod
    def from_registry(cls, registry: PatternRegistry) -> Objective:
        """Build the objective and refuse any registry whose targets differ from the declaration.

        A pattern added to the registry as a target, or one dropped, must break here: silently
        ignoring a target would make the objective a different question than the phase declares.
        """
        ids = target_pattern_ids(registry)
        declared = tuple(sorted({check.pattern_id for check in CHECKS}))
        if ids != declared:
            raise CalibrationObjectiveError(
                "the registry's target patterns do not match the declared checks: "
                f"registry {ids}, declared {declared}"
            )
        for check in CHECKS:
            pattern = registry.require(check.pattern_id)
            if check.signature_index >= len(pattern.signatures):
                raise CalibrationObjectiveError(
                    f"{check.check_id}: {check.pattern_id} has no signature {check.signature_index}"
                )
        return cls(registry)

    def reading_for(self, check: Check) -> str:
        """The pattern's own wording for the check, so a report never paraphrases the evidence."""
        pattern = self.registry.require(check.pattern_id)
        signature = pattern.signatures[check.signature_index]
        return f"record: {signature.expected} | scoring: {signature.scoring}"

    def checks_for(self, pattern_id: str) -> tuple[Check, ...]:
        return tuple(check for check in CHECKS if check.pattern_id == pattern_id)

    def score(
        self,
        events: pl.DataFrame,
        *,
        window: CalibrationWindow,
        county_nodes: tuple[str, ...] = (),
    ) -> TargetScores:
        """Score one run's calibration window; any other window is refused."""
        if window.role is not WindowRole.CALIBRATION:
            raise CalibrationObjectiveError(
                f"the objective may only read the calibration window, not {window.role.value}"
            )
        series = tick_series(events, window=window, county_nodes=county_nodes)
        yearly = yearly_series(series)
        outcomes: dict[str, list[CheckOutcome]] = {
            pattern_id: [] for pattern_id in self.pattern_ids
        }
        for check in CHECKS:
            value, satisfied = _evaluate(check, yearly=yearly, series=series)
            outcomes[check.pattern_id].append(
                CheckOutcome(
                    check_id=check.check_id,
                    pattern_id=check.pattern_id,
                    question=check.question,
                    value=value,
                    satisfied=satisfied,
                    reading=self.reading_for(check),
                )
            )
        return TargetScores(
            patterns=tuple(
                PatternScore(pattern_id, tuple(outcomes[pattern_id]))
                for pattern_id in self.pattern_ids
            )
        )


def _series_values(yearly: pl.DataFrame, column: str) -> list[float]:
    if column not in yearly.columns:
        raise CalibrationObjectiveError(f"yearly series has no column {column!r}")
    return [float(value) for value in yearly[column]]


def _evaluate(
    check: Check,
    *,
    yearly: pl.DataFrame,
    series: pl.DataFrame,
) -> tuple[float, bool]:
    if check.kind is CheckKind.RISES:
        values = _series_values(yearly, check.statistic)
        change = values[-1] - values[0]
        return change, change > 0.0
    if check.kind is CheckKind.FALLS:
        values = _series_values(yearly, check.statistic)
        change = values[-1] - values[0]
        return change, change < 0.0
    if check.kind is CheckKind.CO_MOVES_POSITIVE:
        left = _series_values(yearly, check.statistic)
        right = _series_values(yearly, check.against or "")
        rho = rank_correlation(left, right)
        return rho, rho > 0.0
    if check.kind is CheckKind.MOSTLY_BELOW:
        values = [float(value) for value in series[check.statistic]]
        below = sum(1 for value in values if value < (check.line or 0.0))
        share = below / len(values) if values else 0.0
        return share, share >= (check.share or 0.0)
    if check.kind is CheckKind.PRESENT_IN_CRISIS_YEARS:
        distress = _series_values(yearly, _distress_column())
        values = _series_values(yearly, check.statistic)
        ordered = sorted(distress)
        median = ordered[len(ordered) // 2]
        crisis = [value for value, level in zip(values, distress, strict=True) if level >= median]
        total = sum(crisis)
        return total, total > 0.0
    raise CalibrationObjectiveError(f"{check.check_id}: unknown check kind {check.kind!r}")
