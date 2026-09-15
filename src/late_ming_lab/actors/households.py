"""Weighted household cohorts and their balance sheets.

A cohort represents ``households`` households with the same endowment and the same
environment; it never represents a named family and never invents household-level detail. All
quantities are cohort totals in the units declared in :mod:`late_ming_lab.evidence.parameters`
(grain in ``shi``, silver in ``tael``, land in ``mu``).

The two accounting rules it obeys come from
:class:`~late_ming_lab.actors.ledger.LedgerAgent`: no balance may go negative, and no balance may
move without a recorded, logged explanation.

Where a household needs a counterparty — grain to buy, silver to borrow, a buyer for its land —
it asks for one through :mod:`late_ming_lab.actors.exchange`. It does not know whether the
merchant layer or the elite layer answers, and it cannot conjure grain or silver on its own.

The coping ladder lives in :meth:`HouseholdCohortAgent.monthly_budget` because it is the
household's own behaviour. What it does *not* contain is any anger, grievance or rebellion
scalar: distress is a physical ledger quantity — subsistence need that went unmet — and
nothing else.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from types import MappingProxyType

from pydantic import Field, PrivateAttr

from late_ming_lab.actors.exchange import CreditSource, GrainMarket
from late_ming_lab.actors.ledger import (
    ADULTS_DELTA,
    ASSETS_DELTA,
    DEBT_DELTA,
    GRAIN_DELTA,
    HOUSEHOLDS_DELTA,
    LAND_DELTA,
    SILVER_DELTA,
    TAX_ARREARS_DELTA,
    LedgerAgent,
    LedgerError,
)
from late_ming_lab.core.events import Event
from late_ming_lab.core.tick import TickContext, TickPhase
from late_ming_lab.evidence.parameters import HouseholdParameters
from late_ming_lab.networks.nodes import AgrarianZone

#: P02/P03 named the domain error this way; the shared ledger raises :class:`LedgerError`.
HouseholdLedgerError = LedgerError

#: Names re-exported for the ledger contract this actor satisfies.
__all__ = [
    "ADULTS_DELTA",
    "ASSETS_DELTA",
    "DEBT_DELTA",
    "GRAIN_DELTA",
    "HOUSEHOLDS_DELTA",
    "LAND_DELTA",
    "SILVER_DELTA",
    "TAX_ARREARS_DELTA",
    "CohortClass",
    "CohortEvent",
    "CohortEventType",
    "CopingStage",
    "HouseholdCohortAgent",
    "HouseholdLedgerError",
    "HouseholdPopulation",
    "emit_cohort_event",
]

COHORT_ID_PATTERN = r"^[a-z0-9][a-z0-9._:-]*$"
DISTRESS_WINDOW_MONTHS = 12

HOUSEHOLD_RULE_VERSION = "household-survival-v1"
HARVEST_RULE_VERSION = "harvest-v1"
DEBT_RULE_VERSION = "debt-service-v1"
ELIGIBILITY_RULE_VERSION = "eligibility-v1"
BOOKKEEPING_RULE_VERSION = "cohort-bookkeeping-v1"


class CohortClass(StrEnum):
    """Endowment archetypes; a cohort is a set of households, not an individual."""

    LANDLESS_LABOURER = "landless-labourer"
    TENANT_HOUSEHOLD = "tenant-household"
    POOR_SMALLHOLDER = "poor-smallholder"
    MIDDLE_SMALLHOLDER = "middle-smallholder"
    WEALTHY_FARMER = "wealthy-farmer"


class CopingStage(IntEnum):
    """The coping ladder, in order. Higher means further down the ladder."""

    SELF_SUFFICIENT = 0
    REDUCING_CONSUMPTION = 1
    BORROWING = 2
    SELLING_ASSETS = 3
    SELLING_LAND = 4
    DESTITUTE = 5

    @property
    def token(self) -> str:
        return self.name.lower()


class CohortEventType(StrEnum):
    """Every transition a cohort can record."""

    LABOUR_INCOME = "LABOUR_INCOME"
    CONSUMPTION = "CONSUMPTION"
    BORROWING_REQUEST = "BORROWING_REQUEST"
    GRAIN_PURCHASE = "GRAIN_PURCHASE"
    MOVABLE_ASSET_SALE = "MOVABLE_ASSET_SALE"
    GRAIN_SEIZURE = "GRAIN_SEIZED"
    ASSET_SEIZURE = "MOVABLE_ASSET_SEIZED"
    MIGRATION_DEPARTURE = "MIGRATION_DEPARTURE"
    MIGRATION_ARRIVAL = "MIGRATION_ARRIVAL"
    MIGRANT_SUBSISTENCE = "MIGRANT_SUBSISTENCE"
    LAND_SALE = "LAND_SALE"
    FORECLOSURE = "FORECLOSURE"
    COPING_TRANSITION = "COPING_TRANSITION"
    TAX_PAYMENT = "TAX_PAYMENT"
    TAX_ARREARS = "TAX_ARREARS_ASSESSED"
    RECRUITMENT_LEVY = "RECRUITMENT_LEVY"
    DESERTER_RETURN = "DESERTER_RETURN"
    MARKET_SALE = "MARKET_SALE"
    RELIEF_RECEIVED = "RELIEF_RECEIVED"
    TAX_MEDIATION = "TAX_MEDIATION"
    HARVEST = "HARVEST"
    RENT_PAYMENT = "RENT_PAYMENT"
    DEBT_INTEREST = "DEBT_INTEREST"
    DEBT_REPAYMENT = "DEBT_REPAYMENT"
    ELIGIBILITY = "ELIGIBILITY"
    COHORT_STATE = "COHORT_STATE"


@dataclass(frozen=True, slots=True)
class CohortEvent:
    """One recorded transition of a cohort, ready to be emitted by the system."""

    event_type: CohortEventType
    rule_version: str
    trigger: dict[str, float]
    outcome: str


def emit_cohort_event(
    ctx: TickContext, cohort: HouseholdCohortAgent, event: CohortEvent, phase: TickPhase
) -> Event:
    """Write one cohort transition into the run's event log."""
    return ctx.emit(
        event.event_type.value,
        phase=phase.token,
        agent_id=cohort.cohort_id,
        region=cohort.node_id,
        rule_version=event.rule_version,
        trigger=event.trigger,
        outcome=event.outcome,
    )


