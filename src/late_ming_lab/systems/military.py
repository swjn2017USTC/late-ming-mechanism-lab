"""Military finance, desertion, band recruitment, band action, violence and bookkeeping.

Six systems on the phases the plan assigns them:

```text
10 military finance   pay what the treasury can, feed the garrison, move morale and cohesion
11 desertion          a declared probability, and a declared destination for everyone who leaves
12 band recruitment   the recruit pool, garrison levies, band levies and band formation
13 band action        bands eat, move toward food, and take grain and goods from the land
14 violence           suppression, dissolution, split and merge
16 bookkeeping        garrison and band state records, and the ledger check
```

Every rule is a declared arithmetic relation over measured quantities — arrears per soldier, food
per soldier, cohesion, size, the unmet share of the subsistence floor. Nothing here is a tactic, a
siege, an order of battle or a named leader, and no rule decides who "should" win: suppression and
raids are abstractions that move people, food and material between actors, each of which keeps its
own reconciled books and is charged against the same recruit pool.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from late_ming_lab.actors.elites import EliteLayer, emit_elite_event
from late_ming_lab.actors.government import CountyGovernment, GovernmentLayer
from late_ming_lab.actors.households import (
    HouseholdCohortAgent,
    HouseholdPopulation,
    emit_cohort_event,
)
from late_ming_lab.actors.merchants import MerchantLayer
from late_ming_lab.actors.military import (
    BAND_RULE_VERSION,
    MILITARY_RULE_VERSION,
    ArmedBand,
    BandLayer,
    GovernmentMilitaryUnit,
    MilitaryEvent,
    MilitaryEventType,
    MilitaryLayer,
)
from late_ming_lab.core.tick import (
    RESOURCE_BAND_STANDING,
    RESOURCE_BAND_STORES,
    RESOURCE_BAND_TROOPS,
    RESOURCE_COHORT_ADULTS,
    RESOURCE_COHORT_ASSETS,
    RESOURCE_COHORT_GRAIN,
    RESOURCE_COUNTY_GRANARY,
    RESOURCE_COUNTY_TREASURY,
    RESOURCE_DISTRESS_WINDOW,
    RESOURCE_ELITE_GRAIN,
    RESOURCE_MARKET_PRICE,
    RESOURCE_MERCHANT_STOCK,
    RESOURCE_UNIT_PAY,
    RESOURCE_UNIT_STANDING,
    RESOURCE_UNIT_STORES,
    RESOURCE_UNIT_TROOPS,
    TickContext,
    TickPhase,
)
from late_ming_lab.evidence.parameters import BandParameters, MilitaryParameters
from late_ming_lab.networks.graphs import SpatialGraphs
from late_ming_lab.systems.fiscal import emit_government_event
from late_ming_lab.systems.markets import LocalGrainMarket, MarketBook

DESERTION_RULE_VERSION: Final[str] = "desertion-v1"
RECRUITMENT_RULE_VERSION: Final[str] = "recruitment-v1"
LEVY_RULE_VERSION: Final[str] = "levy-v1"
SUPPRESSION_RULE_VERSION: Final[str] = "suppression-v1"
SPLIT_RULE_VERSION: Final[str] = "split-v1"
MERGE_RULE_VERSION: Final[str] = "merge-v1"


def emit_military_event(
    ctx: TickContext, actor_id: str, node_id: str, event: MilitaryEvent, phase: TickPhase
) -> None:
    """Write one garrison or band transition into the run's event log."""
    ctx.emit(
        event.event_type.value,
        phase=phase.token,
        agent_id=actor_id,
        region=node_id,
        rule_version=event.rule_version,
        trigger=event.trigger,
        outcome=event.outcome,
    )


class DeserterPool:
    """Deserters who have left a garrison and not yet been organized, per node.

    Declared state rather than a hidden variable: the desertion system is the only writer, band
    formation is the only reader, and every movement in and out is logged. It exists because the
    plan's observable is *diffuse violence becoming organizational*: deserters gather before a band
    exists, and the pool is where they gather.
    """

    def __init__(self) -> None:
        self._by_node: dict[str, float] = {}

    def at(self, node_id: str) -> float:
        return self._by_node.get(node_id, 0.0)

    def add(self, node_id: str, troops: float) -> None:
        if troops <= 0.0:
            return
        self._by_node[node_id] = self.at(node_id) + troops

    def take(self, node_id: str, troops: float) -> float:
        """Take up to ``troops`` out of the pool; returns what was actually there."""
        taken = min(troops, self.at(node_id))
        remaining = self.at(node_id) - taken
        if remaining > 0.0:
            self._by_node[node_id] = remaining
        else:
            self._by_node.pop(node_id, None)
        return taken

    @property
    def total_troops(self) -> float:
        return sum(self._by_node.values())

    def nodes_with_deserters(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_node))


@dataclass(frozen=True, slots=True)
class RaidYield:
    """What one raid returned: grain, the arms it yielded, and the allowance that is left."""

    taken: float
    arms: float
    remaining: float


def _arms_capability(band: ArmedBand, parameters: BandParameters) -> float:
    """How well armed a band is, against the declared mark for a full complement."""
    return min(1.0, band.arms_per_member / parameters.arms_per_member_for_full_capability)


def suppression_reach(
    unit: GovernmentMilitaryUnit,
    band: ArmedBand,
    military_parameters: MilitaryParameters,
    band_parameters: BandParameters,
) -> float:
    """Members a garrison can reach in a band this month.

    Strength against size, discounted twice: by how embedded the band is locally, and by how well
    it is armed. One definition, used both by suppression and by a band deciding whether to move —
    a band must not flee a threat different from the one that actually removes its people.
    """
    return (
        unit.troops
        * military_parameters.suppression_effectiveness
        * (1.0 - band.network)
        * (
            1.0
            - _arms_capability(band, band_parameters)
            * military_parameters.suppression_arms_mitigation
        )
    )


def _form_band(
    layer: BandLayer,
    *,
    node_id: str,
    cohesion: float,
    network: float,
    access: tuple[str, ...] | None = None,
    mobility: float | None = None,
) -> ArmedBand:
    """Create a band with nothing in it; every member arrives through a logged inflow."""
    band = ArmedBand(
        band_id=layer.next_id(),
        node_id=node_id,
        troops=0.0,
        cohesion=cohesion,
        network=network,
        territorial_access=access or (node_id,),
        **({} if mobility is None else {"mobility": mobility}),
    )
    layer.add(band)
    return band


