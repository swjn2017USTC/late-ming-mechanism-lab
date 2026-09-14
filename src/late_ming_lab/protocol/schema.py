"""The validation protocol: the definitions every V2 report reads, and nothing else.

V2-P03's first job is to freeze what an outcome *is* before any V2 result is read, because a
definition chosen after the numbers are in is a fit in disguise. The protocol lives in
`data/protocol/validation-protocol-v2.yaml`, is loaded here, is hashed into every batch manifest,
and is refused when a batch was scored under a different one.

```text
windows          calibration, hold-out, extrapolation, whole-run - and the isolation between them
primary outcomes continuous dimensions: fiscal realisation and base, arrears, relief coverage,
                 military supply, migration outflow, market connectivity, livelihood shortfall
                 and armed concentration. Each carries a direction, an aggregation, a missingness
                 rule, a minimum substantive effect and the comparison level the record supports.
derived          the crossed-line count and the binary breakdown reading, computed *from* the
                 primary outcomes and never used as the headline
comparison       direction, ordering, magnitude, none - so no report can upgrade what the record
                 supports into what it does not
```

A threshold is never a historical fact in this file. Where a line turns a measurement into a
verdict, it is declared as a normative choice or a model assumption with a range, and the verdict's
dependence on it is reported (`threshold-ensemble-v2.yaml`) rather than assumed away.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from late_ming_lab.core.hashing import canonical_json, hash_text

PROTOCOL_SCHEMA_VERSION: Final[str] = "validation-protocol-v2"
PROTOCOL_PATH: Final[str] = "data/protocol/validation-protocol-v2.yaml"

Direction = Literal[
    "lower-is-adverse",
    "higher-is-adverse",
    "higher-shortfall-is-adverse",
    "higher-share-is-adverse",
]
ComparisonLevel = Literal["direction", "ordering", "magnitude", "none"]
ThresholdIdentity = Literal["normative", "model-assumption", "evidence-bounded"]
MissingnessRule = Literal["refuse", "declared-imputation", "not-applicable"]


class ProtocolError(ValueError):
    """Raised when the protocol cannot be read, or does not hold together."""


class ProtocolWindow(BaseModel):
    """One scoring window, with the tick range and the rule that governs it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    role: Literal["scoring", "reporting"] = Field(
        default="scoring",
        description=(
            "scoring windows partition the run and may not overlap; the reporting window spans it "
            "for outcome reporting and may not be used as a fitting target"
        ),
    )
    start_tick: int = Field(ge=0)
    end_tick: int = Field(ge=0)
    note: str = Field(min_length=1)

    @model_validator(mode="after")
    def _window_is_ordered(self) -> ProtocolWindow:
        if self.end_tick < self.start_tick:
            raise ProtocolError(
                f"{self.id}: end tick {self.end_tick} precedes start {self.start_tick}"
            )
        return self

    @property
    def ticks(self) -> int:
        return self.end_tick - self.start_tick + 1


class Isolation(BaseModel):
    """The window isolation rule, and the code that enforces it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule: str = Field(min_length=1)
    enforced_by: tuple[str, ...] = Field(min_length=1)


class MissingnessRuleEntry(BaseModel):
    """What happens to a value the run did not produce."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: MissingnessRule
    when: str = Field(min_length=1)
    action: str = Field(min_length=1)


