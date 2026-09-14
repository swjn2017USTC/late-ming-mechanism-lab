"""Candidate and accepted edges for the three movement graphs of the historical core.

V2-P02 keeps two layers for every graph. A *candidate* edge comes from a declared screening rule and
is never evidence that two places were connected; an *accepted* edge comes from a rule checked
against a layer and carries that layer's provenance. Both are kept, so a coverage report can say why
an accepted link exists and why a candidate never became one.

```text
candidates         proximity between the seats of the node table, grade S
military accepted  seats whose nearest stations are within two legs of one route chain, grade B
trade accepted     the military links carried by a major chain (MAJ_MINOR = 1), grade S
migration accepted same-province seats within 60 km, plus one link per external node, grade S
```

Three conventions hold everywhere below.

- **A link is symmetric.** Every row writes its two endpoints in ascending node-id order: P02 has
  one cost per pair and no direction, and a directional asymmetry is a declared open item, not an
  approximation made here.
- **A distance belongs to the places, a cost to what moves.** ``distance_km`` is always the
  great-circle distance between the two seats of the node table, so the same pair states the same
  distance in all three graphs and only ``cost``, ``capacity`` and ``risk`` differ by graph.
- **An assumption says so.** Every candidate row is grade ``S`` and names the screening rule; every
  accepted row names the layer it was checked against and every number that was declared rather than
  read, so nothing is inherited from another graph's edge.

The courier station graph is built from the 2016 routes and stations layers, with one defect handled
rather than inherited: **the station layer's ``YZ_LAT`` and ``YZ_LONG`` attributes are swapped**
(``YZ_LAT`` holds 98-124, ``YZ_LONG`` holds 20-42), while the ``geometry`` column is correct in
EPSG:4326. Only the geometry is read, and every value that depends on a station's position repeats
the defect in its note.

Adjacency rule implemented for the station graph, stated once here and used by the military rule: a
route line connects two stations when the line passes within :data:`STATION_SNAP_RADIUS_KM` of both
and no other station that the same line passes that close to lies between them along the line. The
layer's routes were adjusted to meet the station points, so this normally makes one link per route
feature; the radius is what absorbs the cases where they do not meet exactly. The station id is the
layer's ``YZ_ID``; ``MAJ_MINOR`` (1 = major, 2 = minor) is kept as the edge attribute of the link.

The military and trade rules then accept a seat pair when the shortest chain of those station links
between the two snapped stations is one or two legs long (:data:`MAX_STATION_HOPS`), not only when
the stations touch: the selected seats are a network sample spread over two provinces, and a
one-leg rule would leave the military graph with a single edge. The hop count is written into the
row's note, and the chain's class is its strongest (lowest) ``MAJ_MINOR``.

A seat no station reaches belongs to no movement graph, so the attachment is public rather than
buried: :func:`snapped_stations` gives the nearest station of every located node and
:func:`unattached_nodes` names the ones outside the tolerance, which a node selection can require
before it selects.

Loading is the only part that touches the raw files, which are untracked: builders take frames, and
a caller that already holds a station graph (a test, or a second graph built from the same layer)
passes it in rather than reading the zips again.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Final

import geopandas as gpd
import networkx as nx
import numpy as np
import numpy.typing as npt
import polars as pl

from late_ming_lab.evidence.grades import DataProvenance, EvidenceGrade
from late_ming_lab.evidence.provenance import find_repo_root
from late_ming_lab.evidence.snapshots import RAW_ROOT
from late_ming_lab.historical.provenance import COURIER_ROUTES, courier_derived, declared
from late_ming_lab.networks.adapter import EDGE_COLUMNS
from late_ming_lab.networks.edges import GraphKind

#: The two courier layers, relative to the repository root. Raw snapshots are never tracked.
COURIER_ROUTES_ZIP: Final[str] = f"{RAW_ROOT}/chgis-v6/Ming_Routes_2016.zip"
COURIER_STATIONS_ZIP: Final[str] = f"{RAW_ROOT}/chgis-v6/Ming_Stations_2016.zip"

#: The station layer's coordinate defect, repeated on every value derived from a station position.
STATION_COORDINATE_DEFECT: Final[str] = (
    "Station coordinates come from the layer's geometry column in EPSG:4326; its YZ_LAT and "
    "YZ_LONG attributes are swapped and are not used."
)

#: How far apart two seats may be and still be *listed* as a candidate. Declared screening value:
#: the courier layer's own route segments run 27 km at the median and 53 km at the 90th percentile,
#: so 150 km reaches past any plausible neighbour without asserting one. Candidates are a pool for
#: the per-graph rules, never links, and the value is a V2-P03 sensitivity item.
CANDIDATE_RADIUS_KM: Final[float] = 150.0

#: How far a seat may lie from a station and still be treated as that station's seat. Declared
#: tolerance: across the courier layer's own station-to-CHGIS-point matches that resolve in the
#: county layer, 96% are within 40 km (median 0 km, p90 2 km), so 40 km admits a real match while a
#: seat is not usually offered a station several counties away.
STATION_SNAP_RADIUS_KM: Final[float] = 40.0

#: How far a household is assumed to move in one P02 migration link. Declared: at roughly a day's
#: walk with a load it keeps the migration graph local, and it is the first edge threshold V2-P04
#: should vary, because the same-province rule is already the weakest of the three topologies.
MIGRATION_MAX_KM: Final[float] = 60.0

#: How many legs of the documented route chain may stand between two seats that are still linked.
#: Declared: the selected seats are a network sample spread over two provinces, not a chain of
#: neighbours, so most of their snapped stations sit two station hops apart and a one-leg rule left
#: the military graph with a single edge. One or two legs is the rule implemented below; raising
#: this constant means revisiting the chain enumeration in :func:`_route_chain`.
MAX_STATION_HOPS: Final[int] = 2

#: Declared placeholder magnitudes. None of these is read from a layer; each is named in the note of
#: every row it prices, and each is a review item rather than a measurement.
CANDIDATE_KM_PER_DAY: Final[float] = 25.0
CANDIDATE_CAPACITY: Final[float] = 100.0
CANDIDATE_RISK: Final[float] = 0.1
MILITARY_KM_PER_DAY: Final[float] = 30.0
MILITARY_CAPACITY: Final[float] = 300.0
MILITARY_RISK_MAJOR: Final[float] = 0.05
MILITARY_RISK_MINOR: Final[float] = 0.15
TRADE_KM_PER_DAY: Final[float] = 20.0
TRADE_CAPACITY: Final[float] = 500.0
TRADE_RISK: Final[float] = 0.10
MIGRATION_COST_PER_HOUSEHOLD: Final[float] = 1.0
MIGRATION_CAPACITY: Final[float] = 50.0
MIGRATION_RISK: Final[float] = 0.20

#: The node-table columns an edge builder reads. A table missing one of them is refused by name.
NODE_COLUMNS_READ: Final[tuple[str, ...]] = (
    "node_id",
    "kind",
    "province",
    "latitude",
    "longitude",
)

#: Mean great-circle degree and radius: one distance definition for the whole module.
EARTH_RADIUS_KM: Final[float] = 6371.0088
KM_PER_DEGREE: Final[float] = EARTH_RADIUS_KM * math.pi / 180.0

#: The adapter's edge columns and their types: the one place this module decides a frame's schema.
_EDGE_DTYPES: Final[dict[str, pl.DataType]] = {
    "source": pl.String(),
    "target": pl.String(),
    "distance_km": pl.Float64(),
    "cost": pl.Float64(),
    "capacity": pl.Float64(),
    "risk": pl.Float64(),
    "evidence_grade": pl.String(),
    "source_id": pl.String(),
    "locator": pl.String(),
    "note": pl.String(),
}


class EdgeBuildError(ValueError):
    """Raised when a table cannot produce candidate or accepted edges."""


@dataclass(frozen=True, slots=True)
class RouteLine:
    """One route feature of the courier layer: its line and its published rank."""

    major_minor: int
    #: ``(longitude, latitude)`` vertices in EPSG:4326, in the layer's order.
    coordinates: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class _LineFrame:
    """A route line in a local kilometre frame, for distance and ordering along the line."""

    xy: npt.NDArray[np.float64]
    cumulative: npt.NDArray[np.float64]
    origin: tuple[float, float]


@dataclass(frozen=True, slots=True)
class _CourierLink:
    """A seat pair the courier layer supports, before pricing."""

    source: str
    target: str
    distance_km: float
    hops: int
    major_minor: int


@dataclass(frozen=True, slots=True)
class _Stations:
    """The station graph's nodes as arrays, in station-id order."""

    ids: tuple[int, ...]
    names: tuple[str, ...]
    lons: npt.NDArray[np.float64]
    lats: npt.NDArray[np.float64]


