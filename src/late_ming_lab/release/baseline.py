"""The V1 baseline freeze: what ``v0.1.0-rc1`` is, by content, and how to prove it still is that.

V2 builds on the V1 release candidate instead of replacing it (``docs/OMP_UPGRADE_PLAN_V2.md``
section 4), so V2-P00 has to answer two questions a tag alone cannot: *exactly which bytes* are the
baseline, and *which commit produced each artifact*. Four decisions carry most of the weight.

- **Frozen tracked content comes from git, not from the working tree.** Every frozen file is read
  as the blob it is in the baseline commit, so the manifest records the release rather than whatever
  a working tree happened to hold. The build refuses to freeze a tree in which a frozen file has
  been modified, so a baseline cannot be taken over uncommitted work.
- **An artifact's generation commit is read from the artifact's own manifest.** V1's batches
  recorded ``git_sha`` when they ran, and several ran at commits older than the release (seven of
  the nine from a dirty tree). Writing the current HEAD beside those files would be a provenance
  lie, so each artifact carries the commit it recorded, where that came from, and whether the tree
  was dirty; the manifest never substitutes HEAD for any of it. An artifact that recorded nothing
  says ``unrecorded`` rather than borrowing the release's identity.
- **Additions and tracked edits are reported; rewrites of the release are not.** V2 adds files, and
  V2 also evolves V1 code and documents - that is what a working tree is for. So a frozen *tracked*
  file that changed since the baseline is reported as ``modified`` and does not fail the check,
  while these do: a frozen file that vanished, any change inside a V1 artifact directory, and a
  manifest that no longer describes the commit it names. V1's artifacts and the release commit must
  not move, and a later phase that changes V1 code must say so in its own report.
- **Hashing is over bytes.** Artifacts include Parquet, so the digests here are SHA-256 of raw file
  bytes rather than of a decoded string.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from late_ming_lab import __version__
from late_ming_lab.core.hashing import canonical_json, hash_text

BASELINE_SCHEMA_VERSION: Final[str] = "baseline-v1"
BASELINE_PATH: Final[str] = "docs/v2/baseline-v1.json"
GIT_TIMEOUT_SECONDS: Final[float] = 60.0
HASH_PATTERN: Final[str] = r"^[0-9a-f]{64}$"
HEAD_PATTERN: Final[str] = r"^[0-9a-f]{40}$"

#: Where frozen tracked files live, by group. A tracked file outside these roots fails the build
#: rather than entering the manifest with no group.
GROUP_ROOTS: Final[tuple[tuple[str, str], ...]] = (
    ("src/", "code"),
    ("tests/", "tests"),
    ("docs/", "docs"),
    ("data/", "data"),
    ("sources/", "sources"),
    (".omp/", "config"),
    ("outputs/", "report"),
)

#: Tracked files whose group is not decided by their directory.
GROUP_FILES: Final[dict[str, str]] = {
    "pyproject.toml": "config",
    "uv.lock": "config",
    ".python-version": "config",
    ".gitignore": "config",
    ".env.example": "config",
    "README.md": "readme",
}

#: The artifact families V1 wrote outside git: each immediate subdirectory is one artifact.
ARTIFACT_ROOTS: Final[tuple[tuple[str, str], ...]] = (
    ("outputs/runs", "run"),
    ("outputs/experiments", "experiment"),
    ("outputs/calibration", "calibration"),
    ("outputs/institutional", "institutional"),
)

#: Loose artifact files with no manifest of their own: one record for the directory.
ARTIFACT_FILE_ROOTS: Final[tuple[tuple[str, str], ...]] = (("outputs/analysis", "analysis"),)

#: Manifest keys copied into the record when a batch declares them; the rest stay in the artifact.
MANIFEST_FACT_KEYS: Final[tuple[str, ...]] = (
    "run_count",
    "jobs",
    "replicates",
    "grid_replicates",
    "ticks",
    "warmup_ticks",
    "base_seed",
    "seed",
    "root_seed",
    "chains",
    "decisions",
    "refusals",
    "tick_count",
    "labels",
    "policies",
    "arm_status",
)

#: Where a generation commit came from. ``unrecorded`` is a finding, not a gap to fill with HEAD.
CommitSource = Literal["artifact-manifest", "unrecorded"]


class BaselineError(RuntimeError):
    """Raised when a baseline cannot be taken, read, or checked."""


def sha256_bytes(payload: bytes) -> str:
    """SHA-256 hex digest of raw file bytes.

    ``core.hashing.hash_text`` hashes a string; artifacts include Parquet, so the freeze hashes
    bytes
    directly rather than pushing binary through a UTF-8 round trip that cannot represent it.
    """
    return hashlib.sha256(payload).hexdigest()


class ArtifactFile(BaseModel):
    """One file inside a frozen artifact directory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=HASH_PATTERN)
    size_bytes: int = Field(ge=0)