class Missingness(BaseModel):
    """The missingness policy, with the default stated and the rules enumerated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default: MissingnessRule
    rules: tuple[MissingnessRuleEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _default_is_one_of_the_rules(self) -> Missingness:
        declared = {rule.id for rule in self.rules}
        if self.default not in declared:
            raise ProtocolError(
                f"the default rule {self.default!r} is not among the declared rules"
            )
        return self


class PrimaryOutcome(BaseModel):
    """One dimension of the primary outcome vector, with everything a report needs to read it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    dimension: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    definition: str = Field(min_length=1)
    direction: Direction
    aggregation: str = Field(min_length=1)
    form: Literal["measure", "ratio", "vector"] = Field(
        description=(
            "how the value is formed from the measurements: a single measurement, the first "
            "measurement over the second, or several reported together with the first as the "
            "outcome's value"
        )
    )
    unit: str = Field(min_length=1)
    measurements: tuple[str, ...] = Field(
        min_length=1,
        description=(
            "the measured quantities this outcome is read from, from the run's own outcome "
            "scalars; a report may not invent a quantity the protocol does not name here"
        ),
    )
    minimum_substantive_effect: float = Field(gt=0)
    historical_comparison: ComparisonLevel
    historical_note: str = Field(min_length=1)
    evidence: tuple[str, ...] = ()


class DerivedThreshold(BaseModel):
    """A line inside a derived reading: its value, what kind of choice it is, and its range."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float
    identity: ThresholdIdentity
    range: tuple[float, float]
    note: str = Field(min_length=1)

    @model_validator(mode="after")
    def _range_contains_the_value(self) -> DerivedThreshold:
        low, high = self.range
        if low > high:
            raise ProtocolError(f"threshold range [{low}, {high}] is inverted")
        if not low <= self.value <= high:
            raise ProtocolError(
                f"threshold value {self.value} lies outside its range [{low}, {high}]"
            )
        return self


class DerivedReading(BaseModel):
    """A reading computed from the primary outcomes; never the headline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    definition: str = Field(min_length=1)
    source: str | None = None
    thresholds: dict[str, DerivedThreshold] = Field(default_factory=dict)
    note: str = Field(min_length=1)


class IntermediateSeries(BaseModel):
    """A series the protocol requires to be retained, so a chain is not only its end state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    granularity: Literal["node-month", "month", "node", "link", "indicator-tick"]
    source: str = Field(min_length=1, description="module:function that produces it")
    chain: str = Field(min_length=1)
    fields: tuple[str, ...] = Field(min_length=1)
    note: str = Field(min_length=1)


class ComparisonLevelEntry(BaseModel):
    """One rung of the comparison ladder, and what it licenses."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: ComparisonLevel
    meaning: str = Field(min_length=1)


