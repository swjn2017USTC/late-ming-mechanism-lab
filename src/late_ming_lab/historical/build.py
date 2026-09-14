"""Assembling, validating and storing the historical core.

One entry point turns the raw snapshots into `historical-core-v1`: nodes chosen by the declared
selection rule, three candidate and accepted edge sets, an annual observed climate index, the
coverage reports about all of it, and a manifest that names every byte the build read.

```text
build    python -m late_ming_lab.historical.build --root .
load     late_ming_lab.historical.build.load_core(".")   the tables a run reads
```

What lands in the repository and what does not is a rights decision, not a convenience one. The
stored tables are *derived*: node identities and coordinates for a dozen seats, distances and link
existence, and counts of recorded events. None of them is a CHGIS layer, a REACHES record, or a
transcription of one, which is what the two licences require; the raw files stay under
`data/raw/private/`, ignored by git, and the manifest records their hashes so a rebuild can prove it
read the same bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import polars as pl
from pydantic import BaseModel, ConfigDict

from late_ming_lab.evidence.grades import EvidenceGrade
from late_ming_lab.evidence.parameters import (
    HistoricalCoreParameters,
    core_default_historical_core_parameters,
)
from late_ming_lab.evidence.snapshots import load_snapshots
from late_ming_lab.historical import coverage as coverage_module
from late_ming_lab.historical import edges as edges_module
from late_ming_lab.historical import selection as selection_module
from late_ming_lab.historical.coverage import FieldProvenance
from late_ming_lab.historical.forcing import (
    AllocationMode,
    MissingCoveragePolicy,
    annual_provenance,
    build_annual_index,
)
from late_ming_lab.historical.inputs import (
    load_category_names,
    load_county_points,
    load_reaches_events,
)
from late_ming_lab.historical.provenance import (
    CHGIS_CHANGES,
    CHGIS_CITATION,
    CHGIS_SOURCE_ID,
    CORE_DATASET_ID,
    CORE_SCHEMA_VERSION,
    COURIER_ROUTES,
    REACHES_SOURCE_ID,
    chgis_derived,
)
from late_ming_lab.historical.selection import (
    SelectionReport,
    SelectionRule,
    candidate_filters,
    external_exits,
    node_table,
    select_nodes,
)
from late_ming_lab.networks.adapter import EDGE_COLUMNS, NODE_COLUMNS, dataset_from_frames
from late_ming_lab.networks.dataset import SpatialDataset
from late_ming_lab.networks.edges import GraphKind
from late_ming_lab.storage.tables import write_table

#: Where the derived tables live. Versioned: a V2 rebuild writes a new directory rather than
#: overwriting the previous core.
CORE_ROOT: Final[str] = "data/normalized/v2/historical-core-v1"
NODES_TABLE: Final[str] = "nodes.parquet"
CLIMATE_TABLE: Final[str] = "climate-annual.parquet"
MANIFEST_FILE: Final[str] = "manifest.json"
REPORT_FILE: Final[str] = "docs/v2/coverage-historical-core-v1.md"

#: Which boundary role each graph needs, for the connector step's node-set restriction.
REQUIRED_ROLE: Final[dict[str, str]] = {
    "trade": "trade-link",
    "migration": "migration-exit",
    "military": "military-link",
}

#: The stored node table carries the adapter's columns plus the CHGIS identity, so a reader can
#: trace a node back to the seat it came from without re-reading the layer.
STORED_NODE_EXTRA: Final[tuple[str, ...]] = (
    "name_py",
    "name_ch",
    "chgis_sys_id",
    "begin_year",
    "end_year",
)


class CoreBuildError(RuntimeError):
    """Raised when the core cannot be built to its declared rule."""


class CoreManifest(BaseModel):
    """What the build read, what it decided, and what it produced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str = CORE_DATASET_ID
    schema_version: str = CORE_SCHEMA_VERSION
    built_from: dict[str, str]
    """Snapshot id -> SHA-256 of the raw file the build read."""
    selection: SelectionRule
    selection_report: dict[str, Any]
    parameters_version: str
    climate: dict[str, Any]
    stations: int = 0
    edges: dict[str, dict[str, int]]
    tables: dict[str, str]
    """File name -> SHA-256 of the stored table."""
    rights: str
    coverage_report: str