#: The columns of the attachment table: which station a seat's movement would start from.
_STATION_DTYPES: Final[dict[str, pl.DataType]] = {
    "node_id": pl.String(),
    "station_id": pl.Int64(),
    "station_name": pl.String(),
    "distance_km": pl.Float64(),
}


def load_stations(root: str | Path) -> pl.DataFrame:
    """The courier layer's stations: id, name and the coordinates of the geometry column.

    The layer carries ``YZ_LAT`` and ``YZ_LONG`` as attributes, and they are swapped; the geometry
    column is the only coordinate source read here (see :data:`STATION_COORDINATE_DEFECT`).
    """
    frame = gpd.read_file(f"zip://{_zip_path(root, COURIER_STATIONS_ZIP)}")
    names = [text if isinstance(text, str) else "" for text in frame["YZNM_PY"].tolist()]
    return pl.DataFrame(
        {
            "station_id": np.asarray(frame["YZ_ID"], dtype=np.int64),
            "name_py": names,
            "longitude": np.asarray(frame.geometry.x, dtype=float),
            "latitude": np.asarray(frame.geometry.y, dtype=float),
        }
    ).sort("station_id")


def load_routes(root: str | Path) -> tuple[RouteLine, ...]:
    """The courier layer's route lines, in layer order.

    A feature whose geometry is missing or is not a simple line is dropped: it states no link. The
    2016 layer has exactly one such feature (``MAJ_MINOR`` 0, no geometry).
    """
    frame = gpd.read_file(f"zip://{_zip_path(root, COURIER_ROUTES_ZIP)}")
    lines: list[RouteLine] = []
    for major_minor, geometry in zip(
        frame["MAJ_MINOR"].tolist(), frame.geometry.tolist(), strict=True
    ):
        if geometry is None or geometry.geom_type != "LineString":
            continue
        lines.append(
            RouteLine(
                major_minor=int(major_minor),
                coordinates=tuple((float(x), float(y)) for x, y in geometry.coords),
            )
        )
    return tuple(lines)


