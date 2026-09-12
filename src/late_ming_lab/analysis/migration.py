"""Migration analysis: who left, where they went, and what the region lost.

Read from the log, like every other analysis module. The measures are physical — households,
adults, grain, silver and land that moved — and the two balances that matter are stated explicitly:

```text
internal      households that left one modelled node and arrived at another
exit          households that left the modelled region altogether, with what they carried
temporary     adults away for a term, and what their absence cost in silver and bought in food
land          mu abandoned at the origin, which no destination receives
```

The ``internal + exit == departure`` identity is what makes the migration numbers trustworthy: a
departure event that is not matched by an arrival or an exit is a leak, and the tests assert there
is none.
"""

from __future__ import annotations

import polars as pl

DEPARTURE_EVENT = "MIGRATION_DEPARTURE"
ARRIVAL_EVENT = "MIGRATION_ARRIVAL"
TRANSIT_EVENT = "MIGRATION_TRANSIT"
SETTLEMENT_EVENT = "MIGRATION_SETTLEMENT"
EXIT_EVENT = "MIGRATION_EXIT"
TEMPORARY_EVENT = "TEMPORARY_MIGRATION"
RETURN_EVENT = "TEMPORARY_RETURN"
MIGRANT_CONSUMPTION_EVENT = "MIGRANT_CONSUMPTION"

PERMANENT_FIELDS: tuple[str, ...] = (
    "households_migrated",
    "adults_migrated",
    "grain_carried_shi",
    "silver_carried_tael",
    "assets_carried_tael",
    "land_abandoned_mu",
)
EXIT_FIELDS: tuple[str, ...] = (
    "households_exited",
    "adults_exited",
    "grain_carried_shi",
    "silver_carried_tael",
    "assets_carried_tael",
)
TEMPORARY_FIELDS: tuple[str, ...] = (
    "adults_away",
    "travel_cost_tael",
    "origin_price_tael_per_shi",
    "destination_price_tael_per_shi",
)


class MigrationAnalysisError(ValueError):
    """Raised when an event frame cannot be read as a migration run."""


def _with_fields(
    events: pl.DataFrame, types: tuple[str, ...], fields: tuple[str, ...]
) -> pl.DataFrame:
    if "trigger_json" not in events.columns:
        raise MigrationAnalysisError("event frame has no trigger_json column")
    frame = events.filter(pl.col("event_type").is_in(list(types)))
    return frame.with_columns(
        [
            pl.col("trigger_json")
            .str.json_path_match(f"$.{field}")
            .cast(pl.Float64, strict=False)
            .alias(field)
            for field in fields
        ]
    )


def migration_flows(events: pl.DataFrame) -> pl.DataFrame:
    """Per tick: households and adults that left, arrived, or left the region."""
    departures = _with_fields(
        events, (DEPARTURE_EVENT,), ("households_migrated", "adults_migrated", "land_abandoned_mu")
    ).filter(pl.col("outcome").str.starts_with("migrated-to"))
    arrivals = _with_fields(
        events, (ARRIVAL_EVENT,), ("households_arrived", "adults_arrived")
    ).filter(pl.col("outcome").str.starts_with("arrived-from"))
    exits = _with_fields(events, (EXIT_EVENT,), ("households_exited", "adults_exited"))

    ticks = events.select(pl.col("tick").unique().sort())
    frame = ticks
    for name, source, column in (
        ("households_departed", departures, "households_migrated"),
        ("adults_departed", departures, "adults_migrated"),
        ("land_abandoned_mu", departures, "land_abandoned_mu"),
        ("households_arrived", arrivals, "households_arrived"),
        ("adults_arrived", arrivals, "adults_arrived"),
        ("households_exited", exits, "households_exited"),
        ("adults_exited", exits, "adults_exited"),
    ):
        totals = (
            source.group_by("tick").agg(pl.col(column).sum().alias(name))
            if not source.is_empty()
            else pl.DataFrame(schema={"tick": pl.Int64(), name: pl.Float64()})
        )
        if name in totals.columns:
            frame = frame.join(totals, on="tick", how="left")
        else:
            frame = frame.with_columns(pl.lit(0.0).alias(name))
    return frame.with_columns(
        [pl.col(name).fill_null(0.0) for name in frame.columns if name != "tick"]
    ).sort("tick")


