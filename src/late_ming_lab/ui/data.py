"""Read-only views over the artifacts the phases already write.

Every tab of the browser reads one of three things this project already produces, and nothing else:

```text
a run directory      manifest.json, summary.json, the event log and the macro frame
                     (storage/run_store.py: manifest.json, summary.json, agent_events.parquet,
                     macro_timeseries.parquet, config.snapshot.yaml)
a batch directory    runs.parquet, governance_timeline.parquet, migration_nodes.parquet and
                     tax_base.parquet (experiments/runner.py, one row set per labelled replicate)
the mechanism cards  docs/mechanisms/cards.yaml (synthesis/report.py)
```

Nothing here runs the model, and nothing here decides what a run means. The per-tick frames are
either columns a batch table already holds or reductions of a run's event log through the analysis
module that owns each measurement — migration flows, band series, garrison series and the county
fiscal series — joined onto the log's own tick grid. Two consequences are stated rather than hidden:

- A **run** directory does not record the county-node set, the scenario's declared trade graph or
  the governance reading thresholds, so this loader does not offer the measurements that need them:
  the crossed-line count, the county filter on price dispersion, and ``market_connectivity``'s
  declared denominators. Where a per-tick measure needs a denominator the run does not record, the
  denominator is the run's own log and the column carrying it is named ``*_observed``, so the two
  numbers are never read as one.
- A **batch** samples the governance lines on one grid and the tax base on another, and its node
  table is written once per run rather than per tick. The loader joins what exists on the tick and
  leaves the holes the batch's own sampling grid leaves; the node table is offered per node, which
  is what it is.

The aggregation rule for a batch is the one the phase pinned: a count adds up over the replicated
runs in scope and a share does not. The frame's ``summary["aggregation"]`` states which was applied
and over how many runs.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import networkx as nx
import polars as pl

from late_ming_lab.analysis.concentration import SHIPMENT_EVENT
from late_ming_lab.analysis.distress import with_trigger_fields
from late_ming_lab.analysis.fiscal import FISCAL_MEASURES, FiscalAnalysisError, county_fiscal_series
from late_ming_lab.analysis.migration import (
    ARRIVAL_EVENT,
    DEPARTURE_EVENT,
    EXIT_EVENT,
    MigrationAnalysisError,
    migration_flows,
)
from late_ming_lab.analysis.military import MilitaryAnalysisError, band_series, garrison_series
from late_ming_lab.synthesis.schema import (
    CARDS_FILE,
    DOCS_ROOT,
    MechanismBook,
    load_book,
)

#: The two artifacts a run directory is recognised by, and the summary beside them. The storage
#: module writes ``agent_events.parquet`` and ``macro_timeseries.parquet``; the phase brief calls
#: the same two artifacts ``events.parquet`` and ``macro.parquet``. Both name one artifact.
RUN_MANIFEST_FILE: Final[str] = "manifest.json"
RUN_SUMMARY_FILE: Final[str] = "summary.json"
RUN_EVENT_FILES: Final[tuple[str, ...]] = ("agent_events.parquet", "events.parquet")
RUN_MACRO_FILES: Final[tuple[str, ...]] = ("macro_timeseries.parquet", "macro.parquet")

#: The batch directory the experiment runner writes, in its own file names.
BATCH_RUNS_FILE: Final[str] = "runs.parquet"
BATCH_GOVERNANCE_FILE: Final[str] = "governance_timeline.parquet"
BATCH_MIGRATION_FILE: Final[str] = "migration_nodes.parquet"
BATCH_TAX_BASE_FILE: Final[str] = "tax_base.parquet"

#: The tick-keyed measurements the Trade and Armed-groups tabs draw, sliced out of the per-tick
#: frame whichever kind produced it.
_TRADE_COLUMNS: Final[tuple[str, ...]] = ("active_link_share", "largest_component_share")
_BAND_COLUMNS: Final[tuple[str, ...]] = ("number_of_bands", "largest_band_share")

#: Columns that identify a row rather than measure anything: they key, filter or scope the frames
#: and are never combined into one.
_NON_METRIC: Final[frozenset[str]] = frozenset({"label", "replicate", "node_id"})
_KEYS: Final[frozenset[str]] = frozenset({"tick", "node_id"})

#: How a column reads, as (human label, unit, rule a batch aggregate combines it with).
#:
#: ``sum`` is for a quantity that adds up over the replicated runs in scope — households, mu, shi,
#: tael, lines — ``mean`` for one that does not, and ``first`` for a calendar label, which is
#: neither. A column not listed here is still offered, because it exists, under its own name with no
#: unit and the mean over the replicates: a number an artifact adds later is never claimed to be in
#: a unit the artifact did not state, and never grows with the size of the batch.
_SUM: Final[str] = "sum"
_MEAN: Final[str] = "mean"
_FIRST: Final[str] = "first"

_MEASURES: Final[dict[str, tuple[str, str, str]]] = {
    # Calendar, from macro_timeseries.parquet.
    "year": ("calendar year of the tick", "year", _FIRST),
    "month_of_year": ("month of the year", "month", _FIRST),
    # The governance sample, from governance_timeline.parquet. A count of crossed reading lines,
    # not a score: it is summed, which reports how many lines the runs in scope crossed at a tick.
    "crossed": ("declared governance reading lines crossed", "lines", _SUM),
    # Migration, from analysis/migration.py.
    "households_departed": ("households that left one node for another", "households", _SUM),
    "adults_departed": ("adults that left one node for another", "adults", _SUM),
    "land_abandoned_mu": ("land abandoned at the origin", "mu", _SUM),
    "households_arrived": ("households that arrived at a node", "households", _SUM),
    "adults_arrived": ("adults that arrived at a node", "adults", _SUM),
    "households_exited": ("households that left the modelled region", "households", _SUM),
    "adults_exited": ("adults that left the modelled region", "adults", _SUM),
    "households_left": ("households this node lost to another", "households", _SUM),
    "households_gone": ("households this node lost to the region's outside", "households", _SUM),
    "households_came": ("households this node gained", "households", _SUM),
    "net_households": ("net households this node gained", "households", _SUM),
    # Armed bands, from analysis/military.py.
    "number_of_bands": ("armed bands standing", "bands", _SUM),
    "total_band_troops": ("armed men in bands", "troops", _SUM),
    "largest_band_troops": ("armed men in the largest band", "troops", _SUM),
    "largest_band_share": ("share of armed men in the largest band", "share", _MEAN),
    "mean_band_troops": ("mean band size", "troops", _MEAN),
    # Garrisons, from analysis/military.py.
    "garrison_troops": ("soldiers in garrison", "troops", _SUM),
    "garrison_grain_shi": ("grain held by the garrisons", "shi", _SUM),
    "pay_arrears_tael": ("pay owed to the garrisons and not paid", "tael", _SUM),
    "mean_morale": ("mean garrison morale", "index", _MEAN),
    "mean_cohesion": ("mean garrison cohesion", "index", _MEAN),
    # County fiscal state, from analysis/fiscal.py, summed over the counties.
    "quota_tael": ("tax quota the counties assessed", "tael", _SUM),
    "assessment_rate": ("assessment rate the counties applied", "rate", _MEAN),
    "collection_effort": ("collection effort the counties spent", "index", _MEAN),
    "reachable_tael": ("receipts the counties could reach", "tael", _SUM),
    "receipts_tael": ("tax the counties actually received", "tael", _SUM),
    "collection_cost_tael": ("what collecting the tax cost", "tael", _SUM),
    "net_receipts_tael": ("receipts net of collection cost", "tael", _SUM),
    "arrears_tael": ("tax left uncollected", "tael", _SUM),
    "arrears_delta_tael": ("change in the arrears stock", "tael", _SUM),
    "taxable_land_mu": ("land the counties can see", "mu", _SUM),
    "hidden_land_mu": ("land the counties cannot see", "mu", _SUM),
    "relief_released_shi": ("relief grain released", "shi", _SUM),
    "relief_cost_tael": ("what the relief cost", "tael", _SUM),
    "silver_tael": ("silver held by the counties", "tael", _SUM),
    "granary_shi": ("grain in the county granaries", "shi", _SUM),
    # Trade, from the links a run's own log carried; see :func:`_trade_by_tick`.
    "active_links": ("trade links that carried grain at this tick", "links", _SUM),
    "links_observed": ("trade links this source's log covers", "links", _SUM),
    "nodes_observed": ("nodes this source's trade log covers", "nodes", _SUM),
    "active_link_share": ("share of the run's trade links carrying grain", "share", _MEAN),
    "largest_component_share": ("share of trade nodes still in one group", "share", _MEAN),
}

#: The per-node migration frame, in the columns ``analysis.migration.node_migration`` uses, plus the
#: tick the whole-run table does not carry.
_NODE_MIGRATION_SCHEMA: Final[dict[str, Any]] = {
    "tick": pl.Int64,
    "node_id": pl.String,
    "households_left": pl.Float64,
    "land_abandoned_mu": pl.Float64,
    "households_gone": pl.Float64,
    "households_came": pl.Float64,
    "net_households": pl.Float64,
}


#: The three flows the node frame is built from, in the attribution rule's own terms.
@dataclass(frozen=True, slots=True)
class _NodeFlow:
    """One of the three flows the node frame is built from: what to read, and what to call it."""

    event: str
    fields: tuple[str, ...]
    outcome_prefix: str | None
    columns: dict[str, str]


_NODE_FLOWS: Final[tuple[_NodeFlow, ...]] = (
    _NodeFlow(
        DEPARTURE_EVENT,
        ("households_migrated", "land_abandoned_mu"),
        "migrated-to",
        {"households_migrated": "households_left", "land_abandoned_mu": "land_abandoned_mu"},
    ),
    _NodeFlow(EXIT_EVENT, ("households_exited",), None, {"households_exited": "households_gone"}),
    _NodeFlow(
        ARRIVAL_EVENT,
        ("households_arrived",),
        "arrived-from",
        {"households_arrived": "households_came"},
    ),
)

#: The two fiscal columns that are a property of each county rather than something the region holds;
#: every other measure is summed over the counties.
_FISCAL_RATES: Final[frozenset[str]] = frozenset({"assessment_rate", "collection_effort"})

#: The analysis modules' own "this log cannot support this measurement" errors. A run that never
#: recorded a garrison has no garrison series; it does not have a broken view.
_ABSENT_MEASURE: Final[tuple[type[Exception], ...]] = (
    MigrationAnalysisError,
    MilitaryAnalysisError,
    FiscalAnalysisError,
)

#: What a manifest field that only one side of a comparison carries reads as.
_ABSENT: Final[str] = "<absent>"


class UiDataError(ValueError):
    """Raised when a path is not an artifact this browser can read, or a comparison it refuses."""


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    """One column a view can draw: its frame, its unit, and the label the selector shows."""

    key: str
    label: str
    unit: str
    scope: str


@dataclass(frozen=True, slots=True)
class RunView:
    """One run or batch, read: its provenance, its per-tick series, and the frames behind them."""

    label: str
    source: Path
    kind: str
    manifest: dict[str, Any]
    summary: dict[str, Any]
    series: pl.DataFrame
    county_nodes: tuple[str, ...]
    migration: pl.DataFrame
    trade: pl.DataFrame
    bands: pl.DataFrame
    runs: pl.DataFrame


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    """Two views side by side, on the ticks they share, with their provenance differences listed."""

    left: RunView
    right: RunView
    aligned: pl.DataFrame
    series: tuple[str, ...]
    manifest_differences: tuple[tuple[str, str, str], ...]


def load_run_view(path: str | Path, *, label: str | None = None) -> RunView:
    """Read one run directory or one batch directory, deciding which it is from what it holds.

    A directory holding a manifest and an event log is a run; a directory holding ``runs.parquet``
    and a manifest is a batch. A batch's ``label`` selects one labelled arm and is refused for a
    run, which holds no arms; without it a batch is combined over every label it holds.
    """
    directory = Path(path)
    if not directory.is_dir():
        raise UiDataError(f"{directory} is not a directory")
    manifest_path = directory / RUN_MANIFEST_FILE
    events_path = _existing(directory, RUN_EVENT_FILES)
    if manifest_path.is_file() and events_path is not None:
        if label is not None:
            raise UiDataError(
                f"{directory} is a single run: it holds no labelled replicates to select from"
            )
        return _run_view(directory, manifest_path, events_path)
    runs_path = directory / BATCH_RUNS_FILE
    if manifest_path.is_file() and runs_path.is_file():
        return _batch_view(directory, manifest_path, runs_path, label=label)
    names = sorted(entry.name for entry in directory.iterdir())
    found = ", ".join(names[:8]) + (f" and {len(names) - 8} more" if len(names) > 8 else "")
    raise UiDataError(
        f"{directory} is neither a run ({RUN_MANIFEST_FILE} and {RUN_EVENT_FILES[-1]}) nor a batch "
        f"({BATCH_RUNS_FILE} and {RUN_MANIFEST_FILE}); it holds {found or 'nothing'}"
    )


def series_catalog(view: RunView) -> tuple[SeriesSpec, ...]:
    """Every column the view can draw, per-tick first, then the per-node columns of its node table.

    Only columns the frames actually carry are listed: a series the source does not record is
    absent from the catalog rather than offered as an empty line, and a column that is not numeric
    (a month name, a warm-up period) is not a series at all.
    """
    specs: list[SeriesSpec] = []
    seen: set[str] = set()
    for frame, scope in ((view.series, "tick"), (view.migration, "node")):
        for name, dtype in frame.schema.items():
            if name in _KEYS or name in seen or not dtype.is_numeric():
                continue
            seen.add(name)
            label, unit, _ = _measure(name)
            specs.append(SeriesSpec(key=name, label=label, unit=unit, scope=scope))
    return tuple(specs)


def compare_runs(left: str | Path, right: str | Path) -> ComparisonResult:
    """Two sources on their shared per-tick series, or the refusal that says they cannot be.

    Two views whose tick counts differ are refused: the batches sample different grids, so a join
    would align a reading with a tick that carries no reading and report the misalignment as a
    divergence. Every field of the two manifests that differs is reported beside the aligned frame,
    so a comparison of two arms is never read as a comparison of the same code.
    """
    left_view = load_run_view(left)
    right_view = load_run_view(right)
    left_ticks = _tick_count(left_view)
    right_ticks = _tick_count(right_view)
    if left_ticks != right_ticks:
        raise UiDataError(
            f"{left_view.label} carries {left_ticks} ticks and {right_view.label} carries "
            f"{right_ticks}: a divergence is not a comparison"
        )
    shared = tuple(
        sorted(
            {spec.key for spec in series_catalog(left_view) if spec.scope == "tick"}
            & {spec.key for spec in series_catalog(right_view) if spec.scope == "tick"}
        )
    )
    aligned = _aligned(left_view.series, right_view.series, shared)
    return ComparisonResult(
        left=left_view,
        right=right_view,
        aligned=aligned,
        series=shared,
        manifest_differences=_manifest_differences(left_view.manifest, right_view.manifest),
    )


def load_cards(root: str | Path) -> MechanismBook:
    """The mechanism book, read exactly as ``synthesis.schema.load_book`` reads it.

    ``root`` is the repository root, the same argument ``synthesis.report.write_mechanism_docs``
    takes; the cards live at ``docs/mechanisms/cards.yaml`` under it.
    """
    path = Path(root) / DOCS_ROOT / CARDS_FILE
    if not path.is_file():
        raise UiDataError(f"no mechanism cards at {path}")
    try:
        return load_book(path)
    except ValueError as error:
        raise UiDataError(f"{path} does not read as a mechanism book: {error}") from error


def _run_view(directory: Path, manifest_path: Path, events_path: Path) -> RunView:
    manifest = _read_json(manifest_path)
    summary_path = directory / RUN_SUMMARY_FILE
    summary = _read_json(summary_path) if summary_path.is_file() else {}
    events = pl.read_parquet(events_path)
    macro_path = _existing(directory, RUN_MACRO_FILES)
    macro = pl.read_parquet(macro_path) if macro_path is not None else None
    series = _run_series(events, macro)
    migration = _node_migration_by_tick(events)
    run_id = str(manifest.get("run_id", directory.name))
    return RunView(
        label=run_id,
        source=directory,
        kind="run",
        manifest=manifest,
        summary=summary,
        series=series,
        county_nodes=_nodes_of(migration),
        migration=migration,
        trade=_named_slice(series, _TRADE_COLUMNS),
        bands=_named_slice(series, _BAND_COLUMNS),
        runs=_empty_replicates(),
    )


def _batch_view(
    directory: Path, manifest_path: Path, runs_path: Path, *, label: str | None
) -> RunView:
    manifest = _read_json(manifest_path)
    runs = pl.read_parquet(runs_path)
    labels = (
        tuple(sorted({str(value) for value in runs["label"].to_list()}))
        if "label" in runs.columns
        else ()
    )
    if label is not None and label not in labels:
        raise UiDataError(
            f"{directory} holds no label {label!r}; it holds {', '.join(labels) or 'no labels'}"
        )
    scope = runs if label is None else runs.filter(pl.col("label") == label)
    series = _batch_series(directory, label)
    migration = _batch_migration(directory, label)
    replicates = int(scope["replicate"].n_unique()) if "replicate" in scope.columns else 0
    name = str(manifest.get("label", directory.name))
    summary: dict[str, Any] = {
        "labels": labels,
        "replicates": replicates,
        "run_count": scope.height,
        "aggregation": _aggregation_note(labels, replicates, label=label),
    }
    return RunView(
        label=name if label is None else f"{name} / {label}",
        source=directory,
        kind="batch",
        manifest=manifest,
        summary=summary,
        series=series,
        county_nodes=_nodes_of(migration),
        migration=migration,
        trade=_named_slice(series, _TRADE_COLUMNS),
        bands=_named_slice(series, _BAND_COLUMNS),
        runs=scope,
    )


def _batch_series(directory: Path, label: str | None) -> pl.DataFrame:
    """The batch's per-tick frame: what its own tables carry on their own sampling grids.

    The governance sample and the tax base are read on different grids — one a year, the other a
    year dated by its last tick — so the two are joined on the tick and the holes each grid leaves
    in the other stay holes. Inventing a value between two readings is not this loader's business.
    """
    frames: list[pl.DataFrame] = []
    for name in (BATCH_GOVERNANCE_FILE, BATCH_TAX_BASE_FILE):
        path = directory / name
        if path.is_file():
            frames.append(_combined(_scoped(pl.read_parquet(path), label), keys=("tick",)))
    return _joined_on_tick(frames)


def _batch_migration(directory: Path, label: str | None) -> pl.DataFrame:
    """The batch's node table, combined over the runs in scope.

    It is written once per run rather than per tick, so the frame is per node and carries no tick;
    a run's node frame, built from the log, does carry one.
    """
    path = directory / BATCH_MIGRATION_FILE
    if not path.is_file():
        schema = {name: dtype for name, dtype in _NODE_MIGRATION_SCHEMA.items() if name != "tick"}
        return pl.DataFrame(schema=schema)
    return _combined(_scoped(pl.read_parquet(path), label), keys=("node_id",))


def _run_series(events: pl.DataFrame, macro: pl.DataFrame | None) -> pl.DataFrame:
    """The run's per-tick frame: the log's own ticks, its calendar, and the measures read."""
    blocks = [
        block
        for block in (
            _block(lambda: migration_flows(events)),
            _block(lambda: band_series(events)),
            _block(lambda: garrison_series(events)),
            _block(lambda: _county_state_by_tick(events)),
            _block(lambda: _trade_by_tick(events)),
        )
        if block is not None
    ]
    frames = [frame for frame in (macro, *blocks) if frame is not None and "tick" in frame.columns]
    if not frames:
        return pl.DataFrame(schema={"tick": pl.Int64})
    spine = frames[0].select("tick")
    for frame in frames[1:]:
        spine = pl.concat([spine, frame.select("tick")]).unique()
    series = spine.sort("tick")
    for frame in frames:
        added = [name for name in frame.columns if name != "tick" and name not in series.columns]
        series = series.join(frame.select(["tick", *added]), on="tick", how="left")
    return series


def _block(source: Callable[[], pl.DataFrame]) -> pl.DataFrame | None:
    """One per-tick derivation, or nothing when this run's log does not carry what it needs."""
    try:
        return source()
    except _ABSENT_MEASURE:
        return None


