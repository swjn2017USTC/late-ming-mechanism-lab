"""Adapters from normalized tables to a :class:`SpatialDataset`.

Real historical geography enters the model only through these functions, and only with
provenance columns. Nothing here fetches, downloads or fills data: a table missing a grade,
or a sourced grade missing a source, is rejected rather than defaulted. The toy fixture in
``fixtures.py`` is the only dataset shipped with the repository, and it is graded ``S``.

Expected columns:

- nodes: ``node_id``, ``kind``, ``province``, ``zone``, ``external_roles``, ``latitude``,
  ``longitude``, ``location_precision``, ``location_uncertainty_km``, ``evidence_grade``,
  ``source_id``, ``locator``, ``note``
- edges: ``source``, ``target``, ``distance_km``, ``cost``, ``capacity``, ``risk``,
  ``evidence_grade``, ``source_id``, ``locator``, ``note``

Extra columns are ignored; a normalized table often carries comments and joins.
"""

from __future__ import annotations

from typing import Any

import polars as pl
from pydantic import ValidationError

from late_ming_lab.evidence.grades import DataProvenance, EvidenceGrade
from late_ming_lab.networks.dataset import SpatialDataset
from late_ming_lab.networks.edges import EdgeMetrics, EdgeRecord
from late_ming_lab.networks.nodes import (
    AgrarianZone,
    CountyNode,
    ExternalRole,
    LocationPrecision,
    NodeKind,
    NodeLocation,
    Province,
)

NODE_COLUMNS: tuple[str, ...] = (
    "node_id",
    "kind",
    "province",
    "zone",
    "external_roles",
    "latitude",
    "longitude",
    "location_precision",
    "location_uncertainty_km",
    "evidence_grade",
    "source_id",
    "locator",
    "note",
)

EDGE_COLUMNS: tuple[str, ...] = (
    "source",
    "target",
    "distance_km",
    "cost",
    "capacity",
    "risk",
    "evidence_grade",
    "source_id",
    "locator",
    "note",
)


class SpatialTableError(ValueError):
    """Raised when a normalized table cannot become a validated dataset."""


def nodes_from_frame(frame: pl.DataFrame) -> tuple[CountyNode, ...]:
    """Convert a normalized node table into nodes, one grade per row."""
    _require_columns("node", frame, NODE_COLUMNS)
    nodes = []
    for index, row in enumerate(frame.select(list(NODE_COLUMNS)).iter_rows(named=True)):
        try:
            nodes.append(
                CountyNode(
                    node_id=_text(row["node_id"], "node_id", index),
                    kind=NodeKind(_text(row["kind"], "kind", index)),
                    province=Province(_text(row["province"], "province", index)),
                    zone=_zone(row["zone"], index),
                    location=_location(row, index),
                    external_roles=_roles(row["external_roles"], index),
                    provenance=_provenance(row, index),
                )
            )
        except (ValidationError, ValueError) as error:
            if isinstance(error, SpatialTableError):
                raise
            raise SpatialTableError(f"node row {index}: {error}") from error
    return tuple(nodes)


def edges_from_frame(frame: pl.DataFrame) -> tuple[EdgeRecord, ...]:
    """Convert a normalized edge table for one graph into edge records."""
    _require_columns("edge", frame, EDGE_COLUMNS)
    records = []
    for index, row in enumerate(frame.select(list(EDGE_COLUMNS)).iter_rows(named=True)):
        try:
            records.append(
                EdgeRecord(
                    source=_text(row["source"], "source", index),
                    target=_text(row["target"], "target", index),
                    metrics=EdgeMetrics(
                        distance_km=_number(row["distance_km"], "distance_km", index),
                        cost=_number(row["cost"], "cost", index),
                        capacity=_number(row["capacity"], "capacity", index),
                        risk=_number(row["risk"], "risk", index),
                    ),
                    provenance=_provenance(row, index),
                )
            )
        except (ValidationError, ValueError) as error:
            if isinstance(error, SpatialTableError):
                raise
            raise SpatialTableError(f"edge row {index}: {error}") from error
    return tuple(records)


def dataset_from_frames(
    *,
    dataset_id: str,
    provenance: DataProvenance,
    nodes: pl.DataFrame,
    trade: pl.DataFrame,
    migration: pl.DataFrame,
    military: pl.DataFrame,
) -> SpatialDataset:
    """Assemble a validated dataset from one node table and three edge tables."""
    return SpatialDataset(
        dataset_id=dataset_id,
        provenance=provenance,
        nodes=nodes_from_frame(nodes),
        trade_edges=edges_from_frame(trade),
        migration_edges=edges_from_frame(migration),
        military_edges=edges_from_frame(military),
    )


def _require_columns(table: str, frame: pl.DataFrame, columns: tuple[str, ...]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise SpatialTableError(f"{table} table is missing columns: {', '.join(missing)}")


def _text(value: Any, column: str, index: int) -> str:
    if value is None or not str(value).strip():
        raise SpatialTableError(f"row {index}: column {column!r} must not be empty")
    return str(value).strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any, column: str, index: int) -> float:
    if value is None:
        raise SpatialTableError(f"row {index}: column {column!r} must not be empty")
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise SpatialTableError(f"row {index}: column {column!r} is not a number") from error


def _zone(value: Any, index: int) -> AgrarianZone | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        return AgrarianZone(text)
    except ValueError as error:
        raise SpatialTableError(f"row {index}: unknown agrarian zone {text!r}") from error


def _roles(value: Any, index: int) -> tuple[ExternalRole, ...]:
    text = _optional_text(value)
    if text is None:
        return ()
    roles = []
    for token in text.split(","):
        name = token.strip()
        if not name:
            continue
        try:
            roles.append(ExternalRole(name))
        except ValueError as error:
            raise SpatialTableError(f"row {index}: unknown external role {name!r}") from error
    return tuple(roles)


def _location(row: dict[str, Any], index: int) -> NodeLocation | None:
    latitude = row["latitude"]
    longitude = row["longitude"]
    if latitude is None and longitude is None:
        return None
    if latitude is None or longitude is None:
        raise SpatialTableError(
            f"row {index}: latitude and longitude must be given together or not at all"
        )
    precision = _optional_text(row["location_precision"])
    if precision is None:
        raise SpatialTableError(f"row {index}: a located node must state location_precision")
    uncertainty = row["location_uncertainty_km"]
    if uncertainty is None:
        raise SpatialTableError(f"row {index}: a located node must state location_uncertainty_km")
    return NodeLocation(
        latitude=_number(latitude, "latitude", index),
        longitude=_number(longitude, "longitude", index),
        precision=LocationPrecision(precision),
        uncertainty_km=_number(uncertainty, "location_uncertainty_km", index),
        provenance=_provenance(row, index),
    )


def _provenance(row: dict[str, Any], index: int) -> DataProvenance:
    grade = _optional_text(row["evidence_grade"])
    if grade is None:
        raise SpatialTableError(
            f"row {index}: every row carries an evidence grade; a value without provenance "
            "cannot enter the model"
        )
    try:
        return DataProvenance(
            grade=EvidenceGrade(grade.upper()),
            source_id=_optional_text(row["source_id"]),
            locator=_optional_text(row["locator"]),
            note=_optional_text(row["note"]) or "",
        )
    except (ValidationError, ValueError) as error:
        raise SpatialTableError(f"row {index}: {error}") from error
