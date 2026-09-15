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
from late_ming_lab.core.tick import (
    RESOURCE_AGRICULTURE,
    RESOURCE_COHORT_ADULTS,
    RESOURCE_COHORT_ASSETS,
    RESOURCE_COHORT_DEBT,
    RESOURCE_COHORT_GRAIN,
    RESOURCE_COHORT_HOUSEHOLDS,
    RESOURCE_COHORT_LAND,
    RESOURCE_COHORT_SILVER,
    RESOURCE_DISTRESS_WINDOW,
    RESOURCE_ELITE_GRAIN,
    RESOURCE_ELITE_LAND,
    RESOURCE_ELITE_SILVER,
    RESOURCE_MARKET_PRICE,
    RESOURCE_MERCHANT_STOCK,
    TickContext,
    TickPhase,
)
from late_ming_lab.evidence.parameters import EliteParameters, HouseholdParameters
from late_ming_lab.systems.elites import FORECLOSURE_RULE_VERSION
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
    # The adult and household counts, the land endowment and the posted price are carried over
    # from previous ticks rather than produced in this one, so they are not claimed here.
    reads: frozenset[str] = frozenset(
        {
            RESOURCE_AGRICULTURE,
            RESOURCE_COHORT_ASSETS,
            RESOURCE_COHORT_DEBT,
            RESOURCE_COHORT_GRAIN,
            RESOURCE_COHORT_LAND,
            RESOURCE_COHORT_SILVER,
            RESOURCE_ELITE_SILVER,
            RESOURCE_MERCHANT_STOCK,
        }
    )
    writes: frozenset[str] = frozenset(
        {
            RESOURCE_COHORT_ASSETS,
            RESOURCE_COHORT_DEBT,
            RESOURCE_COHORT_GRAIN,
            RESOURCE_COHORT_LAND,
            RESOURCE_COHORT_SILVER,
            RESOURCE_DISTRESS_WINDOW,
            RESOURCE_ELITE_LAND,
            RESOURCE_ELITE_SILVER,
            RESOURCE_MERCHANT_STOCK,
        }
    )

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
            for node_id in sorted({cohort.node_id for cohort in population})
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

    A third, declared path is the accumulating branch of M004. A cohort whose outstanding
    obligation goes unserviced for ``foreclosure_after_unserviced_months`` consecutive months is
    declared in default, and the lender takes ``foreclosure_land_share_of_pledge`` of the pledged
    land in satisfaction of the debt. Both are neutral at V1's values — 0 unserviced months and a
    zero share — at which nothing here is declared, taken or emitted, so the run is V1's run.
    Whether that branch is a different trajectory from the mediating one is what the phase
    measures; this class only implements the rule and records it.
    """

    name: str = "debt-service"
    phase: TickPhase = TickPhase.CREDIT_AND_DEBT
    reads: frozenset[str] = frozenset(
        {
            RESOURCE_COHORT_DEBT,
            RESOURCE_COHORT_GRAIN,
            RESOURCE_COHORT_LAND,
            RESOURCE_COHORT_SILVER,
            RESOURCE_MARKET_PRICE,
        }
    )
    writes: frozenset[str] = frozenset(
        {
            RESOURCE_COHORT_DEBT,
            RESOURCE_COHORT_GRAIN,
            RESOURCE_COHORT_LAND,
            RESOURCE_COHORT_SILVER,
            RESOURCE_ELITE_GRAIN,
            RESOURCE_ELITE_LAND,
            RESOURCE_ELITE_SILVER,
        }
    )

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
        # The lender's arrears counter for this run: consecutive months each cohort's outstanding
        # obligation has gone unserviced. It is per-run state like the population's distress
        # window, not ambient state, and at the neutral term it is written and never read.
        self._unserviced_months: dict[str, int] = {}

    def step(self, ctx: TickContext) -> None:
        for cohort in self._population:
            house = self._elites.require(cohort.node_id)
            self._accrue_interest(ctx, cohort)
            serviced_tael = self._repay_in_cash(ctx, cohort, house) + self._repay_from_harvest(
                ctx, cohort, house
            )
            self._record_service(ctx, cohort, house, serviced_tael=serviced_tael)

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
    ) -> float:
        reserve = (
            self._parameters.debt_repayment_silver_reserve_tael_per_household * cohort.households
        )
        spare = max(0.0, cohort.silver_tael - reserve)
        repaid = min(cohort.debt_tael, spare)
        if repaid <= 0.0:
            return 0.0
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
        return repaid

    def _repay_from_harvest(
        self, ctx: TickContext, cohort: HouseholdCohortAgent, house: LocalEliteAgent
    ) -> float:
        if cohort.debt_tael <= 0.0:
            return 0.0
        keep = (
            self._parameters.debt_repayment_grain_ratio_of_annual_need
            * self._parameters.annual_need_shi(cohort.adults)
        )
        surplus = max(0.0, cohort.grain_shi - keep)
        if surplus <= 0.0:
            return 0.0
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
        return repaid

    # ------------------------------------------------------- the accumulating branch

    def _record_service(
        self,
        ctx: TickContext,
        cohort: HouseholdCohortAgent,
        house: LocalEliteAgent,
        *,
        serviced_tael: float,
    ) -> None:
        """Count the months an outstanding obligation went unserviced, and act on the count.

        A month counts as serviced when any repayment happened in it, in cash or in grain; a
        cohort with no debt carries no count. The count resets on service, and it also resets when
        a default is declared, so one default is declared per unserviced term rather than in every
        month after the first.
        """
        if cohort.debt_tael <= 0.0:
            self._unserviced_months.pop(cohort.cohort_id, None)
            return
        if serviced_tael > 0.0:
            self._unserviced_months[cohort.cohort_id] = 0
            return
        months = self._unserviced_months.get(cohort.cohort_id, 0) + 1
        self._unserviced_months[cohort.cohort_id] = months
        self._foreclose_if_in_default(ctx, cohort, house, months_unserviced=months)

    def _foreclose_if_in_default(
        self,
        ctx: TickContext,
        cohort: HouseholdCohortAgent,
        house: LocalEliteAgent,
        *,
        months_unserviced: int,
    ) -> None:
        term = self._elite_parameters.foreclosure_after_unserviced_months
        if term <= 0 or months_unserviced < term:
            return
        emit_elite_event(
            ctx,
            house,
            house.declare_default(
                outstanding_tael=cohort.debt_tael,
                months_unserviced=months_unserviced,
                borrower_id=cohort.cohort_id,
                rule_version=FORECLOSURE_RULE_VERSION,
            ),
            self.phase,
        )
        self._unserviced_months[cohort.cohort_id] = 0
        pledge_mu = self._pledged_land_mu(cohort)
        mu = min(
            pledge_mu * self._elite_parameters.foreclosure_land_share_of_pledge, cohort.land_mu
        )
        if mu <= 0.0:
            return
        reference_value = self._parameters.land_reference_value_tael_per_mu
        land_value = mu * reference_value
        settled_tael = min(cohort.debt_tael, land_value)
        # The pledge is forfeit whole, so the part of its value that the obligation did not absorb
        # stays with the lender: that margin is the gain that makes lending against land accumulate
        # land, and it is recorded rather than left implicit. Nothing pays it back to the cohort.
        surplus_tael = land_value - settled_tael
        emit_cohort_event(
            ctx,
            cohort,
            cohort.record_foreclosure(
                mu=mu,
                pledge_mu=pledge_mu,
                settled_tael=settled_tael,
                lender_id=house.elite_id,
                rule_version=FORECLOSURE_RULE_VERSION,
            ),
            self.phase,
        )
        emit_elite_event(
            ctx,
            house,
            house.foreclose_land(
                mu=mu,
                pledge_mu=pledge_mu,
                settled_tael=settled_tael,
                surplus_tael=surplus_tael,
                borrower_id=cohort.cohort_id,
                rule_version=FORECLOSURE_RULE_VERSION,
            ),
            self.phase,
        )

    def _pledged_land_mu(self, cohort: HouseholdCohortAgent) -> float:
        """The land an outstanding claim was taken against, by the rule that set the credit limit.

        Credit capacity is ``loan_to_value`` times the pledge's reference value (see
        ``LocalCredit.borrow``), so the pledge behind an outstanding obligation is that obligation
        over the loan-to-value ratio, and the land in it is that value at the declared land
        reference price — the same valuation the household itself pledges against. The pledge is
        capped by the land the cohort actually holds, so no cohort is foreclosed on land it does
        not have, and no second land price is introduced here.
        """
        loan_to_value = self._elite_parameters.loan_to_value
        if loan_to_value <= 0.0 or cohort.debt_tael <= 0.0:
            return 0.0
        reference_value = self._parameters.land_reference_value_tael_per_mu
        return min(cohort.land_mu, cohort.debt_tael / loan_to_value / reference_value)


class CohortBookkeepingSystem:
    """Tick phase 16: eligibility flags, monthly state record, invariant check."""

    name: str = "cohort-bookkeeping"
    phase: TickPhase = TickPhase.BOOKKEEPING
    reads: frozenset[str] = frozenset(
        {
            RESOURCE_AGRICULTURE,
            RESOURCE_COHORT_ADULTS,
            RESOURCE_COHORT_ASSETS,
            RESOURCE_COHORT_DEBT,
            RESOURCE_COHORT_GRAIN,
            RESOURCE_COHORT_HOUSEHOLDS,
            RESOURCE_COHORT_LAND,
            RESOURCE_COHORT_SILVER,
            RESOURCE_DISTRESS_WINDOW,
        }
    )
    writes: frozenset[str] = frozenset()

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
