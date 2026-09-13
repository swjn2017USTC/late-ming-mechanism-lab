"""The summary-statistics API: what a run says about a window, in a fixed vector.

Every statistic is a scalar computed from the **event log** restricted to one window, so a
calibration run and a prediction run are summarised by exactly the same code and the only difference
between them is the window. Nothing here reads live actor state: a statistic that could only be read
off the actors at the end of a run could not be sliced by window, and the phase's whole split
(calibration here, hold-out there) depends on slicing.

The vector is declared once, with units and the event that carries it, because a distance is only
meaningful between statistics that mean the same thing on both sides.

Two shapes are provided. :func:`summary_statistics` is the run's *level* in a window — the fixed
vector a sampler scores. :func:`tick_series` (and its :func:`yearly_series` reduction) is the run's
*path* through the window: a pattern whose claim is about co-movement or ordering (dispersion rising
as the crisis deepens, intake tracking desertion) cannot be checked from a level, and reducing the
path to a level first would answer a different question. Both are read from the same event log and
sliced by the same window, so the objective and the posterior predictive check differ in window,
never in code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, cast

import polars as pl

from late_ming_lab.analysis.concentration import gini
from late_ming_lab.calibration.windows import CalibrationWindow

#: Event names the statistics read. Declared here rather than imported from the systems, following
#: the analysis layer's convention: the log's contract is the names, and the names are checked.
CONSUMPTION_EVENT: Final[str] = "CONSUMPTION"
COHORT_STATE_EVENT: Final[str] = "COHORT_STATE"
MIGRATION_DEPARTURE_EVENT: Final[str] = "MIGRATION_DEPARTURE"
MIGRATION_EXIT_EVENT: Final[str] = "MIGRATION_EXIT"
TEMPORARY_MIGRATION_EVENT: Final[str] = "TEMPORARY_MIGRATION"
MARKET_STATE_EVENT: Final[str] = "MARKET_STATE"
TAX_ASSESSMENT_EVENT: Final[str] = "TAX_ASSESSMENT"
TAX_RECEIPT_EVENT: Final[str] = "TAX_RECEIPT"
COUNTY_STATE_EVENT: Final[str] = "COUNTY_STATE"
MILITARY_STATE_EVENT: Final[str] = "MILITARY_STATE"
DESERTION_EVENT: Final[str] = "DESERTERS_LEFT"
BAND_STATE_EVENT: Final[str] = "BAND_STATE"
GRAIN_SEIZED_EVENT: Final[str] = "GRAIN_SEIZED"
RELIEF_EVENT: Final[str] = "OFFICIAL_RELIEF"
RECRUITMENT_LEVY_EVENT: Final[str] = "RECRUITMENT_LEVY"
ELITE_STATE_EVENT: Final[str] = "ELITE_STATE"
CLIMATE_SHOCK_EVENT: Final[str] = "CLIMATE_SHOCK"
MILITARY_STANDING_EVENT: Final[str] = "MILITARY_STANDING"

#: The outcome prefix that marks a levy as a band's in-take rather than a garrison's.
BAND_LEVY_PREFIX: Final[str] = "levied-to:band"


@dataclass(frozen=True, slots=True)
class StatisticDefinition:
    """One scalar in the summary vector: what it is, its unit, and where it comes from."""

    name: str
    unit: str
    source: str
    definition: str


#: The summary vector, in fixed order. A distance is computed element-wise, so the order and the
#: membership of this tuple are part of the calibration contract.
STATISTICS: Final[tuple[StatisticDefinition, ...]] = (
    StatisticDefinition(
        "mean_unmet_ratio",
        "ratio (0-1)",
        CONSUMPTION_EVENT,
        "grain needed but not obtained, over grain needed, across the window",
    ),
    StatisticDefinition(
        "share_cohorts_destitute",
        "share (0-1)",
        COHORT_STATE_EVENT,
        "share of cohorts whose last recorded coping stage in the window is destitute",
    ),
    StatisticDefinition(
        "households_departed",
        "households",
        MIGRATION_DEPARTURE_EVENT,
        "households that left a node for good during the window",
    ),
    StatisticDefinition(
        "households_exited",
        "households",
        MIGRATION_EXIT_EVENT,
        "households that left the modelled region during the window",
    ),
    StatisticDefinition(
        "temporary_adults_sent",
        "adults",
        TEMPORARY_MIGRATION_EVENT,
        "adults sent away for a season during the window",
    ),
    StatisticDefinition(
        "land_abandoned_mu",
        "mu",
        MIGRATION_DEPARTURE_EVENT,
        "cultivated land abandoned by departing households during the window",
    ),
    StatisticDefinition(
        "mean_price_dispersion",
        "coefficient of variation",
        MARKET_STATE_EVENT,
        "mean cross-node coefficient of variation of the posted grain price",
    ),
    StatisticDefinition(
        "peak_price_dispersion",
        "max/min ratio",
        MARKET_STATE_EVENT,
        "worst cross-node max/min price ratio posted in the window",
    ),
    StatisticDefinition(
        "receipts_over_quota",
        "ratio (0-1)",
        TAX_RECEIPT_EVENT,
        "silver received over the quota assessed during the window",
    ),
    StatisticDefinition(
        "tax_arrears_growth",
        "tael",
        COUNTY_STATE_EVENT,
        "change in the county arrears stock across the window",
    ),
    StatisticDefinition(
        "tax_base_change",
        "mu",
        COUNTY_STATE_EVENT,
        "change in the visible taxable land across the window",
    ),
    StatisticDefinition(
        "pay_arrears_growth",
        "tael",
        MILITARY_STATE_EVENT,
        "change in the garrison pay-arrears stock across the window",
    ),
    StatisticDefinition(
        "mean_pay_shortfall",
        "share (0-1)",
        MILITARY_STATE_EVENT,
        "mean of the monthly pay shortfall shares recorded in the window",
    ),
    StatisticDefinition(
        "mean_desertion_rate",
        "share per month",
        DESERTION_EVENT,
        "soldiers who left per month over the strength that could leave",
    ),
    StatisticDefinition(
        "bands_at_end",
        "bands",
        BAND_STATE_EVENT,
        "bands alive at the last recorded tick of the window",
    ),
    StatisticDefinition(
        "peak_largest_band_share",
        "share (0-1)",
        BAND_STATE_EVENT,
        "largest band's share of all armed men, at its highest in the window",
    ),
    StatisticDefinition(
        "cohort_grain_seized",
        "shi",
        GRAIN_SEIZED_EVENT,
        "grain taken from households by armed groups during the window",
    ),
    StatisticDefinition(
        "relief_released",
        "shi",
        RELIEF_EVENT,
        "official relief grain released during the window",
    ),
    StatisticDefinition(
        "elite_land_share",
        "share (0-1)",
        ELITE_STATE_EVENT,
        "elite land over all land held by cohorts and elites, at the last recorded tick",
    ),
    StatisticDefinition(
        "cohort_land_gini",
        "index (0-1)",
        COHORT_STATE_EVENT,
        "weighted Gini of land per household across cohorts, at the last recorded tick",
    ),
    StatisticDefinition(
        "band_intake_adults",
        "adults",
        RECRUITMENT_LEVY_EVENT,
        "adults levied into an armed band rather than a garrison during the window",
    ),
    StatisticDefinition(
        "band_troops_change",
        "troops",
        BAND_STATE_EVENT,
        "change in total band strength from the first to the last recorded tick of the window",
    ),
    StatisticDefinition(
        "deserted_troops",
        "troops",
        DESERTION_EVENT,
        "soldiers who left a garrison during the window",
    ),
)

STATISTIC_NAMES: Final[tuple[str, ...]] = tuple(stat.name for stat in STATISTICS)


class SummaryStatisticError(ValueError):
    """Raised when a run's log cannot be summarised for a window."""


