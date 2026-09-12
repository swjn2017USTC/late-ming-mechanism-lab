"""The extraction-pressure experiment: raise the pressure, watch five things.

The phase's job here is to *supply data*, not to reach a verdict. The experiment sweeps the
nominal extraction pressure from light to crushing and reports, for each level:

```text
nominal quota      what was assessed against the tax base
actual receipt     what the county actually took
tax base           the land the county can see, and how much of it moves out of reach
migration          how many cohorts become eligible to leave
asset depletion    grain, goods and land sold in order to pay
```

It deliberately computes no hypothesis test and adds no verdict column. The question of whether
receipts collapse while pressure rises — the mechanism a later phase might call Fiscal Extraction
Inversion — is *not* answered or asserted here; a phase that wants to claim it must bring the
analysis, the counterfactuals and the sensitivity evidence, and this module's output is the raw
material for that.

Two policy families are run at each level: a fixed effort, and an arrears-escalating one that
raises both the rate and the effort as arrears grow. Comparing them is the point of having an
extraction *policy* at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.actors.elites import AdvanceBasedTaxMediation, TaxMediationPolicy
from late_ming_lab.actors.fixtures import toy_capacity
from late_ming_lab.analysis.distress import cohort_attributes, cohort_distress
from late_ming_lab.analysis.fiscal import (
    fiscal_totals,
    tax_base,
    tax_burden,
    tax_liquidation,
)
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import KernelResult, SimulationKernel
from late_ming_lab.evidence.parameters import core_default_fiscal_parameters
from late_ming_lab.experiments.assembly import Economy, build_toy_economy
from late_ming_lab.policies.fiscal import (
    ArrearsEscalation,
    ExtractionPolicy,
    FixedExtraction,
)
from late_ming_lab.storage.tables import write_table
from late_ming_lab.systems.climate import BaselineClimate, SyntheticClimate

CURVE_ARTIFACT: Final[str] = "p05_extraction_curve.parquet"
BURDEN_ARTIFACT: Final[str] = "p05_tax_burden.parquet"
FISCAL_ARTIFACT: Final[str] = "p05_fiscal_totals.parquet"

#: Every column the experiment reports. Measurements only, by design.
CURVE_COLUMNS: Final[tuple[str, ...]] = (
    "scenario",
    "policy",
    "nominal_pressure",
    "nominal_quota_tael",
    "actual_receipts_tael",
    "collection_cost_tael",
    "net_receipts_tael",
    "mean_collection_effort",
    "mean_assessment_rate",
    "arrears_tael",
    "taxable_land_mu_start",
    "taxable_land_mu_end",
    "taxable_land_mu_change",
    "hidden_land_mu_end",
    "relief_released_shi",
    "relief_cost_tael",
    "silver_tael_end",
    "granary_shi_end",
    "share_permanent_migration_eligible",
    "share_recruitment_eligible",
    "mean_unmet_ratio",
    "grain_sold_for_tax_shi",
    "movables_sold_for_tax_tael",
    "land_sold_for_tax_mu",
    "silver_raised_for_tax_tael",
    "mean_arrears_per_household_tael",
)


@dataclass(frozen=True, slots=True)
class ExtractionScenario:
    """One point on the pressure curve."""

    label: str
    nominal_pressure: float
    policy: str = "fixed"
    effort: float = 0.5
    arrears_weight: float = 0.5
    monthly_event_probability: float = 0.0
    severity_floor: float = 0.0
    coercion_capacity: float | None = None
    tax_mediation: bool = True


@dataclass(frozen=True, slots=True)
class ExtractionRun:
    scenario: ExtractionScenario
    result: KernelResult
    economy: Economy


@dataclass(frozen=True, slots=True)
class ExtractionResults:
    curve: pl.DataFrame
    burden: pl.DataFrame
    fiscal: pl.DataFrame
    runs: tuple[ExtractionRun, ...]

    def write(self, output_dir: str | Path) -> tuple[Path, ...]:
        directory = Path(output_dir)
        return (
            write_table(directory / CURVE_ARTIFACT, self.curve),
            write_table(directory / BURDEN_ARTIFACT, self.burden),
            write_table(directory / FISCAL_ARTIFACT, self.fiscal),
        )


def policy_for(scenario: ExtractionScenario) -> ExtractionPolicy:
    if scenario.policy == "escalating":
        return ArrearsEscalation(
            base_effort=scenario.effort,
            arrears_weight=scenario.arrears_weight,
            effort_ceiling=1.0,
        )
    return FixedExtraction(effort=scenario.effort)


def run_extraction_scenario(
    scenario: ExtractionScenario, *, config: SimulationConfig | None = None
) -> ExtractionRun:
    """Run one pressure level with the whole P05 economy wired in."""
    run_config = config or SimulationConfig()
    climate = (
        BaselineClimate()
        if scenario.monthly_event_probability <= 0.0
        else SyntheticClimate(
            monthly_event_probability=scenario.monthly_event_probability,
            severity_floor=scenario.severity_floor,
        )
    )
    mediation: TaxMediationPolicy | None = (
        AdvanceBasedTaxMediation(minimum_client_land_mu=0.0) if scenario.tax_mediation else None
    )
    capacity = (
        None
        if scenario.coercion_capacity is None
        else toy_capacity(coercion=scenario.coercion_capacity)
    )
    economy = build_toy_economy(
        climate_model=climate,
        with_fiscal=True,
        fiscal_parameters=core_default_fiscal_parameters(),
        extraction_policy=policy_for(scenario),
        tax_mediation=mediation,
        nominal_pressure=scenario.nominal_pressure,
        capacity=capacity,
    )
    result = SimulationKernel(run_config, list(economy.systems)).run(run_label=scenario.label)
    return ExtractionRun(scenario=scenario, result=result, economy=economy)


def default_pressures() -> tuple[float, ...]:
    """Light to crushing, in even steps: the sweep the phase's prompt asks for."""
    return (0.005, 0.01, 0.02, 0.04, 0.08, 0.16)


