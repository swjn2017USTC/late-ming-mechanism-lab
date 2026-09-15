"""The three arrears rules: each fires when its declared condition holds, and none at neutral.

The recovery rule is why this file exists apart from the arms. On the historical core its condition
— a cohort that owes arrears *and* holds silver against its assessment — is never met,
because the households carrying arrears are the ones whose silver the liquidation ladder already
spent. That is a finding about the input, and it would be indistinguishable from dead code without a
test that drives the path deliberately, with a threshold chosen to exercise the rule rather than to
produce a result.
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.evidence.parameters import core_default_fiscal_parameters
from late_ming_lab.experiments.integrated import IntegratedScenario, run_integrated_scenario

SCENARIO = IntegratedScenario(
    label="arrears-rules", dataset="toy", monthly_event_probability=0.4, severity_floor=0.6
)
COMPACT = SimulationConfig.model_validate({"tick_count": 120, "warmup_ticks": 24})


def _relief(events: pl.DataFrame) -> pl.DataFrame:
    return events.filter(pl.col("event_type") == "ARREARS_RELIEF")


def _run(**overrides: float) -> pl.DataFrame:
    fiscal = core_default_fiscal_parameters().model_copy(update=overrides)
    return run_integrated_scenario(
        SCENARIO, config=COMPACT, parameter_sets={"FiscalParameters": fiscal}
    ).result.events


def test_no_rule_fires_at_its_neutral_value() -> None:
    """The neutral parameters are the V1 rule: an obligation is carried whole until it is paid."""
    events = _run()
    assert _relief(events).height == 0


def test_the_settlement_rule_fires_on_a_payment() -> None:
    events = _run(arrears_settlement_share=0.25)
    outcomes = set(_relief(events)["outcome"].to_list())
    assert outcomes == {"settlement"}
    removed = _relief(events)["trigger_json"].str.json_path_match("$.removed_tael").cast(pl.Float64)
    assert float(removed.sum() or 0.0) > 0.0


def test_the_remission_rule_fires_past_the_unmet_ratio_line() -> None:
    events = _run(arrears_remission_share=0.3, arrears_remission_unmet_ratio=0.05)
    outcomes = set(_relief(events)["outcome"].to_list())
    assert outcomes == {"remission"}


def test_the_recovery_rule_fires_when_its_condition_holds() -> None:
    """A code-path test, not a calibrated one: the threshold is set to exercise the rule.

    `arrears_recovery_silver_months=0.05` asks for a twentieth of a month's assessment in silver,
    which the compact sandbox's cohorts do hold while they owe arrears. The value is chosen to reach
    the path and is reported as such: the phase's finding is that the historical core never presents
    the condition at the declared threshold, not that the rule does not work.
    """
    events = _run(arrears_recovery_share=0.5, arrears_recovery_silver_months=0.05)
    recovery = _relief(events).filter(pl.col("outcome") == "recovery")
    assert recovery.height > 0, "the recovery path was not reached even at an exercising threshold"
    cleared = float(
        recovery["trigger_json"].str.json_path_match("$.removed_tael").cast(pl.Float64).sum() or 0.0
    )
    assert cleared > 0.0


def test_the_recovery_rule_fires_at_the_declared_threshold() -> None:
    """The rule is live at the value the arm declares, and the collection order is why.

    Placed after the silver step of the liquidation ladder the rule never fired: the ladder spends
    the household's silver on the current assessment first, so a cohort that owes arrears holds
    nothing by the time the rule looks. Collecting old obligations before the month's own assessment
    is the rule, not an implementation detail, and this test is what holds the order in place.
    """
    events = _run(arrears_recovery_share=0.5, arrears_recovery_silver_months=0.5)
    recovery = _relief(events).filter(pl.col("outcome") == "recovery")
    assert recovery.height > 0, "the recovery rule cannot fire: check where it is called from"


@pytest.mark.parametrize("outcome", ["settlement", "remission", "recovery"])
def test_every_rule_records_what_it_removed(outcome: str) -> None:
    """A rule that removed something without recording it could not be attributed from the log."""
    events = _run(
        arrears_settlement_share=0.25,
        arrears_remission_share=0.3,
        arrears_remission_unmet_ratio=0.05,
        arrears_recovery_share=0.5,
        arrears_recovery_silver_months=0.05,
    )
    rows = _relief(events).filter(pl.col("outcome") == outcome)
    assert rows.height > 0
    for field in ("removed_tael", "outstanding_after_tael", "assessed_tael", "unmet_ratio"):
        values = rows["trigger_json"].str.json_path_match(f"$.{field}").cast(pl.Float64)
        assert values.null_count() < rows.height, field
        assert (values >= 0.0).all(), field
