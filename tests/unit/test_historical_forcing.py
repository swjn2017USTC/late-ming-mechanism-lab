"""The observed forcing: the annual index, the allocator, and the coverage refusals.

The tests are about the two things that can go wrong quietly: a severity that does not mean what the
card says it means, and a node-year the record does not cover sliding through as a zero. Everything
here runs on tables built in the test, so the arithmetic is checkable by hand.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from late_ming_lab.evidence.grades import DataProvenance, EvidenceGrade
from late_ming_lab.evidence.parameters import (
    HISTORICAL_CORE_MONTH_PROFILE,
    HistoricalCoreParameters,
    core_default_historical_core_parameters,
)
from late_ming_lab.historical.forcing import (
    AllocatedObservedClimate,
    AllocationMode,
    MissingCoveragePolicy,
    build_annual_index,
    severity_index,
)
from late_ming_lab.systems.climate import ClimateCoverageError

NODES = pl.DataFrame(
    [
        {
            "node_id": "a",
            "kind": "county",
            "latitude": 35.0,
            "longitude": 110.0,
        },
        {
            "node_id": "b",
            "kind": "county",
            "latitude": 36.0,
            "longitude": 111.0,
        },
        {
            "node_id": "ext",
            "kind": "external",
            "latitude": 37.0,
            "longitude": 112.0,
        },
    ]
)


def _parameters(**overrides: object) -> HistoricalCoreParameters:
    base = core_default_historical_core_parameters().model_dump()
    base.update(overrides)
    return HistoricalCoreParameters.model_validate(base)


def _events(rows: list[tuple[int, float, float, str, int]]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "year": year,
                "month": month,
                "longitude": longitude,
                "latitude": latitude,
                "category": category,
                "record_id": f"{year}-{index}",
            }
            for index, (year, latitude, longitude, category, month) in enumerate(rows)
        ]
    )


def test_the_index_saturates_and_caps() -> None:
    parameters = _parameters()
    assert severity_index(drought=0, famine=0, crop=0, pest=0, parameters=parameters) == 0.0
    # Half the drought saturation gives half the drought weight.
    assert severity_index(
        drought=3, famine=0, crop=0, pest=0, parameters=parameters
    ) == pytest.approx(0.5)
    # Everything at saturation is capped at one, and more events cannot exceed it.
    assert severity_index(drought=6, famine=4, crop=4, pest=4, parameters=parameters) == 1.0
    assert severity_index(drought=99, famine=99, crop=99, pest=99, parameters=parameters) == 1.0


def test_the_annual_index_covers_every_node_year_of_the_window() -> None:
    events = _events(
        [
            (1630, 35.0, 110.0, "30", 5),
            (1630, 35.0, 110.0, "35", 6),
            (1640, 36.0, 111.0, "33", 8),
        ]
    )
    annual = build_annual_index(NODES, events, _parameters())
    assert annual.height == 2 * 20  # two county nodes, twenty years
    a_1630 = annual.filter((pl.col("node_id") == "a") & (pl.col("year") == 1630)).row(0, named=True)
    assert a_1630["drought_events"] == 1
    assert a_1630["famine_events"] == 1
    assert a_1630["records"] is True
    assert a_1630["severity_index"] > 0.0
    a_1625 = annual.filter((pl.col("node_id") == "a") & (pl.col("year") == 1625)).row(0, named=True)
    assert a_1625["records"] is False  # the record says nothing about that node-year
    assert a_1625["severity_index"] == 0.0
    # the external node is not in the index: the model does not simulate its agriculture
    assert set(annual["node_id"].unique().to_list()) == {"a", "b"}


def test_a_refuse_policy_names_the_uncovered_node_years() -> None:
    events = _events([(1630, 35.0, 110.0, "30", 5)])
    annual = build_annual_index(NODES, events, _parameters())
    with pytest.raises(ClimateCoverageError) as error:
        AllocatedObservedClimate(
            annual,
            _parameters(),
            coverage_policy=MissingCoveragePolicy.REFUSE,
            series_id="test-series",
            provenance=DataProvenance(
                grade=EvidenceGrade.B, source_id="reaches-noaa", locator="test"
            ),
            max_reported_gaps=3,
        )
    message = str(error.value)
    assert "test-series" in message
    assert "39 node-year(s)" in message or "node-year(s) carry no record" in message
    assert "a 1625" in message


def test_a_zero_policy_imputes_and_counts() -> None:
    events = _events([(1630, 35.0, 110.0, "30", 5)])
    annual = build_annual_index(NODES, events, _parameters())
    climate = AllocatedObservedClimate(
        annual,
        _parameters(),
        coverage_policy=MissingCoveragePolicy.ZERO,
        series_id="test-series",
    )
    summary = climate.summary()
    assert summary["node_years"] == 40
    assert summary["imputed_node_years"] == 39
    assert summary["imputed_share"] == pytest.approx(39 / 40)


def test_the_allocator_keeps_the_annual_mean_and_the_peak_month() -> None:
    events = _events([(1630, 35.0, 110.0, "30", 5)])
    annual = build_annual_index(NODES, events, _parameters())
    seasonal = AllocatedObservedClimate(
        annual, _parameters(), series_id="test-series", allocation_mode=AllocationMode.SEASONAL
    )
    uniform = AllocatedObservedClimate(
        annual, _parameters(), series_id="test-series", allocation_mode=AllocationMode.UNIFORM
    )
    index = seasonal.annual_severity("a", 1630)
    peak_month = max(
        HISTORICAL_CORE_MONTH_PROFILE, key=lambda month: HISTORICAL_CORE_MONTH_PROFILE[month]
    )
    trough_month = min(
        HISTORICAL_CORE_MONTH_PROFILE, key=lambda month: HISTORICAL_CORE_MONTH_PROFILE[month]
    )
    assert seasonal.monthly_severity("a", 1630, peak_month) > index
    assert seasonal.monthly_severity("a", 1630, trough_month) < index
    # uniform means every month carries the annual value: the ablation removes the shape
    assert uniform.monthly_severity("a", 1630, peak_month) == pytest.approx(index)
    assert uniform.monthly_severity("a", 1630, trough_month) == pytest.approx(index)
    # monthly severities sum to twelve times the annual mean in both modes
    for climate in (seasonal, uniform):
        total = sum(climate.monthly_severity("a", 1630, month) for month in range(1, 13))
        assert total == pytest.approx(12 * index, rel=1e-6)


def test_monthly_severity_never_exceeds_one() -> None:
    events = _events([(1630, 35.0, 110.0, "30", 8), (1630, 35.0, 110.0, "35", 8)])
    annual = build_annual_index(NODES, events, _parameters())
    climate = AllocatedObservedClimate(annual, _parameters(), series_id="test-series")
    for month in range(1, 13):
        assert 0.0 <= climate.monthly_severity("a", 1630, month) <= 1.0


def test_a_node_year_outside_the_series_is_a_coverage_error() -> None:
    events = _events([(1630, 35.0, 110.0, "30", 5)])
    annual = build_annual_index(NODES, events, _parameters())
    climate = AllocatedObservedClimate(annual, _parameters(), series_id="test-series")
    with pytest.raises(ClimateCoverageError, match="a 1624"):
        climate.annual_severity("a", 1624)
    with pytest.raises(ClimateCoverageError, match="nowhere 1630"):
        climate.annual_severity("nowhere", 1630)


def test_an_assumed_series_is_refused() -> None:
    events = _events([(1630, 35.0, 110.0, "30", 5)])
    annual = build_annual_index(NODES, events, _parameters())
    with pytest.raises(ValueError, match="invented"):
        AllocatedObservedClimate(
            annual,
            _parameters(),
            series_id="test-series",
            provenance=DataProvenance.assumption("a series I made up"),
        )


def test_the_shock_interface_consumes_no_randomness() -> None:
    from late_ming_lab.core.clock import Month
    from late_ming_lab.networks.nodes import (
        AgrarianZone,
        CountyNode,
        NodeKind,
        Province,
    )

    events = _events([(1630, 35.0, 110.0, "30", 5)])
    annual = build_annual_index(NODES, events, _parameters())
    climate = AllocatedObservedClimate(annual, _parameters(), series_id="test-series")
    node = CountyNode(
        node_id="a",
        kind=NodeKind.COUNTY,
        province=Province.SHAANXI,
        zone=AgrarianZone.LOESS_DRYLAND,
        provenance=DataProvenance(grade=EvidenceGrade.B, source_id="chgis-v6", locator="test"),
    )
    month = Month(year=1630, month=5)
    before = np.random.default_rng(7).random()
    sample = climate.shock(node=node, month=month, rng=np.random.default_rng(7))
    after = np.random.default_rng(7).random()
    assert before == after
    assert sample.severity == pytest.approx(climate.monthly_severity("a", 1630, 5))
    assert sample.draws == ()
    assert climate.mode.value == "observed-historical"