@dataclass(frozen=True, slots=True)
class HistoricalCore:
    """The loaded core: the tables, and the rule and reports that produced them."""

    nodes: pl.DataFrame
    annual: pl.DataFrame
    edges: dict[str, tuple[pl.DataFrame, pl.DataFrame]]
    manifest: CoreManifest
    field_provenance: tuple[FieldProvenance, ...]

    @property
    def parameters(self) -> HistoricalCoreParameters:
        return core_default_historical_core_parameters()

    def county_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.nodes.filter(pl.col("kind") == "county")["node_id"].to_list()))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_hashes(root: Path) -> dict[str, str]:
    """The snapshot ids and hashes the build reads, taken from the manifest rather than guessed."""
    manifest = load_snapshots(root)
    wanted = {
        "chgis-v6-county-points",
        "chgis-v6-courier-routes",
        "chgis-v6-courier-stations",
        "reaches-noaa-data-v31",
        "reaches-noaa-codes-haz",
        "reaches-noaa-codes-met",
        "reaches-noaa-codes-other",
    }
    return {record.id: str(record.acquisition.sha256) for record in manifest if record.id in wanted}


def field_provenance(annual_rows: int) -> tuple[FieldProvenance, ...]:
    """One row per factual field of the stored tables: grade, source, locator, missing count.

    This is the answer to "does every fact have a provenance?" in a form a test can check: the
    stored tables are enumerated field by field, including the fields whose value is a defined zero
    rather than a record.
    """
    chgis_locator = CHGIS_COUNTY_POINTS_LOCATOR
    reaches_locator = REACHES_LOCATOR
    node_fields = {
        "node_id": ("S", None, "our identifier, from the seat's pinyin name", 0),
        "kind": ("S", None, "county or external, by the node's role", 0),
        "province": ("B", CHGIS_SOURCE_ID, chgis_locator, 0),
        "zone": ("S", None, "the declared agrarian-zone rule", 0),
        "latitude": ("B", CHGIS_SOURCE_ID, chgis_locator, 0),
        "longitude": ("B", CHGIS_SOURCE_ID, chgis_locator, 0),
        "location_uncertainty_km": ("S", None, "declared radius; CHGIS states none", 0),
        "name_py": ("B", CHGIS_SOURCE_ID, chgis_locator, 0),
        "name_ch": ("B", CHGIS_SOURCE_ID, chgis_locator, 0),
        "chgis_sys_id": ("B", CHGIS_SOURCE_ID, chgis_locator, 0),
        "begin_year": ("B", CHGIS_SOURCE_ID, chgis_locator, 0),
        "end_year": ("B", CHGIS_SOURCE_ID, chgis_locator, 0),
        "external_roles": ("S", None, "the declared exit role of a boundary node", 0),
    }
    annual_fields = {
        "severity_index": ("C", REACHES_SOURCE_ID, reaches_locator, 0),
        "drought_events": ("B", REACHES_SOURCE_ID, reaches_locator, 0),
        "famine_events": ("B", REACHES_SOURCE_ID, reaches_locator, 0),
        "crop_events": ("B", REACHES_SOURCE_ID, reaches_locator, 0),
        "pest_events": ("B", REACHES_SOURCE_ID, reaches_locator, 0),
        "total_events": ("B", REACHES_SOURCE_ID, reaches_locator, 0),
        "records": ("B", REACHES_SOURCE_ID, reaches_locator, 0),
    }
    rows: list[FieldProvenance] = []
    for table, fields, count in (
        (NODES_TABLE, node_fields, 0),
        (CLIMATE_TABLE, annual_fields, annual_rows),
    ):
        for field, (grade, source_id, basis, missing) in fields.items():
            rows.append(
                FieldProvenance(
                    table=table,
                    field=field,
                    grade=EvidenceGrade(grade),
                    source_id=source_id,
                    locator=basis if grade != "S" else "",
                    basis=basis,
                    rows=count,
                    missing=missing,
                )
            )
    for kind in (GraphKind.TRADE, GraphKind.MIGRATION, GraphKind.MILITARY):
        distance_basis = (
            CHGIS_COUNTY_POINTS_LOCATOR if kind is GraphKind.MIGRATION else COURIER_ROUTES[1]
        )
        for name, grade, source_id, basis in (
            ("distance_km", "B", CHGIS_SOURCE_ID, distance_basis),
            ("cost", "S", None, "a declared per-graph conversion of distance"),
            ("capacity", "S", None, "a declared per-graph capacity"),
            ("risk", "S", None, "a declared per-graph risk"),
        ):
            rows.append(
                FieldProvenance(
                    table=f"{kind.value}-edges.parquet",
                    field=name,
                    grade=EvidenceGrade(grade),
                    source_id=source_id,
                    locator=basis if grade != "S" else "",
                    basis=basis,
                    rows=0,
                    missing=0,
                )
            )
    return tuple(rows)


