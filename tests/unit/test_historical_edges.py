"""Edges: the candidate pool, the courier station graph, and what each graph accepts."""

from __future__ import annotations

import networkx as nx
import polars as pl
import pytest

from late_ming_lab.evidence.grades import DataProvenance
from late_ming_lab.historical.edges import (
    CANDIDATE_RADIUS_KM,
    MAX_STATION_HOPS,
    MIGRATION_MAX_KM,
    STATION_SNAP_RADIUS_KM,
    EdgeBuildError,
    RouteLine,
    accepted_edges,
    candidate_edges,
    edge_tables,
    snapped_stations,
    station_graph,
    unattached_nodes,
)
from late_ming_lab.networks.adapter import EDGE_COLUMNS
from late_ming_lab.networks.edges import GraphKind

#: The columns the edge builders read from a node table, in the adapter's own names.
NODE_FIELDS = ("node_id", "kind", "province", "latitude", "longitude")


def _node(
    node_id: str,
    *,
    longitude: float,
    latitude: float,
    province: str = "shaanxi",
    kind: str = "county",
) -> dict[str, object]:
    return {
        "node_id": node_id,
        "kind": kind,
        "province": province,
        "latitude": latitude,
        "longitude": longitude,
    }


def _nodes(*rows: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame(list(rows)).select(list(NODE_FIELDS))


def _stations(*rows: tuple[int, str, float, float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "station_id": [row[0] for row in rows],
            "name_py": [row[1] for row in rows],
            "longitude": [row[2] for row in rows],
            "latitude": [row[3] for row in rows],
        }
    )


def _line(major_minor: int, *coordinates: tuple[float, float]) -> RouteLine:
    return RouteLine(major_minor=major_minor, coordinates=coordinates)


def _courier_layer() -> pl.DataFrame:
    """Two documented stations 69 km apart on a major route, two on a minor route."""
    return _stations(
        (1, "XIAN", 108.94, 34.26),
        (2, "WEINAN", 109.60, 34.50),
        (3, "ZHENGZHOU", 113.65, 34.75),
        (4, "KAIFENG", 114.31, 34.80),
    )


def _courier_routes() -> tuple[RouteLine, ...]:
    return (
        _line(1, (108.94, 34.26), (109.60, 34.50)),
        _line(2, (113.65, 34.75), (114.31, 34.80)),
    )


def _courier_graph() -> nx.Graph[int]:
    return station_graph(_courier_layer(), _courier_routes())


def _courier_nodes() -> pl.DataFrame:
    """A seat on each of the four stations, and one that is 595 km from every station."""
    return _nodes(
        _node("sx-xian", longitude=108.90, latitude=34.28),
        _node("sx-weinan", longitude=109.60, latitude=34.50),
        _node("hn-zhengzhou", longitude=113.65, latitude=34.75, province="henan"),
        _node("hn-kaifeng", longitude=114.31, latitude=34.80, province="henan"),
        _node("bz-datong", longitude=115.00, latitude=40.00, province="shanxi"),
    )


def _chain_layer() -> pl.DataFrame:
    """Four stations in a line 55 km apart, joined by one minor and two major route segments."""
    return _stations((1, "A", 0.0, 0.0), (2, "B", 0.5, 0.0), (3, "C", 1.0, 0.0), (4, "D", 1.5, 0.0))


def _chain_routes() -> tuple[RouteLine, ...]:
    return (
        _line(2, (0.0, 0.0), (0.5, 0.0)),
        _line(1, (0.5, 0.0), (1.0, 0.0)),
        _line(1, (1.0, 0.0), (1.5, 0.0)),
    )


def _chain_graph() -> nx.Graph[int]:
    return station_graph(_chain_layer(), _chain_routes())


def _chain_nodes() -> pl.DataFrame:
    return _nodes(
        _node("sx-a", longitude=0.0, latitude=0.0),
        _node("sx-b", longitude=0.5, latitude=0.0),
        _node("sx-c", longitude=1.0, latitude=0.0),
        _node("sx-d", longitude=1.5, latitude=0.0),
    )


def _province_nodes() -> pl.DataFrame:
    """Two Shaanxi seats 46 km apart, a Henan one 2 km from the second, and a far Shaanxi seat."""
    return _nodes(
        _node("sx-a", longitude=108.0, latitude=34.0),
        _node("sx-b", longitude=108.5, latitude=34.0),
        _node("hn-c", longitude=108.52, latitude=34.0, province="henan"),
        _node("sx-d", longitude=110.5, latitude=34.0),
    )


def _exit_nodes() -> pl.DataFrame:
    """A county, a distant county, an exit beside the first, and an exit beside neither."""
    return _nodes(
        _node("sx-a", longitude=108.0, latitude=34.0),
        _node("sx-d", longitude=110.5, latitude=34.0),
        _node("bz-near", longitude=108.2, latitude=34.05, province="beizhili", kind="external"),
        _node("bz-far", longitude=120.0, latitude=40.0, province="beizhili", kind="external"),
    )


def _pairs(frame: pl.DataFrame) -> set[tuple[str, str]]:
    return set(zip(frame["source"].to_list(), frame["target"].to_list(), strict=True))


def test_candidate_edges_keep_the_pairs_inside_the_radius_and_drop_the_rest() -> None:
    nodes = _nodes(
        _node("sx-a", longitude=108.0, latitude=34.0),
        _node("sx-b", longitude=108.5, latitude=34.0),
        _node("hn-c", longitude=110.5, latitude=34.0, province="henan"),
    )

    inside = candidate_edges(nodes)
    assert _pairs(inside) == {("sx-a", "sx-b")}
    assert inside["distance_km"].to_list() == pytest.approx([46.1], abs=0.2)

    wider = candidate_edges(nodes, radius_km=250.0)
    assert _pairs(wider) == {("sx-a", "sx-b"), ("hn-c", "sx-a"), ("hn-c", "sx-b")}
    assert wider.columns == list(EDGE_COLUMNS)


def test_candidate_edges_are_the_same_every_time_and_never_a_self_loop() -> None:
    nodes = _nodes(
        _node("sx-b", longitude=108.5, latitude=34.0),
        _node("sx-a", longitude=108.0, latitude=34.0),
        _node("hn-c", longitude=110.5, latitude=34.0, province="henan"),
    )

    first = candidate_edges(nodes)
    second = candidate_edges(nodes)

    assert first.equals(second)
    assert first["source"].to_list() == sorted(first["source"].to_list())
    assert all(source < target for source, target in _pairs(first))
    assert first.height == len(_pairs(first))


def test_every_graph_accepts_the_same_edges_every_time() -> None:
    nodes = _courier_nodes()

    first = edge_tables(nodes, station_graph=_courier_graph())
    second = edge_tables(nodes, station_graph=_courier_graph())

    assert all(first[key].equals(second[key]) for key in first)


def test_a_military_edge_may_cross_one_intermediate_station_but_not_two() -> None:
    accepted = accepted_edges(_chain_nodes(), GraphKind.MILITARY, station_graph=_chain_graph())

    assert _pairs(accepted) == {
        ("sx-a", "sx-b"),
        ("sx-b", "sx-c"),
        ("sx-c", "sx-d"),
        ("sx-a", "sx-c"),
        ("sx-b", "sx-d"),
    }
    # sx-a to sx-d is three legs of the chain, past MAX_STATION_HOPS.
    assert ("sx-a", "sx-d") not in _pairs(accepted)
    rows = {(row["source"], row["target"]): row for row in accepted.iter_rows(named=True)}
    assert "1-hop pair" in rows[("sx-a", "sx-b")]["note"]
    assert "2-hop pair" in rows[("sx-a", "sx-c")]["note"]
    assert f"{MAX_STATION_HOPS} legs" in rows[("sx-a", "sx-c")]["note"]
    assert rows[("sx-a", "sx-b")]["risk"] == 0.15  # the only leg of that chain is a minor one
    assert rows[("sx-a", "sx-c")]["risk"] == 0.05  # one major leg classes the whole chain as major


def test_trade_takes_a_chain_class_from_its_strongest_leg() -> None:
    trade = accepted_edges(_chain_nodes(), GraphKind.TRADE, station_graph=_chain_graph())

    # sx-a to sx-b is a minor segment, so it is not a trade road; sx-a to sx-c reaches sx-c over a
    # major segment, so it is, even though the first leg is minor.
    assert _pairs(trade) == {
        ("sx-b", "sx-c"),
        ("sx-c", "sx-d"),
        ("sx-a", "sx-c"),
        ("sx-b", "sx-d"),
    }
    assert all("hop chain" in row["note"] for row in trade.iter_rows(named=True))


def test_snapped_stations_report_the_nearest_station_however_far_it_is() -> None:
    attached = snapped_stations(_courier_nodes(), station_graph=_courier_graph())

    assert attached.columns == ["node_id", "station_id", "station_name", "distance_km"]
    assert attached.height == _courier_nodes().height
    near = attached.filter(pl.col("node_id") == "sx-xian").row(0, named=True)
    assert (near["station_id"], near["station_name"]) == (1, "XIAN")
    assert near["distance_km"] == pytest.approx(4.3, abs=0.5)
    far = attached.filter(pl.col("node_id") == "bz-datong").row(0, named=True)
    assert far["station_id"] == 4  # the nearest station, even though no station is within reach
    assert far["distance_km"] > 500.0


def test_unattached_nodes_name_what_no_station_reaches() -> None:
    nodes = _courier_nodes()

    assert unattached_nodes(nodes, station_graph=_courier_graph()) == ("bz-datong",)
    assert unattached_nodes(nodes, station_graph=_courier_graph(), radius_km=3.0) == (
        "bz-datong",
        "sx-xian",
    )
    assert unattached_nodes(nodes, station_graph=nx.Graph()) == (
        "bz-datong",
        "hn-kaifeng",
        "hn-zhengzhou",
        "sx-weinan",
        "sx-xian",
    )


def test_a_candidate_row_states_that_proximity_is_only_a_screening_rule() -> None:
    frame = candidate_edges(
        _nodes(
            _node("sx-a", longitude=108.0, latitude=34.0),
            _node("sx-b", longitude=108.5, latitude=34.0),
        )
    )

    row = frame.row(0, named=True)
    assert row["evidence_grade"] == "S"
    assert row["source_id"] is None
    assert "not evidence of a historical link" in row["note"]
    assert f"{CANDIDATE_RADIUS_KM:g} km" in row["note"]
    assert row["cost"] == pytest.approx(row["distance_km"] / 25.0)
    assert (row["capacity"], row["risk"]) == (100.0, 0.1)


def test_the_station_graph_keeps_only_consecutive_stations_of_one_route() -> None:
    stations = _stations(
        (1, "LEFT", 0.0, 0.0),
        (2, "MIDDLE", 2.0, 0.05),
        (3, "RIGHT", 4.0, 0.0),
        (4, "OFFROUTE", 1.0, 0.9),
    )

    graph = station_graph(stations, (_line(1, (0.0, 0.0), (2.0, 0.05), (4.0, 0.0)),))

    assert graph.nodes[1]["name_py"] == "LEFT"
    assert graph.nodes[1]["longitude"] == 0.0
    assert sorted(graph.edges) == [(1, 2), (2, 3)]  # 1-3 is not a link: 2 lies between them
    assert graph[1][2]["major_minor"] == 1
    assert graph.degree(4) == 0  # 100 km off the route: no route passes that close to it


def test_the_station_graph_keeps_the_strongest_rank_of_a_repeated_link() -> None:
    graph = station_graph(
        _stations((1, "A", 0.0, 0.0), (2, "B", 0.5, 0.0)),
        (_line(2, (0.0, 0.0), (0.5, 0.0)), _line(1, (0.0, 0.0), (0.5, 0.0))),
    )

    assert graph.number_of_edges() == 1
    assert graph[1][2]["major_minor"] == 1


def test_a_military_edge_exists_only_where_the_courier_layer_supports_it() -> None:
    accepted = accepted_edges(_courier_nodes(), GraphKind.MILITARY, station_graph=_courier_graph())

    assert _pairs(accepted) == {("sx-weinan", "sx-xian"), ("hn-kaifeng", "hn-zhengzhou")}
    # The seat 595 km from the nearest station is on no route, so no pair of it is accepted.
    assert not any("bz-datong" in pair for pair in _pairs(accepted))


def test_a_military_edge_is_graded_by_the_courier_layer_and_priced_by_the_rank() -> None:
    accepted = accepted_edges(_courier_nodes(), GraphKind.MILITARY, station_graph=_courier_graph())
    rows = {(row["source"], row["target"]): row for row in accepted.iter_rows(named=True)}

    major = rows[("sx-weinan", "sx-xian")]
    minor = rows[("hn-kaifeng", "hn-zhengzhou")]
    assert major["evidence_grade"] == "B"
    assert major["source_id"] == "chgis-v6"
    assert "Ming_Routes_2016.zip" in str(major["locator"])
    assert "CHGIS" in str(major["locator"])
    assert "are swapped" in major["note"]  # the layer's YZ_LAT/YZ_LONG defect travels with it
    assert f"{STATION_SNAP_RADIUS_KM:g} km" in major["note"]
    assert major["risk"] == 0.05
    assert minor["risk"] == 0.15
    assert major["capacity"] == minor["capacity"] == 300.0
    assert major["cost"] == pytest.approx(major["distance_km"] / 30.0)


def test_a_seat_snaps_to_the_station_that_is_nearest_and_within_the_radius() -> None:
    nodes = _nodes(
        _node("sx-near-xian", longitude=108.90, latitude=34.28),
        _node("sx-weinan", longitude=109.60, latitude=34.50),
    )

    accepted = accepted_edges(nodes, GraphKind.MILITARY, station_graph=_courier_graph())

    assert _pairs(accepted) == {("sx-near-xian", "sx-weinan")}


def test_trade_edges_are_the_major_route_subset_priced_for_grain() -> None:
    nodes = _courier_nodes()
    graph = _courier_graph()

    military = accepted_edges(nodes, GraphKind.MILITARY, station_graph=graph)
    trade = accepted_edges(nodes, GraphKind.TRADE, station_graph=graph)

    assert _pairs(trade) == {("sx-weinan", "sx-xian")}
    assert _pairs(trade) < _pairs(military)
    row = trade.row(0, named=True)
    # documented road, inferred grain movement: grade C, with the courier layer as its source
    assert row["evidence_grade"] == "C"
    assert row["source_id"] == "chgis-v6"
    assert "Ming_Routes_2016.zip" in row["note"] or "courier" in row["note"]
    assert "inferred" in row["note"]
    assert row["cost"] == pytest.approx(row["distance_km"] / 20.0)
    assert (row["capacity"], row["risk"]) == (500.0, 0.10)
    marched = next(
        other
        for other in military.iter_rows(named=True)
        if (other["source"], other["target"]) == (row["source"], row["target"])
    )
    assert row["distance_km"] == pytest.approx(marched["distance_km"])


def test_migration_edges_follow_the_range_and_cross_the_border() -> None:
    accepted = accepted_edges(_province_nodes(), GraphKind.MIGRATION)

    # The three cross-links among sx-a, sx-b and hn-c are all inside the range - including the two
    # that cross the provincial line, which the rule allows because flight does not stop at a
    # border; sx-d is 230 km away, past the range.
    assert _pairs(accepted) == {("hn-c", "sx-a"), ("hn-c", "sx-b"), ("sx-a", "sx-b")}
    row = accepted.row(0, named=True)
    assert row["evidence_grade"] == "S"
    assert f"{MIGRATION_MAX_KM:g} km" in row["note"]
    assert "V2-P04" in row["note"]
    assert (row["cost"], row["capacity"], row["risk"]) == (1.0, 50.0, 0.20)
    assert "household" in row["note"]


def test_migration_links_every_external_node_to_its_nearest_county() -> None:
    accepted = accepted_edges(_exit_nodes(), GraphKind.MIGRATION)

    # The near exit joins sx-a; the far one joins whichever county is nearest, whatever the
    # distance, because an exit that is connected to nothing is not an exit.
    assert _pairs(accepted) == {("bz-near", "sx-a"), ("bz-far", "sx-d")}


def test_nothing_accepted_is_an_empty_frame_rather_than_an_error() -> None:
    nodes = _courier_nodes()

    apart = accepted_edges(nodes, GraphKind.MIGRATION)
    nowhere = accepted_edges(nodes, GraphKind.MILITARY, station_graph=nx.Graph())
    alone = accepted_edges(
        _nodes(_node("sx-a", longitude=108.0, latitude=34.0)), GraphKind.MIGRATION
    )

    assert apart.height == 0  # the courier seats are neighbours on a road, not in a province
    assert nowhere.height == 0
    assert alone.height == 0
    assert apart.columns == nowhere.columns == alone.columns == list(EDGE_COLUMNS)


def test_every_row_carries_provenance_the_adapter_can_read() -> None:
    nodes = _courier_nodes()
    graph = _courier_graph()
    frames = {
        "candidates": candidate_edges(nodes),
        "military": accepted_edges(nodes, GraphKind.MILITARY, station_graph=graph),
        "trade": accepted_edges(nodes, GraphKind.TRADE, station_graph=graph),
        "migration": accepted_edges(_province_nodes(), GraphKind.MIGRATION),
    }

    for name, frame in frames.items():
        assert frame.height > 0, name
        for row in frame.iter_rows(named=True):
            provenance = DataProvenance(
                grade=row["evidence_grade"],
                source_id=row["source_id"],
                locator=row["locator"],
                note=row["note"],
            )
            assert provenance.grade.value in {"B", "C", "S"}


def test_a_node_table_missing_a_column_is_refused_by_name() -> None:
    nodes = _nodes(_node("sx-a", longitude=108.0, latitude=34.0)).drop("latitude")

    with pytest.raises(EdgeBuildError, match="latitude"):
        candidate_edges(nodes)


def test_edge_tables_return_the_six_tables_with_the_candidate_pool_once() -> None:
    nodes = _courier_nodes()
    graph = _courier_graph()

    tables = edge_tables(nodes, station_graph=graph)

    assert list(tables) == [
        "trade_candidates",
        "trade_accepted",
        "migration_candidates",
        "migration_accepted",
        "military_candidates",
        "military_accepted",
    ]
    assert all(frame.columns == list(EDGE_COLUMNS) for frame in tables.values())
    assert tables["trade_candidates"].equals(tables["military_candidates"])
    assert tables["military_candidates"].equals(tables["migration_candidates"])
    assert tables["trade_candidates"].height == 2
    assert tables["migration_accepted"].height == 0
    assert _pairs(tables["military_accepted"]) == {
        ("sx-weinan", "sx-xian"),
        ("hn-kaifeng", "hn-zhengzhou"),
    }

    narrow = candidate_edges(nodes, radius_km=65.0)
    assert narrow.height == 1
    assert edge_tables(nodes, candidates=narrow, station_graph=graph)[
        "migration_candidates"
    ].equals(narrow)