class TableRecord(BaseModel):
    """One Parquet table of an artifact: its name, its row count and its hash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    rows: int = Field(ge=0)
    sha256: str = Field(pattern=HASH_PATTERN)


class FileRecord(BaseModel):
    """A frozen tracked file, as of the baseline commit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    group: str = Field(min_length=1)
    sha256: str = Field(pattern=HASH_PATTERN)
    size_bytes: int = Field(ge=0)
    last_commit: str | None = Field(default=None, pattern=HEAD_PATTERN)


class ArtifactRecord(BaseModel):
    """A V1 artifact directory: its content, its tables, and the commit it was generated at."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    directory: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    label: str | None = None
    schema_version: str | None = None
    generated_at_utc: str | None = None
    generation_commit: str | None = Field(default=None, pattern=HEAD_PATTERN)
    generation_commit_source: CommitSource
    git_dirty_at_generation: bool | None = None
    generation_commit_ancestor_of_freeze: bool | None = None
    file_count: int = Field(ge=0)
    tree_sha256: str = Field(pattern=HASH_PATTERN)
    files: tuple[ArtifactFile, ...] = ()
    tables: tuple[TableRecord, ...] = ()
    facts: dict[str, str] = Field(default_factory=dict)


class Baseline(BaseModel):
    """The frozen release candidate: its commit, its files, and every artifact it produced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["baseline-v1"] = "baseline-v1"
    baseline_id: str = Field(min_length=1)
    commit: str = Field(pattern=HEAD_PATTERN)
    tag: str | None = None
    branch: str | None = None
    engine_version: str
    python_version: str
    generated_at_utc: str
    tracked_file_count: int = Field(ge=0)
    artifact_count: int = Field(ge=0)
    artifact_file_count: int = Field(ge=0)
    files: tuple[FileRecord, ...] = ()
    artifacts: tuple[ArtifactRecord, ...] = ()
    content_digest: str = Field(pattern=HASH_PATTERN)

    def group_counts(self) -> dict[str, int]:
        """How many frozen tracked files each group holds."""
        counts: dict[str, int] = {}
        for record in self.files:
            counts[record.group] = counts.get(record.group, 0) + 1
        return counts

    def artifact(self, directory: str) -> ArtifactRecord:
        for record in self.artifacts:
            if record.directory == directory:
                return record
        raise KeyError(directory)


class Drift(BaseModel):
    """One difference between the freeze and what is there now."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    kind: Literal["modified", "missing", "added"]
    expected: str | None = None
    actual: str | None = None
    section: Literal["tracked", "artifact", "history"] = "tracked"


class GenerationCommit(BaseModel):
    """Where one artifact's generation commit stands relative to the commit being verified."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    directory: str = Field(min_length=1)
    generation_commit: str | None = None
    source: CommitSource
    dirty_at_generation: bool | None = None
    ancestor_of_head: bool | None = None


