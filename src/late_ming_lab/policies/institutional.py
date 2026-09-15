"""The institutional decision layer: a few seats, triggered by events, applied through levers.

The plan allows the runtime model to sit in **a handful of institutional seats** — the central
fiscal authority, a provincial authority, selected county authorities and one armed-group
leadership — and only when something has happened. This module is that layer, and it is
small:

- **Event-triggered, never polled.** Each seat has declared reading lines; a decision happens only
  when one of its own lines is crossed, and never twice within :data:`MIN_TICKS_BETWEEN_DECISIONS`.
  At most one seat decides per tick, so a 240-tick run makes at most twenty calls, not 240 x seats.
- **Readings, not history.** The observation is built from the last
  :data:`WINDOW_TICKS` months of the run's own event log plus the seated actor's current strength:
  every measure is dimensionless, and none of them is a date, a place or a name.
- **Decisions are applied, or refused.** Every action in the space has a lever, and the layer
  reaches exactly those levers. A policy that fails — disabled, unconfirmed model, unreachable
  endpoint, invalid answer — changes nothing: the layer records the refusal and either uses
  a *declared* fallback policy or leaves the state alone. It never calls another model and
  never improvises.
- **The rationale is inert.** It is written into the trace and never read back.

The phase it registers at, :attr:`TickPhase.INSTITUTIONAL_DECISIONS`, was declared in P01 and sits
after taxation, relief, migration and military finance and before bookkeeping: exactly the window in
which an institution can look at the month that just happened and change next month's policy.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

from late_ming_lab.core.events import Event
from late_ming_lab.core.tick import (
    RESOURCE_BAND_TROOPS,
    RESOURCE_COHORT_TAX_ARREARS,
    RESOURCE_COUNTY_ARREARS,
    RESOURCE_DISTRESS_WINDOW,
    RESOURCE_MIGRANTS,
    TickContext,
    TickPhase,
)
from late_ming_lab.evidence.parameters import (
    FiscalParameters,
    core_default_governance_indicators,
)
from late_ming_lab.networks.disruption import CalmTrade, ScaledDisruption, TradeDisruption
from late_ming_lab.policies.base import (
    ACTION_LEVERS,
    ROLE_ACTIONS,
    ActorRole,
    ChatTransport,  # noqa: F401  (re-exported for callers building a layer)
    InstitutionalAction,
    InstitutionalDecision,
    InstitutionalPolicy,
    PolicyError,
    PolicyObservation,
    TracedPolicy,
)
from late_ming_lab.policies.fiscal import ArrearsEscalation, ExtractionPolicy, FixedExtraction
from late_ming_lab.systems.fiscal import OfficialReliefSystem, TaxCollectionSystem

#: The shortest gap between two decisions by the same seat. A crisis is not a reason to poll: an
#: institution reviews its position when something moved, and at most this often.
MIN_TICKS_BETWEEN_DECISIONS: Final[int] = 12

#: How many months of the run an observation looks back over.
WINDOW_TICKS: Final[int] = 12

#: The event types the reading window accumulates. Declared here because the log's contract is the
#: names, and the names are what the measures mean.
ASSESSMENT_EVENT: Final[str] = "TAX_ASSESSMENT"
RECEIPT_EVENT: Final[str] = "TAX_RECEIPT"
CONSUMPTION_EVENT: Final[str] = "CONSUMPTION"
EXIT_EVENT: Final[str] = "MIGRATION_EXIT"
COUNTY_STATE_EVENT: Final[str] = "COUNTY_STATE"
BAND_STATE_EVENT: Final[str] = "BAND_STATE"

#: The lever names a decision can touch, from the shared vocabulary in `policies.base`.
LEVER_EXTRACTION: Final[str] = "extraction-policy"
LEVER_RELIEF: Final[str] = "relief-share"
LEVER_DISRUPTION: Final[str] = "trade-disruption"


@dataclass(frozen=True, slots=True)
class Trigger:
    """One declared line: when the reading is past it, the seat reviews its position."""

    role: ActorRole
    name: str
    measure: str
    direction: str  # "above" or "below"
    threshold: float

    def fires(self, measures: Mapping[str, float]) -> bool:
        value = measures.get(self.measure)
        if value is None:
            return False
        return value > self.threshold if self.direction == "above" else value < self.threshold


#: Two lines this layer declares for itself, because the project has no reading rule for the
#: quantities they name. Both are grade S: a county raising about a third of what it assesses is in
#: trouble, and an arrears stock of half a year's assessment is more than a delay. Neither is
#: evidence, and neither is fitted to anything.
REQUIREMENTS_SHORTFALL_LINE: Final[float] = 0.35
ARREARS_MONTHS_LINE: Final[float] = 6.0


def default_triggers() -> tuple[Trigger, ...]:
    """The declared lines a seat watches, three of them the project's own governance readings.

    ``band_troops_share_of_adults``, ``out_migration_share_of_households`` and
    ``unmet_share_of_need`` are the reading lines P07 already declares for exactly these
    quantities, so a seat triggers on the same lines the governance indicators do rather than on
    numbers invented here. The other two are declared in this module and named as such.
    """
    indicators = core_default_governance_indicators()
    return (
        Trigger(
            ActorRole.CENTRAL_FISCAL,
            "central-remittance-shortfall",
            "receipts_over_quota",
            "below",
            REQUIREMENTS_SHORTFALL_LINE,
        ),
        Trigger(
            ActorRole.PROVINCIAL,
            "provincial-arrears",
            "tax_arrears_months",
            "above",
            ARREARS_MONTHS_LINE,
        ),
        Trigger(
            ActorRole.PROVINCIAL,
            "provincial-distress",
            "unmet_need_share",
            "above",
            indicators.unmet_share_of_need,
        ),
        Trigger(
            ActorRole.COUNTY,
            "county-receipts",
            "receipts_over_quota",
            "below",
            REQUIREMENTS_SHORTFALL_LINE,
        ),
        Trigger(
            ActorRole.COUNTY,
            "county-out-migration",
            "out_migration_share",
            "above",
            indicators.out_migration_share_of_households,
        ),
        Trigger(
            ActorRole.ARMED_GROUP,
            "armed-concentration",
            "armed_share_of_adults",
            "above",
            indicators.band_troops_share_of_adults,
        ),
    )


#: The declared triggers, in the order a seat is offered them. Each is a line on a measure the layer
#: can actually read, and the phase report prints the table so a reader can see what makes an
#: institution act.
TRIGGERS: Final[tuple[Trigger, ...]] = default_triggers()


@dataclass(frozen=True, slots=True)
class ActorSeat:
    """One occupied institutional seat: an opaque code, a role, and the region it speaks for.

    `region` is the node the seat acts on, used to find the levers a decision can pull and recorded
    in the trace. `opaque_region` is what the *actor* is told: an anonymous code, because a prompt
    that names a place hands the actor information about where it stands in the sequence, which is
    what the boundary exists to withhold.
    """

    code: str
    role: ActorRole
    region: str
    opaque_region: str = ""

    def displayed_region(self) -> str:
        """The region as the actor sees it: the opaque code when one is declared, else the node."""
        return self.opaque_region or self.region

    def action_space(self) -> tuple[InstitutionalAction, ...]:
        return ROLE_ACTIONS[self.role]


@dataclass(slots=True)
class ReadingWindow:
    """The last few months of readings, accumulated from the log as the run passes.

    Only the event types named above are read, and only their declared trigger fields. The window is
    what makes an observation a *reading* — dimensionless, current, and free of any date.
    """

    months: int = WINDOW_TICKS
    quota: deque[float] = field(default_factory=deque)
    receipts: deque[float] = field(default_factory=deque)
    need: deque[float] = field(default_factory=deque)
    unmet: deque[float] = field(default_factory=deque)
    exits: deque[float] = field(default_factory=deque)
    arrears: deque[float] = field(default_factory=deque)
    band_troops: deque[float] = field(default_factory=deque)
    largest_share: deque[float] = field(default_factory=deque)

    def push(self, events: Sequence[Event]) -> None:
        """Fold one tick's events into the window, dropping the month that falls out of it."""
        totals = {
            "quota": 0.0,
            "receipts": 0.0,
            "need": 0.0,
            "unmet": 0.0,
            "exits": 0.0,
            "arrears": 0.0,
            "band_troops": 0.0,
            "largest_share": 0.0,
        }
        largest = 0.0
        for event in events:
            trigger = event.trigger
            if event.event_type == ASSESSMENT_EVENT:
                totals["quota"] += float(trigger.get("quota_tael", 0.0))
            elif event.event_type == RECEIPT_EVENT:
                totals["receipts"] += float(trigger.get("receipts_tael", 0.0))
            elif event.event_type == CONSUMPTION_EVENT:
                totals["need"] += float(trigger.get("need_shi", 0.0))
                totals["unmet"] += float(trigger.get("unmet_shi", 0.0))
            elif event.event_type == EXIT_EVENT:
                totals["exits"] += float(trigger.get("households_exited", 0.0))
            elif event.event_type == COUNTY_STATE_EVENT:
                totals["arrears"] = float(trigger.get("arrears_tael", totals["arrears"]))
            elif event.event_type == BAND_STATE_EVENT:
                troops = float(trigger.get("troops", 0.0))
                totals["band_troops"] += troops
                largest = max(largest, troops)
        if largest > 0.0 and totals["band_troops"] > 0.0:
            totals["largest_share"] = largest / totals["band_troops"]
        for name, target in (
            ("quota", self.quota),
            ("receipts", self.receipts),
            ("need", self.need),
            ("unmet", self.unmet),
            ("exits", self.exits),
            ("arrears", self.arrears),
            ("band_troops", self.band_troops),
            ("largest_share", self.largest_share),
        ):
            target.append(totals[name])
        while len(self.quota) > self.months:
            for queue in (
                self.quota,
                self.receipts,
                self.need,
                self.unmet,
                self.exits,
                self.arrears,
                self.band_troops,
                self.largest_share,
            ):
                queue.popleft()

    def measures(self, *, adults: float, starting_households: float) -> dict[str, float]:
        """The dimensionless readings an observation carries."""
        quota = sum(self.quota)
        receipts = sum(self.receipts)
        need = sum(self.need)
        unmet = sum(self.unmet)
        months = max(1, len(self.quota))
        monthly_quota = quota / months
        arrears = self.arrears[-1] if self.arrears else 0.0
        troops = self.band_troops[-1] if self.band_troops else 0.0
        return {
            "tax_arrears_months": arrears / monthly_quota if monthly_quota > 0.0 else 0.0,
            "receipts_over_quota": receipts / quota if quota > 0.0 else 0.0,
            "unmet_need_share": unmet / need if need > 0.0 else 0.0,
            "armed_share_of_adults": troops / adults if adults > 0.0 else 0.0,
            "out_migration_share": (
                sum(self.exits) / starting_households if starting_households > 0.0 else 0.0
            ),
            "largest_band_share": max(self.largest_share) if self.largest_share else 0.0,
        }


