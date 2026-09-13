"""P10 outcome measures, against a real compact run of the wired sandbox.

One scenario is run once and every test in the module reads it, because the measures are reductions
of a whole run rather than of a fixture: a hand-built log would only show that the reductions agree
with themselves. The tests defend the observable contract of the mapping — the keys are there and
finite, the breakdown flag and the breakdown tick cannot disagree, the two connectivity shares are
shares, and the tax-base trajectory really is annual.
"""

from __future__ import annotations

import math

import polars as pl
import pytest

from late_ming_lab.analysis.governance import governance_indicators
from late_ming_lab.analysis.outcomes import (
    GovernanceTimeline,
    governance_timeline,
    outcome_frames,
    outcome_scalars,
)
from late_ming_lab.core.clock import MONTHS_PER_YEAR
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.experiments.integrated import (
    IntegratedRun,
    IntegratedScenario,
    run_integrated_scenario,
)

COMPACT_CONFIG = SimulationConfig.model_validate({"tick_count": 60, "warmup_ticks": 12})

SCENARIO = IntegratedScenario(
    label="outcomes-unit", dataset="toy", monthly_event_probability=0.4, severity_floor=0.6
)

#: The keys `outcome_scalars` promises, pinned here so a rename cannot pass unnoticed.
REQUIRED_SCALARS = (
    "breakdown",
    "time_to_breakdown",
    "indicators_crossed_end",
    "tax_base_end_mu",
    "tax_base_change_mu",
    "receipts_over_quota_total",
    "households_departed",
    "households_exited",
    "migration_net_node_min",
    "migration_net_node_max",
    "market_active_link_share",
    "market_largest_component_share",
    "military_pay_arrears_end_tael",
    "military_pay_arrears_max_tael",
    "largest_band_share_max",
    "largest_band_share_end",
    "bands_at_end",
    "band_merges",
    "elite_loans",
    "suppressions",
    "trade_shipments",
)


@pytest.fixture(scope="module")
def compact_run() -> IntegratedRun:
    return run_integrated_scenario(SCENARIO, config=COMPACT_CONFIG)


@pytest.fixture(scope="module")
def scalars(compact_run: IntegratedRun) -> dict[str, float]:
    return outcome_scalars(
        compact_run.result.events,
        thresholds=compact_run.thresholds,
        population_adults=compact_run.starting_adults,
        starting_households=compact_run.starting_households,
        trade_graph=compact_run.economy.graphs.trade,
    )


@pytest.fixture(scope="module")
def timeline(compact_run: IntegratedRun) -> GovernanceTimeline:
    return governance_timeline(
        compact_run.result.events,
        thresholds=compact_run.thresholds,
        population_adults=compact_run.starting_adults,
        starting_households=compact_run.starting_households,
    )


def test_every_scalar_is_present_and_finite(scalars: dict[str, float]) -> None:
    assert set(REQUIRED_SCALARS) <= set(scalars)
    for key in REQUIRED_SCALARS:
        assert math.isfinite(scalars[key]), f"{key} is not a finite number"


def test_the_breakdown_flag_agrees_with_the_breakdown_tick(scalars: dict[str, float]) -> None:
    expected = 1.0 if scalars["time_to_breakdown"] >= 0.0 else 0.0
    assert scalars["breakdown"] == expected


def test_connectivity_is_a_pair_of_shares(
    scalars: dict[str, float], compact_run: IntegratedRun
) -> None:
    nodes = compact_run.economy.graphs.trade.number_of_nodes()
    assert 0.0 <= scalars["market_active_link_share"] <= 1.0
    assert 0.0 <= scalars["market_largest_component_share"] <= 1.0
    assert scalars["market_largest_component_share"] >= 1.0 / nodes


def test_the_two_migration_extremes_are_ordered(scalars: dict[str, float]) -> None:
    assert scalars["migration_net_node_min"] <= scalars["migration_net_node_max"]


def test_the_tax_base_frame_is_one_row_per_year(compact_run: IntegratedRun) -> None:
    frame = outcome_frames(compact_run.result.events, trade_graph=compact_run.economy.graphs.trade)[
        "tax_base"
    ]
    years = compact_run.result.events.select(
        (pl.col("tick") // MONTHS_PER_YEAR).alias("year_index")
    )["year_index"].n_unique()
    assert frame.height == years
    assert frame["year"].n_unique() == frame.height
    assert frame["year"].min() == 1625
    assert float(frame.select(pl.col("taxable_land_mu").min()).item()) > 0.0


def test_the_timeline_ends_on_the_indicators_own_count(
    compact_run: IntegratedRun, timeline: GovernanceTimeline
) -> None:
    assert len(timeline.ticks) == len(timeline.crossed_counts)
    final = governance_indicators(
        compact_run.result.events.filter(pl.col("tick") <= timeline.ticks[-1]),
        thresholds=compact_run.thresholds,
        population_adults=compact_run.starting_adults,
        starting_households=compact_run.starting_households,
    )
    assert timeline.crossed_counts[-1] == int(final.filter(pl.col("crossed")).height)
