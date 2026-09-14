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

A tick in which nobody left writes none of those events, so the rules that refused a move would be
invisible. Every cohort the phase considers therefore also gets one **gate row** per tick, naming
the gate that decided its tick and the numbers that gate compared: the destination in reach, the
road's capacity and risk, and the cohort's silver per household against the declared cost of a
move. The rows change nothing — they are written after every rule has run, and report what it did.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from typing import Final

from late_ming_lab.actors.households import (
    CopingStage,
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
#: One row per cohort per tick, naming the gate that decided it, moved or not.
MIGRATION_GATE_EVENT: Final[str] = "MIGRATION_GATE"

#: A cohort is never emptied by migration in this phase: the last household stays.
MINIMUM_HOUSEHOLDS_KEPT: Final[float] = 1.0

#: The gates a migration tick can name: the outcomes of :data:`MIGRATION_GATE_EVENT`, in the
#: precedence ``MigrationSystem.step`` applies to them.
GATE_MOVED: Final[str] = "moved"
GATE_NO_DESTINATION: Final[str] = "no-destination"
GATE_NO_RECEIVING_COHORT: Final[str] = "no-receiving-cohort"
GATE_CAPACITY: Final[str] = "capacity"
GATE_SILVER: Final[str] = "silver"
GATE_BELOW_MINIMUM: Final[str] = "below-minimum"
GATE_RETURNED: Final[str] = "returned"
GATE_TEMPORARY: Final[str] = "temporary"
GATE_NOT_ELIGIBLE: Final[str] = "not-eligible"

#: Every outcome a gate row may carry, and the vocabulary the analysis layer reads by name.
GATE_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        GATE_MOVED,
        GATE_NO_DESTINATION,
        GATE_NO_RECEIVING_COHORT,
        GATE_CAPACITY,
        GATE_SILVER,
        GATE_BELOW_MINIMUM,
        GATE_RETURNED,
        GATE_TEMPORARY,
        GATE_NOT_ELIGIBLE,
    }
)


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


