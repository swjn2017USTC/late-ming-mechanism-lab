"""Migration: the coping step that finally moves somebody.

P03 built the coping ladder and stopped one rung short: it decided which cohorts *could* leave and
moved nobody. This system moves them. Three movements, all declared arithmetic over the distress and
the prices the rest of the model has already produced:

```text
permanent   eligible households leave for good, carrying people, food, silver and movable
            property, abandoning the land they were working
temporary   adults leave for a bounded term to eat where grain can still be bought, paid for from
            the cohort's silver, and come home when the term ends or the money runs out
exit        a destination outside the modelled region takes movers out of the model entirely,
            logged as an outflow the way a dispersed deserter is
```

Two rules decide everything else. **Who may move** is what P03 already recorded as eligible from the
measured 12-month unmet share, so migration cannot become an independent opinion about distress.
**Where they go** is the reachable node with the lowest posted grain price, ties broken by node id:
one criterion, no preferences about kin, land or safety, and therefore nothing that could smuggle in
a narrative the evidence does not support.

Costs and limits are physical. A move costs silver per household (and per adult for a season away),
is bounded by the migration edge's declared capacity, loses a declared share of what the movers
carry to the road (the edge's own risk, scaled), and can never take more from a cohort than it holds
or leave it with nothing. Every movement is double-entered: the origin's loss is the destination's
gain, and what leaves the modelled region is an outflow with a name.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from typing import Final

from late_ming_lab.actors.households import (
    HouseholdCohortAgent,
    HouseholdPopulation,
    emit_cohort_event,
)
from late_ming_lab.actors.merchants import MerchantLayer
from late_ming_lab.core.tick import (
    RESOURCE_CLIMATE,
    RESOURCE_COHORT_ADULTS,
    RESOURCE_COHORT_ASSETS,
    RESOURCE_COHORT_GRAIN,
    RESOURCE_COHORT_HOUSEHOLDS,
    RESOURCE_COHORT_LAND,
    RESOURCE_COHORT_SILVER,
    RESOURCE_DISTRESS_WINDOW,
    RESOURCE_MARKET_PRICE,
    RESOURCE_MERCHANT_STOCK,
    RESOURCE_MIGRANTS,
    TickContext,
    TickPhase,
)
from late_ming_lab.evidence.parameters import HouseholdParameters, MigrationParameters
from late_ming_lab.networks.edges import GraphKind
from late_ming_lab.networks.graphs import SpatialGraphs
from late_ming_lab.networks.nodes import ExternalRole, NodeKind
from late_ming_lab.systems.markets import LocalGrainMarket, MarketBook

MIGRATION_RULE_VERSION: Final[str] = "migration-v1"
TEMPORARY_RULE_VERSION: Final[str] = "temporary-migration-v1"

#: Events this system writes; the analysis layer reads them by name.
DEPARTURE_EVENT: Final[str] = "MIGRATION_DEPARTURE"
ARRIVAL_EVENT: Final[str] = "MIGRATION_ARRIVAL"
TRANSIT_EVENT: Final[str] = "MIGRATION_TRANSIT"
SETTLEMENT_EVENT: Final[str] = "MIGRATION_SETTLEMENT"
EXIT_EVENT: Final[str] = "MIGRATION_EXIT"
TEMPORARY_EVENT: Final[str] = "TEMPORARY_MIGRATION"
RETURN_EVENT: Final[str] = "TEMPORARY_RETURN"
MIGRANT_CONSUMPTION_EVENT: Final[str] = "MIGRANT_CONSUMPTION"

#: A cohort is never emptied by migration in this phase: the last household stays.
MINIMUM_HOUSEHOLDS_KEPT: Final[float] = 1.0


@dataclass(frozen=True, slots=True)
class MigrantGroup:
    """Adults of one cohort who are away for a term, and where they are eating.

    A group is a holding account, not an actor with a balance sheet: its adults left the cohort's
    books through a logged transition and re-enter through another. It exists so that a season away
    is visible, bounded and reversible rather than a silent adjustment to a cohort's size.
    """

    cohort_id: str
    origin_node: str
    destination_node: str
    adults: float
    departed_tick: int
    return_tick: int
    subsistence_paid_tael: float = 0.0
    grain_eaten_shi: float = 0.0


class MigrationBook:
    """The temporary migrants currently away, in a deterministic order."""

    def __init__(self) -> None:
        self._groups: dict[str, MigrantGroup] = {}

    def __iter__(self) -> Iterator[MigrantGroup]:
        return iter(self._groups[key] for key in sorted(self._groups))

    def __len__(self) -> int:
        return len(self._groups)

    def at(self, cohort_id: str) -> MigrantGroup | None:
        return self._groups.get(cohort_id)

    def add(self, group: MigrantGroup) -> None:
        if group.cohort_id in self._groups:
            raise ValueError(f"{group.cohort_id} already has temporary migrants away")
        self._groups[group.cohort_id] = group

    def update(self, group: MigrantGroup) -> None:
        self._groups[group.cohort_id] = group

    def remove(self, cohort_id: str) -> MigrantGroup:
        try:
            return self._groups.pop(cohort_id)
        except KeyError as error:
            raise KeyError(f"no temporary migrants recorded for {cohort_id!r}") from error

    @property
    def total_adults(self) -> float:
        return sum(group.adults for group in self._groups.values())


@dataclass(frozen=True, slots=True)
class MigrantBuyer:
    """A node-bound identity for a group of migrants, so a local market can serve them.

    The market layer sells only to a counterparty that belongs to its own node, and migrants belong
    to the node they are standing in while they are away. They hold no balance sheet of their own —
    their cohort pays and the grain is eaten where it is bought — so this is an identity, not an
    actor.
    """

    node_id: str
    cohort_id: str


class MigrationSystem:
    """Tick phase 09: seasonal absence first, then households that leave for good."""

    name: str = "migration"
    phase: TickPhase = TickPhase.MIGRATION
    reads: frozenset[str] = frozenset(
        {
            RESOURCE_CLIMATE,
            RESOURCE_DISTRESS_WINDOW,
            RESOURCE_MARKET_PRICE,
            RESOURCE_MERCHANT_STOCK,
            RESOURCE_COHORT_GRAIN,
            RESOURCE_COHORT_SILVER,
            RESOURCE_COHORT_HOUSEHOLDS,
            RESOURCE_COHORT_ADULTS,
            RESOURCE_COHORT_ASSETS,
            RESOURCE_COHORT_LAND,
        }
    )
    writes: frozenset[str] = frozenset(
        {
            RESOURCE_COHORT_HOUSEHOLDS,
            RESOURCE_COHORT_ADULTS,
            RESOURCE_COHORT_GRAIN,
            RESOURCE_COHORT_SILVER,
            RESOURCE_COHORT_ASSETS,
            RESOURCE_COHORT_LAND,
            RESOURCE_MIGRANTS,
        }
    )

    def __init__(
        self,
        *,
        graphs: SpatialGraphs,
        population: HouseholdPopulation,
        merchants: MerchantLayer,
        book: MarketBook,
        parameters: MigrationParameters,
        household_parameters: HouseholdParameters,
    ) -> None:
        self._graphs = graphs
        self._population = population
        self._merchants = merchants
        self._book = book
        self._parameters = parameters
        self._household_parameters = household_parameters
        self._migrants = MigrationBook()
        self._priced_nodes = frozenset(state.node_id for state in book.states())
        self._markets: Mapping[str, LocalGrainMarket] = {
            node_id: LocalGrainMarket(node_id=node_id, book=book, merchants=merchants)
            for node_id in sorted(self._priced_nodes)
        }

    @property
    def migrants(self) -> MigrationBook:
        return self._migrants

    def step(self, ctx: TickContext) -> None:
        self._bring_migrants_home(ctx)
        self._permanent_migration(ctx)
        self._temporary_migration(ctx)
        self._population.check_invariants()

    # ------------------------------------------------------------------ destinations

    def destination_for(self, origin: str) -> str | None:
        """Where a household leaving ``origin`` would go, by one declared comparison.

        The rule, in order:

        1. **A county in reach is the first choice**, and among those the one with the lowest
           posted grain price, ties broken by node id.
        2. **Leaving the region is the last resort**: it happens only when no reachable county
           offers a lower price than the household's own node, and a migration exit is in reach.
        3. If nothing in reach is cheaper and no exit exists, movers still take the least bad
           county rather than staying put.

        The order matters because boundary nodes post the reference price and never respond to
        scarcity — left to a plain price comparison, the region would empty into the exits long
        before any of its own counties were tried.
        """
        if origin not in self._graphs.migration:
            return None
        counties: list[tuple[float, str]] = []
        exits: list[tuple[float, str]] = []
        for neighbour in sorted(self._graphs.migration.neighbors(origin)):
            if neighbour not in self._priced_nodes:
                continue
            candidate = (self._book.price(neighbour), neighbour)
            (exits if self.is_exit(neighbour) else counties).append(candidate)
        own_price = self._book.price(origin)
        better_counties = [candidate for candidate in counties if candidate[0] < own_price]
        if better_counties:
            return min(better_counties)[1]
        if exits:
            return min(exits)[1]
        return min(counties)[1] if counties else None

    def is_exit(self, node_id: str) -> bool:
        """True when a node is outside the modelled region: movers there leave the model."""
        node = self._graphs.nodes.by_id.get(node_id)
        if node is None:
            return True
        return node.kind is NodeKind.EXTERNAL and ExternalRole.MIGRATION_EXIT in node.external_roles

    def edge_capacity(self, source: str, target: str) -> float:
        data = self._graphs.migration.get_edge_data(source, target) or {}
        return float(data.get("capacity", 0.0))

    def edge_risk(self, source: str, target: str) -> float:
        data = self._graphs.migration.get_edge_data(source, target) or {}
        return float(data.get("risk", 0.0))

    def migration_cost(self, source: str, target: str) -> float:
        return self._graphs.cost(GraphKind.MIGRATION, source, target)

    # ------------------------------------------------------------------ temporary

    def _temporary_migration(self, ctx: TickContext) -> None:
        """Send a share of an eligible cohort's adults away for a bounded term."""
        parameters = self._parameters
        for cohort in self._population:
            if not cohort.temporary_migration_eligible or self._migrants.at(cohort.cohort_id):
                continue
            destination = self.destination_for(cohort.node_id)
            if destination is None:
                continue
            wanted = min(
                cohort.adults, cohort.adults * parameters.temporary_share_of_adults_per_month
            )
            if wanted < 1.0:
                continue
            cost = wanted * parameters.cost_tael_per_adult
            if cost > cohort.silver_tael:
                continue
            group = MigrantGroup(
                cohort_id=cohort.cohort_id,
                origin_node=cohort.node_id,
                destination_node=destination,
                adults=wanted,
                departed_tick=ctx.tick,
                return_tick=ctx.tick + parameters.temporary_term_months,
            )
            emit_cohort_event(
                ctx,
                cohort,
                cohort.send_migrant_adults(
                    adults=wanted, destination=destination, rule_version=TEMPORARY_RULE_VERSION
                ),
                self.phase,
            )
            if cost > 0.0:
                emit_cohort_event(
                    ctx,
                    cohort,
                    cohort.record_migrant_subsistence(
                        silver_tael=cost,
                        destination=destination,
                        rule_version=TEMPORARY_RULE_VERSION,
                    ),
                    self.phase,
                )
            self._migrants.add(replace(group, subsistence_paid_tael=cost))
            ctx.emit(
                TEMPORARY_EVENT,
                phase=self.phase.token,
                agent_id=cohort.cohort_id,
                region=cohort.node_id,
                rule_version=TEMPORARY_RULE_VERSION,
                trigger={
                    "adults_away": wanted,
                    "travel_cost_tael": cost,
                    "origin_price_tael_per_shi": self._book.price(cohort.node_id),
                    "destination_price_tael_per_shi": self._book.price(destination),
                    "return_tick": float(group.return_tick),
                },
                outcome=f"away-to:{destination}",
            )

    def _bring_migrants_home(self, ctx: TickContext) -> None:
        """Feed the away adults where they are, and bring them home when the term or the money ends.

        The food is bought at the destination node's market with the origin cohort's silver, which
        is the point of the move: grain that cannot be had at home can sometimes be bought where the
        harvest was not as bad. The per-month budget is the same share of the cohort's silver as the
        share of its adults that are away, so a poor cohort sends fewer adults and for less.
        """
        for group in tuple(self._migrants):
            cohort = self._population.require(group.cohort_id)
            need = self._subsistence_need(group)
            wanted = max(0.0, need - group.grain_eaten_shi)
            budget = cohort.silver_tael * self._parameters.temporary_share_of_adults_per_month
            market = self._markets.get(group.destination_node)
            bought = 0.0
            spent = 0.0
            if wanted > 0.0 and budget > 0.0 and market is not None:
                outcome = market.buy_grain(
                    ctx,
                    MigrantBuyer(
                        node_id=group.destination_node, cohort_id=f"migrants:{group.cohort_id}"
                    ),
                    shi_wanted=wanted,
                    max_silver=budget,
                    phase=self.phase,
                )
                bought = outcome.quantity
                spent = outcome.value_tael
                if bought > 0.0:
                    emit_cohort_event(
                        ctx,
                        cohort,
                        cohort.record_migrant_subsistence(
                            silver_tael=spent,
                            destination=group.destination_node,
                            rule_version=TEMPORARY_RULE_VERSION,
                        ),
                        self.phase,
                    )
                    ctx.emit(
                        MIGRANT_CONSUMPTION_EVENT,
                        phase=self.phase.token,
                        agent_id=group.cohort_id,
                        region=group.destination_node,
                        rule_version=TEMPORARY_RULE_VERSION,
                        trigger={
                            "adults_away": group.adults,
                            "grain_eaten_shi": bought,
                            "silver_spent_tael": spent,
                            "price_tael_per_shi": market.price_tael_per_shi,
                        },
                        outcome="fed-at-destination",
                    )
            if wanted > 0.0 and bought <= 0.0:
                ctx.emit(
                    MIGRANT_CONSUMPTION_EVENT,
                    phase=self.phase.token,
                    agent_id=group.cohort_id,
                    region=group.destination_node,
                    rule_version=TEMPORARY_RULE_VERSION,
                    trigger={
                        "adults_away": group.adults,
                        "grain_eaten_shi": 0.0,
                        "silver_spent_tael": 0.0,
                        "price_tael_per_shi": market.price_tael_per_shi if market else 0.0,
                    },
                    outcome="unfed",
                )
            updated = replace(
                group,
                subsistence_paid_tael=group.subsistence_paid_tael + spent,
                grain_eaten_shi=group.grain_eaten_shi + bought,
            )
            self._migrants.update(updated)
            term_over = ctx.tick >= group.return_tick
            out_of_money = bought <= 0.0 and cohort.silver_tael <= 0.0
            if term_over or out_of_money:
                self._migrants.remove(group.cohort_id)
                emit_cohort_event(
                    ctx,
                    cohort,
                    cohort.receive_migrant_adults(
                        adults=updated.adults,
                        source=group.destination_node,
                        rule_version=TEMPORARY_RULE_VERSION,
                    ),
                    self.phase,
                )
                ctx.emit(
                    RETURN_EVENT,
                    phase=self.phase.token,
                    agent_id=cohort.cohort_id,
                    region=cohort.node_id,
                    rule_version=TEMPORARY_RULE_VERSION,
                    trigger={
                        "adults_returned": updated.adults,
                        "subsistence_paid_tael": updated.subsistence_paid_tael,
                        "grain_eaten_shi": updated.grain_eaten_shi,
                        "months_away": float(ctx.tick - group.departed_tick + 1),
                    },
                    outcome="term-ended" if term_over else "out-of-money",
                )

    def _subsistence_need(self, group: MigrantGroup) -> float:
        """What a group away from home eats: its adults against the household layer's own floor."""
        return group.adults * self._household_parameters.subsistence_grain_per_adult_month_shi

    # ------------------------------------------------------------------ permanent

    def _permanent_migration(self, ctx: TickContext) -> None:
        """Move eligible households for good, within the region or out of it."""
        parameters = self._parameters
        for cohort in self._population:
            if not cohort.permanent_migration_eligible:
                continue
            destination = self.destination_for(cohort.node_id)
            if destination is None:
                continue
            if (
                not self.is_exit(destination)
                and self._population.by_id.get(self._arrival_cohort_id(cohort, destination)) is None
            ):
                # Nobody there can receive this class of household. The move is refused rather
                # than booked as a regional exit: staying is the honest outcome.
                continue
            share = parameters.permanent_share_of_households_per_month
            keepable = max(0.0, cohort.households - MINIMUM_HOUSEHOLDS_KEPT)
            # The edge's capacity is already a monthly household flow (P02 declares it in
            # households per month), so it is a ceiling on the move, not something to scale again.
            capacity = self.edge_capacity(cohort.node_id, destination)
            movers = min(cohort.households * share, capacity, keepable)
            if movers < parameters.minimum_households_to_move:
                continue
            # A household can only leave if it can pay its own way: movers carry their share of
            # the cohort's silver, so the gate is silver per household against the cost of a move.
            if cohort.silver_tael / cohort.households < parameters.cost_tael_per_household:
                continue
            self._move_households(ctx, cohort, destination, movers)

    def _move_households(
        self,
        ctx: TickContext,
        cohort: HouseholdCohortAgent,
        destination: str,
        movers: float,
    ) -> None:
        """Take movers out of the origin, and put what survives the road where they arrive."""
        parameters = self._parameters
        share = movers / cohort.households
        risk = min(1.0, self.edge_risk(cohort.node_id, destination) * parameters.transit_loss_share)
        travel_cost = movers * parameters.cost_tael_per_household

        taken_grain = cohort.grain_shi * share
        taken_silver = cohort.silver_tael * share
        taken_assets = cohort.movable_assets_tael * share
        adults = cohort.adults * share
        arrival_grain = taken_grain * (1.0 - risk)
        arrival_assets = taken_assets * (1.0 - risk)
        arrival_silver = max(0.0, taken_silver - travel_cost) * (1.0 - risk)

        emit_cohort_event(
            ctx,
            cohort,
            cohort.migrate_households_out(
                households=movers,
                adults=adults,
                grain_shi=taken_grain,
                silver_tael=taken_silver,
                movable_assets_tael=taken_assets,
                land_abandoned_mu=cohort.land_mu * share,
                destination=destination,
                rule_version=MIGRATION_RULE_VERSION,
            ),
            self.phase,
        )
        ctx.emit(
            TRANSIT_EVENT,
            phase=self.phase.token,
            agent_id=cohort.cohort_id,
            region=cohort.node_id,
            rule_version=MIGRATION_RULE_VERSION,
            trigger={
                "households_moved": movers,
                "adults_moved": adults,
                "grain_taken_shi": taken_grain,
                "grain_arrived_shi": arrival_grain,
                "grain_lost_shi": taken_grain - arrival_grain,
                "silver_taken_tael": taken_silver,
                "silver_arrived_tael": arrival_silver,
                "silver_spent_or_lost_tael": taken_silver - arrival_silver,
                "assets_taken_tael": taken_assets,
                "assets_arrived_tael": arrival_assets,
                "travel_cost_tael": travel_cost,
                "transit_risk": risk,
            },
            outcome=f"in-transit-to:{destination}",
        )

        arrival = self._population.by_id.get(self._arrival_cohort_id(cohort, destination))
        if self.is_exit(destination) or arrival is None:
            ctx.emit(
                EXIT_EVENT,
                phase=self.phase.token,
                agent_id=cohort.cohort_id,
                region=cohort.node_id,
                rule_version=MIGRATION_RULE_VERSION,
                trigger={
                    "households_exited": movers,
                    "adults_exited": adults,
                    "grain_carried_shi": arrival_grain,
                    "silver_carried_tael": arrival_silver,
                    "assets_carried_tael": arrival_assets,
                },
                outcome=f"exited-to:{destination}",
            )
            return
        emit_cohort_event(
            ctx,
            arrival,
            arrival.receive_migrant_households(
                households=movers,
                adults=adults,
                grain_shi=arrival_grain,
                silver_tael=arrival_silver,
                movable_assets_tael=arrival_assets,
                source=cohort.node_id,
                rule_version=MIGRATION_RULE_VERSION,
            ),
            self.phase,
        )
        ctx.emit(
            SETTLEMENT_EVENT,
            phase=self.phase.token,
            agent_id=cohort.cohort_id,
            region=destination,
            rule_version=MIGRATION_RULE_VERSION,
            trigger={
                "households_settled": movers,
                "adults_settled": adults,
                "origin_households_left": cohort.households,
                "arrival_households": arrival.households,
                "land_per_household_arrival_mu": arrival.land_per_household_mu,
            },
            outcome=f"settled-at:{destination}",
        )

    def _arrival_cohort_id(self, cohort: HouseholdCohortAgent, destination: str) -> str:
        """Movers join the cohort of their own class at the destination, if there is one."""
        return f"{destination}:{cohort.cohort_class.value}"


__all__ = [
    "ARRIVAL_EVENT",
    "DEPARTURE_EVENT",
    "EXIT_EVENT",
    "MIGRANT_CONSUMPTION_EVENT",
    "MIGRATION_RULE_VERSION",
    "RETURN_EVENT",
    "SETTLEMENT_EVENT",
    "TEMPORARY_EVENT",
    "TEMPORARY_RULE_VERSION",
    "TRANSIT_EVENT",
    "MigrantBuyer",
    "MigrantGroup",
    "MigrationBook",
    "MigrationSystem",
]
