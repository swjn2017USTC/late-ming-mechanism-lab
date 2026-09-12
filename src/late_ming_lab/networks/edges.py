"""Edge records for the three spatial graphs.

The same pair of places has different costs depending on what moves along the link, so the
numbers never travel alone: each graph carries its own :class:`EdgeSemantics`, and no code
may read a cost without knowing which graph it came from.

Every edge stores ``distance_km``, ``cost``, ``capacity`` and ``risk``. Their meanings are
graph-specific; the units are declared in the semantics record rather than guessed.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from late_ming_lab.evidence.grades import DataProvenance

NODE_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"


class GraphKind(StrEnum):
    """The three separate movement graphs; never one county-adjacency graph."""

    TRADE = "trade"
    MIGRATION = "migration"
    MILITARY = "military"


class EdgeSemantics(BaseModel):
    """What ``cost``, ``capacity`` and ``risk`` mean in one graph."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: GraphKind
    version: str
    cost_meaning: str
    cost_unit: str
    capacity_meaning: str
    capacity_unit: str
    risk_meaning: str
    distance_meaning: str = "ground distance between the two seats, approximate"


class EdgeMetrics(BaseModel):
    """The four quantities every edge stores, with units fixed by its graph."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    distance_km: float = Field(gt=0, allow_inf_nan=False)
    cost: float = Field(gt=0, allow_inf_nan=False)
    capacity: float = Field(gt=0, allow_inf_nan=False)
    risk: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)


class EdgeRecord(BaseModel):
    """One undirected link in one graph.

    Links are symmetric in P02: a single cost stands for both directions. Directional
    terrain asymmetry is a declared open item, not a silent approximation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(pattern=NODE_ID_PATTERN, max_length=64)
    target: str = Field(pattern=NODE_ID_PATTERN, max_length=64)
    metrics: EdgeMetrics
    provenance: DataProvenance

    @model_validator(mode="after")
    def _validate_endpoints(self) -> EdgeRecord:
        if self.source == self.target:
            raise ValueError(f"self-loop at {self.source!r} is not a link between places")
        return self

    @property
    def key(self) -> tuple[str, str]:
        """Order-independent edge identity."""
        first, second = sorted((self.source, self.target))
        return (first, second)