def _in_window(events: pl.DataFrame, window: CalibrationWindow) -> pl.DataFrame:
    return events.filter(
        (pl.col("tick") >= window.first_tick) & (pl.col("tick") <= window.last_tick)
    )


def _trigger(frame: pl.DataFrame, field: str) -> pl.Series:
    """One numeric trigger value out of the event log's JSON payload."""
    return frame["trigger_json"].str.json_path_match(f"$.{field}").cast(pl.Float64, strict=False)


def scalar(value: object) -> float:
    """A polars aggregate as a float; 0.0 when it is null (the run has not produced it yet)."""
    return 0.0 if value is None else float(cast("float", value))


def _total(frame: pl.DataFrame, field: str) -> float:
    if frame.is_empty():
        return 0.0
    return scalar(_trigger(frame, field).sum())


def _mean(frame: pl.DataFrame, field: str) -> float:
    if frame.is_empty():
        return 0.0
    return scalar(_trigger(frame, field).mean())


def _of_type(events: pl.DataFrame, event_type: str) -> pl.DataFrame:
    return events.filter(pl.col("event_type") == event_type)


def _destitute_share(events: pl.DataFrame) -> float:
    states = _of_type(events, COHORT_STATE_EVENT)
    if states.is_empty():
        return 0.0
    last = states.sort("seq").group_by("agent_id").agg(pl.col("outcome").last().alias("stage"))
    destitute = last.filter(pl.col("stage") == "destitute").height
    return destitute / last.height


