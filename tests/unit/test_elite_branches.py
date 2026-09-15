"""M004's second branch: the accumulating lender, observed on a compact sandbox run.

The card's falsifiable prediction is what this module can defend on its own: an accumulating
branch — a lender that declares a default and takes the pledge — has to be *distinguishable* from
the V1 credit channel before any arm can compare their base contractions. So the tests here build
the branch, watch it fire, and check the transfer it makes. The arm comparison itself belongs to
the phase's runner, not to this file.

The two declared parameters are neutral exactly where V1's rule is:
``foreclosure_after_unserviced_months`` at ``0`` never declares a default, and
``foreclosure_land_share_of_pledge`` at ``0.0`` never takes land. At those values nothing new is
emitted, no balance moves, and the run is V1's run event for event — which is what the first test
holds the code to. Two controls follow it: an accumulating branch that has to fire (one unserviced
month, the whole pledge), and the same declaration with the share at zero, which has to declare
defaults and take nothing. A control that cannot fire fails here with the evidence it would have
needed, rather than passing quietly.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from late_ming_lab.actors.elites import EliteEventType
from late_ming_lab.actors.households import CohortEventType
from late_ming_lab.actors.ledger import DEBT_DELTA, LAND_DELTA
from late_ming_lab.analysis.distress import with_trigger_fields
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.evidence.parameters import (
    EliteParameters,
    core_default_elite_parameters,
    core_default_household_parameters,
)
from late_ming_lab.experiments.integrated import (
    IntegratedRun,
    IntegratedScenario,
    run_integrated_scenario,
)

COMPACT_CONFIG = SimulationConfig.model_validate({"tick_count": 60, "warmup_ticks": 12})

SCENARIO = IntegratedScenario(
    label="elite-branches-unit", dataset="toy", monthly_event_probability=0.4, severity_floor=0.6
)

#: The neutral parameter set: the fields are left at the values the class declares, which is what
#: every existing caller of ``EliteParameters`` gets.
NEUTRAL = core_default_elite_parameters()

#: The same two fields declared explicitly at their neutral values, so "the default is neutral" is
#: a measured comparison rather than a reading of the class.
DECLARED_NEUTRAL = NEUTRAL.model_copy(
    update={"foreclosure_after_unserviced_months": 0, "foreclosure_land_share_of_pledge": 0.0}
)

#: The declared accumulating branch: an obligation unserviced for one month is in default, and the
#: lender takes the whole pledge. Declared as the phase's positive control; nothing here claims
#: that this is how an elite behaved.
FORECLOSING = NEUTRAL.model_copy(
    update={"foreclosure_after_unserviced_months": 1, "foreclosure_land_share_of_pledge": 1.0}
)

#: The same declaration with the share at zero: defaults are declared, no land is ever taken. It
#: is the control that separates the term from the share, and it must stay distinguishable from
#: both the neutral values and the accumulating branch.
DECLARED_ONLY = NEUTRAL.model_copy(
    update={"foreclosure_after_unserviced_months": 1, "foreclosure_land_share_of_pledge": 0.0}
)

ELITE_DEFAULT = EliteEventType.DEFAULT
ELITE_FORECLOSURE = EliteEventType.FORECLOSURE
COHORT_FORECLOSURE = CohortEventType.FORECLOSURE.value
TAX_ASSESSMENT = "TAX_ASSESSMENT"

#: Every field each new event has to carry, as a number, under ``trigger``.
TRIGGER_FIELDS: dict[str, tuple[str, ...]] = {
    ELITE_DEFAULT: ("outstanding_tael", "months_unserviced"),
    ELITE_FORECLOSURE: (
        "mu_transferred",
        "pledge_mu",
        "settled_tael",
        "surplus_over_claim_tael",
        "land_mu",
        LAND_DELTA,
    ),
    COHORT_FORECLOSURE: (
        "mu_transferred",
        "pledge_mu",
        "settled_tael",
        "land_left_mu",
        "debt_tael",
        LAND_DELTA,
    ),
}

#: The fields the pairing test reconciles between the two sides of one transfer.
TRANSFER_FIELDS = (
    "mu_transferred",
    "pledge_mu",
    "settled_tael",
    "surplus_over_claim_tael",
    "land_left_mu",
    LAND_DELTA,
    DEBT_DELTA,
)

#: The declared collateral value of a mu, which the pledge and the settle-up are both read in.
LAND_REFERENCE_VALUE = core_default_household_parameters().land_reference_value_tael_per_mu

NEW_EVENTS = (ELITE_DEFAULT, ELITE_FORECLOSURE, COHORT_FORECLOSURE)


def _run(elite_parameters: EliteParameters | None = None) -> IntegratedRun:
    overrides: dict[str, object] = (
        {} if elite_parameters is None else {"EliteParameters": elite_parameters}
    )
    return run_integrated_scenario(SCENARIO, config=COMPACT_CONFIG, parameter_sets=overrides)


@pytest.fixture(scope="module")
def neutral_run() -> IntegratedRun:
    """The run every existing caller gets: the new fields left at the class defaults."""
    return _run()


@pytest.fixture(scope="module")
def declared_neutral_run() -> IntegratedRun:
    """The same run with the neutral values declared field by field."""
    return _run(DECLARED_NEUTRAL)


@pytest.fixture(scope="module")
def foreclosure_run() -> IntegratedRun:
    """The declared accumulating branch."""
    return _run(FORECLOSING)


@pytest.fixture(scope="module")
def declared_only_run() -> IntegratedRun:
    """Defaults declared, the pledge never taken: the control that separates term from share."""
    return _run(DECLARED_ONLY)


def _event_count(run: IntegratedRun, event_type: str) -> int:
    return run.result.events.filter(pl.col("event_type") == event_type).height


def _total_land(run: IntegratedRun) -> float:
    return sum(cohort.land_mu for cohort in run.economy.population) + (
        run.economy.elites.total_land_mu
    )


def _branch_evidence(run: IntegratedRun) -> str:
    """What the log and the ledgers say, for a message that must name why nothing fired."""
    events = run.result.events
    counts = {
        row["event_type"]: row["len"]
        for row in events.group_by("event_type").len().iter_rows(named=True)
    }
    return (
        f"ELITE_LOAN {counts.get(EliteEventType.LOAN_ISSUED, 0)}, "
        f"ELITE_DEFAULT {counts.get(ELITE_DEFAULT, 0)}, "
        f"ELITE_FORECLOSURE {counts.get(ELITE_FORECLOSURE, 0)}, "
        f"outstanding cohort debt {sum(c.debt_tael for c in run.economy.population):.3f} tael, "
        f"cohort land {sum(c.land_mu for c in run.economy.population):.3f} mu, "
        f"elite land {run.economy.elites.total_land_mu:.3f} mu"
    )


def _total(frame: pl.DataFrame, column: str) -> float:
    """One column's total as a plain float; an empty selection totals zero."""
    return float(frame.select(pl.col(column).sum().fill_null(0.0)).to_series().to_list()[0])


