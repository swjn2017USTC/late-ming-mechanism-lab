"""The monthly simulation clock.

One tick is one calendar month. The window is fixed by :class:`SimulationConfig`; ticks are
zero-based and the leading ``warmup_ticks`` are the baseline period, after which the model
enters the shock period. Month arithmetic is pure integer arithmetic: no calendar library,
no timezone, no wall clock.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from late_ming_lab.core.config import SimulationConfig

MONTHS_PER_YEAR: Final[int] = 12


class Period(StrEnum):
    """Which part of the window a tick belongs to."""

    WARMUP = "warmup"
    SHOCK = "shock"


class TickOutOfRange(ValueError):
    """Raised when a tick or month lies outside the simulation window."""


class Month(BaseModel):
    """A calendar month, ordered by its absolute index."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    year: int = Field(ge=1, le=9999)
    month: int = Field(ge=1, le=12)

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def index(self) -> int:
        """Absolute month index; consecutive months differ by exactly one."""
        return self.year * MONTHS_PER_YEAR + (self.month - 1)

    @classmethod
    def from_index(cls, index: int) -> Month:
        if index < MONTHS_PER_YEAR:
            raise ValueError(f"month index {index} precedes year 1")
        year, zero_based_month = divmod(index, MONTHS_PER_YEAR)
        return cls(year=year, month=zero_based_month + 1)

    def plus_months(self, months: int) -> Month:
        if months < 0:
            raise ValueError(f"months must be non-negative, got {months}")
        return Month.from_index(self.index + months)

    def offset_from(self, other: Month) -> int:
        """Signed number of months from ``other`` to ``self``."""
        return self.index - other.index


class Clock(BaseModel):
    """Deterministic iterator over the monthly ticks of one run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: Month
    tick_count: int = Field(ge=1)
    warmup_ticks: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_window(self) -> Clock:
        if self.warmup_ticks > self.tick_count:
            raise ValueError(
                f"warmup_ticks ({self.warmup_ticks}) must not exceed tick_count ({self.tick_count})"
            )
        return self

    @classmethod
    def from_config(cls, config: SimulationConfig) -> Clock:
        return cls(
            start=Month(year=config.start_year, month=config.start_month),
            tick_count=config.tick_count,
            warmup_ticks=config.warmup_ticks,
        )

    @property
    def ticks(self) -> range:
        """The tick indices of this window, in order."""
        return range(self.tick_count)

    @property
    def end(self) -> Month:
        """Last month of the window."""
        return self.month_at(self.tick_count - 1)

    def month_at(self, tick: int) -> Month:
        if not 0 <= tick < self.tick_count:
            raise TickOutOfRange(f"tick {tick} outside [0, {self.tick_count})")
        return self.start.plus_months(tick)

    def tick_of(self, month: Month) -> int:
        offset = month.offset_from(self.start)
        if not 0 <= offset < self.tick_count:
            raise TickOutOfRange(f"month {month} outside [{self.start}, {self.end}]")
        return offset

    def period_at(self, tick: int) -> Period:
        self.month_at(tick)  # range check
        return Period.WARMUP if tick < self.warmup_ticks else Period.SHOCK

    def contains(self, month: Month) -> bool:
        return 0 <= month.offset_from(self.start) < self.tick_count
