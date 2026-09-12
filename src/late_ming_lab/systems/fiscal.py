"""Fiscal extraction and official relief: phases 07 and 08 of a tick.

Taxation is decomposed exactly as the plan's M3 requires — a nominal quota, the collection
effort spent against it, what that effort cost, what was actually received, and what remains in
arrears — and every one of those is a separate logged quantity.

Collection follows a declared order, and each step is the same machinery the household already
uses for food, so nothing new is invented for the tax collector:

```text
1 elite tax mediation: the local elite may advance part of the obligation
2 silver on hand
3 forced grain sale to the local market, down to a subsistence reserve
4 movable assets
5 land, bought by the local elite
6 borrowing against remaining collateral
7 whatever is left becomes arrears owed to the county
```

The county's arrears stock is the sum of its households' arrears, so the two sides cannot drift,
and the same double-entry discipline applies as everywhere else: a payment leaves the household
and arrives at the treasury in the same tick, with both events naming the other side.

Official relief is separate from private relief and is funded from the treasury: the county buys
grain into its granary at the posted market price and releases it to households whose measured
distress crosses a threshold, subject to its own ReliefCapacity, and pays the logistics of doing
so. The fiscal cost of relief — grain value plus logistics — is recorded.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from late_ming_lab.actors.elites import (
    EliteLayer,
    LocalEliteAgent,
    NoTaxMediation,
    TaxMediationPolicy,
)
from late_ming_lab.actors.exchange import CreditSource
from late_ming_lab.actors.government import (
    FISCAL_RULE_VERSION,
    RELIEF_RULE_VERSION,
    CountyGovernment,
    GovernmentEvent,
    GovernmentLayer,
)
from late_ming_lab.actors.households import (
    HouseholdCohortAgent,
    HouseholdPopulation,
    emit_cohort_event,
)
from late_ming_lab.actors.merchants import MerchantLayer
from late_ming_lab.core.tick import (
    RESOURCE_COHORT_ASSETS,
    RESOURCE_COHORT_DEBT,
    RESOURCE_COHORT_GRAIN,
    RESOURCE_COHORT_LAND,
    RESOURCE_COHORT_SILVER,
    RESOURCE_COHORT_TAX_ARREARS,
    RESOURCE_COUNTY_ARREARS,
    RESOURCE_COUNTY_GRANARY,
    RESOURCE_COUNTY_TREASURY,
    RESOURCE_DISTRESS_WINDOW,
    RESOURCE_ELITE_LAND,
    RESOURCE_ELITE_SILVER,
    RESOURCE_MARKET_PRICE,
    RESOURCE_MERCHANT_STOCK,
    TickContext,
    TickPhase,
)
from late_ming_lab.evidence.parameters import (
    EliteParameters,
    FiscalParameters,
    HouseholdParameters,
)
from late_ming_lab.policies.fiscal import ExtractionPolicy, FixedExtraction
from late_ming_lab.systems.markets import LocalGrainMarket, MarketBook, emit_merchant_event

TAX_RULE_VERSION: Final[str] = "tax-collection-v1"
EXTRACTION_RULE_VERSION: Final[str] = "extraction-policy-v1"


class TaxCollectionSystem:
    """Tick phase 07: assess the quota, spend the effort, take what can be taken."""

    name: str = "tax-collection"
    phase: TickPhase = TickPhase.TAXATION
    reads: frozenset[str] = frozenset(
        {
            RESOURCE_COHORT_ASSETS,
            RESOURCE_COHORT_DEBT,
            RESOURCE_COHORT_GRAIN,
            RESOURCE_COHORT_LAND,
            RESOURCE_COHORT_SILVER,
            RESOURCE_COHORT_TAX_ARREARS,
            RESOURCE_COUNTY_TREASURY,
            RESOURCE_ELITE_LAND,
            RESOURCE_ELITE_SILVER,
            RESOURCE_MARKET_PRICE,
        }
    )
    writes: frozenset[str] = frozenset(
        {
            RESOURCE_COHORT_ASSETS,
            RESOURCE_COHORT_DEBT,
            RESOURCE_COHORT_GRAIN,
            RESOURCE_COHORT_LAND,
            RESOURCE_COHORT_SILVER,
            RESOURCE_COHORT_TAX_ARREARS,
            RESOURCE_COUNTY_ARREARS,
            RESOURCE_COUNTY_TREASURY,
            RESOURCE_ELITE_LAND,
            RESOURCE_ELITE_SILVER,
            RESOURCE_MERCHANT_STOCK,
        }
    )

    def __init__(
        self,
        *,
        governments: GovernmentLayer,
        population: HouseholdPopulation,
        elites: EliteLayer,
        merchants: MerchantLayer,
        book: MarketBook,
        fiscal_parameters: FiscalParameters,
        household_parameters: HouseholdParameters,
        elite_parameters: EliteParameters,
        credit: CreditSource | None = None,
        policy: ExtractionPolicy | None = None,
        tax_mediation: TaxMediationPolicy | None = None,
        nominal_pressure: float = 0.02,
    ) -> None:
        self._governments = governments
        self._population = population
        self._elites = elites
        self._merchants = merchants
        self._book = book
        self._parameters = fiscal_parameters
        self._household_parameters = household_parameters
        self._elite_parameters = elite_parameters
        self._credit = credit
        self._policy = policy or FixedExtraction(effort=0.5)
        self._tax_mediation = tax_mediation or NoTaxMediation()
        self._nominal_pressure = nominal_pressure
        self._markets: Mapping[str, LocalGrainMarket] = {
            node_id: LocalGrainMarket(node_id=node_id, book=book, merchants=merchants)
            for node_id in sorted({county.node_id for county in governments})
        }

    @property
    def policy(self) -> ExtractionPolicy:
        return self._policy

    @property
    def nominal_pressure(self) -> float:
        return self._nominal_pressure

    def step(self, ctx: TickContext) -> None:
        for county in self._governments:
            county.begin_tick()
            cohorts = self._local_cohorts(county.node_id)
            if not cohorts:
                continue
            self._assess_and_collect(ctx, county, cohorts)
        self._governments.check_invariants()

    # ------------------------------------------------------------------ one county

    def _assess_and_collect(
        self,
        ctx: TickContext,
        county: CountyGovernment,
        cohorts: tuple[HouseholdCohortAgent, ...],
    ) -> None:
        elite = self._elites.require(county.node_id)
        taxable_land = sum(cohort.land_mu for cohort in cohorts)
        hidden_share = self._parameters.hidden_land_share(
            information_capacity=county.capacity.information
        )
        hidden_land = elite.land_mu * hidden_share

        prior_arrears = sum(cohort.tax_arrears_tael for cohort in cohorts)
        rate = self._policy.assessment_rate(
            nominal_pressure=self._nominal_pressure,
            arrears_tael=prior_arrears,
            quota_tael=prior_arrears,
        )
        quota = rate * taxable_land * self._parameters.assessed_value_tael_per_mu
        emit_government_event(
            ctx,
            county,
            county.record_assessment(
                quota_tael=quota,
                taxable_land_mu=taxable_land,
                hidden_land_mu=hidden_land,
                assessment_rate=rate,
            ),
            self.phase,
        )

        effort = self._policy.collection_effort(
            nominal_pressure=self._nominal_pressure,
            arrears_tael=prior_arrears,
            quota_tael=max(quota, 1e-9),
            coercion_capacity=county.capacity.coercion,
        )
        reach = min(1.0, county.capacity.tax_collection + county.capacity.coercion * effort)
        reachable = quota * effort * reach
        emit_government_event(
            ctx,
            county,
            county.record_extraction_decision(
                pressure=self._nominal_pressure,
                effort=effort,
                arrears_tael_before=prior_arrears,
                quota_tael=quota,
                reachable_tael=reachable,
                rule_version=EXTRACTION_RULE_VERSION,
            ),
            self.phase,
        )

        receipts = 0.0
        if quota > 0.0 and taxable_land > 0.0:
            for cohort in cohorts:
                share = cohort.land_mu / taxable_land
                target = reachable * share
                receipts += self._collect_from(ctx, county, elite, cohort, target)

        cost_due = self._parameters.collection_cost_tael(
            effort=effort, quota_tael=quota, logistics_capacity=county.capacity.logistics
        )
        emit_government_event(
            ctx,
            county,
            county.pay_collection_cost(silver_tael=cost_due),
            self.phase,
        )

    def _collect_from(
        self,
        ctx: TickContext,
        county: CountyGovernment,
        elite: LocalEliteAgent,
        cohort: HouseholdCohortAgent,
        target: float,
    ) -> float:
        """Collect one household's target, down the declared order; returns what the county got."""
        if target <= 0.0:
            return 0.0
        collected = 0.0
        outstanding = target

        advanced = min(
            self._tax_mediation.advance_tael(
                parameters=self._elite_parameters,
                client_land_mu=cohort.land_mu,
                demand_tael=outstanding,
            ),
            elite.silver_tael,
        )
        if advanced > 0.0:
            emit_elite_mediation(ctx, elite, cohort, advanced, self.phase)
            emit_government_event(
                ctx,
                county,
                county.receive_tax(
                    silver_tael=advanced, payer_id=elite.elite_id, channel="mediator"
                ),
                self.phase,
            )
            collected += advanced
            outstanding -= advanced

        if outstanding > 0.0:
            payment = min(outstanding, cohort.silver_tael)
            if payment > 0.0:
                emit_cohort_event(
                    ctx,
                    cohort,
                    cohort.record_tax_payment(
                        silver_tael=payment,
                        assessed_tael=target,
                        county_id=county.government_id,
                        channel="silver",
                        rule_version=TAX_RULE_VERSION,
                    ),
                    self.phase,
                )
                emit_government_event(
                    ctx,
                    county,
                    county.receive_tax(
                        silver_tael=payment, payer_id=cohort.cohort_id, channel="household"
                    ),
                    self.phase,
                )
                collected += payment
                outstanding -= payment

        outstanding = self._sell_grain_for_tax(ctx, county, cohort, outstanding)
        outstanding = self._sell_movables_for_tax(ctx, county, cohort, outstanding)
        outstanding = self._sell_land_for_tax(ctx, county, cohort, outstanding)
        outstanding = self._borrow_for_tax(ctx, county, elite, cohort, outstanding)

        if outstanding > 1e-9:
            emit_cohort_event(
                ctx,
                cohort,
                cohort.record_tax_arrears(
                    delta_tael=outstanding,
                    county_id=county.government_id,
                    rule_version=TAX_RULE_VERSION,
                ),
                self.phase,
            )
            emit_government_event(
                ctx,
                county,
                county.record_arrears(delta_tael=outstanding),
                self.phase,
            )
        return collected

    # ------------------------------------------------------------------ liquidation path

    def _price(self, node_id: str) -> float:
        return self._book.price(node_id)

    def _sell_grain_for_tax(
        self,
        ctx: TickContext,
        county: CountyGovernment,
        cohort: HouseholdCohortAgent,
        outstanding: float,
    ) -> float:
        keep = (
            self._household_parameters.tax_grain_sale_floor_ratio_of_annual_need
            * self._household_parameters.annual_need_shi(cohort.adults)
        )
        sellable = max(0.0, cohort.grain_shi - keep)
        if sellable <= 0.0:
            return outstanding
        price = self._price(cohort.node_id)
        wanted = min(sellable, outstanding / price)
        house = self._merchants.require(cohort.node_id)
        shi = min(wanted, house.silver_tael / price)
        if shi <= 0.0:
            return outstanding
        emit_merchant_event(
            ctx,
            house,
            house.buy_from_household(
                shi=shi,
                price_tael_per_shi=price,
                seller_id=cohort.cohort_id,
                rule_version=TAX_RULE_VERSION,
            ),
            self.phase,
        )
        event = cohort.record_market_sale(
            shi=shi,
            price_tael_per_shi=price,
            buyer_id=house.merchant_id,
            rule_version=TAX_RULE_VERSION,
            reason="tax",
        )
        emit_cohort_event(ctx, cohort, event, self.phase)
        proceeds = event.trigger["proceeds_tael"]
        return self._pay_from_proceeds(ctx, county, cohort, outstanding, proceeds)

    def _sell_movables_for_tax(
        self,
        ctx: TickContext,
        county: CountyGovernment,
        cohort: HouseholdCohortAgent,
        outstanding: float,
    ) -> float:
        if cohort.movable_assets_tael <= 0.0:
            return outstanding
        market = self._markets[cohort.node_id]
        outcome = market.buy_movables(
            ctx,
            cohort,
            wanted_tael=outstanding,
            max_tael=cohort.movable_assets_tael,
            phase=self.phase,
        )
        if outcome.quantity <= 0.0:
            return outstanding
        emit_cohort_event(
            ctx,
            cohort,
            cohort.record_movable_asset_sale(
                proceeds_tael=outcome.quantity, rule_version=TAX_RULE_VERSION, reason="tax"
            ),
            self.phase,
        )
        return self._pay_from_proceeds(ctx, county, cohort, outstanding, outcome.quantity)

    def _sell_land_for_tax(
        self,
        ctx: TickContext,
        county: CountyGovernment,
        cohort: HouseholdCohortAgent,
        outstanding: float,
    ) -> float:
        if self._credit is None or cohort.land_mu <= 0.0:
            return outstanding
        outcome = self._credit.sell_land(
            ctx, cohort, wanted_tael=outstanding, max_mu=cohort.land_mu
        )
        if outcome.quantity <= 0.0:
            return outstanding
        emit_cohort_event(
            ctx,
            cohort,
            cohort.record_land_sale(
                mu=outcome.quantity,
                price_tael_per_mu=self._credit.land_price_tael_per_mu,
                rule_version=TAX_RULE_VERSION,
                reason="tax",
            ),
            self.phase,
        )
        return self._pay_from_proceeds(ctx, county, cohort, outstanding, outcome.value_tael)

    def _borrow_for_tax(
        self,
        ctx: TickContext,
        county: CountyGovernment,
        elite: LocalEliteAgent,
        cohort: HouseholdCohortAgent,
        outstanding: float,
    ) -> float:
        if self._credit is None:
            return outstanding
        decision = self._credit.borrow(
            ctx,
            cohort,
            requested_tael=outstanding,
            collateral_tael=cohort.collateral_value_tael,
            existing_debt_tael=cohort.debt_tael,
        )
        if decision.granted_tael <= 0.0:
            return outstanding
        emit_cohort_event(
            ctx,
            cohort,
            cohort.record_borrowing_request(
                requested_tael=outstanding,
                granted_tael=decision.granted_tael,
                capacity_tael=decision.capacity_tael,
                lender_id=decision.lender_id,
                rule_version=TAX_RULE_VERSION,
                reason="tax",
            ),
            self.phase,
        )
        return self._pay_from_proceeds(ctx, county, cohort, outstanding, decision.granted_tael)

    def _pay_from_proceeds(
        self,
        ctx: TickContext,
        county: CountyGovernment,
        cohort: HouseholdCohortAgent,
        outstanding: float,
        proceeds: float,
    ) -> float:
        """Turn realised proceeds into a tax payment and return what is still owed."""
        if proceeds <= 0.0 or outstanding <= 0.0:
            return outstanding
        payment = min(outstanding, cohort.silver_tael)
        if payment <= 0.0:
            return outstanding
        emit_cohort_event(
            ctx,
            cohort,
            cohort.record_tax_payment(
                silver_tael=payment,
                assessed_tael=payment,
                county_id=county.government_id,
                channel="liquidation",
                rule_version=TAX_RULE_VERSION,
            ),
            self.phase,
        )
        emit_government_event(
            ctx,
            county,
            county.receive_tax(
                silver_tael=payment, payer_id=cohort.cohort_id, channel="liquidation"
            ),
            self.phase,
        )
        return max(0.0, outstanding - payment)

    def _local_cohorts(self, node_id: str) -> tuple[HouseholdCohortAgent, ...]:
        return tuple(cohort for cohort in self._population if cohort.node_id == node_id)


