"""``G_trade``: grain and goods movement between seats.

Cost is the effort of moving goods, capacity is the monthly throughput of the link, risk is
the chance that a movement along it is lost or delayed. These numbers are *not*
interchangeable with migration or military costs on the same pair of places.
"""

from __future__ import annotations

import networkx as nx

from late_ming_lab.networks.edges import EdgeRecord, EdgeSemantics, GraphKind
from late_ming_lab.networks.nodes import ExternalRole, SpatialNodes

SEMANTICS = EdgeSemantics(
    kind=GraphKind.TRADE,
    version="trade-semantics-v1",
    cost_meaning="effort and expense of moving goods along the link",
    cost_unit="model cost units (dimensionless in P02)",
    capacity_meaning="goods that can move along the link in one month",
    capacity_unit="goods units per month",
    risk_meaning="probability-like chance that a movement is lost, delayed or stolen",
)

#: An external endpoint must be declared as a trade link.
REQUIRED_EXTERNAL_ROLE = ExternalRole.TRADE_LINK


def build(*, dataset_id: str, nodes: SpatialNodes, edges: tuple[EdgeRecord, ...]) -> nx.Graph[str]:
    """Build ``G_trade`` from validated nodes and edge records."""
    graph: nx.Graph[str] = nx.Graph(
        kind=GraphKind.TRADE.value,
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
