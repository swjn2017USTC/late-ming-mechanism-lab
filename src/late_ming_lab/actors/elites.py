"""Local elites: the counterparty that P03 was missing.

An elite house is the aggregated landholding and money-lending interest of one node: it
collects rent, lends silver against collateral, buys land from households that are selling,
releases grain as private relief, and mediates tax (an interface, because no tax demand exists
before P05). It is an aggregate, not a named family and not a moral type.

Nothing here decides whether elites are benevolent or predatory. Every action is a rule with
declared parameters — a lending rate and collateral rule, a land price, a relief rule keyed to
measured distress — and the phase's job is to measure what those rules produce: price
dispersion, land concentration, debt distribution, and whether credit delays collapse or
accelerates dispossession. The interesting outcome is that the same rules can do both.

Elite claims are **derived**, never stored: the outstanding claim on households in a node is
the sum of those households' debts, so accrued interest cannot drift between borrower and
lender records.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from late_ming_lab.actors.ledger import (
    GRAIN_DELTA,
    LAND_DELTA,
    SILVER_DELTA,
    LedgerAgent,
)
from late_ming_lab.core.events import Event
from late_ming_lab.core.tick import TickContext, TickPhase
from late_ming_lab.evidence.parameters import EliteParameters


class EliteEventType:
    """Event names used by elite-side transitions."""

    RENT_RECEIVED = "ELITE_RENT"
    GRAIN_RECEIVED = "ELITE_GRAIN_RECEIPT"
    LOAN_ISSUED = "ELITE_LOAN"
    LOAN_REPAID = "ELITE_LOAN_REPAID"
    DEFAULT = "ELITE_DEFAULT"
    FORECLOSURE = "ELITE_FORECLOSURE"
    LAND_PURCHASE = "ELITE_LAND_PURCHASE"
    RELIEF = "ELITE_RELIEF"
    GRAIN_SALE = "ELITE_GRAIN_SALE"
    GRAIN_SEIZURE = "ELITE_GRAIN_SEIZED"
    TAX_MEDIATION = "ELITE_TAX_MEDIATION"
    STATE = "ELITE_STATE"


@dataclass(frozen=True, slots=True)
class EliteEvent:
    """One elite-side transition, ready to be emitted by a system."""

    event_type: str
    rule_version: str
    trigger: dict[str, float]
    outcome: str


class LocalEliteAgent(LedgerAgent):
    """Aggregated elite house of one node."""

    node_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    households: float = Field(gt=0)
    land_mu: float = Field(ge=0)
    grain_shi: float = Field(ge=0)
    silver_tael: float = Field(ge=0)

    @property
    def elite_id(self) -> str:
        return f"elite::{self.node_id}"

    @property
    def ledger_name(self) -> str:
        return self.elite_id

    @property
    def land_per_household_mu(self) -> float:
        return self.land_mu / self.households

    # ------------------------------------------------------------------ transitions

    def receive_rent(self, *, grain_shi: float, payer_id: str, rule_version: str) -> EliteEvent:
        self._apply(grain=grain_shi, impacts=((GRAIN_DELTA, grain_shi),))
        return EliteEvent(
            event_type=EliteEventType.RENT_RECEIVED,
            rule_version=rule_version,
            trigger={
                "rent_shi": grain_shi,
                GRAIN_DELTA: grain_shi,
                "grain_shi": self.grain_shi,
            },
            outcome=f"rent-from:{payer_id}",
        )

    def issue_loan(self, *, granted_tael: float, borrower_id: str, rule_version: str) -> EliteEvent:
        """Lend silver; the matching claim grows on the borrower's side."""
        self._apply(silver=-granted_tael, impacts=((SILVER_DELTA, -granted_tael),))
        return EliteEvent(
            event_type=EliteEventType.LOAN_ISSUED,
            rule_version=rule_version,
            trigger={
                "granted_tael": granted_tael,
                "silver_left_tael": self.silver_tael,
                SILVER_DELTA: -granted_tael,
            },
            outcome=f"lent-to:{borrower_id}",
        )

    def receive_repayment(
        self, *, repaid_tael: float, borrower_id: str, in_kind: bool, rule_version: str
    ) -> EliteEvent:
        """Take repayment in silver; grain repayment arrives through :meth:`receive_grain`."""
        self._apply(silver=repaid_tael, impacts=((SILVER_DELTA, repaid_tael),))
        return EliteEvent(
            event_type=EliteEventType.LOAN_REPAID,
            rule_version=rule_version,
            trigger={
                "repaid_tael": repaid_tael,
                "repaid_in_kind": float(in_kind),
                SILVER_DELTA: repaid_tael,
            },
            outcome=f"repaid-by:{borrower_id}",
        )

    def receive_grain(
        self, *, grain_shi: float, payer_id: str, reason: str, rule_version: str
    ) -> EliteEvent:
        self._apply(grain=grain_shi, impacts=((GRAIN_DELTA, grain_shi),))
        return EliteEvent(
            event_type=EliteEventType.GRAIN_RECEIVED,
            rule_version=rule_version,
            trigger={
                "grain_received_shi": grain_shi,
                GRAIN_DELTA: grain_shi,
                "grain_shi": self.grain_shi,
            },
            outcome=f"{reason}:{payer_id}",
        )

    def declare_default(
        self,
        *,
        outstanding_tael: float,
        months_unserviced: int,
        borrower_id: str,
        rule_version: str,
    ) -> EliteEvent:
        """Record that a borrower's obligation went unserviced past the declared term.

        Nothing moves here: a default is a statement about the claim, and it is recorded so the
        foreclosure that follows it is attributable. The rule that calls it lives in the debt
        phase, which is the only place that knows whether a month was serviced.
        """
        return EliteEvent(
            event_type=EliteEventType.DEFAULT,
            rule_version=rule_version,
            trigger={
                "outstanding_tael": outstanding_tael,
                "months_unserviced": float(months_unserviced),
            },
            outcome=f"defaulted:{borrower_id}",
        )

    def foreclose_land(
        self,
        *,
        mu: float,
        pledge_mu: float,
        settled_tael: float,
        surplus_tael: float,
        borrower_id: str,
        rule_version: str,
    ) -> EliteEvent:
        """Take pledged land in satisfaction of an unserviced claim.

        No silver moves, which is what separates this from :meth:`buy_land`: the lender keeps the
        claim's silver and takes the land instead. The pledge is forfeit whole, so where its value
        exceeds the obligation it settles, the excess stays with the lender — that margin is the
        lender's gain and is recorded as ``surplus_over_claim_tael`` rather than left implicit.
        The claim itself falls on the borrower's side, where claims are held — the elite's
        outstanding claims are derived from borrower debt, so recording ``settled_tael`` here and
        not there could not drift.
        """
        self._apply(land=mu, impacts=((LAND_DELTA, mu),))
        return EliteEvent(
            event_type=EliteEventType.FORECLOSURE,
            rule_version=rule_version,
            trigger={
                "mu_transferred": mu,
                "pledge_mu": pledge_mu,
                "settled_tael": settled_tael,
                "surplus_over_claim_tael": surplus_tael,
                "land_mu": self.land_mu,
                LAND_DELTA: mu,
            },
            outcome=f"foreclosed-from:{borrower_id}",
        )

    def buy_land(
        self, *, mu: float, paid_tael: float, seller_id: str, rule_version: str
    ) -> EliteEvent:
        self._apply(
            land=mu,
            silver=-paid_tael,
            impacts=((LAND_DELTA, mu), (SILVER_DELTA, -paid_tael)),
        )
        return EliteEvent(
            event_type=EliteEventType.LAND_PURCHASE,
            rule_version=rule_version,
            trigger={
                "land_bought_mu": mu,
                "paid_tael": paid_tael,
                "land_mu": self.land_mu,
                LAND_DELTA: mu,
                SILVER_DELTA: -paid_tael,
            },
            outcome=f"bought-from:{seller_id}",
        )

    def release_relief(
        self, *, grain_shi: float, recipient_id: str, rule_version: str
    ) -> EliteEvent:
        self._apply(grain=-grain_shi, impacts=((GRAIN_DELTA, -grain_shi),))
        return EliteEvent(
            event_type=EliteEventType.RELIEF,
            rule_version=rule_version,
            trigger={
                "released_shi": grain_shi,
                "grain_left_shi": self.grain_shi,
                GRAIN_DELTA: -grain_shi,
            },
            outcome=f"relieved:{recipient_id}",
        )

    def record_grain_seizure(
        self,
        *,
        grain_shi: float,
        taker_id: str,
        rule_version: str,
        reason: str = "band",
    ) -> EliteEvent:
        """Lose stored grain to a raider; taken, not sold."""
        taken = min(grain_shi, self.grain_shi)
        if taken <= 0.0:
            raise ValueError("a grain seizure must take at least one shi")
        self._apply(grain=-taken, impacts=((GRAIN_DELTA, -taken),))
        return EliteEvent(
            event_type=EliteEventType.GRAIN_SEIZURE,
            rule_version=rule_version,
            trigger={
                "grain_seized_shi": taken,
                GRAIN_DELTA: -taken,
                "grain_shi": self.grain_shi,
                f"reason_is_{reason}": 1.0,
            },
            outcome=f"seized-by:{taker_id}",
        )

    def sell_grain(
        self, *, shi: float, price_tael_per_shi: float, buyer_id: str, rule_version: str
    ) -> EliteEvent:
        proceeds = shi * price_tael_per_shi
        self._apply(
            grain=-shi,
            silver=proceeds,
            impacts=((GRAIN_DELTA, -shi), (SILVER_DELTA, proceeds)),
        )
        return EliteEvent(
            event_type=EliteEventType.GRAIN_SALE,
            rule_version=rule_version,
            trigger={
                "shi": shi,
                "price_tael_per_shi": price_tael_per_shi,
                "proceeds_tael": proceeds,
                GRAIN_DELTA: -shi,
                SILVER_DELTA: proceeds,
            },
            outcome=f"sold-to:{buyer_id}",
        )

    def record_tax_mediation(
        self,
        *,
        advanced_tael: float,
        client_id: str,
        demand_tael: float,
        rule_version: str,
    ) -> EliteEvent:
        """Record an advance made on a household's behalf against an expected tax demand."""
        self._apply(silver=-advanced_tael, impacts=((SILVER_DELTA, -advanced_tael),))
        return EliteEvent(
            event_type=EliteEventType.TAX_MEDIATION,
            rule_version=rule_version,
            trigger={
                "advanced_tael": advanced_tael,
                "demand_tael": demand_tael,
                "silver_left_tael": self.silver_tael,
                SILVER_DELTA: -advanced_tael,
            },
            outcome=f"advanced-for:{client_id}",
        )

    def snapshot(
        self, *, claims_tael: float, price_tael_per_shi: float, rule_version: str
    ) -> EliteEvent:
        return EliteEvent(
            event_type=EliteEventType.STATE,
            rule_version=rule_version,
            trigger={
                "land_mu": self.land_mu,
                "land_per_household_mu": self.land_per_household_mu,
                "grain_shi": self.grain_shi,
                "silver_tael": self.silver_tael,
                "outstanding_claims_tael": claims_tael,
                "grain_value_tael": self.grain_shi * price_tael_per_shi,
            },
            outcome="elite-state",
        )


