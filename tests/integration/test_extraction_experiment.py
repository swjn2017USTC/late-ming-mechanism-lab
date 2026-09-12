"""The extraction-pressure experiment: the data, and what the phase refuses to claim.

The tests here check that the sweep runs, that the numbers it reports behave mechanically as
declared (a higher pressure assesses a higher quota), that the two policy families differ, and
that no verdict column exists. They deliberately do **not** assert any relationship between
pressure and receipts beyond the declared mechanics: whether receipts collapse while pressure
rises is a hypothesis for a later phase, and P05 supplies the data rather than the claim.
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.experiments.extraction import (
    CURVE_COLUMNS,
    ExtractionResults,
    ExtractionScenario,
    default_pressures,
    run_extraction_experiment,
    run_extraction_scenario,
)

SHORT_CONFIG = SimulationConfig.model_validate({"tick_count": 72, "warmup_ticks": 12})


@pytest.fixture(scope="module")
def sweep() -> ExtractionResults:
    scenarios = (
        *(
            ExtractionScenario(
                label=f"fixed-{pressure:g}",
                nominal_pressure=pressure,
                policy="fixed",
                monthly_event_probability=0.5,
                severity_floor=0.6,
            )
            for pressure in (0.01, 0.08, 0.64)
        ),
        ExtractionScenario(
            label="escalating-0.08",
            nominal_pressure=0.08,
            policy="escalating",
            monthly_event_probability=0.5,
            severity_floor=0.6,
        ),
    )
    return run_extraction_experiment(config=SHORT_CONFIG, scenarios=scenarios)


def test_the_sweep_reports_measurements_and_nothing_else(sweep: ExtractionResults) -> None:
    curve = sweep.curve

    assert tuple(curve.columns) == CURVE_COLUMNS
    for verdict_like in ("inversion", "verdict", "hypothesis", "conclusion", "collapsed"):
        assert verdict_like not in curve.columns
    assert curve.height == 4
    assert not curve.select(["nominal_quota_tael", "actual_receipts_tael"]).is_empty()


def test_a_higher_nominal_pressure_assesses_a_higher_quota(sweep: ExtractionResults) -> None:
    quotas = (
        sweep.curve.filter(sweep.curve["policy"] == "fixed")
        .sort("nominal_pressure")["nominal_quota_tael"]
        .to_list()
    )

    assert quotas == sorted(quotas)
    assert quotas[-1] > quotas[0] * 10.0, "the sweep must actually span a wide range"


def test_the_fiscal_ledger_balances_under_every_pressure(sweep: ExtractionResults) -> None:
    curve = sweep.curve

    for row in curve.iter_rows(named=True):
        assert row["actual_receipts_tael"] >= 0.0
        assert row["collection_cost_tael"] >= 0.0
        assert row["net_receipts_tael"] == pytest.approx(
            row["actual_receipts_tael"] - row["collection_cost_tael"], abs=1e-6
        )
        assert row["arrears_tael"] >= 0.0
        assert row["mean_collection_effort"] <= 1.0


def test_extraction_pressure_leaves_measurable_traces_in_households(
    sweep: ExtractionResults,
) -> None:
    curve = sweep.curve.sort("nominal_pressure")
    hardest = curve.row(-1, named=True)

    assert hardest["share_permanent_migration_eligible"] >= 0.0
    assert hardest["land_sold_for_tax_mu"] >= 0.0
    assert hardest["movables_sold_for_tax_tael"] >= 0.0
    assert hardest["mean_arrears_per_household_tael"] >= 0.0
    assert curve.select("actual_receipts_tael").sum().item() > 0.0


def test_the_policy_changes_the_outcome_at_the_same_nominal_pressure(
    sweep: ExtractionResults,
) -> None:
    fixed = sweep.curve.filter(
        (sweep.curve["policy"] == "fixed") & (sweep.curve["nominal_pressure"] == 0.08)
    ).row(0, named=True)
    escalating = sweep.curve.filter(sweep.curve["policy"] == "escalating").row(0, named=True)

    assert escalating["scenario"] != fixed["scenario"]
    assert escalating["mean_assessment_rate"] > fixed["mean_assessment_rate"]
    assert escalating["mean_collection_effort"] >= fixed["mean_collection_effort"]


def test_escalation_responds_to_the_arrears_stock_at_the_call_site() -> None:
    """A policy that reads arrears must be driven by a meaningful arrears ratio.

    The unit tests exercise the policy object; this one checks the system wires it to something
    that actually moves, because passing the arrears as their own denominator turns every
    escalating policy into a step function that fires once and then never changes.
    """
    from late_ming_lab.analysis.distress import with_trigger_fields

    def rates_for(policy: str) -> tuple[float, float]:
        run = run_extraction_scenario(
            ExtractionScenario(
                label=f"{policy}-probe",
                nominal_pressure=0.01,
                policy=policy,
                monthly_event_probability=0.5,
                severity_floor=0.6,
            ),
            config=SHORT_CONFIG,
        )
        rates = with_trigger_fields(
            run.result.events.filter(run.result.events["event_type"] == "TAX_ASSESSMENT"),
            ("assessment_rate",),
        )
        extremes = rates.select(
            pl.col("assessment_rate").min().alias("lowest"),
            pl.col("assessment_rate").max().alias("highest"),
        ).row(0, named=True)
        return float(extremes["lowest"] or 0.0), float(extremes["highest"] or 0.0)

    fixed_low, fixed_high = rates_for("fixed")
    escalating_low, escalating_high = rates_for("escalating")

    assert fixed_low == fixed_high, "a fixed policy assesses the same rate however arrears move"
    assert escalating_high > escalating_low, (
        "an escalating policy must raise its rate as arrears accumulate"
    )


def test_the_default_sweep_starts_light_and_ends_heavy() -> None:
    pressures = default_pressures()

    assert pressures == tuple(sorted(pressures))
    assert pressures[0] < pressures[-1] / 10.0
