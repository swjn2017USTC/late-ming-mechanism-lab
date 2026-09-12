"""Toy household endowments: five cohort classes, one per county node.

This is **not** social history. The cohort weights follow the illustrative example in
`docs/OMP_ENGINEERING_PLAN.md` §3, and every endowment is a development-scale assumption
graded ``S``. The fixture exists so the coping ladder can be exercised end to end; P08
replaces these numbers with sourced parameter cards, and P04 will give the credit and price
placeholders real counterparties.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from late_ming_lab.actors.elites import EliteLayer, LocalEliteAgent
from late_ming_lab.actors.government import CountyGovernment, GovernmentLayer, StateCapacity
from late_ming_lab.actors.households import (
    CohortClass,
    HouseholdCohortAgent,
    HouseholdPopulation,
)
from late_ming_lab.actors.merchants import MerchantHouse, MerchantLayer
from late_ming_lab.evidence.grades import DataProvenance
from late_ming_lab.networks.graphs import SpatialGraphs
from late_ming_lab.networks.nodes import SpatialNodes

#: Adults per household is not modelled in detail; one assumption covers all classes.
ADULTS_PER_HOUSEHOLD: Final[float] = 2.0


@dataclass(frozen=True, slots=True)
class CohortEndowment:
    """Per-household endowment of one cohort class, in the units of the model."""

    cohort_class: CohortClass
    households: float
    land_mu: float
    grain_shi: float
    silver_tael: float
    debt_tael: float
    movable_assets_tael: float


COHORT_ENDOWMENT_PROVENANCE: Final[DataProvenance] = DataProvenance.assumption(
    "development-scale cohort weights (after the engineering plan's illustrative example) "
    "and per-household endowments of land, grain, silver, debt and movable assets; grade S, "
    "to be replaced by sourced parameter cards in P08"
)


def toy_endowments() -> tuple[CohortEndowment, ...]:
    """The five cohort classes used by every county node of the toy dataset."""
    return (
        CohortEndowment(
            cohort_class=CohortClass.LANDLESS_LABOURER,
            households=820.0,
            land_mu=0.0,
            grain_shi=1.0,
            silver_tael=0.5,
            debt_tael=0.5,
            movable_assets_tael=1.0,
        ),
        CohortEndowment(
            cohort_class=CohortClass.TENANT_HOUSEHOLD,
            households=650.0,
            land_mu=2.0,
            grain_shi=1.5,
            silver_tael=0.5,
            debt_tael=2.0,
            movable_assets_tael=1.5,
        ),
        CohortEndowment(
            cohort_class=CohortClass.POOR_SMALLHOLDER,
            households=1450.0,
            land_mu=8.0,
            grain_shi=2.0,
            silver_tael=1.0,
            debt_tael=1.0,
            movable_assets_tael=2.0,
        ),
        CohortEndowment(
            cohort_class=CohortClass.MIDDLE_SMALLHOLDER,
            households=1010.0,
            land_mu=15.0,
            grain_shi=4.0,
            silver_tael=3.0,
            debt_tael=1.5,
            movable_assets_tael=5.0,
        ),
        CohortEndowment(
            cohort_class=CohortClass.WEALTHY_FARMER,
            households=270.0,
            land_mu=30.0,
            grain_shi=10.0,
            silver_tael=10.0,
            debt_tael=1.0,
            movable_assets_tael=15.0,
        ),
    )


def cohort_id(node_id: str, cohort_class: CohortClass) -> str:
    """Stable cohort identity: one cohort per county node and class."""
    return f"{node_id}:{cohort_class.value}"


def toy_cohort_population(
    nodes: SpatialNodes, *, adults_per_household: float = ADULTS_PER_HOUSEHOLD
) -> HouseholdPopulation:
    """Build the toy population: every county node gets every cohort class."""
    cohorts = [
        HouseholdCohortAgent(
            cohort_id=cohort_id(node.node_id, endowment.cohort_class),
            node_id=node.node_id,
            cohort_class=endowment.cohort_class,
            zone=node.zone,
            households=endowment.households,
            adults=endowment.households * adults_per_household,
            land_mu=endowment.households * endowment.land_mu,
            grain_shi=endowment.households * endowment.grain_shi,
            silver_tael=endowment.households * endowment.silver_tael,
            debt_tael=endowment.households * endowment.debt_tael,
            movable_assets_tael=endowment.households * endowment.movable_assets_tael,
        )
        for node in nodes.counties
        for endowment in toy_endowments()
        if node.zone is not None
    ]
    return HouseholdPopulation(cohorts)


# ---------------------------------------------------------------------- P04 counterparties

#: Per-household endowments of the local interest, in the units of the model; grade S.
MERCHANT_SILVER_TAEL_PER_NODE: Final[float] = 1_200.0
MERCHANT_GRAIN_SHI_PER_NODE: Final[float] = 900.0
ELITE_HOUSEHOLDS_PER_NODE: Final[float] = 20.0
ELITE_LAND_MU_PER_NODE: Final[float] = 9_000.0
ELITE_GRAIN_SHI_PER_NODE: Final[float] = 4_000.0
ELITE_SILVER_TAEL_PER_NODE: Final[float] = 3_000.0


def toy_merchant_layer(graphs: SpatialGraphs, *, stock_scale: float = 1.0) -> MerchantLayer:
    """One merchant house at every node the trade graph reaches.

    County nodes hold the market; boundary nodes that appear as trade links hold a house too,
    because a consignment needs a buyer at the far end of the link. ``stock_scale`` exists
    because the reference endowments are arbitrary: 900 shi at a node whose cohorts need 2,100
    shi a month is a fourteenth of the declared six-month cover, and the phase's first mechanism
    question is exactly whether such thin stocks let arbitrage equalise anything.
    """
    if stock_scale <= 0:
        raise ValueError("merchant stock scale must be positive")
    return MerchantLayer(
        tuple(
            MerchantHouse(
                node_id=node_id,
                silver_tael=MERCHANT_SILVER_TAEL_PER_NODE * stock_scale,
                grain_shi=MERCHANT_GRAIN_SHI_PER_NODE * stock_scale,
            )
            for node_id in sorted(graphs.trade.nodes)
        )
    )


def toy_elite_layer(nodes: SpatialNodes) -> EliteLayer:
    """One aggregated elite house per county node.

    The initial elite claim on households is not set here: claims are derived from household
    debt, so the households' own opening debts define it.
    """
    return EliteLayer(
        tuple(
            LocalEliteAgent(
                node_id=node.node_id,
                households=ELITE_HOUSEHOLDS_PER_NODE,
                land_mu=ELITE_LAND_MU_PER_NODE,
                grain_shi=ELITE_GRAIN_SHI_PER_NODE,
                silver_tael=ELITE_SILVER_TAEL_PER_NODE,
            )
            for node in nodes.counties
        )
    )


#: County treasuries start empty: the fiscal layer is about extraction, not endowment.
COUNTY_SILVER_TAEL: Final[float] = 0.0
COUNTY_GRANARY_SHI: Final[float] = 0.0


def toy_capacity(
    *,
    tax_collection: float = 0.6,
    information: float = 0.5,
    relief: float = 0.5,
    coercion: float = 0.4,
    logistics: float = 0.6,
) -> StateCapacity:
    """Declared development-scale capacities, each one adjustable on its own."""
    return StateCapacity(
        tax_collection=tax_collection,
        information=information,
        relief=relief,
        coercion=coercion,
        logistics=logistics,
    )


def toy_government_layer(
    graphs: SpatialGraphs, *, capacity: StateCapacity | None = None
) -> GovernmentLayer:
    """One county government per county node, with an empty treasury and granary."""
    settings = capacity or toy_capacity()
    return GovernmentLayer(
        tuple(
            CountyGovernment(
                node_id=node.node_id,
                capacity=settings,
                silver_tael=COUNTY_SILVER_TAEL,
                grain_shi=COUNTY_GRANARY_SHI,
            )
            for node in graphs.nodes.counties
        )
    )
