"""The robustness report: what crossing means, and which verdicts the ensemble is allowed to move.

Three things can go wrong quietly here. The vectorised crossing can disagree with the rule it
claims to implement; a criterion declared threshold-free can be moved by the ensemble anyway; and
a criterion no measurement decides can be reported as decided. All three are checked here.
"""

from __future__ import annotations

import pytest

from late_ming_lab.protocol.robustness import (
    BREAKDOWN_LINE_KEY,
    BREAKDOWN_READING,
    GATE_ARM,
    NO_ELITE_CREDIT_ARM,
    REFERENCE_ARM,
    RobustnessError,
    RunReading,
    breakdown_lines,
    crossed_count,
    crossed_flags,
    crossed_table,
    declared_criteria,
    evaluate,
    reads_breakdown,
)
from late_ming_lab.protocol.schema import ValidationProtocol, load_protocol
from late_ming_lab.protocol.thresholds import ThresholdEnsemble, load_ensemble


@pytest.fixture(scope="module")
def protocol() -> ValidationProtocol:
    return load_protocol(".")


@pytest.fixture(scope="module")
def ensemble() -> ThresholdEnsemble:
    return load_ensemble(".")


def _run(*, run_id: str, arm: str, measures: dict[str, float], **readings: float) -> RunReading:
    return RunReading(
        run_id=run_id,
        arm=arm,
        root_seed=1,
        policy_id="pilot-policy",
        indicators=measures,
        directions={name: "above-is-failure" for name in measures},
        inversion=readings.get("inversion", 0.0),
        ratchet=readings.get("ratchet", 0.0),
        consolidation=readings.get("consolidation", 0.0),
        elite_loans=readings.get("elite_loans", 0.0),
        bands_at_end=readings.get("bands_at_end", 0.0),
    )


def test_the_vectorised_crossing_agrees_with_the_rule_it_implements(
    ensemble: ThresholdEnsemble,
) -> None:
    """The table is the same arithmetic as `crossed_flags`, member by member and line by line.

    The report's shares are the table's, so a sign error here would invert every one of them while
    every test that reads a share would still pass.
    """
    run = _run(
        run_id="r",
        arm=REFERENCE_ARM,
        measures=dict.fromkeys(ensemble.indicator_ids, 0.5),
    )
    members = (
        dict.fromkeys(ensemble.indicator_ids, 0.4),
        dict.fromkeys(ensemble.indicator_ids, 0.6),
        {name: (0.4 if name.endswith("_share") else 0.6) for name in ensemble.indicator_ids},
    )
    table = crossed_table((run,), members)
    for index, member in enumerate(members):
        expected = crossed_flags(run, member)
        for position, indicator in enumerate(table.indicators):
            assert bool(table.flags[index, 0, position]) is expected[indicator], (index, indicator)


def test_an_above_is_failure_line_crosses_upwards_and_a_below_is_failure_line_downwards() -> None:
    measures = {"fiscal_receipts": 0.4, "tax_base_contraction": 0.02}
    run = RunReading(
        run_id="r",
        arm=REFERENCE_ARM,
        root_seed=1,
        policy_id="pilot-policy",
        indicators=measures,
        directions={
            "fiscal_receipts": "below-is-failure",
            "tax_base_contraction": "above-is-failure",
        },
        inversion=0.0,
        ratchet=0.0,
        consolidation=0.0,
        elite_loans=0.0,
        bands_at_end=0.0,
    )
    # Lines chosen so each direction has one crossing and one non-crossing case.
    assert crossed_flags(run, {"fiscal_receipts": 0.5, "tax_base_contraction": 0.05}) == {
        "fiscal_receipts": True,
        "tax_base_contraction": False,
    }
    assert crossed_flags(run, {"fiscal_receipts": 0.2, "tax_base_contraction": 0.01}) == {
        "fiscal_receipts": False,
        "tax_base_contraction": True,
    }
    assert crossed_count(run, {"fiscal_receipts": 0.2, "tax_base_contraction": 0.05}) == 0
    assert crossed_count(run, {"fiscal_receipts": 0.5, "tax_base_contraction": 0.01}) == 2


def test_a_member_missing_an_indicator_is_refused() -> None:
    run = _run(run_id="r", arm=REFERENCE_ARM, measures={"fiscal_receipts": 0.4})
    with pytest.raises(RobustnessError, match="partially specified"):
        crossed_flags(run, {})


def test_the_breakdown_lines_come_from_the_protocol(protocol: ValidationProtocol) -> None:
    reading = next(item for item in protocol.derived_readings if item.id == BREAKDOWN_READING)
    entry = reading.thresholds[BREAKDOWN_LINE_KEY]
    assert breakdown_lines(protocol) == tuple(range(int(entry.range[0]), int(entry.range[1]) + 1))
    assert entry.value in breakdown_lines(protocol)


def test_reads_breakdown_follows_the_line_it_is_given() -> None:
    measures = {"tax_base_contraction": 0.05}
    run = _run(run_id="r", arm=REFERENCE_ARM, measures=measures)
    member = {"tax_base_contraction": 0.01}
    assert reads_breakdown(run, member, minimum=1)
    assert not reads_breakdown(run, member, minimum=2)


