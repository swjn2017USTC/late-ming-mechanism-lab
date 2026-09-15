"""The band chain: what moved the largest band's share, component by component.

The M005 card's uncertainty is that consolidation is robust as an outcome while its attribution
inside the model is not: no merge fired anywhere in the P10 batch, so the link the model's own
documentation names was never exercised. A run's log records who moved into and out of every band,
and this reader sorts those movements into the six links the mechanism's chain is made of:

```text
formation         a band appears, filled from the unorganized pool or from a levy
refugee intake    an existing band levies the distress-eligible adults of its node
deserter intake   an existing band takes in the unorganized deserters of its node
merger            one band absorbs another
split             one band becomes two
dissolution       a band loses members to suppression, or disappears
```

Each component is reported per tick with the men it moved, its effect on the number of bands and
its effect on the largest band's share. Those effects *partition* the change in that share rather
than re-describing it, which is what makes the attribution readable as a decomposition.

Three things keep the partition honest rather than rhetorical:

- the movements are read from the ledger delta every band event carries (``troops_delta_people``),
  so the parts sum with the model's own arithmetic rather than a recomputation of it;
- the reconstruction is checked against the ``BAND_STATE`` the log records for every tick, and a
  log the movements cannot reproduce is refused. A log that has quietly lost a movement would
  otherwise charge the missing men to whichever component happened to be applied last;
- a movement whose cause this module does not know is refused too, because dropping it would leave
  the partition incomplete while still summing to something.

The effects are order-dependent within a tick — two components acting in the same month share an
interaction term, and the component applied later takes it — so the order is declared here, as the
tick's own phase order, and documented rather than left to the log's row order. The total does not
depend on it.

Both sides of a two-sided movement are logged, once by the band leaving and once by the band
arriving (a merger is a survivor's intake and an absorbed band's loss). The movement is therefore
counted once, as the men who arrived; the count of bands it changes is a separate column, because a
merger moves 50 men and removes a band while a levy moves 50 men and removes none.

Nothing here scores a hypothesis. The M005 card's prediction — lower the cohesion bar, and the
largest band's share should exceed the 0.382 the declared policies reach — is read from these
numbers by a report, not by this module.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

import polars as pl

from late_ming_lab.actors.ledger import TROOPS_DELTA
from late_ming_lab.analysis.military import band_series

#: The records this reader needs: the monthly band state, the two whole-band transitions, and the
#: two movement records the ledger writes for a band (`RECRUIT_LEVY`, `DESERTERS_LEFT`).
BAND_STATE_EVENT: Final[str] = "BAND_STATE"
BAND_FORMED_EVENT: Final[str] = "BAND_FORMED"
BAND_DISSOLVED_EVENT: Final[str] = "BAND_DISSOLVED"
RECRUIT_LEVY_EVENT: Final[str] = "RECRUIT_LEVY"
DESERTION_EVENT: Final[str] = "DESERTERS_LEFT"

#: `ArmedBand.band_id` is ``band-####``, and a band is the only actor whose id starts with it.
BAND_ID_PREFIX: Final[str] = "band-"

#: The field the state record carries: the band's own strength at the month's bookkeeping.
TROOPS_FIELD: Final[str] = "troops"

#: The field only a dissolution record carries; the same event type also records a band giving up
#: its arms without giving up its people, which is not a band disappearing.
DISBANDED_FIELD: Final[str] = "troops_disbanded"

FORMATION: Final[str] = "formation"
REFUGEE_INTAKE: Final[str] = "refugee_intake"
DESERTER_INTAKE: Final[str] = "deserter_intake"
MERGER: Final[str] = "merger"
SPLIT: Final[str] = "split"
DISSOLUTION: Final[str] = "dissolution"

#: The six links, in the order they are applied to a tick's opening state. The order is the tick's
#: own: formation and intake belong to the recruitment phase, and suppression, dissolution, split
#: and merge follow it in the violence phase, in that order.
COMPONENTS: Final[tuple[str, ...]] = (
    FORMATION,
    REFUGEE_INTAKE,
    DESERTER_INTAKE,
    DISSOLUTION,
    SPLIT,
    MERGER,
)

#: How far the reconstruction may stand from a recorded band state before the tick is refused.
#: The movements are re-added in a different order from the one the actors applied them in, so a
#: band's total carries float residue of the order of 1e-14 relative; a log missing a real movement
#: is orders of magnitude beyond this, which is the difference the check has to see.
RECONCILIATION_TOLERANCE: Final[float] = 1e-9

#: The smallest strength that counts as a band standing. A suppression loss is bounded by what the
#: band has, so a band emptied to the last bit of float precision is left with ~1e-15 members and
#: is dissolved in the same tick; that residue is not a band.
DUST_TROOPS: Final[float] = RECONCILIATION_TOLERANCE

_CHAIN_SCHEMA: Final[dict[str, pl.DataType]] = {
    "tick": pl.Int64(),
    "component": pl.String(),
    "troops": pl.Float64(),
    "band_count_delta": pl.Int64(),
    "band_count": pl.Int64(),
    "largest_band_share_delta": pl.Float64(),
    "largest_band_share": pl.Float64(),
}


class BandChainError(ValueError):
    """Raised when a log cannot be read as a band chain at all."""


@dataclass(frozen=True, slots=True)
class _Cause:
    """Where one logged movement belongs, and what it does to the layer.

    ``opens_band`` and ``closes_band`` are declared rather than inferred from the sign of the troop
    delta: a merger moves members both ways and closes a band, and a suppression loss takes members
    away without closing anything.
    """

    component: str
    opens_band: bool = False
    closes_band: bool = False


#: Every movement a band's log writes, keyed by ``(outcome head, origin)``. The head is the token
#: before the outcome's first colon; the origin is the token after it, up to the next colon — the
#: source of an arrival or the destination of a departure, and ``""`` where the head names none.
#: A movement this table does not carry is refused rather than dropped.
MOVEMENT_CAUSES: Final[Mapping[tuple[str, str], _Cause]] = MappingProxyType(
    {
        ("formed-from", "levy"): _Cause(FORMATION, opens_band=True),
        ("formed-from", "unorganized-deserters"): _Cause(FORMATION, opens_band=True),
        ("formed-from", "split"): _Cause(SPLIT, opens_band=True),
        ("joined-from", "levy"): _Cause(REFUGEE_INTAKE),
        ("joined-from", "deserters"): _Cause(DESERTER_INTAKE),
        ("joined-from", "merge"): _Cause(MERGER),
        ("split-to", ""): _Cause(SPLIT),
        ("merge-to", ""): _Cause(MERGER, closes_band=True),
        ("suppressed-to", ""): _Cause(DISSOLUTION),
        ("disbanded-to", ""): _Cause(DISSOLUTION, closes_band=True),
    }
)


@dataclass(slots=True)
class _Signals:
    """A run's band movements, filed by the tick and the component that own them."""

    opens: dict[tuple[int, str], set[str]] = field(default_factory=dict)
    closes: dict[tuple[int, str], set[str]] = field(default_factory=dict)
    deltas: dict[tuple[int, str], list[tuple[str, float]]] = field(default_factory=dict)


