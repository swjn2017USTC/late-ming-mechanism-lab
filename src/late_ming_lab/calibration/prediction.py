"""The prediction path: what the ensemble says about the windows it was never fitted to.

This module is deliberately separate from :mod:`late_ming_lab.calibration.targets`. That one holds
the patterns an objective may score; this one holds the patterns P08 *reserved* — the eight
``hold-out`` patterns — plus the machinery to run the ensemble forward into the hold-out and
extrapolation windows and record what it finds there.

The separation is the phase's central safeguard, and it is structural rather than documented:

- the objective refuses any window but the calibration window, and :class:`PredictiveChecks` refuses
  the calibration window, so neither can be used where the other belongs;
- the two check tables are disjoint by construction and a test asserts it both ways;
- the simulator never imports this module, so no calibration run can be scored against a hold-out
  pattern even by accident.

A hold-out pattern is scored with the same vocabulary as a target — a sign, a co-movement, an
ordering — because the record's claims are the same kind of claim. What differs is when the number
is allowed to be looked at: after the ensemble is frozen, never during the sampling.

Failure is a result here too. A pattern whose claim the ensemble contradicts is reported with the
value that contradicts it, and a pattern that cannot be checked at this scale is named as unchecked
with the reason rather than quietly dropped.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.calibration.ensemble import Ensemble
from late_ming_lab.calibration.simulator import SandboxSimulator
from late_ming_lab.calibration.summary_stats import (
    STATISTIC_NAMES,
    summary_statistics,
    tick_series,
    yearly_series,
)
from late_ming_lab.calibration.targets import (
    Check,
    CheckKind,
    CheckOutcome,
    PatternScore,
    TargetScores,
    rank_correlation,
)
from late_ming_lab.calibration.windows import (
    CalibrationWindow,
    WindowRole,
    calibration_window,
    extrapolation_window,
    hold_out_window,
    whole_run_window,
)
from late_ming_lab.evidence.cards import ParameterCards
from late_ming_lab.evidence.ledger import CalibrationRole, PatternRegistry

#: The precision a prediction check uses when it compares a share against an even spread. Half of a
#: pattern's window is the natural line: a claim of "concentrated in the worst years" is a claim
#: that more than half of the quantity falls in the tail the pattern names.
MAJORITY_SHARE: Final[float] = 0.5

#: The last years of the run the two late-concentration patterns name.
LATE_YEARS: Final[int] = 5

#: Where the warm-up ends. A pattern that says migration was used in the crisis years rather than in
#: the baseline is checked against this tick, not against an invented threshold.
WARMUP_TICKS: Final[int] = 24


@dataclass(frozen=True, slots=True)
class PredictionCheck(Check):
    """A check on a hold-out pattern, with the tail it names and how many years that tail is."""

    late_years: int | None = None
    after_tick: int | None = None


CHECKS: Final[tuple[PredictionCheck, ...]] = (
    PredictionCheck(
        "shock-peak-in-late-years",
        "chongzhen-drought-sequence",
        signature_index=0,
        kind=CheckKind.PEAK_IN_LAST_YEARS,
        statistic="shock_severity",
        late_years=LATE_YEARS,
        question="does the worst shock year fall in the last five years of the run?",
    ),
    PredictionCheck(
        "famine-events-concentrated-late",
        "famine-worst-years-1639-43",
        signature_index=0,
        kind=CheckKind.SHARE_IN_LAST_YEARS,
        statistic="destitute_cohorts",
        late_years=LATE_YEARS,
        share=MAJORITY_SHARE,
        question="is more than half of the destitute cohort-months in the last five years?",
    ),
    PredictionCheck(
        "largest-band-share-rises",
        "many-bands-then-consolidation",
        signature_index=0,
        kind=CheckKind.RISES,
        statistic="largest_band_share",
        question="does the largest band's share of armed men rise over the run?",
    ),
    PredictionCheck(
        "pay-arrears-accumulate",
        "pay-monetised-and-arrears",
        signature_index=0,
        kind=CheckKind.RISES,
        statistic="pay_arrears_tael",
        question="does the garrison arrears stock accumulate over the run?",
    ),
    PredictionCheck(
        "pay-shortfall-structural",
        "pay-monetised-and-arrears",
        signature_index=0,
        kind=CheckKind.MOSTLY_ABOVE,
        statistic="pay_shortfall_share",
        line=0.0,
        share=MAJORITY_SHARE,
        question="is some pay shortfall recorded in most months, rather than only in shock years?",
    ),
    PredictionCheck(
        "price-spike-peak-late",
        "price-spike-concentration",
        signature_index=0,
        kind=CheckKind.PEAK_IN_LAST_YEARS,
        statistic="price_cv",
        late_years=LATE_YEARS,
        question="does the worst price dispersion fall in the last five years of the run?",
    ),
    PredictionCheck(
        "receipts-short-of-quota",
        "quota-erosion-and-surcharge",
        signature_index=0,
        kind=CheckKind.MOSTLY_BELOW,
        statistic="receipts_over_quota",
        line=1.0,
        share=MAJORITY_SHARE,
        question="do receipts stay below the assessed quota in most months of the run?",
    ),
    PredictionCheck(
        "relief-coverage-falls-as-need-peaks",
        "relief-overwhelmed-in-worst-years",
        signature_index=0,
        kind=CheckKind.CO_MOVES_NEGATIVE,
        statistic="relief_coverage",
        against="unmet_ratio",
        question="does relief coverage fall in the years when need is highest?",
    ),
    PredictionCheck(
        "exits-in-crisis-years",
        "shaanxi-net-outflow",
        signature_index=0,
        kind=CheckKind.SHARE_AFTER_TICK,
        statistic="migration_exits",
        after_tick=WARMUP_TICKS,
        share=MAJORITY_SHARE,
        question="do the region's exits fall after the warm-up rather than in it?",
    ),
)

#: Hold-out patterns this scale cannot check, with the reason. They are reported as unchecked so a
#: reader can see the gap rather than reading silence as agreement.
UNCHECKED: Final[tuple[tuple[str, str], ...]] = ()


class PredictionError(ValueError):
    """Raised when the prediction path is pointed at a window that is not a prediction window."""


def predictive_pattern_ids(registry: PatternRegistry) -> tuple[str, ...]:
    """The ids of every pattern P08 reserved (`hold-out`), in a stable order."""
    return tuple(sorted(pattern.id for pattern in registry.by_role(CalibrationRole.HOLD_OUT)))


@dataclass(frozen=True, slots=True)
class PredictiveChecks:
    """The hold-out patterns' checks, bound to the registry that declared them."""

    registry: PatternRegistry

    @property
    def pattern_ids(self) -> tuple[str, ...]:
        return predictive_pattern_ids(self.registry)

    @classmethod
    def from_registry(cls, registry: PatternRegistry) -> PredictiveChecks:
        """Refuse a registry whose reserved patterns differ from the declared checks.

        Two directions are checked at once: every declared check must name a pattern the registry
        actually reserved, and the declared checks must cover every reserved pattern. Either failure
        means the prediction surface changed without the phase noticing.
        """
        reserved = predictive_pattern_ids(registry)
        declared = tuple(sorted({check.pattern_id for check in CHECKS} | {p for p, _ in UNCHECKED}))
        if reserved != declared:
            raise PredictionError(
                "the registry's held-out patterns do not match the declared prediction checks: "
                f"registry {reserved}, declared {declared}"
            )
        for check in CHECKS:
            pattern = registry.require(check.pattern_id)
            if check.signature_index >= len(pattern.signatures):
                raise PredictionError(
                    f"{check.check_id}: {check.pattern_id} has no signature {check.signature_index}"
                )
        return cls(registry)

    def reading_for(self, check: PredictionCheck) -> str:
        pattern = self.registry.require(check.pattern_id)
        signature = pattern.signatures[check.signature_index]
        return f"record: {signature.expected} | scoring: {signature.scoring}"

    def score(
        self,
        events: pl.DataFrame,
        *,
        window: CalibrationWindow,
        county_nodes: tuple[str, ...] = (),
    ) -> TargetScores:
        """Score one run in a prediction window; the calibration window is refused."""
        allowed = {WindowRole.HOLD_OUT, WindowRole.EXTRAPOLATION, WindowRole.WHOLE_RUN}
        if window.role not in allowed:
            raise PredictionError(
                "the prediction checks score the hold-out, the extrapolation and the whole run, "
                f"never {window.role.value}"
            )
        series = tick_series(events, window=window, county_nodes=county_nodes)
        yearly = yearly_series(series)
        outcomes: dict[str, list[CheckOutcome]] = {
            pattern_id: [] for pattern_id in self.pattern_ids
        }
        for check in CHECKS:
            value, satisfied = evaluate(check, yearly=yearly, series=series, window=window)
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


