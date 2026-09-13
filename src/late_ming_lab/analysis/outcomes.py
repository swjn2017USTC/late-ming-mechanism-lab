"""P10 outcome measures: what one run did, as a fixed set of numbers a comparison can hold.

P10 asks what a mechanism is necessary *for*, which means reducing each run to the same handful of
quantities so an ablation, a sensitivity draw or a counterfactual can be laid beside its baseline.
This module is that reduction. It computes nothing new: every scalar is read from the analysis
module that already owns the measurement — governance indicators, fiscal totals, migration totals,
military totals, trade summary — and the trajectories behind them are returned as frames.

Two of the measures need a rule stated in advance rather than a measurement derived from the data:

```text
breakdown   a run is in breakdown at a sampled tick when at least ``BREAKDOWN_INDICATORS`` of the
            eight declared governance reading lines are crossed at that tick. P07 measured five of
            eight crossing even in calm runs, so the sixth is the earliest count that separates a
            crisis run from its own baseline. It is a reading rule, grade S, never evidence.
market      ``active_link_share`` and ``largest_component_share`` ask whether the market is still
            one market: how many declared trade links carried grain, and whether the links that did
            still tie the nodes into one component.
```

The sentinel is stated where it is used: a run whose breakdown time never arrives reports ``-1.0``
rather than ``NaN``, so a comparison table stays sortable and a reader sees "never", not a hole.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import networkx as nx
import polars as pl

from late_ming_lab.analysis.concentration import trade_summary
from late_ming_lab.analysis.fiscal import county_fiscal_series, fiscal_totals, tax_base
from late_ming_lab.analysis.governance import governance_indicators, governance_summary
from late_ming_lab.analysis.migration import migration_totals, node_migration
from late_ming_lab.analysis.military import garrison_series, military_totals
from late_ming_lab.analysis.scalars import largest, smallest, total
from late_ming_lab.core.clock import MONTHS_PER_YEAR
from late_ming_lab.evidence.parameters import GovernanceIndicatorParameters

#: A run is in breakdown at a tick when at least this many of the eight declared governance reading
#: lines are crossed at that tick. P07 measured five of eight crossing even in calm runs, so the
#: sixth is the earliest count that separates a crisis run from its own baseline. Declared reading
#: rule, grade S, never evidence.
BREAKDOWN_INDICATORS: Final[int] = 6

#: Ticks between two readings of the declared governance lines. One year: the lines are slow state.
BREAKDOWN_SAMPLE_EVERY: Final[int] = 24

#: The run's declared calendar epoch: the default start year of :class:`SimulationConfig`, and the
#: same epoch ``calibration.summary_stats.yearly_series`` reduces with. The frames here take no
#: configuration, so the epoch is fixed rather than passed, and a caller with a different window is
#: expected to state it rather than have it inferred.
_CALENDAR_EPOCH_YEAR: Final[int] = 1625

#: The outcome measures keyed by name, in the order a comparison table should read them.
_SCALAR_KEYS: Final[tuple[str, ...]] = (
    "breakdown",
    "time_to_breakdown",
    "indicators_crossed_end",
    "tax_base_end_mu",
    "tax_base_change_mu",
    "receipts_over_quota_total",
    "households_departed",
    "households_exited",
    "migration_net_node_min",
    "migration_net_node_max",
    "market_active_link_share",
    "market_largest_component_share",
    "military_pay_arrears_end_tael",
    "military_pay_arrears_max_tael",
    "largest_band_share_max",
    "largest_band_share_end",
    "bands_at_end",
    "band_merges",
    "elite_loans",
    "suppressions",
    "trade_shipments",
)


@dataclass(frozen=True, slots=True)
class GovernanceTimeline:
    """The count of crossed declared lines, re-read on the event log's sampled prefixes."""

    ticks: tuple[int, ...]
    crossed_counts: tuple[int, ...]

    def first_breakdown(self, *, minimum: int = BREAKDOWN_INDICATORS) -> int | None:
        """Earliest sampled tick whose crossed count reaches the line, or None if it never does."""
        for tick, crossed in zip(self.ticks, self.crossed_counts, strict=True):
            if crossed >= minimum:
                return tick
        return None


