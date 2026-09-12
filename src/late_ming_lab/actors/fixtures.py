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

from late_ming_lab.actors.households import (
    CohortClass,
    HouseholdCohortAgent,
    HouseholdPopulation,
)
from late_ming_lab.evidence.grades import DataProvenance
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
