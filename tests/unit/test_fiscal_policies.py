"""Extraction policy rules: two answers, kept separate.

A policy says how much is assessed and how much effort is spent collecting it. The tests here
check that the two are genuinely separate: escalation changes the effort, a fixed policy does not,
and the effort ceiling and the coercion floor bind where they should.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from late_ming_lab.evidence.parameters import core_default_fiscal_parameters
from late_ming_lab.policies.fiscal import (
    ArrearsEscalation,
    ExtractionPolicy,
    FixedExtraction,
)


def test_both_policies_satisfy_the_contract() -> None:
    assert isinstance(FixedExtraction(effort=0.5), ExtractionPolicy)
    assert isinstance(
        ArrearsEscalation(base_effort=0.5, arrears_weight=0.5, effort_ceiling=1.0),
        ExtractionPolicy,
    )


def test_a_fixed_policy_ignores_the_arrears_it_creates() -> None:
    policy = FixedExtraction(effort=0.4)

    for arrears in (0.0, 100.0, 100_000.0):
        assert policy.assessment_rate(
            nominal_pressure=0.02, arrears_tael=arrears, quota_tael=1_000.0
        ) == pytest.approx(0.02)
        assert policy.collection_effort(
            nominal_pressure=0.02,
            arrears_tael=arrears,
            quota_tael=1_000.0,
            coercion_capacity=0.9,
        ) == pytest.approx(0.4)


def test_escalation_raises_the_rate_and_the_effort_with_the_arrears() -> None:
    policy = ArrearsEscalation(base_effort=0.4, arrears_weight=0.5, effort_ceiling=0.9)

    untouched = policy.assessment_rate(nominal_pressure=0.02, arrears_tael=0.0, quota_tael=1_000.0)
    pressed = policy.assessment_rate(
        nominal_pressure=0.02, arrears_tael=1_000.0, quota_tael=1_000.0
    )
    effort_untouched = policy.collection_effort(
        nominal_pressure=0.02, arrears_tael=0.0, quota_tael=1_000.0, coercion_capacity=0.2
    )
    effort_pressed = policy.collection_effort(
        nominal_pressure=0.02, arrears_tael=1_000.0, quota_tael=1_000.0, coercion_capacity=0.2
    )

    assert untouched == pytest.approx(0.02)
    assert pressed > untouched
    assert effort_pressed > effort_untouched
    assert effort_pressed <= policy.effort_ceiling


def test_escalation_is_bounded_by_the_ceiling_and_floored_by_coercion() -> None:
    policy = ArrearsEscalation(base_effort=0.1, arrears_weight=10.0, effort_ceiling=0.8)

    effort = policy.collection_effort(
        nominal_pressure=0.05, arrears_tael=1e9, quota_tael=1.0, coercion_capacity=0.5
    )
    floored = ArrearsEscalation(
        base_effort=0.2, arrears_weight=0.0, effort_ceiling=0.8
    ).collection_effort(
        nominal_pressure=0.05, arrears_tael=0.0, quota_tael=1_000.0, coercion_capacity=0.6
    )

    assert effort == pytest.approx(0.8), "effort cannot exceed the declared ceiling"
    assert floored == pytest.approx(0.6), "a coercive apparatus works at least at its capacity"


def test_a_policy_cannot_promise_more_than_full_effort() -> None:
    with pytest.raises(ValidationError):
        FixedExtraction(effort=1.5)
    with pytest.raises(ValidationError):
        ArrearsEscalation(base_effort=0.5, arrears_weight=0.5, effort_ceiling=0.0)


def test_fiscal_parameter_helpers_behave_as_declared() -> None:
    parameters = core_default_fiscal_parameters()

    assert parameters.provenance.is_assumption
    assert parameters.hidden_land_share(information_capacity=1.0) == 0.0
    assert parameters.hidden_land_share(information_capacity=0.0) == pytest.approx(
        parameters.elite_hidden_land_share
    )
    assert parameters.hidden_land_share(information_capacity=0.5) < (
        parameters.hidden_land_share(information_capacity=0.0)
    )

    good_logistics = parameters.collection_cost_tael(
        effort=0.5, quota_tael=1_000.0, logistics_capacity=1.0
    )
    poor_logistics = parameters.collection_cost_tael(
        effort=0.5, quota_tael=1_000.0, logistics_capacity=0.1
    )
    assert poor_logistics > good_logistics

    relief = parameters.relief_cost_tael(released_shi=100.0, logistics_capacity=0.5)
    assert relief == pytest.approx(100.0 * parameters.relief_logistics_cost_per_shi_tael / 0.5)

    # The declared floor keeps a county with no logistics at all from dividing by zero.
    floored = parameters.relief_cost_tael(released_shi=100.0, logistics_capacity=0.0)
    assert floored == pytest.approx(
        100.0
        * parameters.relief_logistics_cost_per_shi_tael
        / parameters.collection_cost_logistics_floor
    )
    with pytest.raises(ValueError, match="information capacity"):
        parameters.hidden_land_share(information_capacity=1.5)
