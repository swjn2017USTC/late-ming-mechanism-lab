"""Event contract: immutable, canonically serialized, replayable through Parquet."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from late_ming_lab.core.clock import TickOutOfRange
from late_ming_lab.core.events import (
    EVENT_COLUMNS,
    Event,
    EventLogger,
    events_from_frame,
    events_to_frame,
)
from late_ming_lab.core.rng import RngStream
from late_ming_lab.storage.tables import read_table, write_table


def _migration_event(seq: int = 3) -> Event:
    return Event(
        seq=seq,
        tick=87,
        event_type="HOUSEHOLD_MIGRATION",
        phase="migration",
        agent_id="cohort-17",
        region="R17",
        rule_version="migration-v3",
        rng_stream=RngStream.MIGRATION,
        rng_draw=0.184,
        trigger={"subsistence_gap": 0.31, "debt_ratio": 1.8},
        outcome="MIGRATE_R17_R19",
    )


def test_events_are_immutable() -> None:
    event = _migration_event()

    with pytest.raises(ValidationError):
        event.tick = 88
    with pytest.raises(TypeError):
        event.trigger["subsistence_gap"] = 0.9  # type: ignore[index]


def test_trigger_serialization_ignores_insertion_order() -> None:
    first = Event(seq=0, tick=0, event_type="A", trigger={"b": 2.0, "a": 1.0})
    second = Event(seq=0, tick=0, event_type="A", trigger={"a": 1.0, "b": 2.0})

    assert first == second
    assert first.to_json() == second.to_json()
    assert first.trigger_json == '{"a":1.0,"b":2.0}'


def test_malformed_events_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Event(seq=0, tick=0, event_type="lowercase")
    with pytest.raises(ValidationError):
        Event(seq=0, tick=0, event_type="TICK", phase="Migration")
    with pytest.raises(ValidationError):
        Event(seq=0, tick=0, event_type="TICK", rng_draw=1.0)
    with pytest.raises(ValidationError):
        Event(seq=0, tick=0, event_type="TICK", rng_draw=-0.1)


def test_events_round_trip_through_json() -> None:
    event = _migration_event()

    restored = Event.from_json(event.to_json())

    assert restored == event
    assert dict(restored.trigger) == {"subsistence_gap": 0.31, "debt_ratio": 1.8}


def test_events_round_trip_through_parquet(tmp_path: Path) -> None:
    events = [_migration_event(seq=0), Event(seq=1, tick=0, event_type="TICK")]
    path = tmp_path / "agent_events.parquet"

    write_table(path, events_to_frame(events))
    restored = events_from_frame(read_table(path))

    assert restored == tuple(events)
    assert [event.to_json() for event in restored] == [event.to_json() for event in events]


def test_event_frames_declare_their_columns() -> None:
    frame = events_to_frame([])

    assert frame.columns == list(EVENT_COLUMNS)
    assert frame.height == 0


def test_incomplete_frames_are_rejected() -> None:
    with pytest.raises(ValueError, match="missing columns"):
        events_from_frame(pl.DataFrame({"seq": [0]}))


def test_logger_numbers_events_in_emission_order() -> None:
    logger = EventLogger(tick_count=3)

    logger.emit(tick=0, event_type="TICK")
    logger.emit(tick=1, event_type="TICK")
    logger.emit(tick=1, event_type="TICK")

    assert [event.seq for event in logger.events] == [0, 1, 2]
    assert [event.key for event in logger.events] == [(0, 0), (1, 1), (1, 2)]
    assert len(logger) == 3


def test_logger_rejects_out_of_window_and_backwards_ticks() -> None:
    logger = EventLogger(tick_count=3)
    logger.emit(tick=2, event_type="TICK")

    with pytest.raises(TickOutOfRange):
        logger.emit(tick=3, event_type="TICK")
    with pytest.raises(ValueError, match="non-decreasing"):
        logger.emit(tick=1, event_type="TICK")

    with pytest.raises(ValueError, match="tick_count"):
        EventLogger(tick_count=0)


def test_logger_frame_is_ordered_and_typed() -> None:
    logger = EventLogger(tick_count=2)
    logger.emit(tick=0, event_type="TICK")
    logger.emit(tick=1, event_type="HOUSEHOLD_MIGRATION", rng_draw=0.25)

    frame = logger.to_frame()

    assert frame["seq"].to_list() == [0, 1]
    assert frame["event_type"].to_list() == ["TICK", "HOUSEHOLD_MIGRATION"]
    assert frame["rng_draw"].to_list() == [None, 0.25]
    assert events_from_frame(frame) == logger.events


def test_event_json_is_canonical() -> None:
    event = _migration_event()
    payload = json.loads(event.to_json())

    assert payload["rng_stream"] == "migration"
    assert payload["trigger"] == {"subsistence_gap": 0.31, "debt_ratio": 1.8}
    assert event.to_json() == json.dumps(payload, sort_keys=True, separators=(",", ":"))


def test_events_for_tick_exposes_only_that_tick_in_order() -> None:
    logger = EventLogger(tick_count=3)
    logger.emit(tick=0, event_type="TICK")
    logger.emit(tick=1, event_type="HOUSEHOLD_MIGRATION", region="R1")
    logger.emit(tick=1, event_type="LAND_SALE", region="R2")
    logger.emit(tick=2, event_type="TICK")

    assert [event.event_type for event in logger.events_for_tick(1)] == [
        "HOUSEHOLD_MIGRATION",
        "LAND_SALE",
    ]
    assert logger.events_for_tick(0) == (logger.events[0],)
    with pytest.raises(TickOutOfRange):
        logger.events_for_tick(3)