def _county_state_by_tick(events: pl.DataFrame) -> pl.DataFrame:
    """The county state summed over the counties, per tick.

    The reduction is ``analysis.outcomes.outcome_frames``': the counties are summed, because each
    column is a stock the region holds or a flow it moved. The two rate columns are the exception —
    a rate belongs to the county that applied it — so they are averaged, and their unit says so.
    """
    series = county_fiscal_series(events)
    return (
        series.group_by("tick")
        .agg(
            [
                (pl.col(name).mean() if name in _FISCAL_RATES else pl.col(name).sum()).alias(name)
                for name in FISCAL_MEASURES
            ]
        )
        .sort("tick")
    )


def _trade_by_tick(events: pl.DataFrame) -> pl.DataFrame:
    """Per tick: how much of the run's trade network was still carrying grain.

    The rule is ``analysis.outcomes.market_connectivity``'s — a link counts once it has carried
    grain, and a node with no active link is its own component — but the denominators there are the
    scenario's *declared* trade graph, which a run directory does not record. Here they are the
    links and nodes this run's own shipment log covers, and ``links_observed``/``nodes_observed``
    carry them so the two measures are never read as one. A tick with no shipment reads zero, the
    way ``analysis.military.band_series`` reads a tick with no band: nothing moved, which is a
    measurement.
    """
    empty = pl.DataFrame(
        schema={
            "tick": pl.Int64,
            "active_links": pl.Int64,
            "links_observed": pl.Int64,
            "nodes_observed": pl.Int64,
            "active_link_share": pl.Float64,
            "largest_component_share": pl.Float64,
        }
    )
    shipments = events.filter(pl.col("event_type") == SHIPMENT_EVENT)
    if shipments.is_empty() or "trigger_json" not in shipments.columns:
        return empty
    carried = (
        with_trigger_fields(shipments, ("shi",))
        .with_columns(
            pl.col("outcome").str.split(":").list.get(1, null_on_oob=True).alias("destination")
        )
        .filter(
            (pl.col("shi") > 0.0)
            & pl.col("destination").is_not_null()
            & (pl.col("region") != pl.col("destination"))
        )
    )
    nodes = sorted(
        {str(value) for value in carried["region"].to_list()} | _strings(carried, "destination")
    )
    if not nodes:
        return empty
    links: set[tuple[str, str]] = set()
    per_tick: dict[int, set[tuple[str, str]]] = {}
    for tick, origin, destination in carried.select(["tick", "region", "destination"]).iter_rows():
        link = _link(str(origin), str(destination))
        links.add(link)
        per_tick.setdefault(int(tick), set()).add(link)
    records = [
        _trade_row(int(tick), per_tick.get(int(tick), set()), nodes, len(links))
        for tick in events["tick"].unique().sort().to_list()
    ]
    return pl.DataFrame(records, schema=empty.schema)


