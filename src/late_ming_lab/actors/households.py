"""Weighted household cohorts and their balance sheets.

A cohort represents ``households`` households with the same endowment and the same
environment; it never represents a named family and never invents household-level detail. All
quantities are cohort totals in the units declared in :mod:`late_ming_lab.evidence.parameters`
(grain in ``shi``, silver in ``tael``, land in ``mu``).

Two rules are enforced in code rather than documented only:

- **no negative balance** — every field is validated on assignment, so a bug that would drive
  grain, silver, land, assets or debt below zero raises immediately;
- **no unsourced balance change** — balances change only through the accounting primitives
  below, each of which records its delta and emits the event that explains it. Balances are
  reconciled against the recorded deltas on every check, so an assignment that bypassed the
  ledger surfaces as a mismatch instead of a silent gift.

The coping ladder lives in :meth:`HouseholdCohortAgent.monthly_budget` because it is the
household's own behaviour. What it does *not* contain is any anger, grievance or rebellion
scalar: distress is a physical ledger quantity — subsistence need that went unmet — and
nothing else.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from late_ming_lab.core.events import Event
from late_ming_lab.core.tick import TickContext, TickPhase
from late_ming_lab.evidence.parameters import HouseholdParameters
from late_ming_lab.networks.nodes import AgrarianZone

COHORT_ID_PATTERN = r"^[a-z0-9][a-z0-9._:-]*$"
DISTRESS_WINDOW_MONTHS = 12

#: Trigger keys that carry a balance change; the event log *is* the ledger.
GRAIN_DELTA = "grain_delta_shi"
SILVER_DELTA = "silver_delta_tael"
LAND_DELTA = "land_delta_mu"
DEBT_DELTA = "debt_delta_tael"
ASSETS_DELTA = "assets_delta_tael"

LEDGER_KEYS: tuple[str, ...] = (GRAIN_DELTA, SILVER_DELTA, LAND_DELTA, DEBT_DELTA, ASSETS_DELTA)

BALANCE_TOLERANCE = 1e-9

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
    LAND_SALE = "LAND_SALE"
    COPING_TRANSITION = "COPING_TRANSITION"
    HARVEST = "HARVEST"
    RENT_PAYMENT = "RENT_PAYMENT"
    DEBT_INTEREST = "DEBT_INTEREST"
    DEBT_REPAYMENT = "DEBT_REPAYMENT"
    ELIGIBILITY = "ELIGIBILITY"
    COHORT_STATE = "COHORT_STATE"


class HouseholdLedgerError(RuntimeError):
    """Raised when a cohort's balances disagree with the deltas it recorded."""


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


