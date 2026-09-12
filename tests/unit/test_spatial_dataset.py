"""Dataset schema: integrity of a spatial dataset and its scaling to a regional size."""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import pytest
from pydantic import ValidationError

from late_ming_lab.evidence.grades import DataProvenance
from late_ming_lab.networks.dataset import (
    SpatialDataset,
    load_spatial_dataset,
    save_spatial_dataset,
)
from late_ming_lab.networks.edges import EdgeMetrics, EdgeRecord, GraphKind
from late_ming_lab.networks.nodes import AgrarianZone, CountyNode, ExternalRole, NodeKind, Province

ASSUMED = DataProvenance.assumption("test fixture assumption")


def _county(node_id: str, province: Province, zone: AgrarianZone) -> CountyNode:
    return CountyNode(
        node_id=node_id,
        kind=NodeKind.COUNTY,
        province=province,
        zone=zone,
        provenance=ASSUMED,
    )


def _external(node_id: str, province: Province) -> CountyNode:
    return CountyNode(
        node_id=node_id,
        kind=NodeKind.EXTERNAL,
        province=province,
        external_roles=(
            ExternalRole.MIGRATION_EXIT,
            ExternalRole.MILITARY_LINK,
            ExternalRole.TRADE_LINK,
        ),
        provenance=ASSUMED,
    )


def _edge(source: str, target: str, distance_km: float, cost: float) -> EdgeRecord:
    return EdgeRecord(
        source=source,
        target=target,
        metrics=EdgeMetrics(distance_km=distance_km, cost=cost, capacity=100.0, risk=0.1),
        provenance=ASSUMED,
    )


def _regional_dataset(county_count: int = 60) -> SpatialDataset:
    """A regional-size dataset: a ring of counties plus four boundary nodes.

    Topology is deliberately explicit and boring — the point is that the schema, the three
    graphs and the validation hold at 50-100 nodes, not that this is geography.
    """
    counties = [
        _county(
            f"county-{index:03d}",
            Province.SHAANXI if index % 2 else Province.HENAN,
            AgrarianZone.LOESS_DRYLAND if index % 2 else AgrarianZone.NORTH_CHINA_PLAIN,
        )
        for index in range(county_count)
    ]
    externals = [
        _external("ext-shanxi", Province.SHANXI),
        _external("ext-huguang", Province.HUGUANG),
        _external("ext-sichuan", Province.SICHUAN),
        _external("ext-beizhili", Province.BEIZHILI),
    ]
    ring = [
        (f"county-{index:03d}", f"county-{(index + 1) % county_count:03d}")
        for index in range(county_count)
    ]
    spokes = [
        ("county-000", "ext-shanxi"),
        (f"county-{county_count // 3:03d}", "ext-huguang"),
        (f"county-{2 * county_count // 3:03d}", "ext-sichuan"),
        (f"county-{county_count - 1:03d}", "ext-beizhili"),
    ]
    pairs = ring + spokes
    return SpatialDataset(
        dataset_id="regional-schema-check",
        provenance=ASSUMED,
        nodes=tuple(counties + externals),
        trade_edges=tuple(
            _edge(a, b, 80.0 + index, 1.0 + index / 10) for index, (a, b) in enumerate(pairs)
        ),
        migration_edges=tuple(
            _edge(a, b, 80.0 + index, 0.5 + index / 20) for index, (a, b) in enumerate(pairs)
        ),
        military_edges=tuple(
            _edge(a, b, 80.0 + index, 0.9 + index / 15) for index, (a, b) in enumerate(pairs)
        ),
    )


def test_toy_dataset_round_trips_through_json_and_file(
    toy_dataset: SpatialDataset, tmp_path: Path
) -> None:
    restored = SpatialDataset.from_json(toy_dataset.to_json())

    assert restored == toy_dataset
    assert restored.provenance.is_assumption

    path = save_spatial_dataset(tmp_path / "spatial" / "toy.json", toy_dataset)

    assert load_spatial_dataset(path) == toy_dataset


def test_unknown_endpoints_are_refused(toy_dataset: SpatialDataset) -> None:
    payload = toy_dataset.model_dump(mode="json")
    payload["trade_edges"] = [{**payload["trade_edges"][0], "target": "toy-nowhere"}]

    with pytest.raises(ValidationError, match="unknown node"):
        SpatialDataset.model_validate(payload)


def test_duplicate_edges_are_refused(toy_dataset: SpatialDataset) -> None:
    payload = toy_dataset.model_dump(mode="json")
    payload["migration_edges"] = [
        *payload["migration_edges"],
        {
            **payload["migration_edges"][0],
            "source": payload["migration_edges"][0]["target"],
            "target": payload["migration_edges"][0]["source"],
        },
    ]

    with pytest.raises(ValidationError, match="duplicate migration edge"):
        SpatialDataset.model_validate(payload)


def test_a_pair_may_not_state_two_distances(toy_dataset: SpatialDataset) -> None:
    payload = toy_dataset.model_dump(mode="json")
    first = payload["military_edges"][0]
    payload["military_edges"] = [
        {**first, "metrics": {**first["metrics"], "distance_km": 999.0}},
        *payload["military_edges"][1:],
    ]

    with pytest.raises(ValidationError, match="distance belongs to the places"):
        SpatialDataset.model_validate(payload)


def test_a_dataset_needs_at_least_one_node() -> None:
    with pytest.raises(ValidationError):
        SpatialDataset(dataset_id="empty", provenance=ASSUMED, nodes=())


def test_dataset_builds_the_three_graphs(toy_dataset: SpatialDataset) -> None:
    graphs = toy_dataset.build()

    assert graphs.dataset_id == toy_dataset.dataset_id
    assert len(graphs.nodes) == len(toy_dataset.nodes)
    assert set(GraphKind) == {GraphKind.TRADE, GraphKind.MIGRATION, GraphKind.MILITARY}


def test_a_regional_dataset_of_sixty_counties_validates_and_builds() -> None:
    dataset = _regional_dataset(60)
    graphs = dataset.build()

    counties = {node.node_id for node in dataset.node_registry().counties}
    assert len(counties) == 60
    assert len(dataset.nodes) == 64
    for kind in GraphKind:
        graph = graphs.graph(kind)
        assert nx.is_connected(graph)
        assert counties <= set(graph.nodes)
        assert graph.number_of_nodes() == 64
        assert graph.number_of_edges() == 64


def test_regional_datasets_keep_the_distance_invariant() -> None:
    dataset = _regional_dataset(50)
    distances = {
        (kind.value, edge.key): edge.metrics.distance_km
        for kind in GraphKind
        for edge in dataset.edges(kind)
    }
    by_pair: dict[tuple[str, str], set[float]] = {}
    for (_, pair), distance in distances.items():
        by_pair.setdefault(pair, set()).add(distance)

    assert all(len(found) == 1 for found in by_pair.values())
    assert len({edge.key for edge in dataset.trade_edges}) == len(dataset.trade_edges)