def courier_station_graph(root: str | Path | None = None) -> nx.Graph[int]:
    """The courier station graph, read from the raw layer under ``root`` (or the repository)."""
    directory = _resolve_root(root)
    return station_graph(load_stations(directory), load_routes(directory))


def station_graph(
    stations: pl.DataFrame,
    routes: tuple[RouteLine, ...],
    *,
    snap_radius_km: float = STATION_SNAP_RADIUS_KM,
) -> nx.Graph[int]:
    """Build the station graph from the layer's two tables.

    Nodes are ``YZ_ID`` values carrying ``name_py``, ``longitude`` and ``latitude``; an edge means
    one route line passes within ``snap_radius_km`` of both stations with no other station it passes
    that close to in between, and carries the stronger (lower) ``MAJ_MINOR`` of the lines that say
    so.
    """
    _require_columns(stations, ("station_id", "name_py", "longitude", "latitude"))
    ids = [int(value) for value in stations["station_id"].to_list()]
    names = [str(value) for value in stations["name_py"].to_list()]
    lons = stations["longitude"].to_numpy().astype(float)
    lats = stations["latitude"].to_numpy().astype(float)

    graph: nx.Graph[int] = nx.Graph()
    graph.graph["coordinate_defect"] = STATION_COORDINATE_DEFECT
    for index, station_id in enumerate(ids):
        graph.add_node(
            station_id,
            name_py=names[index],
            longitude=float(lons[index]),
            latitude=float(lats[index]),
        )

    for route in routes:
        coordinates = np.asarray(route.coordinates, dtype=float)
        if coordinates.shape[0] < 2:
            continue
        frame = _line_frame(coordinates)
        hits = [
            (_nearest_on_line(frame, lon=float(lons[index]), lat=float(lats[index])), ids[index])
            for index in _near_line(coordinates, lons, lats, radius_km=snap_radius_km)
        ]
        on_line = sorted(
            (offset, station_id)
            for (distance_km, offset), station_id in hits
            if distance_km <= snap_radius_km
        )
        for (_, first), (_, second) in pairwise(on_line):
            if first == second:
                continue
            existing = graph.get_edge_data(first, second)
            rank = (
                route.major_minor
                if existing is None
                else min(existing["major_minor"], route.major_minor)
            )
            graph.add_edge(first, second, major_minor=int(rank))
    return graph