def _adopt(
    ctx: TickContext,
    band: ArmedBand,
    *,
    troops: float,
    source: str,
    phase: TickPhase,
    grain_shi: float = 0.0,
    arms_units: float = 0.0,
    rule_version: str = BAND_RULE_VERSION,
) -> None:
    """Fill a band from one named source, so every inflow has exactly one origin in the log."""
    if troops <= 0.0 and grain_shi <= 0.0 and arms_units <= 0.0:
        return
    emit_military_event(
        ctx,
        band.band_id,
        band.node_id,
        band.adopt(
            troops=troops,
            grain_shi=grain_shi,
            arms_units=arms_units,
            source=source,
            rule_version=rule_version,
        ),
        phase,
    )


class MilitaryFinanceSystem:
    """Tick phase 10: pay, rations, morale and cohesion.

    A garrison eats its own stores first and the county granary second; it is paid from the county
    treasury up to the declared share of that treasury, and whatever is left unpaid becomes
    arrears that the soldiers can see, count, and eventually walk away from. With no county wired
    there is nobody to pay or feed them — a legitimate configuration, and the one that produces
    desertion for purely fiscal reasons.
    """

    name: str = "military-finance"
    phase: TickPhase = TickPhase.MILITARY_FINANCE
    # Unit troop counts are carried over from previous ticks, so the phase-level claim names the
    # pay, stores and standing this phase produces and the county and market state it draws on.
    reads: frozenset[str] = frozenset(
        {
            RESOURCE_COUNTY_GRANARY,
            RESOURCE_COUNTY_TREASURY,
            RESOURCE_MARKET_PRICE,
            RESOURCE_MERCHANT_STOCK,
            RESOURCE_UNIT_PAY,
            RESOURCE_UNIT_STORES,
        }
    )
    writes: frozenset[str] = frozenset(
        {
            RESOURCE_COUNTY_GRANARY,
            RESOURCE_COUNTY_TREASURY,
            RESOURCE_MERCHANT_STOCK,
            RESOURCE_UNIT_PAY,
            RESOURCE_UNIT_STANDING,
            RESOURCE_UNIT_STORES,
        }
    )

    def __init__(
        self,
        *,
        military: MilitaryLayer,
        governments: GovernmentLayer | None,
        parameters: MilitaryParameters,
        merchants: MerchantLayer | None = None,
        book: MarketBook | None = None,
    ) -> None:
        self._military = military
        self._governments = governments
        self._parameters = parameters
        self._markets: Mapping[str, LocalGrainMarket] = (
            {}
            if governments is None or merchants is None or book is None
            else {
                county.node_id: LocalGrainMarket(
                    node_id=county.node_id, book=book, merchants=merchants
                )
                for county in governments
            }
        )

    def pay_share(self, unit: GovernmentMilitaryUnit) -> float:
        """What this month's pay obligation amounts to."""
        return unit.troops * self._parameters.pay_tael_per_soldier_month

    def step(self, ctx: TickContext) -> None:
        for unit in self._military:
            due = self.pay_share(unit)
            emit_military_event(
                ctx, unit.unit_id, unit.node_id, unit.record_pay_due(due_tael=due), self.phase
            )
            self._pay(ctx, unit, due)
            shortfall = self._feed(ctx, unit)
            self._update_standing(ctx, unit, shortfall)
        self._military.check_invariants()

    def _pay(self, ctx: TickContext, unit: GovernmentMilitaryUnit, due: float) -> None:
        parameters = self._parameters
        county = None if self._governments is None else self._governments.require(unit.node_id)
        if county is None:
            unit.pay_shortfall_share = 1.0 if due > 0.0 else 0.0
            emit_military_event(
                ctx,
                unit.unit_id,
                unit.node_id,
                unit.accrue_pay_arrears(silver_tael=due),
                self.phase,
            )
            return
        owed = due + unit.pay_arrears_tael
        affordable = county.silver_tael * parameters.pay_share_of_treasury
        paid = min(owed, affordable)
        if paid > 0.0:
            emit_government_event(
                ctx,
                county,
                county.pay_military(
                    silver_tael=paid, payee_id=unit.unit_id, rule_version=MILITARY_RULE_VERSION
                ),
                self.phase,
            )
            emit_military_event(
                ctx,
                unit.unit_id,
                unit.node_id,
                unit.receive_pay(silver_tael=paid, payer_id=county.government_id),
                self.phase,
            )
        unpaid = max(0.0, due - paid)
        unit.pay_shortfall_share = unpaid / due if due > 0.0 else 0.0
        if unpaid > 0.0:
            emit_military_event(
                ctx,
                unit.unit_id,
                unit.node_id,
                unit.accrue_pay_arrears(silver_tael=unpaid),
                self.phase,
            )

    def _feed(self, ctx: TickContext, unit: GovernmentMilitaryUnit) -> float:
        """Feed the unit from its own stores, the granary, and the market; return the unmet share.

        The order is declared: the garrison's own store first, then the county granary, then grain
        the county buys on the local market with its own silver. A garrison starves only when the
        county is out of grain *and* silver, which is the fiscal-military squeeze this phase is
        about — not a bookkeeping accident.
        """
        parameters = self._parameters
        need = unit.troops * parameters.food_shi_per_soldier_month
        if need <= 0.0:
            return 0.0
        county = None if self._governments is None else self._governments.require(unit.node_id)
        ration_shortfall = max(0.0, need - unit.grain_shi)
        if ration_shortfall > 0.0 and county is not None:
            self._issue_rations(ctx, unit, county, ration_shortfall)
        eaten = unit.eat(grain_shi=need)
        emit_military_event(ctx, unit.unit_id, unit.node_id, eaten, self.phase)
        return eaten.trigger["food_shortfall_shi"] / need

    def _issue_rations(
        self,
        ctx: TickContext,
        unit: GovernmentMilitaryUnit,
        county: CountyGovernment,
        shortfall: float,
    ) -> None:
        issued = 0.0
        from_granary = county.issue_grain(
            grain_shi=shortfall, recipient_id=unit.unit_id, rule_version=MILITARY_RULE_VERSION
        )
        if from_granary.trigger["grain_issued_shi"] > 0.0:
            emit_government_event(ctx, county, from_granary, self.phase)
            issued += from_granary.trigger["grain_issued_shi"]
        remaining = shortfall - issued
        market = self._markets.get(unit.node_id)
        if remaining > 0.0 and market is not None and county.silver_tael > 0.0:
            budget = county.silver_tael * self._parameters.ration_purchase_share_of_silver
            outcome = market.buy_grain(
                ctx, county, shi_wanted=remaining, max_silver=budget, phase=self.phase
            )
            if outcome.quantity > 0.0:
                emit_government_event(
                    ctx,
                    county,
                    county.buy_grain(
                        grain_shi=outcome.quantity, price_tael_per_shi=market.price_tael_per_shi
                    ),
                    self.phase,
                )
                bought = county.issue_grain(
                    grain_shi=outcome.quantity,
                    recipient_id=unit.unit_id,
                    rule_version=MILITARY_RULE_VERSION,
                )
                emit_government_event(ctx, county, bought, self.phase)
                issued += bought.trigger["grain_issued_shi"]
        if issued > 0.0:
            emit_military_event(
                ctx,
                unit.unit_id,
                unit.node_id,
                unit.receive_food(grain_shi=issued, source=county.government_id),
                self.phase,
            )

    def _update_standing(
        self, ctx: TickContext, unit: GovernmentMilitaryUnit, unmet_food_share: float
    ) -> None:
        """Morale and cohesion follow *this month's* arrears and rations.

        The accumulated arrears stay on the books and stay visible in every standing record, but
        what moves the soldiers is the pay that did not arrive now: a garrison that is paid in full
        this month recovers, however large the arrears it is owed.
        """
        parameters = self._parameters
        paid_share = 1.0 - unit.pay_shortfall_share
        fed_share = 1.0 - unmet_food_share
        recovery = parameters.morale_recovery * paid_share * fed_share
        morale_delta = (
            recovery
            - parameters.morale_pay_weight * unit.pay_shortfall_share
            - parameters.morale_food_weight * unmet_food_share
        )
        cohesion_delta = recovery - parameters.cohesion_food_weight * unmet_food_share
        emit_military_event(
            ctx,
            unit.unit_id,
            unit.node_id,
            unit.update_standing(morale_delta=morale_delta, cohesion_delta=cohesion_delta),
            self.phase,
        )


