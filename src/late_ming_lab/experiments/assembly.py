"""Assembling a run: the toy economy wired into the kernel in tick order.

One place builds the whole P04 economy — spatial graphs, cohorts, merchants, elites, and the
systems that connect them — so the experiments cannot drift apart in how they wire the model, and
so a reader can see the complete tick order in one screen:

```text
01 climate            ClimateSystem
02 agricultural state AgriculturalStateSystem
03 harvest            HarvestSystem          (rent paid to the elite)
04 consumption        ConsumptionSystem      (ladder against market and lender)
05 market clearing    MarketClearingSystem   (surplus sales, intercounty trade, prices)
06 credit and debt    DebtServiceSystem      (interest, cash and grain repayment)
08 relief             EliteActionSystem      (private relief, tax mediation hook)
16 bookkeeping        CohortBookkeepingSystem
```

Everything built here is a development-scale assumption graded ``S``: the toy county dataset,
the toy cohort endowments, the toy merchant and elite endowments, and every parameter set. None
of it is history, and the assembly says so rather than leaving it to the reader.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from late_ming_lab.actors.elites import EliteLayer, TaxMediationPolicy
from late_ming_lab.actors.fixtures import (
    toy_cohort_population,
    toy_elite_layer,
    toy_government_layer,
    toy_merchant_layer,
)
from late_ming_lab.actors.government import GovernmentLayer, StateCapacity
from late_ming_lab.actors.households import HouseholdPopulation
from late_ming_lab.actors.merchants import MerchantLayer
from late_ming_lab.core.tick import System
from late_ming_lab.evidence.parameters import (
    CropParameters,
    EliteParameters,
    FiscalParameters,
    HouseholdParameters,
    MarketParameters,
    core_default_crop_parameters,
    core_default_elite_parameters,
    core_default_fiscal_parameters,
    core_default_household_parameters,
    core_default_market_parameters,
)
from late_ming_lab.networks.disruption import CalmTrade, TradeDisruption
from late_ming_lab.networks.fixtures import toy_spatial_dataset
from late_ming_lab.networks.graphs import SpatialGraphs
from late_ming_lab.policies.fiscal import ExtractionPolicy
from late_ming_lab.systems.agriculture import AgriculturalStateSystem, HarvestSystem
from late_ming_lab.systems.calendar import AgriculturalCalendar, core_default_calendar
from late_ming_lab.systems.climate import BaselineClimate, ClimateModel, ClimateSystem
from late_ming_lab.systems.elites import EliteActionSystem, LocalCredit
from late_ming_lab.systems.fiscal import (
    CountyBookkeepingSystem,
    OfficialReliefSystem,
    TaxCollectionSystem,
)
from late_ming_lab.systems.household_survival import (
    CohortBookkeepingSystem,
    ConsumptionSystem,
    DebtServiceSystem,
)
from late_ming_lab.systems.markets import MarketClearingSystem

ASSEMBLY_VERSION: Final[str] = "toy-economy-v1"


@dataclass(frozen=True, slots=True)
class Economy:
    """One wired model, ready to run."""

    graphs: SpatialGraphs
    population: HouseholdPopulation
    merchants: MerchantLayer
    elites: EliteLayer
    market: MarketClearingSystem
    credit: LocalCredit
    governments: GovernmentLayer | None
    systems: tuple[System, ...]
    calendar: AgriculturalCalendar
    crop_parameters: CropParameters
    household_parameters: HouseholdParameters
    market_parameters: MarketParameters
    elite_parameters: EliteParameters


def build_toy_economy(
    *,
    climate_model: ClimateModel | None = None,
    disruption: TradeDisruption | None = None,
    tax_mediation: TaxMediationPolicy | None = None,
    calendar: AgriculturalCalendar | None = None,
    crop_parameters: CropParameters | None = None,
    household_parameters: HouseholdParameters | None = None,
    market_parameters: MarketParameters | None = None,
    elite_parameters: EliteParameters | None = None,
    merchant_stock_scale: float = 1.0,
    with_fiscal: bool = True,
    fiscal_parameters: FiscalParameters | None = None,
    capacity: StateCapacity | None = None,
    extraction_policy: ExtractionPolicy | None = None,
    nominal_pressure: float = 0.02,
) -> Economy:
    """Build the toy economy; every argument is a scenario knob, every default is grade ``S``."""
    zone_calendar = calendar or core_default_calendar()
    crops = crop_parameters or core_default_crop_parameters()
    households = household_parameters or core_default_household_parameters()
    markets = market_parameters or core_default_market_parameters()
    elite_settings = elite_parameters or core_default_elite_parameters()

    graphs = toy_spatial_dataset().build()
    population = toy_cohort_population(graphs.nodes)
    merchants = toy_merchant_layer(graphs, stock_scale=merchant_stock_scale)
    elites = toy_elite_layer(graphs.nodes)

    market = MarketClearingSystem(
        graphs=graphs,
        population=population,
        merchants=merchants,
        household_parameters=households,
        market_parameters=markets,
        elite_parameters=elite_settings,
        elite_grain_provider=elites,
        disruption=disruption or CalmTrade(),
    )
    credit = LocalCredit(elites=elites, population=population, parameters=elite_settings)
    governments = toy_government_layer(graphs, capacity=capacity) if with_fiscal else None
    fiscal = fiscal_parameters or core_default_fiscal_parameters()
    systems: list[System] = [
        ClimateSystem(graphs.nodes, zone_calendar, climate_model or BaselineClimate()),
        AgriculturalStateSystem(population),
        HarvestSystem(population, zone_calendar, crops, households, elites=elites),
        ConsumptionSystem(
            population, households, book=market.book, merchants=merchants, credit=credit
        ),
        market,
        DebtServiceSystem(population, households, elite_settings, elites=elites, book=market.book),
    ]
    if governments is not None:
        systems.extend(
            (
                TaxCollectionSystem(
                    governments=governments,
                    population=population,
                    elites=elites,
                    merchants=merchants,
                    book=market.book,
                    fiscal_parameters=fiscal,
                    household_parameters=households,
                    elite_parameters=elite_settings,
                    credit=credit,
                    policy=extraction_policy,
                    tax_mediation=tax_mediation,
                    nominal_pressure=nominal_pressure,
                ),
                OfficialReliefSystem(
                    governments=governments,
                    population=population,
                    merchants=merchants,
                    book=market.book,
                    fiscal_parameters=fiscal,
                    household_parameters=households,
                ),
            )
        )
    systems.append(
        EliteActionSystem(
            elites=elites,
            population=population,
            parameters=elite_settings,
            household_parameters=households,
            book=market.book,
        )
    )
    systems.append(CohortBookkeepingSystem(population, households))
    if governments is not None:
        systems.append(CountyBookkeepingSystem(governments=governments, population=population))
    return Economy(
        graphs=graphs,
        population=population,
        merchants=merchants,
        elites=elites,
        market=market,
        credit=credit,
        governments=governments,
        systems=tuple(systems),
        calendar=zone_calendar,
        crop_parameters=crops,
        household_parameters=households,
        market_parameters=markets,
        elite_parameters=elite_settings,
    )