def _trade_row(
    tick: int, active: set[tuple[str, str]], nodes: list[str], observed_links: int
) -> dict[str, float]:
    graph: nx.Graph[str] = nx.Graph()
    graph.add_nodes_from(nodes)
    graph.add_edges_from(sorted(active))
    largest = max(len(component) for component in nx.connected_components(graph))
    return {
        "tick": tick,
        "active_links": len(active),
        "links_observed": observed_links,
        "nodes_observed": len(nodes),
        "active_link_share": len(active) / observed_links if observed_links else 0.0,
        "largest_component_share": largest / len(nodes),
    }


def _node_migration_by_tick(events: pl.DataFrame) -> pl.DataFrame:
    """Per tick and node: households that left, exited, arrived, and the net that follows.

    The attribution rule is ``analysis.migration.node_migration``'s: a departure and an exit belong
    to the origin node, an arrival to the destination, and ``net_households`` counts arrivals minus
    departures, because an exit leaves no arrival behind. The one change is the grouping key — that
    table reduces the whole run, this one keeps the tick, because the map tab slides over it.
    """
    if events.is_empty() or "trigger_json" not in events.columns:
        return pl.DataFrame(schema=_NODE_MIGRATION_SCHEMA)
    flows = [(flow, _node_flow(events, flow)) for flow in _NODE_FLOWS]
    present = [frame for _, frame in flows if frame is not None]
    if not present:
        return pl.DataFrame(schema=_NODE_MIGRATION_SCHEMA)
    keys = present[0].select(["tick", "region"])
    for frame in present[1:]:
        keys = pl.concat([keys, frame.select(["tick", "region"])]).unique()
    joined = keys
    for flow, block in flows:
        if block is None:
            joined = joined.with_columns(
                [pl.lit(0.0).alias(name) for name in flow.columns.values()]
            )
        else:
            joined = joined.join(block, on=["tick", "region"], how="left")
    return (
        joined.with_columns(
            [
                pl.col(name).fill_null(0.0)
                for name in joined.columns
                if name not in ("tick", "region")
            ]
        )
        .with_columns(
            (pl.col("households_came") - pl.col("households_left")).alias("net_households")
        )
        .rename({"region": "node_id"})
        .select([*_NODE_MIGRATION_SCHEMA])
        .sort(["tick", "node_id"])
    )


