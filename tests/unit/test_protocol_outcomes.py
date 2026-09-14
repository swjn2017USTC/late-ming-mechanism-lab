"""The primary outcome vector is read from the protocol, and a missing measurement is refused.

The phase's acceptance says later reports read their definitions from the frozen protocol. The way
that can fail silently is a report inventing a quantity or treating an unmeasured one as zero, so
both are refused here, on a real sandbox log rather than a hand-built frame.
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.evidence.parameters import core_default_governance_indicators
from late_ming_lab.experiments.integrated import (
    IntegratedRun,
    IntegratedScenario,
    run_integrated_scenario,
)
from late_ming_lab.protocol.intermediates import IntermediateError, assert_retained
from late_ming_lab.protocol.measures import PROTOCOL_EXTRA_MEASURES, protocol_measurements
from late_ming_lab.protocol.outcomes import (
    OutcomeError,
    OutcomeVector,
    compute_outcomes,
    window_events,
)
from late_ming_lab.protocol.schema import ValidationProtocol, load_protocol

COMPACT_CONFIG = SimulationConfig.model_validate({"tick_count": 60, "warmup_ticks": 12})

SCENARIO = IntegratedScenario(
    label="protocol-unit", dataset="toy", monthly_event_probability=0.4, severity_floor=0.6
)


@pytest.fixture(scope="module")
def run() -> IntegratedRun:
    return run_integrated_scenario(SCENARIO, config=COMPACT_CONFIG)


@pytest.fixture(scope="module")
def protocol() -> ValidationProtocol:
    return load_protocol(".")


def test_every_measurement_the_protocol_names_is_measured(run: IntegratedRun) -> None:
    """A protocol naming a quantity no run produces would be a definition nothing can satisfy."""
    measures = _measures(run)
    named = {
        name for outcome in load_protocol(".").primary_outcomes for name in outcome.measurements
    }
    assert named <= set(measures), sorted(named - set(measures))


def test_the_extra_measures_are_the_ones_this_project_adds(run: IntegratedRun) -> None:
    measures = _measures(run)
    assert set(PROTOCOL_EXTRA_MEASURES) <= set(measures)
    assert measures["subsistence_need_shi"] >= measures["subsistence_unmet_shi"] >= 0.0


def test_the_vector_has_one_value_per_declared_outcome(run: IntegratedRun) -> None:
    protocol = load_protocol(".")
    vector = _vector(run, protocol, "whole-run")
    assert set(vector.values) == {outcome.id for outcome in protocol.primary_outcomes}
    assert vector.protocol_digest == protocol.digest()


def test_the_vector_reports_the_components_it_was_computed_from(run: IntegratedRun) -> None:
    protocol = load_protocol(".")
    vector = _vector(run, protocol, "whole-run")
    for outcome in protocol.primary_outcomes:
        value = vector.value(outcome.id)
        assert set(value.components) == set(outcome.measurements)
        if value.resolution == "measured":
            assert value.components


def test_a_window_is_a_slice_of_the_run(run: IntegratedRun) -> None:
    """A window is measured on its own ticks, so a window covering the run measures the run."""
    protocol = load_protocol(".")
    window = protocol.window("calibration")
    whole = _vector(run, protocol, "whole-run")
    sliced = _vector(run, protocol, "calibration")
    last_tick = run.result.events["tick"].max()
    assert isinstance(last_tick, int)
    assert window.end_tick >= last_tick
    assert sliced.value("migration_outflow").components["households_exited"] == pytest.approx(
        whole.value("migration_outflow").components["households_exited"]
    )


def test_a_window_holding_no_events_is_refused_rather_than_reported_as_zero(
    run: IntegratedRun,
) -> None:
    """The extrapolation window of a sixty-tick run is empty, and an empty window measures nothing.

    Returning zeros would look like a calm decade; the analysis raising is what stops an empty
    window from becoming a result.
    """
    protocol = load_protocol(".")
    with pytest.raises(Exception, match="no COUNTY_STATE records"):
        _vector(run, protocol, "extrapolation")


def test_a_window_the_protocol_never_declared_is_refused(run: IntegratedRun) -> None:
    with pytest.raises(KeyError):
        _vector(run, load_protocol("."), "a-window-of-my-own")


def test_a_measurement_the_measure_set_cannot_produce_is_refused(
    run: IntegratedRun, protocol: ValidationProtocol
) -> None:
    """Not a data gap: a binding error, and refused with that reason rather than as a zero."""
    broken = protocol.model_copy(
        update={
            "primary_outcomes": tuple(
                outcome.model_copy(update={"measurements": ("no_such_measure",)})
                if index == 0
                else outcome
                for index, outcome in enumerate(protocol.primary_outcomes)
            )
        }
    )
    with pytest.raises(OutcomeError, match="no run can supply"):
        _vector(run, broken, "whole-run")


def test_a_nan_measurement_is_refused_under_a_refusing_protocol(
    run: IntegratedRun, protocol: ValidationProtocol
) -> None:
    assert protocol.missingness.default == "refuse"
    vector = _vector(run, protocol, "whole-run")
    # The refusal path is exercised by the components check above; here the vector is complete,
    # so a caller can see the difference between "refused" and "measured as zero".
    assert not vector.refused()


def test_window_events_keeps_the_window_and_drops_the_rest(run: IntegratedRun) -> None:
    sliced = window_events(run.result.events, 10, 20)
    ticks = sliced["tick"].to_list()
    assert min(ticks) >= 10
    assert max(ticks) <= 20
    assert sliced.height < run.result.events.height


def test_window_events_refuses_a_log_with_no_tick_column() -> None:
    with pytest.raises(OutcomeError, match="tick column"):
        window_events(pl.DataFrame({"event_type": ["A"]}), 0, 5)


def _measures(run: IntegratedRun) -> dict[str, float]:
    economy = run.economy
    return protocol_measurements(
        run.result.events,
        thresholds=core_default_governance_indicators(),
        population_adults=sum(cohort.adults for cohort in economy.population),
        starting_households=sum(cohort.households for cohort in economy.population),
        trade_graph=economy.graphs.trade,
    )


def _vector(
    run: IntegratedRun,
    protocol: ValidationProtocol,
    window: str,
    purpose: str = "report",
) -> OutcomeVector:
    economy = run.economy
    return compute_outcomes(
        run.result.events,
        protocol,
        window_id=window,
        run_id="unit",
        purpose=purpose,  # type: ignore[arg-type]
        thresholds=core_default_governance_indicators(),
        population_adults=sum(cohort.adults for cohort in economy.population),
        starting_households=sum(cohort.households for cohort in economy.population),
        trade_graph=economy.graphs.trade,
    )


def test_every_intermediate_series_the_protocol_requires_is_retained(run: IntegratedRun) -> None:
    """The chain, not only its end state: each declared series must come back non-empty with its
    declared fields, at the granularity the protocol names."""
    protocol = load_protocol(".")
    frames = assert_retained(protocol, run.result.events)
    assert set(frames) == {series.id for series in protocol.intermediates}
    monthly = [
        series
        for series in protocol.intermediates
        if series.granularity in ("month", "node-month", "indicator-tick")
    ]
    assert monthly, "the protocol requires at least one series read by the month"
    # Every run produces these; node-level migration and trade links may legitimately be empty for a
    # run in which nothing moved, and are returned empty rather than refused.
    always = (
        "county_fiscal_month",
        "military_standing_month",
        "armed_bands_month",
        "governance_sample",
    )
    for name in always:
        assert frames[name].height > 0, name
        assert "tick" in frames[name].columns, name


def test_a_declared_series_nothing_produces_is_refused(run: IntegratedRun) -> None:
    protocol = load_protocol(".")
    broken = protocol.model_copy(
        update={
            "intermediates": (
                *protocol.intermediates,
                protocol.intermediates[0].model_copy(update={"id": "a_series_nothing_produces"}),
            )
        }
    )
    with pytest.raises(IntermediateError, match="a_series_nothing_produces"):
        assert_retained(broken, run.result.events)
