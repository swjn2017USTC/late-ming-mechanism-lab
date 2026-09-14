"""The P12 experiment: the same world under four decision policies, and what changes when it does.

The question is not whether one policy looks more historical. It is whether the *mechanisms* the
model produces survive a change of decision policy, and where a difference shows up as a level
rather than as a mechanism. So every arm runs the same configuration, the same parameter values and
the same random numbers — replicate *r* of every policy starts from root seed ``base_seed + r`` —
and the readings are the declared mechanism verdicts plus the run's own outcome scalars.

```text
rule      a declared threshold table
utility   a bounded linear objective
random    a seeded control
ustc      the runtime model, which fails closed unless the model id is operator-confirmed
```

Three verdict rules, declared here and applied to whatever arms actually ran:

- a policy **shows** a mechanism when at least half of its replicates have it;
- a mechanism is **robust** when three or more arms show it, **mixed** at two, **model-dependent**
  at exactly one, and **absent** at none. With the runtime arm refused, the verdicts are computed
  over the arms that ran, and the report says so in the same paragraph as the numbers;
- the tipping question is answered by where the breakdown region *is* under each policy, not by
  whether the run looked bad: the grid reports the crossed-line count and the breakdown indicator
  per cell, and the region has moved when the cells that break down are not the same cells.

The runtime arm is wired and refused. Nothing here pretends a scripted answer is a model's answer:
if the gate is closed, the arm's row says so, and no conclusion is drawn from an arm that did not
run.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.analysis.mechanisms import MECHANISM_IDS, MechanismReading, mechanism_readings
from late_ming_lab.calibration.summary_stats import scalar
from late_ming_lab.evidence.provenance import git_provenance
from late_ming_lab.experiments.counterfactual import compare_metrics
from late_ming_lab.experiments.institutional_smoke import run_institutional
from late_ming_lab.experiments.interventions import (
    ArmConfiguration,
    baseline_configuration,
    configuration_hash,
)
from late_ming_lab.policies.base import PolicyError

#: The four arms the phase compares, in the order the matrix reports them.
POLICY_ARMS: Final[tuple[str, ...]] = ("rule", "utility", "random", "ustc")

#: The reference arm: differences are read against it, and the report says which one it is.
REFERENCE_POLICY: Final[str] = "rule"

#: The arm that runs a model. A mechanism only this arm shows is *model-dependent*; one that a
#: single declared rule shows is *policy-dependent*, and the two are not the same claim.
RUNTIME_POLICY: Final[str] = "ustc"

#: The main comparison: six replicates per arm, 240 ticks, common random numbers.
DEFAULT_REPLICATES: Final[int] = 6
TICK_COUNT: Final[int] = 240
WARMUP_TICKS: Final[int] = 24
BASE_SEED: Final[int] = 20_260_916

#: The tipping grid: fiscal pressure against climate severity, three values each, three replicates.
GRID_PRESSURE: Final[tuple[float, ...]] = (0.01, 0.02, 0.04)
GRID_SEVERITY: Final[tuple[float, ...]] = (0.3, 0.6, 0.9)
GRID_REPLICATES: Final[int] = 2

#: A policy shows a mechanism when at least this share of its replicates has it.
SHOWING_SHARE: Final[float] = 0.5

#: How many showing arms make a mechanism robust.
ROBUST_ARMS: Final[int] = 3

#: The outcome metrics the level comparison reads, in the report's order.
LEVEL_METRICS: Final[tuple[str, ...]] = (
    "indicators_crossed_end",
    "breakdown",
    "receipts_over_quota_total",
    "tax_base_change_mu",
    "military_pay_arrears_end_tael",
    "largest_band_share_max",
    "bands_at_end",
    "households_exited",
    "market_active_link_share",
)

OUTPUT_ROOT: Final[str] = "outputs/experiments"
BATCH_LABEL: Final[str] = "p12-robustness"
REPORT_NAME: Final[str] = "policy-robustness.md"
REPORT_DIR: Final[str] = "docs/experiments"


class RobustnessError(RuntimeError):
    """Raised when the comparison cannot be made as declared."""


@dataclass(frozen=True, slots=True)
class P12Result:
    """Everything one P12 batch produced, read as attributes rather than dictionary keys."""

    arms: tuple[PolicyArmResult, ...]
    matrix: pl.DataFrame
    verdicts: pl.DataFrame
    levels: pl.DataFrame
    grid: pl.DataFrame
    summary: pl.DataFrame
    movement: pl.DataFrame
    directory: Path
    report: Path


@dataclass(frozen=True, slots=True)
class PolicyArmResult:
    """One arm: whether it ran, what it showed, and the traces it left."""

    policy: str
    status: str  # "ran" or "refused"
    reason: str
    readings: pl.DataFrame
    levels: pl.DataFrame
    traces: pl.DataFrame
    refusals: pl.DataFrame

    def showing(self, mechanism: str) -> bool:
        if self.status != "ran":
            return False
        rows = self.readings.filter(pl.col("mechanism") == mechanism)
        if rows.is_empty():
            return False
        return scalar(rows["present"].cast(pl.Float64).mean()) >= SHOWING_SHARE


def run_policy_arm(
    policy: str,
    *,
    replicates: int = DEFAULT_REPLICATES,
    base_seed: int = BASE_SEED,
    ticks: int = TICK_COUNT,
    warmup_ticks: int = WARMUP_TICKS,
    config: ArmConfiguration | None = None,
) -> PolicyArmResult:
    """Run one policy across the replicates, or record why it could not be run.

    A policy that refuses — the runtime model when its id is not confirmed — leaves an arm with no
    readings. That is a result about the phase's configuration, and the matrix prints it as such
    rather than imputing anything from the other arms.
    """
    arm = config or baseline_configuration()
    reading_rows: list[dict[str, object]] = []
    level_rows: list[dict[str, object]] = []
    trace_frames: list[pl.DataFrame] = []
    refusal_frames: list[pl.DataFrame] = []
    for replicate in range(replicates):
        try:
            run = run_institutional(
                policy=policy,
                config=arm,
                ticks=ticks,
                warmup_ticks=warmup_ticks,
                seed=base_seed + replicate,
            )
        except PolicyError as error:
            return PolicyArmResult(
                policy=policy,
                status="refused",
                reason=str(error),
                readings=_empty_readings(),
                levels=pl.DataFrame(),
                traces=pl.DataFrame(),
                refusals=pl.DataFrame(),
            )
        for reading in mechanism_readings(run.events):
            reading_rows.append(_reading_row(policy, replicate, reading))
        level_rows.append({"label": policy, "replicate": replicate, **run.outcomes})
        trace_frames.append(
            run.traces.with_columns(
                pl.lit(policy).alias("policy"), pl.lit(replicate).alias("replicate")
            )
        )
        refusal_frames.append(
            run.refusals.with_columns(
                pl.lit(policy).alias("policy"), pl.lit(replicate).alias("replicate")
            )
        )
    return PolicyArmResult(
        policy=policy,
        status="ran",
        reason="",
        readings=pl.DataFrame(reading_rows),
        levels=pl.DataFrame(level_rows),
        traces=pl.concat(trace_frames, how="diagonal_relaxed") if trace_frames else pl.DataFrame(),
        refusals=(
            pl.concat(refusal_frames, how="diagonal_relaxed") if refusal_frames else pl.DataFrame()
        ),
    )


def _reading_row(policy: str, replicate: int, reading: MechanismReading) -> dict[str, object]:
    return {
        "label": policy,
        "replicate": replicate,
        "mechanism": reading.mechanism,
        "present": 1.0 if reading.present else 0.0,
        "strength": reading.strength,
        "reading": reading.reading,
    }


def _empty_readings() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "label": pl.String,
            "replicate": pl.Int64,
            "mechanism": pl.String,
            "present": pl.Float64,
            "strength": pl.Float64,
            "reading": pl.String,
        }
    )


def run_policy_tipping(
    policy: str,
    *,
    replicates: int = GRID_REPLICATES,
    base_seed: int = BASE_SEED,
    ticks: int = TICK_COUNT,
    warmup_ticks: int = WARMUP_TICKS,
    config: ArmConfiguration | None = None,
) -> pl.DataFrame:
    """The tipping grid for one policy: pressure against severity, with the crisis readings."""
    arm = config or baseline_configuration()
    rows: list[dict[str, object]] = []
    for pressure in GRID_PRESSURE:
        for severity in GRID_SEVERITY:
            varied = arm.with_updates(
                scenario=replace(arm.scenario, nominal_pressure=pressure, severity_floor=severity)
            )
            for replicate in range(replicates):
                try:
                    run = run_institutional(
                        policy=policy,
                        config=varied,
                        ticks=ticks,
                        warmup_ticks=warmup_ticks,
                        seed=base_seed + replicate,
                    )
                except PolicyError as error:
                    raise RobustnessError(
                        f"the {policy} arm refused during the grid: {error}"
                    ) from error
                rows.append(
                    {
                        "policy": policy,
                        "nominal_pressure": pressure,
                        "severity_floor": severity,
                        "replicate": replicate,
                        "crossed": run.outcomes["indicators_crossed_end"],
                        "breakdown": run.outcomes["breakdown"],
                        "band_share": run.outcomes["largest_band_share_max"],
                        "arrears": run.outcomes["military_pay_arrears_end_tael"],
                    }
                )
    return pl.DataFrame(rows)


def mechanism_matrix(arms: tuple[PolicyArmResult, ...]) -> pl.DataFrame:
    """Rows are mechanisms, columns are policies: the share of replicates showing each."""
    rows: list[dict[str, object]] = []
    for mechanism in MECHANISM_IDS:
        row: dict[str, object] = {"mechanism": mechanism}
        for arm in arms:
            if arm.status != "ran":
                row[arm.policy] = None
                continue
            readings = arm.readings.filter(pl.col("mechanism") == mechanism)
            row[arm.policy] = (
                scalar(readings["present"].mean()) if not readings.is_empty() else None
            )
        rows.append(row)
    return pl.DataFrame(rows)


def robustness_verdicts(arms: tuple[PolicyArmResult, ...]) -> pl.DataFrame:
    """Per mechanism: which arms show it, and the verdict the declared rules give."""
    ran = tuple(arm for arm in arms if arm.status == "ran")
    if not ran:
        raise RobustnessError("no arm ran, so there is nothing to compare")
    rows: list[dict[str, object]] = []
    for mechanism in MECHANISM_IDS:
        showing = tuple(arm.policy for arm in ran if arm.showing(mechanism))
        ran_count = len(ran)
        runtime_ran = any(arm.policy == RUNTIME_POLICY and arm.status == "ran" for arm in ran)
        if not showing:
            verdict = "absent"
        elif len(showing) >= min(ROBUST_ARMS, ran_count):
            verdict = "robust"
        elif len(showing) == 1:
            # One arm is a statement about *that policy*: whether it is the phase's model-dependent
            # case or only a policy-dependent one depends on which arm it is, not on the count.
            if runtime_ran and showing[0] == RUNTIME_POLICY:
                verdict = "model-dependent"
            else:
                verdict = "policy-dependent"
        else:
            verdict = "mixed"
        rows.append(
            {
                "mechanism": mechanism,
                "arms_showing": len(showing),
                "arms_ran": ran_count,
                "showing_policies": ",".join(showing),
                "verdict": verdict,
            }
        )
    return pl.DataFrame(rows)


def level_comparison(arms: tuple[PolicyArmResult, ...]) -> pl.DataFrame:
    """Paired level differences against the reference arm, under common random numbers."""
    frames = [arm.levels for arm in arms if arm.status == "ran"]
    if not frames:
        raise RobustnessError("no arm ran, so there is nothing to compare")
    stacked = pl.concat(frames, how="diagonal_relaxed")
    present = [metric for metric in LEVEL_METRICS if metric in stacked.columns]
    compared = [
        arm.policy for arm in arms if arm.policy != REFERENCE_POLICY and arm.status == "ran"
    ]
    return compare_metrics(stacked, baseline=REFERENCE_POLICY, metrics=present, arms=compared)


def tipping_summary(grid: pl.DataFrame) -> pl.DataFrame:
    """Per policy and cell: the crossed-line count and the breakdown share."""
    return (
        grid.group_by("policy", "nominal_pressure", "severity_floor")
        .agg(
            [
                pl.col("crossed").mean().alias("mean_crossed"),
                pl.col("breakdown").mean().alias("breakdown_share"),
                pl.col("band_share").median().alias("median_band_share"),
                pl.len().alias("runs"),
            ]
        )
        .sort("policy", "nominal_pressure", "severity_floor")
    )


def region_movement(summary: pl.DataFrame) -> pl.DataFrame:
    """Whether the breakdown region sits in the same cells under every policy.

    The region is the set of grid cells where any run breaks down. Two policies have the same region
    when those sets are equal; the verdict is per policy against the reference arm, so a shifted
    region is visible as a difference rather than as a claim about "the tipping point".
    """
    cells = (
        summary.filter(pl.col("breakdown_share") > 0.0)
        .group_by("policy")
        .agg(
            [
                pl.col("nominal_pressure").alias("pressure_cells"),
                pl.col("severity_floor").alias("severity_cells"),
            ]
        )
    )
    reference = cells.filter(pl.col("policy") == REFERENCE_POLICY)
    reference_cells: set[tuple[float, float]] = set()
    if not reference.is_empty():
        reference_cells = {
            (float(pressure), float(severity))
            for pressure, severity in zip(
                reference["pressure_cells"][0], reference["severity_cells"][0], strict=True
            )
        }
    rows: list[dict[str, object]] = []
    for row in cells.iter_rows(named=True):
        policy_cells = {
            (float(p), float(s))
            for p, s in zip(row["pressure_cells"], row["severity_cells"], strict=True)
        }
        rows.append(
            {
                "policy": row["policy"],
                "cells_with_breakdown": len(policy_cells),
                "same_as_reference": policy_cells == reference_cells,
                "cells": ",".join(f"{p:g}x{s:g}" for p, s in sorted(policy_cells)),
            }
        )
    return pl.DataFrame(rows)


def run_p12(
    root: str | Path,
    *,
    replicates: int = DEFAULT_REPLICATES,
    grid_replicates: int = GRID_REPLICATES,
    base_seed: int = BASE_SEED,
    ticks: int = TICK_COUNT,
    warmup_ticks: int = WARMUP_TICKS,
    output_dir: str | Path | None = None,
    report_dir: str | Path | None = None,
    policies: tuple[str, ...] = POLICY_ARMS,
) -> P12Result:
    """Run the arms and the grid, write the artifacts, and write the report."""
    directory = Path(root)
    target = Path(output_dir) if output_dir is not None else directory / OUTPUT_ROOT / BATCH_LABEL
    target.mkdir(parents=True, exist_ok=True)
    arms = tuple(
        run_policy_arm(
            policy,
            replicates=replicates,
            base_seed=base_seed,
            ticks=ticks,
            warmup_ticks=warmup_ticks,
        )
        for policy in policies
    )
    grids: list[pl.DataFrame] = []
    for arm in arms:
        if arm.status != "ran":
            continue
        grids.append(
            run_policy_tipping(
                arm.policy,
                replicates=grid_replicates,
                base_seed=base_seed,
                ticks=ticks,
                warmup_ticks=warmup_ticks,
            )
        )
    grid = pl.concat(grids, how="diagonal_relaxed") if grids else pl.DataFrame()
    matrix = mechanism_matrix(arms)
    verdicts = robustness_verdicts(arms)
    levels = level_comparison(arms)
    summary = tipping_summary(grid) if not grid.is_empty() else pl.DataFrame()
    movement = region_movement(summary) if not summary.is_empty() else pl.DataFrame()
    for name, frame in (
        ("mechanism_readings", pl.concat([arm.readings for arm in arms if arm.status == "ran"])),
        ("levels", pl.concat([arm.levels for arm in arms if arm.status == "ran"])),
        ("decisions", pl.concat([arm.traces for arm in arms if arm.status == "ran"])),
        ("tipping_grid", grid),
        ("tipping_summary", summary),
    ):
        if not frame.is_empty():
            frame.write_parquet(target / f"{name}.parquet")
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "policy-robustness-v1",
                "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                "git_sha": git_provenance(directory).git_sha,
                "policies": list(policies),
                "replicates": replicates,
                "grid_replicates": grid_replicates,
                "ticks": ticks,
                "warmup_ticks": warmup_ticks,
                "seed_rule": (
                    "root_seed = base_seed + replicate: replicate r of every policy starts from "
                    "the same random numbers"
                ),
                "base_seed": base_seed,
                "arm_status": {
                    arm.policy: {
                        "status": arm.status,
                        "reason": arm.reason,
                        "decisions": arm.traces.height,
                    }
                    for arm in arms
                },
                "arm_configuration_hash": configuration_hash(baseline_configuration()),
                "note": (
                    "the runtime arm is refused by the model gate when the configured model id is "
                    "not the operator-confirmed one; the report draws no conclusion from an arm "
                    "that did not run"
                ),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    report = write_report(
        root,
        arms=arms,
        matrix=matrix,
        verdicts=verdicts,
        levels=levels,
        summary=summary,
        movement=movement,
        directory=target,
        output_dir=report_dir,
    )
    return P12Result(
        arms=arms,
        matrix=matrix,
        verdicts=verdicts,
        levels=levels,
        grid=grid,
        summary=summary,
        movement=movement,
        directory=target,
        report=report,
    )


def mechanism_effect(arms: tuple[PolicyArmResult, ...]) -> pl.DataFrame:
    """Per mechanism and policy: the presence share and the median strength, for the report."""
    rows: list[dict[str, object]] = []
    for arm in arms:
        for mechanism in MECHANISM_IDS:
            if arm.status != "ran":
                rows.append(
                    {
                        "mechanism": mechanism,
                        "policy": arm.policy,
                        "present_share": None,
                        "median_strength": None,
                        "status": arm.status,
                    }
                )
                continue
            readings = arm.readings.filter(pl.col("mechanism") == mechanism)
            rows.append(
                {
                    "mechanism": mechanism,
                    "policy": arm.policy,
                    "present_share": (
                        scalar(readings["present"].mean()) if not readings.is_empty() else None
                    ),
                    "median_strength": (
                        scalar(readings["strength"].median()) if not readings.is_empty() else None
                    ),
                    "status": arm.status,
                }
            )
    return pl.DataFrame(rows)


def _table(frame: pl.DataFrame, columns: Sequence[str] | None = None) -> str:
    """A markdown table, floats shortened so a row stays readable and None printed as an em dash."""
    selected = frame.select(list(columns)) if columns is not None else frame
    header = "| " + " | ".join(selected.columns) + " |"
    rule = "| " + " | ".join("---" for _ in selected.columns) + " |"
    lines = [header, rule]
    for row in selected.iter_rows():
        cells = []
        for value in row:
            if value is None:
                cells.append("—")
            elif isinstance(value, float):
                cells.append(f"{value:.4g}")
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_report(
    root: str | Path,
    *,
    arms: tuple[PolicyArmResult, ...],
    matrix: pl.DataFrame,
    verdicts: pl.DataFrame,
    levels: pl.DataFrame,
    summary: pl.DataFrame,
    movement: pl.DataFrame,
    directory: str | Path,
    output_dir: str | Path | None = None,
) -> Path:
    """Write the P12 report: the five questions, the matrix, and the caveats that limit them."""
    effects = mechanism_effect(arms)
    text = _report_text(
        arms=arms,
        matrix=matrix,
        verdicts=verdicts,
        levels=levels,
        summary=summary,
        movement=movement,
        effects=effects,
        directory=Path(directory),
    )
    base = Path(output_dir) if output_dir is not None else Path(root) / REPORT_DIR
    base.mkdir(parents=True, exist_ok=True)
    path = base / REPORT_NAME
    path.write_text(text, encoding="utf-8")
    return path


def _report_text(
    *,
    arms: tuple[PolicyArmResult, ...],
    matrix: pl.DataFrame,
    verdicts: pl.DataFrame,
    levels: pl.DataFrame,
    summary: pl.DataFrame,
    movement: pl.DataFrame,
    effects: pl.DataFrame,
    directory: Path,
) -> str:
    refused = [arm for arm in arms if arm.status != "ran"]
    ran = [arm for arm in arms if arm.status == "ran"]
    decisions = pl.concat([arm.traces for arm in ran]) if ran else pl.DataFrame()
    lines = [
        "# P12 robustness: the same world under four decision policies",
        "",
        f"Artifacts: `{directory.name}`. {len(ran)} arms ran with {DEFAULT_REPLICATES} replicates "
        f"each over {TICK_COUNT} ticks, and a {len(GRID_PRESSURE)} by {len(GRID_SEVERITY)} grid of "
        f"fiscal pressure against climate severity with {GRID_REPLICATES} replicates per cell.",
        "",
        "Every arm runs the same configuration, the same parameter values and the same random",
        "numbers: replicate *r* of every policy starts from root seed `base_seed + r`. A",
        "difference between arms at the same replicate is the decision policy and nothing else.",
        "",
        "## The arms",
        "",
        "| policy | status | decisions | replicates | reason if refused |",
        "| --- | --- | --- | --- | --- |",
    ]
    for arm in arms:
        reason = arm.reason.replace("|", "/") if arm.reason else "—"
        lines.append(
            f"| `{arm.policy}` | {arm.status} | {arm.traces.height} | "
            f"{arm.levels.height if arm.status == 'ran' else 0} | {reason} |"
        )
    lines += [
        "",
        "## The robustness matrix",
        "",
        "A cell is the share of that arm's replicates in which the mechanism is present. An",
        "em dash means the arm did not run: nothing is imputed for it.",
        "",
        _table(matrix),
        "",
        "Verdict rules, declared before the runs: a policy *shows* a mechanism when half its",
        "replicates or more have it; *robust* when three or more arms show it, *mixed* at two,",
        "*model-dependent* when the runtime arm is the only one that shows it, *policy-dependent*",
        "when a single declared policy is, and *absent* when none does. The verdicts cover the",
        "arms that ran; where the runtime arm did not, nothing is imputed for it.",
        "",
        _table(
            verdicts,
            ["mechanism", "arms_showing", "arms_ran", "showing_policies", "verdict"],
        ),
        "",
        "## The five questions",
        "",
        "### 1 and 2. Extraction inversion and the fiscal-military ratchet",
        "",
        "Both are read off the same arms as everything else. What the matrix says, in words:",
        "",
        _table(
            effects,
            ["mechanism", "policy", "status", "present_share", "median_strength"],
        ),
        "",
        "### 3. Does the crisis tipping region move?",
        "",
        "The grid varies fiscal pressure and climate severity and reads the crisis off the",
        "governance line count and the breakdown indicator, per cell and per policy.",
        "",
        _table(summary) if not summary.is_empty() else "The grid did not run.",
        "",
        "Cells where any run breaks down, and whether they match the reference arm's cells:",
        "",
        _table(movement) if not movement.is_empty() else "No cell broke down in any arm.",
        "",
        "### 4. Does armed-band consolidation depend on the model?",
        "",
        "The band mechanism's row in the matrix answers this directly. It is shown by the arms",
        "that showed it, and the verdict is *model-dependent* only when the arm that showed it is",
        "the runtime one; a mechanism a single declared policy shows is *policy-dependent*.",
        "",
        "### 5. Levels or mechanisms?",
        "",
        "Paired level differences against the reference arm, on the same replicates:",
        "",
        _table(levels) if not levels.is_empty() else "No arm ran.",
        "",
        "Reading the two tables together is the phase's answer. Where the mechanism rows agree",
        "across arms while the level rows move, the policy changed *how much*. Where a mechanism",
        "row itself changes across arms, the policy changed *what the model does* — and that is a",
        "claim about the decision rule, not about history.",
        "",
        "## What this cannot say",
        "",
        f"- **The runtime arm did not run.** {len(refused)} arm(s) were refused by the model gate: "
        + ("; ".join(f"`{arm.policy}`: {arm.reason}" for arm in refused) if refused else "none"),
        "",
        "  The configured runtime model id is not the operator-confirmed one, so no live call was",
        "  made and no conclusion is drawn about a model-backed policy. A mechanism no arm",
        "  showed is *not* evidence an LLM-backed policy would not show it: it is a statement",
        "  about the three declared policies that ran.",
        f"- **{len(decisions)} decisions** across every arm: not a large decision experiment, "
        "and the seats are a handful.",
        f"- **The grid is {GRID_REPLICATES} replicates per cell per arm**, so a breakdown share "
        "there is a coarse reading of where the region is, not a probability.",
        "- **The mechanisms are the three P12 declared**: extraction inversion, the",
        "  fiscal-military ratchet and band consolidation. Nothing else was looked for.",
        "",
    ]
    return "\n".join(lines)


def load_p12(directory: str | Path) -> P12Result:
    """Read a P12 batch back and regenerate its report without re-running the model.

    The report's whole claim to trustworthiness is that it is computed from the artifact; this is
    what makes that checkable, and it is what the suite uses to keep the report from drifting.
    """
    source = Path(directory)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    readings = pl.read_parquet(source / "mechanism_readings.parquet")
    levels = pl.read_parquet(source / "levels.parquet")
    decisions = pl.read_parquet(source / "decisions.parquet")
    grid = pl.read_parquet(source / "tipping_grid.parquet")
    arms: list[PolicyArmResult] = []
    for policy in manifest["policies"]:
        status = manifest["arm_status"][policy]["status"]
        arm_readings = readings.filter(pl.col("label") == policy)
        arm_levels = levels.filter(pl.col("label") == policy)
        arms.append(
            PolicyArmResult(
                policy=policy,
                status=status,
                reason=str(manifest["arm_status"][policy]["reason"]),
                readings=arm_readings,
                levels=arm_levels,
                traces=decisions.filter(pl.col("policy") == policy),
                refusals=pl.DataFrame(),
            )
        )
    summary = pl.read_parquet(source / "tipping_summary.parquet")
    return P12Result(
        arms=tuple(arms),
        matrix=mechanism_matrix(tuple(arms)),
        verdicts=robustness_verdicts(tuple(arms)),
        levels=level_comparison(tuple(arms)),
        grid=grid,
        summary=summary,
        movement=region_movement(summary) if not summary.is_empty() else pl.DataFrame(),
        directory=source,
        report=source / REPORT_NAME,
    )