#: Locators reused by the field table, kept next to the fields they describe.
CHGIS_COUNTY_POINTS_LOCATOR: Final[str] = (
    "CHGIS V6 time-series county points (v6_time_cnty_pts_utf_wgs84.zip), "
    "https://doi.org/10.7910/DVN/Q9VOF5"
)
REACHES_LOCATOR: Final[str] = (
    "REACHES Chinese Historical Climate Database, NOAA/WDS study 23410, "
    "https://www.ncei.noaa.gov/access/paleo-search/study/23410"
)


def _edge_sets(nodes: pl.DataFrame) -> dict[str, tuple[pl.DataFrame, pl.DataFrame]]:
    """Candidate and accepted edges for the three graphs, from one node table."""
    candidates = edges_module.candidate_edges(nodes)
    return {
        graph.value: (candidates, edges_module.accepted_edges(nodes, graph))
        for graph in (GraphKind.TRADE, GraphKind.MIGRATION, GraphKind.MILITARY)
    }


def complete_connectivity(
    nodes: pl.DataFrame, edges: dict[str, tuple[pl.DataFrame, pl.DataFrame]]
) -> tuple[dict[str, tuple[pl.DataFrame, pl.DataFrame]], dict[str, int]]:
    """Add the fewest links that make each graph connected, and say how many were needed.

    The dataset refuses a graph that is not connected over its own node set, and it is right to: a
    node no link reaches cannot exercise that graph's mechanism. The documented rules alone do not
    connect a twelve-seat sample across two provinces, so the gaps are closed with *labelled*
    connectors - the minimum spanning tree over the seats by ground distance, restricted to the
    pairs the graph does not already accept. A connector is graded ``S``, carries ``connector`` on
    the row, and says in its note that it exists to make the graph connected rather than because a
    source documents it; the coverage report counts them per graph, so the share of a graph that is
    documented is visible.
    """
    import networkx as nx

    located = nodes.filter(pl.col("latitude").is_not_null()).to_dicts()
    completed: dict[str, tuple[pl.DataFrame, pl.DataFrame]] = {}
    counts: dict[str, int] = {}
    for name, (candidates, accepted) in edges.items():
        # Each graph may only touch nodes whose declared roles admit it, so a connector cannot drag
        # a boundary node into a graph its role excludes.
        required = REQUIRED_ROLE[name]
        allowed = {
            str(row["node_id"])
            for row in located
            if row["kind"] == "county" or required in str(row["external_roles"] or "").split(",")
        }
        graph: nx.Graph[str] = nx.Graph()
        graph.add_nodes_from(sorted(allowed))
        for row in accepted.iter_rows(named=True):
            graph.add_edge(str(row["source"]), str(row["target"]))
        coordinates = {
            str(row["node_id"]): (float(row["latitude"]), float(row["longitude"]))
            for row in located
            if str(row["node_id"]) in allowed
        }
        rows: list[dict[str, Any]] = []
        components = sorted(nx.connected_components(graph), key=len, reverse=True)
        while len(components) > 1:
            best: tuple[float, str, str] | None = None
            for first in components[0]:
                for other in components[1:]:
                    for second in other:
                        distance = selection_module.haversine_km(
                            coordinates[first][0],
                            coordinates[first][1],
                            coordinates[second][0],
                            coordinates[second][1],
                        )
                        if best is None or distance < best[0]:
                            best = (distance, first, second)
            if best is None:
                break
            distance, first, second = best
            connector = {
                "source": min(first, second),
                "target": max(first, second),
                "distance_km": distance,
                "cost": _connector_cost(name, distance),
                "capacity": _connector_capacity(name),
                "risk": _connector_risk(name),
                "evidence_grade": "S",
                "source_id": "",
                "locator": "",
                "note": (
                    "Connector: added to make the " + name + " graph connected over its node set. "
                    "It is a modelling requirement, not a documented link, and it is counted as a "
                    "connector in the coverage report."
                ),
            }
            rows.append(connector)
            graph.add_edge(first, second, connector=True)
            components = sorted(nx.connected_components(graph), key=len, reverse=True)
        counts[name] = len(rows)
        if rows:
            additions = pl.DataFrame(
                rows,
                schema={
                    "source": pl.Utf8,
                    "target": pl.Utf8,
                    "distance_km": pl.Float64,
                    "cost": pl.Float64,
                    "capacity": pl.Float64,
                    "risk": pl.Float64,
                    "evidence_grade": pl.Utf8,
                    "source_id": pl.Utf8,
                    "locator": pl.Utf8,
                    "note": pl.Utf8,
                },
            ).select(accepted.columns)
            accepted = pl.concat([accepted, additions], how="vertical_relaxed").sort(
                ["source", "target"]
            )
        completed[name] = (candidates, accepted)
    return completed, counts