def _lowest(frame: pl.DataFrame, column: str) -> float:
    """One column's minimum as a plain float; an empty selection returns 0.0."""
    values = frame.select(pl.col(column).min()).to_series().to_list()
    return float(values[0]) if values[0] is not None else 0.0


def _last_assessment(run: IntegratedRun) -> pl.DataFrame:
    """The final month's assessment of every county, with its base fields as numbers."""
    assessments = with_trigger_fields(
        run.result.events.filter(pl.col("event_type") == TAX_ASSESSMENT),
        ("taxable_land_mu", "hidden_land_mu"),
    )
    final_tick = assessments["tick"].max()
    return assessments.filter(pl.col("tick") == final_tick)


def test_the_neutral_values_reproduce_the_v1_credit_rule(
    neutral_run: IntegratedRun, declared_neutral_run: IntegratedRun
) -> None:
    """At the neutral values the run is V1's run: nothing declared, nothing taken, nothing new."""
    events = neutral_run.result.events
    emitted = events.filter(pl.col("event_type").is_in(NEW_EVENTS))
    assert emitted.is_empty(), (
        f"the neutral values emitted {emitted.height} branch event(s): "
        + _branch_evidence(neutral_run)
    )
    assert declared_neutral_run.result.summary.simulation_digest == (
        neutral_run.result.summary.simulation_digest
    ), "the declared neutral values are not the values the class defaults to"
    assert declared_neutral_run.result.summary.event_count == neutral_run.result.summary.event_count
    assert _event_count(declared_neutral_run, EliteEventType.LOAN_ISSUED) == _event_count(
        neutral_run, EliteEventType.LOAN_ISSUED
    )
    assert _total_land(declared_neutral_run) == pytest.approx(_total_land(neutral_run), rel=1e-12)


