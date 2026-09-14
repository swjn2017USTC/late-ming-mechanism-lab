"""The migration gate log: why each cohort did or did not move in each tick.

The V1 hold-out check ``exits-in-crisis-years`` fails because almost nobody ever leaves, and the
reasons are spread across the three rules that decide a move: no destination in reach, a destination
with no cohort of the movers' class, a road whose monthly capacity is under the minimum, a household
holding less silver than a move costs, a share under the minimum, or a cohort that is simply not
eligible. None of those is visible in a tick where nobody left, because the movement events are only
written when somebody does.

These tests run one compact sandbox and read its log the way the analysis layer does. They defend
the gate rows' own contract — one row per cohort per tick, every field present and numeric, an
outcome from the declared vocabulary — and, above all, that the rows are *additive*: each row's verb
is the movement the events record for that cohort and tick, its counts and summed households are
those events' own numbers, and a row that refused or applied nothing names a tick in which its rule
moved nobody.
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.analysis.distress import with_trigger_fields
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import TICK_EVENT_TYPE
from late_ming_lab.core.tick import TickPhase
from late_ming_lab.experiments.integrated import (
    IntegratedRun,
    IntegratedScenario,
    run_integrated_scenario,
)
from late_ming_lab.systems.migration import (
    ARRIVAL_EVENT,
    DEPARTURE_EVENT,
    EXIT_EVENT,
    GATE_BELOW_MINIMUM,
    GATE_MOVED,
    GATE_NO_DESTINATION,
    GATE_NOT_ELIGIBLE,
    GATE_OUTCOMES,
    GATE_RETURNED,
    GATE_SILVER,
    GATE_TEMPORARY,
    MIGRATION_GATE_EVENT,
    MIGRATION_RULE_VERSION,
    RETURN_EVENT,
    SETTLEMENT_EVENT,
    TEMPORARY_EVENT,
    TRANSIT_EVENT,
)

#: The fields every gate row promises, in the order the emitter writes them.
GATE_FIELDS = (
    "households",
    "adults",
    "silver_per_household",
    "eligible_permanent",
    "destination_is_exit",
    "edge_capacity_households",
    "edge_risk",
    "migration_cost_tael",
    "movers_households",
)

#: The refusals: the tokens that say no household left. ``not-eligible`` is not one of them — a
#: cohort no rule applied to is not a cohort a rule refused.
REFUSALS = frozenset(GATE_OUTCOMES - {GATE_MOVED, GATE_RETURNED, GATE_TEMPORARY, GATE_NOT_ELIGIBLE})

#: The refusals only the seasonal rule can reach, because the permanent rule never ran.
SEASONAL_REFUSALS = frozenset({GATE_NO_DESTINATION, GATE_SILVER, GATE_BELOW_MINIMUM})

COMPACT_CONFIG = SimulationConfig.model_validate({"tick_count": 96, "warmup_ticks": 12})

SCENARIO = IntegratedScenario(
    label="migration-chain-unit", dataset="toy", monthly_event_probability=0.5, severity_floor=0.6
)


@pytest.fixture(scope="module")
def chain_run() -> IntegratedRun:
    return run_integrated_scenario(SCENARIO, config=COMPACT_CONFIG)


@pytest.fixture(scope="module")
def events(chain_run: IntegratedRun) -> pl.DataFrame:
    return chain_run.result.events


@pytest.fixture(scope="module")
def gates(events: pl.DataFrame) -> pl.DataFrame:
    gate_events = events.filter(pl.col("event_type") == MIGRATION_GATE_EVENT)
    return with_trigger_fields(gate_events, GATE_FIELDS)


@pytest.fixture(scope="module")
def cohort_ids(chain_run: IntegratedRun) -> set[str]:
    return {cohort.cohort_id for cohort in chain_run.economy.population}


def _of_type(
    events: pl.DataFrame, event_type: str, outcome_prefix: str | None = None
) -> pl.DataFrame:
    """The rows of one event type, optionally only those whose outcome starts with a phrase."""
    frame = events.filter(pl.col("event_type") == event_type)
    if outcome_prefix is None:
        return frame
    return frame.filter(pl.col("outcome").str.starts_with(outcome_prefix))


def _pairs(frame: pl.DataFrame) -> set[tuple[int, str]]:
    """The (tick, cohort) pairs a frame's rows stand for, whatever the frame is."""
    return set(zip(frame["tick"].to_list(), frame["agent_id"].to_list(), strict=True))