class BaselineVerification(BaseModel):
    """The result of re-hashing a frozen baseline against a working tree and against git history."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline_id: str = Field(min_length=1)
    commit: str = Field(pattern=HEAD_PATTERN)
    head: str | None = Field(default=None, pattern=HEAD_PATTERN)
    ok: bool
    tracked: tuple[Drift, ...] = ()
    artifacts: tuple[Drift, ...] = ()
    history: tuple[Drift, ...] = ()
    generated_at: tuple[GenerationCommit, ...] = ()
    notes: tuple[str, ...] = ()

    def failures(self) -> tuple[Drift, ...]:
        """What fails the check: history that does not hash, or a frozen release item that moved.

        A *tracked* file is the working tree V2 evolves, so neither an addition nor an edit to one
        fails the check — both are still reported, as ``additions()`` and as ``modified()``. What
        fails is a frozen tracked file that vanished, any drift inside a V1 artifact directory, and
        a manifest that no longer describes the commit it names.
        """
        return tuple(
            drift
            for drift in (*self.history, *self.tracked, *self.artifacts)
            if not (drift.section == "tracked" and drift.kind in {"added", "modified"})
        )

    def additions(self) -> tuple[Drift, ...]:
        """Files that did not exist in the baseline; V2 adds these by design."""
        return tuple(drift for drift in self.tracked if drift.kind == "added")

    def modified(self) -> tuple[Drift, ...]:
        """Frozen tracked files that changed since the baseline: reported, never a pass."""
        return tuple(drift for drift in self.tracked if drift.kind == "modified")


def group_for(path: str) -> str:
    """The declared group of a frozen tracked file; anything else is an error, not a guess."""
    if path in GROUP_FILES:
        return GROUP_FILES[path]
    for prefix, group in GROUP_ROOTS:
        if path.startswith(prefix):
            return group
    raise BaselineError(f"{path}: no declared group; add it to GROUP_ROOTS or GROUP_FILES")


def tracked_files(root: Path, commit: str) -> tuple[str, ...]:
    """Every path tracked at ``commit``, in sorted order."""
    listing = _git(root, "ls-tree", "-r", "--name-only", "-z", commit)
    if listing is None:
        raise BaselineError(f"cannot list the tree at {commit}; is {root} a git repository?")
    return tuple(sorted(path for path in listing.split("\x00") if path))


def blob_contents(root: Path, commit: str, paths: Sequence[str]) -> dict[str, bytes]:
    """The bytes each path has at ``commit``, read from the object store in one round trip."""
    if not paths:
        return {}
    request = "".join(f"{commit}:{path}\n" for path in paths).encode("utf-8")
    completed = _run(root, ["cat-file", "--batch"], data=request)
    if completed is None:
        raise BaselineError(f"cannot read blobs at {commit}")
    payload = completed.stdout
    contents: dict[str, bytes] = {}
    cursor = 0
    for path in paths:
        header_end = payload.find(b"\n", cursor)
        if header_end < 0:
            raise BaselineError(f"truncated cat-file output at {path}")
        header = payload[cursor:header_end].split()
        if len(header) < 3 or header[1] == b"missing":
            raise BaselineError(f"{commit}:{path} is not in the object store")
        size = int(header[2])
        start = header_end + 1
        contents[path] = payload[start : start + size]
        cursor = start + size + 1
    return contents


def last_commits(root: Path) -> dict[str, str]:
    """The newest commit that touched each tracked path, for files that carry no manifest."""
    log = _git(root, "log", "--format=\x1e%H", "--name-only", "--no-renames")
    if log is None:
        return {}
    commits: dict[str, str] = {}
    revision: str | None = None
    for line in log.splitlines():
        if line.startswith("\x1e"):
            revision = line[1:].strip()
        elif line and revision is not None:
            commits.setdefault(line, revision)
    return commits


def is_ancestor(root: Path, earlier: str, later: str) -> bool | None:
    """Whether ``earlier`` is an ancestor of ``later``; ``None`` when git cannot say."""
    completed = _run(root, ["merge-base", "--is-ancestor", earlier, later])
    if completed is None:
        return None
    return completed.returncode == 0


def scan_artifacts(root: Path, *, freeze_commit: str | None = None) -> tuple[ArtifactRecord, ...]:
    """Hash every V1 artifact directory, and read the generation commit it recorded itself."""
    records: list[ArtifactRecord] = []
    for relative, kind in ARTIFACT_ROOTS:
        directory = root / relative
        if not directory.is_dir():
            continue
        for child in sorted(directory.iterdir()):
            if child.is_dir():
                records.append(_artifact_record(root, child, kind, freeze_commit))
    for relative, kind in ARTIFACT_FILE_ROOTS:
        directory = root / relative
        if directory.is_dir():
            records.append(_artifact_record(root, directory, kind, freeze_commit, flat=True))
    return tuple(records)


def build_baseline(
    root: str | Path,
    *,
    commit: str | None = None,
    generated_at: datetime | None = None,
) -> Baseline:
    """Freeze ``commit`` (default: HEAD) and the artifacts on disk into a baseline record."""
    repository = Path(root).resolve()
    freeze = commit or _head(repository)
    if freeze is None:
        raise BaselineError(f"{repository}: no commit to freeze")
    paths = tracked_files(repository, freeze)
    contents = blob_contents(repository, freeze, paths)
    history = last_commits(repository)
    modified = sorted(
        path
        for path, blob in contents.items()
        if not (repository / path).is_file() or (repository / path).read_bytes() != blob
    )
    if modified:
        raise BaselineError(
            "refusing to freeze a modified tree; these frozen files differ from"
            f"{freeze[:12]}: {', '.join(modified)}"
        )
    files = tuple(
        FileRecord(
            path=path,
            group=group_for(path),
            sha256=sha256_bytes(contents[path]),
            size_bytes=len(contents[path]),
            last_commit=history.get(path),
        )
        for path in paths
    )
    artifacts = scan_artifacts(repository, freeze_commit=freeze)
    tag = _first_line(_git(repository, "tag", "--points-at", freeze))
    return Baseline(
        baseline_id=tag or f"commit-{freeze[:12]}",
        commit=freeze,
        tag=tag,
        branch=_first_line(_git(repository, "rev-parse", "--abbrev-ref", "HEAD")),
        engine_version=__version__,
        python_version=_python_version(),
        generated_at_utc=(generated_at or datetime.now(UTC)).isoformat(),
        tracked_file_count=len(files),
        artifact_count=len(artifacts),
        artifact_file_count=sum(record.file_count for record in artifacts),
        files=files,
        artifacts=artifacts,
        content_digest=content_digest(files, artifacts),
    )


def content_digest(files: Sequence[FileRecord], artifacts: Sequence[ArtifactRecord]) -> str:
    """The identity of a baseline: every frozen path and hash, and nothing that is a clock."""
    payload = {
        "files": [[record.path, record.sha256] for record in files],
        "artifacts": [[record.directory, record.tree_sha256] for record in artifacts],
    }
    return hash_text(canonical_json(payload))


def write_baseline(root: str | Path, baseline: Baseline, path: str | Path | None = None) -> Path:
    """Write the baseline as pretty, key-sorted JSON, and return where it went."""
    target = Path(root) / (path or BASELINE_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_baseline(baseline), encoding="utf-8")
    return target


def render_baseline(baseline: Baseline) -> str:
    """The exact text a baseline file holds, so two builds can be compared as text."""
    payload = baseline.model_dump(mode="json")
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def load_baseline(path: str | Path) -> Baseline:
    """Read a written baseline back."""
    return Baseline.model_validate_json(Path(path).read_text(encoding="utf-8"))


def verify_baseline(root: str | Path, baseline: Baseline) -> BaselineVerification:
    """Re-hash the working tree and the frozen commit against the baseline, and report "
    "differences."""
    repository = Path(root).resolve()
    history = _history_drift(repository, baseline)
    tracked = list(_tracked_drift(repository, baseline))
    artifacts = list(_artifact_drift(repository, baseline))
    head = _head(repository)
    notes: list[str] = []
    if history is None:
        notes.append(
            f"the commit {baseline.commit[:12]} could not be re-read from git, so the manifest's "
            "description of it is unverified"
        )
    additions = _additions(repository, baseline)
    tracked.extend(Drift(path=path, kind="added", section="tracked") for path in additions)
    if additions:
        notes.append(f"{len(additions)} tracked file(s) did not exist in the baseline: additions")
    generated = tuple(
        GenerationCommit(
            directory=record.directory,
            generation_commit=record.generation_commit,
            source=record.generation_commit_source,
            dirty_at_generation=record.git_dirty_at_generation,
            ancestor_of_head=(
                None
                if record.generation_commit is None or head is None
                else is_ancestor(repository, record.generation_commit, head)
            ),
        )
        for record in baseline.artifacts
    )
    for entry in generated:
        if entry.generation_commit is None:
            notes.append(f"{entry.directory}: the artifact records no generation commit")
        elif entry.ancestor_of_head is False:
            notes.append(
                f"{entry.directory}: generated at {entry.generation_commit[:12]}, which is not an "
                "ancestor of HEAD"
            )
        elif entry.dirty_at_generation:
            notes.append(
                f"{entry.directory}: generated at {entry.generation_commit[:12]} from a dirty tree"
            )
    return BaselineVerification(
        baseline_id=baseline.baseline_id,
        commit=baseline.commit,
        head=head,
        ok=history is not None and not _failures(history, tracked, artifacts),
        tracked=tuple(tracked),
        artifacts=tuple(artifacts),
        history=() if history is None else history,
        generated_at=generated,
        notes=tuple(notes),
    )


