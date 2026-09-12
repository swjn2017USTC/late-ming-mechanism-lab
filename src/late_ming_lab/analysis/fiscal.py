"""Fiscal analysis: the tax ledger, the base, the burden, and what extraction costs households.

Everything is read from the log. The county's monthly state record carries the tax decomposition
the plan's M3 requires, and the household events carry who paid, how, and what had to be sold to
do it — so a reader can see both the treasury's side and the household's side of the same
obligation.
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from late_ming_lab.actors.households import HouseholdPopulation
from late_ming_lab.actors.ledger import (
    ASSETS_DELTA,
    GRAIN_DELTA,
    LAND_DELTA,
    SILVER_DELTA,
    TAX_ARREARS_DELTA,
)
from late_ming_lab.analysis.distress import with_trigger_fields

COUNTY_STATE_EVENT = "COUNTY_STATE"
ASSESSMENT_EVENT = "TAX_ASSESSMENT"

#: The quantities the extraction experiment reports. Deliberately only measurements: the phase
#: supplies data for testing a mechanism hypothesis, and does not score one.
FISCAL_MEASURES: tuple[str, ...] = (
    "quota_tael",
    "assessment_rate",
    "collection_effort",
    "reachable_tael",
    "receipts_tael",
    "collection_cost_tael",
    "net_receipts_tael",
    "arrears_tael",
    "arrears_delta_tael",
    "taxable_land_mu",
    "hidden_land_mu",
    "relief_released_shi",
    "relief_cost_tael",
    "silver_tael",
    "granary_shi",
)


class FiscalAnalysisError(ValueError):
    """Raised when an event frame cannot be analysed as a fiscal run."""


def county_fiscal_series(events: pl.DataFrame) -> pl.DataFrame:
    """Per tick and county: the fiscal flows, the base and the balances."""
    states = events.filter(pl.col("event_type") == COUNTY_STATE_EVENT)
    if states.is_empty():
        raise FiscalAnalysisError("event frame holds no COUNTY_STATE records")
    return (
        with_trigger_fields(states, FISCAL_MEASURES)
        .select(["tick", "region", *FISCAL_MEASURES])
        .sort(["region", "tick"])
    )


def fiscal_totals(events: pl.DataFrame) -> dict[str, float]:
    """Run totals and end states, summed over counties."""
    series = county_fiscal_series(events)
    summary = series.select(
        [
            pl.col("quota_tael").sum().alias("nominal_quota_tael"),
            pl.col("receipts_tael").sum().alias("actual_receipts_tael"),
            pl.col("collection_cost_tael").sum().alias("collection_cost_tael"),
            pl.col("net_receipts_tael").sum().alias("net_receipts_tael"),
            pl.col("relief_released_shi").sum().alias("relief_released_shi"),
            pl.col("relief_cost_tael").sum().alias("relief_cost_tael"),
            pl.col("collection_effort").mean().alias("mean_collection_effort"),
            pl.col("assessment_rate").mean().alias("mean_assessment_rate"),
        ]
    ).row(0, named=True)
    final = (
        series.sort(["region", "tick"])
        .group_by("region")
        .agg(
            [
                pl.col("arrears_tael").last().alias("arrears_tael"),
                pl.col("taxable_land_mu").last().alias("taxable_land_mu"),
                pl.col("hidden_land_mu").last().alias("hidden_land_mu"),
                pl.col("silver_tael").last().alias("silver_tael"),
                pl.col("granary_shi").last().alias("granary_shi"),
            ]
        )
        .select(
            [
                pl.col("arrears_tael").sum().alias("arrears_tael"),
                pl.col("taxable_land_mu").sum().alias("taxable_land_mu_end"),
                pl.col("hidden_land_mu").sum().alias("hidden_land_mu_end"),
                pl.col("silver_tael").sum().alias("silver_tael_end"),
                pl.col("granary_shi").sum().alias("granary_shi_end"),
            ]
        )
        .row(0, named=True)
    )
    return {key: float(value or 0.0) for key, value in {**summary, **final}.items()}


def tax_base(events: pl.DataFrame) -> pl.DataFrame:
    """The assessed base per county over time: what the county can see, and what it cannot."""
    series = county_fiscal_series(events)
    return (
        series.group_by("region")
        .agg(
            [
                pl.col("taxable_land_mu").first().alias("taxable_land_mu_start"),
                pl.col("taxable_land_mu").last().alias("taxable_land_mu_end"),
                pl.col("hidden_land_mu").last().alias("hidden_land_mu_end"),
            ]
        )
        .with_columns(
            (pl.col("taxable_land_mu_end") - pl.col("taxable_land_mu_start")).alias(
                "taxable_land_mu_change"
            )
        )
        .sort("region")
    )


def tax_liquidation(events: pl.DataFrame, *, population: HouseholdPopulation) -> pl.DataFrame:
    """What households had to sell to pay tax, per cohort class.

    Only events carrying ``reason_is_tax`` count: grain sold, movable goods sold and land sold in
    order to meet an obligation. Sales made to eat are a different thing and are not mixed in.
    """
    cohort_ids = [cohort.cohort_id for cohort in population]
    by_class = {cohort.cohort_id: cohort.cohort_class.value for cohort in population}
    fields = (GRAIN_DELTA, SILVER_DELTA, LAND_DELTA, ASSETS_DELTA, "reason_is_tax")
    cohort_events = events.filter(pl.col("agent_id").is_in(cohort_ids))
    enriched = with_trigger_fields(cohort_events, fields)
    for_tax = enriched.filter(pl.col("reason_is_tax") > 0.0)
    if for_tax.is_empty():
        return pl.DataFrame(
            schema={
                "cohort_class": pl.String(),
                "grain_sold_for_tax_shi": pl.Float64(),
                "silver_raised_for_tax_tael": pl.Float64(),
                "land_sold_for_tax_mu": pl.Float64(),
                "movables_sold_for_tax_tael": pl.Float64(),
            }
        )
    return (
        for_tax.with_columns(
            pl.col("agent_id")
            .replace_strict(by_class, return_dtype=pl.String)
            .alias("cohort_class")
        )
        .group_by("cohort_class")
        .agg(
            [
                (-pl.col(GRAIN_DELTA))
                .filter(pl.col(GRAIN_DELTA) < 0)
                .sum()
                .alias("grain_sold_for_tax_shi"),
                pl.col(SILVER_DELTA)
                .filter(pl.col(SILVER_DELTA) > 0)
                .sum()
                .alias("silver_raised_for_tax_tael"),
                (-pl.col(LAND_DELTA))
                .filter(pl.col(LAND_DELTA) < 0)
                .sum()
                .alias("land_sold_for_tax_mu"),
                (-pl.col(ASSETS_DELTA))
                .filter(pl.col(ASSETS_DELTA) < 0)
                .sum()
                .alias("movables_sold_for_tax_tael"),
            ]
        )
        .sort("cohort_class")
    )


def tax_burden(population: HouseholdPopulation) -> pl.DataFrame:
    """Arrears and the assessed-vs-paid position, per cohort class at the end of a run."""
    rows = [
        {
            "cohort_class": cohort.cohort_class.value,
            "node_id": cohort.node_id,
            "households": cohort.households,
            "tax_arrears_tael": cohort.tax_arrears_tael,
            "arrears_per_household_tael": cohort.tax_arrears_tael / cohort.households,
            "land_mu": cohort.land_mu,
            "land_per_household_mu": cohort.land_per_household_mu,
            "silver_tael": cohort.silver_tael,
            "movable_assets_tael": cohort.movable_assets_tael,
        }
        for cohort in population
    ]
    frame = pl.DataFrame(rows)
    return (
        frame.group_by("cohort_class")
        .agg(
            [
                pl.col("households").sum().alias("households"),
                pl.col("tax_arrears_tael").sum().alias("tax_arrears_tael"),
                pl.col("arrears_per_household_tael")
                .mean()
                .alias("mean_arrears_per_household_tael"),
                pl.col("land_mu").sum().alias("land_mu"),
                pl.col("land_per_household_mu").mean().alias("mean_land_per_household_mu"),
                pl.col("silver_tael").sum().alias("silver_tael"),
                pl.col("movable_assets_tael").sum().alias("movable_assets_tael"),
            ]
        )
        .sort("cohort_class")
    )


def arrears_reconciliation(
    events: pl.DataFrame, *, population: HouseholdPopulation, county_ids: Sequence[str]
) -> pl.DataFrame:
    """County arrears against household arrears, per county, from the log alone."""
    cohort_ids = [cohort.cohort_id for cohort in population]
    household = (
        with_trigger_fields(
            events.filter(
                (pl.col("event_type") == "TAX_ARREARS_ASSESSED")
                & (pl.col("agent_id").is_in(cohort_ids))
            ),
            (TAX_ARREARS_DELTA,),
        )
        .group_by("region")
        .agg(pl.col(TAX_ARREARS_DELTA).sum().alias("household_arrears_tael"))
        .rename({"region": "node_id"})
    )
    counties = (
        with_trigger_fields(
            events.filter(
                (pl.col("event_type") == "TAX_ARREARS")
                & (pl.col("agent_id").is_in(list(county_ids)))
            ),
            ("arrears_delta_tael",),
        )
        .group_by("region")
        .agg(pl.col("arrears_delta_tael").sum().alias("county_arrears_tael"))
        .rename({"region": "node_id"})
    )
    return (
        household.join(counties, on="node_id", how="full", coalesce=True)
        .with_columns(
            (
                pl.col("household_arrears_tael").fill_null(0.0)
                - pl.col("county_arrears_tael").fill_null(0.0)
            ).alias("difference_tael")
        )
        .sort("node_id")
    )