def evaluate(
    check: PredictionCheck,
    *,
    yearly: pl.DataFrame,
    series: pl.DataFrame,
    window: CalibrationWindow,
) -> tuple[float, bool]:
    """Measure one prediction check. The kinds are the objective's plus three the split needs."""
    if check.kind is CheckKind.PEAK_IN_LAST_YEARS:
        values = _yearly(yearly, check.statistic)
        years = [int(year) for year in yearly["year"]]
        years_in_window = check.late_years or 0
        peak_year = years[max(range(len(values)), key=lambda index: values[index])]
        threshold = years[-1] - years_in_window + 1
        return float(peak_year), peak_year >= threshold
    if check.kind is CheckKind.SHARE_IN_LAST_YEARS:
        values = _yearly(yearly, check.statistic)
        years = [int(year) for year in yearly["year"]]
        total = sum(values)
        threshold = years[-1] - (check.late_years or 0) + 1
        late = sum(value for value, year in zip(values, years, strict=True) if year >= threshold)
        share = late / total if total > 0.0 else 0.0
        return share, share >= (check.share or MAJORITY_SHARE)
    if check.kind is CheckKind.SHARE_AFTER_TICK:
        ticks = [int(tick) for tick in series["tick"]]
        values = [float(value) for value in series[check.statistic]]
        total = sum(values)
        after = sum(
            value
            for value, tick in zip(values, ticks, strict=True)
            if tick >= (check.after_tick or 0)
        )
        share = after / total if total > 0.0 else 0.0
        return share, share >= (check.share or MAJORITY_SHARE)
    if check.kind is CheckKind.MOSTLY_ABOVE:
        values = [float(value) for value in series[check.statistic]]
        above = sum(1 for value in values if value > (check.line or 0.0))
        share = above / len(values) if values else 0.0
        return share, share >= (check.share or MAJORITY_SHARE)
    if check.kind is CheckKind.CO_MOVES_NEGATIVE:
        left = _yearly(yearly, check.statistic)
        right = _yearly(yearly, check.against or "")
        rho = rank_correlation(left, right)
        return rho, rho < 0.0
    if check.kind is CheckKind.RISES:
        values = _yearly(yearly, check.statistic)
        change = values[-1] - values[0]
        return change, change > 0.0
    if check.kind is CheckKind.FALLS:
        values = _yearly(yearly, check.statistic)
        change = values[-1] - values[0]
        return change, change < 0.0
    if check.kind is CheckKind.MOSTLY_BELOW:
        values = [float(value) for value in series[check.statistic]]
        below = sum(1 for value in values if value < (check.line or 0.0))
        share = below / len(values) if values else 0.0
        return share, share >= (check.share or MAJORITY_SHARE)
    raise PredictionError(f"{check.check_id}: {check.kind.value} is not a prediction check kind")