class OfficialReliefSystem:
    """Tick phase 08: fill the granary from the treasury, then release to the distressed."""

    name: str = "official-relief"
    phase: TickPhase = TickPhase.RELIEF
    reads: frozenset[str] = frozenset(
        {
            RESOURCE_COUNTY_GRANARY,
            RESOURCE_COUNTY_TREASURY,
            RESOURCE_DISTRESS_WINDOW,
            RESOURCE_MARKET_PRICE,
            RESOURCE_MERCHANT_STOCK,
        }
    )
    writes: frozenset[str] = frozenset(
        {
            RESOURCE_COHORT_GRAIN,
            RESOURCE_COUNTY_GRANARY,
            RESOURCE_COUNTY_TREASURY,
            RESOURCE_MERCHANT_STOCK,
        }
    )

    def __init__(
        self,
        *,
        governments: GovernmentLayer,
        population: HouseholdPopulation,
        merchants: MerchantLayer,
        book: MarketBook,
        fiscal_parameters: FiscalParameters,
        household_parameters: HouseholdParameters,
    ) -> None:
        self._governments = governments
        self._population = population
        self._merchants = merchants
        self._book = book
        self._parameters = fiscal_parameters
        self._household_parameters = household_parameters
        self._markets: Mapping[str, LocalGrainMarket] = {
            node_id: LocalGrainMarket(node_id=node_id, book=book, merchants=merchants)
            for node_id in sorted({county.node_id for county in governments})
        }

    def step(self, ctx: TickContext) -> None:
        for county in self._governments:
            cohorts = self._local_cohorts(county.node_id)
            if not cohorts:
                continue
            self._fill_granary(ctx, county)
            released = self._release(ctx, county, cohorts)
            if released > 0.0:
                cost = self._parameters.relief_cost_tael(
                    released_shi=released, logistics_capacity=county.capacity.logistics
                )
                emit_government_event(
                    ctx, county, county.pay_relief_cost(silver_tael=cost), self.phase
                )
        self._governments.check_invariants()

    def _fill_granary(self, ctx: TickContext, county: CountyGovernment) -> None:
        need = self._monthly_local_need(county.node_id)
        target = need * self._parameters.granary_target_cover_months
        shortfall = max(0.0, target - county.grain_shi)
        if shortfall <= 0.0 or county.silver_tael <= 0.0:
            return
        budget = county.silver_tael * self._parameters.granary_purchase_share_of_silver
        price = self._book.price(county.node_id)
        market = self._markets[county.node_id]
        shoppable = min(shortfall, budget / price)
        if shoppable <= 0.0:
            return
        outcome = market.buy_grain(
            ctx, county, shi_wanted=shoppable, max_silver=budget, phase=self.phase
        )
        if outcome.quantity <= 0.0:
            return
        emit_government_event(
            ctx,
            county,
            county.buy_grain(grain_shi=outcome.quantity, price_tael_per_shi=price),
            self.phase,
        )

    def _release(
        self,
        ctx: TickContext,
        county: CountyGovernment,
        cohorts: tuple[HouseholdCohortAgent, ...],
    ) -> float:
        eligible = [
            cohort
            for cohort in cohorts
            if self._population.unmet_ratio(cohort.cohort_id)
            >= self._parameters.relief_eligibility_unmet_ratio
        ]
        if not eligible or county.grain_shi <= 0.0:
            return 0.0
        need = self._monthly_local_need(county.node_id)
        deliverable = min(
            county.grain_shi,
            need * self._parameters.relief_share_of_need * county.capacity.relief,
        )
        if deliverable <= 0.0:
            return 0.0
        weights = [
            cohort.households * self._population.unmet_ratio(cohort.cohort_id)
            for cohort in eligible
        ]
        total = sum(weights)
        if total <= 0.0:
            return 0.0
        released = 0.0
        for cohort, weight in zip(eligible, weights, strict=True):
            share = deliverable * weight / total
            if share <= 0.0:
                continue
            event = county.release_relief(grain_shi=share, recipient_id=cohort.cohort_id)
            emit_government_event(ctx, county, event, self.phase)
            granted = event.trigger["released_shi"]
            released += granted
            if granted <= 0.0:
                continue
            emit_cohort_event(
                ctx,
                cohort,
                cohort.record_relief(
                    grain_shi=granted,
                    donor_id=county.government_id,
                    rule_version=RELIEF_RULE_VERSION,
                    source="official",
                ),
                self.phase,
            )
        return released

    def _local_cohorts(self, node_id: str) -> tuple[HouseholdCohortAgent, ...]:
        return tuple(cohort for cohort in self._population if cohort.node_id == node_id)

    def _monthly_local_need(self, node_id: str) -> float:
        return sum(
            self._household_parameters.subsistence_grain_per_adult_month_shi * cohort.adults
            for cohort in self._local_cohorts(node_id)
        )


