"""Household consumption, debt service and the eligibility bookkeeping.

Three systems, on the tick phases the plan assigns to them:

| Phase | System | What it does |
| --- | --- | --- |
| 04 household consumption | `ConsumptionSystem` | runs each cohort's coping ladder for the month |
| 06 credit and debt | `DebtServiceSystem` | accrues interest, repays what a household can spare |
| 16 bookkeeping | `CohortBookkeepingSystem` | eligibility, state snapshot, invariant check |

Eligibility is where P03 is deliberately thin: the model records *who could* move, sell labour
to an army or join an armed group, and moves nobody. Distress is measured as the share of the
subsistence floor that went unmet over the trailing window — a physical ledger quantity. There
is no anger, grievance or rebellion scalar anywhere in this layer, by design.
"""

from __future__ import annotations

from typing import Final

from late_ming_lab.actors.households import (
    BOOKKEEPING_RULE_VERSION,
    DEBT_RULE_VERSION,
    ELIGIBILITY_RULE_VERSION,
    HOUSEHOLD_RULE_VERSION,
    CohortEventType,
    HouseholdPopulation,
    emit_cohort_event,
)
from late_ming_lab.core.tick import TickContext, TickPhase
from late_ming_lab.evidence.parameters import HouseholdParameters

CONSUMPTION_EVENT: Final[CohortEventType] = CohortEventType.CONSUMPTION


class ConsumptionSystem:
    """Tick phase 04: the household budget and the coping ladder."""

    name: str = "household-consumption"
    phase: TickPhase = TickPhase.HOUSEHOLD_CONSUMPTION

    def __init__(self, population: HouseholdPopulation, parameters: HouseholdParameters) -> None:
        self._population = population
        self._parameters = parameters
        for cohort in population:
            cohort.set_land_reference_value(parameters.land_reference_value_tael_per_mu)

    def step(self, ctx: TickContext) -> None:
        for cohort in self._population:
            for event in cohort.monthly_budget(
                parameters=self._parameters,
                labour_demand_factor=self._population.node_yield_factor(cohort.node_id),
                rule_version=HOUSEHOLD_RULE_VERSION,
            ):
                emit_cohort_event(ctx, cohort, event, self.phase)
                if event.event_type is CONSUMPTION_EVENT:
                    self._population.record_month(
                        cohort.cohort_id,
                        need_shi=event.trigger["need_shi"],
                        unmet_shi=event.trigger["unmet_shi"],
                    )


class DebtServiceSystem:
    """Tick phase 06: interest accrues first, then the household repays what it can spare."""

    name: str = "debt-service"
    phase: TickPhase = TickPhase.CREDIT_AND_DEBT

    def __init__(self, population: HouseholdPopulation, parameters: HouseholdParameters) -> None:
        self._population = population
        self._parameters = parameters

    def step(self, ctx: TickContext) -> None:
        for cohort in self._population:
            if cohort.debt_tael > 0:
                interest = cohort.debt_tael * self._parameters.interest_rate_monthly
                emit_cohort_event(
                    ctx,
                    cohort,
                    cohort.record_debt_interest(
                        interest_tael=interest,
                        rate_monthly=self._parameters.interest_rate_monthly,
                        rule_version=DEBT_RULE_VERSION,
                    ),
                    self.phase,
                )
            reserve = (
                self._parameters.debt_repayment_silver_reserve_tael_per_household
                * cohort.households
            )
            spare = max(0.0, cohort.silver_tael - reserve)
            repaid = min(cohort.debt_tael, spare)
            if repaid > 0:
                emit_cohort_event(
                    ctx,
                    cohort,
                    cohort.record_debt_repayment(
                        repaid_tael=repaid, rule_version=DEBT_RULE_VERSION
                    ),
                    self.phase,
                )


class CohortBookkeepingSystem:
    """Tick phase 16: eligibility flags, monthly state record, invariant check."""

    name: str = "cohort-bookkeeping"
    phase: TickPhase = TickPhase.BOOKKEEPING

    def __init__(self, population: HouseholdPopulation, parameters: HouseholdParameters) -> None:
        self._population = population
        self._parameters = parameters

    def step(self, ctx: TickContext) -> None:
        for cohort in self._population:
            ratio = self._population.unmet_ratio(cohort.cohort_id)
            event = cohort.record_eligibility(
                unmet_ratio_12m=ratio,
                temporary=ratio >= self._parameters.temporary_migration_unmet_ratio,
                permanent=ratio >= self._parameters.permanent_migration_unmet_ratio,
                recruitment=(
                    ratio >= self._parameters.recruitment_unmet_ratio
                    and cohort.land_per_household_mu
                    <= self._parameters.recruitment_max_land_per_household_mu
                ),
                rule_version=ELIGIBILITY_RULE_VERSION,
            )
            if event is not None:
                emit_cohort_event(ctx, cohort, event, self.phase)
            emit_cohort_event(
                ctx,
                cohort,
                cohort.snapshot_event(rule_version=BOOKKEEPING_RULE_VERSION),
                self.phase,
            )
        self._population.check_invariants()