def governance_timeline(
    events: pl.DataFrame,
    *,
    thresholds: GovernanceIndicatorParameters,
    population_adults: float,
    starting_households: float,
    every: int = BREAKDOWN_SAMPLE_EVERY,
) -> GovernanceTimeline:
    """The eight declared lines, re-read on the event log's prefixes.

    The crossing count at tick t is `governance_indicators` evaluated on `events <= t`, so the
    reading lines are exactly the ones the project already declares, not a re-implementation.
    """
    if every < 1:
        raise ValueError("sampling interval must be at least one tick")
    last = int(_last_tick(events))
    sampled = list(range(0, last + 1, every))
    counts: list[int] = []
    for tick in sampled:
        window = events.filter(pl.col("tick") <= tick)
        indicators = governance_indicators(
            window,
            thresholds=thresholds,
            population_adults=population_adults,
            starting_households=starting_households,
        )
        counts.append(int(governance_summary(indicators)["indicators_crossed"]))
    return GovernanceTimeline(ticks=tuple(sampled), crossed_counts=tuple(counts))


def _event_count(events: pl.DataFrame, event_type: str) -> int:
    """How many events of one type the log holds; 0 when it holds none."""
    if events.is_empty() or "event_type" not in events.columns:
        return 0
    return events.filter(pl.col("event_type") == event_type).height


def _last_tick(events: pl.DataFrame) -> int:
    """The last tick the log covers; 0 when it holds nothing.

    The sampling grid is built from the calendar, not from the ticks that happen to carry events, so
    two runs are compared at the same ticks even if one of them records nothing in a month.
    """
    if events.is_empty() or "tick" not in events.columns:
        return 0
    value = events["tick"].max()
    return 0 if value is None else int(str(value))


def market_connectivity(events: pl.DataFrame, *, trade_graph: nx.Graph[str]) -> dict[str, float]:
    """Two declared measures of whether the market is still one market.

    `active_link_share` — share of the declared trade edges that carried at least one shipment.
    `largest_component_share` — share of trade nodes in the largest component of the subgraph the
    active edges induce, counting a node with no active edge as its own component.
    """
    shipments = trade_summary(events)
    active: set[tuple[str, str]] = set()
    for row in shipments.iter_rows(named=True):
        origin = str(row["origin"])
        destination = str(row["destination"])
        if origin == destination or float(row["shipped_shi"] or 0.0) <= 0.0:
            continue
        if trade_graph.has_edge(origin, destination):
            active.add((origin, destination) if origin < destination else (destination, origin))

    declared = trade_graph.number_of_edges()
    nodes: list[str] = list(trade_graph.nodes)
    if nodes:
        subgraph: nx.Graph[str] = nx.Graph()
        subgraph.add_nodes_from(nodes)
        subgraph.add_edges_from(sorted(active))
        largest_component = max(len(component) for component in nx.connected_components(subgraph))
        component_share = largest_component / len(nodes)
    else:
        component_share = 0.0
    return {
        "active_link_share": len(active) / declared if declared > 0 else 0.0,
        "largest_component_share": component_share,
    }