class ValidationProtocol(BaseModel):
    """The frozen protocol: windows, missingness, outcomes, derived readings, comparison levels."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["validation-protocol-v2"] = "validation-protocol-v2"
    version: str = Field(min_length=1)
    frozen_on: str = Field(min_length=1)
    run_ticks: int = Field(gt=1, description="the window every scoring window partitions")
    status: Literal["frozen", "draft"]
    summary: str = Field(min_length=1)
    windows: tuple[ProtocolWindow, ...] = Field(min_length=2)
    isolation: Isolation
    missingness: Missingness
    primary_outcomes: tuple[PrimaryOutcome, ...] = Field(min_length=1)
    intermediates: tuple[IntermediateSeries, ...] = Field(min_length=1)
    derived_readings: tuple[DerivedReading, ...] = Field(min_length=1)
    comparison_levels: tuple[ComparisonLevelEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _protocol_holds_together(self) -> ValidationProtocol:
        ids = [window.id for window in self.windows]
        if len(set(ids)) != len(ids):
            raise ProtocolError("window ids must be unique")
        scoring = sorted(
            (window for window in self.windows if window.role == "scoring"),
            key=lambda window: window.start_tick,
        )
        for earlier, later in itertools.pairwise(scoring):
            if earlier.end_tick >= later.start_tick:
                raise ProtocolError(
                    f"scoring windows {earlier.id!r} and {later.id!r} overlap: a score could read "
                    "both"
                )
        if scoring:
            if scoring[0].start_tick != 0:
                raise ProtocolError(
                    f"the scoring windows must start at tick 0, not {scoring[0].start_tick}"
                )
            for earlier, later in itertools.pairwise(scoring):
                if later.start_tick != earlier.end_tick + 1:
                    raise ProtocolError(
                        f"scoring windows {earlier.id!r} and {later.id!r} leave a gap"
                    )
            if scoring[-1].end_tick != self.run_ticks - 1:
                raise ProtocolError(
                    f"the scoring windows end at {scoring[-1].end_tick}, not {self.run_ticks - 1}"
                )
        for window in self.windows:
            if window.end_tick >= self.run_ticks:
                raise ProtocolError(
                    f"{window.id}: ends at {window.end_tick}, beyond the {self.run_ticks}-tick run"
                )
        outcome_ids = [outcome.id for outcome in self.primary_outcomes]
        if len(set(outcome_ids)) != len(outcome_ids):
            raise ProtocolError("primary outcome ids must be unique")
        levels = {level.id for level in self.comparison_levels}
        for outcome in self.primary_outcomes:
            if outcome.form == "ratio" and len(outcome.measurements) != 2:
                raise ProtocolError(
                    f"{outcome.id}: a ratio needs exactly two measurements, in numerator then "
                    f"denominator order, and this names {len(outcome.measurements)}"
                )
            if outcome.form == "measure" and len(outcome.measurements) != 1:
                raise ProtocolError(
                    f"{outcome.id}: a single-measurement outcome names "
                    f"{len(outcome.measurements)} measurements"
                )
            if outcome.historical_comparison not in levels:
                raise ProtocolError(
                    f"{outcome.id}: comparison level {outcome.historical_comparison!r} is not "
                    "declared"
                )
        reading_ids = [reading.id for reading in self.derived_readings]
        if len(set(reading_ids)) != len(reading_ids):
            raise ProtocolError("derived reading ids must be unique")
        series_ids = [series.id for series in self.intermediates]
        if len(set(series_ids)) != len(series_ids):
            raise ProtocolError("intermediate series ids must be unique")
        if not any(series.granularity.endswith("month") for series in self.intermediates):
            raise ProtocolError(
                "no intermediate series is read by the month, so the protocol would require only "
                "window-end aggregates"
            )
        return self

    @property
    def dimensions(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(outcome.dimension for outcome in self.primary_outcomes))

    def outcome(self, outcome_id: str) -> PrimaryOutcome:
        for outcome in self.primary_outcomes:
            if outcome.id == outcome_id:
                return outcome
        raise KeyError(outcome_id)

    def window(self, window_id: str) -> ProtocolWindow:
        for window in self.windows:
            if window.id == window_id:
                return window
        raise KeyError(window_id)

    def digest(self) -> str:
        """The protocol's identity: its content, canonicalised, with no clock in it."""
        return hash_text(canonical_json(self.model_dump(mode="json")))

    def threshold_dependence(self) -> tuple[str, ...]:
        """The readings whose verdict depends on a declared line rather than on a measurement."""
        return tuple(reading.id for reading in self.derived_readings if reading.thresholds)


def load_protocol(root: str | Path, *, path: str = PROTOCOL_PATH) -> ValidationProtocol:
    """Read the frozen protocol, refusing a draft or a version this code does not implement."""
    source = Path(root) / path
    if not source.is_file():
        raise ProtocolError(f"{source} is missing; the validation protocol is frozen there")
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ProtocolError(f"{source} is not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise ProtocolError(f"{source} must hold a mapping, not {type(raw).__name__}")
    if raw.get("schema_version") != PROTOCOL_SCHEMA_VERSION:
        raise ProtocolError(
            f"{source} declares schema {raw.get('schema_version')!r}, not "
            f"{PROTOCOL_SCHEMA_VERSION!r}"
        )
    protocol = ValidationProtocol.model_validate(json.loads(json.dumps(raw)))
    if protocol.status != "frozen":
        raise ProtocolError(
            f"{source} is {protocol.status!r}; a batch may not be scored against a draft protocol"
        )
    return protocol
