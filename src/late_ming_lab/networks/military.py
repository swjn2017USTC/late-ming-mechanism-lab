"""``G_military``: movement of troops and armed groups.

Cost is march effort, capacity is how many troops the link can move in one month, risk is
attrition and interception. Military movement cost between two places differs from their
trade and migration costs; the graphs are separate on purpose.
"""

from __future__ import annotations

import networkx as nx

from late_ming_lab.networks.edges import EdgeRecord, EdgeSemantics, GraphKind
from late_ming_lab.networks.nodes import ExternalRole, SpatialNodes

SEMANTICS = EdgeSemantics(
    kind=GraphKind.MILITARY,
    version="military-semantics-v1",
    cost_meaning="march effort and supply cost of moving a force along the link",
    cost_unit="model cost units (dimensionless in P02)",
    capacity_meaning="troops the link can move or sustain in one month",
    capacity_unit="troops per month",
    risk_meaning="probability-like attrition or interception suffered while moving",
)

#: An external endpoint must be declared as a military link.
REQUIRED_EXTERNAL_ROLE = ExternalRole.MILITARY_LINK


def build(*, dataset_id: str, nodes: SpatialNodes, edges: tuple[EdgeRecord, ...]) -> nx.Graph[str]:
    """Build ``G_military`` from validated nodes and edge records."""
    graph: nx.Graph[str] = nx.Graph(
        kind=GraphKind.MILITARY.value,
        semantics=SEMANTICS.model_dump(mode="json"),
        dataset_id=dataset_id,
    )
    # Counties always belong to the layer; boundary nodes enter only through an edge.
    graph.add_nodes_from(node.node_id for node in nodes if node.is_county)
    for edge in edges:
        graph.add_edge(
            edge.source,
            edge.target,
            distance_km=edge.metrics.distance_km,
            cost=edge.metrics.cost,
            capacity=edge.metrics.capacity,
            risk=edge.metrics.risk,
            provenance=edge.provenance.model_dump(mode="json"),
        )
    return graph