@dataclass(frozen=True, slots=True)
class MigrationGate:
    """What one migration tick decided for one cohort, and the road it was decided against.

    ``outcome`` names the gate, from :data:`GATE_OUTCOMES`. ``destination`` is the node the rules
    looked at, or the node a cohort's adults are already away at; it is absent when nothing was in
    reach. ``movers_households`` is what actually left, so it is zero on every row that is not a
    permanent move — a season away moves adults, and a refusal moves nobody.
    """

    outcome: str
    destination: str | None = None
    movers_households: float = 0.0


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
        returned = self._bring_migrants_home(ctx)
        permanent = self._permanent_migration(ctx)
        temporary = self._temporary_migration(ctx)
        self._population.check_invariants()
        # Every cohort gets exactly one gate row per tick, naming the first rule that decided
        # anything for it. The precedence, in the order the phase applies the rules:
        #
        #   1. moved                 the permanent rule sent households this tick
        #   2. no-destination        ... and found no destination in reach
        #   3. no-receiving-cohort   ... whose destination has no cohort of the movers' class
        #   4. capacity              ... whose road capacity held the flow under the minimum
        #   5. silver                ... whose households hold less than a move costs
        #   6. below-minimum         ... whose declared share is under the minimum to move
        #   7. returned              the cohort's away adults came home this tick
        #   8. temporary             the temporary rule sent its adults away, or left them away
        #   9. not-eligible          neither eligibility test passed, so no rule applied
        #
        # The permanent verdict outranks the seasonal ones because a departure is final where a
        # season away is not, and the temporary one outranks the fallback because a cohort whose
        # adults are away *is* being migrated by it.
        for cohort in self._population:
            gate = (
                permanent.get(cohort.cohort_id)
                or returned.get(cohort.cohort_id)
                or temporary.get(cohort.cohort_id)
                or MigrationGate(GATE_NOT_ELIGIBLE)
            )
            self._emit_gate(ctx, cohort, gate)

    def _emit_gate(
        self, ctx: TickContext, cohort: HouseholdCohortAgent, gate: MigrationGate
    ) -> None:
        """Write the tick's verdict for one cohort, whether or not it moved anything.

        The destination is the node the deciding rule used, and the edge figures are that road's;
        they are zero when nothing was in reach. ``migration_cost_tael`` is the declared cost of a
        move per household, which is the number the silver gate is measured against: a refusal
        spends nothing, so a row reporting what it spent would say nothing about why it was refused.
        The row carries the phase's own rule version; a rule that acted names itself in its events.
        """
        destination = gate.destination
        ctx.emit(
            MIGRATION_GATE_EVENT,
            phase=self.phase.token,
            agent_id=cohort.cohort_id,
            region=cohort.node_id,
            rule_version=MIGRATION_RULE_VERSION,
            trigger={
                "households": cohort.households,
                "adults": cohort.adults,
                # A cohort with no households has no per-household figure, and cannot reach the
                # permanent rule's own silver gate either.
                "silver_per_household": (
                    cohort.silver_tael / cohort.households if cohort.households > 0.0 else 0.0
                ),
                "eligible_permanent": 1.0 if cohort.permanent_migration_eligible else 0.0,
                "destination_is_exit": (
                    1.0 if destination is not None and self.is_exit(destination) else 0.0
                ),
                "edge_capacity_households": (
                    self.edge_capacity(cohort.node_id, destination)
                    if destination is not None
                    else 0.0
                ),
                "edge_risk": (
                    self.edge_risk(cohort.node_id, destination) if destination is not None else 0.0
                ),
                "migration_cost_tael": self._parameters.cost_tael_per_household,
                "movers_households": gate.movers_households,
            },
            outcome=gate.outcome,
        )

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

    def _temporary_migration(self, ctx: TickContext) -> dict[str, MigrationGate]:
        """Send a share of an eligible cohort's adults away for a bounded term.

        Returns one verdict for every cohort the rule looked at: an ineligible cohort is not its
        to decide, and is left for the fallback in :meth:`step`.
        """
        gates: dict[str, MigrationGate] = {}
        for cohort in self._population:
            gate = self._temporary_gate(ctx, cohort)
            if gate is not None:
                gates[cohort.cohort_id] = gate
        return gates

    def _temporary_gate(
        self, ctx: TickContext, cohort: HouseholdCohortAgent
    ) -> MigrationGate | None:
        """The seasonal rule for one cohort, or ``None`` when the cohort may not send anybody."""
        if not cohort.temporary_migration_eligible:
            return None
        parameters = self._parameters
        away = self._migrants.at(cohort.cohort_id)
        if away is not None:
            # Already away on an earlier tick's term: the rule has nothing to decide, and the
            # adults are still at the node that term sent them to.
            return MigrationGate(GATE_TEMPORARY, destination=away.destination_node)
        destination = self.destination_for(cohort.node_id)
        if destination is None:
            return MigrationGate(GATE_NO_DESTINATION)
        wanted = min(cohort.adults, cohort.adults * parameters.temporary_share_of_adults_per_month)
        if wanted < 1.0:
            return MigrationGate(GATE_BELOW_MINIMUM, destination=destination)
        cost = wanted * parameters.cost_tael_per_adult
        if cost > cohort.silver_tael:
            return MigrationGate(GATE_SILVER, destination=destination)
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
        return MigrationGate(GATE_TEMPORARY, destination=destination)

    def _bring_migrants_home(self, ctx: TickContext) -> dict[str, MigrationGate]:
        """Feed the away adults where they are, and bring them home when the term or the money ends.

        The food is bought at the destination node's market with the origin cohort's silver, which
        is the point of the move: grain that cannot be had at home can sometimes be bought where the
        harvest was not as bad. The per-month budget is the same share of the cohort's silver as the
        share of its adults that are away, so a poor cohort sends fewer adults and for less.

        Returns a verdict for each cohort whose term ended this tick, and nothing for one whose
        adults are still away: staying away is not a decision this method made.
        """
        returned: dict[str, MigrationGate] = {}
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
                returned[cohort.cohort_id] = MigrationGate(
                    GATE_RETURNED, destination=group.destination_node
                )
        return returned

    def _subsistence_need(self, group: MigrantGroup) -> float:
        """What a group away from home eats: its adults against the household layer's own floor."""
        return group.adults * self._household_parameters.subsistence_grain_per_adult_month_shi

    # ------------------------------------------------------------------ permanent

    def _permanent_migration(self, ctx: TickContext) -> dict[str, MigrationGate]:
        """Move households for good, within the region or out of it.

        Two routes run here. The first is V1's: a cohort whose rolling unmet ratio has passed the
        eligibility line, and which holds the cost of the move in silver. The second is V2-P04's
        declared distress route, which is a no-op at its neutral parameter values and is what the
        historical core's failure points at: on that run the first route produced six departures and
        no regional exit in twenty years while four fifths of the cohorts ended destitute.

        Returns one verdict per cohort the rules looked at, the distress route's verdict taking
        precedence when it actually moved someone.
        """
        gates: dict[str, MigrationGate] = {}
        for cohort in self._population:
            gate = self._permanent_gate(ctx, cohort)
            distress = self._destitution_gate(ctx, cohort)
            chosen = distress or gate
            if chosen is not None:
                gates[cohort.cohort_id] = chosen
        return gates

    def _destitution_gate(
        self, ctx: TickContext, cohort: HouseholdCohortAgent
    ) -> MigrationGate | None:
        """The distress route: a destitute cohort may leave without eligibility or silver.

        `destitution_departure_share` is the share of a destitute cohort's households that may leave
        each month, and `destitution_exit_share` is the part of that taking the out-of-region road
        rather than the nearest cheaper county. Both are zero in the V1 structure, and at zero this
        method returns before touching anything: the ablation arm is then the reference run exactly,
        which is a property of the code rather than a claim about it.

        The exit leg is tried first because V1's routing sends a mover to the cheapest reachable
        county and treats an exit as a last resort, so a famine covering every county — the case the
        record describes — could never produce a regional outflow through such a route.

        Both legs go through :meth:`_move_households`, so the destination's declared monthly
        capacity and the edge's transit loss bound them as they bound any other move, and a cohort
        that cannot be received stays put.
        """
        parameters = self._parameters
        if parameters.destitution_departure_share <= 0.0:
            return None
        if cohort.coping_stage is not CopingStage.DESTITUTE:
            return None
        if cohort.households <= MINIMUM_HOUSEHOLDS_KEPT:
            return None
        moved = 0.0
        destination: str | None = None
        exit_destination = self._exit_destination(cohort.node_id)
        exit_part = (
            parameters.destitution_departure_share * parameters.destitution_exit_share
            if exit_destination is not None
            else 0.0
        )
        if exit_destination is not None and exit_part > 0.0:
            taken = self._move_at_most(ctx, cohort, exit_destination, exit_part)
            if taken > 0.0:
                moved += taken
                destination = exit_destination
        in_region_part = parameters.destitution_departure_share - exit_part
        if in_region_part > 0.0:
            target = self.destination_for(cohort.node_id)
            receivable = target is not None and (
                self.is_exit(target)
                or self._population.by_id.get(self._arrival_cohort_id(cohort, target)) is not None
            )
            if target is not None and receivable:
                taken = self._move_at_most(ctx, cohort, target, in_region_part)
                if taken > 0.0:
                    moved += taken
                    destination = destination or target
        if destination is None:
            return None
        return MigrationGate(GATE_MOVED, destination=destination, movers_households=moved)

    def _move_at_most(
        self,
        ctx: TickContext,
        cohort: HouseholdCohortAgent,
        destination: str,
        share: float,
    ) -> float:
        """Move up to a share of a cohort, bounded by the road's capacity; 0.0 if nothing moved."""
        keepable = max(0.0, cohort.households - MINIMUM_HOUSEHOLDS_KEPT)
        capacity = self.edge_capacity(cohort.node_id, destination)
        movers = min(cohort.households * share, capacity, keepable)
        if movers < self._parameters.minimum_households_to_move:
            return 0.0
        self._move_households(ctx, cohort, destination, movers)
        return movers

    def _exit_destination(self, origin: str) -> str | None:
        """The declared migration exit in reach, or None when the region has none."""
        if origin not in self._graphs.migration:
            return None
        exits = [
            node for node in sorted(self._graphs.migration.neighbors(origin)) if self.is_exit(node)
        ]
        return exits[0] if exits else None

    def _permanent_gate(
        self, ctx: TickContext, cohort: HouseholdCohortAgent
    ) -> MigrationGate | None:
        """The permanent rule for one cohort: which households left, or which gate refused them."""
        if not cohort.permanent_migration_eligible:
            return None
        parameters = self._parameters
        destination = self.destination_for(cohort.node_id)
        if destination is None:
            return MigrationGate(GATE_NO_DESTINATION)
        if (
            not self.is_exit(destination)
            and self._population.by_id.get(self._arrival_cohort_id(cohort, destination)) is None
        ):
            # Nobody there can receive this class of household. The move is refused rather
            # than booked as a regional exit: staying is the honest outcome.
            return MigrationGate(GATE_NO_RECEIVING_COHORT, destination=destination)
        share = parameters.permanent_share_of_households_per_month
        keepable = max(0.0, cohort.households - MINIMUM_HOUSEHOLDS_KEPT)
        # The edge's capacity is already a monthly household flow (P02 declares it in
        # households per month), so it is a ceiling on the move, not something to scale again.
        capacity = self.edge_capacity(cohort.node_id, destination)
        movers = min(cohort.households * share, capacity, keepable)
        if movers < parameters.minimum_households_to_move:
            # The road's capacity refused the move only when it is the ceiling that held the flow
            # under the minimum; when the cohort's own share did, the minimum is what refused it.
            refused_by_capacity = capacity < min(cohort.households * share, keepable)
            outcome = GATE_CAPACITY if refused_by_capacity else GATE_BELOW_MINIMUM
            return MigrationGate(outcome, destination=destination)
        # A household can only leave if it can pay its own way: movers carry their share of
        # the cohort's silver, so the gate is silver per household against the cost of a move.
        if cohort.silver_tael / cohort.households < parameters.cost_tael_per_household:
            return MigrationGate(GATE_SILVER, destination=destination)
        self._move_households(ctx, cohort, destination, movers)
        return MigrationGate(GATE_MOVED, destination=destination, movers_households=movers)

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
    "GATE_BELOW_MINIMUM",
    "GATE_CAPACITY",
    "GATE_MOVED",
    "GATE_NOT_ELIGIBLE",
    "GATE_NO_DESTINATION",
    "GATE_NO_RECEIVING_COHORT",
    "GATE_OUTCOMES",
    "GATE_RETURNED",
    "GATE_SILVER",
    "GATE_TEMPORARY",
    "MIGRANT_CONSUMPTION_EVENT",
    "MIGRATION_GATE_EVENT",
    "MIGRATION_RULE_VERSION",
    "RETURN_EVENT",
    "SETTLEMENT_EVENT",
    "TEMPORARY_EVENT",
    "TEMPORARY_RULE_VERSION",
    "TRANSIT_EVENT",
    "MigrantBuyer",
    "MigrantGroup",
    "MigrationBook",
    "MigrationGate",
    "MigrationSystem",
]