def temporary_migration(events: pl.DataFrame) -> pl.DataFrame:
    """Per tick: adults away, the price gap they left for, and what the absence cost and bought."""
    away = (
        _with_fields(events, (TEMPORARY_EVENT,), TEMPORARY_FIELDS)
        .filter(pl.col("adults_away").is_not_null())
        .group_by("tick")
        .agg(
            [
                pl.col("adults_away").sum().alias("adults_away"),
                pl.col("travel_cost_tael").sum().alias("travel_cost_tael"),
                pl.col("origin_price_tael_per_shi").mean().alias("mean_origin_price"),
                pl.col("destination_price_tael_per_shi").mean().alias("mean_destination_price"),
                pl.len().alias("groups_departed"),
            ]
        )
    )
    consumed = (
        _with_fields(events, (MIGRANT_CONSUMPTION_EVENT,), ("grain_eaten_shi", "silver_spent_tael"))
        .filter(pl.col("grain_eaten_shi").is_not_null())
        .group_by("tick")
        .agg(
            [
                pl.col("grain_eaten_shi").sum().alias("grain_eaten_by_migrants_shi"),
                pl.col("silver_spent_tael").sum().alias("silver_spent_by_migrants_tael"),
            ]
        )
    )
    returned = (
        _with_fields(events, (RETURN_EVENT,), ("adults_returned", "months_away"))
        .group_by("tick")
        .agg(
            [
                pl.col("adults_returned").sum().alias("adults_returned"),
                pl.col("months_away").mean().alias("mean_months_away"),
            ]
        )
        if not events.filter(pl.col("event_type") == RETURN_EVENT).is_empty()
        else pl.DataFrame(schema={"tick": pl.Int64()})
    )
    ticks = events.select(pl.col("tick").unique().sort())
    frame = ticks
    for joinable, columns in (
        (away, ["adults_away", "travel_cost_tael", "groups_departed"]),
        (consumed, ["grain_eaten_by_migrants_shi", "silver_spent_by_migrants_tael"]),
        (returned, ["adults_returned", "mean_months_away"]),
    ):
        present = [column for column in columns if column in joinable.columns]
        frame = (
            frame.join(joinable.select(["tick", *present]), on="tick", how="left")
            if present
            else frame.with_columns(pl.lit(0.0).alias(column) for column in columns)
        )
    return frame.with_columns(
        [pl.col(name).fill_null(0.0) for name in frame.columns if name != "tick"]
    ).sort("tick")


