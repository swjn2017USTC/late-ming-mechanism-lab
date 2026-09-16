"""What the V2.1 audit must not get wrong, and the facts it rests on.

The centre of this file is one rule: a set of executions is as many independent processes as it has
*distinct simulation digests*, not as many as it has seeds. Everything else here checks that the
accessors read what they claim to read — the audit's numbers are only worth printing if the reader
is honest about where they came from.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from late_ming_lab.calibration.priors import DECLARED, EXCLUDED, build_priors
from late_ming_lab.calibration.simulator import _DEFAULTS as REBUILDABLE_SETS
from late_ming_lab.evidence.cards import load_cards
from late_ming_lab.storage.run_store import RunStore
from late_ming_lab.v2_1.accessors import (
    KEY_READINGS,
    P05_ROOT,
    ArmAudit,
    P05Audit,
    RunAudit,
    audit_p05,
    audit_p08,
    compared,
    declared_p05_runs,
    read_p05_run,
)
from late_ming_lab.v2_1.audit import (
    DETERMINISTIC_BY_DESIGN,
    GENERATED_DOCUMENTS,
    STATEMENT_CORPUS,
    AuditBuildError,
    ReplicateSemantics,
    arm_semantics,
    build_registry_payload,
    determinism_verdict,
    registry_findings,
    runs_that_draw,
    semantics_row,
    stream_statements,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def audited() -> P05Audit:
    """The arm register, read once: forty logs are a fact about the tree, not per-test state."""
    return audit_p05(ROOT)


def _run(*, arm: str, seed: int, digest: str, log_digest: str, rows: float = 100.0) -> RunAudit:
    """One synthetic audited run, so the semantics can be exercised without forty Parquet reads."""
    return RunAudit(
        run_id=f"{arm}-{seed}",
        arm=arm,
        root_seed=seed,
        declared_digest=digest,
        observed_digest=digest,
        manifest_seed=seed,
        rng_draw_rows=0,
        rng_streams=(),
        climate_modes=("observed-historical",),
        climate_rule_versions=("climate-allocated-observed-v1",),
        log_digest=log_digest,
        readings={name: rows for name in KEY_READINGS},
    )


def _arm(*, digests: tuple[str, ...], logs: tuple[str, ...] | None = None) -> ArmAudit:
    logs = logs if logs is not None else ("log-0",) * len(digests)
    return ArmAudit(
        arm="synthetic",
        declared_seeds=tuple(20_260_915 + index for index in range(len(digests))),
        runs=tuple(
            _run(
                arm="synthetic",
                seed=20_260_915 + index,
                digest=digest,
                log_digest=logs[index],
            )
            for index, digest in enumerate(digests)
        ),
    )


def test_four_executions_of_one_digest_are_one_independent_replicate() -> None:
    """The regression this phase exists for: a replay is not a sample of size four."""
    semantics = ReplicateSemantics(executions=4, distinct_digests=1)

    assert semantics.kind == "deterministic-replay"
    assert semantics.independent_replicates == 1
    assert "1 independent replicate" in semantics.sentence()
    assert "4 independent replicates" not in semantics.sentence()


def test_the_audited_row_prints_the_replicate_count_not_the_seed_count() -> None:
    """A reader of the document, not only of the dataclass, must see one replicate."""
    row = semantics_row(_arm(digests=("a", "a", "a", "a")))

    assert row["executions"] == 4
    assert row["distinct_digests"] == 1
    assert row["independent_replicates"] == 1
    assert row["reading_unique_counts"]["event_rows"] == 1


def test_four_distinct_digests_are_four_independent_replicates() -> None:
    """The other direction, so the rule is a measurement rather than a fixed answer."""
    row = semantics_row(_arm(digests=("a", "b", "c", "d")))

    assert row["independent_replicates"] == 4
    assert row["kind"] == "independent-replicates"


def test_a_partly_repeated_set_reports_the_distinct_count() -> None:
    """Two digests among four executions is two processes and two replays, not four of either."""
    row = semantics_row(_arm(digests=("a", "a", "b", "b")))

    assert row["independent_replicates"] == 2
    assert row["kind"] == "partial-replay"
    assert "2 independent replicates and 2 replays" in str(row["semantics"])


def test_replicate_semantics_refuses_a_count_it_cannot_have_produced() -> None:
    """More distinct digests than executions is not a data quality note; it is a bug."""
    with pytest.raises(AuditBuildError, match="not a possible outcome"):
        ReplicateSemantics(executions=2, distinct_digests=3)


def test_a_reading_is_compared_at_the_declared_precision() -> None:
    """Last-bit noise from a parallel reduction is not a behavioural difference."""
    assert compared(0.19940185717079711) == compared(0.19940185717079706)
    assert compared(0.1994) != compared(0.1995)


def test_a_reading_that_really_moved_is_not_absorbed_by_the_precision() -> None:
    """The tolerance must not be so coarse that a moved reading reads as a replay."""
    arm = ArmAudit(
        arm="synthetic",
        declared_seeds=(1, 2),
        runs=(
            _run(arm="synthetic", seed=1, digest="a", log_digest="a", rows=100.0),
            _run(arm="synthetic", seed=2, digest="a", log_digest="a", rows=101.0),
        ),
    )

    assert arm.reading_stability() == "reduction-order"
    assert arm.reading_unique_counts()["event_rows"] == 2


def test_the_declared_register_names_the_runs_that_are_on_disk() -> None:
    """Complete only if every declared run exists and nothing undeclared sits beside it."""
    generator, declared = declared_p05_runs(ROOT)
    store = RunStore(ROOT / P05_ROOT)
    on_disk = set(store.list_runs())

    assert generator == "late-ming-lab experiment p05"
    assert len(declared) == 40
    assert len({entry.arm for entry in declared}) == 10
    assert {entry.run_id for entry in declared} == on_disk


def test_the_reference_arm_repeats_exactly_on_disk() -> None:
    """Read from the run directories: one digest, one set of bytes, no draws, observed forcing."""
    _, declared = declared_p05_runs(ROOT)
    reference = tuple(entry for entry in declared if entry.arm == "reference")
    store = RunStore(ROOT / P05_ROOT)
    runs = tuple(read_p05_run(store, entry) for entry in reference)

    assert len(runs) == 4
    assert len({run.observed_digest for run in runs}) == 1
    assert len({run.log_digest for run in runs}) == 1
    assert {run.root_seed for run in runs} == {20_260_915, 20_260_916, 20_260_917, 20_260_918}
    for run in runs:
        assert run.climate_modes == ("observed-historical",)
        assert run.rng_draw_rows == 0
        assert run.seed_agrees
        assert run.digest_agrees


def test_the_verdict_on_the_committed_arms_is_a_declared_determinism(audited: P05Audit) -> None:
    """The phase's entry gate for V2.1-P11, decided from the artifacts rather than asserted."""
    verdict = determinism_verdict(ROOT, audited)

    assert verdict.verdict == DETERMINISTIC_BY_DESIGN
    assert not verdict.is_blocker
    assert verdict.forcing_modes == ("observed-historical",)
    assert all(arm_semantics(arm).independent_replicates == 1 for arm in audited.arms)
    assert {arm.rng_draw_rows for arm in audited.arms} == {0}
    assert sorted(verdict.unused_streams) == [
        "decision",
        "household",
        "market",
        "migration",
        "military",
        "rebel",
    ]
    assert verdict.call_sites["climate"] == ("src/late_ming_lab/systems/climate.py",)


