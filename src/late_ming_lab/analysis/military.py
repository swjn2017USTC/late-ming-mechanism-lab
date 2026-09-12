"""Military analysis: what the log says about garrisons, desertion and armed bands.

Everything here is read out of the event log — including the two quantities the phase exists to
watch: **how many armed groups there are**, and **how concentrated they are**. No measure is
recomputed from live actors, so the artifacts and the log can never disagree.

The measures are:

```text
garrison series        strength, pay arrears, morale and cohesion per tick, summed over garrisons
desertion rate         soldiers who left this month, over the strength that was there to leave
band series            number of bands, total size, largest band, and the largest band's share
band roster            one row per band per tick: size, cohesion, mobility, local support, arms
recruitment            adults levied into garrisons and into bands, and the unorganized pool
raid burden            grain and movable property taken from households, elites and the granary
```

Everything is a measurement. Nothing here scores a hypothesis, and nothing claims that the
observable the plan calls "organizational consolidation" has happened: the largest-band share is
evidence a reader may use, not a verdict this module reaches.
"""

from __future__ import annotations

import polars as pl

MILITARY_STATE_EVENT = "MILITARY_STATE"
BAND_STATE_EVENT = "BAND_STATE"
BAND_FORMED_EVENT = "BAND_FORMED"
BAND_DISSOLVED_EVENT = "BAND_DISSOLVED"
BAND_SPLIT_EVENT = "BAND_SPLIT"
BAND_MERGE_EVENT = "BAND_MERGE"
BAND_MOVE_EVENT = "BAND_MOVE"
BAND_RAID_EVENT = "BAND_RAID"
SUPPRESSION_EVENT = "SUPPRESSION"
DESERTION_EVENT = "DESERTERS_LEFT"
DESERTION_ROUTE_EVENT = "DESERTION_ROUTED"
DESERTER_POOL_EVENT = "DESERTER_POOL"
LEVY_EVENT = "RECRUIT_LEVY"
GRAIN_SEIZED_EVENT = "GRAIN_SEIZED"
ASSET_SEIZED_EVENT = "MOVABLE_ASSET_SEIZED"
ELITE_GRAIN_SEIZED_EVENT = "ELITE_GRAIN_SEIZED"
GRANARY_GRAIN_SEIZED_EVENT = "GRANARY_GRAIN_SEIZED"

GARRISON_FIELDS: tuple[str, ...] = (
    "troops",
    "grain_shi",
    "pay_arrears_tael",
    "pay_arrears_per_soldier_tael",
    "morale",
    "cohesion",
)

BAND_FIELDS: tuple[str, ...] = (
    "troops",
    "grain_shi",
    "arms_units",
    "arms_per_member",
    "mobility",
    "cohesion",
    "network",
)


class MilitaryAnalysisError(ValueError):
    """Raised when an event frame cannot be read as a military run."""


def _trigger_fields(frame: pl.DataFrame, fields: tuple[str, ...]) -> pl.DataFrame:
    if "trigger_json" not in frame.columns:
        raise MilitaryAnalysisError("event frame has no trigger_json column")
    return frame.with_columns(
        [
            pl.col("trigger_json")
            .str.json_path_match(f"$.{field}")
            .cast(pl.Float64, strict=False)
            .alias(field)
            for field in fields
        ]
    )


def garrison_series(events: pl.DataFrame) -> pl.DataFrame:
    """Per tick, summed over garrisons: strength, arrears, morale and cohesion."""
    states = events.filter(pl.col("event_type") == MILITARY_STATE_EVENT)
    if states.is_empty():
        raise MilitaryAnalysisError("event frame holds no MILITARY_STATE records")
    return (
        _trigger_fields(states, GARRISON_FIELDS)
        .group_by("tick")
        .agg(
            [
                pl.col("troops").sum().alias("garrison_troops"),
                pl.col("grain_shi").sum().alias("garrison_grain_shi"),
                pl.col("pay_arrears_tael").sum().alias("pay_arrears_tael"),
                pl.col("morale").mean().alias("mean_morale"),
                pl.col("cohesion").mean().alias("mean_cohesion"),
            ]
        )
        .sort("tick")
    )


