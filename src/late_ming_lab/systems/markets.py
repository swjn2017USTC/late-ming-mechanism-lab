"""The grain market: county inventory, endogenous price, intercounty trade.

Prices are formed from the market's own inventory, not from a script: each node's posted price
falls as the local merchant house accumulates stock and rises as it runs down, and merchants
then arbitrage between nodes along ``G_trade``. Transport cost, link capacity and link risk all
bind, so a price gap that looks profitable can still be untradeable.

The link data comes from P02, where ``cost`` and ``capacity`` were declared dimensionless. P04
fixes their units by declaration: one cost unit becomes silver per shi through
``transport_cost_tael_per_cost_unit_per_shi``, one capacity unit becomes shi per month, and link
risk becomes the fraction of a consignment that never arrives.

Transport cost is a **decision hurdle**, not a payment: it has to be beaten before a merchant
ships, but no carrier actor exists in P04 and no silver leaves anyone to pay it. The cost is
recorded on each flow for analysis, and a later phase that models carriers must move it into the
ledger. Those conversions are grade ``S``
assumptions, stated once, in :class:`~late_ming_lab.evidence.parameters.MarketParameters`.

Nothing here decides what a price *should* be. The phase measures what this rule produces.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from late_ming_lab.actors.elites import EliteEvent, EliteLayer, LocalEliteAgent
from late_ming_lab.actors.exchange import NodeBound, TradeOutcome
from late_ming_lab.actors.households import (
    HOUSEHOLD_RULE_VERSION,
    HouseholdPopulation,
    emit_cohort_event,
)
from late_ming_lab.actors.merchants import MerchantEvent, MerchantHouse, MerchantLayer
from late_ming_lab.core.tick import (
    RESOURCE_COHORT_GRAIN,
    RESOURCE_COHORT_SILVER,
    RESOURCE_ELITE_GRAIN,
    RESOURCE_ELITE_SILVER,
    RESOURCE_MARKET_PRICE,
    RESOURCE_MERCHANT_STOCK,
    TickContext,
    TickPhase,
)
from late_ming_lab.evidence.parameters import (
    EliteParameters,
    HouseholdParameters,
    MarketParameters,
)
from late_ming_lab.networks.disruption import CalmTrade, TradeDisruption
from late_ming_lab.networks.graphs import SpatialGraphs

MARKET_RULE_VERSION: Final[str] = "market-clearing-v1"
TRADE_RULE_VERSION: Final[str] = "intercounty-trade-v1"
MARKET_STATE_EVENT: Final[str] = "MARKET_STATE"
MERCHANT_STATE_EVENT: Final[str] = "MERCHANT_STATE"
#: The price chain's own constraints, one row per node and month: V2-P04.
MARKET_CONSTRAINT_EVENT: Final[str] = "MARKET_CONSTRAINT"


class MarketPrice(BaseModel):
    """The posted state of one county's grain market."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: str
    price_tael_per_shi: float = Field(gt=0)
    inventory_shi: float = Field(ge=0)
    local_need_shi: float = Field(ge=0)


@dataclass(frozen=True, slots=True)
class DemandRecord:
    """Grain wanted at one node since the previous pricing, and why it was not served.

    ``unsold_shi`` is demand the buyer could pay for and the merchant could not supply: the stock
    constraint. ``unaffordable_shi`` is demand with no silver behind it: hunger the price cannot see
    unless the rule is told to look at it. Keeping them apart is the point — they are different
    facts about a famine, and a single "unmet need" number would merge them.
    """

    wanted_shi: float = 0.0
    unsold_shi: float = 0.0
    unaffordable_shi: float = 0.0

    @property
    def total_shi(self) -> float:
        return self.wanted_shi


@dataclass(frozen=True, slots=True)
class TradeFlow:
    """One intercounty consignment, for analysis and for the report."""

    origin: str
    destination: str
    shipped_shi: float
    arrived_shi: float
    lost_shi: float
    proceeds_tael: float
    transport_cost_tael: float