def _node_flow(events: pl.DataFrame, flow: _NodeFlow) -> pl.DataFrame | None:
    """One node flow per tick, or nothing when the log holds no such event."""
    selected = events.filter(pl.col("event_type") == flow.event)
    if selected.is_empty():
        return None
    tagged = with_trigger_fields(selected, flow.fields)
    if flow.outcome_prefix is not None:
        tagged = tagged.filter(pl.col("outcome").str.starts_with(flow.outcome_prefix))
    if tagged.is_empty():
        return None
    return tagged.group_by(["tick", "region"]).agg(
        [pl.col(name).sum().alias(alias) for name, alias in flow.columns.items()]
    )


def _combined(frame: pl.DataFrame, *, keys: Sequence[str]) -> pl.DataFrame:
    """One row per key combination, every remaining numeric column combined by its own rule."""
    metrics = [
        name
        for name, dtype in frame.schema.items()
        if name not in keys and name not in _NON_METRIC and dtype.is_numeric()
    ]
    if not metrics:
        return frame.select(list(keys)).unique().sort(list(keys))
    return frame.group_by(list(keys)).agg([_combine(name) for name in metrics]).sort(list(keys))


def _combine(name: str) -> pl.Expr:
    rule = _measure(name)[2]
    if rule == _SUM:
        return pl.col(name).sum().alias(name)
    if rule == _FIRST:
        return pl.col(name).first().alias(name)
    return pl.col(name).mean().alias(name)


