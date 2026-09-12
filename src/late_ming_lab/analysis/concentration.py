"""Analysis of market outcomes: price dispersion, land distribution, debt distribution.

P04's product is not a verdict about markets or elites; it is these three measurements and the
ability to see how they move when a rule changes. Everything here is derived from the run's event
log and the actors' final balance sheets, and every ratio is reported with its denominator so a
reader can check it.
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from late_ming_lab.actors.elites import EliteLayer
from late_ming_lab.actors.households import HouseholdPopulation
from late_ming_lab.actors.merchants import MerchantLayer
from late_ming_lab.analysis.distress import with_trigger_fields

MARKET_STATE_EVENT = "MARKET_STATE"
SHIPMENT_EVENT = "TRADE_SHIPMENT"
CONSUMPTION_EVENT = "CONSUMPTION"


class MarketAnalysisError(ValueError):
    """Raised when an event frame cannot be analysed."""


def price_dispersion(
    events: pl.DataFrame, *, county_nodes: Sequence[str] | None = None
) -> pl.DataFrame:
    """Cross-node price dispersion per tick.

    Boundary nodes post the reference price by construction, so a dispersion measure that
    includes them would be damped by a constant the model never estimated. Pass the county nodes
    to measure the market the model actually claims to model.
    """
    states = events.filter(pl.col("event_type") == MARKET_STATE_EVENT)
    if states.is_empty():
        raise MarketAnalysisError("event frame holds no MARKET_STATE records")
    if county_nodes is not None:
        states = states.filter(pl.col("region").is_in(list(county_nodes)))
        if states.is_empty():
            raise MarketAnalysisError("no MARKET_STATE records for the given county nodes")
    priced = with_trigger_fields(states, ("price_tael_per_shi", "inventory_shi", "local_need_shi"))
    return (
        priced.group_by("tick")
        .agg(
            [
                pl.col("price_tael_per_shi").mean().alias("mean_price"),
                pl.col("price_tael_per_shi").std().alias("sd_price"),
                pl.col("price_tael_per_shi").min().alias("min_price"),
                pl.col("price_tael_per_shi").max().alias("max_price"),
                pl.len().alias("nodes"),
            ]
        )
        .with_columns(
            [
                (pl.col("sd_price") / pl.col("mean_price")).alias("coefficient_of_variation"),
                (pl.col("max_price") / pl.col("min_price")).alias("max_min_ratio"),
            ]
        )
        .sort("tick")
    )


def dispersion_summary(dispersion: pl.DataFrame) -> dict[str, float]:
    """Average dispersion over a run, for scenario comparison."""
    if dispersion.is_empty():
        raise MarketAnalysisError("empty dispersion frame")
    summary = dispersion.select(
        pl.col("coefficient_of_variation").mean().alias("cv"),
        pl.col("max_min_ratio").mean().alias("ratio"),
        pl.col("max_min_ratio").max().alias("worst_ratio"),
    ).row(0, named=True)
    return {
        "mean_coefficient_of_variation": float(summary["cv"] or 0.0),
        "mean_max_min_ratio": float(summary["ratio"] or 0.0),
        "max_max_min_ratio": float(summary["worst_ratio"] or 0.0),
    }


def gini(values: Sequence[float], weights: Sequence[float] | None = None) -> float:
    """Weighted Gini coefficient of a distribution; 0 means perfectly equal.

    The weights replicate each holder; a cohort standing for 1,450 households counts 1,450 times.
    """
    if not values:
        return 0.0
    pairs: list[tuple[float, float]] = [
        (float(value), float(weight))
        for value, weight in zip(values, weights or [1.0] * len(values), strict=True)
    ]
    pairs = [(value, weight) for value, weight in pairs if weight > 0.0]
    total_weight = sum(weight for _, weight in pairs)
    total_value = sum(value * weight for value, weight in pairs)
    if total_weight <= 0.0 or total_value <= 0.0:
        return 0.0
    ordered = sorted(pairs)
    weighted_sum = 0.0
    cumulative_weight = 0.0
    for value, weight in ordered:
        cumulative_weight += weight
        weighted_sum += value * weight * (2.0 * cumulative_weight - weight)
    return weighted_sum / (total_value * total_weight) - 1.0


def land_distribution(population: HouseholdPopulation, elites: EliteLayer) -> pl.DataFrame:
    """Land held by each cohort class and by the elite, with shares and per-household means."""
    rows = [
        {
            "holder": cohort.cohort_class.value,
            "holder_kind": "cohort",
            "node_id": cohort.node_id,
            "households": cohort.households,
            "land_mu": cohort.land_mu,
            "land_per_household_mu": cohort.land_per_household_mu,
        }
        for cohort in population
    ]
    rows.extend(
        {
            "holder": "local-elite",
            "holder_kind": "elite",
            "node_id": house.node_id,
            "households": house.households,
            "land_mu": house.land_mu,
            "land_per_household_mu": house.land_per_household_mu,
        }
        for house in elites
    )
    frame = pl.DataFrame(rows)
    total = frame["land_mu"].sum()
    return frame.with_columns((pl.col("land_mu") / total).alias("land_share")).sort(
        ["holder_kind", "holder", "node_id"]
    )


def land_concentration(population: HouseholdPopulation, elites: EliteLayer) -> dict[str, float]:
    """The two numbers the land question needs: elite share and inequality among households."""
    cohorts = population.cohorts
    elite_land = sum(house.land_mu for house in elites)
    cohort_land = sum(cohort.land_mu for cohort in cohorts)
    total = elite_land + cohort_land
    per_household = [cohort.land_per_household_mu for cohort in cohorts]
    weights = [cohort.households for cohort in cohorts]
    return {
        "elite_land_share": elite_land / total if total > 0 else 0.0,
        "cohort_land_gini": gini(per_household, weights),
        "total_land_mu": total,
        "elite_land_mu": elite_land,
        "cohort_land_mu": cohort_land,
    }


def debt_distribution(population: HouseholdPopulation, elites: EliteLayer) -> pl.DataFrame:
    """Debt held by each cohort class, and the claims it corresponds to per node."""
    claims = {
        house.node_id: sum(
            cohort.debt_tael for cohort in population if cohort.node_id == house.node_id
        )
        for house in elites
    }
    rows = [
        {
            "holder": cohort.cohort_class.value,
            "node_id": cohort.node_id,
            "households": cohort.households,
            "debt_tael": cohort.debt_tael,
            "debt_per_household_tael": cohort.debt_per_household_tael,
            "elite_claims_tael": claims[cohort.node_id],
            "silver_tael": cohort.silver_tael,
        }
        for cohort in population
    ]
    frame = pl.DataFrame(rows)
    return frame.with_columns(
        (pl.col("debt_tael") / frame["debt_tael"].sum()).alias("debt_share")
    ).sort(["holder", "node_id"])


def debt_summary(population: HouseholdPopulation, elites: EliteLayer) -> dict[str, float]:
    cohorts = population.cohorts
    total_debt = sum(cohort.debt_tael for cohort in cohorts)
    indebted = [cohort for cohort in cohorts if cohort.debt_tael > 0.0]
    # Claims are derived from household debt, so the two sides are equal by construction; the
    # number is reported so a mismatch would be visible rather than assumed.
    claims = sum(
        cohort.debt_tael
        for house in elites
        for cohort in cohorts
        if cohort.node_id == house.node_id
    )
    return {
        "total_debt_tael": total_debt,
        "total_elite_claims_tael": claims,
        "share_cohorts_indebted": len(indebted) / len(cohorts) if cohorts else 0.0,
        "mean_debt_per_household_tael": (
            total_debt / population.total_households if population.total_households else 0.0
        ),
    }


def trade_summary(events: pl.DataFrame) -> pl.DataFrame:
    """Shipped, arrived and lost grain per link, with the silver paid for it."""
    shipments = events.filter(pl.col("event_type") == SHIPMENT_EVENT)
    if shipments.is_empty():
        return pl.DataFrame(
            schema={
                "origin": pl.String(),
                "destination": pl.String(),
                "shipped_shi": pl.Float64(),
                "arrived_shi": pl.Float64(),
                "lost_shi": pl.Float64(),
                "proceeds_tael": pl.Float64(),
            }
        )
    with_fields = with_trigger_fields(
        shipments, ("shi", "arrived_shi", "lost_shi", "proceeds_tael")
    ).with_columns(
        pl.col("outcome").str.split(":").list.get(1, null_on_oob=True).alias("destination")
    )
    return (
        with_fields.group_by(["region", "destination"])
        .agg(
            [
                pl.col("shi").sum().alias("shipped_shi"),
                pl.col("arrived_shi").sum().alias("arrived_shi"),
                pl.col("lost_shi").sum().alias("lost_shi"),
                pl.col("proceeds_tael").sum().alias("proceeds_tael"),
            ]
        )
        .rename({"region": "origin"})
        .sort(["origin", "destination"])
    )


def first_distress_ticks(events: pl.DataFrame) -> pl.DataFrame:
    """The first tick at which each cohort ate below its floor; empty means never."""
    below = events.filter(
        (pl.col("event_type") == CONSUMPTION_EVENT) & (pl.col("outcome") == "below-floor")
    )
    if below.is_empty():
        return pl.DataFrame(schema={"agent_id": pl.String(), "first_below_floor_tick": pl.Int64()})
    return (
        below.group_by("agent_id").agg(pl.col("tick").min().alias("first_below_floor_tick"))
    ).sort("agent_id")


def merchant_positions(merchants: MerchantLayer) -> pl.DataFrame:
    """Final merchant balance sheets, one row per house."""
    return pl.DataFrame(
        {
            "node_id": [house.node_id for house in merchants],
            "grain_shi": [house.grain_shi for house in merchants],
            "silver_tael": [house.silver_tael for house in merchants],
            "goods_tael": [house.goods_tael for house in merchants],
        }
    ).sort("node_id")