def _yearly(yearly: pl.DataFrame, column: str) -> list[float]:
    if column not in yearly.columns:
        raise PredictionError(f"yearly series has no column {column!r}")
    return [float(value) for value in yearly[column]]


@dataclass(frozen=True, slots=True)
class WindowObservation:
    """One run in one window: its level statistics and the checks' outcomes."""

    window: WindowRole
    statistics: dict[str, float]
    scores: TargetScores


def observe(
    events: pl.DataFrame,
    *,
    window: CalibrationWindow,
    county_nodes: tuple[str, ...] = (),
    predictive: PredictiveChecks,
) -> WindowObservation:
    """Summarise one run in a prediction window, by the same code the objective uses."""
    if window.role is WindowRole.CALIBRATION:
        raise PredictionError("the calibration window is not a prediction window")
    return WindowObservation(
        window=window.role,
        statistics=summary_statistics(events, window=window, county_nodes=county_nodes),
        scores=predictive.score(events, window=window, county_nodes=county_nodes),
    )


def score_share(outcomes: Sequence[CheckOutcome]) -> float:
    """The share of a pattern's checks that were satisfied, for the prediction report."""
    if not outcomes:
        raise PredictionError("no checks to summarise")
    satisfied = sum(1 for outcome in outcomes if outcome.satisfied)
    return satisfied / len(outcomes)