def test_the_declared_branch_declares_a_default_and_takes_the_pledge(
    foreclosure_run: IntegratedRun,
) -> None:
    """The positive control fires, and the land it takes is the same land on both sides."""
    assert _event_count(foreclosure_run, ELITE_DEFAULT) > 0, (
        "the declared branch never declared a default, so the term was never reached: "
        + _branch_evidence(foreclosure_run)
    )
    moved = with_trigger_fields(foreclosure_run.result.events, TRANSFER_FIELDS)
    elite_rows = moved.filter(pl.col("event_type") == ELITE_FORECLOSURE)
    cohort_rows = moved.filter(pl.col("event_type") == COHORT_FORECLOSURE)
    assert elite_rows.height > 0, (
        "the declared branch declared no default that reached a pledge, so no land was taken: "
        + _branch_evidence(foreclosure_run)
    )
    assert cohort_rows.height == elite_rows.height, (
        "a foreclosure moves land from one ledger to the other, so the two events pair up"
    )
    out = elite_rows.group_by("tick").agg(pl.col("mu_transferred").sum().alias("out"))
    taken = cohort_rows.group_by("tick").agg(pl.col("mu_transferred").sum().alias("taken"))
    paired = (
        out.join(taken, on="tick", how="full", coalesce=True)
        .fill_null(0.0)
        .with_columns((pl.col("out") - pl.col("taken")).abs().alias("gap"))
    )
    assert _total(paired, "gap") < 1e-9, (
        "the mu the lender gained and the mu the cohort lost differ"
    )
    assert _total(elite_rows, LAND_DELTA) == pytest.approx(
        -_total(cohort_rows, LAND_DELTA), rel=1e-12
    )
    assert _total(cohort_rows, DEBT_DELTA) == pytest.approx(
        -_total(cohort_rows, "settled_tael"), rel=1e-12
    )
    assert bool((cohort_rows["mu_transferred"] <= cohort_rows["pledge_mu"] + 1e-9).all()), (
        "the lender takes the pledge or less; it never takes land the pledge did not cover"
    )
    assert _lowest(cohort_rows, "land_left_mu") >= 0.0
    land_value = elite_rows["mu_transferred"] * LAND_REFERENCE_VALUE
    assert bool((land_value >= elite_rows["settled_tael"] - 1e-9).all()), (
        "a foreclosure settled more of the claim than the land it took was worth"
    )
    assert _total(elite_rows, "surplus_over_claim_tael") > 0.0, (
        "no foreclosure left the lender anything above the claim it settled, so the pledge was "
        "not forfeit whole and the branch accumulates nothing"
    )


