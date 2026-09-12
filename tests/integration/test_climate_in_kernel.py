"""Climate forcing inside the kernel: replay, ordering and mode independence."""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.events import Event, events_from_frame
from late_ming_lab.core.kernel import TICK_EVENT_TYPE, SimulationKernel
from late_ming_lab.evidence.grades import DataProvenance
from late_ming_lab.networks.dataset import SpatialDataset
from late_ming_lab.networks.fixtures import toy_spatial_dataset
from late_ming_lab.networks.nodes import AgrarianZone, SpatialNodes
from late_ming_lab.systems.calendar import AgriculturalCalendar, core_default_calendar
from late_ming_lab.systems.climate import (
    CLIMATE_EVENT_TYPE,
    SERIES_COLUMNS,
    BaselineClimate,
    ClimateSystem,
    ObservedHistoricalClimate,
    SyntheticClimate,
)

SOURCED = DataProvenance.model_validate(
    {
        "grade": "C",
        "source_id": "monsoon-reconstruction-2019",
        "locator": "table 3, Shaanxi drought index",
        "note": "reconstructed drought index, normalized to severity",
    }
)


def _climate_system(model: object) -> ClimateSystem:
    graphs = toy_spatial_dataset().build()
    return ClimateSystem(graphs.nodes, core_default_calendar(), model)  # type: ignore[arg-type]


def _run(model: object, config: SimulationConfig) -> list[Event]:
    result = SimulationKernel(config, [_climate_system(model)]).run()
    return list(events_from_frame(result.events))


def _climate(events: list[Event]) -> list[Event]:
    return [event for event in events if event.event_type == CLIMATE_EVENT_TYPE]


def test_climate_runs_in_the_first_tick_phase__for_counties_only(
    short_config: SimulationConfig,
) -> None:
    events = _run(SyntheticClimate(monthly_event_probability=0.5, severity_floor=0.2), short_config)
    counties = {node.node_id for node in toy_spatial_dataset().node_registry().counties}
    climate = _climate(events)

    assert len(climate) == short_config.tick_count * len(counties)
    assert {event.region for event in climate} == counties
    assert {event.phase for event in climate} == {"climate_update"}

    per_tick: dict[int, list[str]] = {}
    for event in events:
        per_tick.setdefault(event.tick, []).append(event.event_type)
    for tick, sequence in per_tick.items():
        assert sequence[0] == TICK_EVENT_TYPE, tick
        assert sequence[1:] == [CLIMATE_EVENT_TYPE] * len(counties), tick


def test_impact_is_severity_weighted_by_the_calendar(short_config: SimulationConfig) -> None:
    calendar = core_default_calendar()
    zones = {node.node_id: node.zone for node in toy_spatial_dataset().node_registry().counties}
    events = _run(SyntheticClimate(monthly_event_probability=0.8, severity_floor=0.3), short_config)

    for event in _climate(events):
        month = int(event.trigger["month_of_year"])
        zone = zones[event.region or ""]
        assert zone is not None
        assert event.trigger["sensitivity"] == calendar.shock_sensitivity(zone, month)
        assert event.trigger["impact"] == pytest.approx(
            event.trigger["severity"] * event.trigger["sensitivity"]
        )
        assert 0.0 <= event.trigger["impact"] <= 1.0


def test_synthetic_forcing_replays_for_the_same_seed(short_config: SimulationConfig) -> None:
    model = SyntheticClimate(monthly_event_probability=0.4, severity_floor=0.25)

    first = _run(model, short_config)
    second = _run(model, short_config)
    reseeded = _run(model, short_config.with_overrides(root_seed=short_config.root_seed + 1))

    assert [event.to_json() for event in first] == [event.to_json() for event in second]
    assert [event.trigger["severity"] for event in _climate(first)] != [
        event.trigger["severity"] for event in _climate(reseeded)
    ]


def test_observed_forcing_is_independent_of_the_seed(short_config: SimulationConfig) -> None:
    series = pl.DataFrame(
        [
            (
                node.node_id,
                1625,
                month,
                0.6 if node.node_id.endswith("a") and month % 3 == 0 else 0.0,
            )
            for node in toy_spatial_dataset().node_registry().counties
            for month in range(1, short_config.tick_count + 1)
        ],
        schema=list(SERIES_COLUMNS),
        orient="row",
    )
    model = ObservedHistoricalClimate.from_frame(series, series_id="toy-series", provenance=SOURCED)

    first = _run(model, short_config)
    reseeded = _run(model, short_config.with_overrides(root_seed=1234))

    assert [event.to_json() for event in first] == [event.to_json() for event in reseeded]
    assert {event.trigger["severity"] for event in _climate(first)} == {0.0, 0.6}
    assert all(event.rng_draw is None for event in _climate(first))
    assert all(event.rule_version == "climate-observed-v1" for event in _climate(first))


def test_observed_forcing_stops_at_the_first_month_the_series_does_not_cover(
    short_config: SimulationConfig,
) -> None:
    series = pl.DataFrame(
        [("toy-sx-a", 1625, 1, 0.3)],
        schema=list(SERIES_COLUMNS),
        orient="row",
    )
    model = ObservedHistoricalClimate.from_frame(series, series_id="gappy", provenance=SOURCED)

    with pytest.raises(ValueError, match="no value for"):
        _run(model, short_config)


def test_baseline_forcing_is_the_zero_reference(short_config: SimulationConfig) -> None:
    events = _climate(_run(BaselineClimate(), short_config))

    assert {event.trigger["severity"] for event in events} == {0.0}
    assert {event.trigger["impact"] for event in events} == {0.0}
    assert all(event.rng_draw is None for event in events)
    assert all(event.rule_version == "climate-baseline-v1" for event in events)


def test_a_zone_without_a_calendar_stops_the_run_before_it_starts(
    toy_dataset: SpatialDataset,
) -> None:
    calendar = core_default_calendar()
    loess_only = AgriculturalCalendar(zones=(calendar.calendar_for(AgrarianZone.LOESS_DRYLAND),))

    with pytest.raises(ValueError, match="no calendar for zone"):
        ClimateSystem(
            toy_dataset.node_registry(),
            loess_only,
            SyntheticClimate(monthly_event_probability=0.1, severity_floor=0.0),
        )


def test_a_boundary_only_node_set_is_refused() -> None:
    external = next(node for node in toy_spatial_dataset().nodes if not node.is_county)

    with pytest.raises(ValueError, match="at least one county node"):
        ClimateSystem(SpatialNodes((external,)), core_default_calendar(), BaselineClimate())