def band_series(events: pl.DataFrame) -> pl.DataFrame:
    """Per tick: how many bands there are, how big they are, and how concentrated.

    ``largest_band_share`` is the share of all armed men in the model who belong to the single
    largest band — the plan's observable for organizational consolidation. It is 0 when there are
    no bands, and 0 is a measurement, not a missing value.
    """
    states = events.filter(pl.col("event_type") == BAND_STATE_EVENT)
    empty = pl.DataFrame(
        schema={
            "tick": pl.Int64(),
            "number_of_bands": pl.Int64(),
            "total_band_troops": pl.Float64(),
            "largest_band_troops": pl.Float64(),
            "largest_band_share": pl.Float64(),
            "mean_band_troops": pl.Float64(),
        }
    )
    if states.is_empty():
        return empty
    ticks = events.select(pl.col("tick").unique().sort()).with_columns(
        pl.lit(0, dtype=pl.Int64).alias("number_of_bands"),
        pl.lit(0.0).alias("total_band_troops"),
        pl.lit(0.0).alias("largest_band_troops"),
    )
    grouped = (
        _trigger_fields(states, BAND_FIELDS)
        .group_by("tick")
        .agg(
            [
                pl.len().alias("number_of_bands"),
                pl.col("troops").sum().alias("total_band_troops"),
                pl.col("troops").max().alias("largest_band_troops"),
            ]
        )
    )
    return (
        ticks.drop("number_of_bands", "total_band_troops", "largest_band_troops")
        .join(grouped, on="tick", how="left")
        .with_columns(
            [
                pl.col("number_of_bands").fill_null(0),
                pl.col("total_band_troops").fill_null(0.0),
                pl.col("largest_band_troops").fill_null(0.0),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("total_band_troops") > 0.0)
                .then(pl.col("largest_band_troops") / pl.col("total_band_troops"))
                .otherwise(0.0)
                .alias("largest_band_share"),
                pl.when(pl.col("number_of_bands") > 0)
                .then(pl.col("total_band_troops") / pl.col("number_of_bands"))
                .otherwise(0.0)
                .alias("mean_band_troops"),
            ]
        )
        .sort("tick")
    )


def band_roster(events: pl.DataFrame) -> pl.DataFrame:
    """One row per band per tick: the size distribution the plan asks for, not just its mean."""
    states = events.filter(pl.col("event_type") == BAND_STATE_EVENT)
    if states.is_empty():
        return pl.DataFrame(
            schema={
                "tick": pl.Int64(),
                "band_id": pl.String(),
                "node_id": pl.String(),
                "troops": pl.Float64(),
                "grain_shi": pl.Float64(),
                "arms_units": pl.Float64(),
                "arms_per_member": pl.Float64(),
                "mobility": pl.Float64(),
                "cohesion": pl.Float64(),
                "network": pl.Float64(),
            }
        )
    return (
        _trigger_fields(states, BAND_FIELDS)
        .select(
            [
                "tick",
                pl.col("agent_id").alias("band_id"),
                pl.col("region").alias("node_id"),
                *BAND_FIELDS,
            ]
        )
        .sort(["tick", "band_id"])
    )


def desertion_rate(events: pl.DataFrame) -> pl.DataFrame:
    """Per tick, summed over garrisons: soldiers who left, over the strength that could leave."""
    garrison = garrison_series(events)
    left = events.filter(pl.col("event_type") == DESERTION_EVENT)
    if left.is_empty():
        return garrison.select("tick").with_columns(
            pl.lit(0.0).alias("deserters_left"),
            pl.lit(0.0).alias("possible_garrison_troops"),
            pl.lit(0.0).alias("desertion_rate"),
        )
    counts = (
        _trigger_fields(left, ("troops_left",))
        .group_by("tick")
        .agg(pl.col("troops_left").sum().alias("deserters_left"))
    )
    return (
        garrison.select("tick", "garrison_troops")
        .with_columns(pl.col("garrison_troops").shift(1).fill_null(pl.col("garrison_troops")))
        .join(counts, on="tick", how="left")
        .with_columns(pl.col("deserters_left").fill_null(0.0))
        .with_columns(
            pl.when(pl.col("garrison_troops") > 0.0)
            .then(pl.col("deserters_left") / pl.col("garrison_troops"))
            .otherwise(0.0)
            .alias("desertion_rate")
        )
        .rename({"garrison_troops": "possible_garrison_troops"})
        .sort("tick")
    )


