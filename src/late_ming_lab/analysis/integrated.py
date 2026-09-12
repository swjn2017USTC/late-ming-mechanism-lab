"""The integrated metric set: one row per scenario, plus the series behind it.

This is the assembly point for the sandbox's output, not a new mechanism. Each metric below is
computed by the module that owns it and reported here unchanged, so a reader who wants to know what
"migration" means follows one hop to `analysis/migration.py` rather than reading this file:

```text
household distress      analysis/distress.py     distribution over cohort classes
land concentration      analysis/concentration.py elite share and household gini
migration               analysis/migration.py    departures, arrivals, exits, seasons away
grain price dispersion  analysis/concentration.py cross-node coefficient of variation
actual tax receipts     analysis/fiscal.py        receipts, cost, arrears against the quota
tax base                analysis/fiscal.py        the land the county can see, and its movement
military arrears        analysis/military.py      the arrears stock each garrison carries
desertion               analysis/military.py      the monthly rate at which soldiers leave
armed groups            analysis/military.py      how many bands, and how big the largest is
largest band share      analysis/military.py      its share of all armed men
governance failure      analysis/governance.py    measured quantities against declared reading lines
```

The metric row carries the *regional* summary of each; the frames carry the detail (per class, per
node, per tick) so a reader can check any summary against what produced it. Nothing here aggregates
across mechanisms into a single score: the governance block reports a count of crossed reading
lines, and the count is as close to a verdict as this module comes.
"""

from __future__ import annotations

import polars as pl

from late_ming_lab.actors.elites import EliteLayer
from late_ming_lab.actors.households import HouseholdPopulation
from late_ming_lab.analysis.concentration import (
    dispersion_summary,
    land_concentration,
    price_dispersion,
)
from late_ming_lab.analysis.distress import (
    cohort_attributes,
    cohort_distress,
    distress_distribution,
)
from late_ming_lab.analysis.fiscal import fiscal_totals, tax_base
from late_ming_lab.analysis.governance import governance_indicators, governance_summary
from late_ming_lab.analysis.migration import migration_flows, migration_totals, node_migration
from late_ming_lab.analysis.military import band_series, military_totals
from late_ming_lab.analysis.scalars import largest, mean, total
from late_ming_lab.evidence.parameters import GovernanceIndicatorParameters


class IntegratedAnalysisError(ValueError):
    """Raised when a run's log cannot be summarised as an integrated scenario."""


def integrated_frames(
    events: pl.DataFrame,
    *,
    population: HouseholdPopulation,
    elites: EliteLayer,
    county_nodes: tuple[str, ...],
) -> dict[str, pl.DataFrame]:
    """Every series the sandbox reports, keyed by name; each one is a metric's own output."""
    distress = cohort_distress(events, attributes=cohort_attributes(population))
    return {
        "distress_distribution": distress_distribution(distress),
        "distress_by_node": distress_distribution(distress, by=("node_id",)),
        "price_dispersion": price_dispersion(events, county_nodes=county_nodes),
        "migration_flows": migration_flows(events),
        "migration_nodes": node_migration(events),
        "band_series": band_series(events),
        "tax_base": tax_base(events),
    }


