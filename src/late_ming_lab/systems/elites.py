"""Elite action systems: lending, land purchase, private relief and tax mediation.

The counterparty the P03 ladder was missing. Credit is executed where the household asks for it
(during its own consumption phase, against the local elite's silver), while relief and tax
mediation are separate monthly actions of the elite.

Two things are deliberately *not* decided here:

- whether lending is good or bad. A loan keeps a household eating this month and enlarges its
  claim next month, and the same rule can produce both delay of collapse and land concentration.
  The phase's tests measure which happens under which parameters;
- what the tax should be. Elites can advance an obligation, but no tax demand exists before P05,
  so the default demand is zero and nothing is advanced. The interface is here so P05 has a
  bounded place to plug the real demand into.
"""

from __future__ import annotations

from typing import Final

from late_ming_lab.actors.elites import (
    EliteLayer,
    LocalEliteAgent,
    NoTaxMediation,
    TaxMediationPolicy,
)
from late_ming_lab.actors.exchange import CreditDecision, NodeBound, TradeOutcome
from late_ming_lab.actors.households import (
    HouseholdCohortAgent,
    HouseholdPopulation,
    emit_cohort_event,
)
from late_ming_lab.core.tick import TickContext, TickPhase
from late_ming_lab.evidence.parameters import EliteParameters, HouseholdParameters
from late_ming_lab.systems.markets import MarketBook, emit_elite_event

CREDIT_RULE_VERSION: Final[str] = "elite-credit-v1"
LAND_RULE_VERSION: Final[str] = "elite-land-v1"
RELIEF_RULE_VERSION: Final[str] = "elite-relief-v1"
TAX_MEDIATION_RULE_VERSION: Final[str] = "tax-mediation-v1"
ELITE_STATE_RULE_VERSION: Final[str] = "elite-state-v1"
ELITE_STATE_EVENT: Final[str] = "ELITE_STATE"


class LocalCredit:
    """The local elite as a lender and as the buyer of distress-sold land."""

    def __init__(
        self,
        *,
        elites: EliteLayer,
        population: HouseholdPopulation,
        parameters: EliteParameters,
    ) -> None:
        self._elites = elites
        self._population = population
        self._parameters = parameters

    @property
    def land_price_tael_per_mu(self) -> float:
        return self._parameters.land_purchase_price_tael_per_mu

    def claims_tael(self, node_id: str) -> float:
        """Outstanding claims on the households of a node; derived, never stored."""
        return sum(cohort.debt_tael for cohort in self._population if cohort.node_id == node_id)

    def borrow(
        self,
        ctx: TickContext,
        borrower: NodeBound,
        requested_tael: float,
        collateral_tael: float,
        existing_debt_tael: float,
    ) -> CreditDecision:
        """Lend against collateral, bounded by the borrower's limit and the lender's silver."""
        house = self._elites.require(borrower.node_id)
        limit = max(
            0.0,
            self._parameters.loan_to_value * collateral_tael - existing_debt_tael,
        )
        lendable = house.silver_tael * self._parameters.max_lending_share_of_silver
        capacity = min(limit, lendable)
        granted = max(0.0, min(requested_tael, capacity))
        if granted > 0.0:
            emit_elite_event(
                ctx,
                house,
                house.issue_loan(
                    granted_tael=granted,
                    borrower_id=_cohort_identity(borrower),
                    rule_version=CREDIT_RULE_VERSION,
                ),
                TickPhase.HOUSEHOLD_CONSUMPTION,
            )
        return CreditDecision(
            granted_tael=granted, capacity_tael=capacity, lender_id=house.elite_id
        )

    def sell_land(
        self, ctx: TickContext, seller: NodeBound, wanted_tael: float, max_mu: float
    ) -> TradeOutcome:
        """Buy land from a distressed household, limited by the elite's silver."""
        house = self._elites.require(seller.node_id)
        price = self.land_price_tael_per_mu
        paid = min(wanted_tael, house.silver_tael)
        mu = min(max_mu, paid / price)
        if mu <= 0.0:
            return TradeOutcome(quantity=0.0, value_tael=0.0, counterparty_id=house.elite_id)
        paid = min(mu * price, house.silver_tael)
        mu = min(mu, paid / price)
        emit_elite_event(
            ctx,
            house,
            house.buy_land(
                mu=mu,
                paid_tael=paid,
                seller_id=_cohort_identity(seller),
                rule_version=LAND_RULE_VERSION,
            ),
            TickPhase.HOUSEHOLD_CONSUMPTION,
        )
        return TradeOutcome(quantity=mu, value_tael=paid, counterparty_id=house.elite_id)