class DesertionSystem:
    """Tick phase 11: who leaves, and where they go.

    The rate is the declared rule; the routing is what makes desertion matter to the rest of the
    model. Deserters go home, out of the modelled population, or into the unorganized pool that
    band formation draws on — and the households that take them back are the same households the
    army levied from.
    """

    name: str = "desertion"
    phase: TickPhase = TickPhase.DESERTION
    reads: frozenset[str] = frozenset(
        {
            RESOURCE_COHORT_ADULTS,
            RESOURCE_UNIT_PAY,
            RESOURCE_UNIT_STANDING,
            RESOURCE_UNIT_STORES,
            RESOURCE_UNIT_TROOPS,
        }
    )
    writes: frozenset[str] = frozenset({RESOURCE_COHORT_ADULTS, RESOURCE_UNIT_TROOPS})

    def __init__(
        self,
        *,
        military: MilitaryLayer,
        population: HouseholdPopulation,
        parameters: MilitaryParameters,
        pool: DeserterPool,
    ) -> None:
        self._military = military
        self._population = population
        self._parameters = parameters
        self._pool = pool

    def desertion_rate(self, unit: GovernmentMilitaryUnit) -> float:
        """The declared share of a garrison that leaves this month.

        Driven by the shortfall of *this month's* pay, the shortfall of this month's rations, and
        how far morale has already fallen — not by the size of the arrears stock, which is a
        grievance but not itself a monthly decision.
        """
        parameters = self._parameters
        need = unit.troops * parameters.food_shi_per_soldier_month
        food_ratio = min(1.0, unit.grain_shi / need) if need > 0.0 else 1.0
        rate = (
            parameters.desertion_base_rate
            + parameters.desertion_pay_weight * unit.pay_shortfall_share
            + parameters.desertion_food_weight * (1.0 - food_ratio)
            + parameters.desertion_morale_weight * (1.0 - unit.morale)
        )
        return min(parameters.desertion_max_rate, rate)

    def step(self, ctx: TickContext) -> None:
        for unit in self._military:
            if unit.troops <= 0.0:
                continue
            rate = self.desertion_rate(unit)
            leaving = min(unit.troops, unit.troops * rate)
            if leaving <= 0.0:
                continue
            emit_military_event(
                ctx,
                unit.unit_id,
                unit.node_id,
                unit.lose_troops(troops=leaving, destination="routing", reason="desertion"),
                self.phase,
            )
            self._route(ctx, unit, leaving, rate)
        self._military.check_invariants()

    def _route(
        self, ctx: TickContext, unit: GovernmentMilitaryUnit, leaving: float, rate: float
    ) -> None:
        parameters = self._parameters
        to_home = leaving * parameters.deserter_home_share
        to_band = leaving * parameters.deserter_band_share
        dispersed = leaving - to_home - to_band

        if to_home > 0.0:
            homecoming = [c for c in self._population if c.node_id == unit.node_id]
            if homecoming:
                per_cohort = to_home / len(homecoming)
                for cohort in homecoming:
                    emit_cohort_event(
                        ctx,
                        cohort,
                        cohort.gain_adults(
                            adults=per_cohort,
                            source=unit.unit_id,
                            rule_version=DESERTION_RULE_VERSION,
                        ),
                        self.phase,
                    )
            else:
                to_home = 0.0

        self._pool.add(unit.node_id, to_band)

        emit_military_event(
            ctx,
            unit.unit_id,
            unit.node_id,
            MilitaryEvent(
                event_type=MilitaryEventType.DESERTION_ROUTE,
                rule_version=DESERTION_RULE_VERSION,
                trigger={
                    "desertion_rate": rate,
                    "deserters_left": leaving,
                    "deserters_to_home": to_home,
                    "deserters_to_bands": to_band,
                    "deserters_dispersed": dispersed,
                    "garrison_troops": unit.troops,
                },
                outcome="desertion-routed",
            ),
            self.phase,
        )


