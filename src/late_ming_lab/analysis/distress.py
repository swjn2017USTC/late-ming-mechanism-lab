"""Analysis: what a run's event log says about cohort distress.

Distress is read out of the log, never recomputed from hidden state. The measures are physical
quantities — the share of the subsistence floor that went unmet, land and assets that left the
cohort, debt that accumulated, and how far down the coping ladder the cohort ended — and are
reported per household so cohorts of different weights can be compared.
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from late_ming_lab.actors.households import CohortEventType, CopingStage, HouseholdPopulation

DISTRESS_THRESHOLDS_ARE_EVIDENCE: str = "thresholds live in HouseholdParameters, not here"

COHORT_ATTRIBUTE_COLUMNS: tuple[str, ...] = (
    "cohort_id",
    "node_id",
    "cohort_class",
    "households",
)


class DistressAnalysisError(ValueError):
    """Raised when an event frame cannot be analysed."""


def cohort_attributes(population: HouseholdPopulation) -> pl.DataFrame:
    """One row per cohort, for joining onto aggregated flows."""
    return pl.DataFrame(
        [
            {
                "cohort_id": cohort.cohort_id,
                "node_id": cohort.node_id,
                "cohort_class": cohort.cohort_class.value,
                "households": cohort.households,
            }
            for cohort in population
        ],
        schema={
            "cohort_id": pl.String(),
            "node_id": pl.String(),
            "cohort_class": pl.String(),
            "households": pl.Float64(),
        },
    )


def with_trigger_fields(frame: pl.DataFrame, fields: Sequence[str]) -> pl.DataFrame:
    """Extract trigger values as numeric columns; absent fields become 0."""
    if "trigger_json" not in frame.columns:
        raise DistressAnalysisError("event frame has no trigger_json column")
    return frame.with_columns(
        [
            pl.col("trigger_json")
            .str.json_path_match(f"$.{field}")
            .cast(pl.Float64, strict=False)
            .fill_null(0.0)
            .alias(field)
            for field in fields
        ]
    )


def _flow_sums(
    frame: pl.DataFrame, event_type: CohortEventType, fields: Sequence[str]
) -> pl.DataFrame:
    selected = frame.filter(pl.col("event_type") == event_type.value)
    if selected.is_empty():
        return pl.DataFrame(
            schema={"cohort_id": pl.String(), **{field: pl.Float64() for field in fields}}
        )
    return (
        with_trigger_fields(selected, fields)
        .group_by(pl.col("agent_id").alias("cohort_id"))
        .agg([pl.col(field).sum() for field in fields])
    )


def _final_state(frame: pl.DataFrame) -> pl.DataFrame:
    snapshots = frame.filter(pl.col("event_type") == CohortEventType.COHORT_STATE.value)
    if snapshots.is_empty():
        raise DistressAnalysisError("event frame holds no COHORT_STATE snapshots")
    fields = (
        "grain_shi",
        "silver_tael",
        "debt_tael",
        "land_mu",
        "movable_assets_tael",
        "coping_stage_index",
        "permanent_migration_eligible",
        "temporary_migration_eligible",
        "recruitment_eligible",
    )
    return (
        with_trigger_fields(snapshots.sort(["tick", "seq"]), fields)
        .group_by(pl.col("agent_id").alias("cohort_id"))
        .agg(
            [pl.col(field).last().alias(f"final_{field}") for field in fields]
            + [pl.col("outcome").last().alias("final_stage")]
        )
    )


def cohort_distress(
    events: pl.DataFrame, *, attributes: pl.DataFrame | None = None
) -> pl.DataFrame:
    """Per-cohort distress ledger for one run, derived entirely from the event log."""
    consumption = _flow_sums(
        events, CohortEventType.CONSUMPTION, ("need_shi", "unmet_shi", "purchased_shi")
    )
    harvest = _flow_sums(events, CohortEventType.HARVEST, ("harvested_shi",))
    rent = _flow_sums(events, CohortEventType.RENT_PAYMENT, ("rent_shi",))
    borrowing = _flow_sums(
        events, CohortEventType.BORROWING_REQUEST, ("requested_tael", "granted_tael")
    )
    interest = _flow_sums(events, CohortEventType.DEBT_INTEREST, ("interest_tael",))
    land_sales = _flow_sums(events, CohortEventType.LAND_SALE, ("land_sold_mu", "proceeds_tael"))
    asset_sales = _flow_sums(events, CohortEventType.MOVABLE_ASSET_SALE, ("assets_sold_tael",))
    labour_income = _flow_sums(events, CohortEventType.LABOUR_INCOME, ("silver_delta_tael",))

    ledger = _final_state(events)
    for flows in (
        consumption,
        harvest,
        rent,
        borrowing,
        interest,
        asset_sales,
        labour_income,
    ):
        ledger = ledger.join(flows, on="cohort_id", how="left")
    ledger = ledger.join(
        land_sales.rename({"proceeds_tael": "land_sale_proceeds_tael"}),
        on="cohort_id",
        how="left",
    )
    if attributes is not None:
        ledger = ledger.join(attributes, on="cohort_id", how="left")

    ledger = ledger.with_columns(
        [
            pl.col("need_shi").fill_null(0.0),
            pl.col("unmet_shi").fill_null(0.0),
            pl.col("purchased_shi").fill_null(0.0),
            pl.col("harvested_shi").fill_null(0.0),
            pl.col("rent_shi").fill_null(0.0),
            pl.col("requested_tael").fill_null(0.0),
            pl.col("granted_tael").fill_null(0.0),
            pl.col("interest_tael").fill_null(0.0),
            pl.col("land_sold_mu").fill_null(0.0),
            pl.col("land_sale_proceeds_tael").fill_null(0.0),
            pl.col("assets_sold_tael").fill_null(0.0),
            pl.col("silver_delta_tael").fill_null(0.0),
        ]
    )
    return ledger.with_columns(
        [
            (
                pl.when(pl.col("need_shi") > 0)
                .then(pl.col("unmet_shi") / pl.col("need_shi"))
                .otherwise(0.0)
            ).alias("unmet_ratio"),
            (pl.col("unmet_shi") > 0).cast(pl.Boolean).alias("ever_below_floor"),
            (pl.col("final_coping_stage_index") >= float(CopingStage.DESTITUTE)).alias("destitute"),
            (pl.col("final_coping_stage_index") >= float(CopingStage.SELLING_LAND)).alias(
                "sold_land_stage"
            ),
        ]
    )


def distress_distribution(
    distress: pl.DataFrame, *, by: Sequence[str] = ("cohort_class",)
) -> pl.DataFrame:
    """Aggregate cohort distress into a distribution over the grouping columns."""
    missing = [column for column in by if column not in distress.columns]
    if missing:
        raise DistressAnalysisError(f"cannot group by missing columns: {', '.join(missing)}")
    return (
        distress.group_by([pl.col(column) for column in by])
        .agg(
            [
                pl.len().alias("cohorts"),
                pl.col("households").sum().alias("households"),
                pl.col("unmet_ratio").mean().alias("mean_unmet_ratio"),
                pl.col("unmet_ratio").max().alias("max_unmet_ratio"),
                pl.col("ever_below_floor").mean().alias("share_below_floor"),
                pl.col("destitute").mean().alias("share_destitute"),
                pl.col("sold_land_stage").mean().alias("share_sold_land"),
                (pl.col("land_sold_mu") / pl.col("households"))
                .mean()
                .alias("mean_land_sold_mu_per_household"),
                (pl.col("final_debt_tael") / pl.col("households"))
                .mean()
                .alias("mean_debt_tael_per_household"),
                (pl.col("granted_tael") / pl.col("households"))
                .mean()
                .alias("mean_borrowed_tael_per_household"),
                (pl.col("purchased_shi") / pl.col("households"))
                .mean()
                .alias("mean_purchased_shi_per_household"),
                pl.col("final_recruitment_eligible").mean().alias("share_recruitment_eligible"),
                pl.col("final_permanent_migration_eligible")
                .mean()
                .alias("share_permanent_migration_eligible"),
            ]
        )
        .sort(list(by))
    )