class EliteActionSystem:
    """Tick phase 08: private relief, tax mediation, and the elite's monthly state record."""

    name: str = "elite-actions"
    phase: TickPhase = TickPhase.RELIEF

    def __init__(
        self,
        *,
        elites: EliteLayer,
        population: HouseholdPopulation,
        parameters: EliteParameters,
        household_parameters: HouseholdParameters,
        book: MarketBook,
        tax_mediation: TaxMediationPolicy | None = None,
        tax_demand_tael_per_household: float = 0.0,
    ) -> None:
        self._elites = elites
        self._population = population
        self._parameters = parameters
        self._household_parameters = household_parameters
        self._book = book
        self._tax_mediation = tax_mediation or NoTaxMediation()
        self._tax_demand_tael_per_household = tax_demand_tael_per_household

    @property
    def tax_mediation(self) -> TaxMediationPolicy:
        return self._tax_mediation

    @property
    def tax_demand_tael_per_household(self) -> float:
        return self._tax_demand_tael_per_household

    def step(self, ctx: TickContext) -> None:
        for house in self._elites:
            self._mediate_tax(ctx, house)
            self._release_relief(ctx, house)
            self._record_state(ctx, house)
        self._elites.check_invariants()

    # ------------------------------------------------------------------ actions

    def _mediate_tax(self, ctx: TickContext, house: LocalEliteAgent) -> None:
        """Advance part of a client's obligation; there is no demand before P05."""
        if self._tax_demand_tael_per_household <= 0.0:
            return
        for cohort in self._local_cohorts(house.node_id):
            if cohort.households <= 0.0:
                continue
            demand = self._tax_demand_tael_per_household * cohort.households
            advanced = self._tax_mediation.advance_tael(
                parameters=self._parameters,
                client_land_mu=cohort.land_mu,
                demand_tael=demand,
            )
            advanced = min(advanced, house.silver_tael)
            if advanced <= 0.0:
                continue
            emit_elite_event(
                ctx,
                house,
                house.record_tax_mediation(
                    advanced_tael=advanced,
                    client_id=cohort.cohort_id,
                    demand_tael=demand,
                    rule_version=TAX_MEDIATION_RULE_VERSION,
                ),
                self.phase,
            )
            emit_cohort_event(
                ctx,
                cohort,
                cohort.record_tax_mediation(
                    advanced_tael=advanced,
                    mediator_id=house.elite_id,
                    rule_version=TAX_MEDIATION_RULE_VERSION,
                ),
                self.phase,
            )

    def _release_relief(self, ctx: TickContext, house: LocalEliteAgent) -> None:
        """Release grain to the households that are measurably short of food."""
        eligible = [
            cohort
            for cohort in self._local_cohorts(house.node_id)
            if self._population.unmet_ratio(cohort.cohort_id)
            >= self._parameters.relief_eligibility_unmet_ratio
        ]
        if not eligible:
            return
        keep = self._parameters.relief_carry_over_ratio_of_local_need * self._local_monthly_need(
            house.node_id
        )
        available = max(0.0, house.grain_shi - keep)
        release = min(available, house.grain_shi * self._parameters.relief_share_of_grain_stock)
        if release <= 0.0:
            return
        weights = [
            cohort.households * self._population.unmet_ratio(cohort.cohort_id)
            for cohort in eligible
        ]
        total = sum(weights)
        if total <= 0.0:
            return
        for cohort, weight in zip(eligible, weights, strict=True):
            share = release * weight / total
            if share <= 0.0:
                continue
            emit_elite_event(
                ctx,
                house,
                house.release_relief(
                    grain_shi=share,
                    recipient_id=cohort.cohort_id,
                    rule_version=RELIEF_RULE_VERSION,
                ),
                self.phase,
            )
            emit_cohort_event(
                ctx,
                cohort,
                cohort.record_relief(
                    grain_shi=share,
                    donor_id=house.elite_id,
                    rule_version=RELIEF_RULE_VERSION,
                ),
                self.phase,
            )

    def _record_state(self, ctx: TickContext, house: LocalEliteAgent) -> None:
        ctx.emit(
            ELITE_STATE_EVENT,
            phase=self.phase.token,
            agent_id=house.elite_id,
            region=house.node_id,
            rule_version=ELITE_STATE_RULE_VERSION,
            trigger=house.snapshot(
                claims_tael=self.claims_tael(house.node_id),
                price_tael_per_shi=self._book.price(house.node_id),
                rule_version=ELITE_STATE_RULE_VERSION,
            ).trigger,
            outcome="elite-state",
        )

    # ------------------------------------------------------------------ helpers

    def claims_tael(self, node_id: str) -> float:
        return sum(cohort.debt_tael for cohort in self._population if cohort.node_id == node_id)

    def _local_cohorts(self, node_id: str) -> tuple[HouseholdCohortAgent, ...]:
        return tuple(cohort for cohort in self._population if cohort.node_id == node_id)

    def _local_monthly_need(self, node_id: str) -> float:
        return sum(
            self._household_parameters.subsistence_grain_per_adult_month_shi * cohort.adults
            for cohort in self._local_cohorts(node_id)
        )


def _cohort_identity(actor: NodeBound) -> str:
    cohort_id = getattr(actor, "cohort_id", None)
    return cohort_id if isinstance(cohort_id, str) else type(actor).__name__
