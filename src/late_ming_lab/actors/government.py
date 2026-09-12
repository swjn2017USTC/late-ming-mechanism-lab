"""County government: assessment, collection, the treasury and the relief granary.

State capacity is **five separate capacities**, never one number (RULES 4):

| Capacity | What it bounds |
| --- | --- |
| `TaxCollectionCapacity` | the share of an assessed obligation the apparatus can actually reach |
| `InformationCapacity` | how much of the true tax base it can see — unseen land is untaxed |
| `ReliefCapacity` | the share of assessed relief need it can actually deliver |
| `CoercionCapacity` | the extra reach it can force; distress shows as extra liquidation |
| `LogisticsCapacity` | how much collection and relief cost per unit delivered |

They are stored separately, parameterised separately, and each has its own measured effect;
:class:`StateCapacity` deliberately has no mean, index or total, and a test asserts that no
aggregate can be added without someone noticing.

The tax ledger is decomposed the way M3 requires: a nominal quota, the collection effort spent
against it, what that effort cost, what was actually received, and what remains in arrears. The
county's silver and granary are reconciled like every other actor's balances, and every movement
is logged with the counterparty that paid or received it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from late_ming_lab.actors.ledger import (
    GRAIN_DELTA,
    SILVER_DELTA,
    LedgerAgent,
)

FISCAL_RULE_VERSION: Final[str] = "fiscal-v1"
RELIEF_RULE_VERSION: Final[str] = "official-relief-v1"
TREASURY_RULE_VERSION: Final[str] = "treasury-v1"

CAPACITY_FIELDS: Final[tuple[str, ...]] = (
    "tax_collection",
    "information",
    "relief",
    "coercion",
    "logistics",
)


class StateCapacity(BaseModel):
    """The five capacities of a county government, kept apart on purpose."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tax_collection: float = Field(ge=0.0, le=1.0)
    information: float = Field(ge=0.0, le=1.0)
    relief: float = Field(ge=0.0, le=1.0)
    coercion: float = Field(ge=0.0, le=1.0)
    logistics: float = Field(ge=0.0, le=1.0)

    def as_mapping(self) -> Mapping[str, float]:
        """Read the capacities by name; there is no aggregate form of this model."""
        return MappingProxyType({field: float(getattr(self, field)) for field in CAPACITY_FIELDS})


class GovernmentEventType(StrEnum):
    """Every transition a county government can record."""

    ASSESSMENT = "TAX_ASSESSMENT"
    RECEIPT = "TAX_RECEIPT"
    COLLECTION_COST = "TAX_COLLECTION_COST"
    ARREARS_CHANGE = "TAX_ARREARS"
    EXTRACTION_DECISION = "EXTRACTION_DECISION"
    GRAIN_PURCHASE = "GOVERNMENT_GRAIN_PURCHASE"
    RELIEF_RELEASE = "OFFICIAL_RELIEF"
    RELIEF_COST = "OFFICIAL_RELIEF_COST"
    MILITARY_PAY = "MILITARY_PAY_OUTLAY"
    GRAIN_ISSUE = "GOVERNMENT_GRAIN_ISSUE"
    GRAIN_SEIZURE = "GRANARY_GRAIN_SEIZED"
    STATE = "COUNTY_STATE"


@dataclass(frozen=True, slots=True)
class GovernmentEvent:
    """One government transition, ready to be emitted by a system."""

    event_type: GovernmentEventType
    rule_version: str
    trigger: dict[str, float]
    outcome: str


