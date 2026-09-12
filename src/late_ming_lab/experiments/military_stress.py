"""The military-finance experiment: short the pay, and watch four things.

The phase's job is to *supply data*, not to reach a verdict. The experiment sweeps the two levers
the plan's M4 gives a county — how much of its treasury it will spend on the garrison, and how hard
the climate shocks the harvest — and reports, for each combination:

```text
garrison        strength at the end, and the arrears it accumulated getting there
desertion       the monthly rate at which soldiers left
armed bands     how many there were, how big the largest was, and its share of all armed men
recruitment     adults levied into garrisons and into bands, and deserters still unorganized
burden          grain and property the bands took from households, elites and the granary
```

It deliberately computes no hypothesis test and adds no verdict column. Whether unpaid soldiers
become rebels in this model is visible in the band columns; whether that constitutes a *mechanism*
is a claim for a later phase, with counterfactuals and sensitivity, and this module's output is the
raw material for it.

Three series are written alongside the curve: the band roster (the size distribution the plan asks
for, one row per band per month), the per-tick band totals, and the per-tick desertion rates.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.analysis.military import (
    band_roster,
    band_series,
    desertion_rate,
    military_totals,
    recruitment_series,
)
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import KernelResult, SimulationKernel
from late_ming_lab.evidence.parameters import (
    MilitaryParameters,
    core_default_military_parameters,
)
from late_ming_lab.experiments.assembly import Economy, build_toy_economy
from late_ming_lab.storage.tables import write_table
from late_ming_lab.systems.climate import BaselineClimate, ClimateModel, SyntheticClimate

CURVE_ARTIFACT: Final[str] = "p06_military_curve.parquet"
BAND_SERIES_ARTIFACT: Final[str] = "p06_band_series.parquet"
BAND_ROSTER_ARTIFACT: Final[str] = "p06_band_roster.parquet"
DESERTION_ARTIFACT: Final[str] = "p06_desertion_series.parquet"
RECRUITMENT_ARTIFACT: Final[str] = "p06_recruitment_series.parquet"

#: Every column the experiment reports. Measurements only, by design.
CURVE_COLUMNS: Final[tuple[str, ...]] = (
    "scenario",
    "pay_share_of_treasury",
    "garrison_troops_per_node",
    "nominal_pressure",
    "shock_probability",
    "shock_severity_floor",
    "garrison_troops_end",
    "pay_arrears_tael_end",
    "mean_desertion_rate",
    "deserters_left_total",
    "levied_to_garrisons_total",
    "levied_to_bands_total",
    "unorganized_deserters_end",
    "bands_end",
    "band_troops_end",
    "largest_band_end",
    "largest_band_share_end",
    "largest_band_share_max",
    "bands_formed_total",
    "bands_dissolved_total",
    "band_splits_total",
    "band_merges_total",
    "band_moves_total",
    "suppressions_total",
    "mean_band_cohesion_end",
    "mean_band_network_end",
    "cohort_grain_seized_total",
    "cohort_assets_seized_total",
    "elite_grain_seized_total",
    "granary_grain_seized_total",
)


@dataclass(frozen=True, slots=True)
class MilitaryScenario:
    """One point on the military-finance surface.

    Two of the three levers are the county's own: how much of the treasury it will spend on pay,
    and how much tax pressure it applies. The third is the size of the claim itself — how many
    soldiers the county is expected to keep — which is what turns a fiscal difficulty into a
    fiscal-military one.
    """

    label: str
    pay_share_of_treasury: float
    garrison_troops_per_node: float = 300.0
    nominal_pressure: float = 0.02
    monthly_event_probability: float = 0.4
    severity_floor: float = 0.6


@dataclass(frozen=True, slots=True)
class MilitaryRun:
    scenario: MilitaryScenario
    result: KernelResult
    economy: Economy
    parameters: MilitaryParameters


@dataclass(frozen=True, slots=True)
class MilitaryResults:
    curve: pl.DataFrame
    band_series: pl.DataFrame
    band_roster: pl.DataFrame
    desertion: pl.DataFrame
    recruitment: pl.DataFrame
    runs: tuple[MilitaryRun, ...]

    def write(self, output_dir: str | Path) -> tuple[Path, ...]:
        directory = Path(output_dir)
        return (
            write_table(directory / CURVE_ARTIFACT, self.curve),
            write_table(directory / BAND_SERIES_ARTIFACT, self.band_series),
            write_table(directory / BAND_ROSTER_ARTIFACT, self.band_roster),
            write_table(directory / DESERTION_ARTIFACT, self.desertion),
            write_table(directory / RECRUITMENT_ARTIFACT, self.recruitment),
        )


def default_scenarios() -> tuple[MilitaryScenario, ...]:
    """The claim-size surface, swept against what the county will spend, under a climate shock.

    The claim is swept because it is the binding constraint at this scale: what a county can pay
    and feed is bounded by what it can raise, and the sweep locates where a garrison stops being
    supportable rather than asserting where that line is. A calm reference at the middle of the
    grid shows how much of the surface is the climate and how much is the fiscal claim.
    """
    claim_sizes = (100.0, 200.0, 300.0, 450.0)
    shares = (0.2, 0.5, 0.8)
    shocked = tuple(
        MilitaryScenario(
            label=f"claim-{troops:g}-pay-{share:g}",
            pay_share_of_treasury=share,
            garrison_troops_per_node=troops,
        )
        for troops in claim_sizes
        for share in shares
    )
    calm = tuple(
        MilitaryScenario(
            label=f"calm-claim-{troops:g}",
            pay_share_of_treasury=0.5,
            garrison_troops_per_node=troops,
            monthly_event_probability=0.0,
            severity_floor=0.0,
        )
        for troops in claim_sizes
    )
    return shocked + calm


def climate_for(scenario: MilitaryScenario) -> ClimateModel:
    if scenario.monthly_event_probability <= 0.0:
        return BaselineClimate()
    return SyntheticClimate(
        monthly_event_probability=scenario.monthly_event_probability,
        severity_floor=scenario.severity_floor,
    )


def run_military_scenario(
    scenario: MilitaryScenario, *, config: SimulationConfig | None = None
) -> MilitaryRun:
    """Run one pay-share level with the whole P06 mechanism wired in."""
    parameters = core_default_military_parameters().model_copy(
        update={
            "pay_share_of_treasury": scenario.pay_share_of_treasury,
            # The claim is both what the county starts with and what it is expected to keep:
            # the levy refills toward it, so a claim it cannot pay for shows up as arrears,
            # desertion and, eventually, men leaving for the hills.
            "garrison_target_troops": scenario.garrison_troops_per_node,
        }
    )
    economy = build_toy_economy(
        climate_model=climate_for(scenario),
        with_fiscal=True,
        with_military=True,
        military_parameters=parameters,
        nominal_pressure=scenario.nominal_pressure,
        garrison_troops=scenario.garrison_troops_per_node,
    )
    result = SimulationKernel(config or SimulationConfig(), list(economy.systems)).run(
        run_label=scenario.label
    )
    return MilitaryRun(scenario=scenario, result=result, economy=economy, parameters=parameters)


def _measure(run: MilitaryRun) -> dict[str, object]:
    totals = military_totals(run.result.events)
    return {
        "scenario": run.scenario.label,
        "pay_share_of_treasury": run.scenario.pay_share_of_treasury,
        "garrison_troops_per_node": run.scenario.garrison_troops_per_node,
        "nominal_pressure": run.scenario.nominal_pressure,
        "shock_probability": run.scenario.monthly_event_probability,
        "shock_severity_floor": run.scenario.severity_floor,
        **totals,
    }


def run_military_experiment(
    *,
    config: SimulationConfig | None = None,
    scenarios: tuple[MilitaryScenario, ...] | None = None,
) -> MilitaryResults:
    """Run the pay-share sweep and return the curve and the series behind it."""
    chosen = scenarios or default_scenarios()
    runs = tuple(run_military_scenario(scenario, config=config) for scenario in chosen)

    def stack(
        build: Callable[[MilitaryRun], pl.DataFrame], columns: tuple[str, ...]
    ) -> pl.DataFrame:
        return pl.concat(
            [build(run).with_columns(pl.lit(run.scenario.label).alias("scenario")) for run in runs],
            how="diagonal_relaxed",
        ).select(["scenario", *columns])

    return MilitaryResults(
        curve=pl.DataFrame([_measure(run) for run in runs]).select(list(CURVE_COLUMNS)),
        band_series=stack(
            lambda run: band_series(run.result.events),
            (
                "tick",
                "number_of_bands",
                "total_band_troops",
                "largest_band_troops",
                "largest_band_share",
                "mean_band_troops",
            ),
        ),
        band_roster=stack(
            lambda run: band_roster(run.result.events),
            (
                "tick",
                "band_id",
                "node_id",
                "troops",
                "cohesion",
                "network",
                "mobility",
                "arms_per_member",
            ),
        ),
        desertion=stack(
            lambda run: desertion_rate(run.result.events),
            ("tick", "possible_garrison_troops", "deserters_left", "desertion_rate"),
        ),
        recruitment=stack(
            lambda run: recruitment_series(run.result.events),
            (
                "tick",
                "levied_to_garrisons",
                "levied_to_bands",
                "unorganized_deserters",
            ),
        ),
        runs=runs,
    )
