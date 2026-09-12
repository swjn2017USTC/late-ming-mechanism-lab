"""The toy spatial fixture: five county nodes and three boundary nodes.

This is the **only** dataset shipped with the repository, and it is not history. Node ids are
placeholders (``toy-sx-a`` …), no node carries coordinates, and every distance, cost,
capacity and risk is a model assumption graded ``S``. It exists to exercise the schema, the
three graphs, the calendar and the climate interface, and to give later phases a small
dataset to develop against until sourced geography arrives through
``networks.adapter``.

Two Shaanxi nodes and one further Shaanxi node sit in the loess dryland zone; two Henan
nodes sit in the north China plain zone. The three boundary nodes are the Shanxi military
and trade link, the Huguang migration exit and grain link, and the Sichuan migration exit.

Known gaps, recorded rather than papered over: the two zones do not cover all of Shaanxi
(the Han river valley is a different cropping environment), and no node yet carries a
sourced location.
"""

from __future__ import annotations

from typing import Final

from late_ming_lab.evidence.grades import DataProvenance
from late_ming_lab.networks.dataset import SpatialDataset
from late_ming_lab.networks.edges import EdgeMetrics, EdgeRecord
from late_ming_lab.networks.nodes import (
    AgrarianZone,
    CountyNode,
    ExternalRole,
    NodeKind,
    Province,
)

TOY_DATASET_ID: Final[str] = "toy-fixture-v1"

#: Every value in this dataset carries this provenance. It is an assumption, not evidence.
TOY_PROVENANCE: Final[DataProvenance] = DataProvenance.assumption(
    "toy fixture: illustrative model assumption for schema and integration tests, not a "
    "historical measurement; replace with a sourced dataset before any historical claim"
)


def toy_spatial_dataset() -> SpatialDataset:
    """Build a fresh five-county toy dataset with its three edge layers."""
    return SpatialDataset(
        dataset_id=TOY_DATASET_ID,
        provenance=TOY_PROVENANCE,
        nodes=(
            _county("toy-sx-a", Province.SHAANXI, AgrarianZone.LOESS_DRYLAND),
            _county("toy-sx-b", Province.SHAANXI, AgrarianZone.LOESS_DRYLAND),
            _county("toy-sx-c", Province.SHAANXI, AgrarianZone.LOESS_DRYLAND),
            _county("toy-hn-a", Province.HENAN, AgrarianZone.NORTH_CHINA_PLAIN),
            _county("toy-hn-b", Province.HENAN, AgrarianZone.NORTH_CHINA_PLAIN),
            _external(
                "toy-ext-shanxi",
                Province.SHANXI,
                (
                    ExternalRole.MIGRATION_EXIT,
                    ExternalRole.MILITARY_LINK,
                    ExternalRole.TRADE_LINK,
                ),
            ),
            _external(
                "toy-ext-huguang",
                Province.HUGUANG,
                (ExternalRole.MIGRATION_EXIT, ExternalRole.TRADE_LINK),
            ),
            _external(
                "toy-ext-sichuan",
                Province.SICHUAN,
                (ExternalRole.MIGRATION_EXIT,),
            ),
        ),
        trade_edges=(
            _edge("toy-sx-a", "toy-sx-b", 90.0, 1.2, 400.0, 0.05),
            _edge("toy-sx-b", "toy-sx-c", 110.0, 2.0, 260.0, 0.12),
            _edge("toy-sx-c", "toy-hn-a", 150.0, 1.6, 320.0, 0.08),
            _edge("toy-hn-a", "toy-hn-b", 120.0, 0.9, 500.0, 0.04),
            _edge("toy-sx-a", "toy-ext-shanxi", 200.0, 2.6, 220.0, 0.15),
            _edge("toy-hn-a", "toy-ext-huguang", 260.0, 2.2, 300.0, 0.10),
        ),
        migration_edges=(
            _edge("toy-sx-a", "toy-sx-b", 90.0, 0.6, 120.0, 0.06),
            _edge("toy-sx-b", "toy-sx-c", 110.0, 0.9, 90.0, 0.14),
            _edge("toy-sx-c", "toy-hn-a", 150.0, 0.8, 100.0, 0.09),
            _edge("toy-hn-a", "toy-hn-b", 120.0, 0.5, 150.0, 0.05),
            _edge("toy-sx-a", "toy-ext-shanxi", 200.0, 1.1, 80.0, 0.18),
            _edge("toy-sx-c", "toy-ext-huguang", 240.0, 1.0, 110.0, 0.12),
            _edge("toy-sx-c", "toy-ext-sichuan", 210.0, 1.3, 70.0, 0.20),
        ),
        military_edges=(
            _edge("toy-sx-a", "toy-sx-b", 90.0, 0.8, 60.0, 0.10),
            _edge("toy-sx-b", "toy-sx-c", 110.0, 1.4, 45.0, 0.16),
            _edge("toy-sx-c", "toy-hn-a", 150.0, 1.2, 50.0, 0.12),
            _edge("toy-hn-a", "toy-hn-b", 120.0, 0.7, 80.0, 0.06),
            _edge("toy-sx-a", "toy-ext-shanxi", 200.0, 1.8, 40.0, 0.20),
        ),
    )


def _county(node_id: str, province: Province, zone: AgrarianZone) -> CountyNode:
    return CountyNode(
        node_id=node_id,
        kind=NodeKind.COUNTY,
        province=province,
        zone=zone,
        provenance=TOY_PROVENANCE,
    )


def _external(node_id: str, province: Province, roles: tuple[ExternalRole, ...]) -> CountyNode:
    return CountyNode(
        node_id=node_id,
        kind=NodeKind.EXTERNAL,
        province=province,
        external_roles=roles,
        provenance=TOY_PROVENANCE,
    )


def _edge(
    source: str,
    target: str,
    distance_km: float,
    cost: float,
    capacity: float,
    risk: float,
) -> EdgeRecord:
    return EdgeRecord(
        source=source,
        target=target,
        metrics=EdgeMetrics(distance_km=distance_km, cost=cost, capacity=capacity, risk=risk),
        provenance=TOY_PROVENANCE,
    )