def _trigger(events: pl.DataFrame, field: str) -> pl.Series:
    """One trigger value as a number, null where the record does not carry the field."""
    return events["trigger_json"].str.json_path_match(f"$.{field}").cast(pl.Float64, strict=False)


def _band_rows(events: pl.DataFrame) -> pl.DataFrame:
    return events.filter(pl.col("agent_id").str.starts_with(BAND_ID_PREFIX))


def _require_band_records(events: pl.DataFrame) -> None:
    """Refuse a log that holds no band record at all, rather than reading it as a chain of zeros.

    A run with no bands produces no state record and no movement, and a log without either is
    either a run in which the mechanism never fired or a log that predates the instrumentation.
    Both have an answer — no chain — and zero is not that answer.
    """
    if events.is_empty():
        raise BandChainError("event frame is empty: there is no run to attribute")
    for column in ("event_type", "agent_id"):
        if column not in events.columns:
            raise BandChainError(f"event frame has no {column} column")
    if (
        events.filter(pl.col("event_type") == BAND_STATE_EVENT).is_empty()
        and _band_rows(events).is_empty()
    ):
        raise BandChainError(
            f"the log holds no {BAND_STATE_EVENT} record and no band movement: "
            "there is no band chain to attribute"
        )


def _band_frame(events: pl.DataFrame) -> pl.DataFrame:
    """The log with the three fields the chain reads pulled out of the trigger JSON."""
    _require_band_records(events)
    if "trigger_json" not in events.columns:
        raise BandChainError("event frame has no trigger_json column")
    return events.with_columns(
        _trigger(events, TROOPS_DELTA).alias(TROOPS_DELTA),
        _trigger(events, TROOPS_FIELD).alias(TROOPS_FIELD),
        _trigger(events, DISBANDED_FIELD).alias(DISBANDED_FIELD),
    )


