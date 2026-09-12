"""The integrated sandbox: two scenarios, 240 ticks, one metric row each.

This is the phase's deliverable as an experiment rather than as a claim. It runs the whole wired
model — climate, agriculture, households, market, credit, taxation, relief, migration, military
finance, desertion, armed bands, violence — over two spatial fixtures:

```text
toy      the five-county fixture every earlier phase developed against
medium   a twelve-county Shaanxi-Henan fixture that exercises the expandable schema
```

Each is run under a calm baseline and a synthetic climate shock, for 240 monthly ticks from 1625-01,
and each produces one row in the metric table plus the series behind every number in it. The
experiment reaches no verdict: it reports what the sandbox does when it is switched on, so that a
reader can ask the phase's only question — does this work as a conservative, explainable,
reproducible dynamical system? — against evidence rather than assertion.

Nothing here is tuned to reproduce the Ming collapse. The climate shock is a scenario parameter,
the fiscal pressure is a scenario parameter, and the metric table reports them next to the outcomes
so that no result can be read as a historical claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.analysis.governance import governance_indicators, governance_series
from late_ming_lab.analysis.integrated import (
    METRIC_COLUMNS,
    integrated_frames,
    integrated_metrics,
)
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import KernelResult, SimulationKernel
from late_ming_lab.evidence.parameters import (
    GovernanceIndicatorParameters,
    core_default_governance_indicators,
    core_default_military_parameters,
)
from late_ming_lab.experiments.assembly import Economy, build_toy_economy
from late_ming_lab.networks.dataset import SpatialDataset
from late_ming_lab.networks.fixtures import medium_spatial_dataset, toy_spatial_dataset
from late_ming_lab.storage.tables import write_table
from late_ming_lab.systems.climate import BaselineClimate, ClimateModel, SyntheticClimate

METRICS_ARTIFACT: Final[str] = "p07_integrated_metrics.parquet"
GOVERNANCE_ARTIFACT: Final[str] = "p07_governance_indicators.parquet"
GOVERNANCE_SERIES_ARTIFACT: Final[str] = "p07_governance_series.parquet"
DISTRESS_ARTIFACT: Final[str] = "p07_distress_distribution.parquet"
PRICE_ARTIFACT: Final[str] = "p07_price_dispersion.parquet"
MIGRATION_ARTIFACT: Final[str] = "p07_migration_flows.parquet"
MIGRATION_NODES_ARTIFACT: Final[str] = "p07_migration_nodes.parquet"
BANDS_ARTIFACT: Final[str] = "p07_band_series.parquet"
TAX_BASE_ARTIFACT: Final[str] = "p07_tax_base.parquet"

#: Frame name -> the key `integrated_frames` produces it under.
FRAME_KEYS: Final[dict[str, str]] = {
    "distress": "distress_distribution",
    "price": "price_dispersion",
    "flows": "migration_flows",
    "nodes": "migration_nodes",
    "bands": "band_series",
    "base": "tax_base",
}

#: The window every integrated scenario runs: 1625-01 to 1644-12.
INTEGRATED_TICK_COUNT: Final[int] = 240
INTEGRATED_WARMUP_TICKS: Final[int] = 24


@dataclass(frozen=True, slots=True)
class IntegratedScenario:
    """One point of the sandbox's surface: a space, a climate and a fiscal pressure."""

    label: str
    dataset: str = "toy"
    monthly_event_probability: float = 0.4
    severity_floor: float = 0.6
    nominal_pressure: float = 0.02
    pay_share_of_treasury: float = 0.5
    garrison_troops: float = 300.0


@dataclass(frozen=True, slots=True)
class IntegratedRun:
    scenario: IntegratedScenario
    result: KernelResult
    economy: Economy
    thresholds: GovernanceIndicatorParameters
    starting_households: float
    starting_adults: float


@dataclass(frozen=True, slots=True)
class IntegratedResults:
    metrics: pl.DataFrame
    governance: pl.DataFrame
    governance_series: pl.DataFrame
    distress: pl.DataFrame
    price_dispersion: pl.DataFrame
    migration_flows: pl.DataFrame
    migration_nodes: pl.DataFrame
    band_series: pl.DataFrame
    tax_base: pl.DataFrame
    runs: tuple[IntegratedRun, ...]

    def write(self, output_dir: str | Path) -> tuple[Path, ...]:
        directory = Path(output_dir)
        return (
            write_table(directory / METRICS_ARTIFACT, self.metrics),
            write_table(directory / GOVERNANCE_ARTIFACT, self.governance),
            write_table(directory / GOVERNANCE_SERIES_ARTIFACT, self.governance_series),
            write_table(directory / DISTRESS_ARTIFACT, self.distress),
            write_table(directory / PRICE_ARTIFACT, self.price_dispersion),
            write_table(directory / MIGRATION_ARTIFACT, self.migration_flows),
            write_table(directory / MIGRATION_NODES_ARTIFACT, self.migration_nodes),
            write_table(directory / BANDS_ARTIFACT, self.band_series),
            write_table(directory / TAX_BASE_ARTIFACT, self.tax_base),
        )