def _ticks(events: pl.DataFrame) -> set[int]:
    """The ticks the run itself recorded, so a test never has to assume the window."""
    return set(_of_type(events, TICK_EVENT_TYPE)["tick"].unique().to_list())


def _column_total(frame: pl.DataFrame, column: str) -> float:
    """One numeric column summed; 0.0 when the frame is empty."""
    if frame.is_empty():
        return 0.0
    value = frame[column].sum()
    return 0.0 if value is None else float(value)


def _trigger_total(frame: pl.DataFrame, field: str) -> float:
    """One trigger field summed, read the way the analysis layer reads it."""
    if frame.is_empty():
        return 0.0
    value = frame["trigger_json"].str.json_path_match(f"$.{field}").cast(pl.Float64).sum()
    return 0.0 if value is None else float(value)


def _permanent_departures(events: pl.DataFrame) -> pl.DataFrame:
    """Households that left a node for good; a season's adults depart under another outcome."""
    return _of_type(events, DEPARTURE_EVENT, "migrated-to")


def _internal_arrivals(events: pl.DataFrame) -> pl.DataFrame:
    """Households that arrived at another counted node; a seasonal return is not one of these."""
    return _of_type(events, ARRIVAL_EVENT, "arrived-from")


def _away_pairs(events: pl.DataFrame) -> set[tuple[int, str]]:
    """Every (tick, cohort) at which the log says a season's adults are away.

    A tick counts as away when a group was sent at or before it and has not come home by then. A
    cohort that comes home and sends the next season in the same tick is away again from that tick,
    which is the order the migration phase itself applies the two rules in.
    """
    sends = _pairs(_of_type(events, TEMPORARY_EVENT))
    returns = _pairs(_of_type(events, RETURN_EVENT))
    away: set[tuple[int, str]] = set()
    for cohort in sorted({cohort for _, cohort in sends | returns}):
        open_season = False
        for tick in sorted(_ticks(events)):
            if (tick, cohort) in returns:
                open_season = False
            if (tick, cohort) in sends:
                open_season = True
            if open_season:
                away.add((tick, cohort))
    return away


def test_one_gate_row_per_cohort_per_tick_in_the_migration_phase(
    gates: pl.DataFrame, events: pl.DataFrame, cohort_ids: set[str]
) -> None:
    expected = {(tick, cohort) for tick in _ticks(events) for cohort in cohort_ids}

    assert _pairs(gates) == expected, "every cohort the phase considers gets a row in every tick"
    assert gates.height == len(expected), "and exactly one: a cohort is not counted twice"
    assert set(gates["phase"].unique()) == {TickPhase.MIGRATION.token}
    assert set(gates["rule_version"].unique()) == {MIGRATION_RULE_VERSION}


def test_every_trigger_field_is_present_and_numeric(gates: pl.DataFrame) -> None:
    raw = gates.select(
        [
            pl.col("trigger_json").str.json_path_match(f"$.{name}").alias(name)
            for name in GATE_FIELDS
        ]
    )

    assert raw.null_count().sum_horizontal().item() == 0, "no field may be missing on any row"
    values = raw.cast(pl.Float64, strict=True)
    assert all(values.select(pl.col(name).is_finite().all()).item() for name in GATE_FIELDS)


def test_every_outcome_is_a_declared_token(gates: pl.DataFrame) -> None:
    tokens = set(gates["outcome"].unique())

    assert gates["outcome"].null_count() == 0
    assert tokens <= GATE_OUTCOMES, "an undeclared token would be unreadable to the analysis layer"
    assert {GATE_MOVED, GATE_NOT_ELIGIBLE} <= tokens
    assert tokens & REFUSALS, "a fixture in which nobody was refused would prove nothing"


