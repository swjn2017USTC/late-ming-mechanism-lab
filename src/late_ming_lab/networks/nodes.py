"""County and boundary nodes.

Space is represented as administrative seats with approximate catchments, never as
digitized county polygons: see ``docs/adr/0001-node-and-catchment-geography.md``. A node
carries identity, province, agrarian zone and — only when a source provides it — a location
point. It carries no area, no boundary and no household content.

Coordinates are factual claims about places, so a node location must be graded ``A`` to
``D``. Invented coordinates are refused rather than shipped with a warning label.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from enum import StrEnum
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from late_ming_lab.evidence.grades import DataProvenance, EvidenceGrade

NODE_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"


class Province(StrEnum):
    """Administrative region of a node; the core two plus boundary neighbours."""

    SHAANXI = "shaanxi"
    HENAN = "henan"
    SHANXI = "shanxi"
    HUGUANG = "huguang"
    SICHUAN = "sichuan"
    BEIZHILI = "beizhili"


class NodeKind(StrEnum):
    COUNTY = "county"
    EXTERNAL = "external"


class ExternalRole(StrEnum):
    """Why a boundary node exists in the model."""

    MIGRATION_EXIT = "migration-exit"
    TRADE_LINK = "trade-link"
    MILITARY_LINK = "military-link"
    EXTERNAL_CONDITION = "external-condition"


class AgrarianZone(StrEnum):
    """Cropping environment a county node belongs to.

    Zones are calibrated environments, not administrative units. They drive the monthly
    agricultural calendar and, later, the production function.
    """

    LOESS_DRYLAND = "loess-dryland"
    NORTH_CHINA_PLAIN = "north-china-plain"


class LocationPrecision(StrEnum):
    SEAT_POINT = "seat-point"
    CATCHMENT_CENTROID = "catchment-centroid"


class NodeLocation(BaseModel):
    """A sourced point for a node, with its stated uncertainty."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    latitude: float = Field(ge=-90.0, le=90.0, allow_inf_nan=False)
    longitude: float = Field(ge=-180.0, le=180.0, allow_inf_nan=False)
    precision: LocationPrecision
    uncertainty_km: float = Field(ge=0.0, allow_inf_nan=False)
    provenance: DataProvenance

    @model_validator(mode="after")
    def _reject_assumed_coordinates(self) -> NodeLocation:
        if self.provenance.grade is EvidenceGrade.S:
            raise ValueError(
                "coordinates are factual claims; an assumed point is not admissible "
                "(omit the location instead of inventing coordinates)"
            )
        return self


class CountyNode(BaseModel):
    """One seat with its approximate catchment, or one boundary node."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: str = Field(pattern=NODE_ID_PATTERN, max_length=64)
    kind: NodeKind
    province: Province
    zone: AgrarianZone | None = Field(
        default=None,
        description="County nodes only: the cropping environment driving calendar and yield.",
    )
    location: NodeLocation | None = None
    external_roles: tuple[ExternalRole, ...] = ()
    provenance: DataProvenance

    @field_validator("external_roles", mode="after")
    @classmethod
    def _canonical_role_order(cls, roles: tuple[ExternalRole, ...]) -> tuple[ExternalRole, ...]:
        if len(set(roles)) != len(roles):
            raise ValueError("external_roles must not repeat a role")
        return tuple(sorted(roles, key=lambda role: role.value))

    @model_validator(mode="after")
    def _validate_kind_consistency(self) -> CountyNode:
        if self.kind is NodeKind.COUNTY:
            if self.zone is None:
                raise ValueError(f"county node {self.node_id!r} requires an agrarian zone")
            if self.external_roles:
                raise ValueError(
                    f"county node {self.node_id!r} cannot carry external roles; "
                    "those describe boundary nodes"
                )
        else:
            if self.zone is not None:
                raise ValueError(
                    f"external node {self.node_id!r} has no agrarian zone: the model does "
                    "not simulate agriculture outside the core provinces"
                )
            if not self.external_roles:
                raise ValueError(
                    f"external node {self.node_id!r} requires at least one external role"
                )
        return self

    @property
    def is_county(self) -> bool:
        return self.kind is NodeKind.COUNTY

    def serves(self, role: ExternalRole) -> bool:
        return role in self.external_roles


class SpatialNodes:
    """Validated, ordered node registry for one dataset."""

    def __init__(self, nodes: Sequence[CountyNode]) -> None:
        if not nodes:
            raise ValueError("a spatial dataset needs at least one node")
        ordered = tuple(sorted(nodes, key=lambda node: node.node_id))
        counts = Counter(node.node_id for node in ordered)
        duplicates = sorted(node_id for node_id, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(f"duplicate node ids: {', '.join(duplicates)}")
        self._nodes = ordered
        self._by_id = MappingProxyType({node.node_id: node for node in ordered})

    def __iter__(self) -> Iterator[CountyNode]:
        return iter(self._nodes)

    def __len__(self) -> int:
        return len(self._nodes)

    @property
    def by_id(self) -> Mapping[str, CountyNode]:
        return self._by_id

    @property
    def counties(self) -> tuple[CountyNode, ...]:
        return tuple(node for node in self._nodes if node.is_county)

    @property
    def externals(self) -> tuple[CountyNode, ...]:
        return tuple(node for node in self._nodes if not node.is_county)

    def require(self, node_id: str) -> CountyNode:
        try:
            return self._by_id[node_id]
        except KeyError as error:
            raise KeyError(f"unknown node {node_id!r}") from error
