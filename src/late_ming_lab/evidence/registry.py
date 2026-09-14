"""The source registry: bibliographic identity, access and grade for every source we cite.

One record per source, loaded from `sources/registry/*.yaml`. The registry is the only place a
source is *identified*; the evidence ledger (`evidence/ledger.py`) is where a source is *used*, and
parameter cards point back here by id. That split is what makes referential integrity checkable:
a card citing `brook-1998` fails validation unless the registry holds that id.

Layering, as `docs/epistemics/evidence-grades.md` requires:

```text
primary                    a source from the period, or a transcription of one
dataset                    measured or reconstructed data, with a stated method
modern_scholarship         later scholarship: monographs, articles, reference works
reference_work             encyclopaedias, chronologies, catalogues used for orientation only
```

Two access rules are structural, not advisory:

- **`access: institution` and `access: human-only` sources are never acquired by an agent.** The
  registry records the locator and the condition, and acquisition is a human act. There is no field
  for a local path to licensed material, because licensed material must not enter the repository.
- **A grade asserts what has actually been checked.** ``verified`` means the record was confirmed
  against a resolvable locator during this phase; ``unverified`` means it is recorded from memory or
  a secondary mention and still has to be confirmed — and an unverified record may not carry grade
  A or B, so the doubt travels with every claim that rests on it.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from late_ming_lab.evidence.grades import SOURCE_ID_PATTERN, EvidenceGrade, ReadDepth

REGISTRY_SCHEMA_VERSION: Final[str] = "source-registry-v2"
REGISTRY_GLOB: Final[str] = "sources/registry/*.yaml"

#: Evidence clusters the phase requires; every cluster must be served by the registry.
EVIDENCE_CLUSTERS: Final[tuple[str, ...]] = (
    "drought_climate",
    "famine",
    "agriculture",
    "population_migration",
    "grain_market_prices",
    "land_debt_elites",
    "taxation_levies",
    "relief",
    "military_finance",
    "rebellion_armed_groups",
)


class SourceLayer(StrEnum):
    """Which part of the evidence base a source belongs to.

    Never collapsed: a citation to a seventeenth-century memorial and a citation to a 2011
    monograph are different kinds of claim, and the ledger says which one it is using.
    """

    PRIMARY = "primary"
    DATASET = "dataset"
    MODERN_SCHOLARSHIP = "modern_scholarship"
    REFERENCE_WORK = "reference_work"


class AccessCondition(StrEnum):
    """How the source can be reached, and by whom."""

    OPEN = "open"
    OPEN_ACCESS_JOURNAL = "open-access-journal"
    LIBRARY = "library"
    INSTITUTION = "institution"
    HUMAN_ONLY = "human-only"


class Verification(StrEnum):
    """Whether this phase actually confirmed the record against a locator."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class SourceRecord(BaseModel):
    """One source, identified well enough that a reader can find it and check our use of it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=SOURCE_ID_PATTERN, max_length=128)
    layer: SourceLayer
    clusters: tuple[str, ...] = Field(min_length=1)
    title: str = Field(min_length=1, max_length=512)
    creators: tuple[str, ...] = ()
    year: int | None = Field(default=None, ge=-2000, le=2100)
    container: str | None = Field(
        default=None, max_length=512, description="journal, series, repository or publisher"
    )
    locator: str = Field(
        min_length=1,
        max_length=512,
        description="DOI, ISBN, stable URL, catalogue shelfmark or archival citation",
    )
    access: AccessCondition
    language: str = Field(min_length=2, max_length=64)
    grade: EvidenceGrade = Field(
        description="the strongest grade a claim may take when it rests on this source alone"
    )
    verification: Verification
    verified_against: str | None = Field(
        default=None,
        max_length=512,
        description="what was opened to confirm the record; required when verified",
    )
    read_depth: ReadDepth = Field(
        default=ReadDepth.IDENTITY_ONLY,
        description=(
            "how much of the source was read, as opposed to identified: a verified record may "
            "still be one nobody opened"
        ),
    )
    next_action: str = Field(
        default="",
        max_length=512,
        description=(
            "for a record that is not verified: what would verify or acquire it, and who has to "
            "do it. The acquisition queue is this field, not a separate list."
        ),
    )
    rights_note: str = Field(default="", max_length=512)
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _record_is_checkable(self) -> SourceRecord:
        unknown = [cluster for cluster in self.clusters if cluster not in EVIDENCE_CLUSTERS]
        if unknown:
            raise ValueError(f"{self.id}: unknown evidence cluster(s) {', '.join(unknown)}")
        if self.verification is Verification.VERIFIED and not self.verified_against:
            raise ValueError(
                f"{self.id}: a verified record must say what was opened to verify it "
                "(verified_against)"
            )
        if self.verification is Verification.UNVERIFIED:
            if self.read_depth is not ReadDepth.IDENTITY_ONLY:
                raise ValueError(
                    f"{self.id}: an unverified record cannot have read its own content; "
                    "read_depth must be identity-only"
                )
            if not self.next_action.strip():
                raise ValueError(
                    f"{self.id}: an unverified record must say what would verify or acquire it "
                    "(next_action), so the queue is machine-readable rather than a paragraph"
                )
        if self.verification is Verification.UNVERIFIED and self.grade in {
            EvidenceGrade.A,
            EvidenceGrade.B,
        }:
            raise ValueError(
                f"{self.id}: an unverified record may not carry grade {self.grade.value}; "
                "a claim resting on it is at best C or D"
            )
        if (
            self.access in {AccessCondition.INSTITUTION, AccessCondition.HUMAN_ONLY}
            and not self.rights_note
        ):
            raise ValueError(
                f"{self.id}: restricted access must state the condition (rights_note), so "
                "that acquisition stays a recorded human act"
            )
        return self

    @property
    def acquisition_is_human_only(self) -> bool:
        return self.access in {AccessCondition.INSTITUTION, AccessCondition.HUMAN_ONLY}


class SourceRegistry:
    """Every registered source, indexed by id."""

    def __init__(self, records: tuple[SourceRecord, ...], *, schema_version: str) -> None:
        if schema_version != REGISTRY_SCHEMA_VERSION:
            raise ValueError(
                f"registry schema {schema_version!r} is not {REGISTRY_SCHEMA_VERSION!r}"
            )
        ordered = tuple(sorted(records, key=lambda record: record.id))
        ids = [record.id for record in ordered]
        duplicates = sorted({source_id for source_id in ids if ids.count(source_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate source ids: {', '.join(duplicates)}")
        self._records = ordered
        self._by_id = {record.id: record for record in ordered}
        self._schema_version = schema_version

    def __iter__(self) -> Iterator[SourceRecord]:
        return iter(self._records)

    def __len__(self) -> int:
        return len(self._records)

    @property
    def records(self) -> tuple[SourceRecord, ...]:
        return self._records

    @property
    def schema_version(self) -> str:
        return self._schema_version

    def require(self, source_id: str) -> SourceRecord:
        try:
            return self._by_id[source_id]
        except KeyError as error:
            raise KeyError(f"no registered source {source_id!r}") from error

    def has(self, source_id: str) -> bool:
        return source_id in self._by_id

    def by_layer(self, layer: SourceLayer) -> tuple[SourceRecord, ...]:
        return tuple(record for record in self._records if record.layer is layer)

    def by_cluster(self, cluster: str) -> tuple[SourceRecord, ...]:
        if cluster not in EVIDENCE_CLUSTERS:
            raise KeyError(f"unknown evidence cluster {cluster!r}")
        return tuple(record for record in self._records if cluster in record.clusters)

    def clusters_without_sources(self) -> tuple[str, ...]:
        return tuple(cluster for cluster in EVIDENCE_CLUSTERS if not self.by_cluster(cluster))

    @property
    def human_only_ids(self) -> tuple[str, ...]:
        return tuple(record.id for record in self._records if record.acquisition_is_human_only)


def load_registry(root: str | Path, *, glob: str = REGISTRY_GLOB) -> SourceRegistry:
    """Read every registry file under ``root`` and return the merged, validated registry."""
    directory = Path(root)
    files = sorted(directory.glob(glob))
    if not files:
        raise FileNotFoundError(f"no source registry files matched {glob!r} under {directory}")
    records: list[SourceRecord] = []
    schema_versions: set[str] = set()
    for path in files:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "sources" not in payload:
            raise ValueError(f"{path}: registry files must hold a 'sources' list")
        schema_versions.add(str(payload.get("schema_version", "")))
        for raw in payload["sources"]:
            records.append(SourceRecord.model_validate(raw))
    if len(schema_versions) != 1:
        raise ValueError(f"registry files disagree on schema_version: {sorted(schema_versions)}")
    return SourceRegistry(tuple(records), schema_version=schema_versions.pop())