class MarketBook:
    """Posted prices, one per node, carried between ticks."""

    def __init__(self, prices: Mapping[str, float]) -> None:
        if not prices:
            raise ValueError("a market book needs at least one price")
        # Demand is carried on the book because the book is the one market object every system
        # holding a LocalGrainMarket already shares; a counter inside the view would see only the
        # callers that happen to use that view.
        self._demand: dict[str, DemandRecord] = {node_id: DemandRecord() for node_id in prices}
        self._prices = {
            node_id: MarketPrice(
                node_id=node_id, price_tael_per_shi=price, inventory_shi=0.0, local_need_shi=0.0
            )
            for node_id, price in sorted(prices.items())
        }

    @property
    def nodes(self) -> tuple[str, ...]:
        return tuple(self._prices)

    def state(self, node_id: str) -> MarketPrice:
        try:
            return self._prices[node_id]
        except KeyError as error:
            raise KeyError(f"no posted price for {node_id!r}") from error

    def price(self, node_id: str) -> float:
        return self.state(node_id).price_tael_per_shi

    def post(self, state: MarketPrice) -> None:
        if state.node_id not in self._prices:
            raise KeyError(f"no posted price for {state.node_id!r}")
        self._prices[state.node_id] = state

    def states(self) -> tuple[MarketPrice, ...]:
        return tuple(self._prices[node_id] for node_id in self._prices)

    def demand(self, node_id: str) -> DemandRecord:
        """Grain wanted at a node since the last pricing."""
        try:
            return self._demand[node_id]
        except KeyError as error:
            raise KeyError(f"no demand ledger for {node_id!r}") from error

    def record_demand(
        self, node_id: str, *, wanted_shi: float, unsold_shi: float, unaffordable_shi: float
    ) -> None:
        """Add one purchase attempt to the node's ledger, whether or not it was served."""
        current = self.demand(node_id)
        self._demand[node_id] = DemandRecord(
            wanted_shi=current.wanted_shi + max(0.0, wanted_shi),
            unsold_shi=current.unsold_shi + max(0.0, unsold_shi),
            unaffordable_shi=current.unaffordable_shi + max(0.0, unaffordable_shi),
        )

    def clear_demand(self) -> None:
        """Start a new window; called once per pricing, after the price has been posted."""
        for node_id in self._demand:
            self._demand[node_id] = DemandRecord()


class LocalGrainMarket:
    """The grain market of one node as a household sees it.

    The posted price is the last one the clearing system computed; the merchant house is the
    only counterparty, so a household's purchase fails when the house is out of grain and its
    asset sale fails when the house is out of silver.
    """

    def __init__(
        self,
        *,
        node_id: str,
        book: MarketBook,
        merchants: MerchantLayer,
        rule_version: str = MARKET_RULE_VERSION,
    ) -> None:
        self._node_id = node_id
        self._book = book
        self._merchants = merchants
        self._rule_version = rule_version

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def price_tael_per_shi(self) -> float:
        return self._book.price(self._node_id)

    def _require_local(self, actor: NodeBound) -> MerchantHouse:
        if actor.node_id != self._node_id:
            raise ValueError(
                f"{self._node_id}: this market serves its own node, not {actor.node_id!r}"
            )
        return self._merchants.require(self._node_id)

    def buy_grain(
        self,
        ctx: TickContext,
        buyer: NodeBound,
        shi_wanted: float,
        max_silver: float,
        *,
        phase: TickPhase = TickPhase.MARKET_CLEARING,
    ) -> TradeOutcome:
        """Sell grain to a local counterparty, recorded under the phase that asked for it.

        A county buying rations in phase 10, migrants buying food in phase 09 and a household
        buying its dinner in phase 04 all trade through this market. The phase token is part of the
        audit trail the scheduler promises, so it belongs to the caller, not to the market.
        """
        house = self._require_local(buyer)
        price = self.price_tael_per_shi
        wanted = max(0.0, shi_wanted)
        affordable = min(wanted, max_silver / price) if price > 0.0 else 0.0
        cost = min(wanted * price, max_silver, house.grain_shi * price)
        shi = min(cost / price, house.grain_shi) if price > 0.0 else 0.0
        # Recorded before the early return: a buyer with no silver is the demand the V1 rule never
        # saw, and dropping that row would drop the famine it is evidence of.
        self._book.record_demand(
            self._node_id,
            wanted_shi=wanted,
            unsold_shi=max(0.0, affordable - shi),
            unaffordable_shi=max(0.0, wanted - affordable),
        )
        if cost <= 0.0:
            return TradeOutcome(quantity=0.0, value_tael=0.0, counterparty_id=house.merchant_id)
        cost = shi * price
        event = house.sell_to_household(
            shi=shi,
            price_tael_per_shi=price,
            buyer_id=_identity(buyer),
            rule_version=self._rule_version,
        )
        emit_merchant_event(ctx, house, event, phase)
        return TradeOutcome(quantity=shi, value_tael=cost, counterparty_id=house.merchant_id)

    def buy_movables(
        self,
        ctx: TickContext,
        seller: NodeBound,
        wanted_tael: float,
        max_tael: float,
        *,
        phase: TickPhase = TickPhase.HOUSEHOLD_CONSUMPTION,
    ) -> TradeOutcome:
        """Buy movable property from a local counterparty, under the asking phase."""
        house = self._require_local(seller)
        proceeds = min(wanted_tael, max_tael, house.silver_tael)
        if proceeds <= 0.0:
            return TradeOutcome(quantity=0.0, value_tael=0.0, counterparty_id=house.merchant_id)
        event = house.buy_movables(
            proceeds_tael=proceeds,
            seller_id=_identity(seller),
            rule_version=self._rule_version,
        )
        emit_merchant_event(ctx, house, event, phase)
        return TradeOutcome(
            quantity=proceeds, value_tael=proceeds, counterparty_id=house.merchant_id
        )