def _failures(
    history: tuple[Drift, ...] | None, tracked: Sequence[Drift], artifacts: Sequence[Drift]
) -> tuple[Drift, ...]:
    """Everything that fails the check: unhashing history, or a frozen release item that moved.

    Tracked additions and tracked edits are reported separately and do not fail it; a vanished
    frozen file, any drift inside an artifact directory, and a manifest that no longer describes its
    commit all do.
    """
    if history is None:
        return tuple()
    candidates = (*history, *tracked, *artifacts)
    return tuple(
        drift
        for drift in candidates
        if not (drift.section == "tracked" and drift.kind in {"added", "modified"})
    )


def _history_drift(repository: Path, baseline: Baseline) -> tuple[Drift, ...] | None:
    """Whether the manifest still describes the commit it names, re-read from git.

    ``None`` means git could not answer at all, which the caller reports rather than swallowing.
    """
    try:
        contents = blob_contents(
            repository, baseline.commit, [record.path for record in baseline.files]
        )
    except BaselineError:
        return None
    drift: list[Drift] = []
    for record in baseline.files:
        payload = contents.get(record.path)
        digest = None if payload is None else sha256_bytes(payload)
        if digest != record.sha256:
            drift.append(
                Drift(
                    path=record.path,
                    kind="modified",
                    expected=record.sha256,
                    actual=digest,
                    section="history",
                )
            )
    return tuple(drift)


