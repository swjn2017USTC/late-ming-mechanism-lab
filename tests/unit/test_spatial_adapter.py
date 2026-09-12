"""Table adapters: real geography enters only through provenance-carrying tables."""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.evidence.grades import DataProvenance
from late_ming_lab.networks.adapter import (
    EDGE_COLUMNS,
    NODE_COLUMNS,
    SpatialTableError,
    dataset_from_frames,
    edges_from_frame,
    nodes_from_frame,
)
from late_ming_lab.networks.edges import GraphKind
from late_ming_lab.networks.nodes import AgrarianZone, ExternalRole, LocationPrecision, Province
from late_ming_lab.systems.calendar import core_default_calendar

SOURCED = DataProvenance.model_validate(
    {
        "grade": "C",
        "source_id": "chgis-2016",
        "locator": "v6 counties, seat points",
        "note": "digitized administrative seat",
    }
)


def _node_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "node_id": "sx-01",
        "kind": "county",
        "province": "shaanxi",
        "zone": "loess-dryland",
        "external_roles": None,
        "latitude": None,
        "longitude": None,
        "location_precision": None,
        "location_uncertainty_km": None,
        "evidence_grade": "C",
        "source_id": "chgis-2016",
        "locator": "v6 counties, row 417",
        "note": "seat point",
        **overrides,
    }
    return row


def _edge_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "source": "sx-01",
        "target": "sx-02",
        "distance_km": 110.0,
        "cost": 1.4,
        "capacity": 300.0,
        "risk": 0.1,
        "evidence_grade": "S",
        "source_id": None,
        "locator": None,
        "note": "assumed link cost",
        **overrides,
    }
    return row


def _frame(rows: list[dict[str, object]], columns: tuple[str, ...]) -> pl.DataFrame:
    return pl.DataFrame(rows).select(list(columns))


def test_nodes_are_parsed_with_their_zone_and_assumed_role_free_kind() -> None:
    nodes = nodes_from_frame(_frame([_node_row()], NODE_COLUMNS))

    assert len(nodes) == 1
    node = nodes[0]
    assert (node.node_id, node.province, node.zone) == (
        "sx-01",
        Province.SHAANXI,
        AgrarianZone.LOESS_DRYLAND,
    )
    assert node.location is None
    assert node.provenance.grade.value == "C"


def test_a_sourced_location_becomes_a_point_with_its_uncertainty() -> None:
    row = _node_row(
        latitude=37.5,
        longitude=110.2,
        location_precision="seat-point",
        location_uncertainty_km=3.0,
    )

    node = nodes_from_frame(_frame([row], NODE_COLUMNS))[0]

    assert node.location is not None
    assert node.location.precision is LocationPrecision.SEAT_POINT
    assert node.location.uncertainty_km == 3.0


def test_external_nodes_parse_their_roles() -> None:
    row = _node_row(
        node_id="ext-shanxi",
        kind="external",
        province="shanxi",
        zone=None,
        external_roles="migration-exit, trade-link",
    )

    node = nodes_from_frame(_frame([row], NODE_COLUMNS))[0]

    assert node.external_roles == (
        ExternalRole.MIGRATION_EXIT,
        ExternalRole.TRADE_LINK,
    )


def test_missing_columns_are_reported_by_name() -> None:
    frame = _frame([_node_row()], NODE_COLUMNS).drop("evidence_grade")

    with pytest.raises(SpatialTableError, match="missing columns: evidence_grade"):
        nodes_from_frame(frame)


def test_a_row_without_provenance_cannot_enter_the_model() -> None:
    with pytest.raises(SpatialTableError, match="every row carries an evidence grade"):
        nodes_from_frame(_frame([_node_row(evidence_grade=None)], NODE_COLUMNS))


def test_assumed_rows_must_state_the_assumption() -> None:
    with pytest.raises(SpatialTableError, match="grade S requires a note"):
        nodes_from_frame(
            _frame([_node_row(evidence_grade="S", source_id=None, note=None)], NODE_COLUMNS)
        )


def test_source_rows_must_carry_a_locator() -> None:
    with pytest.raises(SpatialTableError, match="locator"):
        nodes_from_frame(_frame([_node_row(locator=None)], NODE_COLUMNS))


def test_half_a_coordinate_is_refused() -> None:
    with pytest.raises(SpatialTableError, match="together or not at all"):
        nodes_from_frame(_frame([_node_row(latitude=37.5)], NODE_COLUMNS))


def test_a_located_node_must_state_precision_and_uncertainty() -> None:
    with pytest.raises(SpatialTableError, match="location_precision"):
        nodes_from_frame(_frame([_node_row(latitude=37.5, longitude=110.2)], NODE_COLUMNS))


def test_unknown_zones_and_roles_are_refused() -> None:
    with pytest.raises(SpatialTableError, match="unknown agrarian zone"):
        nodes_from_frame(_frame([_node_row(zone="han-valley")], NODE_COLUMNS))
    with pytest.raises(SpatialTableError, match="unknown external role"):
        nodes_from_frame(
            _frame(
                [_node_row(kind="external", zone=None, external_roles="rebellion")], NODE_COLUMNS
            )
        )


def test_edges_parse_metrics_and_assumed_provenance() -> None:
    edges = edges_from_frame(_frame([_edge_row()], EDGE_COLUMNS))

    assert len(edges) == 1
    assert edges[0].metrics.distance_km == 110.0
    assert edges[0].provenance.is_assumption


def test_invalid_edge_numbers_are_caught_at_the_table_boundary() -> None:
    with pytest.raises(SpatialTableError, match="edge row 0"):
        edges_from_frame(_frame([_edge_row(cost=-1.0)], EDGE_COLUMNS))
    with pytest.raises(SpatialTableError, match="must not be empty"):
        edges_from_frame(_frame([_edge_row(distance_km=None)], EDGE_COLUMNS))


def test_frames_assemble_into_a_dataset_that_builds_its_graphs() -> None:
    nodes = _frame(
        [
            _node_row(node_id="sx-01"),
            _node_row(node_id="hn-01", province="henan", zone="north-china-plain"),
            _node_row(
                node_id="ext-shanxi",
                kind="external",
                province="shanxi",
                zone=None,
                external_roles="trade-link",
            ),
        ],
        NODE_COLUMNS,
    )
    trade = _frame(
        [
            _edge_row(source="sx-01", target="hn-01"),
            _edge_row(source="sx-01", target="ext-shanxi"),
        ],
        EDGE_COLUMNS,
    )
    migration = _frame([_edge_row(source="sx-01", target="hn-01")], EDGE_COLUMNS)
    military = _frame([_edge_row(source="sx-01", target="hn-01")], EDGE_COLUMNS)

    dataset = dataset_from_frames(
        dataset_id="adapter-check",
        provenance=SOURCED,
        nodes=nodes,
        trade=trade,
        migration=migration,
        military=military,
    )
    graphs = dataset.build()

    assert len(dataset.node_registry().counties) == 2
    assert graphs.graph(GraphKind.TRADE).has_edge("sx-01", "ext-shanxi")
    assert core_default_calendar().calendar_for(AgrarianZone.NORTH_CHINA_PLAIN) is not None