def _measure(name: str) -> tuple[str, str, str]:
    """The declared reading of a column, or the honest default for one that is not declared."""
    return _MEASURES.get(name, (name.replace("_", " "), "", _MEAN))


def _scoped(frame: pl.DataFrame, label: str | None) -> pl.DataFrame:
    if label is None or "label" not in frame.columns:
        return frame
    return frame.filter(pl.col("label") == label)


def _joined_on_tick(frames: Sequence[pl.DataFrame]) -> pl.DataFrame:
    """The frames side by side on the tick, keeping every tick either of them read."""
    if not frames:
        return pl.DataFrame(schema={"tick": pl.Int64})
    joined = frames[0]
    for frame in frames[1:]:
        joined = joined.join(frame, on="tick", how="full", coalesce=True)
    return joined.sort("tick")


def _named_slice(series: pl.DataFrame, columns: tuple[str, ...]) -> pl.DataFrame:
    """The per-tick frame restricted to the named measurements.

    When the source does not record them — a batch's tables carry no link counts — the frame is
    empty and keeps the names, so which measurement is absent is visible rather than implied by a
    column that quietly disappeared.
    """
    present = [name for name in columns if name in series.columns]
    if not present:
        return pl.DataFrame(schema={"tick": pl.Int64, **{name: pl.Float64() for name in columns}})
    return series.select(["tick", *present])