class BandRecruitmentSystem:
    """Tick phase 12: the recruit pool, garrison levies, band levies and band formation.

    The pool is shared and finite, and the two recruiters read it differently on purpose:

    * the **garrison** is served first and levies from *all* adults at its node — conscription in
      this model is a household obligation, not a distress response;
    * a **band** levies from the *distress-eligible* adults only, and forms when it has a seed big
      enough to staff itself: unorganized deserters at the node, or a distress-eligible pool that
      its declared recruitment rate would fill over the declared formation horizon.

    A levy takes adults, so it takes labour too. Both recruiters draw down the same cohorts in the
    same tick, garrison first, and the cohort ledger records exactly who left and where they went.
    """

    name: str = "band-recruitment"
    phase: TickPhase = TickPhase.ARMED_RECRUITMENT
    reads: frozenset[str] = frozenset(
        {RESOURCE_COHORT_ADULTS, RESOURCE_DISTRESS_WINDOW, RESOURCE_UNIT_TROOPS}
    )
    writes: frozenset[str] = frozenset(
        {
            RESOURCE_BAND_STANDING,
            RESOURCE_BAND_TROOPS,
            RESOURCE_COHORT_ADULTS,
            RESOURCE_UNIT_TROOPS,
        }
    )

    def __init__(
        self,
        *,
        military: MilitaryLayer,
        bands: BandLayer,
        population: HouseholdPopulation,
        parameters: MilitaryParameters,
        band_parameters: BandParameters,
        pool: DeserterPool,
    ) -> None:
        self._military = military
        self._bands = bands
        self._population = population
        self._parameters = parameters
        self._band_parameters = band_parameters
        self._pool = pool

    def step(self, ctx: TickContext) -> None:
        for unit in self._military:
            room = max(0.0, self._parameters.garrison_target_troops - unit.troops)
            wanted = min(
                eligible_adult_pool(self._population, unit.node_id, distress_eligible=False)
                * self._parameters.levy_rate_of_eligible_adults,
                room,
            )
            taken = self._levy(
                ctx, unit.node_id, wanted, f"garrison:{unit.node_id}", distress_eligible=False
            )
            if taken <= 0.0:
                continue
            emit_military_event(
                ctx,
                unit.unit_id,
                unit.node_id,
                unit.gain_troops(troops=taken, source="levy", reason="levied"),
                self.phase,
            )

        for node_id in sorted({unit.node_id for unit in self._military}):
            self._reinforce_and_form(ctx, node_id)
            self._record_pool(ctx, node_id)
        self._military.check_invariants()
        self._bands.check_invariants()

    def _reinforce_and_form(self, ctx: TickContext, node_id: str) -> None:
        """Feed the unorganized pool into a band, or turn it — with distress — into one."""
        parameters = self._band_parameters
        existing = self._bands.at_node(node_id)

        if existing:
            band = existing[0]
            wanted = (
                eligible_adult_pool(self._population, node_id)
                * parameters.recruitment_rate_of_eligible_adults
            )
            taken = self._levy(ctx, node_id, wanted, band.band_id)
            if taken > 0.0:
                emit_military_event(
                    ctx,
                    band.band_id,
                    node_id,
                    band.gain_members(
                        troops=taken, source="levy", rule_version=RECRUITMENT_RULE_VERSION
                    ),
                    self.phase,
                )
            organized = self._pool.take(node_id, self._pool.at(node_id))
            if organized > 0.0:
                emit_military_event(
                    ctx,
                    band.band_id,
                    node_id,
                    band.gain_members(
                        troops=organized,
                        source="deserters",
                        rule_version=DESERTION_RULE_VERSION,
                    ),
                    self.phase,
                )
            return

        seed = self._pool.at(node_id)
        if seed >= parameters.minimum_formation_troops:
            self._form_from_pool(ctx, node_id, seed)
            return

        pressure = mean_unmet_ratio(self._population, node_id)
        if pressure < parameters.formation_unmet_ratio:
            return
        levy_seed = (
            eligible_adult_pool(self._population, node_id)
            * parameters.recruitment_rate_of_eligible_adults
            * parameters.formation_recruitment_months
        )
        if seed + levy_seed < parameters.minimum_formation_troops:
            return
        plan = self._plan_levy(node_id, levy_seed)
        taken = sum(share for _, share in plan)
        troops = self._pool.at(node_id) + taken
        if troops < parameters.minimum_formation_troops:
            # A levy that cannot staff a band is not a levy: nobody is taken from a household, and
            # the deserters in the pool keep waiting, on the books, for one that can.
            return
        taken = self._apply_levy(ctx, plan, "band-forming")
        troops = self._pool.take(node_id, self._pool.at(node_id)) + taken
        band = _form_band(self._bands, node_id=node_id, cohesion=0.45, network=0.05)
        _adopt(ctx, band, troops=taken, source="levy", phase=self.phase)
        _adopt(
            ctx,
            band,
            troops=troops - taken,
            source="unorganized-deserters",
            phase=self.phase,
            rule_version=DESERTION_RULE_VERSION,
        )
        emit_military_event(
            ctx,
            band.band_id,
            node_id,
            MilitaryEvent(
                event_type=MilitaryEventType.BAND_FORMED,
                rule_version=RECRUITMENT_RULE_VERSION,
                trigger={
                    "troops": troops,
                    "levied_troops": taken,
                    "mean_unmet_ratio": pressure,
                    "formation_source_is_levy": 1.0,
                },
                outcome=f"formed-at:{node_id}",
            ),
            self.phase,
        )

    def _form_from_pool(self, ctx: TickContext, node_id: str, seed: float) -> None:
        troops = self._pool.take(node_id, seed)
        band = _form_band(self._bands, node_id=node_id, cohesion=0.4, network=0.1)
        _adopt(
            ctx,
            band,
            troops=troops,
            source="unorganized-deserters",
            phase=self.phase,
            rule_version=DESERTION_RULE_VERSION,
        )
        emit_military_event(
            ctx,
            band.band_id,
            node_id,
            MilitaryEvent(
                event_type=MilitaryEventType.BAND_FORMED,
                rule_version=DESERTION_RULE_VERSION,
                trigger={
                    "troops": troops,
                    "unorganized_deserters_taken": troops,
                    "formation_source_is_deserters": 1.0,
                },
                outcome=f"formed-at:{node_id}",
            ),
            self.phase,
        )

    def _record_pool(self, ctx: TickContext, node_id: str) -> None:
        """Record unorganized deserters at a node, every tick, including when there are none.

        The pool is a holding account for people who are neither home nor enlisted. Recording it
        whether or not it is empty is what lets a reader reconstruct it exactly from the log.
        """
        waiting = self._pool.at(node_id)
        emit_military_event(
            ctx,
            f"pool::{node_id}",
            node_id,
            MilitaryEvent(
                event_type=MilitaryEventType.DESERTER_POOL,
                rule_version=DESERTION_RULE_VERSION,
                trigger={
                    "unorganized_deserters": waiting,
                    "distress_eligible_adults": eligible_adult_pool(self._population, node_id),
                },
                outcome="unorganized",
            ),
            self.phase,
        )

    def _plan_levy(
        self, node_id: str, adults: float, *, distress_eligible: bool = True
    ) -> tuple[tuple[HouseholdCohortAgent, float], ...]:
        """Who a levy would take adults from, and how many, before anything is written.

        Planning first is what keeps a levy honest: a formation that cannot raise enough adults
        never touches a household, so no adult is ever taken off the books and handed back.
        """
        if adults <= 0.0:
            return ()
        candidates: list[HouseholdCohortAgent] = sorted(
            (
                cohort
                for cohort in self._population
                if cohort.node_id == node_id
                and (cohort.recruitment_eligible or not distress_eligible)
            ),
            key=lambda cohort: (-self._population.unmet_ratio(cohort.cohort_id), cohort.cohort_id),
        )
        remaining = adults
        plan: list[tuple[HouseholdCohortAgent, float]] = []
        for cohort in candidates:
            if remaining <= 1e-9:
                break
            share = min(remaining, cohort.adults * self._parameters.levy_rate_of_eligible_adults)
            if share <= 0.0:
                continue
            plan.append((cohort, share))
            remaining -= share
        return tuple(plan)

    def _apply_levy(
        self,
        ctx: TickContext,
        plan: tuple[tuple[HouseholdCohortAgent, float], ...],
        destination: str,
    ) -> float:
        """Write a planned levy: the hungriest households first, each losing its share."""
        taken = 0.0
        for cohort, share in plan:
            emit_cohort_event(
                ctx,
                cohort,
                cohort.lose_adults(
                    adults=share,
                    destination=destination,
                    rule_version=LEVY_RULE_VERSION,
                    reason="army" if destination.startswith("garrison") else "band",
                ),
                self.phase,
            )
            taken += share
        return taken

    def _levy(
        self,
        ctx: TickContext,
        node_id: str,
        adults: float,
        destination: str,
        *,
        distress_eligible: bool = True,
    ) -> float:
        """Take adults from the cohorts of a node, the hungriest households first."""
        plan = self._plan_levy(node_id, adults, distress_eligible=distress_eligible)
        return self._apply_levy(ctx, plan, destination)