def outcome_scalars(
    events: pl.DataFrame,
    *,
    thresholds: GovernanceIndicatorParameters,
    population_adults: float,
    starting_households: float,
    trade_graph: nx.Graph[str],
    timeline: GovernanceTimeline | None = None,
) -> dict[str, float]:
    """One run's P10 outputs, as a flat mapping of name -> float.

    Every key reports a measurement the project already defines. `breakdown` is 1.0 exactly when the
    run reached the declared line, and `time_to_breakdown` is that sampled tick — or ``-1.0`` when
    it never arrives, the sentinel for "never" stated here so no caller has to read a ``NaN``.
    """
    indicators = governance_indicators(
        events,
        thresholds=thresholds,
        population_adults=population_adults,
        starting_households=starting_households,
    )
    summary = governance_summary(indicators)
    if timeline is None:
        timeline = governance_timeline(
            events,
            thresholds=thresholds,
            population_adults=population_adults,
            starting_households=starting_households,
        )
    breakdown_tick = timeline.first_breakdown()
    fiscal = fiscal_totals(events)
    base = tax_base(events)
    migration = migration_totals(events)
    nodes = node_migration(events)
    military = military_totals(events)
    garrison = garrison_series(events)
    connectivity = market_connectivity(events, trade_graph=trade_graph)
    quota = fiscal["nominal_quota_tael"]

    scalars = {
        "breakdown": 1.0 if breakdown_tick is not None else 0.0,
        "time_to_breakdown": -1.0 if breakdown_tick is None else float(breakdown_tick),
        "indicators_crossed_end": summary["indicators_crossed"],
        "tax_base_end_mu": fiscal["taxable_land_mu_end"],
        "tax_base_change_mu": total(base, "taxable_land_mu_change"),
        "receipts_over_quota_total": (
            fiscal["actual_receipts_tael"] / quota if quota > 0.0 else 0.0
        ),
        "households_departed": migration["households_departed_total"],
        "households_exited": migration["households_exited_total"],
        "migration_net_node_min": smallest(nodes, "net_households"),
        "migration_net_node_max": largest(nodes, "net_households"),
        "market_active_link_share": connectivity["active_link_share"],
        "market_largest_component_share": connectivity["largest_component_share"],
        "military_pay_arrears_end_tael": military["pay_arrears_tael_end"],
        "military_pay_arrears_max_tael": largest(garrison, "pay_arrears_tael"),
        "largest_band_share_max": military["largest_band_share_max"],
        "largest_band_share_end": military["largest_band_share_end"],
        "bands_at_end": military["bands_end"],
        # How often each ablatable mechanism actually fired, so an arm's binding is measured: an
        # ablation that removed nothing shows up here as a counter that never moved.
        "band_merges": float(_event_count(events, "BAND_MERGE")),
        "elite_loans": float(_event_count(events, "ELITE_LOAN")),
        "suppressions": float(_event_count(events, "SUPPRESSION")),
        "trade_shipments": float(_event_count(events, "TRADE_SHIPMENT")),
    }
    return {key: float(scalars[key]) for key in _SCALAR_KEYS}


def outcome_frames(events: pl.DataFrame, *, trade_graph: nx.Graph[str]) -> dict[str, pl.DataFrame]:
    """The trajectories behind the scalars: `tax_base` and `migration_nodes`.

    `tax_base` is one row per calendar year of the run, ``year = 1625 + tick // 12`` (the declared
    epoch above), dated by the year's last tick. The county figures are summed over counties first,
    then reduced the way ``calibration.summary_stats.yearly_series`` reduces them: the stocks
    ``taxable_land_mu`` and ``arrears_tael`` take the year's last value, the flow ``receipts_tael``
    sums over the year. `migration_nodes` is `node_migration` unchanged, one row per node.

    `trade_graph` is accepted so both P10 reductions share one call signature; these two
    trajectories are read from the log alone.
    """
    fiscal = county_fiscal_series(events)
    per_tick = (
        fiscal.group_by("tick")
        .agg(
            [
                pl.col("taxable_land_mu").sum().alias("taxable_land_mu"),
                pl.col("receipts_tael").sum().alias("receipts_tael"),
                pl.col("arrears_tael").sum().alias("arrears_tael"),
            ]
        )
        .sort("tick")
    )
    tax_base_frame = (
        per_tick.with_columns(
            (_CALENDAR_EPOCH_YEAR + (pl.col("tick") // MONTHS_PER_YEAR)).alias("year")
        )
        .group_by("year")
        .agg(
            [
                pl.col("tick").last().alias("tick"),
                pl.col("taxable_land_mu").last().alias("taxable_land_mu"),
                pl.col("receipts_tael").sum().alias("receipts_tael"),
                pl.col("arrears_tael").last().alias("arrears_tael"),
            ]
        )
        .select(["year", "tick", "taxable_land_mu", "receipts_tael", "arrears_tael"])
        .sort("year")
    )
    return {"tax_base": tax_base_frame, "migration_nodes": node_migration(events)}