def snapped_stations(
    nodes: pl.DataFrame,
    *,
    station_graph: nx.Graph[int] | None = None,
) -> pl.DataFrame:
    """The station each located node would move from, and how far away it is.

    One row per located node, whatever the distance: a node whose nearest station is far away is the
    interesting case, so nothing is filtered out here. A station column is null only when the graph
    places no station at all, which is also what makes the node unattached.
    """
    graph = courier_station_graph() if station_graph is None else station_graph
    stations = _stations(graph)
    names = dict(zip(stations.ids, stations.names, strict=True))
    rows: list[dict[str, object]] = []
    for row in _located(nodes).iter_rows(named=True):
        node_id = str(row["node_id"])
        nearest = _nearest_station(
            stations, lon=float(row["longitude"]), lat=float(row["latitude"])
        )
        if nearest is None:
            rows.append(
                {"node_id": node_id, "station_id": None, "station_name": None, "distance_km": None}
            )
            continue
        station_id, distance_km = nearest
        rows.append(
            {
                "node_id": node_id,
                "station_id": station_id,
                "station_name": names[station_id],
                "distance_km": distance_km,
            }
        )
    if not rows:
        return pl.DataFrame(schema=_STATION_DTYPES)
    return pl.DataFrame(rows, schema=_STATION_DTYPES)


def unattached_nodes(
    nodes: pl.DataFrame,
    *,
    station_graph: nx.Graph[int] | None = None,
    radius_km: float = STATION_SNAP_RADIUS_KM,
) -> tuple[str, ...]:
    """The nodes no station reaches within the tolerance, so no movement graph can reach them.

    A node with no coordinates at all is not listed: it never reaches this table, because a seat is
    located before it is selected.
    """
    attached = snapped_stations(nodes, station_graph=station_graph)
    far = attached.filter(pl.col("distance_km").is_null() | (pl.col("distance_km") > radius_km))
    return tuple(str(value) for value in far["node_id"].to_list())


def candidate_edges(nodes: pl.DataFrame, *, radius_km: float = CANDIDATE_RADIUS_KM) -> pl.DataFrame:
    """Every pair of located nodes within ``radius_km``, as one graph-independent candidate pool.

    Proximity is a screening rule: a pair is listed because the two seats are close, which is why
    the rows are graded ``S`` and say so. Nothing here consults a road, a river or a route, and an
    accepted edge is not filtered out of this pool by construction — it is produced by its graph's
    own rule, so the two can be compared.
    """
    located = _located(nodes)
    ids = [str(value) for value in located["node_id"].to_list()]
    lons = located["longitude"].to_numpy().astype(float)
    lats = located["latitude"].to_numpy().astype(float)
    provenance = declared(note=_candidate_note(radius_km))

    rows: list[dict[str, object]] = []
    for left in range(len(ids) - 1):
        distances = _haversine_km(lons[left], lats[left], lons[left + 1 :], lats[left + 1 :])
        for offset in np.flatnonzero(distances <= radius_km):
            index = int(offset)
            distance_km = float(distances[index])
            rows.append(
                _edge_row(
                    ids[left],
                    ids[left + 1 + index],
                    distance_km=distance_km,
                    cost=distance_km / CANDIDATE_KM_PER_DAY,
                    capacity=CANDIDATE_CAPACITY,
                    risk=CANDIDATE_RISK,
                    provenance=provenance,
                )
            )
    return _edge_frame(rows).sort(["source", "target"])


def accepted_edges(
    nodes: pl.DataFrame,
    kind: GraphKind,
    *,
    station_graph: nx.Graph[int] | None = None,
) -> pl.DataFrame:
    """The edges one graph accepts, or an empty frame of edge columns when it accepts none.

    ``station_graph`` is required in practice for trade and military and is read from the raw
    courier layer when it is not given; migration ignores it, because its rule is a node-table rule.
    """
    if kind is GraphKind.MIGRATION:
        return _migration_edges(nodes)
    graph = courier_station_graph() if station_graph is None else station_graph
    links = _courier_links(nodes, graph)
    if kind is GraphKind.MILITARY:
        return _military_edges(links)
    if kind is GraphKind.TRADE:
        return _trade_edges(links)
    raise EdgeBuildError(f"{kind!r} is not one of the three movement graphs")


