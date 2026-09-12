"""The three spatial graphs together, with the invariants that keep them honest.

``G_trade``, ``G_migration`` and ``G_military`` are built separately from the same dataset
and validated here:

- every graph contains every county node, so no county silently drops out of a layer;
- each graph is connected over its own node set;
- an external node appears in a graph only if it declares the role that graph needs;
- only edges declared for that graph appear, so a missing cost cannot be inherited from
  another graph's edge.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

import networkx as nx

from late_ming_lab.networks import migration, military, trade
from late_ming_lab.networks.edges import EdgeRecord, EdgeSemantics, GraphKind
from late_ming_lab.networks.nodes import ExternalRole, SpatialNodes


class SpatialGraphError(ValueError):
    """Raised when a dataset cannot produce three valid, separate graphs."""


@dataclass(frozen=True, slots=True)
class SpatialGraphs:
    """Validated spatial layer: the node registry and its three movement graphs."""

    dataset_id: str
    nodes: SpatialNodes
    semantics: Mapping[GraphKind, EdgeSemantics]
    trade: nx.Graph[str]
    migration: nx.Graph[str]
    military: nx.Graph[str]

    def graph(self, kind: GraphKind) -> nx.Graph[str]:
        """The graph of one kind; the kind must always be named explicitly."""
        if kind is GraphKind.TRADE:
            return self.trade
        if kind is GraphKind.MIGRATION:
            return self.migration
        return self.military

    def cost(self, kind: GraphKind, source: str, target: str) -> float:
        """Edge cost in one specific graph."""
        data = self.graph(kind).get_edge_data(source, target)
        if data is None:
            raise KeyError(f"no {kind.value} link between {source!r} and {target!r}")
        return float(data["cost"])


REQUIRED_EXTERNAL_ROLES: Final[Mapping[GraphKind, ExternalRole]] = MappingProxyType(
    {
        GraphKind.TRADE: trade.REQUIRED_EXTERNAL_ROLE,
        GraphKind.MIGRATION: migration.REQUIRED_EXTERNAL_ROLE,
        GraphKind.MILITARY: military.REQUIRED_EXTERNAL_ROLE,
    }
)


def build_graphs(
    *,
    dataset_id: str,
    nodes: SpatialNodes,
    edges: Mapping[GraphKind, tuple[EdgeRecord, ...]],
) -> SpatialGraphs:
    """Build and validate the three graphs from validated edge records."""
    for kind, records in edges.items():
        _validate_edges(kind, records, nodes)

    built = {
        kind: builder(dataset_id=dataset_id, nodes=nodes, edges=edges[kind])
        for kind, builder in (
            (GraphKind.TRADE, trade.build),
            (GraphKind.MIGRATION, migration.build),
            (GraphKind.MILITARY, military.build),
        )
    }
    for kind, graph in built.items():
        _validate_graph(kind, graph, nodes)
    return SpatialGraphs(
        dataset_id=dataset_id,
        nodes=nodes,
        semantics=MappingProxyType(
            {
                GraphKind.TRADE: trade.SEMANTICS,
                GraphKind.MIGRATION: migration.SEMANTICS,
                GraphKind.MILITARY: military.SEMANTICS,
            }
        ),
        trade=built[GraphKind.TRADE],
        migration=built[GraphKind.MIGRATION],
        military=built[GraphKind.MILITARY],
    )


def _validate_edges(kind: GraphKind, edges: tuple[EdgeRecord, ...], nodes: SpatialNodes) -> None:
    seen: set[tuple[str, str]] = set()
    required_role = REQUIRED_EXTERNAL_ROLES[kind]
    for edge in edges:
        for endpoint in (edge.source, edge.target):
            if endpoint not in nodes.by_id:
                raise SpatialGraphError(f"{kind.value} edge references unknown node {endpoint!r}")
        if edge.key in seen:
            raise SpatialGraphError(
                f"duplicate {kind.value} edge between {edge.source!r} and {edge.target!r}"
            )
        seen.add(edge.key)
        for endpoint in (edge.source, edge.target):
            node = nodes.require(endpoint)
            if node.is_county:
                continue
            if not node.serves(required_role):
                raise SpatialGraphError(
                    f"{kind.value} edge touches external node {node.node_id!r}, which does "
                    f"not declare the {required_role.value!r} role"
                )


def _validate_graph(kind: GraphKind, graph: nx.Graph[str], nodes: SpatialNodes) -> None:
    missing = [node.node_id for node in nodes.counties if node.node_id not in graph]
    if missing:
        raise SpatialGraphError(f"{kind.value} graph is missing county nodes: {', '.join(missing)}")
    if graph.number_of_nodes() and not nx.is_connected(graph):
        raise SpatialGraphError(f"{kind.value} graph is not connected")
