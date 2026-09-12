"""Governance failure indicators: measured quantities, each against a declared reading line.

The plan forbids collapsing state capacity into one scalar, and the same discipline applies here.
These are **not** an index and are not summed into a "crisis level": each row is one measured
quantity, the threshold a reader declared for it, whether it crossed, and the direction of travel.
The count of crossed indicators is reported as a count of rows, never as a score.

The indicators are:

```text
fiscal_receipts     receipts against the assessed quota - is the county collecting what it demands?
tax_base            the land the county can see, contracting or not
tax_arrears         the arrears stock, growing or not
military_pay        the share of the month's pay obligation that does not arrive
armed_groups        armed men against the adult population, and the largest band's share of them
out_migration       households leaving the region against the households that started here
subsistence         the share of the subsistence floor that goes unmet
```

Every threshold is a parameter (`GovernanceIndicatorParameters`, grade ``S``) and every measurement
is read from the event log, so a reader who disagrees with a line can move it without touching the
model and see exactly what changes.
"""

from __future__ import annotations

import polars as pl

from late_ming_lab.analysis.fiscal import county_fiscal_series
from late_ming_lab.analysis.migration import migration_flows
from late_ming_lab.analysis.military import (
    BAND_STATE_EVENT,
    MILITARY_STATE_EVENT,
    garrison_series,
)
from late_ming_lab.analysis.scalars import largest, last, mean, total
from late_ming_lab.evidence.parameters import GovernanceIndicatorParameters


class GovernanceAnalysisError(ValueError):
    """Raised when a run's log cannot support the governance indicators."""


def _trigger_column(frame: pl.DataFrame, field: str) -> pl.Series:
    """One numeric trigger value out of the event log's JSON payload."""
    return frame["trigger_json"].str.json_path_match(f"$.{field}").cast(pl.Float64, strict=False)


def _subsistence_share(events: pl.DataFrame) -> float:
    """Share of the subsistence floor left unmet, over the whole run."""
    consumption = events.filter(pl.col("event_type") == "CONSUMPTION")
    if consumption.is_empty():
        return 0.0
    scaled = consumption.with_columns(
        [
            _trigger_column(consumption, "need_shi").alias("need_shi"),
            _trigger_column(consumption, "unmet_shi").alias("unmet_shi"),
        ]
    )
    need = total(scaled, "need_shi")
    unmet = total(scaled, "unmet_shi")
    return unmet / need if need > 0.0 else 0.0


def _armed_share(events: pl.DataFrame, population_adults: float) -> tuple[float, float]:
    """Armed men as a share of adults, and the largest band's share of all armed men."""
    states = events.filter(pl.col("event_type") == BAND_STATE_EVENT)
    if states.is_empty() or population_adults <= 0.0:
        return 0.0, 0.0
    by_tick = (
        states.with_columns(_trigger_column(states, "troops").alias("troops"))
        .group_by("tick")
        .agg(
            [
                pl.col("troops").sum().alias("band_troops"),
                pl.col("troops").max().alias("largest_band"),
            ]
        )
    )
    peak = largest(by_tick, "band_troops")
    biggest = largest(by_tick, "largest_band")
    share_of_adults = peak / population_adults
    largest_share = biggest / peak if peak > 0.0 else 0.0
    return share_of_adults, largest_share


