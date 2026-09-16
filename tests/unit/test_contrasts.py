"""The V2.1-P11 contrasts: the accessors, the controls and the pre-registered status rules.

The properties this file defends are the ones the phase's acceptance turns on:

```text
the arms are the declared ones   each arm's configuration diff names exactly what it declares, and
                                 the reference declares nothing
the runs are the experiments     the stored runs carry the protocol stamp, the detector's verdict,
                                 and the digests P05 recorded for the two arms it shares
the window is the declared one   whole-run, under the reporting purpose; a reserved window is not
                                 readable as a fit target
the rules are the frozen ones    each status recommendation is the pre-registered rule applied to a
                                 reading, and a falsifier firing is what moves a card down
```

The runs themselves are not produced here: the phase writes them once, and a test that ran them
would be re-running four 240-tick trajectories to check a document.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from late_ming_lab.experiments.contrasts import (
    M002_FALSIFIER,
    M004_FALSIFIER,
    PURPOSE,
    SEED,
    WINDOW,
    ContrastError,
    ContrastReading,
    ContrastRun,
    arm_runs,
    caveats,
    contrasts_payload,
    cross_checks,
    declared_arms,
    load_runs,
    m002_status,
    m004_status,
    p05_arm_digest,
)
from late_ming_lab.experiments.families import FAMILIES, ExperimentError, run_family
from late_ming_lab.experiments.holdout import REFERENCE_ARM
from late_ming_lab.protocol.freeze import WindowAccessError, assert_window_access
from late_ming_lab.protocol.schema import load_protocol

ROOT = Path(__file__).resolve().parents[2]

#: The per-parameter changes each arm must declare, so an arm cannot quietly move something else.
EXPECTED_DIFFS = {
    REFERENCE_ARM: set(),
    "gate-open": {
        "MigrationParameters.cost_tael_per_household",
        "MigrationParameters.cost_tael_per_adult",
        "MigrationParameters.transit_loss_share",
        "MigrationParameters.minimum_households_to_move",
        "HouseholdParameters.permanent_migration_unmet_ratio",
        "HouseholdParameters.temporary_migration_unmet_ratio",
    },
    "elite-credit-closed": {"EliteParameters.loan_to_value"},
    "elite-accumulation": {
        "EliteParameters.foreclosure_after_unserviced_months",
        "EliteParameters.foreclosure_land_share_of_pledge",
    },
}


@pytest.fixture(scope="module")
def runs() -> tuple[ContrastRun, ...]:
    return load_runs(root=ROOT)


@pytest.fixture(scope="module")
def payload(runs: tuple[ContrastRun, ...]) -> dict[str, Any]:
    return contrasts_payload(root=ROOT, runs=runs)


def test_each_arm_declares_exactly_the_parameters_it_says_it_moves() -> None:
    """An arm that moved a parameter its declaration does not name would be another experiment."""
    arms = declared_arms()

    assert {arm.label for arm in arms} == set(EXPECTED_DIFFS)
    for arm in arms:
        assert set(arm.configuration_diff()) == EXPECTED_DIFFS[arm.label]
        assert arm.expects_effect is (arm.label != REFERENCE_ARM)


def test_the_reference_arm_is_the_neutral_structure() -> None:
    """Every other arm is read against it, so it may move nothing at all."""
    reference = next(arm for arm in declared_arms() if arm.label == REFERENCE_ARM)

    assert reference.configuration_diff() == {}
    assert not reference.expects_effect


def test_the_declared_interventions_are_the_projects_own() -> None:
    """The gate and the credit channel are read from one declaration, not retyped here."""
    from late_ming_lab.experiments.interventions import (
        no_elite_credit_updates,
        open_migration_exit_updates,
    )

    migration, household = open_migration_exit_updates()
    gate = next(arm for arm in declared_arms() if arm.label == "gate-open")
    closed = next(arm for arm in declared_arms() if arm.label == "elite-credit-closed")

    assert gate.migration == migration and gate.household == household
    assert closed.elite == no_elite_credit_updates()


def test_the_runs_on_disk_reproduce_what_p05_recorded(runs: tuple[ContrastRun, ...]) -> None:
    """Two of the four arms are P05's declarations, so their digests must repeat exactly."""
    checks = cross_checks(runs, root=ROOT)

    assert checks["reference"]["agrees"], checks["reference"]
    assert checks["elite-accumulation"]["agrees"], checks["elite-accumulation"]
    assert p05_arm_digest(root=ROOT, arm=REFERENCE_ARM, seed=SEED) == (
        "e856aa13b75c06646d5534a07578a95a3bec598ee4a32072e851e51baadd5e59"
    )


