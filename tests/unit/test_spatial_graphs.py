"""Graph contract: three separate graphs, connected, with valid edge metrics.

The point of these tests is that trade, migration and military movement cannot collapse
into one adjacency graph: the node sets differ, the costs differ, and a mutation in one
graph cannot be observed in another.
"""

from __future__ import annotations

import networkx as nx
import pytest
from pydantic import ValidationError

from late_ming_lab.evidence.grades import DataProvenance
from late_ming_lab.networks.dataset import SpatialDataset
from late_ming_lab.networks.edges import EdgeMetrics, EdgeRecord, GraphKind
from late_ming_lab.networks.graphs import SpatialGraphs
from late_ming_lab.networks.nodes import ExternalRole

ASSUMED = DataProvenance.assumption("test fixture assumption")
KINDS = (GraphKind.TRADE, GraphKind.MIGRATION, GraphKind.MILITARY)


def test_every_graph_is_connected_and_holds_every_county(toy_graphs: SpatialGraphs) -> None:
    counties = {node.node_id for node in toy_graphs.nodes.counties}

    for kind in KINDS:
        graph = toy_graphs.graph(kind)
        assert nx.is_connected(graph), kind
        assert counties <= set(graph.nodes), kind


def test_the_three_graphs_are_not_one_graph(toy_graphs: SpatialGraphs) -> None:
    node_sets = {kind: set(toy_graphs.graph(kind).nodes) for kind in KINDS}

    assert toy_graphs.trade is not toy_graphs.migration
    assert toy_graphs.migration is not toy_graphs.military
    assert node_sets[GraphKind.TRADE] != node_sets[GraphKind.MIGRATION]
    assert "toy-ext-sichuan" in node_sets[GraphKind.MIGRATION]
    assert "toy-ext-sichuan" not in node_sets[GraphKind.TRADE]
    assert "toy-ext-huguang" in node_sets[GraphKind.TRADE]
    assert "toy-ext-huguang" not in node_sets[GraphKind.MILITARY]


def test_the_same_pair_carries_different_costs_per_graph(toy_graphs: SpatialGraphs) -> None:
    costs = [toy_graphs.cost(kind, "toy-sx-a", "toy-sx-b") for kind in KINDS]
    distances = [toy_graphs.graph(kind)["toy-sx-a"]["toy-sx-b"]["distance_km"] for kind in KINDS]

    assert len(set(costs)) == len(KINDS)
    assert len(set(distances)) == 1, "distance belongs to the places, not to the graph"


def test_mutating_one_graph_cannot_be_seen_in_another(toy_graphs: SpatialGraphs) -> None:
    trade_edge = toy_graphs.trade["toy-sx-a"]["toy-sx-b"]
    military_cost = toy_graphs.military["toy-sx-a"]["toy-sx-b"]["cost"]

    trade_edge["cost"] = 99.0
    trade_edge["provenance"]["note"] = "mutated"

    assert toy_graphs.migration["toy-sx-a"]["toy-sx-b"]["cost"] != 99.0
    assert toy_graphs.military["toy-sx-a"]["toy-sx-b"]["cost"] == military_cost
    assert toy_graphs.migration["toy-sx-a"]["toy-sx-b"]["provenance"]["note"] != "mutated"


def test_each_graph_declares_what_its_numbers_mean(toy_graphs: SpatialGraphs) -> None:
    for kind in KINDS:
        semantics = toy_graphs.semantics[kind]
        graph = toy_graphs.graph(kind)

        assert semantics.kind is kind
        assert graph.graph["kind"] == kind.value
        assert graph.graph["semantics"]["version"] == semantics.version

    assert len({toy_graphs.semantics[kind].version for kind in KINDS}) == len(KINDS)
    assert len({toy_graphs.semantics[kind].cost_meaning for kind in KINDS}) == len(KINDS)


def test_cost_lookup_requires_naming_a_graph(toy_graphs: SpatialGraphs) -> None:
    with pytest.raises(KeyError, match="no military link"):
        toy_graphs.cost(GraphKind.MILITARY, "toy-hn-a", "toy-ext-huguang")
    with pytest.raises(KeyError):
        toy_graphs.cost(GraphKind.TRADE, "toy-sx-a", "toy-ext-sichuan")


@pytest.mark.parametrize(
    "metrics",
    [
        {"distance_km": 0.0},
        {"distance_km": -5.0},
        {"distance_km": float("nan")},
        {"distance_km": float("inf")},
        {"cost": 0.0},
        {"cost": -1.0},
        {"cost": float("nan")},
        {"capacity": 0.0},
        {"capacity": -10.0},
        {"risk": -0.01},
        {"risk": 1.01},
        {"risk": float("nan")},
    ],
)
def test_invalid_edge_numbers_are_rejected(metrics: dict[str, float]) -> None:
    complete = {"distance_km": 100.0, "cost": 1.0, "capacity": 100.0, "risk": 0.1, **metrics}

    with pytest.raises(ValidationError):
        EdgeMetrics.model_validate(complete)


def test_self_loops_are_rejected() -> None:
    with pytest.raises(ValidationError, match="self-loop"):
        EdgeRecord(
            source="county-a",
            target="county-a",
            metrics=EdgeMetrics(distance_km=1.0, cost=1.0, capacity=1.0, risk=0.0),
            provenance=ASSUMED,
        )


def test_an_external_node_enters_a_graph_only_with_the_matching_role(
    toy_dataset: SpatialDataset,
) -> None:
    payload = toy_dataset.model_dump(mode="json")
    payload["nodes"] = [
        {**node, "external_roles": ["migration-exit"]}
        if node["node_id"] == "toy-ext-shanxi"
        else node
        for node in payload["nodes"]
    ]
    without_trade_role = type(toy_dataset).model_validate(payload)

    with pytest.raises(ValueError, match="trade-link"):
        without_trade_role.build()


def test_a_graph_without_edges_between_counties_is_refused(
    toy_dataset: SpatialDataset,
) -> None:
    payload = toy_dataset.model_dump(mode="json")
    payload["trade_edges"] = payload["trade_edges"][:1]

    with pytest.raises(ValueError, match="not connected"):
        type(toy_dataset).model_validate(payload).build()


def test_boundary_nodes_declare_the_roles_their_graphs_need(toy_graphs: SpatialGraphs) -> None:
    registry = toy_graphs.nodes

    assert registry.require("toy-ext-shanxi").external_roles == (
        ExternalRole.MIGRATION_EXIT,
        ExternalRole.MILITARY_LINK,
        ExternalRole.TRADE_LINK,
    )
    assert registry.require("toy-ext-sichuan").external_roles == (ExternalRole.MIGRATION_EXIT,)
    with pytest.raises(KeyError):
        registry.require("toy-ext-beizhili")