class HouseholdCohortAgent(BaseModel):
    """One weighted cohort of households with its balance sheet and coping state."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    cohort_id: str = Field(pattern=COHORT_ID_PATTERN, max_length=128)
    node_id: str = Field(pattern=COHORT_ID_PATTERN, max_length=64)
    cohort_class: CohortClass
    zone: AgrarianZone

    households: float = Field(gt=0)
    adults: float = Field(gt=0)
    land_mu: float = Field(ge=0)
    grain_shi: float = Field(ge=0)
    silver_tael: float = Field(ge=0)
    debt_tael: float = Field(ge=0)
    movable_assets_tael: float = Field(ge=0)

    season_impact: float = Field(default=0.0, ge=0)
    coping_stage: CopingStage = CopingStage.SELF_SUFFICIENT
    temporary_migration_eligible: bool = False
    permanent_migration_eligible: bool = False
    recruitment_eligible: bool = False

    _ledger: dict[str, float] = PrivateAttr(default_factory=dict)
    _initial: dict[str, float] = PrivateAttr(default_factory=dict)
    _land_reference_value: float = PrivateAttr(default=0.0)

    def model_post_init(self, _context: object) -> None:
        self._ledger = dict.fromkeys(LEDGER_KEYS, 0.0)
        self._initial = {
            "households": self.households,
            "grain": self.grain_shi,
            "silver": self.silver_tael,
            "land": self.land_mu,
            "debt": self.debt_tael,
            "assets": self.movable_assets_tael,
        }

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

    @property
    def ledger_deltas(self) -> Mapping[str, float]:
        return MappingProxyType(self._ledger)

    def set_land_reference_value(self, value: float) -> None:
        """Collateral valuation used for credit capacity; declared by the run's parameters."""
        if value <= 0:
            raise ValueError("land reference value must be positive")
        self._land_reference_value = value

    # ------------------------------------------------------------------ accounting core

    def _apply(
        self,
        *,
        grain: float = 0.0,
        silver: float = 0.0,
        land: float = 0.0,
        debt: float = 0.0,
        assets: float = 0.0,
        impacts: tuple[tuple[str, float], ...] = (),
    ) -> None:
        """Apply a balance change; the only place balances ever move.

        The new balances are checked before anything is written, so a rejected change leaves the
        cohort exactly as it was instead of half-moved.
        """
        candidates = (
            ("grain_shi", self.grain_shi + grain),
            ("silver_tael", self.silver_tael + silver),
            ("land_mu", self.land_mu + land),
            ("debt_tael", self.debt_tael + debt),
            ("movable_assets_tael", self.movable_assets_tael + assets),
        )
        for name, value in candidates:
            if not math.isfinite(value) or value < 0.0:
                raise HouseholdLedgerError(
                    f"{self.cohort_id}: refusing an impossible balance change; {name} would "
                    f"become {value}"
                )
        self.grain_shi, self.silver_tael, self.land_mu, self.debt_tael, self.movable_assets_tael = (
            candidates[0][1],
            candidates[1][1],
            candidates[2][1],
            candidates[3][1],
            candidates[4][1],
        )
        for key, value in impacts:
            self._ledger[key] = self._ledger[key] + value

    def check_balances(self) -> None:
        """Reconcile every balance against its recorded deltas and check conservation."""
        initial = self._initial
        expected = {
            "grain": initial["grain"] + self._ledger[GRAIN_DELTA],
            "silver": initial["silver"] + self._ledger[SILVER_DELTA],
            "land": initial["land"] + self._ledger[LAND_DELTA],
            "debt": initial["debt"] + self._ledger[DEBT_DELTA],
            "assets": initial["assets"] + self._ledger[ASSETS_DELTA],
        }
        actual = {
            "grain": self.grain_shi,
            "silver": self.silver_tael,
            "land": self.land_mu,
            "debt": self.debt_tael,
            "assets": self.movable_assets_tael,
        }
        for name, value in expected.items():
            if not math.isclose(actual[name], value, rel_tol=1e-9, abs_tol=BALANCE_TOLERANCE):
                raise HouseholdLedgerError(
                    f"{self.cohort_id}: {name} is {actual[name]} but the recorded deltas "
                    f"account for {value}; a balance changed without an entry"
                )
        if self.households != initial["households"]:
            raise HouseholdLedgerError(
                f"{self.cohort_id}: cohort weight changed from {initial['households']} to "
                f"{self.households}; P03 records eligibility but moves no household"
            )

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
        rule_version: str,
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
            },
            outcome="granted" if granted_tael > 0 else "no-capacity",
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

    def record_movable_asset_sale(self, *, proceeds_tael: float, rule_version: str) -> CohortEvent:
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
            },
            outcome="sold-for-food",
        )

    def record_land_sale(
        self, *, mu: float, price_tael_per_mu: float, rule_version: str
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
            },
            outcome="distress-sale",
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
        self, *, grain_shi: float, share: float, rule_version: str
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
            outcome="paid-to-unmodelled-landlord",
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
        *,
        parameters: HouseholdParameters,
        labour_demand_factor: float,
        rule_version: str,
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
        rest; borrowing starts only when its own silver is gone. Whatever part of the floor is
        still unmet after the whole ladder is recorded as unmet need, which raises the cohort's
        distress ratio and nothing else.

        ``labour_demand_factor`` is the local harvest's yield fraction: a failed harvest means
        little work and little wage. It is a declared placeholder for the labour market that
        P05 introduces; the model claims no wage formation of its own.
        """
        need = parameters.subsistence_grain_per_adult_month_shi * self.adults
        floor = need * parameters.minimum_consumption_fraction
        price = parameters.distress_grain_price_tael_per_shi

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

        if gap > 0:
            purchase_events, bought = self._buy_with_silver(
                gap, price=price, occasion="silver-on-hand", rule_version=rule_version
            )
            events.extend(purchase_events)
            purchased += bought
            gap = max(0.0, gap - bought)

        used_credit = used_assets = used_land = False

        if gap > 0:
            purchase_events, bought = self._borrow_and_buy(
                gap, price=price, parameters=parameters, rule_version=rule_version
            )
            events.extend(purchase_events)
            used_credit = bought > 0
            purchased += bought
            gap = max(0.0, gap - bought)

        if gap > 0:
            purchase_events, bought = self._sell_movables_and_buy(
                gap, price=price, rule_version=rule_version
            )
            events.extend(purchase_events)
            used_assets = bought > 0
            purchased += bought
            gap = max(0.0, gap - bought)

        if gap > 0:
            purchase_events, bought = self._sell_land_and_buy(
                gap, price=price, parameters=parameters, rule_version=rule_version
            )
            events.extend(purchase_events)
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

    def _buy_with_silver(
        self, gap_shi: float, *, price: float, occasion: str, rule_version: str
    ) -> tuple[list[CohortEvent], float]:
        if self.silver_tael <= 0:
            return [], 0.0
        event = self.record_grain_purchase(
            shi=min(gap_shi, self.silver_tael / price),
            price_tael_per_shi=price,
            occasion=occasion,
            rule_version=rule_version,
        )
        return [event], event.trigger["purchased_shi"]

    def _borrow_and_buy(
        self,
        gap_shi: float,
        *,
        price: float,
        parameters: HouseholdParameters,
        rule_version: str,
    ) -> tuple[list[CohortEvent], float]:
        capacity = max(0.0, parameters.loan_to_value * self.collateral_value_tael - self.debt_tael)
        required = gap_shi * price
        granted = min(required, capacity)
        events = [
            self.record_borrowing_request(
                requested_tael=required,
                granted_tael=granted,
                capacity_tael=capacity,
                rule_version=rule_version,
            )
        ]
        if granted <= 0:
            return events, 0.0
        purchase = self.record_grain_purchase(
            shi=min(gap_shi, granted / price),
            price_tael_per_shi=price,
            occasion="borrowed",
            rule_version=rule_version,
        )
        events.append(purchase)
        return events, purchase.trigger["purchased_shi"]

    def _sell_movables_and_buy(
        self, gap_shi: float, *, price: float, rule_version: str
    ) -> tuple[list[CohortEvent], float]:
        proceeds = min(self.movable_assets_tael, gap_shi * price)
        if proceeds <= 0:
            return [], 0.0
        events = [self.record_movable_asset_sale(proceeds_tael=proceeds, rule_version=rule_version)]
        events.append(
            self.record_grain_purchase(
                shi=min(gap_shi, proceeds / price),
                price_tael_per_shi=price,
                occasion="asset-sale",
                rule_version=rule_version,
            )
        )
        return events, events[-1].trigger["purchased_shi"]

    def _sell_land_and_buy(
        self,
        gap_shi: float,
        *,
        price: float,
        parameters: HouseholdParameters,
        rule_version: str,
    ) -> tuple[list[CohortEvent], float]:
        required = gap_shi * price
        land_price = parameters.land_distress_price_tael_per_mu
        mu = min(self.land_mu, required / land_price)
        if mu <= 0:
            return [], 0.0
        events = [
            self.record_land_sale(mu=mu, price_tael_per_mu=land_price, rule_version=rule_version)
        ]
        events.append(
            self.record_grain_purchase(
                shi=min(gap_shi, (mu * land_price) / price),
                price_tael_per_shi=price,
                occasion="land-sale",
                rule_version=rule_version,
            )
        )
        return events, events[-1].trigger["purchased_shi"]


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
            node_id: 1.0 for node_id in {cohort.node_id for cohort in ordered}
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
