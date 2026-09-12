"""Merchant houses and the aggregated merchant layer.

Merchants are the grain market's working capital. A house buys grain where it is cheap and
sells it where it is dear, holds stock between harvests, and is limited by its own silver and
by the trade links declared in `G_trade`. It is an aggregate of the grain merchants of one
node, not a named firm.

Every movement is logged twice — once on the household's side, once here — so the run-scale
invariants can assert that grain and silver were transferred, not created. Nothing in this
module is a price-setting rule: prices come from :mod:`late_ming_lab.systems.markets`, which
reads the inventory these houses hold.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import Field

from late_ming_lab.actors.ledger import (
    ASSETS_DELTA,
    GRAIN_DELTA,
    SILVER_DELTA,
    LedgerAgent,
)


class MerchantEventType:
    """Event names used by merchant-side transitions."""

    BUY_FROM_HOUSEHOLD = "MERCHANT_PURCHASE"
    SELL_TO_HOUSEHOLD = "MERCHANT_SALE"
    BUY_MOVABLES = "MERCHANT_MOVABLES_PURCHASE"
    SHIP_OUT = "TRADE_SHIPMENT"
    RECEIVE = "TRADE_RECEIPT"
    TRADE_LOSS = "TRADE_LOSS"
    STATE = "MERCHANT_STATE"


@dataclass(frozen=True, slots=True)
class MerchantEvent:
    """One merchant-side transition, ready to be emitted by a system."""

    event_type: str
    rule_version: str
    trigger: dict[str, float]
    outcome: str


class MerchantHouse(LedgerAgent):
    """Aggregated grain merchants of one node: silver, stock, and goods taken in trade."""

    node_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    silver_tael: float = Field(ge=0)
    grain_shi: float = Field(ge=0)
    goods_tael: float = Field(default=0.0, ge=0)

    @property
    def merchant_id(self) -> str:
        return f"merchant::{self.node_id}"

    @property
    def ledger_name(self) -> str:
        return self.merchant_id

    # ------------------------------------------------------------------ transitions

    def sell_to_household(
        self, *, shi: float, price_tael_per_shi: float, buyer_id: str, rule_version: str
    ) -> MerchantEvent:
        """Sell grain to a household for silver.

        The quantity is capped at the granary itself: rounding in a price calculation must never
        be able to oversell the stock, because a negative granary is refused by the ledger.
        """
        shi = min(shi, self.grain_shi)
        proceeds = shi * price_tael_per_shi
        self._apply(
            grain=-shi,
            silver=proceeds,
            impacts=((GRAIN_DELTA, -shi), (SILVER_DELTA, proceeds)),
        )
        return MerchantEvent(
            event_type=MerchantEventType.SELL_TO_HOUSEHOLD,
            rule_version=rule_version,
            trigger={
                "shi": shi,
                "price_tael_per_shi": price_tael_per_shi,
                "proceeds_tael": proceeds,
                GRAIN_DELTA: -shi,
                SILVER_DELTA: proceeds,
                "counterparty_is_household": 1.0,
            },
            outcome=f"sold-to:{buyer_id}",
        )

    def buy_from_household(
        self,
        *,
        shi: float,
        price_tael_per_shi: float,
        seller_id: str,
        rule_version: str,
        seller_kind: str = "household",
    ) -> MerchantEvent:
        """Buy grain from a household or an elite estate for silver.

        The seller's kind is recorded in the outcome, so a reader of the log can tell whether a
        merchant bought from a household or from an estate without cross-referencing agent ids.
        """
        cost = min(shi * price_tael_per_shi, self.silver_tael)
        shi = cost / price_tael_per_shi
        self._apply(
            grain=shi,
            silver=-cost,
            impacts=((GRAIN_DELTA, shi), (SILVER_DELTA, -cost)),
        )
        return MerchantEvent(
            event_type=MerchantEventType.BUY_FROM_HOUSEHOLD,
            rule_version=rule_version,
            trigger={
                "shi": shi,
                "price_tael_per_shi": price_tael_per_shi,
                "cost_tael": cost,
                GRAIN_DELTA: shi,
                SILVER_DELTA: -cost,
            },
            outcome=f"bought-from-{seller_kind}:{seller_id}",
        )

    def buy_movables(
        self, *, proceeds_tael: float, seller_id: str, rule_version: str
    ) -> MerchantEvent:
        """Take movable goods off a household's hands in exchange for silver."""
        proceeds_tael = min(proceeds_tael, self.silver_tael)
        self._apply(
            silver=-proceeds_tael,
            goods=proceeds_tael,
            impacts=((SILVER_DELTA, -proceeds_tael), (ASSETS_DELTA, proceeds_tael)),
        )
        return MerchantEvent(
            event_type=MerchantEventType.BUY_MOVABLES,
            rule_version=rule_version,
            trigger={
                "proceeds_tael": proceeds_tael,
                "goods_tael": self.goods_tael,
                SILVER_DELTA: -proceeds_tael,
                ASSETS_DELTA: proceeds_tael,
            },
            outcome=f"bought-goods-from:{seller_id}",
        )

    def ship_out(
        self,
        *,
        shi: float,
        arrived_shi: float,
        proceeds_tael: float,
        destination: str,
        rule_version: str,
    ) -> tuple[MerchantEvent, MerchantEvent]:
        """Send grain along a link and sell what arrives.

        The consignment leaves the granary whole; what the link's risk destroys never arrives,
        never earns silver and is recorded as a separate loss, so the loss cannot be hidden in
        the shipment total.
        """
        lost = shi - arrived_shi
        self._apply(
            grain=-shi,
            silver=proceeds_tael,
            impacts=((GRAIN_DELTA, -shi), (SILVER_DELTA, proceeds_tael)),
        )
        shipment = MerchantEvent(
            event_type=MerchantEventType.SHIP_OUT,
            rule_version=rule_version,
            trigger={
                "shi": shi,
                "arrived_shi": arrived_shi,
                "lost_shi": lost,
                "proceeds_tael": proceeds_tael,
                GRAIN_DELTA: -shi,
                SILVER_DELTA: proceeds_tael,
            },
            outcome=f"shipped-to:{destination}",
        )
        loss = MerchantEvent(
            event_type=MerchantEventType.TRADE_LOSS,
            rule_version=rule_version,
            trigger={"lost_shi": lost, "destination_is_external": 0.0},
            outcome="lost-in-transit",
        )
        return shipment, loss

    def receive(
        self, *, shi: float, paid_tael: float, origin: str, rule_version: str
    ) -> MerchantEvent:
        """Receive a shipment and pay for it, never spending silver it does not hold."""
        paid_tael = min(paid_tael, self.silver_tael)
        self._apply(
            grain=shi,
            silver=-paid_tael,
            impacts=((GRAIN_DELTA, shi), (SILVER_DELTA, -paid_tael)),
        )
        return MerchantEvent(
            event_type=MerchantEventType.RECEIVE,
            rule_version=rule_version,
            trigger={
                "shi": shi,
                "paid_tael": paid_tael,
                GRAIN_DELTA: shi,
                SILVER_DELTA: -paid_tael,
            },
            outcome=f"received-from:{origin}",
        )

    def snapshot(self, *, price_tael_per_shi: float, rule_version: str) -> MerchantEvent:
        """Monthly state record; a derived view, not hidden state."""
        return MerchantEvent(
            event_type=MerchantEventType.STATE,
            rule_version=rule_version,
            trigger={
                "grain_shi": self.grain_shi,
                "silver_tael": self.silver_tael,
                "goods_tael": self.goods_tael,
                "price_tael_per_shi": price_tael_per_shi,
                "stock_value_tael": self.grain_shi * price_tael_per_shi,
            },
            outcome="merchant-state",
        )


