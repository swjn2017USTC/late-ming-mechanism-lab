"""Government military units and armed bands.

Two actor types, deliberately unheroic. A `GovernmentMilitaryUnit` is a garrison with a strength,
a food stock, a pay obligation and the two things pay and food produce: morale and cohesion. An
`ArmedBand` is what the plan calls it — size, food, arms, mobility, cohesion, network and
territorial access — and it consolidates or dissolves by declared rules.

Nothing here is a named leader, a tactic, a siege or a weapon. There is no `LiZichengAgent`, no
order of battle, and no rule that reads like a drill manual. A band's actions are *abstractions*:
it eats, it moves toward food, it takes grain and silver from the people around it, and it splits or
merges by size and cohesion. Suppression is likewise an abstraction: a garrison in the same place
reduces a band's numbers, and pays for it in food and cohesion.

People are conserved. Every recruit leaves a household cohort's adult balance and appears in a
unit or a band; every deserter leaves a unit and goes home, to a band, or out of the modelled
population; every suppression loss leaves a band with a recorded destination. Both sides of every
movement are written to the event log, which is what makes the conservation tests possible.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from pydantic import Field, PrivateAttr

from late_ming_lab.actors.ledger import (
    ARMS_DELTA,
    GRAIN_DELTA,
    PAY_ARREARS_DELTA,
    TROOPS_DELTA,
    LedgerAgent,
)

MILITARY_RULE_VERSION = "military-finance-v1"
BAND_RULE_VERSION = "band-action-v1"

NODE_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"


class MilitaryEventType(StrEnum):
    """Every transition a garrison or a band can record."""

    PAY_DUE = "MILITARY_PAY_DUE"
    PAY_RECEIVED = "MILITARY_PAY_RECEIVED"
    FOOD_CONSUMED = "MILITARY_FOOD_CONSUMED"
    STANDING = "MILITARY_STANDING"
    DESERTION = "DESERTERS_LEFT"
    DESERTION_ROUTE = "DESERTION_ROUTED"
    DESERTER_POOL = "DESERTER_POOL"
    LEVY = "RECRUIT_LEVY"
    BAND_FORMED = "BAND_FORMED"
    BAND_DISSOLVED = "BAND_DISSOLVED"
    BAND_RAID = "BAND_RAID"
    BAND_STORES = "BAND_STORES_MOVED"
    BAND_MOVE = "BAND_MOVE"
    BAND_SPLIT = "BAND_SPLIT"
    BAND_MERGE = "BAND_MERGE"
    SUPPRESSION = "SUPPRESSION"
    BAND_STANDING = "BAND_STANDING"
    BAND_STATE = "BAND_STATE"
    UNIT_STATE = "MILITARY_STATE"


@dataclass(frozen=True, slots=True)
class MilitaryEvent:
    """One transition of a garrison or a band, ready to be emitted by a system."""

    event_type: MilitaryEventType
    rule_version: str
    trigger: dict[str, float]
    outcome: str


def _bounded(value: float) -> float:
    return min(max(value, 0.0), 1.0)


class GovernmentMilitaryUnit(LedgerAgent):
    """A garrison: strength, food, pay obligation, morale and cohesion."""

    node_id: str = Field(pattern=NODE_ID_PATTERN, max_length=64)
    troops: float = Field(ge=0)
    grain_shi: float = Field(ge=0)
    pay_arrears_tael: float = Field(
        default=0.0, ge=0, description="pay owed to the soldiers of this unit"
    )
    pay_shortfall_share: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="share of this month's pay obligation that did not arrive",
    )
    morale: float = Field(default=0.5, ge=0, le=1)
    cohesion: float = Field(default=0.5, ge=0, le=1)

    @property
    def unit_id(self) -> str:
        return f"garrison::{self.node_id}"

    @property
    def ledger_name(self) -> str:
        return self.unit_id

    @property
    def arrears_per_soldier_tael(self) -> float:
        return self.pay_arrears_tael / self.troops if self.troops > 0 else 0.0

    # ------------------------------------------------------------------ finance

    def record_pay_due(
        self, *, due_tael: float, rule_version: str = MILITARY_RULE_VERSION
    ) -> MilitaryEvent:
        """Record this month's pay obligation; a liability, not a balance."""
        return MilitaryEvent(
            event_type=MilitaryEventType.PAY_DUE,
            rule_version=rule_version,
            trigger={"pay_due_tael": due_tael, "troops": self.troops},
            outcome="due",
        )

    def receive_pay(
        self, *, silver_tael: float, payer_id: str, rule_version: str = MILITARY_RULE_VERSION
    ) -> MilitaryEvent:
        """Receive pay from the treasury; it pays down the soldiers' arrears, never below zero."""
        applied = min(silver_tael, self.pay_arrears_tael)
        self._apply(pay_arrears=-applied, impacts=((PAY_ARREARS_DELTA, -applied),))
        unapplied = silver_tael - applied
        return MilitaryEvent(
            event_type=MilitaryEventType.PAY_RECEIVED,
            rule_version=rule_version,
            trigger={
                "pay_received_tael": silver_tael,
                "pay_applied_tael": applied,
                "pay_surplus_tael": max(0.0, unapplied),
                PAY_ARREARS_DELTA: -applied,
                "pay_arrears_tael": self.pay_arrears_tael,
                "troops": self.troops,
            },
            outcome=f"paid-by:{payer_id}",
        )

    def accrue_pay_arrears(
        self, *, silver_tael: float, rule_version: str = MILITARY_RULE_VERSION
    ) -> MilitaryEvent:
        """Record pay that was due and not paid."""
        self._apply(pay_arrears=silver_tael, impacts=((PAY_ARREARS_DELTA, silver_tael),))
        return MilitaryEvent(
            event_type=MilitaryEventType.PAY_DUE,
            rule_version=rule_version,
            trigger={
                "arrears_accrued_tael": silver_tael,
                PAY_ARREARS_DELTA: silver_tael,
                "pay_arrears_tael": self.pay_arrears_tael,
            },
            outcome="unpaid",
        )

    def eat(self, *, grain_shi: float, rule_version: str = MILITARY_RULE_VERSION) -> MilitaryEvent:
        """Feed the unit from its own stores; what it cannot eat is a shortfall, not a debt."""
        eaten = min(grain_shi, self.grain_shi)
        self._apply(grain=-eaten, impacts=((GRAIN_DELTA, -eaten),))
        return MilitaryEvent(
            event_type=MilitaryEventType.FOOD_CONSUMED,
            rule_version=rule_version,
            trigger={
                "food_need_shi": grain_shi,
                "food_eaten_shi": eaten,
                "food_shortfall_shi": max(0.0, grain_shi - eaten),
                GRAIN_DELTA: -eaten,
                "grain_shi": self.grain_shi,
            },
            outcome="fed" if eaten >= grain_shi else "short-rations",
        )

    def receive_food(
        self, *, grain_shi: float, source: str, rule_version: str = MILITARY_RULE_VERSION
    ) -> MilitaryEvent:
        self._apply(grain=grain_shi, impacts=((GRAIN_DELTA, grain_shi),))
        return MilitaryEvent(
            event_type=MilitaryEventType.FOOD_CONSUMED,
            rule_version=rule_version,
            trigger={"food_received_shi": grain_shi, GRAIN_DELTA: grain_shi},
            outcome=f"food-from:{source}",
        )

    def update_standing(
        self,
        *,
        morale_delta: float,
        cohesion_delta: float,
        rule_version: str = MILITARY_RULE_VERSION,
    ) -> MilitaryEvent:
        """Move morale and cohesion; both are bounded indices, not balances."""
        before = (self.morale, self.cohesion)
        self.morale = _bounded(self.morale + morale_delta)
        self.cohesion = _bounded(self.cohesion + cohesion_delta)
        return MilitaryEvent(
            event_type=MilitaryEventType.STANDING,
            rule_version=rule_version,
            trigger={
                "morale": self.morale,
                "cohesion": self.cohesion,
                "morale_delta": self.morale - before[0],
                "cohesion_delta": self.cohesion - before[1],
                "pay_arrears_per_soldier_tael": self.arrears_per_soldier_tael,
                "pay_shortfall_share": self.pay_shortfall_share,
            },
            outcome="standing-updated",
        )

    # ------------------------------------------------------------------ people

    def lose_troops(
        self,
        *,
        troops: float,
        destination: str,
        reason: str,
        rule_version: str = MILITARY_RULE_VERSION,
    ) -> MilitaryEvent:
        """Send soldiers away: desertion, disbandment or a suppression loss."""
        gone = min(troops, self.troops)
        self._apply(troops=-gone, impacts=((TROOPS_DELTA, -gone),))
        return MilitaryEvent(
            event_type=MilitaryEventType.DESERTION,
            rule_version=rule_version,
            trigger={
                "troops_left": gone,
                TROOPS_DELTA: -gone,
                "troops": self.troops,
                f"destination_is_{destination}": 1.0,
            },
            outcome=f"{reason}-to:{destination}",
        )

    def gain_troops(
        self,
        *,
        troops: float,
        source: str,
        reason: str,
        rule_version: str = MILITARY_RULE_VERSION,
    ) -> MilitaryEvent:
        self._apply(troops=troops, impacts=((TROOPS_DELTA, troops),))
        return MilitaryEvent(
            event_type=MilitaryEventType.LEVY,
            rule_version=rule_version,
            trigger={
                "troops_joined": troops,
                TROOPS_DELTA: troops,
                "troops": self.troops,
                f"source_is_{source}": 1.0,
            },
            outcome=f"{reason}-from:{source}",
        )

    def state(self, *, rule_version: str = MILITARY_RULE_VERSION) -> MilitaryEvent:
        return MilitaryEvent(
            event_type=MilitaryEventType.UNIT_STATE,
            rule_version=rule_version,
            trigger={
                "troops": self.troops,
                "grain_shi": self.grain_shi,
                "pay_arrears_tael": self.pay_arrears_tael,
                "pay_arrears_per_soldier_tael": self.arrears_per_soldier_tael,
                "morale": self.morale,
                "cohesion": self.cohesion,
            },
            outcome="unit-state",
        )