class HouseholdCohortAgent(LedgerAgent):
    """One weighted cohort of households with its balance sheet and coping state."""

    cohort_id: str = Field(pattern=COHORT_ID_PATTERN, max_length=128)
    node_id: str = Field(pattern=COHORT_ID_PATTERN, max_length=64)
    cohort_class: CohortClass
    zone: AgrarianZone

    households: float = Field(gt=0)
    adults: float = Field(
        gt=0, description="adult labour units; recruits leave this balance and returners rejoin it"
    )
    land_mu: float = Field(ge=0)
    grain_shi: float = Field(ge=0)
    silver_tael: float = Field(ge=0)
    debt_tael: float = Field(ge=0)
    tax_arrears_tael: float = Field(
        default=0.0, ge=0, description="obligation owed to the county, not to a lender"
    )
    movable_assets_tael: float = Field(ge=0)

    season_impact: float = Field(default=0.0, ge=0)
    coping_stage: CopingStage = CopingStage.SELF_SUFFICIENT
    temporary_migration_eligible: bool = False
    permanent_migration_eligible: bool = False
    recruitment_eligible: bool = False

    _land_reference_value: float = PrivateAttr(default=0.0)

    def model_post_init(self, _context: object) -> None:
        super().model_post_init(_context)

    @property
    def ledger_name(self) -> str:
        return self.cohort_id

    # ------------------------------------------------------------------ derived quantities

    @property
    def land_per_household_mu(self) -> float:
        return self.land_mu / self.households

    @property
    def grain_per_household_shi(self) -> float:
        return self.grain_shi / self.households

    @property
    def debt_per_household_tael(self) -> float:
        return self.debt_tael / self.households

    @property
    def collateral_value_tael(self) -> float:
        """Reference value of what the cohort can pledge; not a market price."""
        return self.movable_assets_tael + self.land_mu * self._land_reference_value

    def check_balances(self) -> None:
        """Reconcile every balance, weight included.

        Until P07 a cohort's weight could not change at all, and the check was an equality against
        the opening value. Households migrate now, so weight is a tracked balance like the rest:
        it is reconciled against the movements recorded for it, and nothing else can move it.
        """
        super().check_balances()

    def set_land_reference_value(self, value: float) -> None:
        """Collateral valuation used for credit capacity; declared by the run's parameters."""
        if value <= 0:
            raise ValueError("land reference value must be positive")
        self._land_reference_value = value

    # ------------------------------------------------------------------ transitions

    def accumulate_climate_impact(self, impact: float) -> None:
        """Add this month's exogenous impact to the running crop season.

        No event is emitted: the climate event that carried the impact is already in the log,
        and the harvest event reports the season it accumulated into.
        """
        if impact < 0:
            raise ValueError("climate impact cannot be negative")
        self.season_impact = self.season_impact + impact

    def receive_wage_grain(
        self,
        *,
        grain_shi: float,
        wage_shi_per_adult: float,
        labour_demand_factor: float,
        rule_version: str,
    ) -> CohortEvent:
        """In-kind agricultural wage, scaled by how much local labour was worth employing."""
        self._apply(grain=grain_shi, impacts=((GRAIN_DELTA, grain_shi),))
        return CohortEvent(
            event_type=CohortEventType.LABOUR_INCOME,
            rule_version=rule_version,
            trigger={
                "wage_grain_shi": grain_shi,
                "wage_shi_per_adult_month": wage_shi_per_adult,
                "labour_demand_factor": labour_demand_factor,
                "adults": self.adults,
                GRAIN_DELTA: grain_shi,
            },
            outcome="in-kind-wage-placeholder",
        )

    def eat_from_storage(self, need_shi: float) -> float:
        """Eat from stored grain; returns what was actually eaten."""
        eaten = min(self.grain_shi, max(0.0, need_shi))
        self._apply(grain=-eaten, impacts=((GRAIN_DELTA, -eaten),))
        return eaten

    def record_consumption(
        self,
        *,
        need_shi: float,
        floor_shi: float,
        eaten_shi: float,
        from_purchases_shi: float,
        purchased_shi: float,
        rule_version: str,
    ) -> CohortEvent:
        """Record the month's food intake against the subsistence floor.

        ``eaten_shi`` is everything the household actually ate, whatever its origin, and the
        ledger delta is exactly that amount: grain bought on the ladder is credited to the
        granary when it is bought and debited here when it is eaten, so no purchase can feed
        two months.
        """
        from_storage = max(0.0, eaten_shi - from_purchases_shi)
        return CohortEvent(
            event_type=CohortEventType.CONSUMPTION,
            rule_version=rule_version,
            trigger={
                "need_shi": need_shi,
                "floor_shi": floor_shi,
                "eaten_shi": eaten_shi,
                "from_storage_shi": from_storage,
                "from_purchases_shi": from_purchases_shi,
                "purchased_shi": purchased_shi,
                "reduced_shi": max(0.0, need_shi - eaten_shi),
                "unmet_shi": max(0.0, floor_shi - eaten_shi),
                GRAIN_DELTA: -eaten_shi,
            },
            outcome="met-floor" if eaten_shi >= floor_shi else "below-floor",
        )

    def record_borrowing_request(
        self,
        *,
        requested_tael: float,
        granted_tael: float,
        capacity_tael: float,
        lender_id: str,
        rule_version: str,
        reason: str = "consumption",
    ) -> CohortEvent:
        self._apply(
            silver=granted_tael,
            debt=granted_tael,
            impacts=((SILVER_DELTA, granted_tael), (DEBT_DELTA, granted_tael)),
        )
        return CohortEvent(
            event_type=CohortEventType.BORROWING_REQUEST,
            rule_version=rule_version,
            trigger={
                "requested_tael": requested_tael,
                "granted_tael": granted_tael,
                "capacity_tael": capacity_tael,
                "debt_tael": self.debt_tael,
                SILVER_DELTA: granted_tael,
                DEBT_DELTA: granted_tael,
                f"reason_is_{reason}": 1.0,
            },
            outcome=(f"granted-by:{lender_id}" if granted_tael > 0 else f"no-capacity:{lender_id}"),
        )

    def record_grain_purchase(
        self, *, shi: float, price_tael_per_shi: float, occasion: str, rule_version: str
    ) -> CohortEvent:
        """Buy grain with silver on hand.

        The cost is capped at the silver actually held, so floating-point rounding can never
        push a balance below zero; the event reports the amount that was really bought.
        """
        requested_cost = shi * price_tael_per_shi
        cost = min(requested_cost, self.silver_tael)
        if cost < requested_cost:
            shi = cost / price_tael_per_shi
        self._apply(
            grain=shi,
            silver=-cost,
            impacts=((GRAIN_DELTA, shi), (SILVER_DELTA, -cost)),
        )
        return CohortEvent(
            event_type=CohortEventType.GRAIN_PURCHASE,
            rule_version=rule_version,
            trigger={
                "purchased_shi": shi,
                "price_tael_per_shi": price_tael_per_shi,
                "cost_tael": cost,
                GRAIN_DELTA: shi,
                SILVER_DELTA: -cost,
            },
            outcome=occasion,
        )

    def record_grain_seizure(
        self,
        *,
        grain_shi: float,
        taker_id: str,
        rule_version: str,
        reason: str = "band",
    ) -> CohortEvent:
        """Lose grain to a raider: taken, not sold, so no silver comes back.

        The counterpart of a band's raid. A seizure is a transfer out of the household with no
        market transaction behind it, which is why it carries its own event type.
        """
        taken = min(grain_shi, self.grain_shi)
        if taken <= 0.0:
            raise ValueError("a grain seizure must take at least one shi")
        self._apply(grain=-taken, impacts=((GRAIN_DELTA, -taken),))
        return CohortEvent(
            event_type=CohortEventType.GRAIN_SEIZURE,
            rule_version=rule_version,
            trigger={
                "grain_seized_shi": taken,
                GRAIN_DELTA: -taken,
                "grain_shi": self.grain_shi,
                f"reason_is_{reason}": 1.0,
            },
            outcome=f"seized-by:{taker_id}",
        )

    def record_asset_seizure(
        self,
        *,
        assets_tael: float,
        taker_id: str,
        rule_version: str,
        reason: str = "band",
    ) -> CohortEvent:
        """Lose movable property to a raider; again, no matching inflow of silver."""
        taken = min(assets_tael, self.movable_assets_tael)
        if taken <= 0.0:
            raise ValueError("an asset seizure must take at least one tael of value")
        self._apply(assets=-taken, impacts=((ASSETS_DELTA, -taken),))
        return CohortEvent(
            event_type=CohortEventType.ASSET_SEIZURE,
            rule_version=rule_version,
            trigger={
                "assets_seized_tael": taken,
                ASSETS_DELTA: -taken,
                "movable_assets_tael": self.movable_assets_tael,
                f"reason_is_{reason}": 1.0,
            },
            outcome=f"seized-by:{taker_id}",
        )

    def record_movable_asset_sale(
        self, *, proceeds_tael: float, rule_version: str, reason: str = "food"
    ) -> CohortEvent:
        self._apply(
            assets=-proceeds_tael,
            silver=proceeds_tael,
            impacts=((ASSETS_DELTA, -proceeds_tael), (SILVER_DELTA, proceeds_tael)),
        )
        return CohortEvent(
            event_type=CohortEventType.MOVABLE_ASSET_SALE,
            rule_version=rule_version,
            trigger={
                "assets_sold_tael": proceeds_tael,
                "proceeds_tael": proceeds_tael,
                "assets_left_tael": self.movable_assets_tael,
                ASSETS_DELTA: -proceeds_tael,
                SILVER_DELTA: proceeds_tael,
                f"reason_is_{reason}": 1.0,
            },
            outcome=f"sold-for-{reason}",
        )

    def record_land_sale(
        self,
        *,
        mu: float,
        price_tael_per_mu: float,
        rule_version: str,
        reason: str = "food",
    ) -> CohortEvent:
        proceeds = mu * price_tael_per_mu
        self._apply(
            land=-mu,
            silver=proceeds,
            impacts=((LAND_DELTA, -mu), (SILVER_DELTA, proceeds)),
        )
        return CohortEvent(
            event_type=CohortEventType.LAND_SALE,
            rule_version=rule_version,
            trigger={
                "land_sold_mu": mu,
                "price_tael_per_mu": price_tael_per_mu,
                "proceeds_tael": proceeds,
                "land_left_mu": self.land_mu,
                LAND_DELTA: -mu,
                SILVER_DELTA: proceeds,
                f"reason_is_{reason}": 1.0,
            },
            outcome=f"distress-sale-for-{reason}",
        )

    def record_foreclosure(
        self,
        *,
        mu: float,
        pledge_mu: float,
        settled_tael: float,
        lender_id: str,
        rule_version: str,
    ) -> CohortEvent:
        """Lose pledged land to a lender who has called an unserviced loan.

        No silver arrives: the land is taken in satisfaction of the debt, so the obligation falls
        as the land leaves. Both movements are capped by what the cohort actually holds, so a
        foreclosure can never leave a negative balance, and the household keeps whatever it holds
        above the share of the pledge that was taken — the caller takes a declared share of the
        pledge, never the whole holding unless that share is 1.0. The pledge itself is forfeit
        whole: only the obligation is settled, and the value the land carries above it is the
        lender's, not a payment back to this household.
        """
        taken = min(mu, self.land_mu)
        settled = min(settled_tael, self.debt_tael)
        self._apply(
            land=-taken,
            debt=-settled,
            impacts=((LAND_DELTA, -taken), (DEBT_DELTA, -settled)),
        )
        return CohortEvent(
            event_type=CohortEventType.FORECLOSURE,
            rule_version=rule_version,
            trigger={
                "mu_transferred": taken,
                "pledge_mu": pledge_mu,
                "settled_tael": settled,
                "land_left_mu": self.land_mu,
                "debt_tael": self.debt_tael,
                LAND_DELTA: -taken,
                DEBT_DELTA: -settled,
            },
            outcome=f"foreclosed-by:{lender_id}",
        )

    def surplus_for_sale(self, *, parameters: HouseholdParameters) -> float:
        """Grain a household will sell: everything above the retention it keeps for itself."""
        keep = parameters.surplus_keep_ratio_of_annual_need * parameters.annual_need_shi(
            self.adults
        )
        return max(0.0, self.grain_shi - keep)

    def record_market_sale(
        self,
        *,
        shi: float,
        price_tael_per_shi: float,
        buyer_id: str,
        rule_version: str,
        reason: str = "surplus",
    ) -> CohortEvent:
        """Sell harvest surplus to the local market for silver."""
        proceeds = shi * price_tael_per_shi
        self._apply(
            grain=-shi,
            silver=proceeds,
            impacts=((GRAIN_DELTA, -shi), (SILVER_DELTA, proceeds)),
        )
        return CohortEvent(
            event_type=CohortEventType.MARKET_SALE,
            rule_version=rule_version,
            trigger={
                "sold_shi": shi,
                "price_tael_per_shi": price_tael_per_shi,
                "proceeds_tael": proceeds,
                GRAIN_DELTA: -shi,
                SILVER_DELTA: proceeds,
                f"reason_is_{reason}": 1.0,
            },
            outcome=f"sold-to:{buyer_id}",
        )

    def record_tax_payment(
        self,
        *,
        silver_tael: float,
        assessed_tael: float,
        county_id: str,
        channel: str,
        rule_version: str,
    ) -> CohortEvent:
        """Pay an assessed obligation in silver.

        The channel naming who the county received it from is part of the record: an advance by
        an elite is a different fiscal fact from a household paying out of its own purse.
        """
        paid = min(silver_tael, self.silver_tael)
        self._apply(silver=-paid, impacts=((SILVER_DELTA, -paid),))
        return CohortEvent(
            event_type=CohortEventType.TAX_PAYMENT,
            rule_version=rule_version,
            trigger={
                "assessed_tael": assessed_tael,
                "paid_tael": paid,
                SILVER_DELTA: -paid,
                "silver_tael": self.silver_tael,
            },
            outcome=f"paid-to:{county_id}:{channel}",
        )

    def record_tax_arrears(
        self, *, delta_tael: float, county_id: str, rule_version: str
    ) -> CohortEvent:
        """Carry an unpaid obligation; arrears are owed to the county, not to a lender."""
        self._apply(tax_arrears=delta_tael, impacts=((TAX_ARREARS_DELTA, delta_tael),))
        return CohortEvent(
            event_type=CohortEventType.TAX_ARREARS,
            rule_version=rule_version,
            trigger={
                "arrears_delta_tael": delta_tael,
                TAX_ARREARS_DELTA: delta_tael,
                "tax_arrears_tael": self.tax_arrears_tael,
            },
            outcome=f"owed-to:{county_id}",
        )

    def lose_adults(
        self, *, adults: float, destination: str, rule_version: str, reason: str
    ) -> CohortEvent:
        """Send adults away: to an army, to a band, or out of the modelled population."""
        sent = min(adults, self.adults)
        if sent <= 0.0:
            raise ValueError("a recruitment levy must send at least one adult")
        self._apply(adults=-sent, impacts=((ADULTS_DELTA, -sent),))
        return CohortEvent(
            event_type=CohortEventType.RECRUITMENT_LEVY,
            rule_version=rule_version,
            trigger={
                "adults_levied": sent,
                ADULTS_DELTA: -sent,
                "adults_left": self.adults,
                f"reason_is_{reason}": 1.0,
            },
            outcome=f"levied-to:{destination}",
        )

    def gain_adults(self, *, adults: float, source: str, rule_version: str) -> CohortEvent:
        """Take adults back in: a deserter coming home, or a band dissolving."""
        self._apply(adults=adults, impacts=((ADULTS_DELTA, adults),))
        return CohortEvent(
            event_type=CohortEventType.DESERTER_RETURN,
            rule_version=rule_version,
            trigger={
                "adults_returned": adults,
                ADULTS_DELTA: adults,
                "adults_left": self.adults,
            },
            outcome=f"returned-from:{source}",
        )

    def migrate_households_out(
        self,
        *,
        households: float,
        adults: float,
        grain_shi: float,
        silver_tael: float,
        movable_assets_tael: float,
        land_abandoned_mu: float,
        destination: str,
        rule_version: str,
    ) -> CohortEvent:
        """Send households away for good, with what they can carry.

        Movers take their people, food, silver and movable property with them. They cannot carry
        land, and the fields they were working are abandoned at the origin: the mu leave this
        cohort's books to nobody, which is a declared outflow, not a transfer.
        """
        self._apply(
            households=-households,
            adults=-adults,
            grain=-grain_shi,
            silver=-silver_tael,
            assets=-movable_assets_tael,
            land=-land_abandoned_mu,
            impacts=(
                (HOUSEHOLDS_DELTA, -households),
                (ADULTS_DELTA, -adults),
                (GRAIN_DELTA, -grain_shi),
                (SILVER_DELTA, -silver_tael),
                (ASSETS_DELTA, -movable_assets_tael),
                (LAND_DELTA, -land_abandoned_mu),
            ),
        )
        return CohortEvent(
            event_type=CohortEventType.MIGRATION_DEPARTURE,
            rule_version=rule_version,
            trigger={
                "households_migrated": households,
                "adults_migrated": adults,
                "grain_carried_shi": grain_shi,
                "silver_carried_tael": silver_tael,
                "assets_carried_tael": movable_assets_tael,
                "land_abandoned_mu": land_abandoned_mu,
                HOUSEHOLDS_DELTA: -households,
                ADULTS_DELTA: -adults,
                GRAIN_DELTA: -grain_shi,
                SILVER_DELTA: -silver_tael,
                ASSETS_DELTA: -movable_assets_tael,
                LAND_DELTA: -land_abandoned_mu,
                "households_left": self.households,
                "land_per_household_mu": self.land_per_household_mu,
            },
            outcome=f"migrated-to:{destination}",
        )

    def receive_migrant_households(
        self,
        *,
        households: float,
        adults: float,
        grain_shi: float,
        silver_tael: float,
        movable_assets_tael: float,
        source: str,
        rule_version: str,
    ) -> CohortEvent:
        """Take in households that arrived from another node, with what they carried.

        Arrivals bring no land: they are strangers in this catchment, which is what makes them
        cheap labour for whoever already holds fields here.
        """
        self._apply(
            households=households,
            adults=adults,
            grain=grain_shi,
            silver=silver_tael,
            assets=movable_assets_tael,
            impacts=(
                (HOUSEHOLDS_DELTA, households),
                (ADULTS_DELTA, adults),
                (GRAIN_DELTA, grain_shi),
                (SILVER_DELTA, silver_tael),
                (ASSETS_DELTA, movable_assets_tael),
            ),
        )
        return CohortEvent(
            event_type=CohortEventType.MIGRATION_ARRIVAL,
            rule_version=rule_version,
            trigger={
                "households_arrived": households,
                "adults_arrived": adults,
                "grain_carried_shi": grain_shi,
                "silver_carried_tael": silver_tael,
                "assets_carried_tael": movable_assets_tael,
                HOUSEHOLDS_DELTA: households,
                ADULTS_DELTA: adults,
                GRAIN_DELTA: grain_shi,
                SILVER_DELTA: silver_tael,
                ASSETS_DELTA: movable_assets_tael,
                "households_left": self.households,
                "land_per_household_mu": self.land_per_household_mu,
            },
            outcome=f"arrived-from:{source}",
        )

    def send_migrant_adults(
        self, *, adults: float, destination: str, rule_version: str
    ) -> CohortEvent:
        """Send adults away for a bounded term; they are still this cohort's people.

        The adults leave the cohort's balance for the migration system's holding account and come
        back when the term ends, so sending them away lowers this cohort's subsistence need
        without lowering its weight.
        """
        sent = min(adults, self.adults)
        if sent <= 0.0:
            raise ValueError("sending temporary migrants must send at least one adult")
        self._apply(adults=-sent, impacts=((ADULTS_DELTA, -sent),))
        return CohortEvent(
            event_type=CohortEventType.MIGRATION_DEPARTURE,
            rule_version=rule_version,
            trigger={
                "adults_migrated": sent,
                "temporary": 1.0,
                ADULTS_DELTA: -sent,
                "adults_left": self.adults,
            },
            outcome=f"temporary-to:{destination}",
        )

    def receive_migrant_adults(
        self, *, adults: float, source: str, rule_version: str
    ) -> CohortEvent:
        """Take seasonal migrants back, or bring them home early when their money runs out."""
        self._apply(adults=adults, impacts=((ADULTS_DELTA, adults),))
        return CohortEvent(
            event_type=CohortEventType.MIGRATION_ARRIVAL,
            rule_version=rule_version,
            trigger={
                "adults_returned": adults,
                "temporary": 1.0,
                ADULTS_DELTA: adults,
                "adults_left": self.adults,
            },
            outcome=f"returned-from:{source}",
        )

    def record_migrant_subsistence(
        self, *, silver_tael: float, destination: str, rule_version: str
    ) -> CohortEvent:
        """Pay for the food seasonal migrants eat while they are away.

        The silver leaves the cohort here; the grain is bought at the destination and eaten there,
        so this is the cohort's side of the trade and the destination market's sale is the other.
        """
        paid = min(silver_tael, self.silver_tael)
        if paid <= 0.0:
            raise ValueError("migrant subsistence must cost at least one tael")
        self._apply(silver=-paid, impacts=((SILVER_DELTA, -paid),))
        return CohortEvent(
            event_type=CohortEventType.MIGRANT_SUBSISTENCE,
            rule_version=rule_version,
            trigger={
                "migrant_subsistence_tael": paid,
                SILVER_DELTA: -paid,
                "silver_tael": self.silver_tael,
            },
            outcome=f"fed-migrants-at:{destination}",
        )

    def record_relief(
        self, *, grain_shi: float, donor_id: str, rule_version: str, source: str = "private"
    ) -> CohortEvent:
        """Grain received as relief; a transfer, not production.

        ``source`` distinguishes official relief from a private release, because the two are
        different fiscal facts even though the household experiences the same grain.
        """
        self._apply(grain=grain_shi, impacts=((GRAIN_DELTA, grain_shi),))
        return CohortEvent(
            event_type=CohortEventType.RELIEF_RECEIVED,
            rule_version=rule_version,
            trigger={
                "relief_shi": grain_shi,
                GRAIN_DELTA: grain_shi,
                "grain_shi": self.grain_shi,
                f"source_is_{source}": 1.0,
            },
            outcome=f"relieved-by:{donor_id}:{source}",
        )

    def record_tax_mediation(
        self, *, advanced_tael: float, mediator_id: str, rule_version: str
    ) -> CohortEvent:
        """Record an obligation advanced on this household's behalf as a claim on it."""
        self._apply(
            silver=advanced_tael,
            debt=advanced_tael,
            impacts=((SILVER_DELTA, advanced_tael), (DEBT_DELTA, advanced_tael)),
        )
        return CohortEvent(
            event_type=CohortEventType.TAX_MEDIATION,
            rule_version=rule_version,
            trigger={
                "advanced_tael": advanced_tael,
                "debt_tael": self.debt_tael,
                SILVER_DELTA: advanced_tael,
                DEBT_DELTA: advanced_tael,
            },
            outcome=f"advanced-by:{mediator_id}",
        )

    def record_harvest(
        self,
        *,
        grain_shi: float,
        cultivated_mu: float,
        yield_fraction: float,
        season_impact: float,
        rule_version: str,
    ) -> CohortEvent:
        self._apply(grain=grain_shi, impacts=((GRAIN_DELTA, grain_shi),))
        self.season_impact = 0.0
        return CohortEvent(
            event_type=CohortEventType.HARVEST,
            rule_version=rule_version,
            trigger={
                "harvested_shi": grain_shi,
                "cultivated_mu": cultivated_mu,
                "yield_fraction": yield_fraction,
                "season_impact": season_impact,
                GRAIN_DELTA: grain_shi,
            },
            outcome="harvest" if grain_shi > 0 else "crop-failure",
        )

    def record_rent_payment(
        self, *, grain_shi: float, share: float, landlord_id: str, rule_version: str
    ) -> CohortEvent:
        self._apply(grain=-grain_shi, impacts=((GRAIN_DELTA, -grain_shi),))
        return CohortEvent(
            event_type=CohortEventType.RENT_PAYMENT,
            rule_version=rule_version,
            trigger={
                "rent_shi": grain_shi,
                "rent_share_of_harvest": share,
                GRAIN_DELTA: -grain_shi,
            },
            outcome=f"paid-to:{landlord_id}",
        )

    def record_debt_interest(
        self, *, interest_tael: float, rate_monthly: float, rule_version: str
    ) -> CohortEvent:
        self._apply(debt=interest_tael, impacts=((DEBT_DELTA, interest_tael),))
        return CohortEvent(
            event_type=CohortEventType.DEBT_INTEREST,
            rule_version=rule_version,
            trigger={
                "interest_tael": interest_tael,
                "rate_monthly": rate_monthly,
                "debt_tael": self.debt_tael,
                DEBT_DELTA: interest_tael,
            },
            outcome="accrued",
        )

    def record_debt_repayment(self, *, repaid_tael: float, rule_version: str) -> CohortEvent:
        self._apply(
            silver=-repaid_tael,
            debt=-repaid_tael,
            impacts=((SILVER_DELTA, -repaid_tael), (DEBT_DELTA, -repaid_tael)),
        )
        return CohortEvent(
            event_type=CohortEventType.DEBT_REPAYMENT,
            rule_version=rule_version,
            trigger={
                "repaid_tael": repaid_tael,
                "debt_tael": self.debt_tael,
                SILVER_DELTA: -repaid_tael,
                DEBT_DELTA: -repaid_tael,
            },
            outcome="repaid" if repaid_tael > 0 else "nothing-available",
        )

    def record_repayment_from_harvest(
        self, *, repaid_tael: float, price_tael_per_shi: float, rule_version: str
    ) -> CohortEvent:
        """Repay a grain loan out of the harvest; the counterparty is not modelled yet.

        The grain given up is derived from the silver repaid, and both are capped by what the
        cohort actually holds, so neither balance can be over-drawn.
        """
        repaid = min(repaid_tael, self.debt_tael)
        grain = repaid / price_tael_per_shi
        if grain > self.grain_shi:
            grain = self.grain_shi
            repaid = grain * price_tael_per_shi
        self._apply(
            grain=-grain,
            debt=-repaid,
            impacts=((GRAIN_DELTA, -grain), (DEBT_DELTA, -repaid)),
        )
        return CohortEvent(
            event_type=CohortEventType.DEBT_REPAYMENT,
            rule_version=rule_version,
            trigger={
                "repaid_tael": repaid,
                "grain_repaid_shi": grain,
                "price_tael_per_shi": price_tael_per_shi,
                "debt_tael": self.debt_tael,
                GRAIN_DELTA: -grain,
                DEBT_DELTA: -repaid,
            },
            outcome="repaid-in-grain",
        )

    def enter_coping_stage(
        self, stage: CopingStage, *, reason: str, rule_version: str
    ) -> CohortEvent | None:
        """Escalate the recorded coping stage; returns an event only on a transition."""
        if stage <= self.coping_stage:
            return None
        previous = self.coping_stage
        self.coping_stage = stage
        return CohortEvent(
            event_type=CohortEventType.COPING_TRANSITION,
            rule_version=rule_version,
            trigger={
                "stage_from": float(previous),
                "stage_to": float(stage),
                "land_per_household_mu": self.land_per_household_mu,
                "grain_per_household_shi": self.grain_per_household_shi,
            },
            outcome=f"{previous.token}->{stage.token}:{reason}",
        )

    def reset_coping_stage(self, *, reason: str, rule_version: str) -> CohortEvent | None:
        """Return to self-sufficiency after a harvest that covers the year's need."""
        if self.coping_stage is CopingStage.SELF_SUFFICIENT:
            return None
        previous = self.coping_stage
        self.coping_stage = CopingStage.SELF_SUFFICIENT
        return CohortEvent(
            event_type=CohortEventType.COPING_TRANSITION,
            rule_version=rule_version,
            trigger={
                "stage_from": float(previous),
                "stage_to": float(CopingStage.SELF_SUFFICIENT),
                "grain_per_household_shi": self.grain_per_household_shi,
            },
            outcome=f"{previous.token}->self_sufficient:{reason}",
        )

    def record_eligibility(
        self,
        *,
        unmet_ratio_12m: float,
        temporary: bool,
        permanent: bool,
        recruitment: bool,
        rule_version: str,
    ) -> CohortEvent | None:
        """Record eligibility changes; P03 moves nobody, it only records who could move."""
        changed = (
            temporary != self.temporary_migration_eligible
            or permanent != self.permanent_migration_eligible
            or recruitment != self.recruitment_eligible
        )
        self.temporary_migration_eligible = temporary
        self.permanent_migration_eligible = permanent
        self.recruitment_eligible = recruitment
        if not changed:
            return None
        flags = [
            name
            for name, value in (
                ("temporary-migration", temporary),
                ("permanent-migration", permanent),
                ("recruitment", recruitment),
            )
            if value
        ]
        return CohortEvent(
            event_type=CohortEventType.ELIGIBILITY,
            rule_version=rule_version,
            trigger={
                "unmet_ratio_12m": unmet_ratio_12m,
                "temporary_migration_eligible": float(temporary),
                "permanent_migration_eligible": float(permanent),
                "recruitment_eligible": float(recruitment),
                "land_per_household_mu": self.land_per_household_mu,
            },
            outcome="+".join(flags) if flags else "none",
        )

    def snapshot_event(self, *, rule_version: str) -> CohortEvent:
        """The monthly state record; a derived view, not hidden state."""
        return CohortEvent(
            event_type=CohortEventType.COHORT_STATE,
            rule_version=rule_version,
            trigger={
                "households": self.households,
                "adults": self.adults,
                "land_mu": self.land_mu,
                "land_per_household_mu": self.land_per_household_mu,
                "grain_shi": self.grain_shi,
                "silver_tael": self.silver_tael,
                "debt_tael": self.debt_tael,
                "movable_assets_tael": self.movable_assets_tael,
                "season_impact": self.season_impact,
                "coping_stage_index": float(self.coping_stage),
                "temporary_migration_eligible": float(self.temporary_migration_eligible),
                "permanent_migration_eligible": float(self.permanent_migration_eligible),
                "recruitment_eligible": float(self.recruitment_eligible),
            },
            outcome=self.coping_stage.token,
        )

    # ------------------------------------------------------------------ monthly budget

    def monthly_budget(
        self,
        ctx: TickContext,
        *,
        parameters: HouseholdParameters,
        labour_demand_factor: float,
        market: GrainMarket,
        credit: CreditSource,
        rule_version: str,
        phase: TickPhase = TickPhase.HOUSEHOLD_CONSUMPTION,
    ) -> tuple[CohortEvent, ...]:
        """Run the declared coping ladder for one month and return the recorded transitions.

        Fixed, versioned order, matching the phase specification:

        ```text
        1 stored grain and in-kind wages (and silver on hand, both stored resources)
        2 discretionary consumption cut down to the floor
        3 borrowing request
        4 movable asset sale
        5 land sale
        6 eligibility flags (computed by the bookkeeping system, not here)
        ```

        Silver on hand is spent after the consumption cut and before borrowing, because a
        household that cannot reach the floor first accepts eating less and then pays for the
        rest. Every rung is executed against a counterparty — the local grain market for food and
        movables, the local elite for credit and land — so a rung fails when the counterparty
        cannot deliver, not when a formula says so. Whatever part of the floor is still unmet
        after the whole ladder is recorded as unmet need, which raises the cohort's distress
        ratio and nothing else.

        ``labour_demand_factor`` is the local harvest's yield fraction: a failed harvest means
        little work and little wage. It is a declared placeholder for the labour market that
        P05 introduces; the model claims no wage formation of its own.
        """
        need = parameters.subsistence_grain_per_adult_month_shi * self.adults
        floor = need * parameters.minimum_consumption_fraction
        price = market.price_tael_per_shi

        demand = labour_demand_factor
        events: list[CohortEvent] = [
            self.receive_wage_grain(
                grain_shi=self.adults * parameters.wage_grain_shi_per_adult_month * demand,
                wage_shi_per_adult=parameters.wage_grain_shi_per_adult_month,
                labour_demand_factor=demand,
                rule_version=rule_version,
            )
        ]

        eaten_from_storage = self.eat_from_storage(need)
        purchased = 0.0
        gap = max(0.0, floor - eaten_from_storage)
        used_credit = used_assets = used_land = False

        if gap > 0:
            bought = self._buy_food(
                ctx,
                market,
                phase=phase,
                gap=gap,
                price=price,
                occasion="silver-on-hand",
                events=events,
                rule_version=rule_version,
            )
            purchased += bought
            gap = max(0.0, gap - bought)

        if gap > 0:
            requested = gap * price
            decision = credit.borrow(
                ctx,
                self,
                requested_tael=requested,
                collateral_tael=self.collateral_value_tael,
                existing_debt_tael=self.debt_tael,
            )
            events.append(
                self.record_borrowing_request(
                    requested_tael=requested,
                    granted_tael=decision.granted_tael,
                    capacity_tael=decision.capacity_tael,
                    lender_id=decision.lender_id,
                    rule_version=rule_version,
                )
            )
            if decision.granted_tael > 0:
                bought = self._buy_food(
                    ctx,
                    market,
                    gap=gap,
                    price=price,
                    occasion=f"borrowed-from:{decision.lender_id}",
                    events=events,
                    rule_version=rule_version,
                )
                used_credit = bought > 0
                purchased += bought
                gap = max(0.0, gap - bought)

        if gap > 0:
            outcome = market.buy_movables(
                ctx,
                self,
                wanted_tael=gap * price,
                max_tael=self.movable_assets_tael,
                phase=phase,
            )
            if outcome.quantity > 0:
                events.append(
                    self.record_movable_asset_sale(
                        proceeds_tael=outcome.quantity, rule_version=rule_version
                    )
                )
                bought = self._buy_food(
                    ctx,
                    market,
                    gap=gap,
                    price=price,
                    occasion=f"asset-sale-to:{outcome.counterparty_id}",
                    events=events,
                    rule_version=rule_version,
                )
                used_assets = bought > 0
                purchased += bought
                gap = max(0.0, gap - bought)

        if gap > 0:
            land_price = credit.land_price_tael_per_mu
            outcome = credit.sell_land(ctx, self, wanted_tael=gap * price, max_mu=self.land_mu)
            if outcome.quantity > 0:
                events.append(
                    self.record_land_sale(
                        mu=outcome.quantity,
                        price_tael_per_mu=land_price,
                        rule_version=rule_version,
                    )
                )
                bought = self._buy_food(
                    ctx,
                    market,
                    gap=gap,
                    price=price,
                    occasion=f"land-sale-to:{outcome.counterparty_id}",
                    events=events,
                    rule_version=rule_version,
                )
                used_land = bought > 0
                purchased += bought
                gap = max(0.0, gap - bought)

        # Food bought this month is eaten this month; the draw is debited here so that a
        # purchase is credited once and debited once. Only purchased grain can remain to eat:
        # the first draw already took everything up to `need` from the granary.
        shortfall = max(0.0, floor - eaten_from_storage)
        eaten_from_purchases = self.eat_from_storage(shortfall)
        eaten = eaten_from_storage + eaten_from_purchases
        unmet = max(0.0, floor - eaten)
        events.append(
            self.record_consumption(
                need_shi=need,
                floor_shi=floor,
                eaten_shi=eaten,
                from_purchases_shi=eaten_from_purchases,
                purchased_shi=purchased,
                rule_version=rule_version,
            )
        )

        stage = self._stage_reached(
            consumed=eaten,
            need=need,
            unmet=unmet,
            used_credit=used_credit,
            used_assets=used_assets,
            used_land=used_land,
        )
        transition = self.enter_coping_stage(
            stage, reason="monthly-budget", rule_version=rule_version
        )
        if transition is not None:
            events.append(transition)
        return tuple(events)

    def _buy_food(
        self,
        ctx: TickContext,
        market: GrainMarket,
        *,
        gap: float,
        price: float,
        occasion: str,
        events: list[CohortEvent],
        phase: TickPhase = TickPhase.HOUSEHOLD_CONSUMPTION,
        rule_version: str,
    ) -> float:
        """Buy what the market can deliver with the silver on hand; returns the shi delivered."""
        if self.silver_tael <= 0.0 or gap <= 0.0:
            return 0.0
        outcome = market.buy_grain(
            ctx, self, shi_wanted=gap, max_silver=self.silver_tael, phase=phase
        )
        if outcome.quantity <= 0.0:
            return 0.0
        events.append(
            self.record_grain_purchase(
                shi=outcome.quantity,
                price_tael_per_shi=price,
                occasion=occasion,
                rule_version=rule_version,
            )
        )
        return outcome.quantity

    def _stage_reached(
        self,
        *,
        consumed: float,
        need: float,
        unmet: float,
        used_credit: bool,
        used_assets: bool,
        used_land: bool,
    ) -> CopingStage:
        if unmet > 0:
            return CopingStage.DESTITUTE
        if used_land:
            return CopingStage.SELLING_LAND
        if used_assets:
            return CopingStage.SELLING_ASSETS
        if used_credit:
            return CopingStage.BORROWING
        if consumed < need:
            return CopingStage.REDUCING_CONSUMPTION
        return CopingStage.SELF_SUFFICIENT