def _price_dispersion(
    events: pl.DataFrame, *, county_nodes: tuple[str, ...]
) -> tuple[float, float]:
    states = _of_type(events, MARKET_STATE_EVENT)
    if county_nodes:
        states = states.filter(pl.col("region").is_in(list(county_nodes)))
    if states.is_empty():
        return 0.0, 0.0
    priced = states.with_columns(_trigger(states, "price_tael_per_shi").alias("price"))
    per_tick = priced.group_by("tick").agg(
        [
            pl.col("price").mean().alias("mean_price"),
            pl.col("price").std().alias("sd_price"),
            pl.col("price").min().alias("min_price"),
            pl.col("price").max().alias("max_price"),
        ]
    )
    cv = per_tick.with_columns((pl.col("sd_price") / pl.col("mean_price")).alias("cv"))["cv"].mean()
    ratio = per_tick.with_columns((pl.col("max_price") / pl.col("min_price")).alias("ratio"))[
        "ratio"
    ].max()
    return scalar(cv), scalar(ratio)


def _first_last(events: pl.DataFrame, event_type: str, field: str) -> tuple[float, float]:
    frame = _of_type(events, event_type)
    if frame.is_empty():
        return 0.0, 0.0
    ordered = frame.sort("seq").with_columns(_trigger(frame, field).alias("value"))
    first = ordered.group_by("region").agg(pl.col("value").first().alias("v"))["v"].sum()
    last = ordered.group_by("region").agg(pl.col("value").last().alias("v"))["v"].sum()
    return scalar(first), scalar(last)


def _bands_at_end(events: pl.DataFrame) -> int:
    states = _of_type(events, BAND_STATE_EVENT)
    if states.is_empty():
        return 0
    last_tick = int(cast("int", states["tick"].max() or 0))
    return states.filter(pl.col("tick") == last_tick).height


def _peak_largest_band_share(events: pl.DataFrame) -> float:
    states = _of_type(events, BAND_STATE_EVENT)
    if states.is_empty():
        return 0.0
    per_tick = (
        states.with_columns(_trigger(states, "troops").alias("troops"))
        .group_by("tick")
        .agg(
            [
                pl.col("troops").sum().alias("total"),
                pl.col("troops").max().alias("largest"),
            ]
        )
    )
    shares = per_tick.filter(pl.col("total") > 0.0).with_columns(
        (pl.col("largest") / pl.col("total")).alias("share")
    )
    if shares.is_empty():
        return 0.0
    return scalar(shares["share"].max())


def _last_per_agent(frame: pl.DataFrame, *fields: str) -> pl.DataFrame:
    """The last recorded value of each trigger field per agent, by emission order."""
    if frame.is_empty():
        return pl.DataFrame({"agent_id": pl.Series([], dtype=pl.String)})
    ordered = frame.sort("seq")
    enriched = ordered.with_columns([_trigger(ordered, field).alias(field) for field in fields])
    return enriched.group_by("agent_id").agg([pl.col(field).last() for field in fields])


def _land_holdings(events: pl.DataFrame) -> tuple[float, float]:
    """Elite land and cohort land at the last recorded tick of the scope, in mu."""
    elites = _last_per_agent(_of_type(events, ELITE_STATE_EVENT), "land_mu")
    cohorts = _last_per_agent(_of_type(events, COHORT_STATE_EVENT), "land_mu")
    elite_land = scalar(elites["land_mu"].sum()) if "land_mu" in elites.columns else 0.0
    cohort_land = scalar(cohorts["land_mu"].sum()) if "land_mu" in cohorts.columns else 0.0
    return elite_land, cohort_land


