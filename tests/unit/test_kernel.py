"""Kernel contract: tick frame, phase ordering, stream isolation, no global randomness."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import numpy as np
import pytest

from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import MACRO_COLUMNS, TICK_EVENT_TYPE, SimulationKernel
from late_ming_lab.core.rng import RngStream
from late_ming_lab.core.tick import TICK_ORDER_VERSION, TickContext, TickPhase


@dataclass(slots=True)
class _DrawSystem:
    """A test-only system: no history, just a draw recorded in the event log."""

    name: str = "test-draw"
    phase: TickPhase = TickPhase.HOUSEHOLD_CONSUMPTION
    calls: list[tuple[int, float]] = field(default_factory=list)

    def step(self, ctx: TickContext) -> None:
        draw = ctx.rng.draw(RngStream.HOUSEHOLD)
        self.calls.append((ctx.tick, draw))
        ctx.emit(
            "TEST_DRAW",
            phase="household_consumption",
            rng_stream=RngStream.HOUSEHOLD,
            rng_draw=draw,
            rule_version="test-draw-v1",
            trigger={"tick": float(ctx.tick)},
            outcome=ctx.period.value,
        )


@dataclass(slots=True)
class _OtherSystem:
    name: str = "test-other"
    phase: TickPhase = TickPhase.BOOKKEEPING

    def step(self, ctx: TickContext) -> None:
        ctx.emit("TEST_OTHER", phase="bookkeeping")


def _config(**overrides: object) -> SimulationConfig:
    return SimulationConfig.model_validate({"tick_count": 4, "warmup_ticks": 2, **overrides})


def test_tick_order_is_versioned_and_ordered() -> None:
    phases = list(TickPhase)

    assert TICK_ORDER_VERSION == "tick-order-v1"
    assert [phase.value for phase in phases] == list(range(1, len(phases) + 1))
    assert [phase.token for phase in phases[:3]] == [
        "climate_update",
        "agricultural_state",
        "grain_production",
    ]
    assert phases[-1].token == "data_collection"


def test_kernel_records_one_clock_marker_per_tick() -> None:
    result = SimulationKernel(_config()).run()
    events = result.events

    assert events.height == 4
    assert events["event_type"].to_list() == [TICK_EVENT_TYPE] * 4
    assert events["tick"].to_list() == [0, 1, 2, 3]
    assert events["seq"].to_list() == [0, 1, 2, 3]
    assert events["phase"].to_list() == [TickPhase.BOOKKEEPING.token] * 4
    assert events["outcome"].to_list() == ["warmup", "warmup", "shock", "shock"]
    assert events["rng_draw"].to_list() == [None] * 4


def test_kernel_emits_the_macro_index_frame() -> None:
    result = SimulationKernel(_config()).run()
    macro = result.macro

    assert macro.columns == list(MACRO_COLUMNS)
    assert macro["month"].to_list() == ["1625-01", "1625-02", "1625-03", "1625-04"]
    assert macro["year"].to_list() == [1625] * 4
    assert macro["month_of_year"].to_list() == [1, 2, 3, 4]
    assert macro["period"].to_list() == ["warmup", "warmup", "shock", "shock"]


def test_systems_run_inside_the_tick_in_registration_order() -> None:
    draw = _DrawSystem()
    other = _OtherSystem()
    result = SimulationKernel(_config(), [draw, other]).run()

    assert result.events["event_type"].to_list() == [
        TICK_EVENT_TYPE,
        "TEST_DRAW",
        "TEST_OTHER",
        TICK_EVENT_TYPE,
        "TEST_DRAW",
        "TEST_OTHER",
        TICK_EVENT_TYPE,
        "TEST_DRAW",
        "TEST_OTHER",
        TICK_EVENT_TYPE,
        "TEST_DRAW",
        "TEST_OTHER",
    ]
    assert len(draw.calls) == 4


def test_systems_must_follow_the_versioned_tick_order() -> None:
    with pytest.raises(ValueError, match="versioned tick order"):
        SimulationKernel(_config(), [_OtherSystem(), _DrawSystem()])
    with pytest.raises(ValueError, match="duplicate system name"):
        SimulationKernel(_config(), [_DrawSystem(), _DrawSystem(name="test-draw")])
    with pytest.raises(ValueError, match="must not be empty"):
        SimulationKernel(_config(), [_DrawSystem(name="")])


def test_systems_see_a_consistent_tick_context() -> None:
    seen: list[tuple[int, str, str, str]] = []

    class _Inspector:
        name = "test-inspector"
        phase = TickPhase.DATA_COLLECTION

        def step(self, ctx: TickContext) -> None:
            seen.append((ctx.tick, str(ctx.month), ctx.period.value, str(ctx.config.root_seed)))

    result = SimulationKernel(_config(root_seed=99), [_Inspector()]).run()

    assert seen == [
        (0, "1625-01", "warmup", "99"),
        (1, "1625-02", "warmup", "99"),
        (2, "1625-03", "shock", "99"),
        (3, "1625-04", "shock", "99"),
    ]
    assert result.summary.event_count == 4


def test_kernel_never_touches_global_randomness() -> None:
    random.seed(1234)
    python_state = random.getstate()
    numpy_state = np.random.get_state()

    SimulationKernel(_config(), [_DrawSystem()]).run()

    assert random.getstate() == python_state
    assert np.random.get_state()[1].tolist() == numpy_state[1].tolist()


def test_same_seed_replays_systems_exactly() -> None:
    first = SimulationKernel(_config(), [_DrawSystem()]).run()
    second = SimulationKernel(_config(), [_DrawSystem()]).run()
    other = SimulationKernel(_config(root_seed=1), [_DrawSystem()]).run()

    assert first.summary.simulation_digest == second.summary.simulation_digest
    assert first.events.equals(second.events)
    assert first.summary.simulation_digest != other.summary.simulation_digest


def test_kernel_uses_the_configured_window_only() -> None:
    kernel = SimulationKernel(_config(tick_count=240, warmup_ticks=24))

    assert kernel.clock.tick_count == 240
    assert str(kernel.clock.end) == "1644-12"
    assert kernel.systems == ()
