"""Climate interface: three modes, replay semantics and fail-closed coverage."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from late_ming_lab.core.clock import Month
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.rng import RngStream, RngStreams
from late_ming_lab.evidence.grades import DataProvenance
from late_ming_lab.networks.fixtures import toy_spatial_dataset
from late_ming_lab.networks.nodes import CountyNode
from late_ming_lab.systems.climate import (
    SERIES_COLUMNS,
    BaselineClimate,
    ClimateCoverageError,
    ClimateMode,
    ObservedHistoricalClimate,
    SyntheticClimate,
)

ASSUMED = DataProvenance.assumption("series used for a test")
SOURCED = DataProvenance.model_validate(
    {
        "grade": "B",
        "source_id": "monsoon-reconstruction-2019",
        "locator": "table 3, Shaanxi drought index",
        "note": "reconstructed drought index, normalized to severity",
    }
)

JANUARY_1625 = Month(year=1625, month=1)
FEBRUARY_1625 = Month(year=1625, month=2)


def _county(node_id: str) -> CountyNode:
    for node in toy_spatial_dataset().nodes:
        if node.node_id == node_id:
            return node
    raise AssertionError(f"unknown toy node {node_id}")


def _rng() -> np.random.Generator:
    return RngStreams(11).generator(RngStream.CLIMATE)


def _series(rows: list[tuple[str, int, int, float]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=list(SERIES_COLUMNS), orient="row")


def test_baseline_reports_no_anomaly_and_consumes_no_randomness() -> None:
    model = BaselineClimate()
    rng = _rng()
    before = rng.bit_generator.state

    sample = model.shock(node=_county("toy-sx-a"), month=JANUARY_1625, rng=rng)

    assert model.mode is ClimateMode.BASELINE
    assert (sample.severity, sample.draws) == (0.0, ())
    assert rng.bit_generator.state == before


def test_synthetic_draws_are_unconditional_so_counterfactuals_share_them() -> None:
    cautious = SyntheticClimate(monthly_event_probability=0.1, severity_floor=0.0)
    severe = SyntheticClimate(monthly_event_probability=0.9, severity_floor=0.5)
    node = _county("toy-sx-a")

    cautious_rng = np.random.default_rng(3)
    severe_rng = np.random.default_rng(3)
    cautious_sample = cautious.shock(node=node, month=JANUARY_1625, rng=cautious_rng)
    severe_sample = severe.shock(node=node, month=JANUARY_1625, rng=severe_rng)

    assert cautious_sample.draws == severe_sample.draws
    assert len(cautious_sample.draws) == 2

    reference = np.random.default_rng(3)
    reference.random()
    reference.random()
    assert cautious_rng.bit_generator.state == reference.bit_generator.state


def test_synthetic_severity_respects_its_parameters() -> None:
    node = _county("toy-hn-a")
    never = SyntheticClimate(monthly_event_probability=0.0, severity_floor=0.4)
    always = SyntheticClimate(monthly_event_probability=1.0, severity_floor=0.4)

    never_rng = _rng()
    always_rng = _rng()

    assert all(
        never.shock(node=node, month=JANUARY_1625, rng=never_rng).severity == 0.0 for _ in range(50)
    )
    assert all(
        0.4 <= always.shock(node=node, month=JANUARY_1625, rng=always_rng).severity <= 1.0
        for _ in range(50)
    )


def test_synthetic_is_reproducible_for_a_given_seed() -> None:
    node = _county("toy-sx-b")
    model = SyntheticClimate(monthly_event_probability=0.5, severity_floor=0.2)

    def run() -> list[float]:
        rng = _rng()
        return [model.shock(node=node, month=JANUARY_1625, rng=rng).severity for _ in range(20)]

    assert run() == run()


def test_observed_series_replays_recorded_values() -> None:
    series = _series(
        [
            ("toy-sx-a", 1625, 1, 0.7),
            ("toy-sx-a", 1625, 2, 0.0),
            ("toy-hn-a", 1625, 1, 0.2),
        ]
    )
    model = ObservedHistoricalClimate.from_frame(
        series, series_id="test-series", provenance=SOURCED
    )

    assert model.mode is ClimateMode.OBSERVED_HISTORICAL
    assert model.rule_version == "climate-observed-v1"
    assert len(model) == 3
    assert model.years == (1625,)
    assert model.shock(node=_county("toy-sx-a"), month=JANUARY_1625, rng=_rng()).severity == 0.7
    assert model.shock(node=_county("toy-hn-a"), month=JANUARY_1625, rng=_rng()).severity == 0.2


def test_observed_replay_is_independent_of_the_random_stream() -> None:
    series = _series([("toy-sx-a", 1625, 1, 0.42)])
    model = ObservedHistoricalClimate.from_frame(
        series, series_id="test-series", provenance=SOURCED
    )
    node = _county("toy-sx-a")

    first = model.shock(node=node, month=JANUARY_1625, rng=np.random.default_rng(1))
    second = model.shock(node=node, month=JANUARY_1625, rng=np.random.default_rng(999))

    assert first == second
    assert first.draws == ()


def test_observed_series_fails_closed_on_a_gap() -> None:
    model = ObservedHistoricalClimate.from_frame(
        _series([("toy-sx-a", 1625, 1, 0.7)]), series_id="gappy", provenance=SOURCED
    )

    with pytest.raises(ClimateCoverageError, match="no value for toy-sx-a 1625-02"):
        model.shock(node=_county("toy-sx-a"), month=FEBRUARY_1625, rng=_rng())


def test_invented_series_is_not_an_observation() -> None:
    with pytest.raises(ValueError, match="belongs in the synthetic mode"):
        ObservedHistoricalClimate.from_frame(
            _series([("toy-sx-a", 1625, 1, 0.7)]), series_id="invented", provenance=ASSUMED
        )


@pytest.mark.parametrize(
    "rows",
    [
        [("toy-sx-a", 1625, 1, 1.4)],
        [("toy-sx-a", 1625, 1, -0.1)],
        [("toy-sx-a", 1625, 1, 0.5), ("toy-sx-a", 1625, 1, 0.6)],
    ],
)
def test_malformed_series_are_refused(rows: list[tuple[str, int, int, float]]) -> None:
    with pytest.raises(ValueError):
        ObservedHistoricalClimate.from_frame(_series(rows), series_id="broken", provenance=SOURCED)


def test_series_tables_must_carry_the_documented_columns() -> None:
    with pytest.raises(ValueError, match="missing columns: severity"):
        ObservedHistoricalClimate.from_frame(
            _series([("toy-sx-a", 1625, 1, 0.5)]).drop("severity"),
            series_id="broken",
            provenance=SOURCED,
        )


def test_modes_are_distinguishable_in_the_event_log() -> None:
    versions = {
        BaselineClimate().rule_version,
        SyntheticClimate(monthly_event_probability=0.1, severity_floor=0.0).rule_version,
        ObservedHistoricalClimate.from_frame(
            _series([("toy-sx-a", 1625, 1, 0.5)]), series_id="s", provenance=SOURCED
        ).rule_version,
    }

    assert len(versions) == 3


def test_climate_parameters_are_bounded() -> None:
    for payload in (
        {"monthly_event_probability": 1.5, "severity_floor": 0.0},
        {"monthly_event_probability": 0.1, "severity_floor": -0.1},
        {"monthly_event_probability": 0.1, "severity_floor": 1.4},
    ):
        with pytest.raises((ValueError, TypeError)):
            SyntheticClimate.model_validate(payload)


def test_config_seed_determines_the_synthetic_stream() -> None:
    config = SimulationConfig.model_validate({"tick_count": 4, "warmup_ticks": 1})
    node = _county("toy-sx-a")
    model = SyntheticClimate(monthly_event_probability=0.5, severity_floor=0.0)

    def run() -> list[float]:
        rng = RngStreams(config.root_seed).generator(RngStream.CLIMATE)
        return [model.shock(node=node, month=JANUARY_1625, rng=rng).severity for _ in range(10)]

    assert run() == run()