def _land_share(elite_land: float, cohort_land: float) -> float:
    total = elite_land + cohort_land
    return elite_land / total if total > 0.0 else 0.0


def _cohort_land_gini(events: pl.DataFrame) -> float:
    """Weighted Gini of land per household across cohorts, at the last recorded tick."""
    cohorts = _last_per_agent(
        _of_type(events, COHORT_STATE_EVENT), "land_per_household_mu", "households"
    )
    if cohorts.is_empty() or "land_per_household_mu" not in cohorts.columns:
        return 0.0
    return gini(list(cohorts["land_per_household_mu"]), list(cohorts["households"]))


def _band_troops_change(events: pl.DataFrame) -> float:
    states = _of_type(events, BAND_STATE_EVENT)
    if states.is_empty():
        return 0.0
    per_tick = (
        states.with_columns(_trigger(states, "troops").alias("troops"))
        .group_by("tick")
        .agg(pl.col("troops").sum())
        .sort("tick")
    )
    return scalar(per_tick["troops"].last()) - scalar(per_tick["troops"].first())


def _band_intake(events: pl.DataFrame) -> float:
    """Adults a band took in: levies whose destination is a band, not a garrison."""
    levies = _of_type(events, RECRUITMENT_LEVY_EVENT)
    if levies.is_empty():
        return 0.0
    return _total(
        levies.filter(pl.col("outcome").str.starts_with(BAND_LEVY_PREFIX)), "adults_levied"
    )


#: The per-tick columns :func:`tick_series` produces, in fixed order.
SERIES_COLUMNS: Final[tuple[str, ...]] = (
    "tick",
    "unmet_ratio",
    "destitute_share",
    "price_cv",
    "price_ratio",
    "receipts_over_quota",
    "taxable_land_mu",
    "arrears_tael",
    "elite_land_share",
    "cohort_land_gini",
    "band_intake_adults",
    "deserted_troops",
    "land_abandoned_mu",
    "band_troops",
    "shock_severity",
    "destitute_cohorts",
    "band_count",
    "largest_band_share",
    "pay_shortfall_share",
    "pay_arrears_tael",
    "relief_coverage",
    "migration_exits",
)

#: Series columns that measure a rate or a share: a year is their mean.
YEARLY_MEAN_COLUMNS: Final[tuple[str, ...]] = (
    "unmet_ratio",
    "destitute_share",
    "price_cv",
    "price_ratio",
    "receipts_over_quota",
    "elite_land_share",
    "cohort_land_gini",
    "shock_severity",
    "band_count",
    "largest_band_share",
    "pay_shortfall_share",
    "relief_coverage",
)

#: Series columns that measure a flow: a year is their sum.
YEARLY_SUM_COLUMNS: Final[tuple[str, ...]] = (
    "band_intake_adults",
    "deserted_troops",
    "land_abandoned_mu",
    "destitute_cohorts",
    "migration_exits",
)

#: Series columns that measure a stock: a year is its last recorded value.
YEARLY_LAST_COLUMNS: Final[tuple[str, ...]] = (
    "taxable_land_mu",
    "arrears_tael",
    "band_troops",
    "pay_arrears_tael",
)


def _by_tick(
    frame: pl.DataFrame, field: str, name: str, *, how: Literal["sum", "last", "mean"]
) -> pl.DataFrame:
    """One row per tick: a trigger field summed, averaged, or taken as the tick's last record."""
    empty = pl.DataFrame(
        {"tick": pl.Series([], dtype=pl.Int64), name: pl.Series([], dtype=pl.Float64)}
    )
    if frame.is_empty():
        return empty
    values = frame.with_columns(_trigger(frame, field).alias(name))
    if how == "last":
        values = values.sort("seq").group_by("tick").agg(pl.col(name).last())
    elif how == "mean":
        values = values.group_by("tick").agg(pl.col(name).mean())
    else:
        values = values.group_by("tick").agg(pl.col(name).sum())
    return values.select("tick", name)