class CountyGovernment(LedgerAgent):
    """One county's fiscal apparatus: treasury, granary, capacities and tax flows."""

    node_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    capacity: StateCapacity
    silver_tael: float = Field(ge=0)
    grain_shi: float = Field(ge=0)

    _flows: dict[str, float] = PrivateAttr(default_factory=dict)

    def model_post_init(self, _context: object) -> None:
        super().model_post_init(_context)
        self.begin_tick()

    def begin_tick(self) -> None:
        """Reset the month's flow counters; balances are never touched here."""
        self._flows = {
            "quota_tael": 0.0,
            "receipts_tael": 0.0,
            "collection_cost_tael": 0.0,
            "arrears_delta_tael": 0.0,
            "relief_released_shi": 0.0,
            "relief_cost_tael": 0.0,
            "taxable_land_mu": 0.0,
            "hidden_land_mu": 0.0,
            "assessment_rate": 0.0,
            "collection_effort": 0.0,
            "reachable_tael": 0.0,
            "pressure": 0.0,
            "military_pay_tael": 0.0,
            "military_grain_shi": 0.0,
        }

    @property
    def flows(self) -> Mapping[str, float]:
        """This month's fiscal flows, as the bookkeeping phase will report them."""
        return MappingProxyType(self._flows)

    def accumulate(self, **amounts: float) -> None:
        """Add to this month's flows; unknown names are refused so typos cannot vanish."""
        for name, amount in amounts.items():
            if name not in self._flows:
                raise KeyError(f"unknown county flow {name!r}")
            self._flows[name] = self._flows[name] + amount

    @property
    def government_id(self) -> str:
        return f"county::{self.node_id}"

    @property
    def ledger_name(self) -> str:
        return self.government_id

    # ------------------------------------------------------------------ assessment

    def record_assessment(
        self,
        *,
        quota_tael: float,
        taxable_land_mu: float,
        hidden_land_mu: float,
        assessment_rate: float,
        rule_version: str = FISCAL_RULE_VERSION,
    ) -> GovernmentEvent:
        """Record a nominal quota; an assessment moves no balance, it creates an obligation."""
        self.accumulate(
            quota_tael=quota_tael,
            taxable_land_mu=taxable_land_mu,
            hidden_land_mu=hidden_land_mu,
            assessment_rate=assessment_rate,
        )
        return GovernmentEvent(
            event_type=GovernmentEventType.ASSESSMENT,
            rule_version=rule_version,
            trigger={
                "quota_tael": quota_tael,
                "taxable_land_mu": taxable_land_mu,
                "hidden_land_mu": hidden_land_mu,
                "assessment_rate": assessment_rate,
                "information_capacity": self.capacity.information,
            },
            outcome="assessed",
        )

    def record_extraction_decision(
        self,
        *,
        pressure: float,
        effort: float,
        arrears_tael_before: float,
        quota_tael: float,
        reachable_tael: float,
        rule_version: str = FISCAL_RULE_VERSION,
    ) -> GovernmentEvent:
        """Record what the extraction policy decided, and the capacity it ran into."""
        self.accumulate(
            pressure=pressure,
            collection_effort=effort,
            reachable_tael=reachable_tael,
        )
        return GovernmentEvent(
            event_type=GovernmentEventType.EXTRACTION_DECISION,
            rule_version=rule_version,
            trigger={
                "pressure": pressure,
                "collection_effort": effort,
                "arrears_tael_before": arrears_tael_before,
                "quota_tael": quota_tael,
                "reachable_tael": reachable_tael,
                "tax_collection_capacity": self.capacity.tax_collection,
                "coercion_capacity": self.capacity.coercion,
                "logistics_capacity": self.capacity.logistics,
            },
            outcome="collected" if effort > 0.0 else "no-effort",
        )

    # ------------------------------------------------------------------ collection

    def receive_tax(
        self,
        *,
        silver_tael: float,
        payer_id: str,
        channel: str,
        rule_version: str = FISCAL_RULE_VERSION,
    ) -> GovernmentEvent:
        """Take silver in; the channel names who actually paid it."""
        self._apply(silver=silver_tael, impacts=((SILVER_DELTA, silver_tael),))
        self.accumulate(receipts_tael=silver_tael)
        return GovernmentEvent(
            event_type=GovernmentEventType.RECEIPT,
            rule_version=rule_version,
            trigger={
                "receipts_tael": silver_tael,
                SILVER_DELTA: silver_tael,
                "silver_tael": self.silver_tael,
            },
            outcome=f"{channel}:{payer_id}",
        )

    def pay_collection_cost(
        self, *, silver_tael: float, rule_version: str = FISCAL_RULE_VERSION
    ) -> GovernmentEvent:
        """Pay for the collection effort itself; the cost never reaches the treasury."""
        paid = min(silver_tael, self.silver_tael)
        self._apply(silver=-paid, impacts=((SILVER_DELTA, -paid),))
        self.accumulate(collection_cost_tael=paid)
        return GovernmentEvent(
            event_type=GovernmentEventType.COLLECTION_COST,
            rule_version=rule_version,
            trigger={
                "collection_cost_tael": paid,
                "collection_cost_due_tael": silver_tael,
                SILVER_DELTA: -paid,
                "logistics_capacity": self.capacity.logistics,
            },
            outcome="paid" if paid >= silver_tael else "unpaid-in-part",
        )

    def record_arrears(
        self, *, delta_tael: float, rule_version: str = FISCAL_RULE_VERSION
    ) -> GovernmentEvent:
        """Add to or write down the outstanding obligation; arrears are a stock, not a balance."""
        self.accumulate(arrears_delta_tael=delta_tael)
        return GovernmentEvent(
            event_type=GovernmentEventType.ARREARS_CHANGE,
            rule_version=rule_version,
            trigger={"arrears_delta_tael": delta_tael},
            outcome="accrued" if delta_tael >= 0 else "written-down",
        )

    # ------------------------------------------------------------------ treasury and relief

    def buy_grain(
        self,
        *,
        grain_shi: float,
        price_tael_per_shi: float,
        rule_version: str = TREASURY_RULE_VERSION,
    ) -> GovernmentEvent:
        """Fill the relief granary from the market at the posted price."""
        cost = min(grain_shi * price_tael_per_shi, self.silver_tael)
        shi = cost / price_tael_per_shi if price_tael_per_shi > 0 else 0.0
        self._apply(
            grain=shi,
            silver=-cost,
            impacts=((GRAIN_DELTA, shi), (SILVER_DELTA, -cost)),
        )
        return GovernmentEvent(
            event_type=GovernmentEventType.GRAIN_PURCHASE,
            rule_version=rule_version,
            trigger={
                "purchased_shi": shi,
                "price_tael_per_shi": price_tael_per_shi,
                "cost_tael": cost,
                GRAIN_DELTA: shi,
                SILVER_DELTA: -cost,
                "granary_shi": self.grain_shi,
            },
            outcome="granary-filled",
        )

    def release_relief(
        self,
        *,
        grain_shi: float,
        recipient_id: str,
        rule_version: str = RELIEF_RULE_VERSION,
    ) -> GovernmentEvent:
        """Release grain from the granary to a household.

        A relief plan can exceed the granary; what is released is what it holds, and the event
        records both the plan and the release so a shortfall is visible rather than hidden.
        """
        released = min(grain_shi, self.grain_shi)
        self._apply(grain=-released, impacts=((GRAIN_DELTA, -released),))
        self.accumulate(relief_released_shi=released)
        return GovernmentEvent(
            event_type=GovernmentEventType.RELIEF_RELEASE,
            rule_version=rule_version,
            trigger={
                "released_shi": released,
                "planned_shi": grain_shi,
                GRAIN_DELTA: -released,
                "granary_shi": self.grain_shi,
                "relief_capacity": self.capacity.relief,
            },
            outcome=f"relieved:{recipient_id}",
        )

    def pay_military(
        self, *, silver_tael: float, payee_id: str, rule_version: str
    ) -> GovernmentEvent:
        """Pay the garrison: silver out of the treasury, against pay already owed."""
        paid = min(silver_tael, self.silver_tael)
        self._apply(silver=-paid, impacts=((SILVER_DELTA, -paid),))
        self.accumulate(military_pay_tael=paid)
        return GovernmentEvent(
            event_type=GovernmentEventType.MILITARY_PAY,
            rule_version=rule_version,
            trigger={
                "military_pay_tael": paid,
                "military_pay_requested_tael": silver_tael,
                SILVER_DELTA: -paid,
                "silver_tael": self.silver_tael,
            },
            outcome=f"paid-to:{payee_id}" if paid > 0.0 else "nothing-to-pay",
        )

    def issue_grain(
        self, *, grain_shi: float, recipient_id: str, rule_version: str
    ) -> GovernmentEvent:
        """Issue grain from the granary as military rations.

        Separate from :meth:`release_relief`: the same granary feeds both the garrison and the
        starving, and the two claims must stay distinguishable in the log.
        """
        issued = min(grain_shi, self.grain_shi)
        self._apply(grain=-issued, impacts=((GRAIN_DELTA, -issued),))
        self.accumulate(military_grain_shi=issued)
        return GovernmentEvent(
            event_type=GovernmentEventType.GRAIN_ISSUE,
            rule_version=rule_version,
            trigger={
                "grain_issued_shi": issued,
                "grain_requested_shi": grain_shi,
                GRAIN_DELTA: -issued,
                "granary_shi": self.grain_shi,
            },
            outcome=f"issued-to:{recipient_id}",
        )

    def record_grain_seizure(
        self, *, grain_shi: float, taker_id: str, rule_version: str, reason: str = "band"
    ) -> GovernmentEvent:
        """Lose granary grain to a raider."""
        taken = min(grain_shi, self.grain_shi)
        if taken <= 0.0:
            raise ValueError("a grain seizure must take at least one shi")
        self._apply(grain=-taken, impacts=((GRAIN_DELTA, -taken),))
        return GovernmentEvent(
            event_type=GovernmentEventType.GRAIN_SEIZURE,
            rule_version=rule_version,
            trigger={
                "grain_seized_shi": taken,
                GRAIN_DELTA: -taken,
                "granary_shi": self.grain_shi,
                f"reason_is_{reason}": 1.0,
            },
            outcome=f"seized-by:{taker_id}",
        )

    def pay_relief_cost(
        self, *, silver_tael: float, rule_version: str = RELIEF_RULE_VERSION
    ) -> GovernmentEvent:
        """Pay the logistics of a relief operation; the grain itself is the other cost."""
        paid = min(silver_tael, self.silver_tael)
        self._apply(silver=-paid, impacts=((SILVER_DELTA, -paid),))
        self.accumulate(relief_cost_tael=paid)
        return GovernmentEvent(
            event_type=GovernmentEventType.RELIEF_COST,
            rule_version=rule_version,
            trigger={
                "relief_cost_tael": paid,
                "relief_cost_due_tael": silver_tael,
                SILVER_DELTA: -paid,
                "logistics_capacity": self.capacity.logistics,
            },
            outcome="paid" if paid >= silver_tael else "unpaid-in-part",
        )

    def snapshot(
        self, *, arrears_tael: float, rule_version: str = FISCAL_RULE_VERSION
    ) -> GovernmentEvent:
        """The county's monthly state record: this month's flows, balances and five capacities.

        The capacities travel separately, as five fields, and no aggregate of them is computed
        anywhere in the model.
        """
        flows = self._flows
        return GovernmentEvent(
            event_type=GovernmentEventType.STATE,
            rule_version=rule_version,
            trigger={
                "quota_tael": flows["quota_tael"],
                "assessment_rate": flows["assessment_rate"],
                "collection_effort": flows["collection_effort"],
                "reachable_tael": flows["reachable_tael"],
                "pressure": flows["pressure"],
                "receipts_tael": flows["receipts_tael"],
                "collection_cost_tael": flows["collection_cost_tael"],
                "net_receipts_tael": flows["receipts_tael"] - flows["collection_cost_tael"],
                "arrears_tael": arrears_tael,
                "arrears_delta_tael": flows["arrears_delta_tael"],
                "taxable_land_mu": flows["taxable_land_mu"],
                "hidden_land_mu": flows["hidden_land_mu"],
                "relief_released_shi": flows["relief_released_shi"],
                "relief_cost_tael": flows["relief_cost_tael"],
                "military_pay_tael": flows["military_pay_tael"],
                "military_grain_shi": flows["military_grain_shi"],
                "silver_tael": self.silver_tael,
                "granary_shi": self.grain_shi,
                "tax_collection_capacity": self.capacity.tax_collection,
                "information_capacity": self.capacity.information,
                "relief_capacity": self.capacity.relief,
                "coercion_capacity": self.capacity.coercion,
                "logistics_capacity": self.capacity.logistics,
            },
            outcome="county-state",
        )


class GovernmentLayer:
    """The county governments of every node, in a fixed order."""

    def __init__(self, governments: Sequence[CountyGovernment]) -> None:
        if not governments:
            raise ValueError("a government layer needs at least one county")
        ordered = tuple(sorted(governments, key=lambda county: county.node_id))
        ids = [county.node_id for county in ordered]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate counties: {', '.join(sorted(ids))}")
        self._counties = ordered
        self._by_node = MappingProxyType({county.node_id: county for county in ordered})

    def __iter__(self) -> Iterator[CountyGovernment]:
        return iter(self._counties)

    def __len__(self) -> int:
        return len(self._counties)

    @property
    def counties(self) -> tuple[CountyGovernment, ...]:
        return self._counties

    @property
    def total_silver_tael(self) -> float:
        return sum(county.silver_tael for county in self._counties)

    @property
    def total_grain_shi(self) -> float:
        return sum(county.grain_shi for county in self._counties)

    def require(self, node_id: str) -> CountyGovernment:
        try:
            return self._by_node[node_id]
        except KeyError as error:
            raise KeyError(f"no county government at {node_id!r}") from error

    def check_invariants(self) -> None:
        for county in self._counties:
            county.check_balances()
