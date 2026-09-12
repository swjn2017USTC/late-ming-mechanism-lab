"""The medium fixture: a twelve-county scale-up of the toy dataset.

The assertions here are properties of the built dataset and its three graphs, not of the
source: which counties exist, what the boundary nodes declare, which layers reach them, and
how the four edge metrics behave across layers.
"""

from __future__ import annotations

from collections import defaultdict

import networkx as nx
import pytest

from late_ming_lab.evidence.grades import EvidenceGrade
from late_ming_lab.networks.dataset import SpatialDataset
from late_ming_lab.networks.edges import GraphKind
from late_ming_lab.networks.fixtures import MEDIUM_DATASET_ID, medium_spatial_dataset
from late_ming_lab.networks.graphs import SpatialGraphs
from late_ming_lab.networks.nodes import ExternalRole, Province

KINDS = (GraphKind.TRADE, GraphKind.MIGRATION, GraphKind.MILITARY)

SHAANXI_COUNTIES = tuple(f"medium-sx-{letter}" for letter in "abcdef")
HENAN_COUNTIES = tuple(f"medium-hn-{letter}" for letter in "abcdef")
COUNTIES = SHAANXI_COUNTIES + HENAN_COUNTIES

#: Each boundary node: the province it stands for and the roles it must declare.
EXTERNALS = {
    "medium-ext-shanxi": (
        Province.SHANXI,
        frozenset(
            {
                ExternalRole.MIGRATION_EXIT,
                ExternalRole.MILITARY_LINK,
                ExternalRole.TRADE_LINK,
            }
        ),
    ),
    "medium-ext-huguang": (
        Province.HUGUANG,
        frozenset({ExternalRole.MIGRATION_EXIT, ExternalRole.TRADE_LINK}),
    ),
    "medium-ext-sichuan": (Province.SICHUAN, frozenset({ExternalRole.MIGRATION_EXIT})),
}

#: Which boundary nodes each layer must reach, derived from those declared roles.
EXTERNALS_PER_LAYER = {
    GraphKind.TRADE: frozenset({"medium-ext-shanxi", "medium-ext-huguang"}),
    GraphKind.MIGRATION: frozenset(EXTERNALS),
    GraphKind.MILITARY: frozenset({"medium-ext-shanxi"}),
}


@pytest.fixture
def dataset() -> SpatialDataset:
    return medium_spatial_dataset()


@pytest.fixture
def graphs(dataset: SpatialDataset) -> SpatialGraphs:
    return dataset.build()


def test_the_medium_dataset_declares_its_own_identity_and_size(
    dataset: SpatialDataset,
) -> None:
    assert dataset.dataset_id == MEDIUM_DATASET_ID == "medium-fixture-v1"
    registry = dataset.node_registry()
    assert len(registry.counties) == 12
    assert {node.node_id for node in registry.counties} == set(COUNTIES)
    assert {node.node_id for node in registry.externals} == set(EXTERNALS)


@pytest.mark.parametrize("node_id", sorted(EXTERNALS))
def test_boundary_nodes_declare_the_province_and_roles_they_stand_for(
    dataset: SpatialDataset, node_id: str
) -> None:
    province, roles = EXTERNALS[node_id]
    node = dataset.node_registry().require(node_id)
    assert node.province is province
    assert set(node.external_roles) == roles
    assert not node.is_county


@pytest.mark.parametrize("kind", KINDS)
def test_every_layer_holds_every_county_and_is_connected(
    graphs: SpatialGraphs, kind: GraphKind
) -> None:
    graph = graphs.graph(kind)
    assert set(COUNTIES) <= set(graph.nodes)
    assert nx.is_connected(graph)


@pytest.mark.parametrize("kind", KINDS)
def test_each_layer_reaches_the_boundary_nodes_its_roles_require(
    graphs: SpatialGraphs, kind: GraphKind
) -> None:
    reached = {node for node in graphs.graph(kind).nodes if node not in COUNTIES}
    assert reached == set(EXTERNALS_PER_LAYER[kind])


def test_the_fixture_is_an_assumption_and_carries_no_coordinates(
    dataset: SpatialDataset,
) -> None:
    assert dataset.provenance.grade is EvidenceGrade.S
    for node in dataset.nodes:
        assert node.location is None
        assert node.provenance.grade is EvidenceGrade.S
    for kind in KINDS:
        assert all(edge.provenance.grade is EvidenceGrade.S for edge in dataset.edges(kind))


def test_each_province_is_a_chain_joined_to_the_other(graphs: SpatialGraphs) -> None:
    trade = graphs.graph(GraphKind.TRADE)
    for province_nodes in (SHAANXI_COUNTIES, HENAN_COUNTIES):
        assert nx.is_connected(trade.subgraph(province_nodes))
    crossing = [
        (source, target)
        for source, target in trade.edges
        if (source in SHAANXI_COUNTIES) != (target in SHAANXI_COUNTIES)
    ]
    assert len(crossing) >= 2


def test_a_pair_states_the_same_distance_in_every_layer_it_appears_in(
    dataset: SpatialDataset,
) -> None:
    stated: dict[tuple[str, str], set[float]] = defaultdict(set)
    for kind in KINDS:
        for edge in dataset.edges(kind):
            metrics = edge.metrics
            assert metrics.distance_km > 0
            assert metrics.cost > 0
            assert metrics.capacity > 0
            assert 0 < metrics.risk <= 1
            stated[edge.key].add(metrics.distance_km)
    for pair, distances in stated.items():
        assert len(distances) == 1, f"pair {pair} states distances {sorted(distances)}"


def test_shared_pairs_order_cost_capacity_and_risk_the_same_way(
    dataset: SpatialDataset,
) -> None:
    per_layer = {kind: {edge.key: edge.metrics for edge in dataset.edges(kind)} for kind in KINDS}
    shared = set.intersection(*(set(metrics) for metrics in per_layer.values()))
    assert shared, "the fixture must contain pairs stated in all three layers"
    for pair in sorted(shared):
        trade = per_layer[GraphKind.TRADE][pair]
        migration = per_layer[GraphKind.MIGRATION][pair]
        military = per_layer[GraphKind.MILITARY][pair]
        assert migration.cost < military.cost < trade.cost, pair
        assert trade.capacity > migration.capacity > military.capacity, pair
        assert trade.risk < migration.risk < military.risk, pair
