"""The P10 invariants: the arms, the runner's seeding, the comparison rules and the outcomes.

The expensive parts of P10 — the ablation, Morris, Sobol and grid batches — are the phase's
artifact, not its test suite. What the suite defends is the machinery a reader has to be able to
trust: that the nine required ablations exist and change only what they declare, that replicate *r*
of every arm shares a root seed, that a design row moves only its own parameters, that the
comparison rules say what they claim, and that the outcome readings hold their invariants.

One real run of each kind is made where a run is the only way to see the property; everything
else is pure arithmetic over the declared tables.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from late_ming_lab.analysis.outcomes import BREAKDOWN_INDICATORS, BREAKDOWN_SAMPLE_EVERY
from late_ming_lab.calibration.summary_stats import scalar
from late_ming_lab.evidence.cards import load_cards
from late_ming_lab.experiments.counterfactual import (
    BREAKDOWN_LINES,
    ComparisonError,
    cliffs_delta_of,
    collapse_probability,
    interaction_effect,
    line_sensitivity,
    paired_comparison,
    response_curve,
    time_to_breakdown_summary,
    wilson_interval,
    with_breakdown_lines,
)
from late_ming_lab.experiments.interventions import (
    BASELINE,
    FIELD_BY_PARAMETER_SET,
    INTERVENTIONS,
    JOINT_ARMS,
    arm_configuration,
    baseline_configuration,
    configuration_diff,
    configuration_hash,
    declared_arms,
)
from late_ming_lab.experiments.runner import (
    DESIGN_COLUMNS,
    Job,
    ablation_jobs,
    design_jobs,
    grid_jobs,
    run_jobs,
)
from late_ming_lab.experiments.sensitivity import sweep_parameters

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The nine ablations the plan names, verbatim. They are the phase's requirement, so they are pinned
#: as a set: an arm renamed or dropped breaks this test rather than going unnoticed.
REQUIRED_ABLATIONS = (
    "NO_DROUGHT",
    "NO_EXTRACTION_ESCALATION",
    "FULL_MILITARY_PAY",
    "HIGH_RELIEF",
    "NO_ELITE_CREDIT",
    "NO_TRADE_DISRUPTION",
    "NO_BAND_MERGER",
    "LOW_REPRESSION",
    "OPEN_MIGRATION_EXIT",
)


def test_the_required_ablations_are_exactly_the_declared_ones() -> None:
    assert tuple(intervention.name for intervention in INTERVENTIONS) == REQUIRED_ABLATIONS
    assert set(declared_arms()) == {BASELINE, *REQUIRED_ABLATIONS} | {
        arm.name for arm in JOINT_ARMS
    }
    assert len(declared_arms()) == len(set(declared_arms()))


def test_each_arm_changes_only_what_it_declares() -> None:
    """The difference is computed, so a report cannot claim a change the arm does not make."""
    baseline = baseline_configuration()
    expected = {
        "NO_DROUGHT": {"scenario.monthly_event_probability", "scenario.severity_floor"},
        "NO_EXTRACTION_ESCALATION": {"extraction_policy"},
        "FULL_MILITARY_PAY": {"scenario.pay_share_of_treasury"},
        "HIGH_RELIEF": {
            "capacity.relief",
            "fiscal.relief_share_of_need",
            "fiscal.relief_eligibility_unmet_ratio",
            "elite.relief_share_of_grain_stock",
            "elite.relief_eligibility_unmet_ratio",
        },
        "NO_ELITE_CREDIT": {"elite.loan_to_value"},
        "NO_TRADE_DISRUPTION": {"disruption"},
        "NO_BAND_MERGER": {"band.merge_cohesion_above"},
        "LOW_REPRESSION": {"military.suppression_effectiveness"},
        "OPEN_MIGRATION_EXIT": {
            "household.permanent_migration_unmet_ratio",
            "household.temporary_migration_unmet_ratio",
            "migration.cost_tael_per_household",
            "migration.cost_tael_per_adult",
            "migration.transit_loss_share",
            "migration.minimum_households_to_move",
        },
    }
    for name, fields in expected.items():
        changed = {field for field, _, _ in configuration_diff(baseline, arm_configuration(name))}
        assert changed == fields, name
    for arm in JOINT_ARMS:
        singles = {part for part in arm.name.removeprefix("JOINT_").split("+")}
        joint = {field for field, _, _ in configuration_diff(baseline, arm_configuration(arm.name))}
        union: set[str] = set()
        for single in singles:
            union |= {
                field for field, _, _ in configuration_diff(baseline, arm_configuration(single))
            }
        assert joint == union, arm.name


def test_the_baseline_is_the_sandbox_plus_the_two_declared_regimes() -> None:
    """The reference arm is declared, and its hash separates it from any other configuration."""
    baseline = baseline_configuration()
    assert baseline.scenario.monthly_event_probability > 0.0
    assert baseline.extraction_policy.name == "arrears-escalation"
    assert baseline.disruption.name == "p10-baseline"
    assert configuration_hash(baseline) != configuration_hash(arm_configuration("NO_DROUGHT"))
    assert configuration_hash(baseline) == configuration_hash(baseline_configuration())


def test_a_draw_moves_only_the_parameters_it_names() -> None:
    sweep = sweep_parameters(load_cards(REPO_ROOT))
    design = pl.DataFrame({"run": [0], sweep[0].name: [sweep[0].low + 0.01]})
    jobs = design_jobs(design)
    assert len(jobs) == 1
    assert dict(jobs[0].draw) == {sweep[0].name: sweep[0].low + 0.01}
    assert "run" not in dict(jobs[0].draw)


def test_a_grid_covers_the_cartesian_product_with_replicates() -> None:
    values = {"a": [1.0, 2.0], "b": [10.0, 20.0, 30.0]}
    jobs = grid_jobs(["a", "b"], values, replicates=3)

    assert len(jobs) == 2 * 3 * 3
    assert len({job.replicate for job in jobs}) == 3
    assert len({job.label for job in jobs}) == 6
    assert all("run" not in dict(job.draw) for job in jobs)


def test_ablation_jobs_pair_every_arm_with_every_replicate() -> None:
    jobs = ablation_jobs(replicates=3)

    assert len(jobs) == len(declared_arms()) * 3
    for replicate in range(3):
        labels = {job.label for job in jobs if job.replicate == replicate}
        assert labels == set(declared_arms())


def test_wilson_interval_brackets_the_share_and_widens_when_trials_are_few() -> None:
    low, high = wilson_interval(0, 12)
    assert low == 0.0 and 0.0 < high < 0.5
    assert wilson_interval(6, 12)[0] < 0.5 < wilson_interval(6, 12)[1]
    assert wilson_interval(0, 0) == (0.0, 0.0)
    wide = wilson_interval(1, 2)
    narrow = wilson_interval(500, 1000)
    assert (wide[1] - wide[0]) > (narrow[1] - narrow[0])


def test_paired_comparison_aligns_on_the_replicate_and_reports_the_distribution() -> None:
    runs = pl.DataFrame(
        {
            "label": [BASELINE] * 4 + ["ARM"] * 4,
            "replicate": [0, 1, 2, 3] * 2,
            "metric": [1.0, 2.0, 3.0, 4.0, 2.0, 3.0, 4.0, 6.0],
        }
    )
    comparison = paired_comparison(runs, metric="metric", baseline=BASELINE, arm="ARM", seed=1)

    assert comparison.replicates == 4
    assert comparison.median_difference == pytest.approx(1.0)
    assert comparison.share_increase == pytest.approx(1.0)
    assert comparison.resolved
    assert comparison.direction == "up"
    assert -1.0 <= comparison.cliffs_delta <= 1.0
    assert comparison.cliffs_delta > 0.0


def test_paired_comparison_refuses_arms_that_do_not_share_replicates() -> None:
    runs = pl.DataFrame(
        {
            "label": [BASELINE, BASELINE, "ARM"],
            "replicate": [0, 1, 0],
            "metric": [1.0, 2.0, 3.0],
        }
    )
    with pytest.raises(ComparisonError, match="different replicate sets"):
        paired_comparison(runs, metric="metric", baseline=BASELINE, arm="ARM", seed=1)


def test_a_flat_difference_is_reported_unresolved() -> None:
    """An interval that covers zero must not be read as a direction."""
    runs = pl.DataFrame(
        {
            "label": [BASELINE] * 4 + ["ARM"] * 4,
            "replicate": [0, 1, 2, 3] * 2,
            "metric": [1.0, 2.0, 3.0, 4.0, 1.0, 2.0, 3.0, 4.0],
        }
    )
    comparison = paired_comparison(runs, metric="metric", baseline=BASELINE, arm="ARM", seed=1)

    assert comparison.median_difference == 0.0
    assert not comparison.resolved
    assert comparison.direction == "unresolved"


def test_interaction_is_the_joint_effect_minus_the_sum_of_the_parts() -> None:
    runs = pl.DataFrame(
        {
            "label": [BASELINE] * 3 + ["A"] * 3 + ["B"] * 3 + ["JOINT"] * 3,
            "replicate": [0, 1, 2] * 4,
            "metric": [0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 5.0, 5.0, 5.0],
        }
    )
    effect = interaction_effect(
        runs, metric="metric", baseline=BASELINE, single_a="A", single_b="B", joint="JOINT", seed=1
    )

    assert effect.effect_a == pytest.approx(1.0)
    assert effect.effect_b == pytest.approx(2.0)
    assert effect.effect_joint == pytest.approx(5.0)
    assert effect.interaction == pytest.approx(2.0)
    assert effect.direction == "super-additive"


def test_response_curve_reads_a_straight_line_as_zero_curvature_and_a_bend_as_a_spike() -> None:
    straight = pl.DataFrame({"x": [float(i) for i in range(20)], "y": [2.0 * i for i in range(20)]})
    curved = pl.DataFrame(
        {"x": [float(i) for i in range(20)], "y": [0.0 if i < 10 else 100.0 for i in range(20)]}
    )
    flat_curve = response_curve(straight, parameter="x", metric="y", bins=4)
    bent_curve = response_curve(curved, parameter="x", metric="y", bins=4)

    flat_peak = scalar(flat_curve["curvature"].max())
    bent_peak = scalar(bent_curve["curvature"].max())
    assert abs(flat_peak) < 1e-6
    assert bent_peak > 0.0
    assert scalar(bent_curve["runs"].sum()) == 20.0


def test_breakdown_lines_are_added_from_the_governance_timeline() -> None:
    runs = pl.DataFrame({"label": [BASELINE], "replicate": [0]})
    governance = pl.DataFrame(
        {
            "label": [BASELINE] * 3,
            "replicate": [0] * 3,
            "tick": [0, 12, 24],
            "crossed": [2, 5, 7],
        }
    )
    enriched = with_breakdown_lines(runs, governance, lines=(5, 6))

    assert enriched["peak_crossed"][0] == 7
    assert enriched["peak_at_least_5"][0] == 1.0
    assert enriched["peak_at_least_6"][0] == 1.0
    probabilities = collapse_probability(enriched, indicator="peak_at_least_5")
    assert probabilities["collapse_probability"][0] == 1.0
    sensitivity = line_sensitivity(enriched, lines=(5, 6))
    assert set(sensitivity["line"]) == {5, 6}
    assert sensitivity["collapse_probability"].to_list() == [1.0, 1.0]


def test_the_never_sentinel_stays_out_of_the_timing_summary() -> None:
    """A median of the sentinel is not a time, and the summary must not average one in."""
    runs = pl.DataFrame(
        {
            "label": [BASELINE] * 3 + ["ARM"] * 3,
            "replicate": [0, 1, 2] * 2,
            "time_to_breakdown": [-1.0, 48.0, 72.0, -1.0, -1.0, -1.0],
        }
    )
    summary = time_to_breakdown_summary(runs)
    baseline = summary.filter(pl.col("label") == BASELINE).row(0, named=True)
    arm = summary.filter(pl.col("label") == "ARM").row(0, named=True)

    assert baseline["runs_reaching_the_line"] == 2
    assert baseline["runs_never_reaching"] == 1
    assert baseline["median_tick"] == pytest.approx(60.0)
    assert arm["runs_reaching_the_line"] == 0
    assert arm["runs_never_reaching"] == 3
    assert arm["median_tick"] is None


def test_the_declared_breakdown_line_is_above_the_calm_baseline_p07_measured() -> None:
    """P07 measured five of eight lines crossing even in calm runs, so the line has to be higher."""
    assert BREAKDOWN_INDICATORS >= 6
    assert max(BREAKDOWN_LINES) == 8
    assert BREAKDOWN_INDICATORS in BREAKDOWN_LINES
    assert BREAKDOWN_SAMPLE_EVERY > 0


def test_a_batch_writes_its_artifact_and_manifest_with_the_arms_it_ran(tmp_path: Path) -> None:
    """One real run of each kind: the artifact, the manifest, and the seed rule."""
    jobs = (
        Job(label=BASELINE, base_arm=BASELINE, replicate=0),
        Job(label="NO_DROUGHT", base_arm="NO_DROUGHT", replicate=0),
        Job(label="NO_DROUGHT", base_arm="NO_DROUGHT", replicate=1),
    )
    batch = run_jobs(
        jobs,
        base_seed=4_242,
        label="invariants",
        output_dir=tmp_path,
        root=REPO_ROOT,
        ticks=36,
        warmup_ticks=12,
    )
    manifest = json.loads((tmp_path / "invariants" / "manifest.json").read_text(encoding="utf-8"))

    assert batch.runs.height == 3
    seeds = {
        (row["label"], row["replicate"]): row["root_seed"]
        for row in batch.runs.iter_rows(named=True)
    }
    # The common-random-numbers pairing: one replicate, one root seed, whatever the arm.
    assert seeds[(BASELINE, 0)] == seeds[("NO_DROUGHT", 0)] == 4_242
    assert seeds[("NO_DROUGHT", 1)] == 4_243
    assert manifest["seed_rule"].startswith("root_seed = base_seed + replicate")
    assert manifest["design"] == {"kind": "arms"}
    assert len(manifest["arms"]) == len(declared_arms())
    assert manifest["arms"]["NO_DROUGHT"]["differences_from_baseline"] == [
        {"field": "scenario.monthly_event_probability", "baseline": "0.4", "arm": "0.0"},
        {"field": "scenario.severity_floor", "baseline": "0.6", "arm": "0.0"},
    ]
    assert (tmp_path / "invariants" / "runs.parquet").exists()
    assert (tmp_path / "invariants" / "governance_timeline.parquet").exists()

    for column in (
        "indicators_crossed_end",
        "market_active_link_share",
        "market_largest_component_share",
        "military_pay_arrears_end_tael",
        "largest_band_share_max",
        "time_to_breakdown",
        "tax_base_change_mu",
        "receipts_over_quota_total",
        "band_merges",
        "elite_loans",
        "suppressions",
        "trade_shipments",
    ):
        assert column in batch.runs.columns
    # `peak_crossed` is derived from the timeline when a report is written, not stored per run.
    assert "peak_crossed" in with_breakdown_lines(batch.runs, batch.governance).columns
    connectivity = batch.runs["market_active_link_share"].to_numpy()
    assert np.all((connectivity >= 0.0) & (connectivity <= 1.0))
    assert (batch.runs["migration_net_node_min"] <= batch.runs["migration_net_node_max"]).all()
    assert (batch.runs["time_to_breakdown"] >= -1.0).all()


def test_a_design_batch_records_its_design_and_applies_only_its_columns(tmp_path: Path) -> None:
    sweep = sweep_parameters(load_cards(REPO_ROOT))
    design = pl.DataFrame(
        {
            "run": [0, 1, 2],
            sweep[0].name: [sweep[0].low, sweep[0].high, (sweep[0].low + sweep[0].high) / 2.0],
        }
    )
    jobs = design_jobs(design, label_prefix="DESIGN")
    batch = run_jobs(
        jobs,
        base_seed=7,
        label="design",
        output_dir=tmp_path,
        root=REPO_ROOT,
        parameter_sets={
            parameter.name: FIELD_BY_PARAMETER_SET[parameter.parameter_set] for parameter in sweep
        },
        ticks=36,
        warmup_ticks=12,
        design={"kind": "custom", "points": 3},
    )
    manifest = json.loads((tmp_path / "design" / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["design"] == {"kind": "custom", "points": 3}
    assert batch.runs.height == 3
    assert DESIGN_COLUMNS[0] not in batch.runs.columns  # the row id is not a draw
    assert sweep[0].name in batch.runs.columns
    assert batch.runs[sweep[0].name].to_list() == pytest.approx(
        [sweep[0].low, sweep[0].high, (sweep[0].low + sweep[0].high) / 2.0]
    )


def test_cliffs_delta_of_identical_samples_is_zero() -> None:
    values = np.array([1.0, 2.0, 3.0, 4.0])
    assert cliffs_delta_of(values, values) == 0.0
    assert cliffs_delta_of(values, values + 10.0) == 1.0
    assert cliffs_delta_of(values, values - 10.0) == -1.0