class HouseholdPopulation:
    """All cohorts of a run, with the rolling distress window and the invariant check."""

    def __init__(
        self,
        cohorts: Sequence[HouseholdCohortAgent],
        *,
        window_months: int = DISTRESS_WINDOW_MONTHS,
    ) -> None:
        if not cohorts:
            raise ValueError("a population needs at least one cohort")
        if window_months < 1:
            raise ValueError("the distress window needs at least one month")
        ordered = tuple(sorted(cohorts, key=lambda cohort: cohort.cohort_id))
        ids = [cohort.cohort_id for cohort in ordered]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate cohort ids: {', '.join(sorted(ids))}")
        self._cohorts = ordered
        self._by_id = MappingProxyType({cohort.cohort_id: cohort for cohort in ordered})
        self._window_months = window_months
        self._need_window: dict[str, deque[float]] = {
            cohort.cohort_id: deque(maxlen=window_months) for cohort in ordered
        }
        self._unmet_window: dict[str, deque[float]] = {
            cohort.cohort_id: deque(maxlen=window_months) for cohort in ordered
        }
        self._labour_demand: dict[str, float] = {
            node_id: 1.0 for node_id in sorted({cohort.node_id for cohort in ordered})
        }

    def __iter__(self) -> Iterator[HouseholdCohortAgent]:
        return iter(self._cohorts)

    def __len__(self) -> int:
        return len(self._cohorts)

    @property
    def cohorts(self) -> tuple[HouseholdCohortAgent, ...]:
        return self._cohorts

    @property
    def by_id(self) -> Mapping[str, HouseholdCohortAgent]:
        return self._by_id

    @property
    def total_households(self) -> float:
        return sum(cohort.households for cohort in self._cohorts)

    @property
    def window_months(self) -> int:
        return self._window_months

    def require(self, cohort_id: str) -> HouseholdCohortAgent:
        try:
            return self._by_id[cohort_id]
        except KeyError as error:
            raise KeyError(f"unknown cohort {cohort_id!r}") from error

    def set_node_yield_factor(self, node_id: str, yield_fraction: float) -> None:
        """Record how good the last local harvest was; labour demand follows it."""
        if not 0.0 <= yield_fraction <= 1.0:
            raise ValueError(f"yield fraction must lie in [0, 1], got {yield_fraction}")
        self._labour_demand[node_id] = yield_fraction

    def node_yield_factor(self, node_id: str) -> float:
        try:
            return self._labour_demand[node_id]
        except KeyError as error:
            raise KeyError(f"unknown node {node_id!r}") from error

    def record_month(self, cohort_id: str, *, need_shi: float, unmet_shi: float) -> None:
        self._need_window[cohort_id].append(need_shi)
        self._unmet_window[cohort_id].append(unmet_shi)

    def unmet_ratio(self, cohort_id: str) -> float:
        """Share of the trailing window's subsistence floor that went unmet."""
        need = sum(self._need_window[cohort_id])
        if need <= 0:
            return 0.0
        return sum(self._unmet_window[cohort_id]) / need

    def check_invariants(self) -> None:
        """Reconcile every cohort, in a fixed order so failures are reproducible."""
        for cohort in self._cohorts:
            cohort.check_balances()
