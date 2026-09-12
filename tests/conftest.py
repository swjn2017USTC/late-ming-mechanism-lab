"""Shared fixtures: the toy dataset, its graphs and the default calendar.

P02 tests run against the shipped toy fixture and against datasets built inside the tests.
No historical dataset is committed, so no test can accidentally depend on one.
"""

from __future__ import annotations

import pytest

from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.networks.dataset import SpatialDataset
from late_ming_lab.networks.fixtures import toy_spatial_dataset
from late_ming_lab.networks.graphs import SpatialGraphs
from late_ming_lab.systems.calendar import AgriculturalCalendar, core_default_calendar


@pytest.fixture
def toy_dataset() -> SpatialDataset:
    return toy_spatial_dataset()


@pytest.fixture
def toy_graphs(toy_dataset: SpatialDataset) -> SpatialGraphs:
    return toy_dataset.build()


@pytest.fixture
def calendar() -> AgriculturalCalendar:
    return core_default_calendar()


@pytest.fixture
def short_config() -> SimulationConfig:
    return SimulationConfig.model_validate({"tick_count": 6, "warmup_ticks": 2})
