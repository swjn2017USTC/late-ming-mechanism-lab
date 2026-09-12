"""Immutable, replayable event representation.

The event log is a first-class artifact: any state change that matters must be explainable
from it — tick, event, agent, region, trigger values, rule version, RNG draw, outcome
(RULES 14, 15). Events are frozen, ordered by ``(tick, seq)``, identity-stable under
canonical JSON, and round-trip through Parquet without loss.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any, Final

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from late_ming_lab.core.clock import TickOutOfRange
from late_ming_lab.core.hashing import canonical_json
from late_ming_lab.core.rng import RngStream

EVENT_TYPE_PATTERN = r"^[A-Z][A-Z0-9_]*$"
PHASE_PATTERN = r"^[a-z][a-z0-9_]*$"

#: Physical column order of the event Parquet artifact.
EVENT_COLUMNS: Final[tuple[str, ...]] = (
    "seq",
    "tick",
    "event_type",
    "phase",
    "agent_id",
    "region",
    "rule_version",
    "rng_stream",
    "rng_draw",
    "trigger_json",
    "outcome",
)

EVENT_SCHEMA: Final[dict[str, pl.DataType]] = {
    "seq": pl.Int64(),
    "tick": pl.Int64(),
    "event_type": pl.String(),
    "phase": pl.String(),
    "agent_id": pl.String(),
    "region": pl.String(),
    "rule_version": pl.String(),
    "rng_stream": pl.String(),
    "rng_draw": pl.Float64(),
    "trigger_json": pl.String(),
    "outcome": pl.String(),
}


class Event(BaseModel):
    """One immutable, replayable simulation event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int = Field(ge=0, description="Global emission order; fixes replay ordering exactly.")
    tick: int = Field(ge=0)
    event_type: str = Field(pattern=EVENT_TYPE_PATTERN, max_length=64)
    phase: str | None = Field(default=None, pattern=PHASE_PATTERN, max_length=64)
    agent_id: str | None = None
    region: str | None = None
    rule_version: str | None = None
    rng_stream: RngStream | None = None
    rng_draw: float | None = Field(default=None, ge=0.0, lt=1.0)
    trigger: Mapping[str, float] = Field(default_factory=dict)
    outcome: str | None = None

    @field_validator("trigger", mode="after")
    @classmethod
    def _freeze_trigger(cls, value: Mapping[str, float]) -> Mapping[str, float]:
        return MappingProxyType(dict(value))

    @field_serializer("trigger")
    def _serialize_trigger(self, value: Mapping[str, float]) -> dict[str, float]:
        return dict(value)

    @property
    def key(self) -> tuple[int, int]:
        return (self.tick, self.seq)

    @property
    def trigger_json(self) -> str:
        """Canonical JSON of the trigger values, as stored in Parquet."""
        return canonical_json(dict(self.trigger))

    def to_json(self) -> str:
        """Canonical JSON; the digest and replay unit of an event."""
        return canonical_json(self.model_dump(mode="json"))

    @classmethod
    def from_json(cls, text: str) -> Event:
        return cls.model_validate_json(text)


def events_to_frame(events: Iterable[Event]) -> pl.DataFrame:
    """Convert events to the Parquet-ready frame with an explicit schema."""
    rows = [
        (
            event.seq,
            event.tick,
            event.event_type,
            event.phase,
            event.agent_id,
            event.region,
            event.rule_version,
            None if event.rng_stream is None else event.rng_stream.value,
            event.rng_draw,
            event.trigger_json,
            event.outcome,
        )
        for event in events
    ]
    return pl.DataFrame(rows, schema=EVENT_SCHEMA, orient="row")


def events_from_frame(frame: pl.DataFrame) -> tuple[Event, ...]:
    """Replay events from a frame produced by :func:`events_to_frame`."""
    missing = [column for column in EVENT_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"event frame is missing columns: {', '.join(missing)}")
    events: list[Event] = []
    for row in frame.select(list(EVENT_COLUMNS)).iter_rows(named=True):
        payload: dict[str, Any] = dict(row)
        payload["trigger"] = json.loads(payload.pop("trigger_json") or "{}")
        events.append(Event.model_validate(payload))
    return tuple(events)


class EventLogger:
    """Append-only event collector for one run."""

    def __init__(self, tick_count: int) -> None:
        if tick_count < 1:
            raise ValueError(f"tick_count must be positive, got {tick_count}")
        self._tick_count = tick_count
        self._events: list[Event] = []

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def emit(
        self,
        *,
        tick: int,
        event_type: str,
        phase: str | None = None,
        agent_id: str | None = None,
        region: str | None = None,
        rule_version: str | None = None,
        rng_stream: RngStream | None = None,
        rng_draw: float | None = None,
        trigger: Mapping[str, float] | None = None,
        outcome: str | None = None,
    ) -> Event:
        """Record one event and return it.

        The emission order *is* the replay order, so out-of-window and backwards ticks are
        rejected rather than silently tolerated.
        """
        if not 0 <= tick < self._tick_count:
            raise TickOutOfRange(f"tick {tick} outside [0, {self._tick_count})")
        if self._events and tick < self._events[-1].tick:
            raise ValueError(
                f"event at tick {tick} follows tick {self._events[-1].tick}; "
                "the event log must be emitted in non-decreasing tick order"
            )
        event = Event(
            seq=len(self._events),
            tick=tick,
            event_type=event_type,
            phase=phase,
            agent_id=agent_id,
            region=region,
            rule_version=rule_version,
            rng_stream=rng_stream,
            rng_draw=rng_draw,
            trigger=dict(trigger or {}),
            outcome=outcome,
        )
        self._events.append(event)
        return event

    def to_frame(self) -> pl.DataFrame:
        return events_to_frame(self._events)

    def events_for_tick(self, tick: int) -> tuple[Event, ...]:
        """Events already emitted for ``tick``.

        Systems are coupled through the event log, not through shared mutable state: a later
        phase reads what an earlier phase recorded for the same tick.
        """
        if not 0 <= tick < self._tick_count:
            raise TickOutOfRange(f"tick {tick} outside [0, {self._tick_count})")
        collected: list[Event] = []
        for event in reversed(self._events):
            if event.tick < tick:
                break
            if event.tick == tick:
                collected.append(event)
        collected.reverse()
        return tuple(collected)