class BandActionSystem:
    """Tick phase 13: bands eat, move toward food, and take from the land.

    A band's "strategy" is one line: avoid being destroyed and find food. It raids everyone at its
    node in fixed proportion to their stores, eats what its people need, and — if it is hungry, or
    if the garrison at its node could remove a declared share of its people this month, and it is
    mobile enough — walks to the neighbouring node where households hold the most grain. There is
    no target selection beyond that, and nothing here reads a map of forts, passes or armies.
    """

    name: str = "band-actions"
    phase: TickPhase = TickPhase.ARMED_MOVEMENT
    reads: frozenset[str] = frozenset(
        {
            RESOURCE_BAND_STANDING,
            RESOURCE_BAND_STORES,
            RESOURCE_BAND_TROOPS,
            RESOURCE_COHORT_ASSETS,
            RESOURCE_COHORT_GRAIN,
            RESOURCE_COUNTY_GRANARY,
            RESOURCE_ELITE_GRAIN,
            RESOURCE_UNIT_TROOPS,
        }
    )
    writes: frozenset[str] = frozenset(
        {
            RESOURCE_BAND_STANDING,
            RESOURCE_BAND_STORES,
            RESOURCE_COHORT_ASSETS,
            RESOURCE_COHORT_GRAIN,
            RESOURCE_COUNTY_GRANARY,
            RESOURCE_ELITE_GRAIN,
        }
    )

    def __init__(
        self,
        *,
        bands: BandLayer,
        military: MilitaryLayer,
        population: HouseholdPopulation,
        elites: EliteLayer,
        governments: GovernmentLayer | None,
        graphs: SpatialGraphs,
        parameters: BandParameters,
        military_parameters: MilitaryParameters,
    ) -> None:
        self._bands = bands
        self._military = military
        self._population = population
        self._elites = elites
        self._governments = governments
        self._graphs = graphs
        self._parameters = parameters
        self._military_parameters = military_parameters

    def step(self, ctx: TickContext) -> None:
        for band in self._bands:
            raided = self._raid(ctx, band) > 0.0
            fed_share = self._eat(ctx, band)
            moved = self._move(ctx, band)
            self._drift(ctx, band, raided=raided, fed_share=fed_share, moved=moved)
        self._bands.check_invariants()

    def _raid(self, ctx: TickContext, band: ArmedBand) -> float:
        """Live off the land: take grain up to a declared multiple of the band's own need.

        The cap is the band's need, not a share of the population's store, so a band's burden on
        the countryside scales with the band. When a node has been eaten out the band gets less
        than its need, which is what makes it hungry — and hunger is what moves and splits bands.
        """
        parameters = self._parameters
        need = band.troops * parameters.food_shi_per_member_month
        allowance = need * parameters.raid_extraction_multiple

        yield_from_cohorts = self._take_from_cohorts(ctx, band, allowance)
        taken = yield_from_cohorts.taken
        arms_taken = yield_from_cohorts.arms
        remaining = yield_from_cohorts.remaining
        taken += self._take_from_elite(ctx, band, remaining)
        taken += self._take_from_granary(ctx, band, remaining)

        if taken > 0.0 or arms_taken > 0.0:
            emit_military_event(
                ctx,
                band.band_id,
                band.node_id,
                band.record_raid(
                    grain_shi=taken,
                    arms_units=arms_taken,
                    victim_id=f"population:{band.node_id}",
                ),
                self.phase,
            )
        return taken + arms_taken

    def _take_from_cohorts(self, ctx: TickContext, band: ArmedBand, allowance: float) -> RaidYield:
        """Take grain from the cohorts in proportion to their stores.

        Returns what was taken, the arms it yielded, and what the band's allowance still covers.
        """
        parameters = self._parameters
        local = [cohort for cohort in self._population if cohort.node_id == band.node_id]
        stock = sum(cohort.grain_shi for cohort in local)
        taken = 0.0
        arms_taken = 0.0
        if allowance > 0.0 and stock > 0.0:
            for cohort in local:
                share = min(allowance, stock) * (cohort.grain_shi / stock)
                if share <= 0.0:
                    continue
                seizure = cohort.record_grain_seizure(
                    grain_shi=share, taker_id=band.band_id, rule_version=BAND_RULE_VERSION
                )
                emit_cohort_event(ctx, cohort, seizure, self.phase)
                taken += seizure.trigger["grain_seized_shi"]
        for cohort in local:
            assets = cohort.movable_assets_tael * parameters.raid_asset_share_per_month
            if assets <= 0.0:
                continue
            found = cohort.record_asset_seizure(
                assets_tael=assets, taker_id=band.band_id, rule_version=BAND_RULE_VERSION
            )
            emit_cohort_event(ctx, cohort, found, self.phase)
            arms_taken += found.trigger["assets_seized_tael"] * parameters.arms_per_asset_valuation
        return RaidYield(taken=taken, arms=arms_taken, remaining=max(0.0, allowance - taken))

    def _take_from_elite(self, ctx: TickContext, band: ArmedBand, allowance: float) -> float:
        """Take what the elite house has, as from households: same rule, one counterparty."""
        if allowance <= 0.0 or band.node_id not in self._elites.by_node:
            return 0.0
        house = self._elites.require(band.node_id)
        if house.grain_shi <= 0.0:
            return 0.0
        seizure = house.record_grain_seizure(
            grain_shi=min(allowance, house.grain_shi),
            taker_id=band.band_id,
            rule_version=BAND_RULE_VERSION,
        )
        emit_elite_event(ctx, house, seizure, self.phase)
        return seizure.trigger["grain_seized_shi"]

    def _take_from_granary(self, ctx: TickContext, band: ArmedBand, allowance: float) -> float:
        """Take from the county granary, if a county exists and the allowance still covers it."""
        if allowance <= 0.0 or self._governments is None:
            return 0.0
        county = self._governments.require(band.node_id)
        if county.grain_shi <= 0.0:
            return 0.0
        seizure = county.record_grain_seizure(
            grain_shi=min(allowance, county.grain_shi),
            taker_id=band.band_id,
            rule_version=BAND_RULE_VERSION,
        )
        emit_government_event(ctx, county, seizure, self.phase)
        return seizure.trigger["grain_seized_shi"]

    def _eat(self, ctx: TickContext, band: ArmedBand) -> float:
        need = band.troops * self._parameters.food_shi_per_member_month
        event = band.eat(grain_shi=need)
        emit_military_event(ctx, band.band_id, band.node_id, event, self.phase)
        if need <= 0.0:
            return 1.0
        return event.trigger["food_eaten_shi"] / need

    def _move(self, ctx: TickContext, band: ArmedBand) -> bool:
        if band.mobility < self._parameters.movement_mobility_floor:
            return False
        if not (self._is_hungry(band) or self._is_harassed(band)):
            return False
        destination = self._best_neighbour(band.node_id)
        if destination is None:
            return False
        access = tuple(sorted({*band.territorial_access, destination}))
        emit_military_event(
            ctx,
            band.band_id,
            band.node_id,
            band.move_to(node_id=destination, access=access),
            self.phase,
        )
        return True

    def _is_hungry(self, band: ArmedBand) -> bool:
        need = band.troops * self._parameters.food_shi_per_member_month
        return need > 0.0 and band.grain_shi < need

    def _is_harassed(self, band: ArmedBand) -> bool:
        """Would the local garrison remove enough of this band that moving beats staying?"""
        if band.troops <= 0.0:
            return False
        unit = self._military.require(band.node_id)
        reach = suppression_reach(unit, band, self._military_parameters, self._parameters)
        return reach / band.troops >= self._parameters.movement_avoidance_ratio

    def _best_neighbour(self, node_id: str) -> str | None:
        """The neighbouring node whose households hold the most grain; no tactical reading."""
        if node_id not in self._graphs.military:
            return None
        best: tuple[float, str] | None = None
        for neighbour in sorted(self._graphs.military.neighbors(node_id)):
            grain = sum(
                cohort.grain_shi for cohort in self._population if cohort.node_id == neighbour
            )
            candidate = (grain, neighbour)
            if best is None or candidate > best:
                best = candidate
        return None if best is None else best[1]

    def _drift(
        self, ctx: TickContext, band: ArmedBand, *, raided: bool, fed_share: float, moved: bool
    ) -> None:
        """Standing after the month's actions.

        Cohesion follows the food: a fed band coheres, a hungry one does not. It also has a ceiling
        set by how many strangers the band absorbed this month — a body of recruits is not yet a
        body of comrades, and a band that grows faster than it coheres is the one that fractures
        next month. Local support follows the raids: ties grow while a band lives off its own
        standing and collapse once it starts taking grain from the people around it. Moving halves
        what is left of those ties, because the band is new to the ground it arrives on. This is the
        declared stand-in for the plan's "diffuse violence becomes organizational, and organization
        costs support".
        """
        parameters = self._parameters
        intake_share = min(1.0, band.take_intake() / band.troops) if band.troops > 0.0 else 0.0
        cohesion_delta = (
            parameters.cohesion_gain_per_month * fed_share
            - parameters.cohesion_decay_per_month * (1.0 - fed_share)
        )
        if raided:
            network_delta = -parameters.network_loss_from_raid_per_month
        else:
            network_delta = parameters.network_gain_per_month * (1.0 - band.network)
        if moved:
            network_delta -= band.network / 2.0
        emit_military_event(
            ctx,
            band.band_id,
            band.node_id,
            band.update_standing(
                cohesion_delta=cohesion_delta,
                mobility_delta=(
                    parameters.mobility_gain_from_move
                    if moved
                    else -parameters.mobility_decay_per_month
                ),
                network_delta=network_delta,
                cohesion_ceiling=1.0 - intake_share,
            ),
            self.phase,
        )