def migration_totals(events: pl.DataFrame) -> dict[str, float]:
    """Run totals: what left the region, what moved inside it, and what the movers carried."""
    departure = _with_fields(events, (DEPARTURE_EVENT,), PERMANENT_FIELDS).filter(
        pl.col("outcome").str.starts_with("migrated-to")
    )
    exit_events = _with_fields(events, (EXIT_EVENT,), EXIT_FIELDS)
    arrivals = _with_fields(
        events, (ARRIVAL_EVENT,), ("households_arrived", "adults_arrived")
    ).filter(pl.col("outcome").str.starts_with("arrived-from"))
    transit = _with_fields(
        events,
        (TRANSIT_EVENT,),
        ("grain_lost_shi", "silver_spent_or_lost_tael", "travel_cost_tael"),
    )
    temporary = _with_fields(events, (TEMPORARY_EVENT,), TEMPORARY_FIELDS)
    returns = _with_fields(events, (RETURN_EVENT,), ("adults_returned",))
    consumed = _with_fields(
        events, (MIGRANT_CONSUMPTION_EVENT,), ("grain_eaten_shi", "silver_spent_tael")
    )

    def total(frame: pl.DataFrame, column: str) -> float:
        if frame.is_empty() or column not in frame.columns:
            return 0.0
        value = frame[column].sum()
        return 0.0 if value is None else float(value)

    households_departed = total(departure, "households_migrated")
    households_exited = total(exit_events, "households_exited")
    households_arrived = total(arrivals, "households_arrived")
    return {
        "households_departed_total": households_departed,
        "households_arrived_total": households_arrived,
        "households_exited_total": households_exited,
        "internal_migration_share": (
            0.0
            if households_departed <= 0.0
            else (households_departed - households_exited) / households_departed
        ),
        "adults_departed_total": total(departure, "adults_migrated"),
        "adults_exited_total": total(exit_events, "adults_exited"),
        "land_abandoned_mu_total": total(departure, "land_abandoned_mu"),
        "grain_carried_shi_total": total(departure, "grain_carried_shi"),
        "grain_lost_in_transit_shi_total": total(transit, "grain_lost_shi"),
        "silver_lost_or_spent_in_transit_tael_total": total(transit, "silver_spent_or_lost_tael"),
        "temporary_departures_total": float(temporary.height),
        "temporary_adults_sent_total": total(temporary, "adults_away"),
        "temporary_adults_returned_total": total(returns, "adults_returned"),
        "temporary_travel_cost_tael_total": total(temporary, "travel_cost_tael"),
        "migrant_grain_eaten_shi_total": total(consumed, "grain_eaten_shi"),
        "migrant_silver_spent_tael_total": total(consumed, "silver_spent_tael"),
    }


def node_migration(events: pl.DataFrame) -> pl.DataFrame:
    """Per node: net households gained or lost, and the land left behind.

    Departures and exits are attributed to the origin node, arrivals to the destination, so the
    regional total of this table cancels to minus the exits.
    """
    departure = _with_fields(
        events, (DEPARTURE_EVENT,), ("households_migrated", "land_abandoned_mu")
    ).filter(pl.col("outcome").str.starts_with("migrated-to"))
    exits = _with_fields(events, (EXIT_EVENT,), ("households_exited",))
    arrivals = _with_fields(events, (ARRIVAL_EVENT,), ("households_arrived",)).filter(
        pl.col("outcome").str.starts_with("arrived-from")
    )
    left = departure.group_by("region").agg(
        [
            pl.col("households_migrated").sum().alias("households_left"),
            pl.col("land_abandoned_mu").sum().alias("land_abandoned_mu"),
        ]
    )
    gone = exits.group_by("region").agg(pl.col("households_exited").sum().alias("households_gone"))
    came = arrivals.group_by("region").agg(
        pl.col("households_arrived").sum().alias("households_came")
    )
    sources = [frame.select("region") for frame in (left, gone, came) if not frame.is_empty()]
    if not sources:
        return pl.DataFrame(
            schema={
                "node_id": pl.String(),
                "households_left": pl.Float64(),
                "households_gone": pl.Float64(),
                "households_came": pl.Float64(),
                "net_households": pl.Float64(),
                "land_abandoned_mu": pl.Float64(),
            }
        )
    nodes = pl.concat(sources, how="vertical").unique()
    return (
        nodes.join(left, on="region", how="left")
        .join(gone, on="region", how="left")
        .join(came, on="region", how="left")
        .with_columns(
            [
                pl.col("households_left").fill_null(0.0),
                pl.col("households_gone").fill_null(0.0),
                pl.col("households_came").fill_null(0.0),
                pl.col("land_abandoned_mu").fill_null(0.0),
            ]
        )
        .with_columns(
            (pl.col("households_came") - pl.col("households_left")).alias("net_households")
        )
        .rename({"region": "node_id"})
        .sort("node_id")
    )