def test_a_declared_register_that_lost_a_run_is_reported_rather_than_counted_as_zero(
    audited: P05Audit,
) -> None:
    """Absence is not zero: a missing execution must not read as a completed one.

    The audit reads what the register declares and reports what is absent; a register naming
    nothing would raise rather than produce an empty, apparently complete, table.
    """
    assert audited.missing_run_ids == ()
    assert audited.undeclared_run_ids == ()
    assert len(audited.runs) == 40
    assert len(audited.arms) == 10


def test_runs_that_draw_are_read_with_their_forcing_mode_and_stream() -> None:
    """The counter-check to the historical core's zero, on a run set that does draw."""
    roots = runs_that_draw(ROOT, output_root="outputs/pilot/v2-p03")

    assert roots
    for run in roots:
        assert run.rng_streams == ("climate",)
        assert run.climate_modes == ("synthetic",)
        assert run.climate_rule_versions == ("climate-synthetic-v1",)
        assert run.rng_draw_rows > 0


def test_the_statement_scan_reads_only_the_declared_corpus() -> None:
    """A scan that read its own output, or a report quoting it, would not be reproducible.

    The corpus is declared where the design lives; a phase report or an exec plan records work and
    may quote this audit, so reading one would make each generation quote the last.
    """
    statements = stream_statements(ROOT)

    for stream, lines in statements.items():
        for line in lines:
            assert line.startswith(STATEMENT_CORPUS), (stream, line)
    assert statements["household"], "the design documents do name the streams they declare"
    assert not any(
        line.startswith(f"{GENERATED_DOCUMENTS}/")
        or line.startswith("docs/phase-reports/")
        or line.startswith("docs/exec-plans/")
        for lines in statements.values()
        for line in lines
    )