#: The roles a prediction check may read. Declared here as well as used, so a report can state the
#: set it covered rather than listing whatever happened to run.
PREDICTION_WINDOW_ROLES: Final[tuple[WindowRole, ...]] = (
    WindowRole.HOLD_OUT,
    WindowRole.EXTRAPOLATION,
    WindowRole.WHOLE_RUN,
)

#: The columns of the predictive statistics table: the calibration window's statistics, carried per
#: draw and per window so a report never recomputes a number the artifact already holds.
STATISTICS_FILE: Final[str] = "predictive_statistics.parquet"
CHECKS_FILE: Final[str] = "predictive_checks.parquet"


@dataclass(frozen=True, slots=True)
class PosteriorPredictive:
    """What the ensemble does in every window of the run, per draw."""

    statistics: pl.DataFrame
    checks: pl.DataFrame


def prediction_windows() -> tuple[CalibrationWindow, ...]:
    """The windows the prediction path covers: the reserved ones, in split order."""
    return (calibration_window(), hold_out_window(), extrapolation_window(), whole_run_window())


def posterior_predictive(
    ensemble: Ensemble,
    cards: ParameterCards,
    registry: PatternRegistry,
    *,
    draw_limit: int | None = None,
) -> PosteriorPredictive:
    """Run every posterior draw forward and record its statistics and checks in every window.

    The calibration window is included on purpose: it is the reference the other three are read
    against, and it is scored by the objective that produced the ensemble. The other three are
    scored by :class:`PredictiveChecks`, which cannot read the calibration window at all. No number
    here enters an objective: the ensemble is already frozen by the time this runs.
    """
    simulator = SandboxSimulator(cards, registry)
    predictive = PredictiveChecks.from_registry(registry)
    objective = simulator.objective
    statistics_rows: list[dict[str, object]] = []
    check_rows: list[dict[str, object]] = []
    draws = ensemble.draws if draw_limit is None else ensemble.draws[:draw_limit]
    for index, draw in enumerate(draws):
        run = simulator.run(draw.parameter_map())
        for window in prediction_windows():
            values = summary_statistics(run.events, window=window, county_nodes=run.county_nodes)
            statistics_rows.append({"draw": index, "window": window.role.value, **values})
            if window.role is WindowRole.CALIBRATION:
                scores = objective.score(run.events, window=window, county_nodes=run.county_nodes)
                kind = "target"
            else:
                scores = predictive.score(run.events, window=window, county_nodes=run.county_nodes)
                kind = "reserved"
            for pattern in scores.patterns:
                for outcome in pattern.checks:
                    check_rows.append(
                        {
                            "draw": index,
                            "window": window.role.value,
                            "kind": kind,
                            "pattern_id": outcome.pattern_id,
                            "check_id": outcome.check_id,
                            "question": outcome.question,
                            "value": outcome.value,
                            "satisfied": outcome.satisfied,
                        }
                    )
    return PosteriorPredictive(
        statistics=pl.DataFrame(statistics_rows).select(["draw", "window", *STATISTIC_NAMES]),
        checks=pl.DataFrame(check_rows),
    )


def write_posterior_predictive(
    result: PosteriorPredictive, directory: str | Path
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Persist both predictive tables into a batch directory."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    result.statistics.write_parquet(target / STATISTICS_FILE)
    result.checks.write_parquet(target / CHECKS_FILE)
    return result.statistics, result.checks


def load_posterior_predictive(directory: str | Path) -> PosteriorPredictive:
    """Read both predictive tables back from a batch directory."""
    source = Path(directory)
    return PosteriorPredictive(
        statistics=pl.read_parquet(source / STATISTICS_FILE),
        checks=pl.read_parquet(source / CHECKS_FILE),
    )