def integrated_metrics(
    events: pl.DataFrame,
    *,
    population: HouseholdPopulation,
    elites: EliteLayer,
    thresholds: GovernanceIndicatorParameters,
    county_nodes: tuple[str, ...],
    starting_households: float,
    starting_adults: float,
) -> dict[str, object]:
    """One scenario's metric row: every headline quantity, with its own measure's name attached."""
    distress = cohort_distress(events, attributes=cohort_attributes(population))
    distribution = distress_distribution(distress)
    price = dispersion_summary(price_dispersion(events, county_nodes=county_nodes))
    fiscal = fiscal_totals(events)
    base = tax_base(events)
    military = military_totals(events)
    migration = migration_totals(events)
    land = land_concentration(population, elites)
    indicators = governance_indicators(
        events,
        thresholds=thresholds,
        population_adults=starting_adults,
        starting_households=starting_households,
    )
    summary = governance_summary(indicators)
    crossed = (
        indicators.filter(pl.col("crossed"))["indicator"].sort().to_list()
        if not indicators.is_empty()
        else []
    )

    households = total(distribution, "households")
    weighted = distribution.with_columns(
        (distribution["mean_unmet_ratio"] * distribution["households"]).alias("weighted_unmet")
    )
    weighted_unmet = total(weighted, "weighted_unmet") / households if households > 0.0 else 0.0
    base_change = total(base, "taxable_land_mu_change")
    base_start = total(base, "taxable_land_mu_start")
    return {
        "mean_unmet_ratio": weighted_unmet,
        "max_unmet_ratio": largest(distribution, "max_unmet_ratio"),
        "share_cohorts_below_floor": mean(distribution, "share_below_floor"),
        "share_cohorts_destitute": mean(distribution, "share_ended_destitute"),
        "share_cohorts_selling_land": mean(distribution, "share_ended_selling_land"),
        "elite_land_share": land["elite_land_share"],
        "cohort_land_gini": land["cohort_land_gini"],
        "total_land_mu": land["total_land_mu"],
        "households_departed": migration["households_departed_total"],
        "households_arrived": migration["households_arrived_total"],
        "households_exited": migration["households_exited_total"],
        "internal_migration_share": migration["internal_migration_share"],
        "land_abandoned_mu": migration["land_abandoned_mu_total"],
        "temporary_adults_sent": migration["temporary_adults_sent_total"],
        "migrant_grain_eaten_shi": migration["migrant_grain_eaten_shi_total"],
        "migrant_silver_spent_tael": migration["migrant_silver_spent_tael_total"],
        "grain_lost_in_transit_shi": migration["grain_lost_in_transit_shi_total"],
        "mean_price_cv": price["mean_coefficient_of_variation"],
        "mean_max_min_price_ratio": price["mean_max_min_ratio"],
        "worst_max_min_price_ratio": price["max_max_min_ratio"],
        "nominal_quota_tael": fiscal["nominal_quota_tael"],
        "actual_receipts_tael": fiscal["actual_receipts_tael"],
        "net_receipts_tael": fiscal["net_receipts_tael"],
        "tax_arrears_tael": fiscal["arrears_tael"],
        "tax_base_start_mu": base_start,
        "tax_base_change_mu": base_change,
        "hidden_land_mu_end": fiscal["hidden_land_mu_end"],
        "relief_released_shi": fiscal["relief_released_shi"],
        "granary_shi_end": fiscal["granary_shi_end"],
        "garrison_troops_end": military["garrison_troops_end"],
        "military_pay_arrears_tael_end": military["pay_arrears_tael_end"],
        "mean_desertion_rate": military["mean_desertion_rate"],
        "deserters_total": military["deserters_left_total"],
        "bands_end": military["bands_end"],
        "band_troops_end": military["band_troops_end"],
        "largest_band_share_end": military["largest_band_share_end"],
        "largest_band_share_max": military["largest_band_share_max"],
        "bands_formed_total": military["bands_formed_total"],
        "cohort_grain_seized_total": military["cohort_grain_seized_total"],
        "indicators_crossed": summary["indicators_crossed"],
        "indicators_reported": summary["indicators_reported"],
        "indicators_crossed_names": ",".join(crossed),
        "population_adults_end": sum(cohort.adults for cohort in population),
        "population_households_end": sum(cohort.households for cohort in population),
    }


#: The metric columns the integrated experiment writes, in report order.
METRIC_COLUMNS: tuple[str, ...] = (
    "scenario",
    "dataset",
    "counties",
    "climate_shock_probability",
    "climate_severity_floor",
    "nominal_pressure",
    "pay_share_of_treasury",
    "mean_unmet_ratio",
    "max_unmet_ratio",
    "share_cohorts_below_floor",
    "share_cohorts_destitute",
    "share_cohorts_selling_land",
    "elite_land_share",
    "cohort_land_gini",
    "total_land_mu",
    "households_departed",
    "households_arrived",
    "households_exited",
    "internal_migration_share",
    "land_abandoned_mu",
    "temporary_adults_sent",
    "migrant_grain_eaten_shi",
    "migrant_silver_spent_tael",
    "grain_lost_in_transit_shi",
    "mean_price_cv",
    "mean_max_min_price_ratio",
    "worst_max_min_price_ratio",
    "nominal_quota_tael",
    "actual_receipts_tael",
    "net_receipts_tael",
    "tax_arrears_tael",
    "tax_base_start_mu",
    "tax_base_change_mu",
    "hidden_land_mu_end",
    "relief_released_shi",
    "granary_shi_end",
    "garrison_troops_end",
    "military_pay_arrears_tael_end",
    "mean_desertion_rate",
    "deserters_total",
    "bands_end",
    "band_troops_end",
    "largest_band_share_end",
    "largest_band_share_max",
    "bands_formed_total",
    "cohort_grain_seized_total",
    "indicators_crossed",
    "indicators_reported",
    "indicators_crossed_names",
    "population_adults_end",
    "population_households_end",
)
