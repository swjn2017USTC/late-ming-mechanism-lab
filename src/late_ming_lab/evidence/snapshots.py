"""The source snapshot manifest: which bytes of a source this project holds, and on what terms.

The registry (`evidence/registry.py`) identifies a source and says whether it was checked. This
module records the *file* side of the same question, one record per acquired or pending snapshot:

```text
identity     which source it belongs to, what version, where it came from, in what format
rights       what the licence actually says, where that was read, and what may be redistributed
acquisition  how it was obtained, when, by what tool, how big it is, and its SHA-256
derivation   what may be published out of it, and what was published
verification what was opened to confirm the file is the thing it claims to be
```

Four rules are enforced here rather than documented only, because each of them is a way a
rights problem becomes invisible:

- **An acquired snapshot has a hash.** No `acquired: true` record without `sha256`, `bytes`,
  `acquired_utc` and a `local_path`.
- **Raw files never live in a tracked directory.** Every `local_path` is under
  ``data/raw/private/``, which `.gitignore` excludes; ``derived_output_rule`` says what may be
  committed instead, and ``derived_committed`` names the files that actually were.
- **A file we may not redistribute is never a committed file.** The record's own
  ``raw_publishable`` flag is derived from the licence, not asserted: only ``permitted`` and
  ``attribution-required`` can be published, and an invariant test refuses a committed path
  anywhere else.
- **An unknown licence is a finding.** ``rights.status: unknown`` requires the question that would
  settle it, so "we did not check" cannot be read as "there is no restriction".

Nothing here decides what enters the model: a snapshot is an input a later phase may read, and the
parameter cards and the ledger remain the only places a value or a claim is registered.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from late_ming_lab.evidence.grades import SOURCE_ID_PATTERN, ReadDepth

SNAPSHOT_SCHEMA_VERSION: Final[str] = "source-snapshot-v1"
SNAPSHOT_GLOB: Final[str] = "sources/snapshots/*.yaml"

#: Where raw snapshots live. Ignored by git; every record's ``local_path`` must sit under it.
RAW_ROOT: Final[str] = "data/raw/private"

HASH_PATTERN: Final[str] = r"^[0-9a-f]{64}$"


class RightsStatus(StrEnum):
    """What kind of permission the licence gives, in the licence's own words."""

    OPEN = "open"
    """Free to use and redistribute."""

    OPEN_ATTRIBUTION = "open-attribution"
    """Free to use and redistribute with attribution (Creative Commons, or equivalent)."""

    ACADEMIC_ONLY = "academic-only"
    """Free for non-commercial research and teaching, with redistribution withheld or gated."""

    RESTRICTED = "restricted"
    """Access requires a subscription, an account, or permission that has not been granted."""

    UNKNOWN = "unknown"
    """No statement of terms was found; the question that would settle it is recorded."""


class Redistribution(StrEnum):
    """Whether the bytes themselves may be published."""

    PERMITTED = "permitted"
    ATTRIBUTION_REQUIRED = "attribution-required"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"


class AcquisitionMethod(StrEnum):
    """How the file was, or would have to be, obtained."""

    HTTP = "http"
    """A plain unauthenticated download from a public URL."""

    HUMAN = "human"
    """Only a person may obtain it: a licence acceptance, an account, a library, an archive."""

    NONE = "none"
    """Not acquired and not planned; the record exists to describe a distribution path."""


