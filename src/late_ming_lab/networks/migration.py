"""``G_migration``: household movement between seats and out of the core.

Cost is what it takes a household to move along the link, capacity is how many households
the link can absorb per month, risk is attrition on the way. Migration cost is deliberately
not the trade cost of the same pair of places.
"""

from __future__ import annotations

import networkx as nx

from late_ming_lab.networks.edges import EdgeRecord, EdgeSemantics, GraphKind
from late_ming_lab.networks.nodes import ExternalRole, SpatialNodes

SEMANTICS = EdgeSemantics(
    kind=GraphKind.MIGRATION,
    version="migration-semantics-v1",
    cost_meaning="what it costs a household to move along the link",
    cost_unit="model cost units (dimensionless in P02)",
    capacity_meaning="households the link can carry in one month",
    capacity_unit="households per month",
    risk_meaning="probability-like attrition suffered while moving",
)

#: An external endpoint must be declared as a migration exit.
REQUIRED_EXTERNAL_ROLE = ExternalRole.MIGRATION_EXIT


def build(*, dataset_id: str, nodes: SpatialNodes, edges: tuple[EdgeRecord, ...]) -> nx.Graph[str]:
    """Build ``G_migration`` from validated nodes and edge records."""
    graph: nx.Graph[str] = nx.Graph(
        kind=GraphKind.MIGRATION.value,
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