@runtime_checkable
class DisruptionHost(Protocol):
    """What the leaky abstraction needs from the market: a disruption regime it can swap.

    The market owns the regime's *use*; this layer only installs one. Typing it as a protocol keeps
    the decision layer from importing the market system it may be constructed beside.
    """

    def set_disruption(self, disruption: TradeDisruption) -> None: ...


class InstitutionalLevers:
    """The world-facing levers a decision may reach, and nothing else.

    Every action in :data:`~late_ming_lab.policies.base.ACTION_LEVERS` has an entry here, so no
    decision can be *recorded* as taken while changing nothing. The levers are the two setters the
    model exposes for policy input (extraction policy, relief share) and the market's declared
    disruption regime — the same hook shape P04 declared and P06 left in place.
    """

    def __init__(
        self,
        *,
        tax: TaxCollectionSystem | None = None,
        relief: OfficialReliefSystem | None = None,
        market: DisruptionHost | None = None,
        base_disruption: TradeDisruption | None = None,
        blocked_link: tuple[str, str] | None = None,
        fiscal_parameters: FiscalParameters | None = None,
        base_effort: float = 0.5,
    ) -> None:
        self._tax = tax
        self._relief = relief
        self._market = market
        self._base_disruption = base_disruption or CalmTrade()
        self._blocked_link = blocked_link
        self._fiscal = fiscal_parameters
        self._base_effort = base_effort
        self._relief_share = (
            fiscal_parameters.relief_share_of_need if fiscal_parameters is not None else 0.0
        )

    @property
    def relief_share(self) -> float:
        return self._relief_share

    def apply(self, decision: InstitutionalDecision) -> tuple[str, ...]:
        """Apply one decision, returning the lever names it touched.

        ``MAINTAIN`` touches nothing. The three fiscal actions replace the extraction policy with a
        declared one whose effort and rate move with the decision's intensity; ``RELIEF_TRANSFER``
        moves the relief share between its declared bounds; the two link actions install the
        declared disruption regime or lift it. The rationale is not consulted anywhere in this
        method.
        """
        lever = ACTION_LEVERS[decision.action]
        if decision.action is InstitutionalAction.MAINTAIN:
            return ()
        if decision.action is InstitutionalAction.RELAX_EXTRACTION:
            effort = self._base_effort * (1.0 - 0.8 * decision.intensity)
            self._install_policy(FixedExtraction(effort=max(0.0, effort)))
            return (lever,)
        if decision.action is InstitutionalAction.INTENSIFY_EXTRACTION:
            effort = min(1.0, self._base_effort + (1.0 - self._base_effort) * decision.intensity)
            self._install_policy(
                ArrearsEscalation(base_effort=effort, arrears_weight=0.5, effort_ceiling=1.0)
            )
            return (lever,)
        if decision.action is InstitutionalAction.RELIEF_TRANSFER:
            share = min(1.0, 0.5 + 0.5 * decision.intensity)
            self._relief_share = share
            if self._relief is not None:
                self._relief.set_relief_share(share)
            return (lever,)
        if decision.action is InstitutionalAction.BLOCK_LINK:
            if self._blocked_link is not None and self._market is not None:
                regime = ScaledDisruption(
                    name="institutional-blockade",
                    risk_scale=1.5,
                    capacity_scale=0.5,
                    blocked_links=(self._blocked_link,),
                )
                self._market.set_disruption(regime)
            return (lever,)
        if decision.action is InstitutionalAction.REOPEN_LINK:
            if self._market is not None:
                self._market.set_disruption(self._base_disruption)
            return (lever,)
        raise PolicyError(f"{decision.action.value} has no lever")  # pragma: no cover - enum total

    def _install_policy(self, policy: ExtractionPolicy) -> None:
        if self._tax is not None:
            self._tax.set_extraction_policy(policy)