def _count_by_tick(frame: pl.DataFrame, name: str) -> pl.DataFrame:
    """One row per tick: how many distinct agents recorded a state in it."""
    empty = pl.DataFrame(
        {"tick": pl.Series([], dtype=pl.Int64), name: pl.Series([], dtype=pl.Float64)}
    )
    if frame.is_empty():
        return empty
    return (
        frame.group_by("tick")
        .agg(pl.col("agent_id").n_unique().cast(pl.Float64).alias(name))
        .select("tick", name)
    )


def _largest_share_by_tick(frame: pl.DataFrame, field: str, name: str) -> pl.DataFrame:
    """One row per tick: the largest holder's share of the tick's total of a trigger field."""
    empty = pl.DataFrame(
        {"tick": pl.Series([], dtype=pl.Int64), name: pl.Series([], dtype=pl.Float64)}
    )
    if frame.is_empty():
        return empty
    values = frame.with_columns(_trigger(frame, field).alias("_value"))
    per_tick = values.group_by("tick").agg(
        [
            pl.col("_value").sum().alias("_total"),
            pl.col("_value").max().alias("_largest"),
        ]
    )
    return per_tick.with_columns(
        pl.when(pl.col("_total") > 0.0)
        .then(pl.col("_largest") / pl.col("_total"))
        .otherwise(0.0)
        .alias(name)
    ).select("tick", name)


def _destitute_cohorts_by_tick(events: pl.DataFrame) -> pl.DataFrame:
    """Cohort-months spent destitute per tick: how many cohorts recorded the destitute stage."""
    states = _of_type(events, COHORT_STATE_EVENT)
    empty = pl.DataFrame(
        {
            "tick": pl.Series([], dtype=pl.Int64),
            "destitute_cohorts": pl.Series([], dtype=pl.Float64),
        }
    )
    if states.is_empty():
        return empty
    return (
        states.with_columns((pl.col("outcome") == "destitute").cast(pl.Float64).alias("flag"))
        .group_by("tick")
        .agg(pl.col("flag").sum().alias("destitute_cohorts"))
        .select("tick", "destitute_cohorts")
    )


def _ratio_by_tick(numerator: pl.DataFrame, denominator: pl.DataFrame, name: str) -> pl.DataFrame:
    """A per-tick ratio of two summed trigger fields, zero where the denominator is zero."""
    joined = numerator.join(denominator, on="tick", how="full", coalesce=True).with_columns(
        pl.col("_num").fill_null(0.0), pl.col("_den").fill_null(0.0)
    )
    return joined.with_columns(
        pl.when(pl.col("_den") > 0.0)
        .then(pl.col("_num") / pl.col("_den"))
        .otherwise(0.0)
        .alias(name)
    ).select("tick", name)


def _per_tick_land(events: pl.DataFrame, window: CalibrationWindow) -> pl.DataFrame:
    """Land share and cohort Gini per tick, from the state records each tick carries."""
    elites = _of_type(events, ELITE_STATE_EVENT)
    cohorts = _of_type(events, COHORT_STATE_EVENT)
    if elites.is_empty() or cohorts.is_empty():
        return pl.DataFrame(
            {
                "tick": pl.Series([], dtype=pl.Int64),
                "elite_land_share": pl.Series([], dtype=pl.Float64),
                "cohort_land_gini": pl.Series([], dtype=pl.Float64),
            }
        )
    elite_land = _by_tick(elites, "land_mu", "elite_land_mu", how="last")
    cohort_land = _by_tick(cohorts, "land_mu", "cohort_land_mu", how="last")
    joined = elite_land.join(cohort_land, on="tick", how="full", coalesce=True).with_columns(
        pl.col("elite_land_mu").fill_null(0.0), pl.col("cohort_land_mu").fill_null(0.0)
    )
    shares = joined.with_columns(
        pl.when((pl.col("elite_land_mu") + pl.col("cohort_land_mu")) > 0.0)
        .then(pl.col("elite_land_mu") / (pl.col("elite_land_mu") + pl.col("cohort_land_mu")))
        .otherwise(0.0)
        .alias("elite_land_share")
    ).select("tick", "elite_land_share")

    ordered = cohorts.sort("seq").with_columns(
        _trigger(cohorts, "land_per_household_mu").alias("land_per_household_mu"),
        _trigger(cohorts, "households").alias("households"),
    )
    last = ordered.group_by("tick", "agent_id").agg(
        pl.col("land_per_household_mu").last(), pl.col("households").last()
    )
    gini_rows = [
        {
            "tick": group["tick"][0],
            "cohort_land_gini": gini(
                list(group["land_per_household_mu"]), list(group["households"])
            ),
        }
        for group in last.partition_by("tick", maintain_order=True)
    ]
    index = pl.DataFrame(
        gini_rows,
        schema={"tick": pl.Int64, "cohort_land_gini": pl.Float64},
    )
    spine = pl.DataFrame({"tick": pl.Series(list(range(window.first_tick, window.last_tick + 1)))})
    return (
        spine.join(shares, on="tick", how="left")
        .join(index, on="tick", how="left")
        .with_columns(
            pl.col("elite_land_share").fill_null(0.0), pl.col("cohort_land_gini").fill_null(0.0)
        )
    )


