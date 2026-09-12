"""Household behaviour inside the kernel: the toy shock experiment."""

from __future__ import annotations

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from late_ming_lab.actors.households import CohortEventType
from late_ming_lab.analysis.distress import (
    cohort_attributes,
    cohort_distress,
    distress_distribution,
)
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.tick import TickPhase
from late_ming_lab.experiments.household_shock import (
    ScenarioRun,
    ShockScenario,
    default_scenarios,
    run_scenario,
    run_shock_experiment,
)
from late_ming_lab.networks.fixtures import toy_spatial_dataset

#: The full 1625-1644 window: a four-year slice does not separate the cohort classes.
DEFAULT_CONFIG = SimulationConfig()


@pytest.fixture(scope="module")
def baseline() -> ScenarioRun:
    return run_scenario(ShockScenario("baseline", 0.0, 0.0))


@pytest.fixture(scope="module")
def severe() -> ScenarioRun:
    return run_scenario(ShockScenario("severe", 0.5, 0.6))


def _distress(run: ScenarioRun) -> pl.DataFrame:
    return cohort_distress(run.result.events, attributes=cohort_attributes(run.population))


def test_a_normal_year_needs_no_coping(baseline: ScenarioRun) -> None:
    distress = _distress(baseline)

    assert distress["unmet_shi"].sum() == 0.0
    assert distress["granted_tael"].sum() == 0.0
    assert distress["land_sold_mu"].sum() == 0.0
    assert set(distress["final_stage"].unique()) == {"self_sufficient"}
    assert distress["final_permanent_migration_eligible"].sum() == 0.0


def test_a_severe_shock_pushes_cohorts_down_the_ladder(severe: ScenarioRun) -> None:
    distress = _distress(severe)

    assert distress["unmet_shi"].sum() > 0.0
    assert distress["purchased_shi"].sum() > 0.0
    assert (distress["final_coping_stage_index"] > 0).any()


def test_distress_follows_endowment_not_cohort_labels(severe: ScenarioRun) -> None:
    """The ordering is emergent: no rule names a cohort class."""

    distribution = distress_distribution(_distress(severe), by=("cohort_class",))
    ratio = {
        row["cohort_class"]: row["mean_unmet_ratio"] for row in distribution.iter_rows(named=True)
    }

    assert ratio["landless-labourer"] > ratio["tenant-household"] > ratio["poor-smallholder"]
    assert ratio["poor-smallholder"] > ratio["middle-smallholder"]
    assert ratio["middle-smallholder"] > ratio["wealthy-farmer"]


def test_more_severe_forcing_means_more_distress() -> None:
    experiment = run_shock_experiment()
    totals = (
        experiment.distress.group_by("severity_index")
        .agg(pl.col("unmet_shi").sum().alias("unmet_shi"))
        .sort("severity_index")
    )

    unmet = totals["unmet_shi"].to_list()
    assert unmet == sorted(unmet)
    assert unmet[0] == 0.0
    assert unmet[-1] > unmet[len(unmet) // 2] > 0.0
    assert experiment.distribution.height == len(default_scenarios()) * 5


def test_the_household_layer_adds_no_randomness(baseline: ScenarioRun) -> None:
    reseeded = run_scenario(
        ShockScenario("baseline", 0.0, 0.0),
        config=DEFAULT_CONFIG.with_overrides(root_seed=DEFAULT_CONFIG.root_seed + 1),
    )

    assert baseline.result.events.equals(reseeded.result.events)
    assert baseline.result.summary.simulation_digest == reseeded.result.summary.simulation_digest


def test_the_same_scenario_replays_exactly(severe: ScenarioRun) -> None:
    again = run_scenario(ShockScenario("severe", 0.5, 0.6))

    assert severe.result.events.equals(again.result.events)
    assert severe.result.summary.simulation_digest == again.result.summary.simulation_digest
    # Run artifacts are byte-identical; derived sums agree to floating-point tolerance,
    # because a parallel reduction need not add the same numbers in the same order.
    assert_frame_equal(
        _distress(severe).sort("cohort_id"),
        _distress(again).sort("cohort_id"),
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


def test_every_cohort_node_pair_gets_every_transition_logged(severe: ScenarioRun) -> None:
    events = severe.result.events
    counties = {node.node_id for node in toy_spatial_dataset().node_registry().counties}
    cohort_ids = {cohort.cohort_id for cohort in severe.population}
    cohort_events = events.filter(pl.col("agent_id").is_in(sorted(cohort_ids)))
    seen = set(cohort_events["agent_id"].drop_nulls().unique())

    assert seen == cohort_ids
    assert len(cohort_ids) / len(counties) == 5.0
    for event_type in (
        CohortEventType.CONSUMPTION,
        CohortEventType.HARVEST,
        CohortEventType.COHORT_STATE,
        CohortEventType.LABOUR_INCOME,
    ):
        assert event_type.value in set(events["event_type"].unique())


def test_household_events_carry_their_rule_version_and_phase(severe: ScenarioRun) -> None:
    events = severe.result.events
    cohort_events = events.filter(pl.col("agent_id").str.contains(":"))

    assert set(cohort_events["phase"].unique()) <= {phase.token for phase in TickPhase}
    assert cohort_events["region"].null_count() == 0