def _cause(event_type: str, outcome: object) -> _Cause:
    """The component one logged movement belongs to, from the outcome the actor wrote."""
    head, _, rest = str(outcome or "").partition(":")
    origin = rest.partition(":")[0]
    cause = MOVEMENT_CAUSES.get((head, origin))
    if cause is None:
        cause = MOVEMENT_CAUSES.get((head, ""))
    if cause is None:
        raise BandChainError(
            f"a {event_type} movement carries the outcome {outcome!r}, which this reader does not "
            "attribute: a movement it skipped would leave the partition short of what moved"
        )
    return cause


def _signals(frame: pl.DataFrame) -> _Signals:
    """File every band movement of the run by the tick and component that own it."""
    opens: defaultdict[tuple[int, str], set[str]] = defaultdict(set)
    closes: defaultdict[tuple[int, str], set[str]] = defaultdict(set)
    deltas: defaultdict[tuple[int, str], list[tuple[str, float]]] = defaultdict(list)
    for row in _band_rows(frame).iter_rows(named=True):
        tick = int(row["tick"])
        band_id = str(row["agent_id"])
        event_type = str(row["event_type"])
        if event_type == BAND_FORMED_EVENT:
            opens[(tick, FORMATION)].add(band_id)
        elif event_type == BAND_DISSOLVED_EVENT and row[DISBANDED_FIELD] is not None:
            closes[(tick, DISSOLUTION)].add(band_id)
        delta = row[TROOPS_DELTA]
        if delta is None:
            continue
        cause = _cause(event_type, row["outcome"])
        deltas[(tick, cause.component)].append((band_id, float(delta)))
        if cause.opens_band:
            opens[(tick, cause.component)].add(band_id)
        if cause.closes_band:
            closes[(tick, cause.component)].add(band_id)
    return _Signals(opens=dict(opens), closes=dict(closes), deltas=dict(deltas))


def _states_by_tick(frame: pl.DataFrame) -> dict[int, dict[str, float]]:
    """The band state the log records for each tick, one strength per standing band."""
    states: defaultdict[int, dict[str, float]] = defaultdict(dict)
    for row in frame.filter(pl.col("event_type") == BAND_STATE_EVENT).iter_rows(named=True):
        states[int(row["tick"])][str(row["agent_id"])] = float(row[TROOPS_FIELD] or 0.0)
    return dict(states)


def _largest_share(state: dict[str, float]) -> float:
    """The largest band's share of all band members; 0.0 when no band stands.

    The measure is the record's own, from :func:`late_ming_lab.analysis.military.band_series`, so
    that the chain's effects are read against the same observable the phase reports.
    """
    total = sum(state.values())
    if total <= 0.0:
        return 0.0
    return max(state.values()) / total


def _reconcile(vector: dict[str, float], recorded: dict[str, float], tick: int) -> None:
    """Refuse a tick whose movements do not reproduce the state the log recorded for it.

    A band the log no longer records that stands at float residue is dropped rather than refused: a
    suppression loss is bounded by what the band has, so a band emptied to its last member keeps
    ~1e-15 of it, and the tick that closes such a band is the tick the record says so. A band the
    log does record is never dropped, whatever it stands at.
    """
    for band_id, troops in list(vector.items()):
        if band_id not in recorded and abs(troops) <= DUST_TROOPS:
            del vector[band_id]
    unexplained = sorted(set(vector) - set(recorded))
    if unexplained:
        raise BandChainError(
            f"tick {tick}: the movements leave {', '.join(unexplained)} standing and the log "
            "records no such band"
        )
    unrecorded = sorted(set(recorded) - set(vector))
    if unrecorded:
        raise BandChainError(
            f"tick {tick}: the log records {', '.join(unrecorded)} and no movement explains it"
        )
    for band_id, troops in recorded.items():
        if abs(vector[band_id] - troops) > RECONCILIATION_TOLERANCE * max(1.0, abs(troops)):
            raise BandChainError(
                f"tick {tick}: the movements give {band_id} {vector[band_id]:.9g} members against "
                f"the recorded {troops:.9g}"
            )


