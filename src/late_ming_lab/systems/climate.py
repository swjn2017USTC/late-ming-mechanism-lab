"""Exogenous climate forcing: baseline, observed-historical and synthetic modes.

A climate shock is a *forcing*, not a harvest and not a price. It is a severity in ``[0, 1]``
for one node and one month, where 0 means "no adverse anomaly for this place" and 1 means the
most severe anomaly the mode can produce. Turning severity into a yield belongs to the
production function (P03), which weights it by the agricultural calendar; the climate layer
must not smuggle in a crop model.

Three modes, deliberately not interchangeable:

- ``baseline`` — no adverse anomaly, ever. The reference run, and the ablation baseline.
- ``observed-historical`` — replays a sourced series, one severity per node and month. It
  consumes no randomness, fails closed on a gap, and refuses to be graded ``S``: an invented
  series is not an observation.
- ``synthetic`` — draws from the run's ``climate_rng`` stream with declared parameters. Both
  draws are taken unconditionally for every node and month, so changing a parameter changes
  the meaning of the draws without shifting them; that is what makes common random numbers
  work in counterfactuals.

Every mode records the same event shape, and the rule version in the event log says which
mode produced the number, so a run's forcing is never anonymous.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Literal, Protocol

import numpy as np
import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from late_ming_lab.core.clock import Month
from late_ming_lab.core.rng import RngStream
from late_ming_lab.core.tick import RESOURCE_CLIMATE, TickContext, TickPhase
from late_ming_lab.evidence.grades import DataProvenance, EvidenceGrade
from late_ming_lab.networks.nodes import CountyNode, SpatialNodes
from late_ming_lab.systems.calendar import AgriculturalCalendar, ZoneCalendar

CLIMATE_EVENT_TYPE: Final[str] = "CLIMATE_SHOCK"

#: Columns of an observed series table; one severity per node, year and month.
SERIES_COLUMNS: Final[tuple[str, ...]] = ("node_id", "year", "month", "severity")


class ClimateMode(StrEnum):
    BASELINE = "baseline"
    OBSERVED_HISTORICAL = "observed-historical"
    SYNTHETIC = "synthetic"


@dataclass(frozen=True, slots=True)
class ClimateSample:
    """One severity, plus the uniform draws consumed to produce it (none when replaying)."""

    severity: float
    draws: tuple[tuple[str, float], ...] = field(default=())

    def __post_init__(self) -> None:
        if not 0.0 <= self.severity <= 1.0:
            raise ValueError(f"severity must lie in [0, 1], got {self.severity}")


class ClimateCoverageError(ValueError):
    """Raised when an observed series has no value for a node and month that is requested."""


class ClimateModel(Protocol):
    """A source of exogenous monthly forcing."""

    @property
    def mode(self) -> ClimateMode: ...

    @property
    def rule_version(self) -> str: ...

    def shock(
        self, *, node: CountyNode, month: Month, rng: np.random.Generator
    ) -> ClimateSample: ...


class BaselineClimate(BaseModel):
    """No adverse anomaly: the reference and ablation baseline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal[ClimateMode.BASELINE] = ClimateMode.BASELINE
    rule_version: str = "climate-baseline-v1"

    def shock(self, *, node: CountyNode, month: Month, rng: np.random.Generator) -> ClimateSample:
        """Always zero severity; consumes no randomness."""
        return ClimateSample(severity=0.0)


