"""The relief-constraint chain: what held each county's release down, read off a real run.

`relief_coverage` says how much a county released and cannot say why it was not more: an empty
granary, a treasury that could not fill it, a logistics ceiling, or an eligibility threshold that
admitted nobody. The sandbox is run once and every test reads the same log, because the question is
a property of a whole run rather than of a hand-built county. These tests defend the observable
contract of the record: one row per county per tick including the months nothing was released,
every bound present and numeric, the released quantities unchanged, and a binding constraint drawn
from the declared tokens.
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.analysis.distress import with_trigger_fields
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.experiments.integrated import (
    IntegratedRun,
    IntegratedScenario,
    run_integrated_scenario,
)
from late_ming_lab.systems.fiscal import RELIEF_CONSTRAINT_EVENT

COMPACT_CONFIG = SimulationConfig.model_validate({"tick_count": 60, "warmup_ticks": 12})

SCENARIO = IntegratedScenario(
    label="relief-chain-unit", dataset="toy", monthly_event_probability=0.4, severity_floor=0.6
)

#: The release the record has to account for, named here the way the government layer names it.
OFFICIAL_RELIEF_EVENT = "OFFICIAL_RELIEF"

#: And the county's own monthly record, which fixes how many county-ticks the run has.
COUNTY_STATE_EVENT = "COUNTY_STATE"

#: The trigger contract `RELIEF_CONSTRAINT` promises, pinned so a rename cannot pass unnoticed.
CONSTRAINT_FIELDS = (
    "need_shi",
    "eligible_households",
    "eligible_adults",
    "grain_stock_shi",
    "treasury_tael",
    "capacity_relief",
    "demand_shi",
    "released_shi",
    "stock_bound_shi",
    "capacity_bound_shi",
    "eligibility_bound_shi",
    "unmet_after_shi",
)

#: The only tokens `outcome` may hold; anything else is a constraint nobody can read off.
BINDING_CONSTRAINTS = ("stock", "silver", "capacity", "eligibility", "none")


@pytest.fixture(scope="module")
def compact_run() -> IntegratedRun:
    return run_integrated_scenario(SCENARIO, config=COMPACT_CONFIG)


@pytest.fixture(scope="module")
def constraints(compact_run: IntegratedRun) -> pl.DataFrame:
    """Every relief-constraint row of the run, with its trigger fields as numeric columns."""
    rows = compact_run.result.events.filter(pl.col("event_type") == RELIEF_CONSTRAINT_EVENT)
    return with_trigger_fields(rows, CONSTRAINT_FIELDS)


def test_one_row_is_recorded_for_every_county_on_every_tick(
    compact_run: IntegratedRun, constraints: pl.DataFrame
) -> None:
    assert constraints.height > 0, "the relief phase must record its constraint every tick"
    book = compact_run.result.events.filter(pl.col("event_type") == COUNTY_STATE_EVENT)
    expected = set(book.select("tick", "region").iter_rows())
    recorded = constraints.select("tick", "region").rows()

    assert len(recorded) == len(set(recorded)), "a county recorded two constraints in one tick"
    assert set(recorded) == expected, "every county-tick must carry exactly one constraint record"


def test_every_bound_is_present_and_numeric(constraints: pl.DataFrame) -> None:
    for field in CONSTRAINT_FIELDS:
        matched = constraints["trigger_json"].str.json_path_match(f"$.{field}").cast(pl.Float64)
        assert matched.null_count() == 0, f"{field} is missing from a relief-constraint row"
        assert matched.is_finite().all(), f"{field} is not a finite number"
        assert constraints[field].dtype == pl.Float64, f"{field} is not a numeric column"


def test_the_record_adds_up_to_exactly_the_relief_that_was_released(
    compact_run: IntegratedRun, constraints: pl.DataFrame
) -> None:
    released = (
        compact_run.result.events.filter(pl.col("event_type") == OFFICIAL_RELIEF_EVENT)
        .pipe(with_trigger_fields, ("released_shi",))["released_shi"]
        .sum()
    )

    assert released > 0.0, "the fixture must actually release relief for this comparison to bite"
    assert constraints["released_shi"].sum() == pytest.approx(released, rel=1e-12)


def test_the_released_quantity_is_the_tightest_bound_the_record_reports(
    constraints: pl.DataFrame,
) -> None:
    tightest = constraints.select(
        pl.min_horizontal("stock_bound_shi", "capacity_bound_shi", "eligibility_bound_shi").alias(
            "tightest"
        )
    )["tightest"]

    assert (constraints["released_shi"] >= 0.0).all()
    assert constraints["released_shi"].to_list() == pytest.approx(tightest.to_list(), rel=1e-9)


def test_the_binding_constraint_is_one_of_the_declared_tokens(constraints: pl.DataFrame) -> None:
    assert set(constraints["outcome"].unique()) <= set(BINDING_CONSTRAINTS)


def test_the_sandbox_actually_binds_something(constraints: pl.DataFrame) -> None:
    counts = constraints["outcome"].value_counts()

    assert counts.filter(pl.col("outcome") != "none").height > 0, (
        "no county-tick bound anything, so this instrumentation shows nothing: "
        f"{counts.sort('count', descending=True).to_dicts()}"
    )