def governance_indicators(
    events: pl.DataFrame,
    *,
    thresholds: GovernanceIndicatorParameters,
    population_adults: float,
    starting_households: float,
) -> pl.DataFrame:
    """One row per indicator: the measurement, its line, whether it crossed, and the trend."""
    fiscal = county_fiscal_series(events)
    receipts = total(fiscal, "receipts_tael")
    quota = total(fiscal, "quota_tael")
    # Both ends of the comparison are aggregates over the same counties: the sum of each county's
    # first observation against the sum of its last. A min-of-series against a sum-of-finals would
    # measure nothing but the aggregation mistake.
    bases = (
        fiscal.sort(["region", "tick"])
        .group_by("region")
        .agg(
            [
                pl.col("taxable_land_mu").first().alias("base_start"),
                pl.col("taxable_land_mu").last().alias("base_end"),
            ]
        )
    )
    base_start = total(bases, "base_start")
    base_end = total(bases, "base_end")
    arrears = total(fiscal, "arrears_delta_tael")
    months = float(fiscal["tick"].n_unique() or 1)

    standing = events.filter(pl.col("event_type") == "MILITARY_STANDING")
    pay_shortfall = mean(
        standing.with_columns(
            _trigger_column(standing, "pay_shortfall_share").alias("pay_shortfall_share")
        ),
        "pay_shortfall_share",
    )

    annualised_arrears = arrears / months
    receipts_share = receipts / quota if quota > 0.0 else 0.0
    base_contraction = (base_start - base_end) / base_start if base_start > 0.0 else 0.0
    armed_share, largest_share = _armed_share(events, population_adults)
    flows = migration_flows(events)
    exited = total(flows, "households_exited")
    out_migration_share = exited / starting_households if starting_households > 0.0 else 0.0
    unmet_share = _subsistence_share(events)

    rows = [
        {
            "indicator": "fiscal_receipts",
            "measure": receipts_share,
            "threshold": thresholds.receipts_below_quota_share,
            "direction": "below-is-failure",
        },
        {
            "indicator": "tax_base_contraction",
            "measure": base_contraction,
            "threshold": thresholds.tax_base_contraction_share,
            "direction": "above-is-failure",
        },
        {
            "indicator": "tax_arrears_growth",
            "measure": annualised_arrears,
            "threshold": thresholds.arrears_growth_tael_per_month,
            "direction": "above-is-failure",
        },
        {
            "indicator": "military_pay_shortfall",
            "measure": pay_shortfall,
            "threshold": thresholds.pay_shortfall_share,
            "direction": "above-is-failure",
        },
        {
            "indicator": "armed_share_of_adults",
            "measure": armed_share,
            "threshold": thresholds.band_troops_share_of_adults,
            "direction": "above-is-failure",
        },
        {
            "indicator": "largest_band_share",
            "measure": largest_share,
            "threshold": thresholds.largest_band_share,
            "direction": "above-is-failure",
        },
        {
            "indicator": "out_migration",
            "measure": out_migration_share,
            "threshold": thresholds.out_migration_share_of_households,
            "direction": "above-is-failure",
        },
        {
            "indicator": "subsistence_shortfall",
            "measure": unmet_share,
            "threshold": thresholds.unmet_share_of_need,
            "direction": "above-is-failure",
        },
    ]
    frame = pl.DataFrame(rows)
    crossed = (
        pl.when(pl.col("direction") == "below-is-failure")
        .then(pl.col("measure") < pl.col("threshold"))
        .otherwise(pl.col("measure") > pl.col("threshold"))
    )
    return frame.with_columns(
        [
            crossed.cast(pl.Boolean).alias("crossed"),
            (pl.col("measure") - pl.col("threshold")).alias("distance_from_threshold"),
        ]
    )


def governance_summary(indicators: pl.DataFrame) -> dict[str, float]:
    """The count of crossed indicators and the two fiscal quantities behind them."""
    if indicators.is_empty():
        raise GovernanceAnalysisError("empty indicator frame")
    return {
        "indicators_crossed": float(indicators.filter(pl.col("crossed")).height),
        "indicators_reported": float(indicators.height),
    }


def governance_series(events: pl.DataFrame, *, every: int = 12) -> pl.DataFrame:
    """The same indicators sampled through the run, so a reader can see when they moved.

    Sampled rather than monthly because the point is the direction of travel: a run that crosses a
    line in 1629 and stays across it is a different story from one that crosses it in 1643.
    """
    if every < 1:
        raise GovernanceAnalysisError("sampling interval must be at least one tick")
    ticks = sorted(events["tick"].unique().to_list())
    sampled = [tick for index, tick in enumerate(ticks) if index % every == 0]
    frames = []
    for index, tick in enumerate(sampled):
        window = events.filter(pl.col("tick") <= tick)
        garrison = garrison_series(window)
        frames.append(
            {
                "tick": tick,
                "garrison_troops": last(garrison, "garrison_troops"),
                "pay_arrears_tael": last(garrison, "pay_arrears_tael"),
                "military_states": float(
                    window.filter(pl.col("event_type") == MILITARY_STATE_EVENT).height
                ),
                "bands": float(window.filter(pl.col("event_type") == BAND_STATE_EVENT).height),
                "sample_index": index,
            }
        )
    return pl.DataFrame(frames)
