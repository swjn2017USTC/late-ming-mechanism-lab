"""The V2-P01 invariants: a snapshot has a hash, a licence and a rule, or it is not a snapshot.

These tests defend the properties that keep a rights problem visible: an acquired file always has a
hash and an ignored path; a file we may not redistribute is never a committed file; an unknown
licence always carries the question that would settle it; every snapshot's source is registered; and
a file that is present on disk hashes to what the manifest says. They also defend the acquisition
queue as data rather than prose - every unverified record says what would verify it.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from late_ming_lab.evidence.grades import ReadDepth
from late_ming_lab.evidence.registry import Verification, load_registry
from late_ming_lab.evidence.snapshots import (
    RAW_ROOT,
    Acquisition,
    AcquisitionMethod,
    Redistribution,
    RightsStatus,
    SnapshotManifest,
    SnapshotRecord,
    SnapshotVerification,
    load_snapshots,
    unregistered_sources,
)

ROOT = Path(__file__).resolve().parents[2]
DIGEST = "0" * 64


def _record(**overrides: Any) -> dict[str, Any]:
    """A minimal valid record, so a test can break exactly one field."""
    payload: dict[str, Any] = {
        "id": "example-snapshot",
        "source_id": "chgis-v6",
        "title": "An example",
        "version": "1",
        "format": "text",
        "locator": "https://example.invalid/file",
        "rights": {
            "status": "open",
            "redistribution": "permitted",
            "statement": "free to use",
            "basis": "the landing page",
            "checked_utc": "2026-09-14",
        },
        "acquisition": {
            "method": "http",
            "acquired": True,
            "fetch_url": "https://example.invalid/file.txt",
            "acquired_utc": "2026-09-14",
            "tool": "curl",
            "bytes": 12,
            "sha256": DIGEST,
            "local_path": f"{RAW_ROOT}/example/file.txt",
        },
        "derived_output_rule": "derived tables may be published with citation",
        "verification": {
            "opened_utc": "2026-09-14",
            "what_confirmed": "the file downloaded and matched the listing",
            "read_depth": "identity-only",
        },
    }
    payload.update(overrides)
    return payload


def test_an_acquired_snapshot_must_carry_its_hash_and_path() -> None:
    SnapshotRecord.model_validate(_record())
    for field in ("sha256", "bytes", "acquired_utc", "local_path"):
        acquisition = dict(_record()["acquisition"])
        acquisition[field] = None
        with pytest.raises(ValidationError, match=field):
            SnapshotRecord.model_validate(_record(acquisition=acquisition))


def test_a_pending_snapshot_says_what_it_is_waiting_for() -> None:
    pending = {
        "method": "human",
        "acquired": False,
        "human_note": "a person asks the archive for the register",
    }
    SnapshotRecord.model_validate(_record(acquisition=pending))
    with pytest.raises(ValidationError, match="human_note"):
        SnapshotRecord.model_validate(_record(acquisition={"method": "human", "acquired": False}))


def test_a_raw_file_never_lives_outside_the_ignored_tree() -> None:
    with pytest.raises(ValidationError, match="local_path must be under"):
        SnapshotRecord.model_validate(
            _record(
                acquisition={
                    "method": "http",
                    "acquired": True,
                    "fetch_url": "https://example.invalid/file.txt",
                    "acquired_utc": "2026-09-14",
                    "bytes": 1,
                    "sha256": DIGEST,
                    "local_path": "data/raw/public/example.txt",
                }
            )
        )


def test_a_human_only_acquisition_is_never_recorded_as_acquired() -> None:
    with pytest.raises(ValidationError, match="human-only acquisition"):
        SnapshotRecord.model_validate(
            _record(
                acquisition={
                    "method": "human",
                    "acquired": True,
                    "acquired_utc": "2026-09-14",
                    "bytes": 1,
                    "sha256": DIGEST,
                    "local_path": f"{RAW_ROOT}/example/file.txt",
                }
            )
        )


def test_an_unknown_licence_must_state_the_question() -> None:
    with pytest.raises(ValidationError, match="unknown licence"):
        SnapshotRecord.model_validate(
            _record(
                rights={
                    "status": "unknown",
                    "redistribution": "unknown",
                    "statement": "no terms found",
                    "basis": "the landing page",
                    "checked_utc": "2026-09-14",
                }
            )
        )


def test_only_a_licence_that_permits_it_makes_a_snapshot_publishable() -> None:
    forbidden = SnapshotRecord.model_validate(
        _record(
            rights={
                "status": "academic-only",
                "redistribution": "prohibited",
                "statement": "no redistribution",
                "basis": "the EULA",
                "checked_utc": "2026-09-14",
            }
        )
    )
    assert not forbidden.raw_publishable
    permissive = SnapshotRecord.model_validate(_record())
    assert permissive.raw_publishable


def test_the_manifest_refuses_a_duplicate_id() -> None:
    record = SnapshotRecord.model_validate(_record())
    with pytest.raises(ValueError, match="duplicate snapshot ids"):
        SnapshotManifest((record, record), schema_version="source-snapshot-v1")
    with pytest.raises(ValueError, match="not 'source-snapshot-v1'"):
        SnapshotManifest((record,), schema_version="source-snapshot-v2")


def test_every_snapshot_names_a_registered_source() -> None:
    manifest = load_snapshots(ROOT)
    assert len(manifest) > 0
    assert unregistered_sources(ROOT, manifest) == ()


def test_every_acquired_snapshot_that_is_present_hashes_to_its_record() -> None:
    manifest = load_snapshots(ROOT)
    checked = 0
    for record in manifest.acquired_records:
        path = ROOT / str(record.acquisition.local_path)
        if not path.is_file():
            continue
        checked += 1
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == record.acquisition.sha256, record.id
        assert path.stat().st_size == record.acquisition.bytes, record.id
    assert checked == len(manifest.acquired_records) or checked == 0, (
        "a snapshot is either present and checked, or absent because raw files are not tracked"
    )


def test_no_raw_snapshot_is_tracked_by_git() -> None:
    if not (ROOT / ".git").exists():
        pytest.skip("needs a git checkout to ask what is tracked")
    tracked = subprocess.run(
        ["git", "ls-files", RAW_ROOT],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert tracked == "", f"raw snapshots must never be tracked: {tracked}"


def test_the_manifest_is_consistent_with_the_registry() -> None:
    """Every licence finding is one of the declared statuses, and every source id resolves."""
    manifest = load_snapshots(ROOT)
    registry = load_registry(ROOT)
    for record in manifest:
        assert record.source_id in {source.id for source in registry}
        assert record.rights.status in set(RightsStatus)
        assert record.rights.redistribution in set(Redistribution)
        assert isinstance(record.acquisition, Acquisition)
        assert record.acquisition.method in set(AcquisitionMethod)
        assert isinstance(record.verification, SnapshotVerification)


def test_the_acquisition_queue_is_machine_readable() -> None:
    registry = load_registry(ROOT)
    unverified = [source for source in registry if source.verification is Verification.UNVERIFIED]
    assert unverified, "the phase found none unverified, which would be a claim to justify"
    for source in unverified:
        assert source.next_action.strip(), source.id
        assert source.read_depth is ReadDepth.IDENTITY_ONLY, source.id
        assert source.access.value in {
            "open",
            "open-access-journal",
            "library",
            "institution",
            "human-only",
        }


def test_a_verified_record_may_still_be_one_nobody_read() -> None:
    """The distinction the phase exists to keep: verified identity is not a read source."""
    registry = load_registry(ROOT)
    verified_but_unread = [
        source
        for source in registry
        if source.verification is Verification.VERIFIED
        and source.read_depth is ReadDepth.IDENTITY_ONLY
    ]
    assert verified_but_unread, "if nothing is identity-only, the field is not measuring anything"
    read = [source for source in registry if source.read_depth is ReadDepth.FULL_TEXT]
    assert len(read) < len(registry), "a registry where everything was read in full is surprising"


def test_an_http_snapshot_records_where_to_fetch_it() -> None:
    """The locator is a citation; the fetch_url is what a script can download again."""
    record = SnapshotRecord.model_validate(_record())
    assert record.acquisition.fetch_url == "https://example.invalid/file.txt"
    with pytest.raises(ValidationError, match="fetch_url"):
        SnapshotRecord.model_validate(
            _record(
                acquisition={
                    "method": "http",
                    "acquired": True,
                    "acquired_utc": "2026-09-14",
                    "bytes": 1,
                    "sha256": DIGEST,
                    "local_path": f"{RAW_ROOT}/example/file.txt",
                }
            )
        )


def test_every_acquired_snapshot_can_be_fetched_again() -> None:
    for record in load_snapshots(ROOT).acquired_records:
        assert record.acquisition.fetch_url, record.id
        assert str(record.acquisition.fetch_url).startswith("http"), record.id
