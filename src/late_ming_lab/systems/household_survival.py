"""Household consumption, debt service and the eligibility bookkeeping.

Three systems, on the tick phases the plan assigns to them:

| Phase | System | What it does |
| --- | --- | --- |
| 04 household consumption | `ConsumptionSystem` | the coping ladder |
| 06 credit and debt | `DebtServiceSystem` | interest on the lender's terms, then repayment |
| 16 bookkeeping | `CohortBookkeepingSystem` | eligibility, state snapshot, invariant check |

Eligibility is where this layer is deliberately thin: the model records *who could* move, sell
labour to an army or join an armed group, and moves nobody. Distress is measured as the share of
the subsistence floor that went unmet over the trailing window — a physical ledger quantity.
There is no anger, grievance or rebellion scalar anywhere in this layer, by design.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from late_ming_lab.actors.elites import EliteLayer, LocalEliteAgent
from late_ming_lab.actors.exchange import CreditSource
from late_ming_lab.actors.households import (
    BOOKKEEPING_RULE_VERSION,
    DEBT_RULE_VERSION,
    ELIGIBILITY_RULE_VERSION,
    HOUSEHOLD_RULE_VERSION,
    CohortEventType,
    HouseholdCohortAgent,
    HouseholdPopulation,
    emit_cohort_event,
)
from late_ming_lab.actors.merchants import MerchantLayer
from late_ming_lab.core.tick import TickContext, TickPhase
from late_ming_lab.evidence.parameters import EliteParameters, HouseholdParameters
from late_ming_lab.systems.markets import (
    LocalGrainMarket,
    MarketBook,
    emit_elite_event,
)

CONSUMPTION_EVENT: Final[CohortEventType] = CohortEventType.CONSUMPTION


class ConsumptionSystem:
    """Tick phase 04: the household budget and the coping ladder."""

    name: str = "household-consumption"
    phase: TickPhase = TickPhase.HOUSEHOLD_CONSUMPTION

    def __init__(
        self,
        population: HouseholdPopulation,
        parameters: HouseholdParameters,
        *,
        book: MarketBook,
        merchants: MerchantLayer,
        credit: CreditSource,
    ) -> None:
        self._population = population
        self._parameters = parameters
        self._credit = credit
        self._markets: Mapping[str, LocalGrainMarket] = {
            node_id: LocalGrainMarket(node_id=node_id, book=book, merchants=merchants)
            for node_id in {cohort.node_id for cohort in population}
        }
        for cohort in population:
            cohort.set_land_reference_value(parameters.land_reference_value_tael_per_mu)

    def step(self, ctx: TickContext) -> None:
        for cohort in self._population:
            for event in cohort.monthly_budget(
                ctx,
                parameters=self._parameters,
                labour_demand_factor=self._population.node_yield_factor(cohort.node_id),
                market=self._markets[cohort.node_id],
                credit=self._credit,
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
    """Tick phase 06: interest on the lender's terms, then repayment.

    Interest is charged by the lender, not chosen by the household, and the household's debt is
    the elite's claim: claims are derived from household debt, so the two sides cannot drift.

    Repayment happens two ways. A household with silver above its reserve pays cash, which moves
    to the elite. A household whose harvest exceeds its own year of need repays in grain at the
    posted market price, and the elite takes that grain into its granary — the ordinary way a
    grain loan was cleared in this economy.
    """

    name: str = "debt-service"
    phase: TickPhase = TickPhase.CREDIT_AND_DEBT

    def __init__(
        self,
        population: HouseholdPopulation,
        parameters: HouseholdParameters,
        elite_parameters: EliteParameters,
        *,
        elites: EliteLayer,
        book: MarketBook,
    ) -> None:
        self._population = population
        self._parameters = parameters
        self._elite_parameters = elite_parameters
        self._elites = elites
        self._book = book

    def step(self, ctx: TickContext) -> None:
        for cohort in self._population:
            house = self._elites.require(cohort.node_id)
            self._accrue_interest(ctx, cohort)
            self._repay_in_cash(ctx, cohort, house)
            self._repay_from_harvest(ctx, cohort, house)

    def _accrue_interest(self, ctx: TickContext, cohort: HouseholdCohortAgent) -> None:
        if cohort.debt_tael <= 0.0:
            return
        rate = self._elite_parameters.interest_rate_monthly
        emit_cohort_event(
            ctx,
            cohort,
            cohort.record_debt_interest(
                interest_tael=cohort.debt_tael * rate,
                rate_monthly=rate,
                rule_version=DEBT_RULE_VERSION,
            ),
            self.phase,
        )

    def _repay_in_cash(
        self, ctx: TickContext, cohort: HouseholdCohortAgent, house: LocalEliteAgent
    ) -> None:
        reserve = (
            self._parameters.debt_repayment_silver_reserve_tael_per_household * cohort.households
        )
        spare = max(0.0, cohort.silver_tael - reserve)
        repaid = min(cohort.debt_tael, spare)
        if repaid <= 0.0:
            return
        emit_cohort_event(
            ctx,
            cohort,
            cohort.record_debt_repayment(repaid_tael=repaid, rule_version=DEBT_RULE_VERSION),
            self.phase,
        )
        emit_elite_event(
            ctx,
            house,
            house.receive_repayment(
                repaid_tael=repaid,
                borrower_id=cohort.cohort_id,
                in_kind=False,
                rule_version=DEBT_RULE_VERSION,
            ),
            self.phase,
        )

    def _repay_from_harvest(
        self, ctx: TickContext, cohort: HouseholdCohortAgent, house: LocalEliteAgent
    ) -> None:
        if cohort.debt_tael <= 0.0:
            return
        keep = (
            self._parameters.debt_repayment_grain_ratio_of_annual_need
            * self._parameters.annual_need_shi(cohort.adults)
        )
        surplus = max(0.0, cohort.grain_shi - keep)
        if surplus <= 0.0:
            return
        price = self._book.price(cohort.node_id)
        repaid = min(cohort.debt_tael, surplus * price)
        grain = repaid / price
        emit_cohort_event(
            ctx,
            cohort,
            cohort.record_repayment_from_harvest(
                repaid_tael=repaid,
                price_tael_per_shi=price,
                rule_version=DEBT_RULE_VERSION,
            ),
            self.phase,
        )
        emit_elite_event(
            ctx,
            house,
            house.receive_grain(
                grain_shi=grain,
                payer_id=cohort.cohort_id,
                reason="grain-repayment",
                rule_version=DEBT_RULE_VERSION,
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