def _aligned(left: pl.DataFrame, right: pl.DataFrame, shared: tuple[str, ...]) -> pl.DataFrame:
    """Both sides of a comparison on one tick column, one column per side per shared series."""
    left_side = left.select(["tick", *shared]).rename({key: f"{key}@left" for key in shared})
    right_side = right.select(["tick", *shared]).rename({key: f"{key}@right" for key in shared})
    return left_side.join(right_side, on="tick", how="full", coalesce=True).sort("tick")


def _manifest_differences(
    left: dict[str, Any], right: dict[str, Any]
) -> tuple[tuple[str, str, str], ...]:
    """Every provenance field the two manifests state differently, sorted by field name."""
    differences: list[tuple[str, str, str]] = []
    for field in sorted(set(left) | set(right)):
        left_value = left.get(field, _ABSENT)
        right_value = right.get(field, _ABSENT)
        if left_value != right_value:
            differences.append((field, _shown(left_value), _shown(right_value)))
    return tuple(differences)


def _shown(value: object) -> str:
    if value is None or isinstance(value, str):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return _json(value)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _tick_count(view: RunView) -> int:
    return int(view.series["tick"].n_unique()) if "tick" in view.series.columns else 0


def _nodes_of(migration: pl.DataFrame) -> tuple[str, ...]:
    """The nodes a source's own migration frame attributes households to.

    Which nodes are counties is a property of the scenario's dataset, and a run directory does not
    record it, so the set is read from the frame rather than guessed from the node names.
    """
    if "node_id" not in migration.columns:
        return ()
    return tuple(sorted({str(value) for value in migration["node_id"].to_list()}))


def _aggregation_note(labels: tuple[str, ...], replicates: int, *, label: str | None) -> str:
    scope = f"label {label}" if label is not None else f"{len(labels)} labels"
    return (
        f"combined over {scope} and {replicates} replicated runs per tick: summed where the "
        "column's unit is a count (households, mu, shi, tael, lines), averaged where it is a share "
        "or a rate"
    )


def _strings(frame: pl.DataFrame, column: str) -> set[str]:
    return {str(value) for value in frame[column].to_list()}


def _link(origin: str, destination: str) -> tuple[str, str]:
    return (origin, destination) if origin < destination else (destination, origin)


def _existing(directory: Path, names: Sequence[str]) -> Path | None:
    for name in names:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise UiDataError(f"{path} does not hold a JSON object")
    return payload


def _empty_replicates() -> pl.DataFrame:
    """A single run's replicate frame: no outcomes, and the two keys so a caller may select."""
    return pl.DataFrame(schema={"label": pl.String(), "replicate": pl.Int64()})