def _per_tick_prices(events: pl.DataFrame, *, county_nodes: tuple[str, ...]) -> pl.DataFrame:
    """Cross-node price dispersion per tick: coefficient of variation and max/min ratio."""
    states = _of_type(events, MARKET_STATE_EVENT)
    if county_nodes:
        states = states.filter(pl.col("region").is_in(list(county_nodes)))
    if states.is_empty():
        return pl.DataFrame(
            {
                "tick": pl.Series([], dtype=pl.Int64),
                "price_cv": pl.Series([], dtype=pl.Float64),
                "price_ratio": pl.Series([], dtype=pl.Float64),
            }
        )
    priced = states.with_columns(_trigger(states, "price_tael_per_shi").alias("price"))
    return (
        priced.group_by("tick")
        .agg(
            [
                pl.col("price").mean().alias("mean_price"),
                pl.col("price").std().alias("sd_price"),
                pl.col("price").min().alias("min_price"),
                pl.col("price").max().alias("max_price"),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("mean_price") > 0.0)
                .then(pl.col("sd_price").fill_null(0.0) / pl.col("mean_price"))
                .otherwise(0.0)
                .alias("price_cv"),
                pl.when(pl.col("min_price") > 0.0)
                .then(pl.col("max_price") / pl.col("min_price"))
                .otherwise(1.0)
                .alias("price_ratio"),
            ]
        )
        .select("tick", "price_cv", "price_ratio")
    )