class MerchantLayer:
    """The merchant houses of every node, in a fixed order."""

    def __init__(self, houses: Sequence[MerchantHouse]) -> None:
        if not houses:
            raise ValueError("a merchant layer needs at least one house")
        ordered = tuple(sorted(houses, key=lambda house: house.node_id))
        ids = [house.node_id for house in ordered]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate merchant nodes: {', '.join(sorted(ids))}")
        self._houses = ordered
        self._by_node = MappingProxyType({house.node_id: house for house in ordered})

    def __iter__(self) -> Iterator[MerchantHouse]:
        return iter(self._houses)

    def __len__(self) -> int:
        return len(self._houses)

    @property
    def houses(self) -> tuple[MerchantHouse, ...]:
        return self._houses

    @property
    def by_node(self) -> Mapping[str, MerchantHouse]:
        return self._by_node

    @property
    def total_grain_shi(self) -> float:
        return sum(house.grain_shi for house in self._houses)

    @property
    def total_silver_tael(self) -> float:
        return sum(house.silver_tael for house in self._houses)

    def require(self, node_id: str) -> MerchantHouse:
        try:
            return self._by_node[node_id]
        except KeyError as error:
            raise KeyError(f"no merchant house at {node_id!r}") from error

    def check_invariants(self) -> None:
        for house in self._houses:
            house.check_balances()
