"""The history-free deterministic simulation kernel.

P01 ships machinery and no domain mechanisms. The kernel advances the monthly clock, hands
each registered system its tick context with independent RNG streams, records the tick frame
in the event log, and produces the run manifest and summary. Historical content — counties,
households, markets, armies — arrives in later phases.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import polars as pl

from late_ming_lab.core.clock import Clock
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.events import EventLogger
from late_ming_lab.core.hashing import canonical_json, hash_records
from late_ming_lab.core.manifest import RunManifest, RunSummary
from late_ming_lab.core.rng import RngStreams
from late_ming_lab.core.tick import System, TickContext, TickPhase
from late_ming_lab.evidence.provenance import git_provenance

#: Event type of the per-tick clock marker.
TICK_EVENT_TYPE: Final[str] = "TICK"

#: Columns of the macro-layer index frame produced by P01.
MACRO_COLUMNS: Final[tuple[str, ...]] = ("tick", "month", "year", "month_of_year", "period")

MACRO_SCHEMA: Final[dict[str, pl.DataType]] = {
    "tick": pl.Int64(),
    "month": pl.String(),
    "year": pl.Int64(),
    "month_of_year": pl.Int64(),
    "period": pl.String(),
}


@dataclass(frozen=True, slots=True)
class KernelResult:
    """Everything one kernel run produced, ready to be persisted."""

    config: SimulationConfig
    manifest: RunManifest
    summary: RunSummary
    events: pl.DataFrame
    macro: pl.DataFrame


class SimulationKernel:
    """Deterministic monthly driver: clock, RNG streams, systems, event log."""

    def __init__(self, config: SimulationConfig, systems: Sequence[System] = ()) -> None:
        self._config = config
        self._clock = Clock.from_config(config)
        self._systems = _validated_systems(systems)

    @property
    def config(self) -> SimulationConfig:
        return self._config

    @property
    def clock(self) -> Clock:
        return self._clock

    @property
    def systems(self) -> tuple[System, ...]:
        return self._systems

    def run(self, run_label: str | None = None) -> KernelResult:
        """Run the window to completion and return the run artifacts."""
        started = time.perf_counter()
        config = self._config
        clock = self._clock
        rng = RngStreams(config.root_seed)
        logger = EventLogger(tick_count=clock.tick_count)

        for tick in clock.ticks:
            context = TickContext(
                config=config,
                clock=clock,
                tick=tick,
                month=clock.month_at(tick),
                period=clock.period_at(tick),
                rng=rng,
                logger=logger,
            )
            logger.emit(
                tick=tick,
                event_type=TICK_EVENT_TYPE,
                phase=TickPhase.BOOKKEEPING.token,
                outcome=context.period.value,
            )
            for system in self._systems:
                system.step(context)

        events = logger.to_frame()
        macro = self._macro_frame()
        created_at = datetime.now(UTC)
        manifest = RunManifest.for_run(
            config=config,
            clock=clock,
            rng=rng,
            provenance=git_provenance(),
            created_at=created_at,
            run_label=run_label,
        )
        summary = RunSummary(
            run_id=manifest.run_id,
            tick_count=clock.tick_count,
            warmup_ticks=clock.warmup_ticks,
            event_count=len(logger),
            simulation_digest=simulation_digest(events, macro),
            created_at=created_at,
            duration_seconds=time.perf_counter() - started,
        )
        return KernelResult(
            config=config, manifest=manifest, summary=summary, events=events, macro=macro
        )

    def _macro_frame(self) -> pl.DataFrame:
        rows = [
            (
                tick,
                str(month),
                month.year,
                month.month,
                self._clock.period_at(tick).value,
            )
            for tick, month in ((tick, self._clock.month_at(tick)) for tick in self._clock.ticks)
        ]
        return pl.DataFrame(rows, schema=MACRO_SCHEMA, orient="row")


def simulation_digest(events: pl.DataFrame, macro: pl.DataFrame) -> str:
    """SHA-256 over the canonical form of every produced row.

    This is the digest that must repeat exactly for the same code, configuration and seed;
    it covers the event log and the macro index, not wall-clock bookkeeping.
    """
    records = [canonical_json(row) for row in events.iter_rows(named=True)]
    records += [canonical_json(row) for row in macro.iter_rows(named=True)]
    return hash_records(records)


def _validated_systems(systems: Sequence[System]) -> tuple[System, ...]:
    validated = tuple(systems)
    seen: set[str] = set()
    previous: TickPhase | None = None
    for system in validated:
        if not system.name:
            raise ValueError("system name must not be empty")
        if system.name in seen:
            raise ValueError(f"duplicate system name {system.name!r}")
        seen.add(system.name)
        if previous is not None and system.phase < previous:
            raise ValueError(
                f"system {system.name!r} registers in phase {system.phase.token!r} after "
                f"{previous.token!r}; systems must follow the versioned tick order"
            )
        previous = system.phase
    return validated