def test_a_move_is_named_by_the_departure_and_the_destination_it_produced(
    gates: pl.DataFrame, events: pl.DataFrame
) -> None:
    moved = gates.filter(pl.col("outcome") == GATE_MOVED)
    internal = moved.filter(pl.col("destination_is_exit") == 0.0)
    exited = moved.filter(pl.col("destination_is_exit") == 1.0)

    assert moved.height > 0, "the fixture must move somebody"
    assert _pairs(moved) == _pairs(_permanent_departures(events))
    # A settlement is the origin's own record of an internal move, so it is the pair to compare
    # with: an arrival is logged by the cohort that received the movers, not the one that left.
    assert _pairs(internal) == _pairs(_of_type(events, SETTLEMENT_EVENT))
    assert _pairs(exited) == _pairs(_of_type(events, EXIT_EVENT))
    assert internal.height > 0 and exited.height > 0, "both halves of the chain are exercised"


def test_a_seasonal_verdict_names_the_season_the_events_record(
    gates: pl.DataFrame, events: pl.DataFrame
) -> None:
    temporary = _pairs(gates.filter(pl.col("outcome") == GATE_TEMPORARY))
    returned = _pairs(gates.filter(pl.col("outcome") == GATE_RETURNED))
    sends = _pairs(_of_type(events, TEMPORARY_EVENT))
    returns = _pairs(_of_type(events, RETURN_EVENT))

    assert temporary and returned, "the fixture must run both ends of the seasonal rule"
    assert temporary <= _away_pairs(events), "a cohort is temporary while its adults are away"
    assert returned <= returns, "a row may only call a cohort returned if its term ended"
    assert not (sends | returns) & _pairs(gates.filter(pl.col("outcome") == GATE_NOT_ELIGIBLE)), (
        "a cohort that sent or brought home adults was not ineligible"
    )


def test_a_row_that_refused_or_applied_nothing_names_a_tick_its_rule_moved_nobody(
    gates: pl.DataFrame, events: pl.DataFrame
) -> None:
    seasonal = _pairs(_of_type(events, TEMPORARY_EVENT)) | _pairs(_of_type(events, RETURN_EVENT))
    permanent = (
        _pairs(_permanent_departures(events))
        | _pairs(_of_type(events, EXIT_EVENT))
        | _pairs(_of_type(events, SETTLEMENT_EVENT))
    )
    refused = gates.filter(pl.col("outcome").is_in(sorted(REFUSALS)))
    seasonal_refused = _pairs(refused.filter(pl.col("eligible_permanent") == 0.0))
    permanent_refused = _pairs(refused.filter(pl.col("eligible_permanent") == 1.0))

    assert not _pairs(gates.filter(pl.col("outcome") == GATE_NOT_ELIGIBLE)) & (
        permanent | seasonal
    ), "no rule applied to an ineligible cohort, so it moved nobody"
    # A permanent refusal outranks a season, not the other way round: a cohort the permanent rule
    # refused may still have sent its adults away, and its row names that refusal. What a refusal
    # may never contradict is the movement of its own rule.
    assert not seasonal_refused & seasonal
    assert not permanent_refused & permanent
    assert set(refused.filter(pl.col("eligible_permanent") == 0.0)["outcome"].unique()) <= set(
        SEASONAL_REFUSALS
    ), "capacity and a missing receiving cohort are the permanent rule's own refusals"


def test_the_gate_reports_the_movement_logs_own_counts_and_households(
    gates: pl.DataFrame, events: pl.DataFrame
) -> None:
    """The rows are additive: they repeat the movement events' numbers and invent none."""
    moved = gates.filter(pl.col("outcome") == GATE_MOVED)
    internal = moved.filter(pl.col("destination_is_exit") == 0.0)
    exited = moved.filter(pl.col("destination_is_exit") == 1.0)
    departures = _permanent_departures(events)
    arrivals = _internal_arrivals(events)

    assert moved.height == departures.height == _of_type(events, TRANSIT_EVENT).height
    assert internal.height == arrivals.height == _of_type(events, SETTLEMENT_EVENT).height
    assert exited.height == _of_type(events, EXIT_EVENT).height

    households = _column_total(moved, "movers_households")
    assert households == pytest.approx(_trigger_total(departures, "households_migrated"))
    assert households == pytest.approx(
        _trigger_total(arrivals, "households_arrived")
        + _trigger_total(_of_type(events, EXIT_EVENT), "households_exited")
    )
    assert gates.filter(pl.col("outcome") != GATE_MOVED)["movers_households"].abs().max() == 0.0, (
        "only a move may claim to have moved households"
    )
