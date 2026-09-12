"""What an actor needs from the other actors, declared where the need arises.

Households do not know whether the merchant layer or the elite layer exists; they know they can
try to buy grain, borrow silver and sell land. Systems implement these protocols, so the actor
contracts stay independent of the systems that satisfy them, and a test can substitute a stub
counterparty without touching the household.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from late_ming_lab.core.tick import TickContext, TickPhase


class CounterpartyError(RuntimeError):
    """Raised when a counterparty cannot execute a requested interaction."""


class NodeBound(Protocol):
    """Anything that belongs to one node; all exchange is local."""

    @property
    def node_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class CreditDecision:
    """The lender's answer to a borrowing request."""

    granted_tael: float
    capacity_tael: float
    lender_id: str

    def __post_init__(self) -> None:
        if self.granted_tael < 0 or self.capacity_tael < 0:
            raise CounterpartyError("a credit decision cannot be negative")
        if self.granted_tael > self.capacity_tael + 1e-9:
            raise CounterpartyError(
                f"granted {self.granted_tael} exceeds the stated capacity {self.capacity_tael}"
            )


@dataclass(frozen=True, slots=True)
class TradeOutcome:
    """What a counterparty actually executed, as opposed to what was asked for."""

    quantity: float
    value_tael: float
    counterparty_id: str

    def __post_init__(self) -> None:
        if self.quantity < 0 or self.value_tael < 0:
            raise CounterpartyError("a trade outcome cannot be negative")


class GrainMarket(Protocol):
    """The local grain market as a household sees it."""

    @property
    def price_tael_per_shi(self) -> float: ...

    def buy_grain(
        self,
        ctx: TickContext,
        buyer: NodeBound,
        shi_wanted: float,
        max_silver: float,
        *,
        phase: TickPhase = TickPhase.HOUSEHOLD_CONSUMPTION,
    ) -> TradeOutcome:
        """Sell grain to a household, limited by the market's stock and the household's silver.

        ``phase`` is the tick phase that asked for the trade. It is part of the audit trail, so the
        caller supplies it: a household buying dinner and a county buying rations are the same
        market transaction happening at different points in the tick.
        """
        ...

    def buy_movables(
        self,
        ctx: TickContext,
        seller: NodeBound,
        wanted_tael: float,
        max_tael: float,
        *,
        phase: TickPhase = TickPhase.HOUSEHOLD_CONSUMPTION,
    ) -> TradeOutcome:
        """Buy movable goods, limited by the buyer's silver and what the household owns."""
        ...


class CreditSource(Protocol):
    """The local lender as a household sees it."""

    @property
    def land_price_tael_per_mu(self) -> float: ...

    def borrow(
        self,
        ctx: TickContext,
        borrower: NodeBound,
        requested_tael: float,
        collateral_tael: float,
        existing_debt_tael: float,
    ) -> CreditDecision: ...

    def sell_land(
        self, ctx: TickContext, seller: NodeBound, wanted_tael: float, max_mu: float
    ) -> TradeOutcome:
        """Buy land, limited by the buyer's silver and the land the household holds."""
        ...