def tick_series(
    events: pl.DataFrame, *, window: CalibrationWindow, county_nodes: tuple[str, ...] = ()
) -> pl.DataFrame:
    """The run's path through one window: every series column, one row per tick of the window.

    Stocks are forward-filled across a tick that recorded nothing (a system that did not run leaves
    no state record), flows become zero, and every column is present for every tick of the window so
    a co-movement check never silently compares two different tick sets.
    """
    scoped = _in_window(events, window)
    if scoped.is_empty():
        raise SummaryStatisticError(f"no events in window {window.label}")

    consumption = _of_type(scoped, CONSUMPTION_EVENT)
    unmet = _ratio_by_tick(
        _by_tick(consumption, "unmet_shi", "_num", how="sum"),
        _by_tick(consumption, "need_shi", "_den", how="sum"),
        "unmet_ratio",
    )

    states = _of_type(scoped, COHORT_STATE_EVENT)
    destitute = (
        states.with_columns((pl.col("outcome") == "destitute").cast(pl.Float64).alias("destitute"))
        .group_by("tick")
        .agg(pl.col("destitute").mean().alias("destitute_share"))
        .select("tick", "destitute_share")
        if not states.is_empty()
        else pl.DataFrame(
            {
                "tick": pl.Series([], dtype=pl.Int64),
                "destitute_share": pl.Series([], dtype=pl.Float64),
            }
        )
    )

    assessment = _of_type(scoped, TAX_ASSESSMENT_EVENT)
    receipt = _of_type(scoped, TAX_RECEIPT_EVENT)
    county = _of_type(scoped, COUNTY_STATE_EVENT)
    receipts_over_quota = _ratio_by_tick(
        _by_tick(receipt, "receipts_tael", "_num", how="sum"),
        _by_tick(assessment, "quota_tael", "_den", how="sum"),
        "receipts_over_quota",
    )

    departure = _of_type(scoped, MIGRATION_DEPARTURE_EVENT).filter(
        pl.col("outcome").str.starts_with("migrated-to")
    )
    parts = (
        unmet,
        destitute,
        _per_tick_prices(scoped, county_nodes=county_nodes),
        receipts_over_quota,
        _by_tick(county, "taxable_land_mu", "taxable_land_mu", how="last"),
        _by_tick(county, "arrears_tael", "arrears_tael", how="last"),
        _per_tick_land(scoped, window),
        _by_tick(
            _of_type(scoped, RECRUITMENT_LEVY_EVENT).filter(
                pl.col("outcome").str.starts_with(BAND_LEVY_PREFIX)
            ),
            "adults_levied",
            "band_intake_adults",
            how="sum",
        ),
        _by_tick(_of_type(scoped, DESERTION_EVENT), "troops_left", "deserted_troops", how="sum"),
        _by_tick(departure, "land_abandoned_mu", "land_abandoned_mu", how="sum"),
        _by_tick(_of_type(scoped, BAND_STATE_EVENT), "troops", "band_troops", how="sum"),
        _by_tick(_of_type(scoped, CLIMATE_SHOCK_EVENT), "severity", "shock_severity", how="mean"),
        _destitute_cohorts_by_tick(scoped),
        _count_by_tick(_of_type(scoped, BAND_STATE_EVENT), "band_count"),
        _largest_share_by_tick(_of_type(scoped, BAND_STATE_EVENT), "troops", "largest_band_share"),
        _by_tick(
            _of_type(scoped, MILITARY_STANDING_EVENT),
            "pay_shortfall_share",
            "pay_shortfall_share",
            how="mean",
        ),
        _by_tick(
            _of_type(scoped, MILITARY_STATE_EVENT),
            "pay_arrears_tael",
            "pay_arrears_tael",
            how="sum",
        ),
        _ratio_by_tick(
            _by_tick(_of_type(scoped, RELIEF_EVENT), "released_shi", "_num", how="sum"),
            _by_tick(consumption, "need_shi", "_den", how="sum"),
            "relief_coverage",
        ),
        _by_tick(
            _of_type(scoped, MIGRATION_EXIT_EVENT),
            "households_exited",
            "migration_exits",
            how="sum",
        ),
    )

    spine = pl.DataFrame({"tick": pl.Series(list(range(window.first_tick, window.last_tick + 1)))})
    frame = spine
    for part in parts:
        frame = frame.join(part, on="tick", how="left")
    frame = frame.with_columns(
        [pl.col(column).fill_null(0.0) for column in SERIES_COLUMNS if column != "tick"]
    )
    stocks = [column for column in YEARLY_LAST_COLUMNS]
    frame = frame.with_columns([pl.col(column).forward_fill() for column in stocks]).with_columns(
        [pl.col(column).fill_null(0.0) for column in stocks]
    )
    missing = [column for column in SERIES_COLUMNS if column not in frame.columns]
    if missing:
        raise SummaryStatisticError(f"tick series is missing columns: {', '.join(missing)}")
    return frame.select(list(SERIES_COLUMNS))