def edge_tables(
    nodes: pl.DataFrame,
    *,
    candidates: pl.DataFrame | None = None,
    station_graph: nx.Graph[int] | None = None,
) -> dict[str, pl.DataFrame]:
    """The six tables P02 writes per graph: candidates beside accepted edges, for audit.

    The candidate pool is graph-independent — proximity is one declared screening rule, not three —
    so the three candidate keys hold the same frame, written once per graph directory so that every
    accepted table sits next to the pool it came from.
    """
    pool = candidate_edges(nodes) if candidates is None else candidates
    graph = courier_station_graph() if station_graph is None else station_graph
    return {
        "trade_candidates": pool,
        "trade_accepted": accepted_edges(nodes, GraphKind.TRADE, station_graph=graph),
        "migration_candidates": pool,
        "migration_accepted": accepted_edges(nodes, GraphKind.MIGRATION),
        "military_candidates": pool,
        "military_accepted": accepted_edges(nodes, GraphKind.MILITARY, station_graph=graph),
    }


def _military_edges(links: tuple[_CourierLink, ...]) -> pl.DataFrame:
    """Price the courier links as march links: a major chain is safer and no faster."""
    rows = [
        _edge_row(
            link.source,
            link.target,
            distance_km=link.distance_km,
            cost=link.distance_km / MILITARY_KM_PER_DAY,
            capacity=MILITARY_CAPACITY,
            risk=MILITARY_RISK_MAJOR if link.major_minor == 1 else MILITARY_RISK_MINOR,
            provenance=courier_derived(note=_military_note(link.hops)),
        )
        for link in links
    ]
    return _edge_frame(rows).sort(["source", "target"])


def _trade_edges(links: tuple[_CourierLink, ...]) -> pl.DataFrame:
    """The major-chain subset of the courier links, priced as grain movement on a road.

    Graded ``C`` rather than ``S``: the *road* is sourced (the CHGIS courier layer) and the grain
    movement along it is an inference from that road, which is what grade C means. The declared
    magnitudes in the note are ours and are named as such.
    """
    rows = [
        _edge_row(
            link.source,
            link.target,
            distance_km=link.distance_km,
            cost=link.distance_km / TRADE_KM_PER_DAY,
            capacity=TRADE_CAPACITY,
            risk=TRADE_RISK,
            provenance=courier_derived(
                note=_trade_note(link.hops, provenance_note=True),
                locator=COURIER_ROUTES,
                grade=EvidenceGrade.C,
            ),
        )
        for link in links
        if link.major_minor == 1
    ]
    return _edge_frame(rows).sort(["source", "target"])


def _migration_edges(nodes: pl.DataFrame) -> pl.DataFrame:
    """County pairs within the declared range, plus one link from each external node.

    Range only: the rule used to require the same province, which is not what flight does - people
    left Shaanxi for Henan - and it also kept the graph from connecting across the provincial line.
    The provinces of the two endpoints are named in the note instead, so a reader can see which
    links cross the border.
    """
    located = _located(nodes)
    counties = located.filter(pl.col("kind") == "county")
    ids = [str(value) for value in counties["node_id"].to_list()]
    lons = counties["longitude"].to_numpy().astype(float)
    lats = counties["latitude"].to_numpy().astype(float)
    provenance = declared(note=_migration_note())

    def row(first: str, second: str, distance_km: float) -> dict[str, object]:
        source, target = sorted((first, second))
        return _edge_row(
            source,
            target,
            distance_km=distance_km,
            cost=MIGRATION_COST_PER_HOUSEHOLD,
            capacity=MIGRATION_CAPACITY,
            risk=MIGRATION_RISK,
            provenance=provenance,
        )

    rows: list[dict[str, object]] = []
    for left in range(len(ids) - 1):
        distances = _haversine_km(lons[left], lats[left], lons[left + 1 :], lats[left + 1 :])
        for offset in np.flatnonzero(distances <= MIGRATION_MAX_KM):
            index = int(offset)
            right = left + 1 + index
            rows.append(row(ids[left], ids[right], float(distances[index])))
    if ids:
        for external in located.filter(pl.col("kind") == "external").iter_rows(named=True):
            distances = _haversine_km(
                float(external["longitude"]), float(external["latitude"]), lons, lats
            )
            nearest = int(np.argmin(distances))
            rows.append(row(str(external["node_id"]), ids[nearest], float(distances[nearest])))
    return _edge_frame(rows).sort(["source", "target"])