def test_a_contrast_criterion_without_its_arms_is_undetermined() -> None:
    """A criterion that needs two arms cannot be decided by runs of one, and says so."""
    run = _run(
        run_id="only",
        arm=REFERENCE_ARM,
        measures={"tax_base_contraction": 0.05},
        consolidation=0.4,
    )
    criteria = {criterion.id: criterion for criterion in declared_criteria()}
    share = criteria["M002.breakdown-in-every-arm-replicate"].share(
        (run,), ({"tax_base_contraction": 0.01},), breakdown_line=1
    )
    assert share.undetermined == 1.0
    assert share.verdict == "undetermined"


def test_the_gate_criterion_moves_with_the_breakdown_line() -> None:
    """The phase's central question: how much of M002's status is the model, how much the line."""
    # Three indicators, all above their lines in the gate arm; two in the reference arm.
    names = ("a", "b", "c")
    gate = _run(run_id="gate", arm=GATE_ARM, measures=dict.fromkeys(names, 0.05))
    reference = _run(run_id="ref", arm=REFERENCE_ARM, measures={"a": 0.05, "b": 0.05, "c": 0.005})
    member = dict.fromkeys(names, 0.01)
    criteria = {criterion.id: criterion for criterion in declared_criteria()}
    criterion = criteria["M002.breakdown-in-every-arm-replicate"]
    # At three lines the reference arm does not break down and the gate arm does; at two both do.
    assert criterion.share((gate, reference), (member,), breakdown_line=3).holds == 1.0
    assert criterion.share((gate, reference), (member,), breakdown_line=2).holds == 0.0


def test_a_threshold_free_criterion_does_not_move_when_the_ensemble_moves(
    protocol: ValidationProtocol, ensemble: ThresholdEnsemble
) -> None:
    """Invariance is shown by evaluating under every member, which is what this asserts."""
    run = _run(
        run_id="ref",
        arm=REFERENCE_ARM,
        measures=dict.fromkeys(ensemble.indicator_ids, 0.5),
        inversion=0.2,
    )
    fixed = (dict.fromkeys(ensemble.indicator_ids, 0.1),)
    moved = (dict.fromkeys(ensemble.indicator_ids, 0.9),)
    first = evaluate((run,), protocol=protocol, ensemble=ensemble, members=fixed)
    second = evaluate((run,), protocol=protocol, ensemble=ensemble, members=moved)
    for left, right in zip(first.criteria, second.criteria, strict=True):
        if left.criterion.startswith("M005.above-declared-share-line"):
            continue  # the one criterion here that reads a line
        assert left.holds == right.holds, left.criterion


def test_the_report_refuses_a_run_that_measured_nothing_the_ensemble_moves(
    protocol: ValidationProtocol, ensemble: ThresholdEnsemble
) -> None:
    run = _run(run_id="r", arm=REFERENCE_ARM, measures={})
    with pytest.raises(RobustnessError, match="measured no value"):
        evaluate((run,), protocol=protocol, ensemble=ensemble, members=({"x": 1.0},))


def test_an_ensemble_with_no_members_decides_nothing(
    protocol: ValidationProtocol, ensemble: ThresholdEnsemble
) -> None:
    run = _run(run_id="r", arm=REFERENCE_ARM, measures=dict.fromkeys(ensemble.indicator_ids, 0.5))
    with pytest.raises(RobustnessError, match="no members"):
        evaluate((run,), protocol=protocol, ensemble=ensemble, members=())


def test_the_elite_credit_criterion_needs_both_arms() -> None:
    measures = {"tax_base_contraction": 0.05}
    with_credit = _run(run_id="a", arm=REFERENCE_ARM, measures=measures, elite_loans=10.0)
    without = _run(run_id="b", arm=NO_ELITE_CREDIT_ARM, measures=measures, elite_loans=0.0)
    criteria = {criterion.id: criterion for criterion in declared_criteria()}
    criterion = criteria["M004.lending-fires-and-stops-firing"]
    member = {"tax_base_contraction": 0.01}
    both = criterion.share((with_credit, without), (member,), breakdown_line=1)
    assert both.holds == 1.0
    assert criterion.share((with_credit,), (member,), breakdown_line=1).undetermined == 1.0


def test_the_crossed_count_distribution_counts_one_run_at_a_time(
    protocol: ValidationProtocol, ensemble: ThresholdEnsemble
) -> None:
    """A share of (member, run) pairs, so no bar can exceed the number of lines a run crosses.

    Summing over runs instead would report counts no single run can reach while still summing to
    one, which is exactly the kind of number a reader would take at face value.
    """
    names = ensemble.indicator_ids
    runs = tuple(
        _run(run_id=f"r{index}", arm=REFERENCE_ARM, measures=dict.fromkeys(names, 0.05 * index))
        for index in range(1, 4)
    )
    members = (dict.fromkeys(names, 0.08), dict.fromkeys(names, 0.2))
    report = evaluate(runs, protocol=protocol, ensemble=ensemble, members=members)
    assert sum(report.crossed_count_share.values()) == pytest.approx(1.0)
    assert max(int(count) for count in report.crossed_count_share) <= len(names)
    assert set(report.breakdown_shares) == {run.run_id for run in runs}
    for shares in report.breakdown_shares.values():
        assert set(shares) == {str(line) for line in report.breakdown_lines}