class MilitaryLayer:
    """The garrisons of every county node, in a fixed order."""

    def __init__(self, units: Sequence[GovernmentMilitaryUnit]) -> None:
        if not units:
            raise ValueError("a military layer needs at least one unit")
        ordered = tuple(sorted(units, key=lambda unit: unit.node_id))
        ids = [unit.node_id for unit in ordered]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate garrison nodes: {', '.join(sorted(ids))}")
        self._units = ordered
        self._by_node = MappingProxyType({unit.node_id: unit for unit in ordered})

    def __iter__(self) -> Iterator[GovernmentMilitaryUnit]:
        return iter(self._units)

    def __len__(self) -> int:
        return len(self._units)

    @property
    def units(self) -> tuple[GovernmentMilitaryUnit, ...]:
        return self._units

    @property
    def total_troops(self) -> float:
        return sum(unit.troops for unit in self._units)

    def require(self, node_id: str) -> GovernmentMilitaryUnit:
        try:
            return self._by_node[node_id]
        except KeyError as error:
            raise KeyError(f"no garrison at {node_id!r}") from error

    def check_invariants(self) -> None:
        for unit in self._units:
            unit.check_balances()


class ArmedBand(LedgerAgent):
    """An armed group: size, food, arms, mobility, cohesion, network, territorial access.

    The identity of a band is its id, not a person: bands are created and dissolved by rules, and
    consolidation into larger organizations is something the phase observes rather than names.
    """

    band_id: str = Field(pattern=r"^band-[a-z0-9-]+$", max_length=64)
    node_id: str = Field(pattern=NODE_ID_PATTERN, max_length=64)
    troops: float = Field(
        default=0.0,
        ge=0,
        description=(
            "members; a band is created empty and filled by a logged inflow, and one emptied by "
            "suppression is dissolved in the same tick"
        ),
    )
    grain_shi: float = Field(default=0.0, ge=0)
    arms_units: float = Field(default=0.0, ge=0)
    mobility: float = Field(default=0.5, ge=0, le=1)
    cohesion: float = Field(default=0.5, ge=0, le=1)
    network: float = Field(
        default=0.0, ge=0, le=1, description="ties into the surrounding population"
    )
    territorial_access: tuple[str, ...] = Field(
        default=(), description="nodes this band can operate in, in canonical order"
    )

    _intake: float = PrivateAttr(default=0.0)

    @property
    def ledger_name(self) -> str:
        return self.band_id

    def take_intake(self) -> float:
        """Members absorbed since the last reading, then forget them.

        A band that takes in a large body of strangers this month is not the same band next
        month, and the system that reads this uses it to hold cohesion down accordingly.
        """
        intake = self._intake
        self._intake = 0.0
        return intake

    @property
    def arms_per_member(self) -> float:
        return self.arms_units / self.troops if self.troops > 0 else 0.0

    def model_post_init(self, _context: object) -> None:
        super().model_post_init(_context)
        if tuple(sorted(set(self.territorial_access))) != self.territorial_access:
            raise ValueError("territorial access must be unique and in canonical order")

    # ------------------------------------------------------------------ transitions

    def record_raid(
        self,
        *,
        grain_shi: float,
        arms_units: float,
        victim_id: str,
        rule_version: str = BAND_RULE_VERSION,
    ) -> MilitaryEvent:
        """Take food and war material from the surrounding population.

        A band holds no treasury: what it takes that is not food becomes arms, at the conversion
        the run declares. This is an abstraction, not a tactic.
        """
        self._apply(
            grain=grain_shi,
            arms=arms_units,
            impacts=((GRAIN_DELTA, grain_shi), (ARMS_DELTA, arms_units)),
        )
        return MilitaryEvent(
            event_type=MilitaryEventType.BAND_RAID,
            rule_version=rule_version,
            trigger={
                "raided_grain_shi": grain_shi,
                "raided_arms_units": arms_units,
                GRAIN_DELTA: grain_shi,
                ARMS_DELTA: arms_units,
                "grain_shi": self.grain_shi,
            },
            outcome=f"raided:{victim_id}",
        )

    def eat(self, *, grain_shi: float, rule_version: str = BAND_RULE_VERSION) -> MilitaryEvent:
        eaten = min(grain_shi, self.grain_shi)
        self._apply(grain=-eaten, impacts=((GRAIN_DELTA, -eaten),))
        return MilitaryEvent(
            event_type=MilitaryEventType.FOOD_CONSUMED,
            rule_version=rule_version,
            trigger={
                "food_need_shi": grain_shi,
                "food_eaten_shi": eaten,
                "food_shortfall_shi": max(0.0, grain_shi - eaten),
                GRAIN_DELTA: -eaten,
                "grain_shi": self.grain_shi,
            },
            outcome="fed" if eaten >= grain_shi else "hungry",
        )

    def receive_grain(
        self, *, grain_shi: float, source: str, rule_version: str = BAND_RULE_VERSION
    ) -> MilitaryEvent:
        self._apply(grain=grain_shi, impacts=((GRAIN_DELTA, grain_shi),))
        return MilitaryEvent(
            event_type=MilitaryEventType.BAND_STORES,
            rule_version=rule_version,
            trigger={"grain_received_shi": grain_shi, GRAIN_DELTA: grain_shi},
            outcome=f"grain-from:{source}",
        )

    def adopt(
        self,
        *,
        troops: float,
        grain_shi: float = 0.0,
        arms_units: float = 0.0,
        source: str,
        rule_version: str = BAND_RULE_VERSION,
    ) -> MilitaryEvent:
        """Take in the members, food and arms a band starts with.

        A band is always created empty and filled by this call, so its opening strength is a logged
        inflow like every later one, and the band's books reconcile from zero like everyone else's.
        It is not an intake for cohesion: the founding members are the band, not strangers absorbed
        into one.
        """
        self._apply(
            troops=troops,
            grain=grain_shi,
            arms=arms_units,
            impacts=((TROOPS_DELTA, troops), (GRAIN_DELTA, grain_shi), (ARMS_DELTA, arms_units)),
        )
        return MilitaryEvent(
            event_type=MilitaryEventType.LEVY,
            rule_version=rule_version,
            trigger={
                "troops_joined": troops,
                "grain_received_shi": grain_shi,
                "arms_gained_units": arms_units,
                TROOPS_DELTA: troops,
                GRAIN_DELTA: grain_shi,
                ARMS_DELTA: arms_units,
                "troops": self.troops,
                f"source_is_{source}": 1.0,
            },
            outcome=f"formed-from:{source}",
        )

    def take_grain(
        self,
        *,
        grain_shi: float,
        destination: str,
        reason: str,
        rule_version: str = BAND_RULE_VERSION,
    ) -> MilitaryEvent:
        """Give up grain: to a splinter, a merging band, or nobody at all on dispersal."""
        taken = min(grain_shi, self.grain_shi)
        if taken <= 0.0:
            raise ValueError("a band must give up at least one shi of grain")
        self._apply(grain=-taken, impacts=((GRAIN_DELTA, -taken),))
        return MilitaryEvent(
            event_type=MilitaryEventType.BAND_STORES,
            rule_version=rule_version,
            trigger={
                "grain_given_shi": taken,
                GRAIN_DELTA: -taken,
                "grain_shi": self.grain_shi,
            },
            outcome=f"{reason}-to:{destination}",
        )

    def drop_arms(
        self, *, arms_units: float, reason: str, rule_version: str = BAND_RULE_VERSION
    ) -> MilitaryEvent:
        """Give up war material without giving up people."""
        dropped = min(arms_units, self.arms_units)
        if dropped <= 0.0:
            raise ValueError("a band must give up at least one unit of arms")
        self._apply(arms=-dropped, impacts=((ARMS_DELTA, -dropped),))
        return MilitaryEvent(
            event_type=MilitaryEventType.BAND_DISSOLVED,
            rule_version=rule_version,
            trigger={
                "arms_dropped_units": dropped,
                ARMS_DELTA: -dropped,
                "arms_units": self.arms_units,
            },
            outcome=reason,
        )

    def gain_members(
        self,
        *,
        troops: float,
        source: str,
        arms_units: float = 0.0,
        rule_version: str = BAND_RULE_VERSION,
    ) -> MilitaryEvent:
        self._apply(
            troops=troops,
            arms=arms_units,
            impacts=((TROOPS_DELTA, troops), (ARMS_DELTA, arms_units)),
        )
        self._intake += troops
        return MilitaryEvent(
            event_type=MilitaryEventType.LEVY,
            rule_version=rule_version,
            trigger={
                "troops_joined": troops,
                "arms_gained_units": arms_units,
                TROOPS_DELTA: troops,
                "troops": self.troops,
                f"source_is_{source}": 1.0,
            },
            outcome=f"joined-from:{source}",
        )

    def lose_members(
        self,
        *,
        troops: float,
        arms_units: float,
        destination: str,
        reason: str,
        rule_version: str = BAND_RULE_VERSION,
    ) -> MilitaryEvent:
        gone = min(troops, self.troops)
        arms_gone = min(arms_units, self.arms_units)
        self._apply(
            troops=-gone,
            arms=-arms_gone,
            impacts=((TROOPS_DELTA, -gone), (ARMS_DELTA, -arms_gone)),
        )
        return MilitaryEvent(
            event_type=MilitaryEventType.DESERTION,
            rule_version=rule_version,
            trigger={
                "troops_left": gone,
                "arms_lost_units": arms_gone,
                TROOPS_DELTA: -gone,
                "troops": self.troops,
                f"destination_is_{destination}": 1.0,
            },
            outcome=f"{reason}-to:{destination}",
        )

    def update_standing(
        self,
        *,
        cohesion_delta: float = 0.0,
        mobility_delta: float = 0.0,
        network_delta: float = 0.0,
        cohesion_ceiling: float = 1.0,
        rule_version: str = BAND_RULE_VERSION,
    ) -> MilitaryEvent:
        self.cohesion = min(_bounded(self.cohesion + cohesion_delta), cohesion_ceiling)
        self.mobility = _bounded(self.mobility + mobility_delta)
        self.network = _bounded(self.network + network_delta)
        return MilitaryEvent(
            event_type=MilitaryEventType.BAND_STANDING,
            rule_version=rule_version,
            trigger={
                "cohesion": self.cohesion,
                "mobility": self.mobility,
                "network": self.network,
                "cohesion_delta": cohesion_delta,
                "mobility_delta": mobility_delta,
                "network_delta": network_delta,
                "cohesion_ceiling": cohesion_ceiling,
            },
            outcome="standing-updated",
        )

    def move_to(
        self, *, node_id: str, access: tuple[str, ...], rule_version: str = BAND_RULE_VERSION
    ) -> MilitaryEvent:
        previous = self.node_id
        self.node_id = node_id
        self.territorial_access = access
        return MilitaryEvent(
            event_type=MilitaryEventType.BAND_MOVE,
            rule_version=rule_version,
            trigger={
                "mobility": self.mobility,
                "access_nodes": float(len(access)),
                "troops": self.troops,
            },
            outcome=f"moved:{previous}->{node_id}",
        )

    def state(self, *, rule_version: str = BAND_RULE_VERSION) -> MilitaryEvent:
        return MilitaryEvent(
            event_type=MilitaryEventType.BAND_STATE,
            rule_version=rule_version,
            trigger={
                "troops": self.troops,
                "grain_shi": self.grain_shi,
                "arms_units": self.arms_units,
                "arms_per_member": self.arms_per_member,
                "mobility": self.mobility,
                "cohesion": self.cohesion,
                "network": self.network,
                "access_nodes": float(len(self.territorial_access)),
            },
            outcome="band-state",
        )


