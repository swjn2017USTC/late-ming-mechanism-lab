"""Two spatial fixtures: the five-county toy set and the twelve-county medium set.

Neither is history. Node ids are placeholders (``toy-sx-a`` …, ``medium-sx-a`` …), no node
carries coordinates, and every distance, cost, capacity and risk is a model assumption
graded ``S``. The toy set is the small dataset the whole test suite develops against; the
medium set is the scale-up the dataset schema promised, twelve counties instead of five, and
it exists so that a regional-size layer can be exercised without sourcing geography. Both
exist until real geography arrives through ``networks.adapter``.

Both fixtures have the same shape. Shaanxi county nodes sit in the loess dryland zone, Henan
county nodes in the north China plain zone. The three boundary nodes are the Shanxi military
and trade link, the Huguang migration exit and grain link, and the Sichuan migration exit.
The medium set is a scale-up of the toy set and not a description of the two provinces:
which counties exist, which links join them, and every number on those links are invented
for development. Which external node is reached by which layer is not invented — it follows
the roles those nodes declare.

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

#: Every value in the toy dataset carries this provenance. It is an assumption, not evidence.
TOY_PROVENANCE: Final[DataProvenance] = DataProvenance.assumption(
    "toy fixture: illustrative model assumption for schema and integration tests, not a "
    "historical measurement; replace with a sourced dataset before any historical claim"
)

MEDIUM_DATASET_ID: Final[str] = "medium-fixture-v1"

#: Every value in the medium dataset carries this provenance. It is an assumption, not evidence.
MEDIUM_PROVENANCE: Final[DataProvenance] = DataProvenance.assumption(
    "medium fixture: placeholder county ids and invented links, a scale-up of the toy fixture "
    "for schema and integration tests, not a historical measurement; every distance, cost, "
    "capacity and risk is a model assumption to be replaced with a sourced dataset before any "
    "historical claim"
)


def toy_spatial_dataset() -> SpatialDataset:
    """Build a fresh five-county toy dataset with its three edge layers."""
    return SpatialDataset(
        dataset_id=TOY_DATASET_ID,
        provenance=TOY_PROVENANCE,
        nodes=(
            _county("toy-sx-a", Province.SHAANXI, AgrarianZone.LOESS_DRYLAND, TOY_PROVENANCE),
            _county("toy-sx-b", Province.SHAANXI, AgrarianZone.LOESS_DRYLAND, TOY_PROVENANCE),
            _county("toy-sx-c", Province.SHAANXI, AgrarianZone.LOESS_DRYLAND, TOY_PROVENANCE),
            _county("toy-hn-a", Province.HENAN, AgrarianZone.NORTH_CHINA_PLAIN, TOY_PROVENANCE),
            _county("toy-hn-b", Province.HENAN, AgrarianZone.NORTH_CHINA_PLAIN, TOY_PROVENANCE),
            _external(
                "toy-ext-shanxi",
                Province.SHANXI,
                (
                    ExternalRole.MIGRATION_EXIT,
                    ExternalRole.MILITARY_LINK,
                    ExternalRole.TRADE_LINK,
                ),
                TOY_PROVENANCE,
            ),
            _external(
                "toy-ext-huguang",
                Province.HUGUANG,
                (ExternalRole.MIGRATION_EXIT, ExternalRole.TRADE_LINK),
                TOY_PROVENANCE,
            ),
            _external(
                "toy-ext-sichuan",
                Province.SICHUAN,
                (ExternalRole.MIGRATION_EXIT,),
                TOY_PROVENANCE,
            ),
        ),
        trade_edges=(
            _edge("toy-sx-a", "toy-sx-b", 90.0, 1.2, 400.0, 0.05, TOY_PROVENANCE),
            _edge("toy-sx-b", "toy-sx-c", 110.0, 2.0, 260.0, 0.12, TOY_PROVENANCE),
            _edge("toy-sx-c", "toy-hn-a", 150.0, 1.6, 320.0, 0.08, TOY_PROVENANCE),
            _edge("toy-hn-a", "toy-hn-b", 120.0, 0.9, 500.0, 0.04, TOY_PROVENANCE),
            _edge("toy-sx-a", "toy-ext-shanxi", 200.0, 2.6, 220.0, 0.15, TOY_PROVENANCE),
            _edge("toy-hn-a", "toy-ext-huguang", 260.0, 2.2, 300.0, 0.10, TOY_PROVENANCE),
        ),
        migration_edges=(
            _edge("toy-sx-a", "toy-sx-b", 90.0, 0.6, 120.0, 0.06, TOY_PROVENANCE),
            _edge("toy-sx-b", "toy-sx-c", 110.0, 0.9, 90.0, 0.14, TOY_PROVENANCE),
            _edge("toy-sx-c", "toy-hn-a", 150.0, 0.8, 100.0, 0.09, TOY_PROVENANCE),
            _edge("toy-hn-a", "toy-hn-b", 120.0, 0.5, 150.0, 0.05, TOY_PROVENANCE),
            _edge("toy-sx-a", "toy-ext-shanxi", 200.0, 1.1, 80.0, 0.18, TOY_PROVENANCE),
            _edge("toy-sx-c", "toy-ext-huguang", 240.0, 1.0, 110.0, 0.12, TOY_PROVENANCE),
            _edge("toy-sx-c", "toy-ext-sichuan", 210.0, 1.3, 70.0, 0.20, TOY_PROVENANCE),
        ),
        military_edges=(
            _edge("toy-sx-a", "toy-sx-b", 90.0, 0.8, 60.0, 0.10, TOY_PROVENANCE),
            _edge("toy-sx-b", "toy-sx-c", 110.0, 1.4, 45.0, 0.16, TOY_PROVENANCE),
            _edge("toy-sx-c", "toy-hn-a", 150.0, 1.2, 50.0, 0.12, TOY_PROVENANCE),
            _edge("toy-hn-a", "toy-hn-b", 120.0, 0.7, 80.0, 0.06, TOY_PROVENANCE),
            _edge("toy-sx-a", "toy-ext-shanxi", 200.0, 1.8, 40.0, 0.20, TOY_PROVENANCE),
        ),
    )


def medium_spatial_dataset() -> SpatialDataset:
    """Build a fresh twelve-county fixture with its three edge layers.

    Six Shaanxi and six Henan counties form a chain inside each province, joined by two
    cross-province links; the same distances appear in every layer, while cost and capacity
    differ because the graphs are separate. On a shared pair the cost order is the toy
    fixture's: migration cheapest, military next, trade dearest. Capacities run the other way,
    trade widest and military narrowest. All of it is an assumption: see
    ``MEDIUM_PROVENANCE``.
    """
    return SpatialDataset(
        dataset_id=MEDIUM_DATASET_ID,
        provenance=MEDIUM_PROVENANCE,
        nodes=(
            _county("medium-sx-a", Province.SHAANXI, AgrarianZone.LOESS_DRYLAND, MEDIUM_PROVENANCE),
            _county("medium-sx-b", Province.SHAANXI, AgrarianZone.LOESS_DRYLAND, MEDIUM_PROVENANCE),
            _county("medium-sx-c", Province.SHAANXI, AgrarianZone.LOESS_DRYLAND, MEDIUM_PROVENANCE),
            _county("medium-sx-d", Province.SHAANXI, AgrarianZone.LOESS_DRYLAND, MEDIUM_PROVENANCE),
            _county("medium-sx-e", Province.SHAANXI, AgrarianZone.LOESS_DRYLAND, MEDIUM_PROVENANCE),
            _county("medium-sx-f", Province.SHAANXI, AgrarianZone.LOESS_DRYLAND, MEDIUM_PROVENANCE),
            _county(
                "medium-hn-a", Province.HENAN, AgrarianZone.NORTH_CHINA_PLAIN, MEDIUM_PROVENANCE
            ),
            _county(
                "medium-hn-b", Province.HENAN, AgrarianZone.NORTH_CHINA_PLAIN, MEDIUM_PROVENANCE
            ),
            _county(
                "medium-hn-c", Province.HENAN, AgrarianZone.NORTH_CHINA_PLAIN, MEDIUM_PROVENANCE
            ),
            _county(
                "medium-hn-d", Province.HENAN, AgrarianZone.NORTH_CHINA_PLAIN, MEDIUM_PROVENANCE
            ),
            _county(
                "medium-hn-e", Province.HENAN, AgrarianZone.NORTH_CHINA_PLAIN, MEDIUM_PROVENANCE
            ),
            _county(
                "medium-hn-f", Province.HENAN, AgrarianZone.NORTH_CHINA_PLAIN, MEDIUM_PROVENANCE
            ),
            _external(
                "medium-ext-shanxi",
                Province.SHANXI,
                (
                    ExternalRole.MIGRATION_EXIT,
                    ExternalRole.MILITARY_LINK,
                    ExternalRole.TRADE_LINK,
                ),
                MEDIUM_PROVENANCE,
            ),
            _external(
                "medium-ext-huguang",
                Province.HUGUANG,
                (ExternalRole.MIGRATION_EXIT, ExternalRole.TRADE_LINK),
                MEDIUM_PROVENANCE,
            ),
            _external(
                "medium-ext-sichuan",
                Province.SICHUAN,
                (ExternalRole.MIGRATION_EXIT,),
                MEDIUM_PROVENANCE,
            ),
        ),
        trade_edges=(
            _edge("medium-sx-a", "medium-sx-b", 95.0, 1.8, 420.0, 0.04, MEDIUM_PROVENANCE),
            _edge("medium-sx-b", "medium-sx-c", 120.0, 2.3, 380.0, 0.06, MEDIUM_PROVENANCE),
            _edge("medium-sx-c", "medium-sx-d", 105.0, 2.0, 400.0, 0.05, MEDIUM_PROVENANCE),
            _edge("medium-sx-d", "medium-sx-e", 130.0, 2.5, 360.0, 0.07, MEDIUM_PROVENANCE),
            _edge("medium-sx-e", "medium-sx-f", 88.0, 1.7, 440.0, 0.04, MEDIUM_PROVENANCE),
            _edge("medium-hn-a", "medium-hn-b", 78.0, 1.5, 460.0, 0.03, MEDIUM_PROVENANCE),
            _edge("medium-hn-b", "medium-hn-c", 96.0, 1.8, 430.0, 0.04, MEDIUM_PROVENANCE),
            _edge("medium-hn-c", "medium-hn-d", 112.0, 2.1, 390.0, 0.06, MEDIUM_PROVENANCE),
            _edge("medium-hn-d", "medium-hn-e", 84.0, 1.6, 450.0, 0.03, MEDIUM_PROVENANCE),
            _edge("medium-hn-e", "medium-hn-f", 101.0, 1.9, 410.0, 0.05, MEDIUM_PROVENANCE),
            _edge("medium-sx-f", "medium-hn-a", 150.0, 2.9, 330.0, 0.08, MEDIUM_PROVENANCE),
            _edge("medium-sx-c", "medium-hn-d", 205.0, 3.9, 280.0, 0.10, MEDIUM_PROVENANCE),
            _edge("medium-sx-a", "medium-ext-shanxi", 200.0, 3.8, 300.0, 0.09, MEDIUM_PROVENANCE),
            _edge("medium-hn-a", "medium-ext-huguang", 260.0, 3.6, 260.0, 0.11, MEDIUM_PROVENANCE),
        ),
        migration_edges=(
            _edge("medium-sx-a", "medium-sx-b", 95.0, 0.7, 140.0, 0.06, MEDIUM_PROVENANCE),
            _edge("medium-sx-b", "medium-sx-c", 120.0, 0.8, 120.0, 0.08, MEDIUM_PROVENANCE),
            _edge("medium-sx-c", "medium-sx-d", 105.0, 0.7, 130.0, 0.07, MEDIUM_PROVENANCE),
            _edge("medium-sx-d", "medium-sx-e", 130.0, 0.9, 110.0, 0.09, MEDIUM_PROVENANCE),
            _edge("medium-sx-e", "medium-sx-f", 88.0, 0.6, 145.0, 0.05, MEDIUM_PROVENANCE),
            _edge("medium-hn-a", "medium-hn-b", 78.0, 0.5, 150.0, 0.05, MEDIUM_PROVENANCE),
            _edge("medium-hn-b", "medium-hn-c", 96.0, 0.7, 140.0, 0.06, MEDIUM_PROVENANCE),
            _edge("medium-hn-c", "medium-hn-d", 112.0, 0.8, 125.0, 0.08, MEDIUM_PROVENANCE),
            _edge("medium-hn-d", "medium-hn-e", 84.0, 0.6, 148.0, 0.05, MEDIUM_PROVENANCE),
            _edge("medium-hn-e", "medium-hn-f", 101.0, 0.7, 135.0, 0.07, MEDIUM_PROVENANCE),
            _edge("medium-sx-f", "medium-hn-a", 150.0, 1.1, 100.0, 0.10, MEDIUM_PROVENANCE),
            _edge("medium-sx-c", "medium-hn-d", 205.0, 1.4, 85.0, 0.13, MEDIUM_PROVENANCE),
            _edge("medium-sx-a", "medium-ext-shanxi", 200.0, 1.4, 90.0, 0.12, MEDIUM_PROVENANCE),
            _edge("medium-hn-a", "medium-ext-huguang", 260.0, 1.8, 80.0, 0.14, MEDIUM_PROVENANCE),
            _edge("medium-sx-f", "medium-ext-sichuan", 215.0, 1.5, 88.0, 0.15, MEDIUM_PROVENANCE),
        ),
        military_edges=(
            _edge("medium-sx-a", "medium-sx-b", 95.0, 1.3, 60.0, 0.10, MEDIUM_PROVENANCE),
            _edge("medium-sx-b", "medium-sx-c", 120.0, 1.7, 48.0, 0.13, MEDIUM_PROVENANCE),
            _edge("medium-sx-c", "medium-sx-d", 105.0, 1.5, 55.0, 0.11, MEDIUM_PROVENANCE),
            _edge("medium-sx-d", "medium-sx-e", 130.0, 1.8, 45.0, 0.14, MEDIUM_PROVENANCE),
            _edge("medium-sx-e", "medium-sx-f", 88.0, 1.2, 62.0, 0.09, MEDIUM_PROVENANCE),
            _edge("medium-hn-a", "medium-hn-b", 78.0, 1.1, 65.0, 0.08, MEDIUM_PROVENANCE),
            _edge("medium-hn-b", "medium-hn-c", 96.0, 1.3, 58.0, 0.10, MEDIUM_PROVENANCE),
            _edge("medium-hn-c", "medium-hn-d", 112.0, 1.6, 50.0, 0.12, MEDIUM_PROVENANCE),
            _edge("medium-hn-d", "medium-hn-e", 84.0, 1.2, 64.0, 0.09, MEDIUM_PROVENANCE),
            _edge("medium-hn-e", "medium-hn-f", 101.0, 1.4, 56.0, 0.11, MEDIUM_PROVENANCE),
            _edge("medium-sx-f", "medium-hn-a", 150.0, 2.1, 40.0, 0.15, MEDIUM_PROVENANCE),
            _edge("medium-sx-c", "medium-hn-d", 205.0, 2.9, 32.0, 0.19, MEDIUM_PROVENANCE),
            _edge("medium-sx-a", "medium-ext-shanxi", 200.0, 2.8, 34.0, 0.17, MEDIUM_PROVENANCE),
        ),
    )


def _county(
    node_id: str,
    province: Province,
    zone: AgrarianZone,
    provenance: DataProvenance,
) -> CountyNode:
    return CountyNode(
        node_id=node_id,
        kind=NodeKind.COUNTY,
        province=province,
        zone=zone,
        provenance=provenance,
    )


def _external(
    node_id: str,
    province: Province,
    roles: tuple[ExternalRole, ...],
    provenance: DataProvenance,
) -> CountyNode:
    return CountyNode(
        node_id=node_id,
        kind=NodeKind.EXTERNAL,
        province=province,
        external_roles=roles,
        provenance=provenance,
    )


def _edge(
    source: str,
    target: str,
    distance_km: float,
    cost: float,
    capacity: float,
    risk: float,
    provenance: DataProvenance,
) -> EdgeRecord:
    return EdgeRecord(
        source=source,
        target=target,
        metrics=EdgeMetrics(distance_km=distance_km, cost=cost, capacity=capacity, risk=risk),
        provenance=provenance,
    )
