"""The primary outcome vector: one run, one window, read straight off the frozen protocol.

The protocol says which measured quantities make up each outcome; this module assembles them,
applies the missingness rule, and refuses to hand a report a number the run did not produce. Two
rules keep it honest:

```text
no invented quantity   every value comes from a measurement the protocol names, and a name that the
                       measure set does not carry is an error, not a zero
no silent zero         a missing measurement is either refused (the default), recorded as missing
                       with the reason, or explicitly declared not applicable by the protocol; a
                       quantity that could not be measured never enters a mean or a share as 0
```

A window is a slice of the same trajectory: window measures are computed on the window's own
ticks, with the run's declared population denominators. Sums therefore add across windows and
end-state readings restart from the window's first tick, which is a per-window score's meaning.
"""

from __future__ import annotations

import networkx as nx
import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from late_ming_lab.evidence.parameters import GovernanceIndicatorParameters
from late_ming_lab.protocol.freeze import Purpose, assert_window_access
from late_ming_lab.protocol.measures import protocol_measurements
from late_ming_lab.protocol.schema import PrimaryOutcome, ValidationProtocol


class OutcomeError(ValueError):
    """Raised when a protocol outcome cannot be read from a run at all."""


class OutcomeValue(BaseModel):
    """One primary outcome in one window, with what it was computed from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    dimension: str
    direction: str
    aggregation: str
    value: float | None
    components: dict[str, float] = Field(default_factory=dict)
    resolution: str = Field(pattern=r"^(measured|missing|not-applicable)$")
    note: str = ""

    def require(self) -> float:
        """The value, refusing a missing one: a caller that needs a number must see the refusal."""
        if self.value is None:
            raise OutcomeError(f"{self.id} was resolved {self.resolution!r}: {self.note}")
        return self.value


class OutcomeVector(BaseModel):
    """Every primary outcome for one run in one window, under one protocol."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    window: str
    protocol_version: str
    protocol_digest: str
    values: dict[str, OutcomeValue]

    def value(self, outcome_id: str) -> OutcomeValue:
        try:
            return self.values[outcome_id]
        except KeyError as error:
            raise OutcomeError(f"{outcome_id!r} is not one of this protocol's outcomes") from error

    def measured(self) -> dict[str, float]:
        """Only the outcomes that were actually measured, so a mean never absorbs a refusal."""
        return {
            key: value.value
            for key, value in self.values.items()
            if value.resolution == "measured" and value.value is not None
        }

    def refused(self) -> tuple[str, ...]:
        return tuple(key for key, value in self.values.items() if value.resolution != "measured")


def window_events(events: pl.DataFrame, start_tick: int, end_tick: int) -> pl.DataFrame:
    """The window's slice of a run's log."""
    if "tick" not in events.columns:
        raise OutcomeError("the log has no tick column, so no window can be cut from it")
    return events.filter((pl.col("tick") >= start_tick) & (pl.col("tick") <= end_tick))


def compute_outcomes(
    events: pl.DataFrame,
    protocol: ValidationProtocol,
    *,
    window_id: str,
    run_id: str,
    purpose: Purpose,
    thresholds: GovernanceIndicatorParameters,
    population_adults: float,
    starting_households: float,
    trade_graph: nx.Graph[str],
) -> OutcomeVector:
    """The outcome vector for one window of one run, read for a declared purpose.

    `purpose` is required rather than optional and is checked here: this is the only place a
    window's numbers are produced, so it is the only place that can refuse a fitting caller the
    hold-out window, or a scoring caller the calibration window. A caller that could measure any
    window would make the isolation rule a convention, and a convention is what this phase exists
    to replace.

    A window id the protocol does not declare, or a measurement the protocol names and the measure
    set does not carry, is an error: the protocol is the definition, and a report that quietly used
    a different one would not be comparable with any other report.
    """
    assert_window_access(protocol, window_id, purpose)
    window = protocol.window(window_id)  # KeyError on a window the protocol never declared
    sliced = window_events(events, window.start_tick, window.end_tick)
    measures = protocol_measurements(
        sliced,
        thresholds=thresholds,
        population_adults=population_adults,
        starting_households=starting_households,
        trade_graph=trade_graph,
    )
    default_rule = protocol.missingness.default
    values: dict[str, OutcomeValue] = {}
    for outcome in protocol.primary_outcomes:
        values[outcome.id] = _read_outcome(
            outcome, measures, window_id=window_id, default_rule=default_rule
        )
    return OutcomeVector(
        run_id=run_id,
        window=window_id,
        protocol_version=protocol.version,
        protocol_digest=protocol.digest(),
        values=values,
    )


def _read_outcome(
    outcome: PrimaryOutcome,
    measures: dict[str, float],
    *,
    window_id: str,
    default_rule: str,
) -> OutcomeValue:
    """One outcome, with the missingness rule applied where a measurement is absent."""
    absent = [name for name in outcome.measurements if name not in measures]
    if absent:
        # A name the protocol declares and the measure set does not carry is a programming error in
        # the protocol's own binding, never a property of the run. It is refused either way, but the
        # reason says which: this is not a data gap to be papered over with a zero.
        if default_rule == "refuse":
            raise OutcomeError(
                f"{outcome.id} needs {', '.join(absent)}, which the measure set does not produce; "
                "the protocol names a quantity no run can supply"
            )
        return OutcomeValue(
            id=outcome.id,
            dimension=outcome.dimension,
            direction=outcome.direction,
            aggregation=outcome.aggregation,
            value=None,
            components={},
            resolution="missing",
            note=f"unbound measurements: {', '.join(absent)}",
        )
    components = {name: float(measures[name]) for name in outcome.measurements}
    unmeasured = [name for name, value in components.items() if value != value]  # NaN
    if unmeasured:
        if default_rule == "refuse":
            raise OutcomeError(
                f"{outcome.id} needs {', '.join(unmeasured)}, which the run measured as NaN"
            )
        return OutcomeValue(
            id=outcome.id,
            dimension=outcome.dimension,
            direction=outcome.direction,
            aggregation=outcome.aggregation,
            value=None,
            components={name: value for name, value in components.items() if value == value},
            resolution="missing",
            note=f"NaN measurements: {', '.join(unmeasured)}",
        )
    value = _aggregate(outcome, components, window_id=window_id)
    return OutcomeValue(
        id=outcome.id,
        dimension=outcome.dimension,
        direction=outcome.direction,
        aggregation=outcome.aggregation,
        value=value,
        components=components,
        resolution="measured",
    )


def _aggregate(outcome: PrimaryOutcome, components: dict[str, float], *, window_id: str) -> float:
    """The outcome's value from its measured components, by the form the protocol declares.

    The form is read from the protocol rather than inferred from the prose next to it: "ratio of
    window totals" and "ratio of window totals; minimum net node flow" are the same words, and one
    of them is not a ratio. A denominator of zero is refused rather than read as 0.0, because a
    share of nothing is not a share.
    """
    if outcome.form == "measure":
        return next(iter(components.values()))
    if outcome.form == "ratio":
        numerator, denominator = (components[name] for name in outcome.measurements[:2])
        if denominator == 0.0:
            raise OutcomeError(
                f"{outcome.id} in {window_id}: the denominator "
                f"{outcome.measurements[1]} is zero, so the share is undefined rather than zero"
            )
        return numerator / denominator
    # A vector: the components are all reported, and the first is the outcome's own value, which the
    # protocol's `measurements` order declares.
    return components[outcome.measurements[0]]