class RightsTerms(BaseModel):
    """The licence, what it says, and where that was read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: RightsStatus
    redistribution: Redistribution
    statement: str = Field(
        min_length=1,
        max_length=1000,
        description="what the governing terms say, quoted or closely paraphrased",
    )
    basis: str = Field(
        min_length=1,
        max_length=512,
        description="the document or page the statement was read from",
    )
    checked_utc: date = Field(description="when the terms were read")
    unresolved_question: str = Field(
        default="",
        max_length=512,
        description="for an unknown or gated licence: the question that would settle it",
    )

    @model_validator(mode="after")
    def _unknown_rights_state_the_question(self) -> RightsTerms:
        if self.status is RightsStatus.UNKNOWN and not self.unresolved_question.strip():
            raise ValueError(
                "an unknown licence must record the question that would settle it, so that "
                "'not checked' cannot read as 'no restriction'"
            )
        if self.status is RightsStatus.RESTRICTED and not self.unresolved_question.strip():
            raise ValueError(
                "restricted access must record what the access depends on (unresolved_question)"
            )
        return self


class Acquisition(BaseModel):
    """How the snapshot was obtained, and the hash that identifies the bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: AcquisitionMethod
    acquired: bool
    fetch_url: str | None = Field(
        default=None,
        max_length=512,
        description=(
            "the URL a script may fetch, as distinct from the locator: a locator is a citation a "
            "reader can check, a fetch_url is the file endpoint a tool can download"
        ),
    )
    acquired_utc: date | None = None
    tool: str | None = Field(default=None, max_length=200)
    bytes: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=HASH_PATTERN)
    local_path: str | None = Field(default=None, max_length=512)
    human_note: str = Field(
        default="",
        max_length=512,
        description="for a human-only acquisition: what the person is being asked to obtain",
    )

    @model_validator(mode="after")
    def _acquisition_is_complete(self) -> Acquisition:
        if self.method is AcquisitionMethod.HTTP and not (self.fetch_url or "").startswith("http"):
            raise ValueError(
                f"an http acquisition needs a fetch_url starting with http; {self.fetch_url!r} "
                "is not one"
            )
        if self.acquired:
            missing = [
                name
                for name, value in (
                    ("sha256", self.sha256),
                    ("bytes", self.bytes),
                    ("acquired_utc", self.acquired_utc),
                    ("local_path", self.local_path),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    f"an acquired snapshot must record {', '.join(missing)}: a file without a "
                    "hash cannot be checked, and one without a path cannot be found"
                )
            if self.method is AcquisitionMethod.HUMAN:
                raise ValueError(
                    "a human-only acquisition cannot also be recorded as acquired by an agent"
                )
        else:
            if any(value is not None for value in (self.sha256, self.bytes, self.local_path)):
                raise ValueError("a snapshot that was not acquired carries no hash, size or path")
            if not self.human_note.strip():
                raise ValueError(
                    "a pending acquisition must say what is being asked for (human_note)"
                )
        return self


class SnapshotVerification(BaseModel):
    """What was opened to confirm the file is the thing the record says it is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    opened_utc: date
    what_confirmed: str = Field(min_length=1, max_length=1000)
    read_depth: ReadDepth = ReadDepth.IDENTITY_ONLY


class SnapshotRecord(BaseModel):
    """One file: its source, its licence, how it was acquired, and what may be done with it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=SOURCE_ID_PATTERN, max_length=128)
    source_id: str = Field(pattern=SOURCE_ID_PATTERN, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    version: str = Field(min_length=1, max_length=128)
    format: str = Field(min_length=1, max_length=64)
    locator: str = Field(min_length=1, max_length=512)
    rights: RightsTerms
    acquisition: Acquisition
    derived_output_rule: str = Field(
        min_length=1,
        max_length=1000,
        description="what derived from this file may be published, and what may not",
    )
    derived_committed: tuple[str, ...] = Field(
        default=(), description="repository paths of derived material that is published"
    )
    verification: SnapshotVerification
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _local_path_is_ignored(self) -> SnapshotRecord:
        path = self.acquisition.local_path
        if path is not None and not path.startswith(f"{RAW_ROOT}/"):
            raise ValueError(
                f"{self.id}: local_path must be under {RAW_ROOT}/, which git ignores; a raw "
                "snapshot is never a tracked file"
            )
        return self

    @property
    def raw_publishable(self) -> bool:
        """Whether the licence lets the bytes themselves be published."""
        return self.rights.redistribution in {
            Redistribution.PERMITTED,
            Redistribution.ATTRIBUTION_REQUIRED,
        }

    @property
    def acquired(self) -> bool:
        return self.acquisition.acquired

    @property
    def pending(self) -> bool:
        return not self.acquisition.acquired


class SnapshotManifest:
    """Every snapshot, indexed by id and linkable to the source registry."""

    def __init__(self, records: tuple[SnapshotRecord, ...], *, schema_version: str) -> None:
        if schema_version != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(
                f"snapshot schema {schema_version!r} is not {SNAPSHOT_SCHEMA_VERSION!r}"
            )
        ordered = tuple(sorted(records, key=lambda record: record.id))
        ids = [record.id for record in ordered]
        duplicates = sorted({record_id for record_id in ids if ids.count(record_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate snapshot ids: {', '.join(duplicates)}")
        self._records = ordered
        self._by_id = {record.id: record for record in ordered}
        self._schema_version = schema_version

    def __iter__(self) -> Iterator[SnapshotRecord]:
        return iter(self._records)

    def __len__(self) -> int:
        return len(self._records)

    @property
    def records(self) -> tuple[SnapshotRecord, ...]:
        return self._records

    @property
    def schema_version(self) -> str:
        return self._schema_version

    def require(self, snapshot_id: str) -> SnapshotRecord:
        try:
            return self._by_id[snapshot_id]
        except KeyError as error:
            raise KeyError(f"no recorded snapshot {snapshot_id!r}") from error

    def for_source(self, source_id: str) -> tuple[SnapshotRecord, ...]:
        return tuple(record for record in self._records if record.source_id == source_id)

    @property
    def acquired_records(self) -> tuple[SnapshotRecord, ...]:
        return tuple(record for record in self._records if record.acquired)

    @property
    def pending_records(self) -> tuple[SnapshotRecord, ...]:
        return tuple(record for record in self._records if record.pending)

    @property
    def local_only_records(self) -> tuple[SnapshotRecord, ...]:
        """Snapshots whose bytes may not be published, so only the record and rule are in git."""
        return tuple(record for record in self._records if not record.raw_publishable)

    def source_ids(self) -> frozenset[str]:
        return frozenset(record.source_id for record in self._records)

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self._records:
            counts[record.rights.status.value] = counts.get(record.rights.status.value, 0) + 1
        return counts


def load_snapshots(root: str | Path, *, glob: str = SNAPSHOT_GLOB) -> SnapshotManifest:
    """Read every snapshot file under ``root`` and return the merged, validated manifest."""
    directory = Path(root)
    files = sorted(directory.glob(glob))
    if not files:
        raise FileNotFoundError(f"no snapshot files matched {glob!r} under {directory}")
    records: list[SnapshotRecord] = []
    schema_versions: set[str] = set()
    for path in files:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "snapshots" not in payload:
            raise ValueError(f"{path}: snapshot files must hold a 'snapshots' list")
        schema_versions.add(str(payload.get("schema_version", "")))
        for raw in payload["snapshots"]:
            records.append(SnapshotRecord.model_validate(raw))
    if len(schema_versions) != 1:
        raise ValueError(f"snapshot files disagree on schema_version: {sorted(schema_versions)}")
    return SnapshotManifest(tuple(records), schema_version=schema_versions.pop())


def unregistered_sources(root: str | Path, manifest: SnapshotManifest) -> tuple[str, ...]:
    """Snapshot records whose ``source_id`` is not in the registry — a broken link, not a gap."""
    from late_ming_lab.evidence.registry import load_registry

    registry = load_registry(root)
    return tuple(
        sorted({record.source_id for record in manifest if not registry.has(record.source_id)})
    )
