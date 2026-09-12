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

__all__ = [
    "RESOURCE_AGRICULTURE",
    "RESOURCE_BAND_STANDING",
    "RESOURCE_BAND_STORES",
    "RESOURCE_BAND_TROOPS",
    "RESOURCE_CLIMATE",
    "RESOURCE_COHORT_ADULTS",
    "RESOURCE_COHORT_ASSETS",
    "RESOURCE_COHORT_DEBT",
    "RESOURCE_COHORT_GRAIN",
    "RESOURCE_COHORT_HOUSEHOLDS",
    "RESOURCE_COHORT_LAND",
    "RESOURCE_COHORT_SILVER",
    "RESOURCE_COHORT_TAX_ARREARS",
    "RESOURCE_COUNTY_ARREARS",
    "RESOURCE_COUNTY_GRANARY",
    "RESOURCE_COUNTY_TREASURY",
    "RESOURCE_DISTRESS_WINDOW",
    "RESOURCE_ELITE_GRAIN",
    "RESOURCE_ELITE_LAND",
    "RESOURCE_ELITE_SILVER",
    "RESOURCE_MARKET_PRICE",
    "RESOURCE_MERCHANT_STOCK",
    "RESOURCE_MIGRANTS",
    "RESOURCE_UNIT_PAY",
    "RESOURCE_UNIT_STANDING",
    "RESOURCE_UNIT_STORES",
    "RESOURCE_UNIT_TROOPS",
    "TICK_ORDER_VERSION",
    "System",
    "TickContext",
    "TickPhase",
]

#: Version of the tick-phase contract. Bump when phases are added, removed or reordered.
TICK_ORDER_VERSION: Final[str] = "tick-order-v1"

#: The vocabulary of shared state a system may claim to read or write. It is the common
#: language of the phase-level dependency claim checked by :mod:`late_ming_lab.core.scheduler`:
#: every writer of a resource must run at or before every reader of it.
RESOURCE_CLIMATE: Final[str] = "climate.shock"
RESOURCE_AGRICULTURE: Final[str] = "agriculture.state"
RESOURCE_COHORT_GRAIN: Final[str] = "cohort.grain"
RESOURCE_COHORT_SILVER: Final[str] = "cohort.silver"
RESOURCE_COHORT_LAND: Final[str] = "cohort.land"
RESOURCE_COHORT_DEBT: Final[str] = "cohort.debt"
RESOURCE_COHORT_ASSETS: Final[str] = "cohort.assets"
RESOURCE_COHORT_ADULTS: Final[str] = "cohort.adults"
RESOURCE_COHORT_HOUSEHOLDS: Final[str] = "cohort.households"
RESOURCE_COHORT_TAX_ARREARS: Final[str] = "cohort.tax_arrears"
RESOURCE_MARKET_PRICE: Final[str] = "market.price"
RESOURCE_MERCHANT_STOCK: Final[str] = "merchant.stock"
RESOURCE_ELITE_GRAIN: Final[str] = "elite.grain"
RESOURCE_ELITE_SILVER: Final[str] = "elite.silver"
RESOURCE_ELITE_LAND: Final[str] = "elite.land"
RESOURCE_COUNTY_TREASURY: Final[str] = "county.silver"
RESOURCE_COUNTY_GRANARY: Final[str] = "county.granary"
RESOURCE_COUNTY_ARREARS: Final[str] = "county.arrears"
RESOURCE_UNIT_TROOPS: Final[str] = "unit.troops"
RESOURCE_UNIT_STORES: Final[str] = "unit.stores"
RESOURCE_UNIT_PAY: Final[str] = "unit.pay_arrears"
RESOURCE_UNIT_STANDING: Final[str] = "unit.standing"
RESOURCE_BAND_TROOPS: Final[str] = "band.troops"
RESOURCE_BAND_STORES: Final[str] = "band.stores"
RESOURCE_BAND_STANDING: Final[str] = "band.standing"
RESOURCE_MIGRANTS: Final[str] = "migration.migrants"
RESOURCE_DISTRESS_WINDOW: Final[str] = "household.distress_window"


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

    ``reads`` and ``writes`` are the phase-level dependency claim the system makes: which shared
    resources of this module's vocabulary it consumes and produces in one tick. The claim is not
    a field-level dataflow analysis — it names the resources whose tick order matters, and
    :mod:`late_ming_lab.core.scheduler` refuses a registration whose reader runs before the
    earliest writer of a resource it reads.
    """

    name: str
    phase: TickPhase
    reads: frozenset[str]
    writes: frozenset[str]

    def step(self, ctx: TickContext) -> None: ...