def emit_elite_mediation(
    ctx: TickContext,
    elite: LocalEliteAgent,
    cohort: HouseholdCohortAgent,
    advanced: float,
    phase: TickPhase,
) -> None:
    """Log the elite's side of an advance made on a household's behalf."""
    event = elite.record_tax_mediation(
        advanced_tael=advanced,
        client_id=cohort.cohort_id,
        demand_tael=advanced,
        rule_version=FISCAL_RULE_VERSION,
    )
    ctx.emit(
        event.event_type,
        phase=phase.token,
        agent_id=elite.elite_id,
        region=elite.node_id,
        rule_version=event.rule_version,
        trigger=event.trigger,
        outcome=event.outcome,
    )
    emit_cohort_event(
        ctx,
        cohort,
        cohort.record_tax_mediation(
            advanced_tael=advanced,
            mediator_id=elite.elite_id,
            rule_version=FISCAL_RULE_VERSION,
        ),
        phase,
    )


class CountyBookkeepingSystem:
    """Tick phase 16: the county's monthly state record and its ledger check.

    The record is a roll-up of the events already emitted this tick — quota, effort, receipts,
    collection cost, arrears, relief, tax base — so a reader of the artifacts gets one row per
    county per month without having to aggregate the log by hand.
    """

    name: str = "county-bookkeeping"
    phase: TickPhase = TickPhase.BOOKKEEPING
    reads: frozenset[str] = frozenset(
        {
            RESOURCE_COHORT_TAX_ARREARS,
            RESOURCE_COUNTY_ARREARS,
            RESOURCE_COUNTY_GRANARY,
            RESOURCE_COUNTY_TREASURY,
        }
    )
    writes: frozenset[str] = frozenset()

    def __init__(self, *, governments: GovernmentLayer, population: HouseholdPopulation) -> None:
        self._governments = governments
        self._population = population

    def step(self, ctx: TickContext) -> None:
        for county in self._governments:
            arrears = sum(
                cohort.tax_arrears_tael
                for cohort in self._population
                if cohort.node_id == county.node_id
            )
            emit_government_event(ctx, county, county.snapshot(arrears_tael=arrears), self.phase)
        self._governments.check_invariants()


def emit_government_event(
    ctx: TickContext, county: CountyGovernment, event: GovernmentEvent, phase: TickPhase
) -> None:
    """Write one government transition into the run's event log."""
    ctx.emit(
        event.event_type.value,
        phase=phase.token,
        agent_id=county.government_id,
        region=county.node_id,
        rule_version=event.rule_version,
        trigger=event.trigger,
        outcome=event.outcome,
    )