def default_scenarios() -> tuple[IntegratedScenario, ...]:
    """Two spaces, calm and shocked: the sandbox's own surface, not a historical one."""
    return (
        IntegratedScenario(
            label="toy-calm", dataset="toy", monthly_event_probability=0.0, severity_floor=0.0
        ),
        IntegratedScenario(label="toy-shock", dataset="toy"),
        IntegratedScenario(
            label="medium-calm", dataset="medium", monthly_event_probability=0.0, severity_floor=0.0
        ),
        IntegratedScenario(label="medium-shock", dataset="medium"),
    )


def dataset_for(scenario: IntegratedScenario) -> SpatialDataset:
    if scenario.dataset == "toy":
        return toy_spatial_dataset()
    if scenario.dataset == "medium":
        return medium_spatial_dataset()
    raise ValueError(f"unknown dataset {scenario.dataset!r}; expected 'toy' or 'medium'")


def climate_for(scenario: IntegratedScenario) -> ClimateModel:
    if scenario.monthly_event_probability <= 0.0:
        return BaselineClimate()
    return SyntheticClimate(
        monthly_event_probability=scenario.monthly_event_probability,
        severity_floor=scenario.severity_floor,
    )


def run_integrated_scenario(
    scenario: IntegratedScenario, *, config: SimulationConfig | None = None
) -> IntegratedRun:
    """Build the whole sandbox for one scenario and run the window to its end."""
    thresholds = core_default_governance_indicators()
    military = core_default_military_parameters().model_copy(
        update={
            "pay_share_of_treasury": scenario.pay_share_of_treasury,
            "garrison_target_troops": scenario.garrison_troops,
        }
    )
    economy = build_toy_economy(
        dataset=dataset_for(scenario),
        climate_model=climate_for(scenario),
        with_fiscal=True,
        with_military=True,
        with_migration=True,
        military_parameters=military,
        garrison_troops=scenario.garrison_troops,
        nominal_pressure=scenario.nominal_pressure,
    )
    starting_households = sum(cohort.households for cohort in economy.population)
    starting_adults = sum(cohort.adults for cohort in economy.population)
    run_config = config or SimulationConfig.model_validate(
        {
            "tick_count": INTEGRATED_TICK_COUNT,
            "warmup_ticks": INTEGRATED_WARMUP_TICKS,
            "scenario_id": f"{scenario.dataset}-fixture",
            "policy_id": "integrated-v1",
        }
    )
    result = SimulationKernel(run_config, list(economy.systems)).run(run_label=scenario.label)
    return IntegratedRun(
        scenario=scenario,
        result=result,
        economy=economy,
        thresholds=thresholds,
        starting_households=starting_households,
        starting_adults=starting_adults,
    )


def _county_nodes(run: IntegratedRun) -> tuple[str, ...]:
    return tuple(node.node_id for node in run.economy.graphs.nodes.counties)


def run_integrated_experiment(
    *,
    config: SimulationConfig | None = None,
    scenarios: tuple[IntegratedScenario, ...] | None = None,
) -> IntegratedResults:
    """Run the sandbox over the scenarios and collect every measurement it produces."""
    chosen = scenarios or default_scenarios()
    runs = tuple(run_integrated_scenario(scenario, config=config) for scenario in chosen)

    metrics = pl.DataFrame(
        [
            {
                "scenario": run.scenario.label,
                "dataset": run.scenario.dataset,
                "counties": len(_county_nodes(run)),
                "climate_shock_probability": run.scenario.monthly_event_probability,
                "climate_severity_floor": run.scenario.severity_floor,
                "nominal_pressure": run.scenario.nominal_pressure,
                "pay_share_of_treasury": run.scenario.pay_share_of_treasury,
                **integrated_metrics(
                    run.result.events,
                    population=run.economy.population,
                    elites=run.economy.elites,
                    thresholds=run.thresholds,
                    county_nodes=_county_nodes(run),
                    starting_households=run.starting_households,
                    starting_adults=run.starting_adults,
                ),
            }
            for run in runs
        ]
    ).select(list(METRIC_COLUMNS))

    tagged: dict[str, list[pl.DataFrame]] = {name: [] for name in FRAME_KEYS}
    for run in runs:
        produced = integrated_frames(
            run.result.events,
            population=run.economy.population,
            elites=run.economy.elites,
            county_nodes=_county_nodes(run),
        )
        for name, source in FRAME_KEYS.items():
            tagged[name].append(
                produced[source].with_columns(pl.lit(run.scenario.label).alias("scenario"))
            )

    def collected(name: str) -> pl.DataFrame:
        return pl.concat(tagged[name], how="diagonal_relaxed")

    governance = pl.concat(
        [
            governance_indicators(
                run.result.events,
                thresholds=run.thresholds,
                population_adults=run.starting_adults,
                starting_households=run.starting_households,
            ).with_columns(pl.lit(run.scenario.label).alias("scenario"))
            for run in runs
        ],
        how="diagonal_relaxed",
    )
    sampled = pl.concat(
        [
            governance_series(run.result.events).with_columns(
                pl.lit(run.scenario.label).alias("scenario")
            )
            for run in runs
        ],
        how="diagonal_relaxed",
    )
    return IntegratedResults(
        metrics=metrics,
        governance=governance,
        governance_series=sampled,
        distress=collected("distress"),
        price_dispersion=collected("price"),
        migration_flows=collected("flows"),
        migration_nodes=collected("nodes"),
        band_series=collected("bands"),
        tax_base=collected("base"),
        runs=runs,
    )
