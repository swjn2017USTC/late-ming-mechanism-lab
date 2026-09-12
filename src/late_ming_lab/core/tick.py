"""Explicit, versioned tick order and the per-tick system interface.

One tick is one month. The seventeen phases below are part of the model contract: they are
declared here, versioned, and enforced by the kernel on registration, so the order is never
decided incidentally by a framework's default scheduling (see
``docs/architecture/system-overview.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Final, Protocol

from late_ming_lab.core.clock import Clock, Month, Period
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.events import Event, EventLogger
from late_ming_lab.core.rng import RngStreams

#: Version of the tick-phase contract. Bump when phases are added, removed or reordered.
TICK_ORDER_VERSION: Final[str] = "tick-order-v1"


class TickPhase(IntEnum):
    """The ordered phases of one monthly tick."""

    CLIMATE_UPDATE = 1
    AGRICULTURAL_STATE = 2
    GRAIN_PRODUCTION = 3
    HOUSEHOLD_CONSUMPTION = 4
    MARKET_CLEARING = 5
    CREDIT_AND_DEBT = 6
    TAXATION = 7
    RELIEF = 8
    MIGRATION = 9
    MILITARY_FINANCE = 10
    DESERTION = 11
    ARMED_RECRUITMENT = 12
    ARMED_MOVEMENT = 13
    VIOLENCE_CONSEQUENCES = 14
    INSTITUTIONAL_DECISIONS = 15
    BOOKKEEPING = 16
    DATA_COLLECTION = 17

    @property
    def token(self) -> str:
        """Lowercase token recorded in the event log."""
        return self.name.lower()


@dataclass(frozen=True, slots=True)
class TickContext:
    """Everything a system may read or write during one tick."""

    config: SimulationConfig
    clock: Clock
    tick: int
    month: Month
    period: Period
    rng: RngStreams
    logger: EventLogger

    def emit(self, event_type: str, **fields: Any) -> Event:
        """Record an event at this tick."""
        return self.logger.emit(tick=self.tick, event_type=event_type, **fields)


class System(Protocol):
    """A simulation system registered to exactly one tick phase.

    P01 ships no domain systems: the protocol exists so that later phases plug mechanisms
    into a fixed, versioned order instead of inventing their own scheduling.
    """

    name: str
    phase: TickPhase

    def step(self, ctx: TickContext) -> None: ...
