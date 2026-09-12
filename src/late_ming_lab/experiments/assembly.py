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
07 taxation           TaxCollectionSystem
08 relief             OfficialReliefSystem, then EliteActionSystem
10 military finance   MilitaryFinanceSystem  (pay, rations, morale, cohesion)
11 desertion          DesertionSystem        (who leaves, and where they go)
12 recruitment        BandRecruitmentSystem  (the shared pool, levies, band formation)
13 band action        BandActionSystem       (raids, rations, movement toward food)
14 violence           ViolenceSystem         (suppression, dissolution, split, merge)
16 bookkeeping        CohortBookkeepingSystem, CountyBookkeepingSystem, military records
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
    GARRISON_TROOPS_PER_NODE,
    toy_band_layer,
    toy_cohort_population,
    toy_elite_layer,
    toy_government_layer,
    toy_merchant_layer,
    toy_military_layer,
)
from late_ming_lab.actors.government import GovernmentLayer, StateCapacity
from late_ming_lab.actors.households import HouseholdPopulation
from late_ming_lab.actors.merchants import MerchantLayer
from late_ming_lab.actors.military import BandLayer, MilitaryLayer
from late_ming_lab.core.tick import System
from late_ming_lab.evidence.parameters import (
    BandParameters,
    CropParameters,
    EliteParameters,
    FiscalParameters,
    HouseholdParameters,
    MarketParameters,
    MilitaryParameters,
    core_default_band_parameters,
    core_default_crop_parameters,
    core_default_elite_parameters,
    core_default_fiscal_parameters,
    core_default_household_parameters,
    core_default_market_parameters,
    core_default_military_parameters,
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
from late_ming_lab.systems.military import (
    BandActionSystem,
    BandRecruitmentSystem,
    DeserterPool,
    DesertionSystem,
    MilitaryBookkeepingSystem,
    MilitaryFinanceSystem,
    ViolenceSystem,
)

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
    military: MilitaryLayer
    bands: BandLayer
    systems: tuple[System, ...]
    calendar: AgriculturalCalendar
    crop_parameters: CropParameters
    household_parameters: HouseholdParameters
    market_parameters: MarketParameters
    elite_parameters: EliteParameters
    military_parameters: MilitaryParameters
    band_parameters: BandParameters


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
    military_parameters: MilitaryParameters | None = None,
    band_parameters: BandParameters | None = None,
    with_military: bool = False,
    garrison_troops: float | None = None,
) -> Economy:
    """Build the toy economy; every argument is a scenario knob, every default is grade ``S``."""
    zone_calendar = calendar or core_default_calendar()
    crops = crop_parameters or core_default_crop_parameters()
    households = household_parameters or core_default_household_parameters()
    markets = market_parameters or core_default_market_parameters()
    elite_settings = elite_parameters or core_default_elite_parameters()
    garrisons = military_parameters or core_default_military_parameters()
    bands = band_parameters or core_default_band_parameters()
    # The military ships off unless asked for, so the measurements P03-P05 recorded stay exactly
    # what they were. Asking for it without fiscal is allowed: an unpaid, unfed garrison is a
    # legitimate configuration, and the one that deserts for purely fiscal reasons.
    military_enabled = with_military

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
    military = toy_military_layer(
        graphs,
        troops_per_node=(GARRISON_TROOPS_PER_NODE if garrison_troops is None else garrison_troops),
    )
    band_layer = toy_band_layer()
    deserter_pool = DeserterPool()
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
    if military_enabled:
        systems.extend(
            (
                MilitaryFinanceSystem(
                    military=military,
                    governments=governments,
                    parameters=garrisons,
                    merchants=merchants,
                    book=market.book,
                ),
                DesertionSystem(
                    military=military,
                    population=population,
                    parameters=garrisons,
                    pool=deserter_pool,
                ),
                BandRecruitmentSystem(
                    military=military,
                    bands=band_layer,
                    population=population,
                    parameters=garrisons,
                    band_parameters=bands,
                    pool=deserter_pool,
                ),
                BandActionSystem(
                    bands=band_layer,
                    military=military,
                    population=population,
                    elites=elites,
                    governments=governments,
                    graphs=graphs,
                    parameters=bands,
                    military_parameters=garrisons,
                ),
                ViolenceSystem(
                    bands=band_layer,
                    military=military,
                    population=population,
                    military_parameters=garrisons,
                    band_parameters=bands,
                ),
                MilitaryBookkeepingSystem(military=military, bands=band_layer),
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
        military=military,
        bands=band_layer,
        systems=tuple(systems),
        calendar=zone_calendar,
        crop_parameters=crops,
        household_parameters=households,
        market_parameters=markets,
        elite_parameters=elite_settings,
        military_parameters=garrisons,
        band_parameters=bands,
    )