def band_chain(events: pl.DataFrame) -> pl.DataFrame:
    """Per tick and component: the men moved, the bands opened or closed, the share's change.

    ``largest_band_share_delta`` is the component's effect on the largest band's share, and the
    deltas of a tick add up to the change the log records for that tick; ``largest_band_share`` is
    the level after the component's movements, so a reader can follow the chain link by link.

    The window the whole chain covers is the run's: the band layer starts empty, so the state the
    first tick opens from has no band in it and the total is measured from there. The frame covers
    every tick the log holds, so a component that never fired is a column of zeros rather than a
    missing row.
    """
    frame = _band_frame(events)
    signals = _signals(frame)
    states = _states_by_tick(frame)
    ticks = frame.select(pl.col("tick").unique().sort()).get_column("tick").to_list()
    rows: list[dict[str, object]] = []
    vector: dict[str, float] = {}
    level = 0.0
    for raw_tick in ticks:
        tick = int(raw_tick)
        recorded = states.get(tick, {})
        steps: list[tuple[str, float, int]] = []
        snapshots: list[dict[str, float]] = []
        for component in COMPONENTS:
            key = (tick, component)
            opened = signals.opens.get(key, set())
            closed = signals.closes.get(key, set())
            movements = signals.deltas.get(key, [])
            for band_id in opened:
                vector.setdefault(band_id, 0.0)
            for band_id, delta in movements:
                vector[band_id] = vector.get(band_id, 0.0) + delta
            for band_id in closed:
                vector.pop(band_id, None)
            arrivals = sum(delta for _, delta in movements if delta > 0.0)
            losses = sum(-delta for _, delta in movements if delta < 0.0)
            troops = arrivals if arrivals > 0.0 else losses
            steps.append((component, troops, len(opened) - len(closed)))
            snapshots.append(dict(vector))
        _reconcile(vector, recorded, tick)
        # The tick ends where the record says it ends, and the check above has just refused any
        # difference large enough to matter, so the last level is read from the reconciled state.
        snapshots[-1] = dict(vector)
        for (component, troops, count_delta), state in zip(steps, snapshots, strict=True):
            share = _largest_share(state)
            rows.append(
                {
                    "tick": tick,
                    "component": component,
                    "troops": troops,
                    "band_count_delta": count_delta,
                    "band_count": len(state),
                    "largest_band_share_delta": share - level,
                    "largest_band_share": share,
                }
            )
            level = share
        # The next tick opens from the state the log recorded for this one, so the reconstruction
        # cannot drift: every tick is checked against the record, never against its own past.
        vector = dict(recorded)
    return pl.DataFrame(rows, schema=_CHAIN_SCHEMA)


def largest_share_series(events: pl.DataFrame) -> pl.DataFrame:
    """Per tick, the largest band's share of all armed men, as the log records it.

    This is the series the chain's effects are measured against: the recorded states rather than
    the reconstruction, so a reader can check the partition without trusting either reader. It is
    the same measure the military analysis reports, read from the same records.
    """
    _require_band_records(events)
    return band_series(events).select(
        "tick",
        "number_of_bands",
        "total_band_troops",
        "largest_band_troops",
        "largest_band_share",
    )


def band_chain_summary(events: pl.DataFrame) -> dict[str, float]:
    """The chain's headline facts for one run, as numbers a report may print.

    Each component reports the men it moved, the bands it opened net, its effect on the largest
    band's share, and that effect as a share of the whole change in concentration. Those shares are
    shares of a signed total, so a component that pushed the other way carries a negative one, and
    a run whose concentration ends where it started leaves every share at 0.0 rather than dividing
    by nothing.
    """
    chain = band_chain(events)
    series = largest_share_series(events)
    summary: dict[str, float] = {}
    deltas: dict[str, float] = {}
    for component in COMPONENTS:
        rows = chain.filter(pl.col("component") == component)
        delta = float(rows["largest_band_share_delta"].sum())
        deltas[component] = delta
        summary[f"band_chain_troops.{component}"] = float(rows["troops"].sum())
        summary[f"band_chain_bands.{component}"] = float(rows["band_count_delta"].sum())
        summary[f"band_chain_largest_share_delta.{component}"] = delta
    change = sum(deltas.values())
    for component in COMPONENTS:
        summary[f"band_chain_share_of_change.{component}"] = (
            deltas[component] / change if change != 0.0 else 0.0
        )
    edges = series.select(
        pl.col("largest_band_share").first().alias("share_first"),
        pl.col("largest_band_share").last().alias("share_end"),
        pl.col("number_of_bands").first().alias("bands_first"),
        pl.col("number_of_bands").last().alias("bands_end"),
    ).row(0, named=True)
    summary["band_chain_largest_share_first"] = float(edges["share_first"])
    summary["band_chain_largest_share_end"] = float(edges["share_end"])
    summary["band_chain_largest_share_change"] = change
    summary["band_chain_bands_first"] = float(edges["bands_first"])
    summary["band_chain_bands_end"] = float(edges["bands_end"])
    return summary


__all__ = [
    "BAND_DISSOLVED_EVENT",
    "BAND_FORMED_EVENT",
    "BAND_STATE_EVENT",
    "COMPONENTS",
    "DESERTION_EVENT",
    "MOVEMENT_CAUSES",
    "RECRUIT_LEVY_EVENT",
    "BandChainError",
    "band_chain",
    "band_chain_summary",
    "largest_share_series",
]