def _courier_links(
    nodes: pl.DataFrame,
    station_graph: nx.Graph[int],
    *,
    snap_radius_km: float = STATION_SNAP_RADIUS_KM,
) -> tuple[_CourierLink, ...]:
    """Seat pairs the courier layer supports, and the chain of stations that supports them.

    A pair is supported when the shortest chain between the two stations is one or two legs of the
    documented route network, and the chain's class is its strongest (lowest) ``MAJ_MINOR``.
    """
    buckets = _station_buckets(nodes, station_graph, snap_radius_km=snap_radius_km)
    points = {
        str(row["node_id"]): (float(row["longitude"]), float(row["latitude"]))
        for row in _located(nodes).iter_rows(named=True)
    }
    carriers = sorted(buckets)
    links: list[_CourierLink] = []
    for index, first_station in enumerate(carriers):
        reach = nx.single_source_shortest_path_length(
            station_graph, first_station, cutoff=MAX_STATION_HOPS
        )
        for second_station in carriers[index + 1 :]:
            hops = reach.get(second_station)
            if hops is None or hops < 1:
                continue
            rank = _chain_class(station_graph, first_station, second_station, hops)
            for first in buckets[first_station]:
                for second in buckets[second_station]:
                    source, target = sorted((first, second))
                    links.append(
                        _CourierLink(
                            source=source,
                            target=target,
                            distance_km=float(_haversine_km(*points[first], *points[second])),
                            hops=hops,
                            major_minor=rank,
                        )
                    )
    links.sort(key=lambda link: (link.source, link.target))
    return tuple(links)


def _chain_class(
    station_graph: nx.Graph[int],
    first: int,
    second: int,
    hops: int,
) -> int:
    """The strongest (lowest) ``MAJ_MINOR`` on the shortest chain between two stations."""
    if hops == 1:
        return int(station_graph[first][second]["major_minor"])
    between = set(station_graph.neighbors(first)) & set(station_graph.neighbors(second))
    return min(
        min(
            int(station_graph[first][station]["major_minor"]),
            int(station_graph[station][second]["major_minor"]),
        )
        for station in between
    )


def _station_buckets(
    nodes: pl.DataFrame,
    station_graph: nx.Graph[int],
    *,
    snap_radius_km: float,
) -> dict[int, tuple[str, ...]]:
    """Which seats each station carries: a seat snaps to its nearest station within the radius."""
    stations = _stations(station_graph)
    buckets: dict[int, list[str]] = {}
    for row in _located(nodes).iter_rows(named=True):
        nearest = _nearest_station(
            stations, lon=float(row["longitude"]), lat=float(row["latitude"])
        )
        if nearest is None:
            continue
        station_id, distance_km = nearest
        if distance_km <= snap_radius_km:
            buckets.setdefault(station_id, []).append(str(row["node_id"]))
    return {station: tuple(sorted(seats)) for station, seats in buckets.items()}


def _nearest_station(stations: _Stations, *, lon: float, lat: float) -> tuple[int, float] | None:
    """The station nearest a point and its distance, or ``None`` when there is no station at all."""
    if not stations.ids:
        return None
    distances = _haversine_km(lon, lat, stations.lons, stations.lats)
    nearest = int(np.argmin(distances))
    return stations.ids[nearest], float(distances[nearest])


def _stations(station_graph: nx.Graph[int]) -> _Stations:
    """The station graph's nodes as arrays in ascending id order, so a tie resolves the same way."""
    ids = tuple(sorted(int(node) for node in station_graph.nodes))
    for station_id in ids:
        if "longitude" not in station_graph.nodes[station_id]:
            raise EdgeBuildError(
                f"station {station_id} carries no longitude and latitude: a seat cannot be "
                "snapped to a station the graph does not place"
            )
    names = tuple(str(station_graph.nodes[node].get("name_py", "")) for node in ids)
    lons = np.array([station_graph.nodes[node]["longitude"] for node in ids], dtype=float)
    lats = np.array([station_graph.nodes[node]["latitude"] for node in ids], dtype=float)
    return _Stations(ids=ids, names=names, lons=lons, lats=lats)


def _located(nodes: pl.DataFrame) -> pl.DataFrame:
    """The node rows that carry coordinates, in node-id order: a link needs a point at both ends."""
    _require_columns(nodes, NODE_COLUMNS_READ)
    return (
        nodes.select(list(NODE_COLUMNS_READ))
        .filter(pl.col("latitude").is_not_null() & pl.col("longitude").is_not_null())
        .with_columns(pl.col("latitude").cast(pl.Float64), pl.col("longitude").cast(pl.Float64))
        .sort("node_id")
    )