class MarketClearingSystem:
    """Tick phase 05: surplus sales, intercounty trade, and next month's prices."""

    name: str = "market-clearing"
    phase: TickPhase = TickPhase.MARKET_CLEARING
    reads: frozenset[str] = frozenset(
        {
            RESOURCE_COHORT_GRAIN,
            RESOURCE_ELITE_GRAIN,
            RESOURCE_MARKET_PRICE,
            RESOURCE_MERCHANT_STOCK,
        }
    )
    writes: frozenset[str] = frozenset(
        {
            RESOURCE_COHORT_GRAIN,
            RESOURCE_COHORT_SILVER,
            RESOURCE_ELITE_GRAIN,
            RESOURCE_ELITE_SILVER,
            RESOURCE_MARKET_PRICE,
            RESOURCE_MERCHANT_STOCK,
        }
    )

    def __init__(
        self,
        *,
        graphs: SpatialGraphs,
        population: HouseholdPopulation,
        merchants: MerchantLayer,
        household_parameters: HouseholdParameters,
        market_parameters: MarketParameters,
        elite_parameters: EliteParameters,
        elite_grain_provider: EliteLayer | None = None,
        disruption: TradeDisruption | None = None,
    ) -> None:
        self._graphs = graphs
        self._population = population
        self._merchants = merchants
        self._household_parameters = household_parameters
        self._parameters = market_parameters
        self._elite_parameters = elite_parameters
        self._elite_grain_provider = elite_grain_provider
        self._disruption = disruption or CalmTrade()
        self._flows: list[TradeFlow] = []
        # Every node the trade graph reaches holds a posted price; external boundary nodes are
        # in the trade graph, so they need one, but the model does not claim to know their
        # scarcity — they post the reference price.
        self._priced_nodes = tuple(sorted(graphs.trade.nodes))
        self._book = MarketBook(
            {
                node_id: market_parameters.reference_price_tael_per_shi
                for node_id in self._priced_nodes
            }
        )

    @property
    def book(self) -> MarketBook:
        return self._book

    @property
    def disruption(self) -> TradeDisruption:
        return self._disruption

    def set_disruption(self, disruption: TradeDisruption) -> None:
        """Install a disruption regime; P06 will drive this from armed-group activity."""
        self._disruption = disruption

    @property
    def last_flows(self) -> tuple[TradeFlow, ...]:
        return tuple(self._flows)

    def local_need_shi(self, node_id: str) -> float:
        """One month of subsistence need for the cohorts of a node."""
        return sum(
            self._household_parameters.subsistence_grain_per_adult_month_shi * cohort.adults
            for cohort in self._population
            if cohort.node_id == node_id
        )

    def step(self, ctx: TickContext) -> None:
        """One monthly clearing, in a declared order.

        Merchants arbitrage between markets first, with the silver they hold, and buy what local
        households and elites want to sell afterwards. Buying the local surplus first would spend
        the silver that importing needs, which is a cash-management artefact rather than a
        mechanism: a merchant facing a high local price imports, then buys what is left over.
        """
        self._flows = []
        self._trade_between_nodes(ctx)
        self._sell_household_surplus(ctx)
        self._sell_elite_surplus(ctx)
        self._post_prices(ctx)
        self._merchants.check_invariants()

    # ------------------------------------------------------------------ clearing

    def _sell_household_surplus(self, ctx: TickContext) -> None:
        """Buy harvest surplus from the cohorts of each node at that node's posted price."""
        for cohort in self._population:
            surplus = cohort.surplus_for_sale(parameters=self._household_parameters)
            if surplus <= 0.0:
                continue
            price = self._book.price(cohort.node_id)
            house = self._merchants.require(cohort.node_id)
            shi = min(surplus, house.silver_tael / price)
            if shi <= 0.0:
                continue
            emit_merchant_event(
                ctx,
                house,
                house.buy_from_household(
                    shi=shi,
                    price_tael_per_shi=price,
                    seller_id=cohort.cohort_id,
                    rule_version=MARKET_RULE_VERSION,
                ),
                self.phase,
            )
            emit_cohort_event(
                ctx,
                cohort,
                cohort.record_market_sale(
                    shi=shi,
                    price_tael_per_shi=price,
                    buyer_id=house.merchant_id,
                    rule_version=HOUSEHOLD_RULE_VERSION,
                ),
                self.phase,
            )

    def _sell_elite_surplus(self, ctx: TickContext) -> None:
        provider = self._elite_grain_provider
        if provider is None:
            return
        for house_entry in provider:
            node_id = house_entry.node_id
            keep = (
                self._elite_parameters.grain_sale_carry_over_ratio_of_local_need
                * self.local_need_shi(node_id)
            )
            surplus = max(0.0, house_entry.grain_shi - keep)
            if surplus <= 0.0:
                continue
            price = self._book.price(node_id)
            house = self._merchants.require(node_id)
            shi = min(surplus, house.silver_tael / price)
            if shi <= 0.0:
                continue
            emit_merchant_event(
                ctx,
                house,
                house.buy_from_household(
                    shi=shi,
                    price_tael_per_shi=price,
                    seller_id=house_entry.elite_id,
                    seller_kind="elite",
                    rule_version=MARKET_RULE_VERSION,
                ),
                self.phase,
            )
            emit_elite_event(
                ctx,
                house_entry,
                house_entry.sell_grain(
                    shi=shi,
                    price_tael_per_shi=price,
                    buyer_id=house.merchant_id,
                    rule_version=MARKET_RULE_VERSION,
                ),
                self.phase,
            )

    def _trade_between_nodes(self, ctx: TickContext) -> None:
        for origin, destination in trade_edges(self._graphs):
            self._ship(ctx, origin, destination)
            self._ship(ctx, destination, origin)

    def _ship(self, ctx: TickContext, origin: str, destination: str) -> None:
        if origin == destination:
            return
        edge = self._graphs.trade[origin][destination]
        origin_price = self._book.price(origin)
        destination_price = self._book.price(destination)
        transport_cost = self._parameters.transport_cost_tael_per_shi(float(edge["cost"]))
        margin = destination_price - origin_price - transport_cost
        if margin <= self._parameters.minimum_trade_margin_tael_per_shi:
            return

        source = self._merchants.require(origin)
        buyer = self._merchants.require(destination)
        capacity = (
            float(edge["capacity"])
            * self._parameters.capacity_unit_shi_per_month
            * self._disruption.capacity_multiplier(origin, destination)
        )
        shippable = min(
            source.grain_shi * self._parameters.max_export_share_of_stock,
            capacity,
        )
        affordable = buyer.silver_tael / max(destination_price, 1e-9)
        shi = min(shippable, affordable)
        if shi <= 0.0:
            return

        loss_fraction = min(
            1.0,
            float(edge["risk"])
            * self._parameters.risk_loss_fraction_scale
            * self._disruption.risk_multiplier(origin, destination),
        )
        arrived = shi * (1.0 - loss_fraction)
        proceeds = arrived * destination_price
        shipment, loss = source.ship_out(
            shi=shi,
            arrived_shi=arrived,
            proceeds_tael=proceeds,
            destination=destination,
            rule_version=TRADE_RULE_VERSION,
        )
        emit_merchant_event(ctx, source, shipment, self.phase)
        emit_merchant_event(ctx, source, loss, self.phase)
        emit_merchant_event(
            ctx,
            buyer,
            buyer.receive(
                shi=arrived, paid_tael=proceeds, origin=origin, rule_version=TRADE_RULE_VERSION
            ),
            self.phase,
        )
        self._flows.append(
            TradeFlow(
                origin=origin,
                destination=destination,
                shipped_shi=shi,
                arrived_shi=arrived,
                lost_shi=shi - arrived,
                proceeds_tael=proceeds,
                transport_cost_tael=transport_cost * shi,
            )
        )

    def _post_prices(self, ctx: TickContext) -> None:
        for node_id in self._priced_nodes:
            house = self._merchants.require(node_id)
            need = self.local_need_shi(node_id)
            demand = self._book.demand(node_id)
            pressure = demand.total_shi / need if need > 0.0 else 0.0
            price = self.price_from_inventory(
                inventory_shi=house.grain_shi, local_need_shi=need, demand_pressure=pressure
            )
            state = MarketPrice(
                node_id=node_id,
                price_tael_per_shi=price,
                inventory_shi=house.grain_shi,
                local_need_shi=need,
            )
            self._book.post(state)
            ctx.emit(
                MARKET_STATE_EVENT,
                phase=self.phase.token,
                region=node_id,
                rule_version=MARKET_RULE_VERSION,
                trigger={
                    "price_tael_per_shi": state.price_tael_per_shi,
                    "inventory_shi": state.inventory_shi,
                    "local_need_shi": state.local_need_shi,
                    "months_of_cover": (
                        state.inventory_shi / state.local_need_shi
                        if state.local_need_shi > 0
                        else 0.0
                    ),
                    "merchant_silver_tael": house.silver_tael,
                },
                outcome="posted",
            )
            emit_merchant_event(
                ctx,
                house,
                house.snapshot(
                    price_tael_per_shi=state.price_tael_per_shi,
                    rule_version=MARKET_RULE_VERSION,
                ),
                self.phase,
            )
            self._emit_constraint(
                ctx, node_id=node_id, state=state, demand=demand, pressure=pressure
            )
        self._book.clear_demand()

    def _emit_constraint(
        self,
        ctx: TickContext,
        *,
        node_id: str,
        state: MarketPrice,
        demand: DemandRecord,
        pressure: float,
    ) -> None:
        """Record every constraint that could have moved this node's price, and which one did.

        V1 reports a price and a stock and leaves a reader to guess which of the five constraints
        was binding — the merchant's stock, demand the stock could not meet, demand with no silver
        behind it, the trade links' capacity and cost, or the price bounds themselves. A single
        posted number cannot distinguish "the harvest was bad" from "nobody could pay" from "the
        ceiling was reached", and those are different histories.
        """
        reference = self._parameters.reference_price_tael_per_shi
        floor = reference * self._parameters.price_floor_ratio
        ceiling = reference * self._parameters.price_ceiling_ratio
        unclamped = self.price_from_inventory(
            inventory_shi=state.inventory_shi,
            local_need_shi=state.local_need_shi,
            demand_pressure=0.0 if self._parameters.demand_pressure_weight == 0.0 else pressure,
        )
        if local_need := state.local_need_shi:
            cover = state.inventory_shi / (local_need * self._parameters.target_cover_months)
        else:
            cover = 0.0
        # Trade: the best margin any neighbour offers, and the capacity the links could carry in.
        best_margin = 0.0
        inbound_capacity = 0.0
        cheapest_transport = 0.0
        if node_id in self._graphs.trade:
            for neighbour in self._graphs.trade.neighbors(node_id):
                edge = self._graphs.trade[node_id][neighbour]
                transport = self._parameters.transport_cost_tael_per_shi(float(edge["cost"]))
                margin = self._book.price(neighbour) - state.price_tael_per_shi - transport
                best_margin = max(best_margin, margin)
                if cheapest_transport == 0.0:
                    cheapest_transport = transport
                else:
                    cheapest_transport = min(cheapest_transport, transport)
                inbound_capacity += float(edge["capacity"]) * (
                    self._parameters.capacity_unit_shi_per_month
                    * self._disruption.capacity_multiplier(node_id, neighbour)
                )
        if state.local_need_shi <= 0.0:
            bound = "none"
        elif unclamped >= ceiling:
            bound = "ceiling"
        elif unclamped <= floor:
            bound = "floor"
        else:
            bound = "inventory"
        ctx.emit(
            MARKET_CONSTRAINT_EVENT,
            phase=self.phase.token,
            region=node_id,
            rule_version=MARKET_RULE_VERSION,
            trigger={
                "price_tael_per_shi": state.price_tael_per_shi,
                "price_unclamped_tael_per_shi": unclamped,
                "price_floor_tael_per_shi": floor,
                "price_ceiling_tael_per_shi": ceiling,
                "inventory_shi": state.inventory_shi,
                "local_need_shi": state.local_need_shi,
                "cover_of_target": cover,
                "wanted_shi": demand.wanted_shi,
                "unfilled_demand_shi": demand.unsold_shi,
                "unaffordable_demand_shi": demand.unaffordable_shi,
                "demand_pressure": pressure,
                "trade_inbound_capacity_shi": inbound_capacity,
                "trade_best_margin_tael_per_shi": best_margin,
                "transport_cost_tael_per_shi": cheapest_transport,
                "merchant_silver_tael": self._merchants.require(node_id).silver_tael,
            },
            outcome=bound,
        )

    def price_from_inventory(
        self, *, inventory_shi: float, local_need_shi: float, demand_pressure: float = 0.0
    ) -> float:
        """The declared price rule: scarcity relative to a target cover, with bounds.

        A node with no modelled demand — an external boundary node — posts the reference price;
        the model has no basis for a scarcity signal there.

        `demand_pressure` is the share of local need that was wanted and not served since the last
        pricing. The V1 rule ignores it entirely, and `demand_pressure_weight` is what turns that
        into a choice: at zero the posted price is exactly what V1 posts, so an arm that sets it to
        zero is a no-op that the phase's own detector must catch, and an arm that raises it is a
        different structure rather than a re-tuned number.
        """
        reference = self._parameters.reference_price_tael_per_shi
        if local_need_shi <= 0.0:
            return reference
        target = max(local_need_shi * self._parameters.target_cover_months, 1e-9)
        cover_ratio = target / max(inventory_shi, 1e-9)
        raw = float(reference * cover_ratio**self._parameters.price_elasticity)
        if self._parameters.demand_pressure_weight > 0.0 and demand_pressure > 0.0:
            multiplier = min(
                1.0 + self._parameters.demand_pressure_weight * demand_pressure,
                self._parameters.demand_pressure_cap,
            )
            raw *= multiplier
        floor = reference * self._parameters.price_floor_ratio
        ceiling = reference * self._parameters.price_ceiling_ratio
        return float(min(max(raw, floor), ceiling))