def emit_elite_event(
    ctx: TickContext, elite: LocalEliteAgent, event: EliteEvent, phase: TickPhase
) -> Event:
    """Write one elite transition into the run's event log."""
    return ctx.emit(
        event.event_type,
        phase=phase.token,
        agent_id=elite.elite_id,
        region=elite.node_id,
        rule_version=event.rule_version,
        trigger=event.trigger,
        outcome=event.outcome,
    )


@runtime_checkable
class TaxMediationPolicy(Protocol):
    """How elites mediate the tax obligations of their clients.

    P05 owns the tax system and the actual demand. This interface exists now so that the elite
    layer is written against a bounded policy rather than against a guess about taxation: the
    policy is asked how much it will advance for a client, and the advance is recorded as a
    claim on that client.
    """

    @property
    def name(self) -> str: ...

    def advance_tael(
        self, *, parameters: EliteParameters, client_land_mu: float, demand_tael: float
    ) -> float: ...


class NoTaxMediation(BaseModel):
    """The default: no tax demand exists yet, so nothing is advanced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = "none"

    def advance_tael(
        self, *, parameters: EliteParameters, client_land_mu: float, demand_tael: float
    ) -> float:
        return 0.0


class AdvanceBasedTaxMediation(BaseModel):
    """Advance a share of the demand for clients above a land threshold.

    The rule is deliberately blunt and grade ``S``: elites with silver cover part of the
    obligation of landholding clients. P05 supplies the real demand; P12 can test alternatives.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = "advance-based"
    minimum_client_land_mu: float = Field(ge=0)

    def advance_tael(
        self, *, parameters: EliteParameters, client_land_mu: float, demand_tael: float
    ) -> float:
        if demand_tael <= 0.0 or client_land_mu < self.minimum_client_land_mu:
            return 0.0
        return demand_tael * parameters.tax_mediation_advance_share