def _connector_cost(name: str, distance_km: float) -> float:
    """The graph's own declared cost rule, applied to a connector."""
    per_day = {
        "trade": edges_module.TRADE_KM_PER_DAY,
        "military": edges_module.MILITARY_KM_PER_DAY,
    }
    if name == "migration":
        return edges_module.MIGRATION_COST_PER_HOUSEHOLD
    return distance_km / per_day.get(name, 25.0)


def _connector_capacity(name: str) -> float:
    return {
        "trade": edges_module.TRADE_CAPACITY,
        "military": edges_module.MILITARY_CAPACITY,
        "migration": edges_module.MIGRATION_CAPACITY,
    }[name]


def _connector_risk(name: str) -> float:
    return {
        "trade": edges_module.TRADE_RISK,
        "military": edges_module.MILITARY_RISK_MINOR,
        "migration": edges_module.MIGRATION_RISK,
    }[name]


def build_core(
    root: str | Path,
    *,
    parameters: HistoricalCoreParameters | None = None,
    allocation_mode: AllocationMode = AllocationMode.SEASONAL,
) -> HistoricalCore:
    """Build the core in memory: nodes, edges, annual climate, coverage and manifest."""
    repository = Path(root)
    parameters = parameters or core_default_historical_core_parameters()
    seats = load_county_points(repository)
    events = load_reaches_events(repository)
    load_category_names(repository)

    report = SelectionReport()
    eligible = candidate_filters(seats, events, report)
    stations = edges_module.load_stations(repository)
    snapped = selection_module.station_distances(eligible, stations)
    attached = set(
        snapped.filter(pl.col("station_km") <= selection_module.STATION_SNAP_RADIUS_KM)[
            "sys_id"
        ].to_list()
    )
    selected = select_nodes(eligible, events, report, attached=attached)
    exits = external_exits(seats, selected, report)
    nodes = node_table(selected, exits)
    stored_nodes = nodes.select(
        [column for column in (*NODE_COLUMNS, *STORED_NODE_EXTRA) if column in nodes.columns]
    )
    edges = _edge_sets(nodes)
    edges, connectors = complete_connectivity(nodes, edges)
    if connectors:
        report.notes = (
            *report.notes,
            "connector links added to make the graphs connected: "
            + ", ".join(f"{name} {count}" for name, count in sorted(connectors.items())),
        )
    annual = build_annual_index(nodes, events, parameters)

    rows = field_provenance(annual.height)
    edge_counts = {
        name: {"candidates": pair[0].height, "accepted": pair[1].height}
        for name, pair in edges.items()
    }
    climate_probe = _climate_probe(annual, parameters, allocation_mode)
    manifest = CoreManifest(
        built_from=_snapshot_hashes(repository),
        selection=SelectionRule(),
        selection_report=report.record(),
        stations=len(stations),
        parameters_version=parameters.version,
        climate=climate_probe,
        edges=edge_counts,
        tables={},
        rights=(
            f"Derived selection, not a redistribution. {CHGIS_CITATION} {CHGIS_CHANGES} Climate "
            "values are counts aggregated out of the REACHES record; no individual record is "
            "reproduced, and the raw files stay under data/raw/private, which git ignores."
        ),
        coverage_report=REPORT_FILE,
    )
    return HistoricalCore(
        nodes=stored_nodes,
        annual=annual,
        edges=edges,
        manifest=manifest,
        field_provenance=rows,
    )