def recruitment_series(events: pl.DataFrame) -> pl.DataFrame:
    """Per tick: adults levied into garrisons and into bands, and the unorganized pool."""
    levies = events.filter(pl.col("event_type") == LEVY_EVENT)
    frame = (
        _trigger_fields(levies, ("troops_joined",))
        .with_columns(
            pl.when(pl.col("agent_id").str.starts_with("garrison"))
            .then(pl.col("troops_joined"))
            .otherwise(0.0)
            .alias("levied_to_garrisons"),
            pl.when(pl.col("agent_id").str.starts_with("band"))
            .then(pl.col("troops_joined"))
            .otherwise(0.0)
            .alias("levied_to_bands"),
        )
        .group_by("tick")
        .agg(
            [
                pl.col("levied_to_garrisons").sum(),
                pl.col("levied_to_bands").sum(),
            ]
        )
        if not levies.is_empty()
        else pl.DataFrame(schema={"tick": pl.Int64()})
    )
    pools = events.filter(pl.col("event_type") == DESERTER_POOL_EVENT)
    pool_frame = (
        _trigger_fields(pools, ("unorganized_deserters",))
        .group_by("tick")
        .agg(pl.col("unorganized_deserters").sum().alias("unorganized_deserters"))
        if not pools.is_empty()
        else pl.DataFrame(schema={"tick": pl.Int64()})
    )
    ticks = events.select(pl.col("tick").unique().sort())
    result = ticks
    for frame_to_join, columns in (
        (frame, ["levied_to_garrisons", "levied_to_bands"]),
        (pool_frame, ["unorganized_deserters"]),
    ):
        if columns[0] in frame_to_join.columns:
            result = result.join(frame_to_join, on="tick", how="left")
        else:
            result = result.with_columns(pl.lit(0.0).alias(column) for column in columns)
    return result.with_columns(
        [
            pl.col(column).fill_null(0.0)
            for column in ("levied_to_garrisons", "levied_to_bands", "unorganized_deserters")
        ]
    ).sort("tick")


def raid_burden(events: pl.DataFrame) -> pl.DataFrame:
    """Per tick: what armed bands took from households, elites and the granary.

    Every row is a seizure event, so the burden is measured on the victims' side of the ledger, not
    from the bands' own records.
    """
    cohort_grain = _trigger_fields(
        events.filter(pl.col("event_type") == GRAIN_SEIZED_EVENT), ("grain_seized_shi",)
    ).select("tick", pl.col("grain_seized_shi").alias("cohort_grain_seized_shi"))
    cohort_assets = _trigger_fields(
        events.filter(pl.col("event_type") == ASSET_SEIZED_EVENT), ("assets_seized_tael",)
    ).select("tick", pl.col("assets_seized_tael").alias("cohort_assets_seized_tael"))
    elite_grain = _trigger_fields(
        events.filter(pl.col("event_type") == ELITE_GRAIN_SEIZED_EVENT), ("grain_seized_shi",)
    ).select("tick", pl.col("grain_seized_shi").alias("elite_grain_seized_shi"))
    granary_grain = _trigger_fields(
        events.filter(pl.col("event_type") == GRANARY_GRAIN_SEIZED_EVENT), ("grain_seized_shi",)
    ).select("tick", pl.col("grain_seized_shi").alias("granary_grain_seized_shi"))
    columns = (
        ("cohort_grain_seized_shi", cohort_grain),
        ("cohort_assets_seized_tael", cohort_assets),
        ("elite_grain_seized_shi", elite_grain),
        ("granary_grain_seized_shi", granary_grain),
    )
    result = events.select(pl.col("tick").unique().sort())
    for name, frame in columns:
        if frame.is_empty():
            result = result.with_columns(pl.lit(0.0).alias(name))
        else:
            result = result.join(
                frame.group_by("tick").agg(pl.col(name).sum()), on="tick", how="left"
            ).with_columns(pl.col(name).fill_null(0.0))
    return result.sort("tick")


