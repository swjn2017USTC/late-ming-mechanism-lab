"""The observables a mortality rule would consume, recomputed from a run's own log.

This is the half of M006 that can be delivered without inventing evidence: the model already
records, for every cohort and month, whether its consumption reached its subsistence floor, and
how large the shortfall was. A rule that turned a sustained shortfall into deaths would read
exactly these series, so the phase records them, checks that they are computable from a stored
run, and reports the distribution a rule would have to be calibrated against.

Nothing here decides anything. The gap is not the absence of these numbers — they are all present —
but the absence of anything outside the model to calibrate a death rate against.
"""

from __future__ import annotations

from typing import Final

import polars as pl

#: The consumption event the shortfall is read from.
CONSUMPTION_EVENT: Final[str] = "CONSUMPTION"

#: One year of months, the rolling window the eligibility rules already use.
ROLLING_MONTHS: Final[int] = 12


class MortalityObservableError(ValueError):
    """Raised when a run's log cannot support the observables at all."""


def _number(value: object) -> float:
    """A polars aggregate as a float; anything else is an error rather than a coerced zero."""
    if isinstance(value, (int, float)):
        return float(value)
    raise MortalityObservableError(f"expected a number from the log, got {type(value).__name__}")


def _trigger(events: pl.DataFrame, field: str) -> pl.Series:
    return events["trigger_json"].str.json_path_match(f"$.{field}").cast(pl.Float64, strict=False)


def shortfall_series(events: pl.DataFrame) -> pl.DataFrame:
    """Per cohort and tick: the need, the unmet part, and whether the floor was missed.

    A month with no `CONSUMPTION` row for a cohort is a month the cohort did not consume at all —
    which is not the same as consuming nothing — so the series is built on the ticks the log
    covers and the caller decides what a gap means. Refusing to invent rows here is what keeps the
    observable honest.
    """
    consumption = events.filter(pl.col("event_type") == CONSUMPTION_EVENT)
    if consumption.is_empty():
        raise MortalityObservableError(
            f"no {CONSUMPTION_EVENT} rows: the log cannot support a shortfall observable"
        )
    scaled = consumption.with_columns(
        [
            _trigger(consumption, "need_shi").alias("need_shi"),
            _trigger(consumption, "unmet_shi").alias("unmet_shi"),
        ]
    ).select(["tick", "agent_id", "region", "need_shi", "unmet_shi"])
    return scaled.with_columns(
        (pl.col("unmet_shi") > 0.0).alias("below_floor"),
        pl.when(pl.col("need_shi") > 0.0)
        .then(pl.col("unmet_shi") / pl.col("need_shi"))
        .otherwise(0.0)
        .alias("unmet_ratio"),
    ).sort(["agent_id", "tick"])


def sustained_shortfalls(events: pl.DataFrame, *, months: int = ROLLING_MONTHS) -> pl.DataFrame:
    """Per cohort: the longest run of months below the floor, and the rolling unmet ratio.

    The two quantities a mortality rule would be handed. ``longest_run_below_floor`` is a duration,
    not a rate: it says how long the model keeps a cohort under the floor, which is the thing a
    famine rule would have to outlast, and the phase reports it rather than turning it into deaths.
    """
    if months < 1:
        raise MortalityObservableError("a rolling window is at least one month")
    series = shortfall_series(events)
    rows: list[dict[str, object]] = []
    for cohort_id, group in series.group_by("agent_id", maintain_order=True):
        frame = group.sort("tick")
        flags = frame["below_floor"].to_list()
        longest = 0
        current = 0
        for flag in flags:
            current = current + 1 if flag else 0
            longest = max(longest, current)
        tail = frame.tail(months)
        rows.append(
            {
                "cohort_id": str(cohort_id[0]) if isinstance(cohort_id, tuple) else str(cohort_id),
                "node_id": str(frame["region"][0]),
                "months_observed": frame.height,
                "months_below_floor": int(sum(1 for flag in flags if flag)),
                "longest_run_below_floor": longest,
                "unmet_ratio_rolling": _number(tail["unmet_ratio"].mean() or 0.0),
                "last_shortfall_shi": _number(frame["unmet_shi"][-1] or 0.0),
            }
        )
    return pl.DataFrame(rows).sort("cohort_id")


def mortality_gap_summary(
    events: pl.DataFrame, *, months: int = ROLLING_MONTHS
) -> dict[str, float]:
    """The numbers the gap report prints: what a rule would see, and what nobody can calibrate."""
    frame = sustained_shortfalls(events, months=months)
    if frame.is_empty():
        raise MortalityObservableError("no cohort recorded a consumption row")
    return {
        "cohorts_observed": float(frame.height),
        "cohorts_with_a_shortfall": float((frame["months_below_floor"] > 0).sum()),
        "cohorts_short_in_most_months": float(
            (frame["months_below_floor"] > frame["months_observed"] / 2).sum()
        ),
        "longest_run_below_floor_max": _number(frame["longest_run_below_floor"].max() or 0),
        "longest_run_below_floor_median": _number(frame["longest_run_below_floor"].median() or 0),
        "unmet_ratio_rolling_max": _number(frame["unmet_ratio_rolling"].max() or 0.0),
        "months_observed": _number(frame["months_observed"].max() or 0),
        "deaths": 0.0,
    }


__all__ = [
    "CONSUMPTION_EVENT",
    "ROLLING_MONTHS",
    "MortalityObservableError",
    "mortality_gap_summary",
    "shortfall_series",
    "sustained_shortfalls",
]
