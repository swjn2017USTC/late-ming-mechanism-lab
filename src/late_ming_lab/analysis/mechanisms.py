"""Mechanism verdicts: does a run show one of the patterns, and how strongly?

P13 will name mechanism cards; P12 has to do something narrower and more checkable: decide, for
one run at one tick horizon, whether three named patterns are *there*. Each reading is a declared
rule over the event log, dimensionless so runs of different scales compare, and paired with a
strength so "present" is not a coin flip. A mechanism is not a number: it is a claim with a
falsifier, so each reading states the falsifier it looked for in the `falsifier` field.

```text
fiscal-extraction-inversion   the county works harder while realising less of what it assesses
fiscal-military-ratchet       the pay-arrears stock accumulates and never clears
armed-band-consolidation      fewer bands, with one of them holding a growing share
```

None of these is a historical finding. They are patterns the model's own mechanisms can produce, and
P12's question is which of them survive a change of *decision policy* — the whole point of measuring
them this way rather than reading one run's story.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Final

import polars as pl

from late_ming_lab.calibration.summary_stats import scalar

#: The event types the readings consume, declared here because the log's contract is the names.
EXTRACTION_EVENT: Final[str] = "EXTRACTION_DECISION"
ASSESSMENT_EVENT: Final[str] = "TAX_ASSESSMENT"
RECEIPT_EVENT: Final[str] = "TAX_RECEIPT"
COUNTY_STATE_EVENT: Final[str] = "COUNTY_STATE"
MILITARY_STATE_EVENT: Final[str] = "MILITARY_STATE"
BAND_STATE_EVENT: Final[str] = "BAND_STATE"

#: The mechanism ids, in the order the robustness matrix reports them.
MECHANISM_IDS: Final[tuple[str, ...]] = (
    "fiscal-extraction-inversion",
    "fiscal-military-ratchet",
    "armed-band-consolidation",
)


class MechanismError(ValueError):
    """Raised when a run's log cannot be read for a mechanism it should contain."""


@dataclass(frozen=True, slots=True)
class MechanismReading:
    """One pattern's verdict in one run: whether it is there, how strongly, and on what evidence."""

    mechanism: str
    present: bool
    strength: float
    detail: tuple[tuple[str, float], ...]
    reading: str
    falsifier: str

    def detail_map(self) -> dict[str, float]:
        return dict(self.detail)


def _trigger(frame: pl.DataFrame, field: str) -> pl.Series:
    return frame["trigger_json"].str.json_path_match(f"$.{field}").cast(pl.Float64, strict=False)


def _per_tick_sum(frame: pl.DataFrame, field: str, name: str) -> pl.DataFrame:
    if frame.is_empty():
        return pl.DataFrame(
            {"tick": pl.Series([], dtype=pl.Int64), name: pl.Series([], dtype=pl.Float64)}
        )
    return (
        frame.with_columns(_trigger(frame, field).alias(name))
        .group_by("tick")
        .agg(pl.col(name).sum())
        .sort("tick")
    )


def _halves(frame: pl.DataFrame, field: str) -> tuple[float, float]:
    """The mean of a per-tick reading over the first and the second half of a run."""
    totals = _per_tick_sum(frame, field, "_value")
    if totals.is_empty():
        return 0.0, 0.0
    values = [float(value) for value in totals["_value"]]
    middle = len(values) // 2
    first = values[:middle] or values
    second = values[middle:] or values
    return sum(first) / len(first), sum(second) / len(second)


def _ratio_halves(events: pl.DataFrame) -> tuple[float, float]:
    """Receipts over the assessed quota, first half against second half."""
    receipts = _per_tick_sum(
        events.filter(pl.col("event_type") == RECEIPT_EVENT), "receipts_tael", "r"
    )
    quota = _per_tick_sum(
        events.filter(pl.col("event_type") == ASSESSMENT_EVENT), "quota_tael", "q"
    )
    if receipts.is_empty() or quota.is_empty():
        return 0.0, 0.0
    joined = receipts.join(quota, on="tick", how="inner").sort("tick")
    if joined.is_empty():
        return 0.0, 0.0
    receipts_column = [float(value) for value in joined["r"]]
    quota_column = [float(value) for value in joined["q"]]
    middle = len(receipts_column) // 2
    slices = (
        (receipts_column[:middle] or receipts_column, quota_column[:middle] or quota_column),
        (receipts_column[middle:] or receipts_column, quota_column[middle:] or quota_column),
    )

    def ratio(receipts_chunk: list[float], quota_chunk: list[float]) -> float:
        total_quota = sum(quota_chunk)
        return sum(receipts_chunk) / total_quota if total_quota > 0.0 else 0.0

    return ratio(*slices[0]), ratio(*slices[1])


