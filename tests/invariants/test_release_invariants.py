"""The V2-P00 freeze invariants: the manifest describes the release, and drift is caught.

These tests build a small git repository from scratch and freeze it, so each drift case is exercised
against the real code rather than asserted about this checkout: a tracked edit, a vanished file, a
rewritten artifact, a new artifact, a manifest that no longer hashes to the commit it names, and an
artifact whose own manifest records a commit that is not HEAD. The release's rule is defended here —
artifacts and the release commit must not move, while tracked code and documents may be edited by a
later phase and are then reported rather than passed over.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from late_ming_lab.release.baseline import (
    BaselineError,
    build_baseline,
    content_digest,
    group_for,
    load_baseline,
    sha256_bytes,
    verify_baseline,
    write_baseline,
)

RUN_DIR = "outputs/runs/run-1"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            "user.name=release test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "init.defaultBranch=main",
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def frozen_repo(tmp_path: Path) -> Path:
    """A commit, then the artifacts a V1 phase would have written after it."""
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "data").mkdir()
    (repo / "outputs" / "runs" / "run-1").mkdir(parents=True)
    (repo / "outputs" / "analysis").mkdir(parents=True)
    (repo / "src" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "data" / "cards.yaml").write_text("card: 1\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "the release")
    commit = _git(repo, "rev-parse", "HEAD")
    run = repo / RUN_DIR
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "run-manifest-v1",
                "run_id": "run-1",
                "git_sha": commit,
                "git_dirty": False,
                "root_seed": 7,
            }
        ),
        encoding="utf-8",
    )
    pl.DataFrame({"tick": [0, 1, 2]}).write_parquet(run / "events.parquet")
    pl.DataFrame({"total": [3]}).write_parquet(repo / "outputs" / "analysis" / "summary.parquet")
    return repo


def test_the_manifest_covers_the_release_and_repeats(frozen_repo: Path) -> None:
    first = build_baseline(frozen_repo, generated_at=datetime(2026, 1, 1, tzinfo=UTC))
    second = build_baseline(frozen_repo, generated_at=datetime(2026, 6, 1, tzinfo=UTC))
    assert first.commit == _git(frozen_repo, "rev-parse", "HEAD")
    assert [record.path for record in first.files] == [
        "data/cards.yaml",
        "pyproject.toml",
        "src/mod.py",
    ]
    assert {record.path: record.group for record in first.files} == {
        "data/cards.yaml": "data",
        "pyproject.toml": "config",
        "src/mod.py": "code",
    }
    assert first.content_digest == second.content_digest
    assert first.generated_at_utc != second.generated_at_utc
    assert first.baseline_id != second.baseline_id or first.commit == second.commit


def test_the_build_refuses_a_modified_frozen_file(frozen_repo: Path) -> None:
    (frozen_repo / "src" / "mod.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(BaselineError, match="modified tree"):
        build_baseline(frozen_repo)


def test_a_tracked_edit_is_reported_and_does_not_fail(frozen_repo: Path) -> None:
    baseline = build_baseline(frozen_repo)
    (frozen_repo / "src" / "mod.py").write_text("VALUE = 2\n", encoding="utf-8")
    verification = verify_baseline(frozen_repo, baseline)
    assert [drift.path for drift in verification.modified()] == ["src/mod.py"]
    assert verification.failures() == ()
    assert verification.ok


def test_a_vanished_frozen_file_fails(frozen_repo: Path) -> None:
    baseline = build_baseline(frozen_repo)
    (frozen_repo / "data" / "cards.yaml").unlink()
    verification = verify_baseline(frozen_repo, baseline)
    assert not verification.ok
    assert [(drift.path, drift.kind) for drift in verification.failures()] == [
        ("data/cards.yaml", "missing")
    ]


def test_a_rewritten_artifact_fails(frozen_repo: Path) -> None:
    baseline = build_baseline(frozen_repo)
    (frozen_repo / RUN_DIR / "manifest.json").write_text("{}\n", encoding="utf-8")
    verification = verify_baseline(frozen_repo, baseline)
    assert not verification.ok
    assert [drift.path for drift in verification.artifacts] == [f"{RUN_DIR}/manifest.json"]
    assert verification.artifacts[0].kind == "modified"


def test_a_file_added_inside_an_artifact_fails(frozen_repo: Path) -> None:
    baseline = build_baseline(frozen_repo)
    (frozen_repo / RUN_DIR / "extra.parquet").write_bytes(b"x")
    verification = verify_baseline(frozen_repo, baseline)
    assert not verification.ok
    assert [drift.path for drift in verification.artifacts] == [f"{RUN_DIR}/extra.parquet"]


def test_a_new_artifact_directory_and_new_code_are_additions(frozen_repo: Path) -> None:
    baseline = build_baseline(frozen_repo)
    second = frozen_repo / "outputs" / "runs" / "run-2"
    second.mkdir()
    (second / "manifest.json").write_text("{}\n", encoding="utf-8")
    (frozen_repo / "src" / "extra.py").write_text("NEW = True\n", encoding="utf-8")
    _git(frozen_repo, "add", "-A")
    _git(frozen_repo, "commit", "-m", "v2 work")
    verification = verify_baseline(frozen_repo, baseline)
    assert verification.ok
    assert verification.artifacts == ()
    additions = {drift.path for drift in verification.additions()}
    assert "src/extra.py" in additions
    assert "outputs/runs/run-2/manifest.json" in additions


def test_a_generation_commit_is_the_artifacts_own_and_not_head(frozen_repo: Path) -> None:
    baseline = build_baseline(frozen_repo)
    _git(frozen_repo, "commit", "--allow-empty", "-m", "later work")
    head = _git(frozen_repo, "rev-parse", "HEAD")
    record = baseline.artifact(RUN_DIR)
    assert record.generation_commit != head
    assert record.generation_commit_source == "artifact-manifest"
    assert record.git_dirty_at_generation is False
    verification = verify_baseline(frozen_repo, baseline)
    entry = next(item for item in verification.generated_at if item.directory == RUN_DIR)
    assert entry.generation_commit == record.generation_commit
    assert entry.ancestor_of_head is True


def test_a_dirty_tree_is_recorded_as_dirty(frozen_repo: Path) -> None:
    run = frozen_repo / RUN_DIR
    payload = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    payload["git_dirty"] = True
    (run / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    baseline = build_baseline(frozen_repo)
    assert baseline.artifact(RUN_DIR).git_dirty_at_generation is True


def test_an_artifact_with_no_manifest_says_unrecorded(frozen_repo: Path) -> None:
    baseline = build_baseline(frozen_repo)
    record = baseline.artifact("outputs/analysis")
    assert record.generation_commit is None
    assert record.generation_commit_source == "unrecorded"
    assert [table.name for table in record.tables] == ["summary.parquet"]
    assert record.tables[0].rows == 1


def test_a_manifest_that_no_longer_describes_its_commit_fails(frozen_repo: Path) -> None:
    baseline = build_baseline(frozen_repo)
    files = tuple(
        record.model_copy(update={"sha256": "0" * 64}) if record.path == "src/mod.py" else record
        for record in baseline.files
    )
    rewritten = baseline.model_copy(
        update={"files": files, "content_digest": content_digest(files, baseline.artifacts)}
    )
    verification = verify_baseline(frozen_repo, rewritten)
    assert not verification.ok
    assert [(drift.path, drift.section) for drift in verification.history] == [
        ("src/mod.py", "history")
    ]


def test_the_timestamp_is_not_part_of_the_identity(frozen_repo: Path) -> None:
    first = build_baseline(frozen_repo, generated_at=datetime(2026, 1, 1, tzinfo=UTC))
    second = build_baseline(frozen_repo, generated_at=datetime(2027, 1, 1, tzinfo=UTC))
    assert first.content_digest == second.content_digest
    assert first.model_dump(mode="json") != second.model_dump(mode="json")


def test_a_written_baseline_round_trips(frozen_repo: Path, tmp_path: Path) -> None:
    baseline = build_baseline(frozen_repo)
    path = write_baseline(frozen_repo, baseline, tmp_path / "baseline.json")
    assert load_baseline(path) == baseline
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_group_for_refuses_a_path_it_does_not_know() -> None:
    with pytest.raises(BaselineError, match="no declared group"):
        group_for("experiments/ablations/run.py")
    assert group_for("src/late_ming_lab/cli.py") == "code"
    assert group_for("uv.lock") == "config"


def test_pinning_an_older_commit_from_a_moved_tree_is_refused(frozen_repo: Path) -> None:
    """The manifest describes the release, never a tree the release does not match."""
    release = _git(frozen_repo, "rev-parse", "HEAD")
    (frozen_repo / "src" / "mod.py").write_text("VALUE = 3\n", encoding="utf-8")
    _git(frozen_repo, "add", "-A")
    _git(frozen_repo, "commit", "-m", "v2 work")
    with pytest.raises(BaselineError, match="modified tree"):
        build_baseline(frozen_repo, commit=release)
    moved = build_baseline(frozen_repo)
    assert moved.commit != release
    frozen = next(record for record in moved.files if record.path == "src/mod.py")
    assert frozen.sha256 == sha256_bytes(b"VALUE = 3\n")


def test_a_copy_of_the_tree_still_verifies(frozen_repo: Path, tmp_path: Path) -> None:
    """Verification is about content, not about where the tree sits."""
    baseline = build_baseline(frozen_repo)
    copy = tmp_path / "copy"
    shutil.copytree(frozen_repo, copy)
    assert verify_baseline(copy, baseline).ok