class ViolenceSystem:
    """Tick phase 14: suppression, dissolution, split and merge.

    Suppression is strength against size, discounted by how well the band is embedded locally.
    Consolidation is what remains: bands that have grown past their cohesion split, bands that are
    cohesive enough and in the same place merge. Nothing here chooses a winner — it clears the
    arithmetic.
    """

    name: str = "violence"
    phase: TickPhase = TickPhase.VIOLENCE_CONSEQUENCES
    reads: frozenset[str] = frozenset(
        {
            RESOURCE_BAND_STANDING,
            RESOURCE_BAND_STORES,
            RESOURCE_BAND_TROOPS,
            RESOURCE_COHORT_ADULTS,
            RESOURCE_UNIT_STANDING,
            RESOURCE_UNIT_STORES,
            RESOURCE_UNIT_TROOPS,
        }
    )
    writes: frozenset[str] = frozenset(
        {
            RESOURCE_BAND_STANDING,
            RESOURCE_BAND_STORES,
            RESOURCE_BAND_TROOPS,
            RESOURCE_COHORT_ADULTS,
            RESOURCE_UNIT_STANDING,
            RESOURCE_UNIT_STORES,
        }
    )

    def __init__(
        self,
        *,
        bands: BandLayer,
        military: MilitaryLayer,
        population: HouseholdPopulation,
        military_parameters: MilitaryParameters,
        band_parameters: BandParameters,
    ) -> None:
        self._bands = bands
        self._military = military
        self._population = population
        self._military_parameters = military_parameters
        self._band_parameters = band_parameters

    def step(self, ctx: TickContext) -> None:
        self._suppress(ctx)
        self._dissolve(ctx)
        self._split(ctx)
        self._merge(ctx)
        self._bands.check_invariants()
        self._military.check_invariants()

    def _suppress(self, ctx: TickContext) -> None:
        parameters = self._military_parameters
        for band in tuple(self._bands):
            if band.troops <= 0.0:
                continue
            unit = self._military.require(band.node_id)
            reach = suppression_reach(unit, band, parameters, self._band_parameters)
            losses = min(band.troops, reach)
            if losses <= 0.0:
                continue
            emit_military_event(
                ctx,
                band.band_id,
                band.node_id,
                band.lose_members(
                    troops=losses,
                    arms_units=band.arms_units * (losses / band.troops),
                    destination="dispersed",
                    reason="suppressed",
                    rule_version=SUPPRESSION_RULE_VERSION,
                ),
                self.phase,
            )
            emit_military_event(
                ctx,
                band.band_id,
                band.node_id,
                MilitaryEvent(
                    event_type=MilitaryEventType.SUPPRESSION,
                    rule_version=SUPPRESSION_RULE_VERSION,
                    trigger={
                        "suppressed_troops": losses,
                        "garrison_troops": unit.troops,
                        "local_support": band.network,
                        "arms_capability": _arms_capability(band, self._band_parameters),
                        "effectiveness": parameters.suppression_effectiveness,
                    },
                    outcome=f"suppressed-by:{unit.unit_id}",
                ),
                self.phase,
            )
            cost = losses * parameters.suppression_food_cost_per_troop_shi
            if cost > 0.0:
                emit_military_event(
                    ctx,
                    unit.unit_id,
                    unit.node_id,
                    unit.eat(grain_shi=cost),
                    self.phase,
                )
            emit_military_event(
                ctx,
                unit.unit_id,
                unit.node_id,
                unit.update_standing(
                    morale_delta=0.0, cohesion_delta=-parameters.suppression_cohesion_cost
                ),
                self.phase,
            )

    def _dissolve(self, ctx: TickContext) -> None:
        """Break up a band that is too small to be one, handing its people, food and arms on."""
        threshold = self._band_parameters.dissolve_troops_below
        for band in tuple(self._bands):
            if band.troops > threshold:
                continue
            troops, grain, arms = band.troops, band.grain_shi, band.arms_units
            homecoming = [c for c in self._population if c.node_id == band.node_id]
            if troops > 0.0:
                emit_military_event(
                    ctx,
                    band.band_id,
                    band.node_id,
                    band.lose_members(
                        troops=troops,
                        arms_units=0.0,
                        destination="population" if homecoming else "dispersed",
                        reason="disbanded",
                        rule_version=BAND_RULE_VERSION,
                    ),
                    self.phase,
                )
            if homecoming and troops > 0.0:
                per_cohort = troops / len(homecoming)
                for cohort in homecoming:
                    emit_cohort_event(
                        ctx,
                        cohort,
                        cohort.gain_adults(
                            adults=per_cohort,
                            source=band.band_id,
                            rule_version=BAND_RULE_VERSION,
                        ),
                        self.phase,
                    )
            if grain > 0.0:
                emit_military_event(
                    ctx,
                    band.band_id,
                    band.node_id,
                    band.take_grain(
                        grain_shi=grain,
                        destination="population" if homecoming else "dispersed",
                        reason="dissolution-abandoned-grain",
                    ),
                    self.phase,
                )
            if arms > 0.0:
                emit_military_event(
                    ctx,
                    band.band_id,
                    band.node_id,
                    band.drop_arms(arms_units=arms, reason="dissolution-abandoned-arms"),
                    self.phase,
                )
            emit_military_event(
                ctx,
                band.band_id,
                band.node_id,
                MilitaryEvent(
                    event_type=MilitaryEventType.BAND_DISSOLVED,
                    rule_version=BAND_RULE_VERSION,
                    trigger={
                        "troops_disbanded": troops,
                        "dissolve_threshold": threshold,
                        "cohesion": band.cohesion,
                    },
                    outcome=f"dissolved-at:{band.node_id}",
                ),
                self.phase,
            )
            self._bands.remove(band.band_id)

    def _split(self, ctx: TickContext) -> None:
        parameters = self._band_parameters
        for band in tuple(self._bands):
            if band.troops <= parameters.split_troops_threshold:
                continue
            if band.cohesion >= parameters.split_cohesion_below:
                continue
            left = band.troops / 2.0
            grain = band.grain_shi / 2.0
            arms = band.arms_units / 2.0
            emit_military_event(
                ctx,
                band.band_id,
                band.node_id,
                band.lose_members(
                    troops=left,
                    arms_units=arms,
                    destination="splinter",
                    reason="split",
                    rule_version=SPLIT_RULE_VERSION,
                ),
                self.phase,
            )
            if grain > 0.0:
                emit_military_event(
                    ctx,
                    band.band_id,
                    band.node_id,
                    band.take_grain(grain_shi=grain, destination="splinter", reason="split"),
                    self.phase,
                )
            parent_troops = band.troops
            splinter = _form_band(
                self._bands,
                node_id=band.node_id,
                cohesion=band.cohesion,
                network=band.network,
                access=band.territorial_access,
                mobility=max(0.0, band.mobility - parameters.mobility_gain_from_move),
            )
            _adopt(
                ctx,
                splinter,
                troops=left,
                grain_shi=grain,
                arms_units=arms,
                source=f"split:{band.band_id}",
                phase=self.phase,
                rule_version=SPLIT_RULE_VERSION,
            )
            emit_military_event(
                ctx,
                splinter.band_id,
                splinter.node_id,
                MilitaryEvent(
                    event_type=MilitaryEventType.BAND_SPLIT,
                    rule_version=SPLIT_RULE_VERSION,
                    trigger={
                        "splinter_troops": left,
                        "splinter_grain_shi": grain,
                        "splinter_arms_units": arms,
                        "parent_troops": parent_troops,
                        "cohesion": splinter.cohesion,
                    },
                    outcome=f"split-from:{band.band_id}",
                ),
                self.phase,
            )

    def _merge(self, ctx: TickContext) -> None:
        parameters = self._band_parameters
        by_node: dict[str, list[ArmedBand]] = {}
        for band in self._bands:
            by_node.setdefault(band.node_id, []).append(band)
        for node_id, group in sorted(by_node.items()):
            if len(group) < 2:
                continue
            ordered = sorted(group, key=lambda item: (-item.troops, item.band_id))
            survivor = ordered[0]
            for absorbed in ordered[1:]:
                if absorbed.band_id not in {band.band_id for band in self._bands}:
                    continue
                if (
                    survivor.cohesion < parameters.merge_cohesion_above
                    or absorbed.cohesion < parameters.merge_cohesion_above
                ):
                    continue
                troops, arms, grain = absorbed.troops, absorbed.arms_units, absorbed.grain_shi
                emit_military_event(
                    ctx,
                    absorbed.band_id,
                    node_id,
                    absorbed.lose_members(
                        troops=troops,
                        arms_units=arms,
                        destination=f"merged-into:{survivor.band_id}",
                        reason="merge",
                        rule_version=MERGE_RULE_VERSION,
                    ),
                    self.phase,
                )
                if grain > 0.0:
                    emit_military_event(
                        ctx,
                        absorbed.band_id,
                        node_id,
                        absorbed.take_grain(
                            grain_shi=grain,
                            destination=f"merged-into:{survivor.band_id}",
                            reason="merge",
                            rule_version=MERGE_RULE_VERSION,
                        ),
                        self.phase,
                    )
                emit_military_event(
                    ctx,
                    survivor.band_id,
                    node_id,
                    survivor.gain_members(
                        troops=troops,
                        source=f"merge:{absorbed.band_id}",
                        arms_units=arms,
                        rule_version=MERGE_RULE_VERSION,
                    ),
                    self.phase,
                )
                if grain > 0.0:
                    emit_military_event(
                        ctx,
                        survivor.band_id,
                        node_id,
                        survivor.receive_grain(
                            grain_shi=grain,
                            source=f"merge:{absorbed.band_id}",
                            rule_version=MERGE_RULE_VERSION,
                        ),
                        self.phase,
                    )
                self._bands.remove(absorbed.band_id)