def _tracked_drift(repository: Path, baseline: Baseline) -> Iterable[Drift]:
    for record in baseline.files:
        path = repository / record.path
        if not path.is_file():
            yield Drift(path=record.path, kind="missing", expected=record.sha256)
            continue
        actual = sha256_bytes(path.read_bytes())
        if actual != record.sha256:
            yield Drift(path=record.path, kind="modified", expected=record.sha256, actual=actual)


def _artifact_drift(repository: Path, baseline: Baseline) -> Iterable[Drift]:
    for record in baseline.artifacts:
        directory = repository / record.directory
        frozen = {entry.path: entry.sha256 for entry in record.files}
        present = _present_files(directory)
        for relative, digest in sorted(frozen.items()):
            joined = f"{record.directory}/{relative}"
            if relative not in present:
                yield Drift(path=joined, kind="missing", expected=digest, section="artifact")
            elif present[relative] != digest:
                yield Drift(
                    path=joined,
                    kind="modified",
                    expected=digest,
                    actual=present[relative],
                    section="artifact",
                )
        for relative in sorted(set(present) - set(frozen)):
            yield Drift(path=f"{record.directory}/{relative}", kind="added", section="artifact")


def _additions(repository: Path, baseline: Baseline) -> tuple[str, ...]:
    current = _git(repository, "ls-tree", "-r", "--name-only", "-z", "HEAD")
    if current is None:
        return ()
    frozen = {record.path for record in baseline.files}
    return tuple(sorted(path for path in current.split("\x00") if path and path not in frozen))


