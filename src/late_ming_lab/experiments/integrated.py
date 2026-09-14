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

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.actors.government import StateCapacity
from late_ming_lab.analysis.governance import governance_indicators, governance_series
from late_ming_lab.analysis.integrated import (
    METRIC_COLUMNS,
    integrated_frames,
    integrated_metrics,
)
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import KernelResult, SimulationKernel
from late_ming_lab.evidence.parameters import (
    BandParameters,
    CropParameters,
    EliteParameters,
    FiscalParameters,
    GovernanceIndicatorParameters,
    HouseholdParameters,
    MarketParameters,
    MigrationParameters,
    MilitaryParameters,
    core_default_band_parameters,
    core_default_crop_parameters,
    core_default_elite_parameters,
    core_default_fiscal_parameters,
    core_default_governance_indicators,
    core_default_household_parameters,
    core_default_market_parameters,
    core_default_migration_parameters,
    core_default_military_parameters,
)
from late_ming_lab.experiments.assembly import Economy, build_toy_economy
from late_ming_lab.networks.dataset import SpatialDataset
from late_ming_lab.networks.disruption import TradeDisruption
from late_ming_lab.networks.fixtures import medium_spatial_dataset, toy_spatial_dataset
from late_ming_lab.policies.fiscal import ExtractionPolicy
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
#: The dataset id the historical core registers under, so a scenario names it rather than a path.
HISTORICAL_CORE_DATASET: Final[str] = "historical-core-v1"

INTEGRATED_TICK_COUNT: Final[int] = 240
INTEGRATED_WARMUP_TICKS: Final[int] = 24


@dataclass(frozen=True, slots=True)
class IntegratedScenario:
    """One point of the sandbox's surface: a space, a climate and a fiscal pressure.

    ``climate_mode`` selects the forcing: ``synthetic`` (the declared default, unchanged from
    P07-P14), ``baseline`` (no adverse anomaly) or ``observed-historical`` (the historical core's
    annual index allocated across months by the declared allocator).
    """

    label: str
    dataset: str = "toy"
    climate_mode: str = "synthetic"
    allocation_mode: str = "seasonal"
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


def dataset_for(scenario: IntegratedScenario, root: str | Path = ".") -> SpatialDataset:
    """The space for a scenario: a fixture in code, or the built historical core on disk."""
    if scenario.dataset == "toy":
        return toy_spatial_dataset()
    if scenario.dataset == "medium":
        return medium_spatial_dataset()
    if scenario.dataset == HISTORICAL_CORE_DATASET:
        from late_ming_lab.historical.build import core_dataset, load_core

        return core_dataset(load_core(root))
    raise ValueError(
        f"unknown dataset {scenario.dataset!r}; expected 'toy', 'medium' or "
        f"{HISTORICAL_CORE_DATASET!r}"
    )


def climate_for(
    scenario: IntegratedScenario,
    root: str | Path = ".",
    parameters: object | None = None,
) -> ClimateModel:
    """The forcing for a scenario: synthetic, baseline, or the observed historical allocation.

    The observed path reads the annual index the historical core stores and allocates it to months
    with a declared profile. It is deliberately *not* a monthly observation series: what the record
    gives is an annual index per node, and the allocator is a parameter-carded model construction
    that V2-P07 can ablate by switching to uniform allocation.
    """
    if scenario.climate_mode == "baseline":
        return BaselineClimate()
    if scenario.climate_mode == "observed-historical":
        from late_ming_lab.evidence.parameters import (
            HistoricalCoreParameters,
            core_default_historical_core_parameters,
        )
        from late_ming_lab.historical.build import load_core
        from late_ming_lab.historical.forcing import AllocatedObservedClimate, AllocationMode

        core = load_core(root)
        chosen = parameters if isinstance(parameters, HistoricalCoreParameters) else None
        settings = chosen or core_default_historical_core_parameters()
        mode = (
            AllocationMode.UNIFORM
            if scenario.allocation_mode == AllocationMode.UNIFORM.value
            else AllocationMode.SEASONAL
        )
        return AllocatedObservedClimate(
            core.annual,
            settings,
            allocation_mode=mode,
            series_id=core.manifest.dataset_id,
        )
    if scenario.monthly_event_probability <= 0.0:
        return BaselineClimate()
    return SyntheticClimate(
        monthly_event_probability=scenario.monthly_event_probability,
        severity_floor=scenario.severity_floor,
    )


def build_integrated_economy(
    scenario: IntegratedScenario,
    *,
    parameter_sets: Mapping[str, object] | None = None,
    disruption: TradeDisruption | None = None,
    extraction_policy: ExtractionPolicy | None = None,
    capacity: StateCapacity | None = None,
    root: str | Path = ".",
) -> Economy:
    """Build the sandbox's economy for one scenario, with declared overrides applied.

    The sandbox has one wiring and this is it: a runner passes a drawn parameter set per name, or a
    disruption regime, an extraction policy or a set of state capacities, and gets the same economy,
    in the same tick order, that the P07 scenarios run. Every override defaults to the behaviour the
    P07 scenarios have, so an omitted argument changes nothing; one whose object is not the thing it
    claims to be is refused rather than silently ignored.
    """
    overrides = parameter_sets or {}
    military = _overridden(
        overrides, MilitaryParameters, core_default_military_parameters
    ).model_copy(
        update={
            "pay_share_of_treasury": scenario.pay_share_of_treasury,
            "garrison_target_troops": scenario.garrison_troops,
        }
    )
    return build_toy_economy(
        dataset=dataset_for(scenario, root),
        climate_model=climate_for(scenario, root, overrides.get("HistoricalCoreParameters")),
        with_fiscal=True,
        with_military=True,
        with_migration=True,
        disruption=disruption,
        extraction_policy=extraction_policy,
        capacity=capacity,
        nominal_pressure=scenario.nominal_pressure,
        garrison_troops=scenario.garrison_troops,
        crop_parameters=_overridden(overrides, CropParameters, core_default_crop_parameters),
        household_parameters=_overridden(
            overrides, HouseholdParameters, core_default_household_parameters
        ),
        market_parameters=_overridden(overrides, MarketParameters, core_default_market_parameters),
        elite_parameters=_overridden(overrides, EliteParameters, core_default_elite_parameters),
        fiscal_parameters=_overridden(overrides, FiscalParameters, core_default_fiscal_parameters),
        military_parameters=military,
        band_parameters=_overridden(overrides, BandParameters, core_default_band_parameters),
        migration_parameters=_overridden(
            overrides, MigrationParameters, core_default_migration_parameters
        ),
    )


def _overridden[T](overrides: Mapping[str, object], model: type[T], default: Callable[[], T]) -> T:
    """The draw's parameter set under this name, or the default; anything else is an error."""
    supplied = overrides.get(model.__name__)
    if supplied is None:
        return default()
    if not isinstance(supplied, model):
        raise TypeError(f"parameter set {model.__name__} was given a {type(supplied).__name__}")
    return supplied


def run_integrated_scenario(
    scenario: IntegratedScenario,
    *,
    config: SimulationConfig | None = None,
    parameter_sets: Mapping[str, object] | None = None,
    root: str | Path = ".",
) -> IntegratedRun:
    """Build the whole sandbox for one scenario and run the window to its end."""
    thresholds = core_default_governance_indicators()
    economy = build_integrated_economy(scenario, parameter_sets=parameter_sets, root=root)
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