def default_scenarios() -> tuple[ExtractionScenario, ...]:
    fixed = tuple(
        ExtractionScenario(
            label=f"fixed-{pressure:g}",
            nominal_pressure=pressure,
            policy="fixed",
            monthly_event_probability=0.5,
            severity_floor=0.6,
        )
        for pressure in default_pressures()
    )
    escalating = tuple(
        ExtractionScenario(
            label=f"escalating-{pressure:g}",
            nominal_pressure=pressure,
            policy="escalating",
            monthly_event_probability=0.5,
            severity_floor=0.6,
        )
        for pressure in default_pressures()
    )
    return fixed + escalating


def _measure(run: ExtractionRun) -> dict[str, object]:
    events = run.result.events
    totals = fiscal_totals(events)
    base = tax_base(events)
    distress = cohort_distress(events, attributes=cohort_attributes(run.economy.population))
    liquidation = tax_liquidation(events, population=run.economy.population)
    burden = tax_burden(run.economy.population)
    need = float(distress.select(pl.col("need_shi").sum()).item() or 0.0)
    unmet = float(distress.select(pl.col("unmet_shi").sum()).item() or 0.0)

    def liquidation_total(column: str) -> float:
        if liquidation.is_empty() or column not in liquidation.columns:
            return 0.0
        return float(liquidation.select(pl.col(column).sum()).item() or 0.0)

    return {
        "scenario": run.scenario.label,
        "policy": run.scenario.policy,
        "nominal_pressure": run.scenario.nominal_pressure,
        "nominal_quota_tael": totals["nominal_quota_tael"],
        "actual_receipts_tael": totals["actual_receipts_tael"],
        "collection_cost_tael": totals["collection_cost_tael"],
        "net_receipts_tael": totals["net_receipts_tael"],
        "mean_collection_effort": totals["mean_collection_effort"],
        "mean_assessment_rate": totals["mean_assessment_rate"],
        "arrears_tael": totals["arrears_tael"],
        "taxable_land_mu_start": float(
            base.select(pl.col("taxable_land_mu_start").sum()).item() or 0.0
        ),
        "taxable_land_mu_end": totals["taxable_land_mu_end"],
        "taxable_land_mu_change": float(
            base.select(pl.col("taxable_land_mu_change").sum()).item() or 0.0
        ),
        "hidden_land_mu_end": totals["hidden_land_mu_end"],
        "relief_released_shi": totals["relief_released_shi"],
        "relief_cost_tael": totals["relief_cost_tael"],
        "silver_tael_end": totals["silver_tael_end"],
        "granary_shi_end": totals["granary_shi_end"],
        "share_permanent_migration_eligible": float(
            distress.select(pl.col("final_permanent_migration_eligible").mean()).item() or 0.0
        ),
        "share_recruitment_eligible": float(
            distress.select(pl.col("final_recruitment_eligible").mean()).item() or 0.0
        ),
        "mean_unmet_ratio": unmet / need if need > 0 else 0.0,
        "grain_sold_for_tax_shi": liquidation_total("grain_sold_for_tax_shi"),
        "movables_sold_for_tax_tael": liquidation_total("movables_sold_for_tax_tael"),
        "land_sold_for_tax_mu": liquidation_total("land_sold_for_tax_mu"),
        "silver_raised_for_tax_tael": liquidation_total("silver_raised_for_tax_tael"),
        "mean_arrears_per_household_tael": float(
            burden.select(pl.col("mean_arrears_per_household_tael").mean()).item() or 0.0
        ),
    }


def run_extraction_experiment(
    *,
    config: SimulationConfig | None = None,
    scenarios: tuple[ExtractionScenario, ...] | None = None,
) -> ExtractionResults:
    """Run the pressure sweep and return the curve, the burden and the fiscal totals."""
    chosen = scenarios or default_scenarios()
    runs = tuple(run_extraction_scenario(scenario, config=config) for scenario in chosen)
    curve = pl.DataFrame([_measure(run) for run in runs]).select(list(CURVE_COLUMNS))
    burden = pl.concat(
        [
            tax_burden(run.economy.population).with_columns(
                pl.lit(run.scenario.label).alias("scenario")
            )
            for run in runs
        ],
        how="diagonal",
    ).sort(["scenario", "cohort_class"])
    fiscal = pl.DataFrame(
        [{"scenario": run.scenario.label, **fiscal_totals(run.result.events)} for run in runs]
    )
    return ExtractionResults(curve=curve, burden=burden, fiscal=fiscal, runs=runs)
