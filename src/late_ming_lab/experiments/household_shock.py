"""Toy shock experiment: modelled climate severity against cohort distress.

The experiment is an argument, and a small one: it holds endowments, calendar, parameters and
seed fixed, varies only the synthetic climate forcing, and reports how the distress
distribution changes. Nothing here is calibrated, and the severity axis is a *scenario
parameter*, not an estimate of any historical drought — the labels say what was assumed.

Two runs of the same scenario are identical, because nothing in the household layer is
stochastic: the only randomness in the chain is the climate draw, and P03's ladder is a
deterministic accounting rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.actors.fixtures import toy_cohort_population
from late_ming_lab.actors.households import HouseholdPopulation
from late_ming_lab.analysis.distress import (
    cohort_attributes,
    cohort_distress,
    distress_distribution,
)
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import KernelResult, SimulationKernel
from late_ming_lab.core.tick import System
from late_ming_lab.evidence.parameters import (
    CropParameters,
    HouseholdParameters,
    core_default_crop_parameters,
    core_default_household_parameters,
)
from late_ming_lab.networks.fixtures import toy_spatial_dataset
from late_ming_lab.storage.tables import write_table
from late_ming_lab.systems.agriculture import AgriculturalStateSystem, HarvestSystem
from late_ming_lab.systems.calendar import AgriculturalCalendar, core_default_calendar
from late_ming_lab.systems.climate import (
    BaselineClimate,
    ClimateModel,
    ClimateSystem,
    SyntheticClimate,
)
from late_ming_lab.systems.household_survival import (
    CohortBookkeepingSystem,
    ConsumptionSystem,
    DebtServiceSystem,
)

DISTRESS_ARTIFACT: Final[str] = "p03_cohort_distress.parquet"
DISTRIBUTION_ARTIFACT: Final[str] = "p03_shock_distribution.parquet"


@dataclass(frozen=True, slots=True)
class ShockScenario:
    """One point on the modelled severity axis."""

    label: str
    monthly_event_probability: float
    severity_floor: float

    @property
    def severity_index(self) -> float:
        """Nominal x-axis: the severity floor of an adverse anomaly, in [0, 1]."""
        return self.severity_floor


@dataclass(frozen=True, slots=True)
class ScenarioRun:
    scenario: ShockScenario
    result: KernelResult
    population: HouseholdPopulation


@dataclass(frozen=True, slots=True)
class ShockExperiment:
    runs: tuple[ScenarioRun, ...]
    distress: pl.DataFrame
    distribution: pl.DataFrame

    def write(self, output_dir: str | Path) -> tuple[Path, Path]:
        """Persist both tables as Parquet; the caller decides where."""
        directory = Path(output_dir)
        return (
            write_table(directory / DISTRESS_ARTIFACT, self.distress),
            write_table(directory / DISTRIBUTION_ARTIFACT, self.distribution),
        )


def default_scenarios() -> tuple[ShockScenario, ...]:
    """The reference run plus four modelled severity levels. Not a historical drought series."""
    return (
        ShockScenario("baseline", 0.0, 0.0),
        ShockScenario("mild", 0.15, 0.2),
        ShockScenario("moderate", 0.3, 0.4),
        ShockScenario("severe", 0.5, 0.6),
        ShockScenario("extreme", 0.7, 0.8),
    )


def climate_model_for(scenario: ShockScenario) -> ClimateModel:
    """The reference scenario uses the baseline mode; the others draw synthetic forcing."""
    if scenario.monthly_event_probability <= 0.0:
        return BaselineClimate()
    return SyntheticClimate(
        monthly_event_probability=scenario.monthly_event_probability,
        severity_floor=scenario.severity_floor,
    )


def run_scenario(
    scenario: ShockScenario,
    *,
    config: SimulationConfig | None = None,
    calendar: AgriculturalCalendar | None = None,
    crop_parameters: CropParameters | None = None,
    household_parameters: HouseholdParameters | None = None,
) -> ScenarioRun:
    """Run one scenario through the kernel with the household systems registered."""
    run_config = config or SimulationConfig()
    zone_calendar = calendar or core_default_calendar()
    crops = crop_parameters or core_default_crop_parameters()
    households = household_parameters or core_default_household_parameters()

    nodes = toy_spatial_dataset().build().nodes
    population = toy_cohort_population(nodes)
    systems: list[System] = [
        ClimateSystem(nodes, zone_calendar, climate_model_for(scenario)),
        AgriculturalStateSystem(population),
        HarvestSystem(population, zone_calendar, crops, households),
        ConsumptionSystem(population, households),
        DebtServiceSystem(population, households),
        CohortBookkeepingSystem(population, households),
    ]
    result = SimulationKernel(run_config, systems).run(run_label=scenario.label)
    return ScenarioRun(scenario=scenario, result=result, population=population)


def run_shock_experiment(
    *,
    scenarios: tuple[ShockScenario, ...] | None = None,
    config: SimulationConfig | None = None,
) -> ShockExperiment:
    """Run every scenario and aggregate the distress distribution."""
    chosen = scenarios or default_scenarios()
    runs = tuple(run_scenario(scenario, config=config) for scenario in chosen)
    distress = _distress_frame(runs)
    distribution = distress_distribution(
        distress, by=("scenario", "severity_index", "cohort_class")
    )
    return ShockExperiment(runs=runs, distress=distress, distribution=distribution)


def _distress_frame(runs: tuple[ScenarioRun, ...]) -> pl.DataFrame:
    frames = [
        cohort_distress(
            run.result.events, attributes=cohort_attributes(run.population)
        ).with_columns(
            pl.lit(run.scenario.label).alias("scenario"),
            pl.lit(run.scenario.severity_index).alias("severity_index"),
            pl.lit(run.scenario.monthly_event_probability).alias("monthly_event_probability"),
        )
        for run in runs
    ]
    return pl.concat(frames).sort(["severity_index", "cohort_class", "cohort_id"])