def yearly_series(
    series: pl.DataFrame, *, start_year: int = 1625, ticks_per_year: int = 12
) -> pl.DataFrame:
    """Reduce a per-tick series to one row per calendar year: means, sums and year-end stocks."""
    if series.is_empty():
        raise SummaryStatisticError("empty tick series")
    frame = series.with_columns((start_year + (pl.col("tick") // ticks_per_year)).alias("year"))
    aggregated = frame.group_by("year").agg(
        [pl.col(column).mean().alias(column) for column in YEARLY_MEAN_COLUMNS]
        + [pl.col(column).sum().alias(column) for column in YEARLY_SUM_COLUMNS]
        + [pl.col(column).last().alias(column) for column in YEARLY_LAST_COLUMNS]
    )
    return aggregated.select(
        ["year", *YEARLY_MEAN_COLUMNS, *YEARLY_SUM_COLUMNS, *YEARLY_LAST_COLUMNS]
    ).sort("year")


def summary_statistics(
    events: pl.DataFrame,
    *,
    window: CalibrationWindow,
    county_nodes: tuple[str, ...] = (),
) -> dict[str, float]:
    """The summary vector for one window of one run.

    The price statistics are dispersion measures — a coefficient of variation and a max/min ratio —
    so they are free of the silver level by construction: a distance between two runs never compares
    price levels that a calibrated parameter changed.
    """
    scoped = _in_window(events, window)
    if scoped.is_empty():
        raise SummaryStatisticError(f"no events in window {window.label}")

    consumption = _of_type(scoped, CONSUMPTION_EVENT)
    need = _total(consumption, "need_shi")
    unmet = _total(consumption, "unmet_shi")

    assessment = _total(_of_type(scoped, TAX_ASSESSMENT_EVENT), "quota_tael")
    receipts = _total(_of_type(scoped, TAX_RECEIPT_EVENT), "receipts_tael")

    arrears_first, arrears_last = _first_last(scoped, COUNTY_STATE_EVENT, "arrears_tael")
    base_first, base_last = _first_last(scoped, COUNTY_STATE_EVENT, "taxable_land_mu")
    pay_first, pay_last = _first_last(scoped, MILITARY_STATE_EVENT, "pay_arrears_tael")

    desertion = _of_type(scoped, DESERTION_EVENT)
    lost = _total(desertion, "troops_left")
    strength = _of_type(scoped, MILITARY_STATE_EVENT)
    standing = strength.with_columns(_trigger(strength, "troops").alias("troops"))
    months = standing.height / max(1, standing["region"].n_unique())
    mean_strength = scalar(standing["troops"].mean()) if not standing.is_empty() else 0.0
    desertion_rate = lost / (mean_strength * months) if mean_strength > 0.0 and months > 0 else 0.0

    dispersion_cv, dispersion_ratio = _price_dispersion(scoped, county_nodes=county_nodes)

    return {
        "mean_unmet_ratio": unmet / need if need > 0.0 else 0.0,
        "share_cohorts_destitute": _destitute_share(scoped),
        "households_departed": _total(
            _of_type(scoped, MIGRATION_DEPARTURE_EVENT).filter(
                pl.col("outcome").str.starts_with("migrated-to")
            ),
            "households_migrated",
        ),
        "households_exited": _total(_of_type(scoped, MIGRATION_EXIT_EVENT), "households_exited"),
        "temporary_adults_sent": _total(_of_type(scoped, TEMPORARY_MIGRATION_EVENT), "adults_away"),
        "land_abandoned_mu": _total(
            _of_type(scoped, MIGRATION_DEPARTURE_EVENT).filter(
                pl.col("outcome").str.starts_with("migrated-to")
            ),
            "land_abandoned_mu",
        ),
        "mean_price_dispersion": dispersion_cv,
        "peak_price_dispersion": dispersion_ratio,
        "receipts_over_quota": receipts / assessment if assessment > 0.0 else 0.0,
        "tax_arrears_growth": arrears_last - arrears_first,
        "tax_base_change": base_last - base_first,
        "pay_arrears_growth": pay_last - pay_first,
        "mean_pay_shortfall": _mean(strength, "pay_shortfall_share")
        if not strength.is_empty()
        else 0.0,
        "mean_desertion_rate": min(1.0, max(0.0, desertion_rate)),
        "bands_at_end": float(_bands_at_end(scoped)),
        "peak_largest_band_share": _peak_largest_band_share(scoped),
        "cohort_grain_seized": _total(_of_type(scoped, GRAIN_SEIZED_EVENT), "grain_seized_shi"),
        "relief_released": _total(_of_type(scoped, RELIEF_EVENT), "released_shi"),
        "elite_land_share": _land_share(*_land_holdings(scoped)),
        "cohort_land_gini": _cohort_land_gini(scoped),
        "band_intake_adults": _band_intake(scoped),
        "band_troops_change": _band_troops_change(scoped),
        "deserted_troops": _total(_of_type(scoped, DESERTION_EVENT), "troops_left"),
    }


def summary_vector(
    events: pl.DataFrame, *, window: CalibrationWindow, county_nodes: tuple[str, ...] = ()
) -> tuple[float, ...]:
    """The same statistics as a fixed-order vector, which is what a distance needs."""
    values = summary_statistics(events, window=window, county_nodes=county_nodes)
    return tuple(values[name] for name in STATISTIC_NAMES)