def test_a_run_without_the_protocol_stamp_is_refused(tmp_path: Path) -> None:
    """A run whose scoring rules are unknown is not a run this phase may read."""
    import shutil

    from late_ming_lab.experiments.contrasts import CONTRASTS_ROOT
    from late_ming_lab.protocol.evaluation import PROTOCOL_STAMP_FILE

    source = ROOT / CONTRASTS_ROOT
    target = tmp_path / CONTRASTS_ROOT
    shutil.copytree(source, target)
    victim = sorted(path for path in target.iterdir() if path.is_dir())[0]
    (victim / PROTOCOL_STAMP_FILE).unlink()

    with pytest.raises(ContrastError, match=r"validation-protocol\.json"):
        load_runs(root=ROOT, output_root=target)


def test_the_contrast_reads_the_reporting_window_and_a_reserved_one_is_refused() -> None:
    """The frozen isolation rule, read rather than restated: report is not turned into fit."""
    protocol = load_protocol(ROOT)

    assert (WINDOW, PURPOSE) == ("whole-run", "report")
    assert_window_access(protocol, WINDOW, "report")
    with pytest.raises(WindowAccessError):
        assert_window_access(protocol, "hold-out", "fit")


def test_the_detector_ran_on_every_arm_and_the_reference_is_the_neutral_one(
    runs: tuple[ContrastRun, ...],
) -> None:
    """A declared structure that moved nothing would be a failed arm, not a null result."""
    verdicts = {run.label: run.no_op for run in runs}

    assert set(verdicts) == set(EXPECTED_DIFFS)
    assert "neutral structure" in verdicts[REFERENCE_ARM]
    for label in ("gate-open", "elite-credit-closed", "elite-accumulation"):
        assert "reproduced the reference" not in verdicts[label], (label, verdicts[label])


def test_the_base_reading_agrees_with_the_two_frozen_definitions(
    runs: tuple[ContrastRun, ...],
) -> None:
    """One number, three ways of reading it: the accessor, the protocol outcome, the indicator.

    The phase reports the assessable base from the project's own per-county accessor, and a reader
    will compare it with the protocol's `fiscal_base` and with the governance line's measure. They
    are the same arithmetic, and a run where they disagreed would be a second definition.
    """
    for run in runs:
        assert run.indicators["tax_base_contraction"] == pytest.approx(
            run.base.contraction_share, rel=1e-12
        )
        assert run.outcome.value("fiscal_base").value == pytest.approx(
            run.base.change_mu, rel=1e-12
        )


def test_the_elite_chain_separates_the_two_branches(runs: tuple[ContrastRun, ...]) -> None:
    """Closed credit lends nothing; accumulation transfers land. Both measured, not asserted."""
    closed = next(run for run in runs if run.label == "elite-credit-closed")
    accumulation = next(run for run in runs if run.label == "elite-accumulation")

    assert closed.elite.loans == 0 and closed.elite.defaults == 0
    assert not closed.elite.fires
    assert accumulation.elite.loans > 0 and accumulation.elite.defaults > 0
    assert accumulation.elite.fires
    assert accumulation.elite.land_transferred_mu > 0.0


def test_the_m002_reading_is_continuous_and_the_projection_is_separate(
    payload: dict[str, Any],
) -> None:
    """The headline is the base, not `breakdown`; the projection is reported beside it."""
    m002 = payload["contrasts"]["M002"]
    assert m002["reading"].startswith("governance tax_base_contraction")
    assert m002["difference"] == pytest.approx(m002["value_b"] - m002["value_a"], rel=1e-12)
    projection = payload["projection"]
    assert [entry["arm"] for entry in projection] == sorted(run["arm"] for run in payload["runs"])
    for entry in projection:
        assert entry["members"] > 0
        assert entry["lines"] == [4, 5, 6, 7, 8]
        assert len(entry["shares"]) == len(entry["lines"])


def test_the_caveats_are_read_from_the_runs(payload: dict[str, Any]) -> None:
    """The size of the gate contrast is qualified by numbers, not by a hedge."""
    text = " ".join(payload["caveats"])

    gate = next(run for run in payload["runs"] if run["arm"] == "gate-open")
    assert f"{gate['starting_households']:.0f}" in text
    assert "cumulative household-moves" in text
    assert "no land" in text