def test_the_unclassified_cards_are_the_complement_of_the_two_declared_lists() -> None:
    """The finding V2-P06 carried: a range-carrying card in neither list, recomputed here."""
    findings = registry_findings(ROOT)
    cards = load_cards(ROOT)
    classified = {name for name, _, _ in DECLARED} | {name for name, _, _ in EXCLUDED}
    expected = {card.id for card in cards if card.range is not None and card.id not in classified}

    assert {card.name for card in findings.unclassified} == expected
    assert findings.unclassified_numeric
    assert all(card.numeric_range for card in findings.unclassified_numeric)
    assert all(not card.numeric_range for card in findings.unclassified_text_only)
    assert findings.range_carrying == sum(1 for card in cards if card.range is not None)


def test_a_declared_prior_the_simulator_cannot_rebuild_is_reported() -> None:
    """A draw that passes the check, enters the hash and never reaches the run is a defect.

    The expected set is recomputed from the cards and the simulator's own rebuild table, so the
    audit is checked against the code rather than against itself.
    """
    findings = registry_findings(ROOT)
    cards = load_cards(ROOT)
    rebuildable = {name for name, _ in REBUILDABLE_SETS}
    expected = {
        prior.name for prior in build_priors(cards) if prior.parameter_set not in rebuildable
    }

    assert set(findings.declared_but_not_applied) == expected
    assert set(findings.declared_but_not_applied) <= {name for name, _, _ in DECLARED}
    assert set(findings.applied_sets) <= rebuildable


def test_the_registry_payload_says_what_it_did_with_each_finding() -> None:
    """Every finding carries a resolution; none is silently dropped."""
    payload = build_registry_payload(ROOT)
    resolutions = payload["resolutions"]
    assert isinstance(resolutions, list)

    findings = {str(entry["finding"]) for entry in resolutions}
    assert "central value outside its own declared range" in findings
    assert "range-carrying cards in neither the declared nor the excluded list" in findings
    assert all(entry["reason"] for entry in resolutions)


def test_the_runtime_arms_report_no_model_decisions() -> None:
    """P08's pilot, recomputed from the traces rather than read from the arm summary."""
    arms = audit_p08(ROOT)

    assert arms.decisions_from_model == 0
    assert arms.agrees_with_manifest
    assert arms.refusals == len(arms.seeds)
    assert arms.decision_traces == 3 * len(arms.seeds)
