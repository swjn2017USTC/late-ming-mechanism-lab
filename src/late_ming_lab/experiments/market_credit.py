"""The P04 mechanism questions, asked as bounded experiments.

Four questions, each answered by running the same toy economy twice with one rule changed, and by
reporting the measured difference rather than a verdict:

| Question | Change | Measured |
| --- | --- | --- |
| A tradability and price dispersion | capacity swept 0x to 10x | price CV, max/min ratio |
| B transport cost and trade flow | cost multiplier | shipped shi, lost shi |
| C credit and household collapse | lending on vs off | unmet share, first distress tick |
| D credit and land concentration | lending on vs off | elite land share, land Gini |

None of this is calibrated, and the severity axis is a scenario parameter, not a historical
drought. A result here is a statement about the model's rules; it is not evidence about
1625-1644, and the report says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.actors.households import HouseholdPopulation
from late_ming_lab.analysis.concentration import (
    debt_distribution,
    debt_summary,
    dispersion_summary,
    first_distress_ticks,
    land_concentration,
    land_distribution,
    price_dispersion,
    trade_summary,
)
from late_ming_lab.analysis.distress import (
    cohort_attributes,
    cohort_distress,
)
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import KernelResult, SimulationKernel
from late_ming_lab.evidence.parameters import (
    core_default_elite_parameters,
    core_default_market_parameters,
)
from late_ming_lab.experiments.assembly import Economy, build_toy_economy
from late_ming_lab.networks.disruption import CalmTrade, ScaledDisruption, TradeDisruption
from late_ming_lab.networks.fixtures import toy_spatial_dataset
from late_ming_lab.storage.tables import write_table
from late_ming_lab.systems.climate import BaselineClimate, SyntheticClimate

DISPERSION_ARTIFACT: Final[str] = "p04_price_dispersion.parquet"
LAND_ARTIFACT: Final[str] = "p04_land_distribution.parquet"
DEBT_ARTIFACT: Final[str] = "p04_debt_distribution.parquet"
MECHANISM_ARTIFACT: Final[str] = "p04_mechanism_results.parquet"

#: The scenario whose distributions the land and debt artifacts describe.
REFERENCE_SCENARIO: Final[str] = "credit-low-rate"


@dataclass(frozen=True, slots=True)
class MarketScenario:
    """One point in the scenario space: forcing, trade regime, credit and relief rules.

    ``with_fiscal`` defaults to false, which is the P04 configuration these answers were measured
    on. P05 adds the county fiscal layer, which changes what credit and markets do; re-measuring
    these questions under it is a later phase's job, and keeping the flag here says so.
    """

    label: str
    monthly_event_probability: float = 0.0
    severity_floor: float = 0.0
    transport_cost_multiplier: float = 1.0
    trade_capacity_scale: float = 1.0
    capacity_unit_shi_per_month: float | None = None
    blocked_links: tuple[tuple[str, str], ...] = ()
    credit_enabled: bool = True
    relief_enabled: bool = True
    interest_rate_monthly: float | None = None
    merchant_stock_scale: float = 1.0
    with_fiscal: bool = False

    @property
    def severity_index(self) -> float:
        return self.severity_floor


@dataclass(frozen=True, slots=True)
class MarketRun:
    scenario: MarketScenario
    result: KernelResult
    economy: Economy


@dataclass(frozen=True, slots=True)
class MechanismResults:
    """The four answers, each as a table with one row per scenario, plus the three outputs.

    ``dispersion``, ``land`` and ``debt`` describe one reference scenario in detail; the four
    questions describe the differences between scenarios.
    """

    integration: pl.DataFrame
    transport_cost: pl.DataFrame
    credit_and_collapse: pl.DataFrame
    credit_and_land: pl.DataFrame
    dispersion: pl.DataFrame
    land: pl.DataFrame
    debt: pl.DataFrame
    runs: tuple[MarketRun, ...]

    def merged(self) -> pl.DataFrame:
        return pl.concat(
            [
                self.integration.with_columns(pl.lit("A-integration").alias("question")),
                self.transport_cost.with_columns(pl.lit("B-transport-cost").alias("question")),
                self.credit_and_collapse.with_columns(
                    pl.lit("C-credit-collapse").alias("question")
                ),
                self.credit_and_land.with_columns(pl.lit("D-credit-land").alias("question")),
            ],
            how="diagonal",
        )

    def write(self, output_dir: str | Path) -> tuple[Path, ...]:
        directory = Path(output_dir)
        return (
            write_table(directory / MECHANISM_ARTIFACT, self.merged()),
            write_table(directory / DISPERSION_ARTIFACT, self.dispersion),
            write_table(directory / LAND_ARTIFACT, self.land),
            write_table(directory / DEBT_ARTIFACT, self.debt),
        )


def run_market_scenario(
    scenario: MarketScenario, *, config: SimulationConfig | None = None
) -> MarketRun:
    """Run one scenario through the kernel with the whole P04 economy wired in."""
    run_config = config or SimulationConfig()
    elite_parameters = core_default_elite_parameters()
    if not scenario.credit_enabled:
        elite_parameters = elite_parameters.model_validate(
            {**elite_parameters.model_dump(), "loan_to_value": 0.0}
        )
    if scenario.interest_rate_monthly is not None:
        elite_parameters = elite_parameters.model_validate(
            {
                **elite_parameters.model_dump(),
                "interest_rate_monthly": scenario.interest_rate_monthly,
            }
        )
    if not scenario.relief_enabled:
        elite_parameters = elite_parameters.model_validate(
            {**elite_parameters.model_dump(), "relief_share_of_grain_stock": 0.0}
        )
    market_parameters = None
    if (
        scenario.transport_cost_multiplier != 1.0
        or scenario.capacity_unit_shi_per_month is not None
    ):
        base = core_default_market_parameters()
        market_parameters = base.model_validate(
            {
                **base.model_dump(),
                "transport_cost_tael_per_cost_unit_per_shi": (
                    base.transport_cost_tael_per_cost_unit_per_shi
                    * scenario.transport_cost_multiplier
                ),
                "capacity_unit_shi_per_month": (
                    scenario.capacity_unit_shi_per_month
                    if scenario.capacity_unit_shi_per_month is not None
                    else base.capacity_unit_shi_per_month
                ),
            }
        )
    climate = (
        BaselineClimate()
        if scenario.monthly_event_probability <= 0.0
        else SyntheticClimate(
            monthly_event_probability=scenario.monthly_event_probability,
            severity_floor=scenario.severity_floor,
        )
    )
    economy = build_toy_economy(
        climate_model=climate,
        disruption=_disruption_for(scenario),
        market_parameters=market_parameters,
        elite_parameters=elite_parameters,
        merchant_stock_scale=scenario.merchant_stock_scale,
        with_fiscal=scenario.with_fiscal,
    )
    result = SimulationKernel(run_config, list(economy.systems)).run(run_label=scenario.label)
    return MarketRun(scenario=scenario, result=result, economy=economy)


def _disruption_for(scenario: MarketScenario) -> TradeDisruption:
    if scenario.trade_capacity_scale >= 1.0 and not scenario.blocked_links:
        return CalmTrade()
    return ScaledDisruption(
        name=f"capacity-{scenario.trade_capacity_scale:g}",
        risk_scale=1.0,
        capacity_scale=scenario.trade_capacity_scale,
        blocked_links=scenario.blocked_links,
    )


def _county_nodes() -> tuple[str, ...]:
    return tuple(node.node_id for node in toy_spatial_dataset().node_registry().counties)


def _scenario_outputs(runs: tuple[MarketRun, ...]) -> dict[str, pl.DataFrame]:
    """Detailed outputs for one reference scenario: dispersion, land distribution, debt."""
    reference = next((run for run in runs if run.scenario.label == REFERENCE_SCENARIO), runs[0])
    return {
        "dispersion": price_dispersion(
            reference.result.events, county_nodes=_county_nodes()
        ).with_columns(pl.lit(reference.scenario.label).alias("scenario")),
        "land": land_distribution(
            reference.economy.population, reference.economy.elites
        ).with_columns(pl.lit(reference.scenario.label).alias("scenario")),
        "debt": debt_distribution(
            reference.economy.population, reference.economy.elites
        ).with_columns(pl.lit(reference.scenario.label).alias("scenario")),
    }


def _metrics_frame(runs: tuple[MarketRun, ...]) -> pl.DataFrame:
    return pl.DataFrame(
        [{"scenario": run.scenario.label, **_scenario_metrics(run)} for run in runs]
    )


def _scenario_distress(run: MarketRun) -> pl.DataFrame:
    return cohort_distress(
        run.result.events, attributes=cohort_attributes(run.economy.population)
    ).with_columns(
        pl.lit(run.scenario.label).alias("scenario"),
        pl.lit(run.scenario.severity_index).alias("severity_index"),
        pl.lit(run.scenario.transport_cost_multiplier).alias("transport_cost_multiplier"),
        pl.lit(run.scenario.trade_capacity_scale).alias("trade_capacity_scale"),
        pl.lit(run.scenario.credit_enabled).alias("credit_enabled"),
    )


def _first_distress(run: MarketRun) -> pl.DataFrame:
    first = first_distress_ticks(run.result.events)
    population: HouseholdPopulation = run.economy.population
    every = pl.DataFrame({"agent_id": [cohort.cohort_id for cohort in population]})
    return every.join(first, on="agent_id", how="left").with_columns(
        pl.lit(run.scenario.label).alias("scenario")
    )


def _scenario_metrics(run: MarketRun) -> dict[str, float]:
    """Every measured quantity for one run; the scenario label is added by the caller."""
    distress = _scenario_distress(run)
    dispersion = dispersion_summary(
        price_dispersion(run.result.events, county_nodes=_county_nodes())
    )
    land = land_concentration(run.economy.population, run.economy.elites)
    debt = debt_summary(run.economy.population, run.economy.elites)
    trades = trade_summary(run.result.events)
    distress_totals = distress.select(
        pl.col("need_shi").sum().alias("need"),
        pl.col("unmet_shi").sum().alias("unmet"),
        pl.col("land_sold_mu").sum().alias("land_sold"),
        pl.col("final_debt_tael").sum().alias("debt"),
    ).row(0, named=True)
    needed = float(distress_totals["need"] or 0.0)
    shipped = (
        float(trades.select(pl.col("shipped_shi").sum()).item() or 0.0) if trades.height else 0.0
    )
    lost = float(trades.select(pl.col("lost_shi").sum()).item() or 0.0) if trades.height else 0.0
    first = _first_distress(run)
    ever_below = first["first_below_floor_tick"].is_not_null().sum()
    return {
        "severity_index": run.scenario.severity_index,
        "transport_cost_multiplier": run.scenario.transport_cost_multiplier,
        "trade_capacity_scale": run.scenario.trade_capacity_scale,
        "credit_enabled": float(run.scenario.credit_enabled),
        "mean_unmet_ratio": (
            float(distress_totals["unmet"] or 0.0) / needed if needed > 0 else 0.0
        ),
        "share_cohorts_below_floor": float(ever_below) / first.height if first.height else 0.0,
        "mean_first_distress_tick": float(
            first.select(pl.col("first_below_floor_tick").mean()).item() or 0.0
        ),
        "land_sold_mu": float(distress_totals["land_sold"] or 0.0),
        "total_debt_tael": float(distress_totals["debt"] or 0.0),
        "shipped_shi": shipped,
        "lost_shi": lost,
        "elite_land_share": land["elite_land_share"],
        "cohort_land_gini": land["cohort_land_gini"],
        "share_cohorts_indebted": debt["share_cohorts_indebted"],
        **dispersion,
    }


def run_market_credit_experiment(
    *,
    config: SimulationConfig | None = None,
    scenarios: tuple[MarketScenario, ...] | None = None,
) -> MechanismResults:
    """Run the four mechanism questions over the full 1625-1644 window."""
    if scenarios is not None:
        runs = tuple(run_market_scenario(scenario, config=config) for scenario in scenarios)
        metrics = _metrics_frame(runs)
        outputs = _scenario_outputs(runs)
        return MechanismResults(
            integration=metrics,
            transport_cost=metrics,
            credit_and_collapse=metrics,
            credit_and_land=metrics,
            runs=runs,
            **outputs,
        )

    # Price dispersion and trade volume are only meaningful once prices move, so questions A and
    # B run under a moderate forced shock; C and D use a severe one.
    moderate_probability, moderate_floor = 0.35, 0.45
    tradability = tuple(
        MarketScenario(
            f"tradability-{unit:g}x",
            monthly_event_probability=moderate_probability,
            severity_floor=moderate_floor,
            capacity_unit_shi_per_month=unit,
        )
        for unit in (0.0, 1.0, 3.0, 10.0)
    ) + tuple(
        # Price dispersion with trade open depends on how much stock merchants actually hold,
        # because a thin stock makes any export a large share of it.
        MarketScenario(
            f"stock-{scale:g}x",
            monthly_event_probability=moderate_probability,
            severity_floor=moderate_floor,
            merchant_stock_scale=scale,
        )
        for scale in (10.0, 100.0)
    )
    transport_costs = tuple(
        MarketScenario(
            f"transport-{multiplier:g}x",
            monthly_event_probability=moderate_probability,
            severity_floor=moderate_floor,
            transport_cost_multiplier=multiplier,
        )
        for multiplier in (0.5, 1.0, 2.0, 4.0)
    )
    shock_probability, shock_floor = 0.5, 0.6
    collapse = (
        MarketScenario(
            "shock-credit-on",
            monthly_event_probability=shock_probability,
            severity_floor=shock_floor,
        ),
        MarketScenario(
            "shock-credit-off",
            monthly_event_probability=shock_probability,
            severity_floor=shock_floor,
            credit_enabled=False,
        ),
    )
    concentration = (
        MarketScenario(
            "credit-off",
            monthly_event_probability=shock_probability,
            severity_floor=shock_floor,
            credit_enabled=False,
        ),
        MarketScenario(
            "credit-low-rate",
            monthly_event_probability=shock_probability,
            severity_floor=shock_floor,
            interest_rate_monthly=0.005,
        ),
        MarketScenario(
            "credit-high-rate",
            monthly_event_probability=shock_probability,
            severity_floor=shock_floor,
            interest_rate_monthly=0.02,
        ),
    )

    scenario_runs = tuple(
        run_market_scenario(scenario, config=config)
        for scenario in (*tradability, *transport_costs, *collapse, *concentration)
    )
    by_label = {run.scenario.label: run for run in scenario_runs}

    def frame(labels: tuple[str, ...]) -> pl.DataFrame:
        return _metrics_frame(tuple(by_label[label] for label in labels))

    return MechanismResults(
        integration=frame(tuple(scenario.label for scenario in tradability)),
        transport_cost=frame(tuple(scenario.label for scenario in transport_costs)),
        credit_and_collapse=frame(("shock-credit-on", "shock-credit-off")),
        credit_and_land=frame(("credit-off", "credit-low-rate", "credit-high-rate")),
        runs=scenario_runs,
        **_scenario_outputs(scenario_runs),
    )