def _climate_probe(
    annual: pl.DataFrame, parameters: HistoricalCoreParameters, mode: AllocationMode
) -> dict[str, Any]:
    """What the manifest records about the forcing: coverage, imputation and the weights."""
    from late_ming_lab.historical.forcing import AllocatedObservedClimate

    climate = AllocatedObservedClimate(
        annual,
        parameters,
        coverage_policy=MissingCoveragePolicy.ZERO,
        allocation_mode=mode,
        series_id=CORE_DATASET_ID,
        provenance=annual_provenance(),
    )
    summary = climate.summary()
    summary["weights"] = {str(month): round(value, 6) for month, value in climate.weights.items()}
    summary["uncovered"] = [f"{node} {year}" for node, year in climate.imputed_node_years]
    return summary


def write_core(root: str | Path, core: HistoricalCore) -> tuple[Path, ...]:
    """Write the derived tables, the manifest and the coverage document."""
    repository = Path(root)
    directory = repository / CORE_ROOT
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = [write_table(directory / NODES_TABLE, core.nodes)]
    written.append(write_table(directory / CLIMATE_TABLE, core.annual))
    for kind, (candidates, accepted) in core.edges.items():
        written.append(write_table(directory / f"{kind}-candidates.parquet", candidates))
        written.append(write_table(directory / f"{kind}-edges.parquet", accepted))
    # The coverage grid is about the counties' climate record: an external node has no agriculture
    # and no observed series, and an unrecorded node-year must appear as missing rather than as a
    # covered zero, which is why only the recorded rows are passed in.
    report = coverage_module.render_coverage_report(
        nodes=core.nodes.filter(pl.col("kind") == "county"),
        annual=core.annual.filter(pl.col("records")),
        edges={kind: pair for kind, pair in core.edges.items()},
        fields=core.field_provenance,
    ) + core_sections(core)
    report_path = repository / REPORT_FILE
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    written.append(report_path)
    tables = {path.name: _digest(path) for path in written if path.suffix == ".parquet"}
    manifest = core.manifest.model_copy(update={"tables": tables})
    manifest_path = directory / MANIFEST_FILE
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    written.append(manifest_path)
    return tuple(written)