def test_each_new_event_carries_its_declared_trigger_fields(
    foreclosure_run: IntegratedRun,
) -> None:
    """Every field a reader needs is under ``trigger`` as a number, and names the other party."""
    events = foreclosure_run.result.events
    cohort_ids = {cohort.cohort_id for cohort in foreclosure_run.economy.population}
    elite_ids = {house.elite_id for house in foreclosure_run.economy.elites}
    for event_type, fields in TRIGGER_FIELDS.items():
        rows = events.filter(pl.col("event_type") == event_type)
        assert rows.height > 0, (
            f"{event_type} never fired, so its trigger fields were never exercised: "
            + _branch_evidence(foreclosure_run)
        )
        for raw in rows["trigger_json"]:
            trigger = json.loads(raw)
            for field in fields:
                assert field in trigger, f"{event_type} does not record {field}: {raw}"
                value = trigger[field]
                assert isinstance(value, int | float) and not isinstance(value, bool), (
                    f"{event_type}.{field} is {value!r}, which is not a number a reader can plot"
                )
        counterparties = {outcome.split(":", 1)[1] for outcome in rows["outcome"]}
        named = cohort_ids if event_type != COHORT_FORECLOSURE else elite_ids
        strangers = sorted(counterparties - named)
        assert counterparties <= named, (
            f"{event_type} names a party outside the run's ledgers: {strangers}"
        )


def test_the_share_decides_whether_land_moves_and_the_term_only_declares(
    neutral_run: IntegratedRun, declared_only_run: IntegratedRun
) -> None:
    """The two declarations are independent: a term without a share declares and takes nothing."""
    assert _event_count(declared_only_run, ELITE_DEFAULT) > 0, (
        "the declared term never declared a default: " + _branch_evidence(declared_only_run)
    )
    assert _event_count(declared_only_run, ELITE_FORECLOSURE) == 0
    assert _event_count(declared_only_run, COHORT_FORECLOSURE) == 0
    assert _total_land(declared_only_run) == pytest.approx(_total_land(neutral_run), rel=1e-12)


def test_total_land_is_conserved_where_the_log_does_not_let_it_go(
    neutral_run: IntegratedRun, foreclosure_run: IntegratedRun
) -> None:
    """Land is only ever transferred; the one outflow is the abandonment the log records."""
    for run in (neutral_run, foreclosure_run):
        moved = with_trigger_fields(run.result.events, (LAND_DELTA, "land_abandoned_mu"))
        cohort_ids = {cohort.cohort_id for cohort in run.economy.population}
        elite_ids = {house.elite_id for house in run.economy.elites}
        land = moved.filter(pl.col(LAND_DELTA) != 0.0)
        assert set(land["agent_id"]) <= cohort_ids | elite_ids, (
            "land left the ledgers that hold it: "
            f"{sorted(set(land['agent_id']) - cohort_ids - elite_ids)}"
        )
        abandoned = _total(
            moved.filter(pl.col("event_type") == CohortEventType.MIGRATION_DEPARTURE.value),
            "land_abandoned_mu",
        )
        cohort_rows = moved.filter(pl.col("agent_id").is_in(sorted(cohort_ids)))
        elite_rows = moved.filter(pl.col("agent_id").is_in(sorted(elite_ids)))
        cohort_delta = _total(cohort_rows, LAND_DELTA)
        elite_delta = _total(elite_rows, LAND_DELTA)
        assert cohort_delta + elite_delta + abandoned == pytest.approx(0.0, abs=1e-6), (
            f"land moved without the log saying where: cohorts {cohort_delta}, elites "
            f"{elite_delta}, abandoned {abandoned}"
        )
    assert _total_land(foreclosure_run) == pytest.approx(_total_land(neutral_run), rel=1e-12), (
        "the branch moves land between ledgers; it does not create or destroy any"
    )


def test_the_land_the_branch_takes_leaves_the_countys_visible_base(
    neutral_run: IntegratedRun, foreclosure_run: IntegratedRun
) -> None:
    """The county's own assessment is where the base effect is recorded: less taxable land, more
    land it cannot see, because the land that moved is now an elite's and is hidden in part."""
    neutral = _last_assessment(neutral_run)
    branch = _last_assessment(foreclosure_run)
    assert set(neutral["region"]) == set(branch["region"]), "the two runs assess the same counties"
    assert _total(branch, "taxable_land_mu") < _total(neutral, "taxable_land_mu"), (
        "the accumulating branch contracted the county's visible base less than V1 did"
    )
    assert _total(branch, "hidden_land_mu") > _total(neutral, "hidden_land_mu"), (
        "the land the branch took did not raise the land the county cannot see"
    )
