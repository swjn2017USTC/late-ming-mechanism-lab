"""Distress analysis: exact aggregation from the event log."""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.actors.households import CohortEventType, CopingStage
from late_ming_lab.analysis.distress import (
    DistressAnalysisError,
    cohort_distress,
    distress_distribution,
    with_trigger_fields,
)
from late_ming_lab.core.events import EventLogger

COHORT = "toy-sx-a:poor-smallholder"


def _frame() -> pl.DataFrame:
    logger = EventLogger(tick_count=3)
    logger.emit(
        tick=0,
        event_type=CohortEventType.LABOUR_INCOME.value,
        agent_id=COHORT,
        region="toy-sx-a",
        trigger={"grain_delta_shi": 40.0},
    )
    logger.emit(
        tick=0,
        event_type=CohortEventType.CONSUMPTION.value,
        agent_id=COHORT,
        region="toy-sx-a",
        trigger={
            "need_shi": 100.0,
            "floor_shi": 75.0,
            "consumed_shi": 90.0,
            "purchased_shi": 10.0,
            "unmet_shi": 0.0,
            "grain_delta_shi": -80.0,
        },
    )
    logger.emit(
        tick=1,
        event_type=CohortEventType.CONSUMPTION.value,
        agent_id=COHORT,
        region="toy-sx-a",
        trigger={
            "need_shi": 100.0,
            "floor_shi": 75.0,
            "consumed_shi": 40.0,
            "purchased_shi": 0.0,
            "unmet_shi": 35.0,
            "grain_delta_shi": -40.0,
        },
    )
    logger.emit(
        tick=1,
        event_type=CohortEventType.LAND_SALE.value,
        agent_id=COHORT,
        region="toy-sx-a",
        trigger={"land_sold_mu": 4.0, "proceeds_tael": 10.0, "land_delta_mu": -4.0},
    )
    logger.emit(
        tick=1,
        event_type=CohortEventType.BORROWING_REQUEST.value,
        agent_id=COHORT,
        region="toy-sx-a",
        trigger={"requested_tael": 5.0, "granted_tael": 3.0},
    )
    logger.emit(
        tick=2,
        event_type=CohortEventType.HARVEST.value,
        agent_id=COHORT,
        region="toy-sx-a",
        trigger={"harvested_shi": 500.0, "grain_delta_shi": 500.0},
    )
    logger.emit(
        tick=2,
        event_type=CohortEventType.COHORT_STATE.value,
        agent_id=COHORT,
        region="toy-sx-a",
        trigger={
            "households": 1450.0,
            "grain_shi": 420.0,
            "silver_tael": 13.0,
            "debt_tael": 3.0,
            "land_mu": 11600.0,
            "movable_assets_tael": 2900.0,
            "coping_stage_index": float(CopingStage.SELLING_LAND),
            "temporary_migration_eligible": 1.0,
            "permanent_migration_eligible": 1.0,
            "recruitment_eligible": 0.0,
        },
        outcome=CopingStage.SELLING_LAND.token,
    )
    return logger.to_frame()


def _attributes() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "cohort_id": [COHORT],
            "node_id": ["toy-sx-a"],
            "cohort_class": ["poor-smallholder"],
            "households": [1450.0],
        }
    )


def test_flows_are_summed_from_the_log() -> None:
    distress = cohort_distress(_frame(), attributes=_attributes())
    row = distress.row(0, named=True)

    assert row["need_shi"] == 200.0
    assert row["unmet_shi"] == 35.0
    assert row["unmet_ratio"] == pytest.approx(0.175)
    assert row["purchased_shi"] == 10.0
    assert row["harvested_shi"] == 500.0
    assert row["land_sold_mu"] == 4.0
    assert row["granted_tael"] == 3.0
    assert row["requested_tael"] == 5.0
    assert row["ever_below_floor"] is True


def test_final_state_comes_from_the_last_snapshot() -> None:
    row = cohort_distress(_frame(), attributes=_attributes()).row(0, named=True)

    assert row["final_grain_shi"] == 420.0
    assert row["final_debt_tael"] == 3.0
    assert row["final_stage"] == CopingStage.SELLING_LAND.token
    assert row["destitute"] is False
    assert row["sold_land_stage"] is True
    assert row["final_permanent_migration_eligible"] == 1.0
    assert row["final_recruitment_eligible"] == 0.0


def test_distribution_reports_shares_and_per_household_means() -> None:
    distress = cohort_distress(_frame(), attributes=_attributes())

    distribution = distress_distribution(distress, by=("cohort_class",))
    row = distribution.row(0, named=True)

    assert row["cohort_class"] == "poor-smallholder"
    assert row["cohorts"] == 1
    assert row["share_below_floor"] == 1.0
    assert row["share_destitute"] == 0.0
    assert row["mean_land_sold_mu_per_household"] == pytest.approx(4.0 / 1450.0)
    assert row["mean_borrowed_tael_per_household"] == pytest.approx(3.0 / 1450.0)


def test_absent_trigger_fields_read_as_zero() -> None:
    frame = with_trigger_fields(_frame(), ("never_recorded", "unmet_shi"))

    assert frame["never_recorded"].to_list() == [0.0] * frame.height
    assert frame["unmet_shi"].sum() == 35.0


def test_frames_without_triggers_or_snapshots_are_refused() -> None:
    with pytest.raises(DistressAnalysisError, match="trigger_json"):
        with_trigger_fields(pl.DataFrame({"event_type": ["TICK"]}), ("unmet_shi",))

    logger = EventLogger(tick_count=1)
    logger.emit(tick=0, event_type="TICK")
    with pytest.raises(DistressAnalysisError, match="COHORT_STATE"):
        cohort_distress(logger.to_frame())


def test_grouping_columns_must_exist() -> None:
    distress = cohort_distress(_frame(), attributes=_attributes())

    with pytest.raises(DistressAnalysisError, match="missing columns"):
        distress_distribution(distress, by=("scenario",))