def _near_line(
    coordinates: npt.NDArray[np.float64],
    lons: npt.NDArray[np.float64],
    lats: npt.NDArray[np.float64],
    *,
    radius_km: float,
) -> npt.NDArray[np.intp]:
    """Indices of the stations a line might reach: a bounding box, before the exact distances."""
    min_lon, min_lat = float(coordinates[:, 0].min()), float(coordinates[:, 1].min())
    max_lon, max_lat = float(coordinates[:, 0].max()), float(coordinates[:, 1].max())
    pad_lat = radius_km / KM_PER_DEGREE
    widest = max(abs(min_lat), abs(max_lat))
    pad_lon = radius_km / (KM_PER_DEGREE * max(math.cos(math.radians(widest)), 1e-6))
    return np.flatnonzero(
        (lons >= min_lon - pad_lon)
        & (lons <= max_lon + pad_lon)
        & (lats >= min_lat - pad_lat)
        & (lats <= max_lat + pad_lat)
    )


def _line_frame(coordinates: npt.NDArray[np.float64]) -> _LineFrame:
    """A line in a local kilometre frame anchored at its first vertex, with its own arc lengths.

    A degree of longitude shrinks with latitude, so the frame scales it at the line's own latitude.
    At the snap radius the error of that flat projection is about 1%, far inside the tolerance the
    rule declares.
    """
    origin = (float(coordinates[0, 0]), float(coordinates[0, 1]))
    width = KM_PER_DEGREE * math.cos(math.radians(origin[1]))
    xy = np.empty((coordinates.shape[0], 2), dtype=float)
    xy[:, 0] = (coordinates[:, 0] - origin[0]) * width
    xy[:, 1] = (coordinates[:, 1] - origin[1]) * KM_PER_DEGREE
    steps = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    return _LineFrame(xy=xy, cumulative=np.concatenate(([0.0], np.cumsum(steps))), origin=origin)


def _nearest_on_line(frame: _LineFrame, *, lon: float, lat: float) -> tuple[float, float]:
    """Distance from a point to a line, and how far along the line its nearest point lies."""
    width = KM_PER_DEGREE * math.cos(math.radians(frame.origin[1]))
    point = np.array([(lon - frame.origin[0]) * width, (lat - frame.origin[1]) * KM_PER_DEGREE])
    if frame.xy.shape[0] == 1:
        return float(np.linalg.norm(frame.xy[0] - point)), 0.0
    starts = frame.xy[:-1]
    deltas = frame.xy[1:] - starts
    lengths = np.linalg.norm(deltas, axis=1)
    fractions = np.clip(
        ((point - starts) * deltas).sum(axis=1) / np.where(lengths > 0.0, lengths, 1.0) ** 2,
        0.0,
        1.0,
    )
    closest = starts + fractions[:, None] * deltas
    distances = np.linalg.norm(closest - point, axis=1)
    index = int(np.argmin(distances))
    return (
        float(distances[index]),
        float(frame.cumulative[index] + fractions[index] * lengths[index]),
    )


def _haversine_km(
    lon1: float | npt.NDArray[np.float64],
    lat1: float | npt.NDArray[np.float64],
    lon2: float | npt.NDArray[np.float64],
    lat2: float | npt.NDArray[np.float64],
) -> npt.NDArray[np.float64]:
    """Great-circle distance in kilometres; arrays broadcast, so one seat can face many stations."""
    phi1 = np.radians(np.asarray(lat1, dtype=float))
    phi2 = np.radians(np.asarray(lat2, dtype=float))
    delta_phi = phi2 - phi1
    delta_lambda = np.radians(np.asarray(lon2, dtype=float) - np.asarray(lon1, dtype=float))
    haversine = (
        np.sin(delta_phi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(delta_lambda / 2.0) ** 2
    )
    return np.asarray(2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(haversine)), dtype=float)


def _edge_row(
    source: str,
    target: str,
    *,
    distance_km: float,
    cost: float,
    capacity: float,
    risk: float,
    provenance: DataProvenance,
) -> dict[str, object]:
    """One edge-table row: the four metrics and the provenance columns the adapter reads."""
    return {
        "source": source,
        "target": target,
        "distance_km": distance_km,
        "cost": cost,
        "capacity": capacity,
        "risk": risk,
        "evidence_grade": provenance.grade.value,
        "source_id": provenance.source_id,
        "locator": provenance.locator,
        "note": provenance.note,
    }


