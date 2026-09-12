"""Agricultural state and harvest.

The coupling from climate to households is deliberately explicit: the climate system records
one impact per node and month in the event log, and this layer reads that record back. Nothing
shares mutable state across phases, and the whole climate→crop chain can be replayed from the
log alone.

The production function is one line of arithmetic, stated in full:

```text
cultivated_mu   = min(land_mu, adults * land_per_adult_capacity_mu)
season_impact   = sum of (severity * calendar sensitivity) since the previous harvest
yield_fraction  = max(0, 1 - yield_loss_scale * season_impact)
harvest_shi     = cultivated_mu * yield_shi_per_mu[zone] * yield_fraction
```

It is a declared assumption, not an estimated agronomic model (grade ``S``): it says that
anomalies accumulate over the season and that the accumulation destroys yield in proportion.
P08 replaces the coefficients with sourced cards; P03 only guarantees that the statement is
explicit, logged and reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from late_ming_lab.actors.elites import EliteLayer
from late_ming_lab.actors.households import (
    HARVEST_RULE_VERSION,
    HouseholdCohortAgent,
    HouseholdPopulation,
    emit_cohort_event,
)
from late_ming_lab.core.tick import (
    RESOURCE_AGRICULTURE,
    RESOURCE_CLIMATE,
    RESOURCE_COHORT_GRAIN,
    RESOURCE_ELITE_GRAIN,
    TickContext,
    TickPhase,
)
from late_ming_lab.evidence.parameters import CropParameters, HouseholdParameters
from late_ming_lab.systems.calendar import AgriculturalCalendar
from late_ming_lab.systems.climate import CLIMATE_EVENT_TYPE
from late_ming_lab.systems.markets import emit_elite_event

AGRICULTURAL_STATE_RULE_VERSION: Final[str] = "agricultural-state-v1"


@dataclass(frozen=True, slots=True)
class HarvestResult:
    """What one cohort's harvest came to, before rent."""

    cultivated_mu: float
    season_impact: float
    yield_fraction: float
    grain_shi: float


def harvest_grain_shi(
    cohort: HouseholdCohortAgent,
    *,
    parameters: CropParameters,
    season_impact: float,
) -> HarvestResult:
    """Apply the declared production function to one cohort."""
    cultivated = min(cohort.land_mu, cohort.adults * parameters.land_per_adult_capacity_mu)
    yield_fraction = max(0.0, 1.0 - parameters.yield_loss_scale * season_impact)
    grain = cultivated * parameters.yield_shi_per_mu[cohort.zone] * yield_fraction
    return HarvestResult(
        cultivated_mu=cultivated,
        season_impact=season_impact,
        yield_fraction=yield_fraction,
        grain_shi=grain,
    )


class AgriculturalStateSystem:
    """Tick phase 02: accumulate this month's exogenous impact into each cohort's season."""

    name: str = "agricultural-state"
    phase: TickPhase = TickPhase.AGRICULTURAL_STATE
    reads: frozenset[str] = frozenset({RESOURCE_CLIMATE})
    writes: frozenset[str] = frozenset({RESOURCE_AGRICULTURE})

    def __init__(self, population: HouseholdPopulation) -> None:
        self._population = population

    def step(self, ctx: TickContext) -> None:
        impacts = {
            event.region: event.trigger["impact"]
            for event in ctx.logger.events_for_tick(ctx.tick)
            if event.event_type == CLIMATE_EVENT_TYPE and event.region is not None
        }
        for cohort in self._population:
            cohort.accumulate_climate_impact(impacts.get(cohort.node_id, 0.0))


class HarvestSystem:
    """Tick phase 03: take the crop in, pay rent, and let a good harvest reset coping."""

    name: str = "harvest"
    phase: TickPhase = TickPhase.GRAIN_PRODUCTION
    # The land and adult endowments are carried over from previous ticks, so the phase-level
    # claim names the season's state and the grain this phase moves, not every field it reads.
    reads: frozenset[str] = frozenset({RESOURCE_AGRICULTURE, RESOURCE_COHORT_GRAIN})
    writes: frozenset[str] = frozenset(
        {RESOURCE_AGRICULTURE, RESOURCE_COHORT_GRAIN, RESOURCE_ELITE_GRAIN}
    )

    def __init__(
        self,
        population: HouseholdPopulation,
        calendar: AgriculturalCalendar,
        crop_parameters: CropParameters,
        household_parameters: HouseholdParameters,
        *,
        elites: EliteLayer | None = None,
    ) -> None:
        self._population = population
        self._calendar = calendar
        self._crop_parameters = crop_parameters
        self._household_parameters = household_parameters
        self._elites = elites

    def step(self, ctx: TickContext) -> None:
        month = ctx.month.month
        for cohort in self._population:
            zone_calendar = self._calendar.calendar_for(cohort.zone)
            if month not in zone_calendar.harvest_ticks:
                continue
            result = harvest_grain_shi(
                cohort,
                parameters=self._crop_parameters,
                season_impact=cohort.season_impact,
            )
            self._population.set_node_yield_factor(cohort.node_id, result.yield_fraction)
            emit_cohort_event(
                ctx,
                cohort,
                cohort.record_harvest(
                    grain_shi=result.grain_shi,
                    cultivated_mu=result.cultivated_mu,
                    yield_fraction=result.yield_fraction,
                    season_impact=result.season_impact,
                    rule_version=HARVEST_RULE_VERSION,
                ),
                self.phase,
            )
            self._pay_rent(ctx, cohort, result.grain_shi)
            self._maybe_reset_coping(ctx, cohort, result.grain_shi)

    def _pay_rent(self, ctx: TickContext, cohort: HouseholdCohortAgent, harvest_shi: float) -> None:
        """Pay rent to the local elite; the counterparty P03 left unmodelled."""
        share = self._household_parameters.rent_share_for(cohort.cohort_class.value)
        if share <= 0.0 or harvest_shi <= 0.0:
            return
        rent = min(harvest_shi * share, cohort.grain_shi)
        if rent <= 0.0:
            return
        house = self._elites.require(cohort.node_id) if self._elites is not None else None
        emit_cohort_event(
            ctx,
            cohort,
            cohort.record_rent_payment(
                grain_shi=rent,
                share=share,
                landlord_id=house.elite_id if house is not None else "unmodelled-landlord",
                rule_version=HARVEST_RULE_VERSION,
            ),
            self.phase,
        )
        if house is None:
            return
        emit_elite_event(
            ctx,
            house,
            house.receive_grain(
                grain_shi=rent,
                payer_id=cohort.cohort_id,
                reason="rent",
                rule_version=HARVEST_RULE_VERSION,
            ),
            self.phase,
        )

    def _maybe_reset_coping(
        self, ctx: TickContext, cohort: HouseholdCohortAgent, harvest_shi: float
    ) -> None:
        annual_need = self._household_parameters.annual_need_shi(cohort.adults)
        if harvest_shi < self._household_parameters.harvest_recovery_grain_ratio * annual_need:
            return
        event = cohort.reset_coping_stage(
            reason="harvest-covers-need", rule_version=HARVEST_RULE_VERSION
        )
        if event is not None:
            emit_cohort_event(ctx, cohort, event, self.phase)
