"""Node schema: county and boundary nodes, and the coordinates that are refused."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from late_ming_lab.evidence.grades import DataProvenance
from late_ming_lab.networks.nodes import (
    AgrarianZone,
    CountyNode,
    ExternalRole,
    LocationPrecision,
    NodeKind,
    NodeLocation,
    Province,
    SpatialNodes,
)

ASSUMED = DataProvenance.assumption("test fixture assumption")
SOURCED = DataProvenance.model_validate(
    {
        "grade": "C",
        "source_id": "chgis-2016",
        "locator": "v6 counties, row 417",
        "note": "seat point digitized from the administrative seat layer",
    }
)


def _county(node_id: str = "county-a", **overrides: object) -> CountyNode:
    payload: dict[str, object] = {
        "node_id": node_id,
        "kind": NodeKind.COUNTY,
        "province": Province.SHAANXI,
        "zone": AgrarianZone.LOESS_DRYLAND,
        "provenance": ASSUMED,
        **overrides,
    }
    return CountyNode.model_validate(payload)


def _external(node_id: str = "ext-shanxi", **overrides: object) -> CountyNode:
    payload: dict[str, object] = {
        "node_id": node_id,
        "kind": NodeKind.EXTERNAL,
        "province": Province.SHANXI,
        "external_roles": (ExternalRole.TRADE_LINK,),
        "provenance": ASSUMED,
        **overrides,
    }
    return CountyNode.model_validate(payload)


def test_county_nodes_need_a_zone_and_no_external_roles() -> None:
    assert _county().zone is AgrarianZone.LOESS_DRYLAND

    with pytest.raises(ValidationError, match="requires an agrarian zone"):
        _county(zone=None)
    with pytest.raises(ValidationError, match="cannot carry external roles"):
        _county(external_roles=(ExternalRole.TRADE_LINK,))


def test_external_nodes_need_a_role_and_no_zone() -> None:
    node = _external()

    assert node.external_roles == (ExternalRole.TRADE_LINK,)
    assert node.serves(ExternalRole.TRADE_LINK)
    assert not node.serves(ExternalRole.MIGRATION_EXIT)

    with pytest.raises(ValidationError, match="at least one external role"):
        _external(external_roles=())
    with pytest.raises(ValidationError, match="has no agrarian zone"):
        _external(zone=AgrarianZone.LOESS_DRYLAND)


def test_roles_are_stored_in_canonical_order() -> None:
    node = _external(
        external_roles=(
            ExternalRole.TRADE_LINK,
            ExternalRole.MIGRATION_EXIT,
            ExternalRole.MILITARY_LINK,
        )
    )

    assert node.external_roles == (
        ExternalRole.MIGRATION_EXIT,
        ExternalRole.MILITARY_LINK,
        ExternalRole.TRADE_LINK,
    )
    with pytest.raises(ValidationError, match="must not repeat"):
        _external(external_roles=(ExternalRole.TRADE_LINK, ExternalRole.TRADE_LINK))


def test_node_ids_follow_the_identifier_contract() -> None:
    assert _county("sx-north.1").node_id == "sx-north.1"

    with pytest.raises(ValidationError):
        _county("Shaanxi North")


def test_coordinates_must_be_sourced_never_assumed() -> None:
    with pytest.raises(ValidationError, match="coordinates are factual claims"):
        NodeLocation(
            latitude=37.5,
            longitude=110.2,
            precision=LocationPrecision.SEAT_POINT,
            uncertainty_km=5.0,
            provenance=ASSUMED,
        )

    located = _county(
        location=NodeLocation(
            latitude=37.5,
            longitude=110.2,
            precision=LocationPrecision.SEAT_POINT,
            uncertainty_km=5.0,
            provenance=SOURCED,
        )
    )

    assert located.location is not None
    assert located.location.precision is LocationPrecision.SEAT_POINT


def test_node_registry_validates_and_partitions() -> None:
    registry = SpatialNodes((_county("county-b"), _county("county-a"), _external()))

    assert [node.node_id for node in registry] == ["county-a", "county-b", "ext-shanxi"]
    assert [node.node_id for node in registry.counties] == ["county-a", "county-b"]
    assert [node.node_id for node in registry.externals] == ["ext-shanxi"]
    assert registry.require("county-a").province is Province.SHAANXI

    with pytest.raises(KeyError, match="unknown node"):
        registry.require("county-z")
    with pytest.raises(ValueError, match="duplicate node ids"):
        SpatialNodes((_county("county-a"), _county("county-a")))
    with pytest.raises(ValueError, match="at least one node"):
        SpatialNodes(())
    with pytest.raises(TypeError):
        registry.by_id["county-a"] = _county("county-a")  # type: ignore[index]