def extraction_inversion(events: pl.DataFrame) -> MechanismReading:
    """The county works harder while realising less: pressure up, receipts over quota down.

    The falsifier is the ordinary case — effort and receipts moving the same way, or effort falling.
    """
    extraction = events.filter(pl.col("event_type") == EXTRACTION_EVENT)
    if extraction.is_empty():
        raise MechanismError("the log holds no extraction decisions to read")
    effort_first, effort_second = _halves(extraction, "collection_effort")
    pressure_first, pressure_second = _halves(extraction, "pressure")
    ratio_first, ratio_second = _ratio_halves(events)
    harder = effort_second > effort_first or pressure_second > pressure_first
    less = ratio_second < ratio_first
    present = harder and less
    strength = (effort_second - effort_first) * (ratio_first - ratio_second) if present else 0.0
    return MechanismReading(
        mechanism=MECHANISM_IDS[0],
        present=present,
        strength=strength,
        detail=(
            ("effort_first_half", effort_first),
            ("effort_second_half", effort_second),
            ("pressure_first_half", pressure_first),
            ("pressure_second_half", pressure_second),
            ("receipts_over_quota_first_half", ratio_first),
            ("receipts_over_quota_second_half", ratio_second),
        ),
        reading=(
            f"effort {effort_first:.3f} to {effort_second:.3f} while receipts over quota moved "
            f"{ratio_first:.3f} to {ratio_second:.3f}"
        ),
        falsifier="effort and receipts over quota moving the same way, or effort falling",
    )


def fiscal_military_ratchet(events: pl.DataFrame) -> MechanismReading:
    """The pay-arrears stock accumulates and never clears.

    The falsifier is the ordinary case of a working treasury: at least one month where the stock
    falls, or a stock that ends where it started.
    """
    states = events.filter(pl.col("event_type") == MILITARY_STATE_EVENT)
    if states.is_empty():
        raise MechanismError("the log holds no military state to read")
    per_tick = _per_tick_sum(states, "pay_arrears_tael", "arrears")
    if per_tick.is_empty():
        raise MechanismError("the military state carries no pay arrears")
    values = [float(value) for value in per_tick["arrears"]]
    start, end = values[0], values[-1]
    declines = sum(1 for before, after in pairwise(values) if after < before)
    assessment = scalar(
        _per_tick_sum(events.filter(pl.col("event_type") == ASSESSMENT_EVENT), "quota_tael", "q")[
            "q"
        ].sum()
    )
    present = end > start and declines == 0
    strength = (end - start) / assessment if assessment > 0.0 else 0.0
    return MechanismReading(
        mechanism=MECHANISM_IDS[1],
        present=present,
        strength=strength,
        detail=(
            ("arrears_start_tael", start),
            ("arrears_end_tael", end),
            ("months_with_a_decline", float(declines)),
            ("assessment_total_tael", assessment),
        ),
        reading=(
            f"arrears {start:,.0f} to {end:,.0f} tael with {declines} month(s) of decline, "
            f"against {assessment:,.0f} assessed"
        ),
        falsifier="at least one month where the arrears stock falls, or a stock that ends flat",
    )


def armed_band_consolidation(events: pl.DataFrame) -> MechanismReading:
    """Fewer bands, with one of them holding a growing share of all armed men.

    The falsifier is a band sector that stays fragmented, or a largest share that falls.
    """
    states = events.filter(pl.col("event_type") == BAND_STATE_EVENT)
    if states.is_empty():
        raise MechanismError("the log holds no band state to read")
    per_tick = (
        states.with_columns(_trigger(states, "troops").alias("troops"))
        .group_by("tick", "agent_id")
        .agg(pl.col("troops").last())
        .group_by("tick")
        .agg(
            [
                pl.len().alias("bands"),
                pl.col("troops").sum().alias("total"),
                pl.col("troops").max().alias("largest"),
            ]
        )
        .sort("tick")
    )
    if per_tick.is_empty():
        raise MechanismError("the band state carries no ticks")

    def tick_reading(position: int) -> tuple[float, float]:
        bands = float(per_tick["bands"][position])
        total = float(per_tick["total"][position])
        largest = float(per_tick["largest"][position])
        return bands, (largest / total if total > 0.0 else 0.0)

    bands_first, share_first = tick_reading(0)
    bands_last, share_last = tick_reading(-1)
    present = share_last > share_first and bands_last <= bands_first
    return MechanismReading(
        mechanism=MECHANISM_IDS[2],
        present=present,
        strength=share_last - share_first,
        detail=(
            ("bands_first_tick", bands_first),
            ("bands_last_tick", bands_last),
            ("largest_share_first_tick", share_first),
            ("largest_share_last_tick", share_last),
        ),
        reading=(
            f"{bands_first:.0f} bands to {bands_last:.0f}, largest share "
            f"{share_first:.3f} to {share_last:.3f}"
        ),
        falsifier="a band sector that stays fragmented, or a largest share that falls",
    )


def mechanism_readings(events: pl.DataFrame) -> tuple[MechanismReading, ...]:
    """Every declared mechanism's verdict for one run, in the matrix's row order."""
    return (
        extraction_inversion(events),
        fiscal_military_ratchet(events),
        armed_band_consolidation(events),
    )