class BandLayer:
    """The armed bands that currently exist, in a fixed order."""

    def __init__(self, bands: Sequence[ArmedBand] = ()) -> None:
        self._bands = tuple(sorted(bands, key=lambda band: band.band_id))
        ids = [band.band_id for band in self._bands]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate band ids: {', '.join(sorted(ids))}")
        self._by_id = MappingProxyType({band.band_id: band for band in self._bands})
        self._next_index = len(self._bands)

    def __iter__(self) -> Iterator[ArmedBand]:
        return iter(self._bands)

    def __len__(self) -> int:
        return len(self._bands)

    @property
    def bands(self) -> tuple[ArmedBand, ...]:
        return self._bands

    @property
    def total_troops(self) -> float:
        return sum(band.troops for band in self._bands)

    def at_node(self, node_id: str) -> tuple[ArmedBand, ...]:
        return tuple(band for band in self._bands if band.node_id == node_id)

    def require(self, band_id: str) -> ArmedBand:
        try:
            return self._by_id[band_id]
        except KeyError as error:
            raise KeyError(f"unknown band {band_id!r}") from error

    def next_id(self) -> str:
        """A fresh band id; identity is a sequence number, never a person's name."""
        self._next_index += 1
        return f"band-{self._next_index:04d}"

    def add(self, band: ArmedBand) -> None:
        if band.band_id in self._by_id:
            raise ValueError(f"band {band.band_id!r} already exists")
        self._bands = tuple(sorted((*self._bands, band), key=lambda item: item.band_id))
        self._by_id = MappingProxyType({item.band_id: item for item in self._bands})

    def remove(self, band_id: str) -> None:
        self.require(band_id)
        self._bands = tuple(band for band in self._bands if band.band_id != band_id)
        self._by_id = MappingProxyType({band.band_id: band for band in self._bands})

    def check_invariants(self) -> None:
        for band in self._bands:
            band.check_balances()