class SyntheticClimate(BaseModel):
    """Declared synthetic forcing drawn from the climate stream.

    ``monthly_event_probability`` is the chance that a given node-month carries an adverse
    anomaly; when it does, severity is uniform on ``[severity_floor, 1]``. The model claims no
    spatial structure: nodes differ only by their draws, not by their parameters.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    monthly_event_probability: float = Field(ge=0.0, le=1.0)
    severity_floor: float = Field(ge=0.0, le=1.0)
    mode: Literal[ClimateMode.SYNTHETIC] = ClimateMode.SYNTHETIC
    rule_version: str = "climate-synthetic-v1"

    def shock(self, *, node: CountyNode, month: Month, rng: np.random.Generator) -> ClimateSample:
        """Two unconditional draws: occurrence first, then magnitude."""
        occurrence = float(rng.random())
        magnitude = float(rng.random())
        severity = (
            0.0
            if occurrence >= self.monthly_event_probability
            else self.severity_floor + (1.0 - self.severity_floor) * magnitude
        )
        return ClimateSample(
            severity=severity,
            draws=(("occurrence", occurrence), ("magnitude", magnitude)),
        )


class ObservedHistoricalClimate:
    """Replay of a sourced severity series; deterministic and randomness-free."""

    mode: ClimateMode = ClimateMode.OBSERVED_HISTORICAL
    rule_version: str = "climate-observed-v1"

    def __init__(self, series: pl.DataFrame, *, series_id: str, provenance: DataProvenance) -> None:
        if provenance.grade is EvidenceGrade.S:
            raise ValueError(
                "an observed-historical series must be graded A, B, C or D; a series graded S "
                "is an invented series and belongs in the synthetic mode"
            )
        missing = [column for column in SERIES_COLUMNS if column not in series.columns]
        if missing:
            raise ValueError(f"series table is missing columns: {', '.join(missing)}")
        self.series_id = series_id
        self.provenance = provenance
        self._index: dict[tuple[str, int, int], float] = {}
        for row in series.select(list(SERIES_COLUMNS)).iter_rows(named=True):
            node_id = str(row["node_id"])
            year = int(row["year"])
            month = int(row["month"])
            severity = float(row["severity"])
            if not 0.0 <= severity <= 1.0 or not np.isfinite(severity):
                raise ValueError(
                    f"series {series_id!r} has severity {severity} for {node_id} "
                    f"{year}-{month:02d}; severity must lie in [0, 1]"
                )
            key = (node_id, year, month)
            if key in self._index:
                raise ValueError(
                    f"series {series_id!r} repeats {node_id} {year}-{month:02d}; "
                    "one severity per node and month"
                )
            self._index[key] = severity

    def __len__(self) -> int:
        return len(self._index)

    @property
    def years(self) -> tuple[int, ...]:
        return tuple(sorted({year for _, year, _ in self._index}))

    def shock(self, *, node: CountyNode, month: Month, rng: np.random.Generator) -> ClimateSample:
        """Replay the recorded severity, or fail closed when the series does not cover it."""
        try:
            severity = self._index[(node.node_id, month.year, month.month)]
        except KeyError as error:
            raise ClimateCoverageError(
                f"series {self.series_id!r} has no value for {node.node_id} "
                f"{month.year}-{month.month:02d}"
            ) from error
        return ClimateSample(severity=severity)

    @classmethod
    def from_frame(
        cls, series: pl.DataFrame, *, series_id: str, provenance: DataProvenance
    ) -> ObservedHistoricalClimate:
        return cls(series, series_id=series_id, provenance=provenance)


class ClimateSystem:
    """Kernel system (phase 01) that applies exogenous forcing to every county node.

    External boundary nodes receive no climate: the model does not simulate their
    agriculture. Nodes are visited in canonical node-id order, so the draws a synthetic model
    consumes are reproducible.
    """

    name: str = "climate"
    phase: TickPhase = TickPhase.CLIMATE_UPDATE
    reads: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset({RESOURCE_CLIMATE})

    def __init__(
        self,
        nodes: SpatialNodes,
        calendar: AgriculturalCalendar,
        model: ClimateModel,
    ) -> None:
        self._model = model
        targets: list[tuple[CountyNode, ZoneCalendar]] = []
        for node in nodes.counties:
            targets.append((node, calendar.calendar_for(node.zone)))
        if not targets:
            raise ValueError("the climate system needs at least one county node")
        self._targets = tuple(targets)

    def step(self, ctx: TickContext) -> None:
        rng = ctx.rng.generator(RngStream.CLIMATE)
        month_of_year = ctx.month.month
        for node, zone_calendar in self._targets:
            sample = self._model.shock(node=node, month=ctx.month, rng=rng)
            sensitivity = zone_calendar.sensitivity_for(month_of_year)
            trigger: dict[str, float] = {
                "severity": sample.severity,
                "sensitivity": sensitivity,
                "impact": sample.severity * sensitivity,
                "month_of_year": float(month_of_year),
            }
            for draw_name, draw_value in sample.draws:
                trigger[f"{draw_name}_draw"] = draw_value
            ctx.emit(
                CLIMATE_EVENT_TYPE,
                phase=self.phase.token,
                region=node.node_id,
                rule_version=self._model.rule_version,
                rng_stream=RngStream.CLIMATE if sample.draws else None,
                rng_draw=sample.draws[0][1] if sample.draws else None,
                trigger=trigger,
                outcome=self._model.mode.value,
            )