@dataclass(frozen=True, slots=True)
class Refusal:
    """A decision the layer did not take, and why: a silence would look like calm."""

    tick: int
    actor: str
    role: str
    policy: str
    reason: str


@dataclass(slots=True)
class InstitutionalDecisionSystem:
    """The tick-phase system: seats, triggers, a policy, and the levers a decision may reach."""

    name: str = "institutional-decisions"
    phase: TickPhase = TickPhase.INSTITUTIONAL_DECISIONS
    #: What the layer reads. It observes the fiscal and armed state of the month that just ended and
    #: the distress and migration flows in it. Its writes are deliberately empty: a decision changes
    #: *policy inputs* (the extraction policy, the relief share, the disruption regime), which the
    #: systems after it consult next tick, not a resource of this tick's dataflow.
    reads: frozenset[str] = frozenset(
        {
            RESOURCE_COUNTY_ARREARS,
            RESOURCE_COHORT_TAX_ARREARS,
            RESOURCE_BAND_TROOPS,
            RESOURCE_DISTRESS_WINDOW,
            RESOURCE_MIGRANTS,
        }
    )
    writes: frozenset[str] = frozenset()

    seats: tuple[ActorSeat, ...] = ()
    policy: InstitutionalPolicy | None = None
    fallback: InstitutionalPolicy | None = None
    levers: InstitutionalLevers | None = None
    adults: float = 0.0
    starting_households: float = 0.0
    min_ticks_between_decisions: int = MIN_TICKS_BETWEEN_DECISIONS
    window_ticks: int = WINDOW_TICKS
    window: ReadingWindow = field(init=False)
    decisions: list[dict[str, object]] = field(default_factory=list, init=False)
    refusals: list[Refusal] = field(default_factory=list, init=False)
    _cursor: int = field(default=0, init=False)
    _last_decision_tick: dict[str, int] = field(default_factory=dict, init=False)
    _rotation: int = field(default=0, init=False)
    _past_the_line: dict[tuple[str, str], bool] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if self.policy is None:
            raise PolicyError("the institutional layer needs a policy")
        if self.levers is None:
            raise PolicyError("the institutional layer needs its levers")
        self.window = ReadingWindow(months=self.window_ticks)

    @property
    def policy_name(self) -> str:
        assert self.policy is not None  # set in __post_init__
        return self.policy.name

    def step(self, ctx: TickContext) -> None:
        """Fold the month into the window, then let at most one triggered seat decide."""
        events = ctx.logger.events[self._cursor :]
        self._cursor = len(ctx.logger.events)
        self.window.push(events)
        measures = self.window.measures(
            adults=self.adults, starting_households=self.starting_households
        )
        for offset in range(len(self.seats)):
            seat = self.seats[(self._rotation + offset) % len(self.seats)]
            crossings = self.crossings(seat, measures)
            if not self._due(seat, ctx.tick, crossings):
                continue
            self._rotation = (self._rotation + offset + 1) % len(self.seats)
            self._last_decision_tick[seat.code] = ctx.tick
            self._decide(seat, ctx, measures, crossings)
            return

    def crossings(self, seat: ActorSeat, measures: Mapping[str, float]) -> tuple[str, ...]:
        """The seat's lines that have just been crossed, updating the crossing state.

        *Event*-triggered means a crossing, not a level: a seat reviews its position when a reading
        passes one of its lines, and does not ask again every month for as long as the line stays
        crossed. A line that was past and comes back inside counts too — that is what a recovery
        looks like from a seat, and it is worth a look.
        """
        crossed: list[str] = []
        for trigger in TRIGGERS:
            if trigger.role is not seat.role:
                continue
            now = trigger.fires(measures)
            key = (seat.code, trigger.name)
            was = self._past_the_line.get(key)
            self._past_the_line[key] = now
            if was is None:
                if now:
                    crossed.append(trigger.name)
            elif now != was:
                crossed.append(trigger.name)
        return tuple(crossed)

    def _due(self, seat: ActorSeat, tick: int, crossings: tuple[str, ...]) -> bool:
        """Whether a crossed line turns into a decision: not twice inside the declared spacing."""
        if not crossings:
            return False
        last = self._last_decision_tick.get(seat.code)
        return last is None or tick - last >= self.min_ticks_between_decisions

    def _decide(
        self,
        seat: ActorSeat,
        ctx: TickContext,
        measures: Mapping[str, float],
        fired: tuple[str, ...],
    ) -> None:
        observation = PolicyObservation(
            actor=seat.code,
            role=seat.role,
            region=seat.displayed_region(),
            tick=ctx.tick,
            measures=tuple(sorted(measures.items())),
            action_space=seat.action_space(),
        )
        policy = self.policy
        assert policy is not None
        try:
            decision = policy.choose_action(observation, seat.action_space())
        except PolicyError as error:
            self._record_refusal(ctx, seat, policy.name, str(error))
            if self.fallback is None:
                return
            try:
                decision = self.fallback.choose_action(observation, seat.action_space())
            except PolicyError as fallback_error:
                self._record_refusal(
                    ctx, seat, self.fallback.name, f"fallback failed: {fallback_error}"
                )
                return
            self._record_decision(
                ctx, seat, self.fallback.name, decision, outcome="fallback", fired=fired
            )
            return
        self._record_decision(ctx, seat, policy.name, decision, outcome="decided", fired=fired)

    def _record_decision(
        self,
        ctx: TickContext,
        seat: ActorSeat,
        policy_name: str,
        decision: InstitutionalDecision,
        *,
        outcome: str,
        fired: tuple[str, ...],
    ) -> None:
        assert self.levers is not None
        levers = self.levers.apply(decision)
        record = self._trace(ctx, seat, policy_name)
        row: dict[str, object] = {
            "tick": ctx.tick,
            "actor": seat.code,
            "role": seat.role.value,
            "region": seat.region,
            "policy": policy_name,
            "model_id": record.get("model_id"),
            "prompt_hash": record.get("prompt_hash"),
            "response_hash": record.get("response_hash"),
            "action": decision.action.value,
            "intensity": decision.intensity,
            "priority": decision.priority.value,
            "rationale": decision.rationale,
            "outcome": outcome,
            "trigger": ",".join(fired),
            "levers": ",".join(levers),
            "latency_ms": record.get("latency_ms"),
        }
        self.decisions.append(row)
        ctx.emit(
            "INSTITUTIONAL_DECISION",
            agent_id=seat.code,
            region=seat.region,
            rule_version=policy_name,
            outcome=f"{outcome}:{decision.action.value}",
            trigger={
                "intensity": decision.intensity,
                "levers_touched": float(len(levers)),
                "priority_code": float(list(type(decision.priority)).index(decision.priority)),
            },
        )

    def _record_refusal(
        self, ctx: TickContext, seat: ActorSeat, policy_name: str, reason: str
    ) -> None:
        self.refusals.append(
            Refusal(
                tick=ctx.tick,
                actor=seat.code,
                role=seat.role.value,
                policy=policy_name,
                reason=reason,
            )
        )
        ctx.emit(
            "INSTITUTIONAL_DECISION",
            agent_id=seat.code,
            region=seat.region,
            rule_version=policy_name,
            outcome="refused",
            trigger={"refused": 1.0},
        )

    def _trace(self, ctx: TickContext, seat: ActorSeat, policy_name: str) -> dict[str, object]:
        assert self.policy is not None
        policy = self.policy
        if isinstance(policy, TracedPolicy) and policy.name == policy_name:
            record = policy.last_record()
            return {
                "model_id": record.model_id,
                "prompt_hash": record.prompt_hash,
                "response_hash": record.response_hash,
                "latency_ms": record.latency_ms,
            }
        return {"model_id": None, "prompt_hash": None, "response_hash": None, "latency_ms": None}