class MilitaryBookkeepingSystem:
    """Tick phase 16: the garrison and band state records, and the ledger check."""

    name: str = "military-bookkeeping"
    phase: TickPhase = TickPhase.BOOKKEEPING
    reads: frozenset[str] = frozenset(
        {
            RESOURCE_BAND_STANDING,
            RESOURCE_BAND_STORES,
            RESOURCE_BAND_TROOPS,
            RESOURCE_UNIT_PAY,
            RESOURCE_UNIT_STANDING,
            RESOURCE_UNIT_STORES,
            RESOURCE_UNIT_TROOPS,
        }
    )
    writes: frozenset[str] = frozenset()

    def __init__(self, *, military: MilitaryLayer, bands: BandLayer) -> None:
        self._military = military
        self._bands = bands

    def step(self, ctx: TickContext) -> None:
        for unit in self._military:
            emit_military_event(ctx, unit.unit_id, unit.node_id, unit.state(), self.phase)
        for band in self._bands:
            emit_military_event(ctx, band.band_id, band.node_id, band.state(), self.phase)
        self._military.check_invariants()
        self._bands.check_invariants()


def eligible_adult_pool(
    population: HouseholdPopulation, node_id: str, *, distress_eligible: bool = True
) -> float:
    """Adults a node can still lose to a levy.

    The garrison levies from all adults (conscription is an obligation); a band levies only from
    the distress-eligible ones (recruitment is a response to hunger). Same cohorts, same ledger,
    two declared pools.
    """
    return sum(
        cohort.adults
        for cohort in population
        if cohort.node_id == node_id and (cohort.recruitment_eligible or not distress_eligible)
    )


def mean_unmet_ratio(population: HouseholdPopulation, node_id: str) -> float:
    """Mean unmet share of the subsistence floor at a node."""
    cohorts = [c for c in population if c.node_id == node_id]
    if not cohorts:
        return 0.0
    return sum(population.unmet_ratio(c.cohort_id) for c in cohorts) / len(cohorts)