def military_totals(events: pl.DataFrame) -> dict[str, float]:
    """Run totals: end-state strength, churn, and the burden the bands imposed."""
    garrison = garrison_series(events)
    bands = band_series(events)
    rates = desertion_rate(events)
    burden = raid_burden(events)
    levies = recruitment_series(events)
    states = events.filter(pl.col("event_type") == BAND_STATE_EVENT)
    band_fields = _trigger_fields(states, BAND_FIELDS) if not states.is_empty() else pl.DataFrame()

    def total(frame: pl.DataFrame, column: str) -> float:
        if frame.is_empty() or column not in frame.columns:
            return 0.0
        return float(frame.select(pl.col(column).sum()).item() or 0.0)

    def last(frame: pl.DataFrame, column: str) -> float:
        if frame.is_empty() or column not in frame.columns:
            return 0.0
        value = frame.select(pl.col(column).last()).item()
        return float(value or 0.0)

    def end_mean(frame: pl.DataFrame, column: str) -> float:
        if frame.is_empty() or column not in frame.columns:
            return 0.0
        value = (
            frame.filter(pl.col("tick") == pl.col("tick").max())
            .select(pl.col(column).mean())
            .item()
        )
        return float(value or 0.0)

    return {
        "garrison_troops_end": last(garrison, "garrison_troops"),
        "garrison_troops_min": (
            0.0
            if garrison.is_empty()
            else float(garrison.select(pl.col("garrison_troops").min()).item() or 0.0)
        ),
        "pay_arrears_tael_end": last(garrison, "pay_arrears_tael"),
        "mean_desertion_rate": (
            0.0
            if rates.is_empty()
            else float(rates.select(pl.col("desertion_rate").mean()).item() or 0.0)
        ),
        "deserters_left_total": total(rates, "deserters_left"),
        "levied_to_garrisons_total": total(levies, "levied_to_garrisons"),
        "levied_to_bands_total": total(levies, "levied_to_bands"),
        "unorganized_deserters_end": last(levies, "unorganized_deserters"),
        "bands_end": (
            0.0
            if bands.is_empty()
            else float(bands.select(pl.col("number_of_bands").last()).item() or 0.0)
        ),
        "band_troops_end": last(bands, "total_band_troops"),
        "largest_band_end": last(bands, "largest_band_troops"),
        "largest_band_share_end": last(bands, "largest_band_share"),
        "largest_band_share_max": (
            0.0
            if bands.is_empty()
            else float(bands.select(pl.col("largest_band_share").max()).item() or 0.0)
        ),
        "bands_formed_total": float(
            events.filter(pl.col("event_type") == BAND_FORMED_EVENT).height
        ),
        "bands_dissolved_total": float(
            events.filter(pl.col("event_type") == BAND_DISSOLVED_EVENT).height
        ),
        "band_splits_total": float(events.filter(pl.col("event_type") == BAND_SPLIT_EVENT).height),
        "band_merges_total": float(events.filter(pl.col("event_type") == BAND_MERGE_EVENT).height),
        "band_moves_total": float(events.filter(pl.col("event_type") == BAND_MOVE_EVENT).height),
        "suppressions_total": float(
            events.filter(pl.col("event_type") == SUPPRESSION_EVENT).height
        ),
        "band_raids_total": float(events.filter(pl.col("event_type") == BAND_RAID_EVENT).height),
        "mean_band_cohesion_end": end_mean(band_fields, "cohesion"),
        "mean_band_network_end": end_mean(band_fields, "network"),
        "cohort_grain_seized_total": total(burden, "cohort_grain_seized_shi"),
        "cohort_assets_seized_total": total(burden, "cohort_assets_seized_tael"),
        "elite_grain_seized_total": total(burden, "elite_grain_seized_shi"),
        "granary_grain_seized_total": total(burden, "granary_grain_seized_shi"),
    }