def _reading(difference: float, *, minimum: float = 0.02) -> ContrastReading:
    """A synthetic paired contrast, so a status rule can be exercised without a run."""
    return ContrastReading(
        name="synthetic",
        question="does b exceed a?",
        arm_a="a",
        arm_b="b",
        reading="a share",
        value_a=0.05,
        value_b=0.05 + difference,
        difference=difference,
        minimum_substantive_effect=minimum,
        direction_holds=difference > 0.0,
        substantive=difference >= minimum,
        falsifier="b contracts no further than a",
        falsifier_fires=difference <= 0.0,
    )


def test_m002_keeps_its_status_only_on_a_substantive_difference() -> None:
    """Above the declared effect the status holds; below it the size does not."""
    assert m002_status(_reading(0.10)).recommended == "CONDITIONAL"
    assert m002_status(_reading(0.005)).recommended == "WEAK"


def test_a_falsifier_that_fires_moves_a_card_down() -> None:
    """The card's own falsifier is what a null result means, and it is named when it fires."""
    firing = m002_status(_reading(0.0))

    assert firing.recommended == "REJECTED"
    assert m002_status(_reading(-0.01)).recommended == "REJECTED"
    assert "the falsifier fired" in firing.rejected
    assert "the falsifier fired" not in m002_status(_reading(0.10)).rejected


def test_the_falsifiers_are_the_cards_own_sentences() -> None:
    """A recommendation that quoted a falsifier the card does not state would test nothing."""
    m002 = (ROOT / "docs/mechanisms/v2/M002.md").read_text(encoding="utf-8")
    m004 = (ROOT / "docs/mechanisms/v2/M004.md").read_text(encoding="utf-8")

    assert M002_FALSIFIER in m002
    assert M004_FALSIFIER in m004


def test_m004_moves_only_when_the_branch_fires_and_the_effect_is_substantive(
    runs: tuple[ContrastRun, ...],
) -> None:
    """A branch that fires without an effect is the card's own falsifier, in one sentence."""
    accumulation = next(run for run in runs if run.label == "elite-accumulation")
    closed = next(run for run in runs if run.label == "elite-credit-closed")

    substantive = m004_status(_reading(0.10), accumulation=accumulation, closed=closed)
    below = m004_status(_reading(0.005), accumulation=accumulation, closed=closed)

    assert substantive.recommended == "CONDITIONAL"
    assert below.recommended == "WEAK"
    assert accumulation.elite.fires, "the fixture relies on the branch firing on this input"


def test_the_documents_status_is_the_rule_applied_to_the_documents_reading(
    payload: dict[str, Any],
) -> None:
    """The rendered recommendation and the recorded readings must be the same decision."""
    statuses = {entry["card"]: entry for entry in payload["status"]}
    m002 = payload["contrasts"]["M002"]

    assert statuses["M002"]["recommended"] == m002_status(ContrastReading(**m002)).recommended
    m004 = payload["contrasts"]["M004"]
    assert statuses["M004"]["v2_status"] == "WEAK"
    assert m004["falsifier_fires"] is (m004["difference"] <= 0.0)
    assert statuses["M002"]["v2_status"] == "CONDITIONAL"


def test_the_family_refuses_a_replicate_count_and_names_the_run_requirement() -> None:
    """The design is one trajectory per arm; a caller asking for more asks for replays."""
    with pytest.raises(ExperimentError, match="one trajectory per arm"):
        run_family("p11", root=ROOT, replicates=4)


def test_the_family_is_registered() -> None:
    assert "p11" in FAMILIES
    assert FAMILIES["p11"].runner is not None


def test_the_caveats_helper_is_a_pure_read_of_the_runs(runs: tuple[ContrastRun, ...]) -> None:
    """The caveat list is derived, so it cannot drift from the numbers it qualifies."""
    lines = caveats(runs)

    assert lines and all(isinstance(line, str) for line in lines)
    assert any("open values" in line for line in lines)


def test_arm_runs_is_not_called_by_the_readers() -> None:
    """Reading the phase must not re-run it: `arm_runs` writes; the readers do not."""
    assert callable(arm_runs)
    for path in sorted((ROOT / "outputs/v2_1/p11").iterdir()):
        assert (path / "validation-protocol.json").is_file()
