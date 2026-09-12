"""Clock contract: the 240-month window, warm-up boundary and pure month arithmetic."""

from __future__ import annotations

import pytest

from late_ming_lab.core.clock import Clock, Month, Period, TickOutOfRange
from late_ming_lab.core.config import SimulationConfig


def _default_clock() -> Clock:
    return Clock.from_config(SimulationConfig())


def test_window_spans_1625_01_to_1644_12() -> None:
    clock = _default_clock()

    assert clock.tick_count == 240
    assert str(clock.start) == "1625-01"
    assert str(clock.end) == "1644-12"
    assert [str(clock.month_at(tick)) for tick in (0, 11, 12, 239)] == [
        "1625-01",
        "1625-12",
        "1626-01",
        "1644-12",
    ]


def test_warmup_covers_1625_and_1626_only() -> None:
    clock = _default_clock()

    assert clock.period_at(0) is Period.WARMUP
    assert clock.period_at(23) is Period.WARMUP
    assert clock.period_at(24) is Period.SHOCK
    assert str(clock.month_at(24)) == "1627-01"
    assert clock.period_at(239) is Period.SHOCK


def test_ticks_and_months_are_inverse() -> None:
    clock = _default_clock()

    for tick in (0, 5, 137, 239):
        assert clock.tick_of(clock.month_at(tick)) == tick
    assert clock.contains(clock.end)
    assert not clock.contains(clock.end.plus_months(1))


def test_out_of_window_ticks_and_months_are_rejected() -> None:
    clock = _default_clock()

    for tick in (-1, 240):
        with pytest.raises(TickOutOfRange):
            clock.month_at(tick)
        with pytest.raises(TickOutOfRange):
            clock.period_at(tick)
    for month in (Month(year=1624, month=12), Month(year=1645, month=1)):
        with pytest.raises(TickOutOfRange):
            clock.tick_of(month)


def test_month_arithmetic_crosses_year_boundaries() -> None:
    assert str(Month(year=1625, month=12).plus_months(1)) == "1626-01"
    assert str(Month(year=1644, month=12).plus_months(0)) == "1644-12"
    assert Month(year=1625, month=1).offset_from(Month(year=1624, month=1)) == 12
    for index in (1625 * 12 + 0, 1625 * 12 + 11, 1644 * 12 + 11):
        assert Month.from_index(index).index == index
    with pytest.raises(ValueError, match="non-negative"):
        Month(year=1625, month=1).plus_months(-1)
    with pytest.raises(ValueError, match="precedes year 1"):
        Month.from_index(0)


def test_clock_rejects_a_warmup_longer_than_the_window() -> None:
    with pytest.raises(ValueError, match="warmup_ticks"):
        Clock(start=Month(year=1625, month=1), tick_count=10, warmup_ticks=11)