def core_sections(core: HistoricalCore) -> str:
    """The parts of the coverage document the generic renderer cannot know: the rule, connectors.

    The coverage module reports coverage, edges and fields from the tables it is given. Three things
    belong only to this core and are appended here, computed from the manifest: the selection rule
    and what it excluded, the connector links that make each graph connected, and the rights the
    stored tables are published under.
    """
    selection = core.manifest.selection_report
    lines: list[str] = [
        "",
        "## Selection rule, and what it excluded",
        "",
        f"- eligible seats: {selection['eligible']} "
        f"({', '.join(f'{k} {v}' for k, v in sorted(selection['eligible_by_province'].items()))})",
        f"- selected: {selection['selected']} "
        f"({', '.join(f'{k} {v}' for k, v in sorted(selection['selected_by_province'].items()))})",
        f"- quota by province: "
        f"{', '.join(f'{k} {v}' for k, v in sorted(selection['quota_by_province'].items()))}",
        f"- seed seats: {', '.join(selection['seed_sys_ids']) or 'none'}",
        f"- boundary exits built: {', '.join(selection['exits']) or 'none'}",
        "",
        "| filter | seats removed |",
        "| --- | --- |",
    ]
    for name, count in sorted(selection["excluded"].items()):
        lines.append(f"| {name.replace('_', ' ')} | {count} |")
    lines += [
        "",
        f"- eligible seats not selected: {len(selection['omitted_eligible'])} (spread and quota, "
        "not quality)",
        f"- stopped before target: {selection['stopped_before_target'] or 'no'}",
        "",
    ]
    for note in selection["notes"]:
        lines.append(f"- note: {note}")
    lines += [
        "",
        "## Connector links",
        "",
        "A connector is a link added to make a graph connected over its node set. It is "
        "graded `S`, carries the word `Connector` in its note, and is not evidence of "
        "anything but the need for a connected graph; the documented links beside it are "
        "graded `B` or `C`.",
        "| graph | accepted | documented | connectors |",
        "| --- | --- | --- | --- |",
    ]
    for name, (candidates, accepted) in sorted(core.edges.items()):
        connectors = accepted.filter(pl.col("note").str.starts_with("Connector"))
        pairs = {(row["source"], row["target"]) for row in candidates.iter_rows(named=True)}
        beyond = [
            row
            for row in connectors.iter_rows(named=True)
            if (row["source"], row["target"]) not in pairs
        ]
        lines.append(
            f"| {name} | {accepted.height} | {accepted.height - connectors.height} | "
            f"{connectors.height} ({len(beyond)} beyond the candidate radius) |"
        )
    lines += [
        "",
        "## Rights",
        "",
        core.manifest.rights,
        "",
        "The core's source snapshots and their hashes are recorded in the build manifest beside",
        "this document; the raw files are not in the repository.",
        "",
    ]
    return "\n".join(lines)


def load_core(root: str | Path) -> HistoricalCore:
    """Read the written core back, so a run reads tables rather than rebuilding them."""
    repository = Path(root)
    directory = repository / CORE_ROOT
    manifest_path = directory / MANIFEST_FILE
    if not manifest_path.is_file():
        raise CoreBuildError(
            f"{manifest_path} is missing; build the core first with "
            "python -m late_ming_lab.historical.build"
        )
    manifest = CoreManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    for name, digest in manifest.tables.items():
        path = directory / name
        if not path.is_file():
            raise CoreBuildError(f"{path} is named by the manifest but missing")
        if _digest(path) != digest:
            raise CoreBuildError(
                f"{path} does not hash to the manifest: {_digest(path)[:12]} against {digest[:12]}"
            )
    nodes = pl.read_parquet(directory / NODES_TABLE)
    annual = pl.read_parquet(directory / CLIMATE_TABLE)
    edges = {
        kind: (
            pl.read_parquet(directory / f"{kind}-candidates.parquet"),
            pl.read_parquet(directory / f"{kind}-edges.parquet"),
        )
        for kind in ("trade", "migration", "military")
    }
    return HistoricalCore(
        nodes=nodes,
        annual=annual,
        edges=edges,
        manifest=manifest,
        field_provenance=field_provenance(annual.height),
    )


def core_dataset(core: HistoricalCore) -> SpatialDataset:
    """The core as a `spatial-dataset-v1` dataset, through the adapter that validates every row."""
    frames = {kind: core.edges[kind][1] for kind in ("trade", "migration", "military")}
    return dataset_from_frames(
        dataset_id=CORE_DATASET_ID,
        provenance=chgis_derived(
            note=(
                "the dataset as a whole: CHGIS-derived seats and distances, with declared "
                "selection, zone, cost, capacity and risk rules. Every row carries its own grade; "
                "this value describes the composition rather than any single field."
            )
        ),
        nodes=core.nodes.select(list(NODE_COLUMNS)),
        trade=frames["trade"].select(list(EDGE_COLUMNS)),
        migration=frames["migration"].select(list(EDGE_COLUMNS)),
        military=frames["military"].select(list(EDGE_COLUMNS)),
    )


def main(argv: list[str] | None = None) -> int:
    """Build and write the core; return a process exit code."""
    parser = argparse.ArgumentParser(description="Build historical-core-v1")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--json", action="store_true", help="print the manifest as JSON")
    arguments = parser.parse_args(argv)
    core = build_core(arguments.root)
    written = write_core(arguments.root, core)
    if arguments.json:
        print(json.dumps(core.manifest.model_dump(mode="json"), indent=2, sort_keys=True))
    else:
        for path in written:
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