def _present_files(directory: Path) -> dict[str, str]:
    if not directory.is_dir():
        return {}
    return {
        str(path.relative_to(directory)): sha256_bytes(path.read_bytes())
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _artifact_record(
    root: Path,
    directory: Path,
    kind: str,
    freeze_commit: str | None,
    *,
    flat: bool = False,
) -> ArtifactRecord:
    paths = sorted(path for path in directory.rglob("*") if path.is_file())
    entries = tuple(
        ArtifactFile(
            path=str(path.relative_to(directory)),
            sha256=sha256_bytes(path.read_bytes()),
            size_bytes=path.stat().st_size,
        )
        for path in paths
    )
    manifest = _read_manifest(None if flat else directory / "manifest.json")
    recorded = manifest.get("git_sha")
    commit = recorded if isinstance(recorded, str) and len(recorded) == 40 else None
    source: CommitSource = "artifact-manifest" if commit else "unrecorded"
    dirty = manifest.get("git_dirty")
    return ArtifactRecord(
        directory=str(directory.relative_to(root)),
        kind=kind,
        label=_label(manifest),
        schema_version=_string(manifest.get("schema_version")),
        generated_at_utc=_string(manifest.get("generated_at_utc") or manifest.get("created_at")),
        generation_commit=commit,
        generation_commit_source=source,
        git_dirty_at_generation=dirty if isinstance(dirty, bool) else None,
        generation_commit_ancestor_of_freeze=(
            None
            if commit is None or freeze_commit is None
            else is_ancestor(root, commit, freeze_commit)
        ),
        file_count=len(entries),
        tree_sha256=hash_text(canonical_json([[entry.path, entry.sha256] for entry in entries])),
        files=entries,
        tables=tuple(_table_record(path, directory) for path in paths if path.suffix == ".parquet"),
        facts=_facts(manifest),
    )


def _table_record(path: Path, directory: Path) -> TableRecord:
    return TableRecord(
        name=str(path.relative_to(directory)),
        rows=int(pl.scan_parquet(path).select(pl.len()).collect().item()),
        sha256=sha256_bytes(path.read_bytes()),
    )


def _facts(manifest: dict[str, Any]) -> dict[str, str]:
    """The declared facts a manifest carries, as strings; anything else stays in the artifact.

    A list of scalars becomes a comma-joined string (the arm labels, the policy names), the one
    nested shape the batches use - a mapping of arm name to a record carrying ``status`` - becomes
    ``name=status`` pairs, and the design record keeps its ``kind``, because whether a batch is an
    ablation set, a Morris screen or a Sobol design is what its sample size means.
    """
    facts: dict[str, str] = {}
    for key in MANIFEST_FACT_KEYS:
        rendered = _fact(manifest.get(key))
        if rendered is not None:
            facts[key] = rendered
    design = manifest.get("design")
    if isinstance(design, dict) and isinstance(design.get("kind"), str):
        facts["design_kind"] = design["kind"]
        if isinstance(design.get("replicates"), int):
            facts["design_replicates"] = str(design["replicates"])
    return facts


def _fact(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, str)):
        return str(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return ",".join(value)
    if isinstance(value, dict):
        pairs = [
            f"{name}={record['status']}"
            for name, record in value.items()
            if isinstance(record, dict) and isinstance(record.get("status"), str)
        ]
        return ";".join(pairs) if pairs else None
    return None


def _label(manifest: dict[str, Any]) -> str | None:
    for key in ("label", "run_id", "batch_id", "policy_name"):
        value = manifest.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _read_manifest(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise BaselineError(f"{path}: manifest is not JSON") from error
    return payload if isinstance(payload, dict) else {}


def _head(repository: Path) -> str | None:
    return _first_line(_git(repository, "rev-parse", "HEAD"))


def _first_line(text: str | None) -> str | None:
    if text is None:
        return None
    stripped = text.strip()
    return stripped.splitlines()[0] if stripped else None


def _python_version() -> str:
    import platform

    return platform.python_version()


def _git(root: Path, *args: str) -> str | None:
    completed = _run(root, list(args))
    if completed is None or completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", errors="surrogateescape")


def _run(
    root: Path, args: Sequence[str], *, data: bytes | None = None
) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            input=data,
            capture_output=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
