"""The spatial dataset schema: nodes plus the three edge layers.

A dataset is the unit of provenance for space. It is versioned, validated and
JSON-serializable, so a regional dataset of 50-100 nodes is the same kind of object as the
five-node toy fixture — only bigger. Cross-graph consistency is enforced here: the same pair
of places must state the same distance in every graph it appears in, while costs are
allowed to differ, because distance is a property of the places and cost is a property of
what moves.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from late_ming_lab.core.hashing import canonical_json
from late_ming_lab.evidence.grades import DataProvenance
from late_ming_lab.networks.edges import EdgeRecord, GraphKind
from late_ming_lab.networks.graphs import SpatialGraphs, build_graphs
from late_ming_lab.networks.nodes import NODE_ID_PATTERN, CountyNode, SpatialNodes
from late_ming_lab.storage.tables import read_json, write_json

DATASET_SCHEMA_VERSION = "spatial-dataset-v1"


class SpatialDataset(BaseModel):
    """Nodes and per-graph edges, with provenance for every part."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["spatial-dataset-v1"] = "spatial-dataset-v1"
    dataset_id: str = Field(pattern=NODE_ID_PATTERN, max_length=64)
    provenance: DataProvenance
    nodes: tuple[CountyNode, ...] = Field(min_length=1)
    trade_edges: tuple[EdgeRecord, ...] = ()
    migration_edges: tuple[EdgeRecord, ...] = ()
    military_edges: tuple[EdgeRecord, ...] = ()

    @model_validator(mode="after")
    def _validate_dataset(self) -> SpatialDataset:
        registry = SpatialNodes(self.nodes)
        node_ids = set(registry.by_id)
        distances: dict[tuple[str, str], float] = {}
        for kind, records in self.edges_by_kind().items():
            counts = Counter(record.key for record in records)
            duplicates = sorted(key for key, count in counts.items() if count > 1)
            if duplicates:
                pairs = ", ".join(f"{first}-{second}" for first, second in duplicates)
                raise ValueError(f"duplicate {kind.value} edge(s): {pairs}")
            for record in records:
                for endpoint in (record.source, record.target):
                    if endpoint not in node_ids:
                        raise ValueError(f"{kind.value} edge references unknown node {endpoint!r}")
                pair = record.key
                distance = distances.setdefault(pair, record.metrics.distance_km)
                if distance != record.metrics.distance_km:
                    raise ValueError(
                        f"pair {pair[0]}-{pair[1]} states distance "
                        f"{record.metrics.distance_km} km here but {distance} km elsewhere; "
                        "distance belongs to the places, cost belongs to the graph"
                    )
        return self

    def edges_by_kind(self) -> dict[GraphKind, tuple[EdgeRecord, ...]]:
        return {
            GraphKind.TRADE: self.trade_edges,
            GraphKind.MIGRATION: self.migration_edges,
            GraphKind.MILITARY: self.military_edges,
        }

    def edges(self, kind: GraphKind) -> tuple[EdgeRecord, ...]:
        return self.edges_by_kind()[kind]

    def node_registry(self) -> SpatialNodes:
        return SpatialNodes(self.nodes)

    def build(self) -> SpatialGraphs:
        """Validate and build the three separate movement graphs."""
        return build_graphs(
            dataset_id=self.dataset_id,
            nodes=self.node_registry(),
            edges=self.edges_by_kind(),
        )

    def to_json(self) -> str:
        return canonical_json(self.model_dump(mode="json"))

    @classmethod
    def from_json(cls, text: str) -> SpatialDataset:
        return cls.model_validate_json(text)


def save_spatial_dataset(path: str | Path, dataset: SpatialDataset) -> Path:
    """Write a dataset as canonical JSON, atomically."""
    return write_json(path, dataset.model_dump(mode="json"))


def load_spatial_dataset(path: str | Path) -> SpatialDataset:
    return SpatialDataset.model_validate(read_json(path))