def _edge_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    """Rows in the adapter's edge schema, empty or not, with the columns in the adapter's order."""
    table = pl.DataFrame(rows, schema=_EDGE_DTYPES) if rows else pl.DataFrame(schema=_EDGE_DTYPES)
    return table.select(list(EDGE_COLUMNS))


def _require_columns(frame: pl.DataFrame, columns: tuple[str, ...]) -> None:
    """Refuse a frame that cannot be read, naming the columns rather than failing further down."""
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise EdgeBuildError(f"table is missing columns: {', '.join(missing)}")


def _zip_path(root: str | Path, relative: str) -> Path:
    path = Path(root) / relative
    if not path.exists():
        raise EdgeBuildError(f"{path} is not there: the raw courier layer is never fetched")
    return path


def _resolve_root(root: str | Path | None) -> Path:
    if root is not None:
        return Path(root)
    found = find_repo_root()
    if found is None:
        raise EdgeBuildError(
            "no repository root found; pass the directory holding data/raw/private"
        )
    return found


def _candidate_note(radius_km: float) -> str:
    return (
        "Candidate rule, and not evidence of a historical link: every pair of located nodes within "
        f"{radius_km:g} km of each other, by great-circle distance over the node table's own "
        "latitude and longitude, is listed, and no pair is accepted until its graph's own rule "
        "confirms it. "
        f"Declared placeholder magnitudes: cost = distance_km / {CANDIDATE_KM_PER_DAY:g} (a "
        f"{CANDIDATE_KM_PER_DAY:g} km day), capacity = {CANDIDATE_CAPACITY:g}, "
        f"risk = {CANDIDATE_RISK:g}."
    )


def _military_note(hops: int) -> str:
    return (
        "Link rule: each seat snaps to its nearest station within "
        f"{STATION_SNAP_RADIUS_KM:g} km; two stations are adjacent when a route line passes within "
        f"{STATION_SNAP_RADIUS_KM:g} km of both with no station between them on it; two seats link "
        f"when the shortest chain between their stations is at most {MAX_STATION_HOPS} legs. This "
        f"{hops}-hop pair sits on a chain classed by its strongest (lowest) MAJ_MINOR. Declared, "
        f"not read: cost = distance_km / {MILITARY_KM_PER_DAY:g} (a "
        f"{MILITARY_KM_PER_DAY:g} km march day), capacity = {MILITARY_CAPACITY:g} troops a month, "
        f"risk = {MILITARY_RISK_MAJOR:g} major, {MILITARY_RISK_MINOR:g} minor. "
        + STATION_COORDINATE_DEFECT
    )


def _trade_note(hops: int, *, provenance_note: bool = False) -> str:
    if provenance_note:
        return (
            "Trade link inferred from a documented courier road: the pair is a "
            f"{hops}-hop chain in the CHGIS V6 courier layer whose strongest segment is "
            "MAJ_MINOR = 1 (a chain may include a minor leg) "
            f"({COURIER_ROUTES[0]}). The road is sourced; the grain movement along it is this "
            "project's inference, and the magnitudes are declared: cost = distance_km / "
            f"{TRADE_KM_PER_DAY:g}, capacity = {TRADE_CAPACITY:g}, risk = {TRADE_RISK:g}."
        )
    return (
        "Accepted trade link. The road is documented in the CHGIS V6 courier routes layer "
        f"({COURIER_ROUTES[0]}, Ming_Routes_2016.zip): this pair is a {hops}-hop pair on a chain "
        "of segments the layer publishes as MAJ_MINOR = 1. The grain movement along that road is "
        f"inferred, not observed, and the magnitudes are declared: cost = distance_km / "
        f"{TRADE_KM_PER_DAY:g} (a {TRADE_KM_PER_DAY:g} km trading day), capacity = "
        f"{TRADE_CAPACITY:g}, risk = {TRADE_RISK:g}."
    )


def _migration_note() -> str:
    return (
        "Accepted migration link, the weakest topology of the three: county seats within "
        f"{MIGRATION_MAX_KM:g} km of each other in the same province, plus one link from every "
        "external node to its nearest county seat so the exits stay connected. Neither rule is "
        "evidence of a documented movement; both are declared proxies, and both are sensitivity "
        "items for V2-P03 (the threshold) and V2-P04 (the structure). Declared magnitudes: cost = "
        f"{MIGRATION_COST_PER_HOUSEHOLD:g} model cost unit per household moved (household units, "
        f"not kilometres), capacity = {MIGRATION_CAPACITY:g} households a month, "
        f"risk = {MIGRATION_RISK:g}."
    )
