"""The P12 comparison's rules, at the smallest scale that still runs a real arm.

The interesting logic in P12 is not the model run — it is the verdict rules, the region comparison
and the report's ability to be regenerated from its artifact. Those are exercised here against
declared arm results, plus one tiny real arm so the wiring is proved and not merely asserted.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from late_ming_lab.analysis.mechanisms import MECHANISM_IDS
from late_ming_lab.experiments.policy_robustness import (
    POLICY_ARMS,
    REFERENCE_POLICY,
    PolicyArmResult,
    load_p12,
    mechanism_effect,
    mechanism_matrix,
    region_movement,
    robustness_verdicts,
    run_p12,
    run_policy_arm,
    tipping_summary,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _arm(
    policy: str,
    *,
    present: dict[str, float],
    status: str = "ran",
    reason: str = "",
    replicates: int = 4,
) -> PolicyArmResult:
    """An arm result with declared presence shares and no model run at all."""
    rows: list[dict[str, object]] = []
    for mechanism, share in present.items():
        hits = round(share * replicates)
        for replicate in range(replicates):
            rows.append(
                {
                    "label": policy,
                    "replicate": replicate,
                    "mechanism": mechanism,
                    "present": 1.0 if replicate < hits else 0.0,
                    "strength": 0.1 if replicate < hits else 0.0,
                    "reading": "declared",
                }
            )
    readings = pl.DataFrame(
        rows,
        schema={
            "label": pl.String,
            "replicate": pl.Int64,
            "mechanism": pl.String,
            "present": pl.Float64,
            "strength": pl.Float64,
            "reading": pl.String,
        },
    )
    levels = pl.DataFrame(
        {
            "label": [policy] * replicates,
            "replicate": list(range(replicates)),
            "indicators_crossed_end": [5.0] * replicates,
        }
    )
    return PolicyArmResult(
        policy=policy,
        status=status,
        reason=reason,
        readings=readings,
        levels=levels,
        traces=pl.DataFrame(),
        refusals=pl.DataFrame(),
    )


def test_a_mechanism_shown_by_every_arm_is_robust() -> None:
    arms = (
        _arm(REFERENCE_POLICY, present={MECHANISM_IDS[2]: 1.0}),
        _arm("utility", present={MECHANISM_IDS[2]: 0.75}),
        _arm("random", present={MECHANISM_IDS[2]: 0.5}),
        _arm("ustc", present={}, status="refused", reason="gate"),
    )
    verdicts = robustness_verdicts(arms)
    band = verdicts.filter(pl.col("mechanism") == MECHANISM_IDS[2]).row(0, named=True)

    assert band["verdict"] == "robust"
    assert band["arms_showing"] == 3
    assert band["arms_ran"] == 3


def test_a_mechanism_only_a_declared_policy_shows_is_policy_dependent() -> None:
    arms = (
        _arm(REFERENCE_POLICY, present={MECHANISM_IDS[0]: 0.0}),
        _arm("utility", present={MECHANISM_IDS[0]: 1.0}),
        _arm("random", present={MECHANISM_IDS[0]: 0.25}),
    )
    verdicts = robustness_verdicts(arms)
    inversion = verdicts.filter(pl.col("mechanism") == MECHANISM_IDS[0]).row(0, named=True)

    assert inversion["verdict"] == "policy-dependent"
    assert inversion["showing_policies"] == "utility"


def test_a_mechanism_only_the_runtime_arm_shows_is_model_dependent() -> None:
    """The one case the phase must mark, and it is marked by *which* arm, not by the count."""
    arms = (
        _arm(REFERENCE_POLICY, present={MECHANISM_IDS[1]: 0.0}),
        _arm("utility", present={MECHANISM_IDS[1]: 0.0}),
        _arm("random", present={MECHANISM_IDS[1]: 0.0}),
        _arm("ustc", present={MECHANISM_IDS[1]: 1.0}),
    )
    verdicts = robustness_verdicts(arms)
    ratchet = verdicts.filter(pl.col("mechanism") == MECHANISM_IDS[1]).row(0, named=True)

    assert ratchet["verdict"] == "model-dependent"
    assert ratchet["showing_policies"] == "ustc"


def test_one_showing_arm_is_policy_dependent_and_two_are_mixed() -> None:
    """The count decides between dependent, mixed and robust; only the runtime arm is special."""
    arms = (
        _arm(REFERENCE_POLICY, present={MECHANISM_IDS[0]: 0.0, MECHANISM_IDS[1]: 1.0}),
        _arm("utility", present={MECHANISM_IDS[0]: 1.0, MECHANISM_IDS[1]: 0.0}),
        _arm("random", present={MECHANISM_IDS[0]: 1.0, MECHANISM_IDS[1]: 0.0}),
    )
    verdicts = robustness_verdicts(arms)
    by_mechanism = {row["mechanism"]: row["verdict"] for row in verdicts.iter_rows(named=True)}

    assert by_mechanism[MECHANISM_IDS[0]] == "mixed"
    assert by_mechanism[MECHANISM_IDS[1]] == "policy-dependent"


def test_the_matrix_leaves_a_refused_arm_empty_rather_than_guessing() -> None:
    arms = (
        _arm(REFERENCE_POLICY, present={mechanism: 1.0 for mechanism in MECHANISM_IDS}),
        _arm("ustc", present={}, status="refused", reason="gate"),
    )
    matrix = mechanism_matrix(arms)

    assert matrix["ustc"].to_list() == [None] * len(MECHANISM_IDS)
    assert matrix[REFERENCE_POLICY].to_list() == [1.0] * len(MECHANISM_IDS)

    effects = mechanism_effect(arms)
    refused_rows = effects.filter(pl.col("policy") == "ustc")
    assert refused_rows["present_share"].to_list() == [None] * len(MECHANISM_IDS)


def test_the_region_moves_when_the_cells_that_break_down_change() -> None:
    summary = pl.DataFrame(
        {
            "policy": ["rule", "rule", "utility", "utility"],
            "nominal_pressure": [0.01, 0.04, 0.01, 0.04],
            "severity_floor": [0.3, 0.9, 0.3, 0.9],
            "breakdown_share": [0.5, 1.0, 0.0, 1.0],
            "mean_crossed": [5.5, 6.0, 5.0, 6.0],
        }
    )
    movement = region_movement(summary)
    by_policy = {row["policy"]: row for row in movement.iter_rows(named=True)}

    assert by_policy["rule"]["same_as_reference"] is True
    assert by_policy["utility"]["same_as_reference"] is False
    assert by_policy["utility"]["cells_with_breakdown"] == 1


def test_the_declared_arms_are_the_four_the_phase_compares() -> None:
    assert POLICY_ARMS == ("rule", "utility", "random", "ustc")
    assert REFERENCE_POLICY == "rule"


def test_the_tipping_summary_aggregates_cells_rather_than_runs() -> None:
    grid = pl.DataFrame(
        {
            "policy": ["rule"] * 4,
            "nominal_pressure": [0.01, 0.01, 0.04, 0.04],
            "severity_floor": [0.3, 0.3, 0.9, 0.9],
            "replicate": [0, 1, 0, 1],
            "crossed": [5.0, 6.0, 6.0, 6.0],
            "breakdown": [0.0, 1.0, 1.0, 1.0],
            "band_share": [0.3, 0.4, 0.5, 0.6],
            "arrears": [1.0, 2.0, 3.0, 4.0],
        }
    )
    summary = tipping_summary(grid)

    assert summary.height == 2
    first = summary.filter(pl.col("nominal_pressure") == 0.01).row(0, named=True)
    assert first["mean_crossed"] == pytest.approx(5.5)
    assert first["breakdown_share"] == pytest.approx(0.5)
    assert first["runs"] == 2


def test_a_small_real_batch_writes_an_artifact_its_report_can_be_rebuilt_from(
    tmp_path: Path,
) -> None:
    """The reproducibility claim: the report is a function of the artifact, not of the run."""
    result = run_p12(
        REPO_ROOT,
        replicates=1,
        grid_replicates=1,
        ticks=48,
        warmup_ticks=12,
        output_dir=tmp_path / "batch",
        report_dir=tmp_path / "reports",
    )
    directory = result.directory
    loaded = load_p12(directory)

    assert (tmp_path / "reports" / "policy-robustness.md").exists()
    for name in (
        "mechanism_readings.parquet",
        "levels.parquet",
        "decisions.parquet",
        "tipping_grid.parquet",
        "tipping_summary.parquet",
        "manifest.json",
    ):
        assert (directory / name).exists(), name

    assert loaded.verdicts.height == len(MECHANISM_IDS)
    for arm in loaded.arms:
        assert arm.policy in POLICY_ARMS
        assert arm.status in {"ran", "refused"}
    ran = [arm for arm in loaded.arms if arm.status == "ran"]
    assert ran, "at least the declared rule arm must run"
    assert all(arm.readings.height == len(MECHANISM_IDS) for arm in ran)


def test_a_refused_runtime_arm_is_recorded_with_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The switch, not the ambient environment, decides: off means a recorded refusal.

    The test declares the condition it is about. Left to the process environment it would pass or
    fail depending on whether an operator had exported `USTC_LLM_ENABLED=1` for a P08 run, and in
    that state it would call the live endpoint from a test — which RULES 13 forbids and which the
    arm is not being asked about here.
    """
    monkeypatch.setenv("USTC_LLM_ENABLED", "0")
    arm = run_policy_arm("ustc", replicates=1, ticks=36, warmup_ticks=12)

    assert arm.status == "refused"
    assert "confirmed runtime model" in arm.reason or "disabled" in arm.reason
    assert arm.readings.is_empty()