def _identity(actor: NodeBound) -> str:
    for attribute in ("cohort_id", "elite_id", "merchant_id", "government_id"):
        value = getattr(actor, attribute, None)
        if isinstance(value, str):
            return value
    return type(actor).__name__


def emit_merchant_event(
    ctx: TickContext, house: MerchantHouse, event: MerchantEvent, phase: TickPhase
) -> None:
    """Write one merchant transition into the run's event log."""
    ctx.emit(
        event.event_type,
        phase=phase.token,
        agent_id=house.merchant_id,
        region=house.node_id,
        rule_version=event.rule_version,
        trigger=event.trigger,
        outcome=event.outcome,
    )


def emit_elite_event(
    ctx: TickContext, house: LocalEliteAgent, event: EliteEvent, phase: TickPhase
) -> None:
    """Write one elite transition into the run's event log."""
    ctx.emit(
        event.event_type,
        phase=phase.token,
        agent_id=house.elite_id,
        region=house.node_id,
        rule_version=event.rule_version,
        trigger=event.trigger,
        outcome=event.outcome,
    )


def trade_edges(graphs: SpatialGraphs) -> Sequence[tuple[str, str]]:
    """Undirected trade links in canonical order."""
    return tuple(
        (origin, destination) if origin <= destination else (destination, origin)
        for origin, destination in (tuple(sorted(edge)) for edge in graphs.trade.edges)
    )