class EliteLayer:
    """The elite houses of every node, in a fixed order."""

    def __init__(self, elite_houses: Sequence[LocalEliteAgent]) -> None:
        if not elite_houses:
            raise ValueError("an elite layer needs at least one house")
        ordered = tuple(sorted(elite_houses, key=lambda house: house.node_id))
        ids = [house.node_id for house in ordered]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate elite nodes: {', '.join(sorted(ids))}")
        self._houses = ordered
        self._by_node = MappingProxyType({house.node_id: house for house in ordered})

    def __iter__(self) -> Iterator[LocalEliteAgent]:
        return iter(self._houses)

    def __len__(self) -> int:
        return len(self._houses)

    @property
    def houses(self) -> tuple[LocalEliteAgent, ...]:
        return self._houses

    @property
    def by_node(self) -> Mapping[str, LocalEliteAgent]:
        return self._by_node

    @property
    def total_land_mu(self) -> float:
        return sum(house.land_mu for house in self._houses)

    @property
    def total_silver_tael(self) -> float:
        return sum(house.silver_tael for house in self._houses)

    @property
    def total_grain_shi(self) -> float:
        return sum(house.grain_shi for house in self._houses)

    def require(self, node_id: str) -> LocalEliteAgent:
        try:
            return self._by_node[node_id]
        except KeyError as error:
            raise KeyError(f"no elite house at {node_id!r}") from error

    def check_invariants(self) -> None:
        for house in self._houses:
            house.check_balances()
