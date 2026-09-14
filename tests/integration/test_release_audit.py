"""The V2-P00 integration checks: the committed freeze and the committed audit describe the
release.

These tests read the real repository: the frozen baseline, the artifact directories it names, the
mechanism cards and the two generated audit documents. They defend the two claims the phase makes —
that ``v0.1.0-rc1`` has not moved, and that every number in the acceptance matrix is read from the
artifact it names — and they are the reason a drifted V1 file cannot pass unnoticed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import polars as pl
import pytest

from late_ming_lab.actors.fixtures import toy_cohort_population
from late_ming_lab.networks.fixtures import toy_spatial_dataset
from late_ming_lab.release.audit import (
    AUDIT_JSON_PATH,
    AUDIT_MARKDOWN_PATH,
    Audit,
    build_audit,
    render_audit_markdown,
    verify_audit,
)
from late_ming_lab.release.baseline import BASELINE_PATH, Baseline, load_baseline, verify_baseline

ROOT = Path(__file__).resolve().parents[2]
RELEASE_TAG = "v0.1.0-rc1"


def _git(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return completed.stdout.strip()


@pytest.fixture(scope="module")
def baseline() -> Baseline:
    return load_baseline(ROOT / BASELINE_PATH)


@pytest.fixture(scope="module")
def audit() -> Audit:
    return build_audit(ROOT)


def test_the_baseline_is_a_git_checkout_with_history() -> None:
    assert (ROOT / ".git").exists(), "these checks need the repository's history"


def test_the_frozen_release_still_verifies(baseline: Baseline) -> None:
    verification = verify_baseline(ROOT, baseline)
    assert verification.failures() == (), verification.failures()
    assert verification.ok
    assert not verification.artifacts


def test_the_frozen_commit_is_the_tagged_release(baseline: Baseline) -> None:
    assert baseline.baseline_id == RELEASE_TAG
    assert baseline.tag == RELEASE_TAG
    assert _git("rev-list", "-n1", RELEASE_TAG) == baseline.commit
    assert _git("merge-base", "--is-ancestor", baseline.commit, "HEAD") == ""


def test_every_artifact_generation_commit_is_the_artifacts_own(baseline: Baseline) -> None:
    recorded = [record for record in baseline.artifacts if record.generation_commit is not None]
    assert recorded, "the release's artifacts must record the commit they were generated at"
    assert all(record.generation_commit_source == "artifact-manifest" for record in recorded)
    assert any(record.generation_commit != baseline.commit for record in recorded), (
        "at least one artifact predates the release; writing HEAD beside it would be a lie"
    )
    unrecorded = [record for record in baseline.artifacts if record.generation_commit is None]
    assert all(record.generation_commit_source == "unrecorded" for record in unrecorded)


def test_the_freeze_covers_code_config_data_and_reports(baseline: Baseline) -> None:
    counts = baseline.group_counts()
    assert sum(counts.values()) == baseline.tracked_file_count
    for group in ("code", "config", "data", "sources", "docs", "report", "tests", "readme"):
        assert counts.get(group, 0) > 0, group
    paths = {record.path for record in baseline.files}
    assert {"pyproject.toml", "uv.lock", "README.md", ".env.example", ".omp/RULES.md"} <= paths
    assert any(path.startswith("data/parameters/") for path in paths)
    assert any(path.startswith("sources/registry/") for path in paths)
    assert any(path.startswith("docs/mechanisms/") for path in paths)
    assert any(path.startswith("outputs/reports/") for path in paths)


def test_every_citation_in_the_audit_resolves(audit: Audit) -> None:
    assert verify_audit(ROOT, audit) == ()


def test_the_committed_audit_is_what_the_code_renders(audit: Audit) -> None:
    committed = json.loads((ROOT / AUDIT_JSON_PATH).read_text(encoding="utf-8"))
    assert committed["content_digest"] == audit.content_digest
    assert committed["schema_version"] == audit.schema_version
    rendered = render_audit_markdown(audit).splitlines()
    stored = (ROOT / AUDIT_MARKDOWN_PATH).read_text(encoding="utf-8").splitlines()

    def strip(lines: list[str]) -> list[str]:
        return [line for line in lines if not line.startswith("- Generated: ")]

    assert strip(rendered) == strip(stored)


def test_the_audit_marks_two_milestones_and_twelve_criteria(audit: Audit) -> None:
    assert [row.id for row in audit.milestones] == ["M1", "M2"]
    assert [row.number for row in audit.criteria] == list(range(1, 13))
    assert set(audit.status_counts()) <= {"met", "partial", "unmet", "not-testable"}
    assert audit.status_counts()["met"] >= 1
    assert audit.status_counts()["unmet"] >= 1, "an audit that finds nothing is not an audit"


def test_the_census_is_measured_from_the_declared_fixture(audit: Audit) -> None:
    nodes = toy_spatial_dataset().build().nodes
    cohorts = toy_cohort_population(nodes)
    assert audit.census.county_count == len([node for node in nodes if node.is_county])
    assert audit.census.external_node_count == len([node for node in nodes if not node.is_county])
    assert audit.census.household_cohort_count == len(cohorts)
    assert "synthetic stationary" in audit.census.climate
    assert all("no claim in the card is about observed climate" in c.climate for c in audit.cards)
    assert (ROOT / audit.census.climate_source.split(":")[0]).is_file()
    assert (ROOT / audit.census.scenario_source.split(":")[0]).is_file()


def test_every_card_records_dataset_climate_sample_arms_and_limits(audit: Audit) -> None:
    assert [card.id for card in audit.cards] == [f"M00{n}" for n in range(1, 7)]
    for card in audit.cards:
        assert card.climate and card.space and card.policy_arms
        assert card.extrapolation_limits and card.counterexample
        if card.datasets:
            for sample in card.datasets:
                if sample.primary_table is None:
                    continue
                table = ROOT / sample.directory / sample.primary_table
                assert pl.read_parquet(table).height == sample.primary_rows
        else:
            assert card.status == "UNIDENTIFIED", card.id


def test_the_card_samples_come_from_artifacts_the_freeze_names(
    baseline: Baseline, audit: Audit
) -> None:
    frozen = {record.directory for record in baseline.artifacts}
    cited = {directory for card in audit.cards for directory in card.sampled_by}
    assert cited, "the card matrix must read at least one artifact"
    assert cited <= frozen, cited - frozen


def test_the_audit_records_the_v1_prose_the_artifacts_contradict(audit: Audit) -> None:
    assert audit.discrepancies, "the phase found none, which is itself a claim to justify"
    claimed = next(
        row for row in audit.discrepancies if row.claim_path == "docs/mechanisms/cards.yaml"
    )
    assert "thirty-two cohorts" in claimed.claim
    assert "five county nodes" in claimed.measured
    assert "twenty-five weighted household cohorts" in claimed.measured
    assert audit.census.county_count == 5
    assert audit.census.household_cohort_count == 25


def test_the_release_is_reported_as_its_own_verification_output(baseline: Baseline) -> None:
    verification = verify_baseline(ROOT, baseline)
    assert len(verification.generated_at) == len(baseline.artifacts)
    assert any(entry.dirty_at_generation for entry in verification.generated_at), (
        "V1 recorded dirty trees; the freeze reports them rather than hiding them"
    )
