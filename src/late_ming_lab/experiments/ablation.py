"""The P10 entry point: run the three experiments, then write the four reports they support.

```bash
uv run python -c "from late_ming_lab.experiments.ablation import run_p10; run_p10('.')"
uv run python -c "from late_ming_lab.experiments.ablation import write_experiment_reports; \\
    write_experiment_reports('.')"
```

Three experiments, all on the P07 sandbox and all under common random numbers:

1. **Ablation** — the baseline, the nine mechanisms the plan names, and three two-way arms, each at
   every replicate. The report is a distributional comparison per metric, not a table of means.
2. **Sensitivity** — a Morris design over every card-bounded scalar parameter, then a Sobol design
   over the parameters Morris selects, with second-order indices so interactions are measured rather
   than assumed.
3. **Tipping** — a two-dimensional grid over the two most influential parameters, to show a region
   rather than two one-dimensional curves.

None of it touches the runtime LLM, and none of it changes a mechanism: an arm is a declared
difference from one baseline configuration, and a design row is a parameter draw applied to it.

Reports are written in a second step that reads the batch directories, so a report can be
regenerated from its artifact without re-running the model.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final

import polars as pl

from late_ming_lab.calibration.summary_stats import scalar
from late_ming_lab.evidence.cards import load_cards
from late_ming_lab.experiments.counterfactual import (
    BREAKDOWN_LINES,
    collapse_probability,
    compare_metrics,
    crossed_count_distribution,
    interaction_effect,
    line_sensitivity,
    response_by_value,
    response_curve,
    time_to_breakdown_summary,
    with_breakdown_lines,
)
from late_ming_lab.experiments.interventions import (
    BASELINE,
    FIELD_BY_PARAMETER_SET,
    arm_configuration,
    baseline_configuration,
    configuration_diff,
    declared_arms,
    question_for,
)
from late_ming_lab.experiments.runner import (
    DEFAULT_REPLICATES,
    EXPERIMENT_ROOT,
    RUN_TICK_COUNT,
    RUN_WARMUP_TICKS,
    ExperimentBatch,
    Job,
    ablation_jobs,
    design_jobs,
    grid_jobs,
    run_jobs,
)
from late_ming_lab.experiments.sensitivity import (
    SweepParameter,
    morris_design,
    morris_indices,
    select_influential,
    sobol_design,
    sobol_indices,
    sweep_parameters,
)

ABLATION_LABEL: Final[str] = "p10-ablations"
MORRIS_LABEL: Final[str] = "p10-morris"
SOBOL_LABEL: Final[str] = "p10-sobol"
GRID_LABEL: Final[str] = "p10-tipping"

REPORT_DIR: Final[str] = "docs/experiments"

#: The base seed of the whole phase. Every replicate of every arm derives from it, so the phase is
#: one experiment rather than four.
P10_BASE_SEED: Final[int] = 20_260_914

#: How many processes a batch may use. The runs are independent and individually seeded, so this
#: changes only how long the phase takes, never what it measures. Two rather than more because the
#: machine this phase ran on had little memory to spare, and four workers thrashed it.
P10_WORKERS: Final[int] = 2

#: Morris: two trajectories of fifteen parameters is 32 runs. Small on purpose — a screening design
#: only has to rank the parameters, and the report prints sigma beside mu_star so a reader can see
#: which rankings a design this size can actually support.
MORRIS_TRAJECTORIES: Final[int] = 2
MORRIS_LEVELS: Final[int] = 4

#: Sobol: eight base samples with second-order indices is 80 runs for four parameters. This is a
#: very small design; the report quotes every confidence interval for exactly that reason.
SOBOL_BASE: Final[int] = 8

#: The grid: three values per axis, one run per cell.
GRID_POINTS: Final[int] = 3
GRID_REPLICATES: Final[int] = 1

#: How many parameters Morris may hand to the Sobol design. Four keeps the second-order design
#: inside the compute this phase is allowed, and the report names the ones it left out.
SOBOL_LIMIT: Final[int] = 4

#: The metrics the ablation and interaction reports compare, in the order they are printed.
REPORTED_METRICS: Final[tuple[str, ...]] = (
    "indicators_crossed_end",
    "peak_crossed",
    "breakdown",
    "tax_base_end_mu",
    "tax_base_change_mu",
    "receipts_over_quota_total",
    "households_departed",
    "households_exited",
    "migration_net_node_min",
    "market_active_link_share",
    "market_largest_component_share",
    "military_pay_arrears_end_tael",
    "military_pay_arrears_max_tael",
    "largest_band_share_max",
    "largest_band_share_end",
    "bands_at_end",
)

#: The events each ablatable mechanism produces. An arm's counters are how a reader checks that the
#: intervention removed something rather than merely being declared.
MECHANISM_COUNTERS: Final[tuple[str, ...]] = (
    "band_merges",
    "elite_loans",
    "suppressions",
    "trade_shipments",
)

#: The outputs the sensitivity analyses are run against, and the one the selection rule uses.
SENSITIVITY_OUTPUTS: Final[tuple[str, ...]] = (
    "indicators_crossed_end",
    "largest_band_share_max",
    "tax_base_change_mu",
    "households_departed",
)
PRIMARY_OUTPUT: Final[str] = "indicators_crossed_end"

#: The three two-way arms, as (single, single, joint) triples.
INTERACTION_TRIPLES: Final[tuple[tuple[str, str, str], ...]] = (
    ("NO_DROUGHT", "FULL_MILITARY_PAY", "JOINT_NO_DROUGHT+FULL_MILITARY_PAY"),
    ("NO_DROUGHT", "HIGH_RELIEF", "JOINT_NO_DROUGHT+HIGH_RELIEF"),
    (
        "NO_EXTRACTION_ESCALATION",
        "NO_ELITE_CREDIT",
        "JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT",
    ),
)


class ExperimentError(RuntimeError):
    """Raised when a P10 step cannot be carried out with the inputs it was given."""


def parameter_field_names(sweep: Sequence[SweepParameter]) -> dict[str, str]:
    """Map each swept parameter to the arm field its parameter set lives in."""
    mapping: dict[str, str] = {}
    for parameter in sweep:
        field = FIELD_BY_PARAMETER_SET.get(parameter.parameter_set)
        if field is None:
            raise ExperimentError(f"no arm field holds {parameter.parameter_set}")
        mapping[parameter.name] = field
    return mapping


def run_ablation_experiment(
    root: str | Path,
    *,
    output_dir: str | Path,
    replicates: int = DEFAULT_REPLICATES,
    base_seed: int = P10_BASE_SEED,
    ticks: int | None = None,
    warmup_ticks: int | None = None,
    progress: Callable[[int, Job], None] | None = None,
    workers: int = 1,
) -> ExperimentBatch:
    """The baseline, the nine ablations and the three joint arms, at every replicate."""
    ticks, warmup_ticks = _resolved_window(ticks, warmup_ticks)
    return run_jobs(
        ablation_jobs(replicates=replicates),
        base_seed=base_seed,
        label=ABLATION_LABEL,
        output_dir=output_dir,
        root=root,
        ticks=ticks,
        warmup_ticks=warmup_ticks,
        design={"kind": "ablation", "replicates": replicates},
        progress=progress,
        workers=workers,
    )


def run_morris(
    root: str | Path,
    *,
    output_dir: str | Path,
    base_seed: int = P10_BASE_SEED,
    trajectories: int = MORRIS_TRAJECTORIES,
    ticks: int | None = None,
    warmup_ticks: int | None = None,
    progress: Callable[[int, Job], None] | None = None,
    workers: int = 1,
) -> tuple[ExperimentBatch, pl.DataFrame, tuple[SweepParameter, ...]]:
    """The Morris design over every card-bounded parameter, with its elementary-effects table."""
    ticks, warmup_ticks = _resolved_window(ticks, warmup_ticks)
    sweep = sweep_parameters(load_cards(root))
    design = morris_design(sweep, trajectories=trajectories, levels=MORRIS_LEVELS, seed=base_seed)
    batch = run_jobs(
        design_jobs(design, label_prefix="MORRIS"),
        base_seed=base_seed,
        label=MORRIS_LABEL,
        output_dir=output_dir,
        root=root,
        parameter_sets=parameter_field_names(sweep),
        ticks=ticks,
        warmup_ticks=warmup_ticks,
        design={"kind": "morris", "trajectories": trajectories, "levels": MORRIS_LEVELS},
        progress=progress,
        workers=workers,
    )
    indices = morris_indices(sweep, design, _outputs(batch), levels=MORRIS_LEVELS, seed=base_seed)
    return batch, indices, sweep


def run_sobol(
    root: str | Path,
    *,
    output_dir: str | Path,
    selected: Sequence[SweepParameter],
    base_seed: int = P10_BASE_SEED,
    base: int = SOBOL_BASE,
    ticks: int | None = None,
    warmup_ticks: int | None = None,
    progress: Callable[[int, Job], None] | None = None,
    workers: int = 1,
) -> tuple[ExperimentBatch, dict[str, pl.DataFrame]]:
    """The Sobol design over the selected parameters, with second-order interaction indices."""
    if not selected:
        raise ExperimentError("the Sobol design needs at least one selected parameter")
    ticks, warmup_ticks = _resolved_window(ticks, warmup_ticks)
    design = sobol_design(selected, base=base, second_order=True, seed=base_seed)
    batch = run_jobs(
        design_jobs(design, label_prefix="SOBOL"),
        base_seed=base_seed,
        label=SOBOL_LABEL,
        output_dir=output_dir,
        root=root,
        parameter_sets=parameter_field_names(selected),
        ticks=ticks,
        warmup_ticks=warmup_ticks,
        design={
            "kind": "sobol",
            "base": base,
            "second_order": True,
            "selected": [parameter.name for parameter in selected],
        },
    )
    tables = sobol_indices(selected, _outputs(batch), base=base, second_order=True, seed=base_seed)
    return batch, tables


def run_tipping_grid(
    root: str | Path,
    *,
    output_dir: str | Path,
    parameters: Sequence[SweepParameter],
    base_seed: int = P10_BASE_SEED,
    points: int = GRID_POINTS,
    replicates: int = GRID_REPLICATES,
    ticks: int | None = None,
    warmup_ticks: int | None = None,
    progress: Callable[[int, Job], None] | None = None,
    workers: int = 1,
) -> ExperimentBatch:
    """A grid over two parameters inside their card ranges: a region, not a curve."""
    if len(parameters) != 2:
        raise ExperimentError("the tipping grid is over exactly two parameters")
    ticks, warmup_ticks = _resolved_window(ticks, warmup_ticks)
    values: dict[str, list[float]] = {}
    for parameter in parameters:
        step = (parameter.high - parameter.low) / (points - 1)
        values[parameter.name] = [parameter.low + index * step for index in range(points)]
    return run_jobs(
        grid_jobs(
            [parameter.name for parameter in parameters],
            values,
            replicates=replicates,
        ),
        base_seed=base_seed,
        label=GRID_LABEL,
        output_dir=output_dir,
        root=root,
        parameter_sets=parameter_field_names(parameters),
        ticks=ticks,
        warmup_ticks=warmup_ticks,
        design={
            "kind": "grid",
            "parameters": [parameter.name for parameter in parameters],
            "points": points,
            "replicates": replicates,
        },
        progress=progress,
        workers=workers,
    )


def run_p10(
    root: str | Path,
    *,
    output_dir: str | Path | None = None,
    report_dir: str | Path | None = None,
    replicates: int = DEFAULT_REPLICATES,
    base_seed: int = P10_BASE_SEED,
    ticks: int | None = None,
    warmup_ticks: int | None = None,
    verbose: bool = False,
    workers: int = P10_WORKERS,
) -> dict[str, Path]:
    """Run all three experiments in order and write the reports that read them.

    Returns the directory of each batch and of the reports, so a caller can inspect the artifacts
    the documents were generated from.
    """
    directory = Path(output_dir) if output_dir is not None else Path(root) / EXPERIMENT_ROOT
    ablations = run_ablation_experiment(
        root,
        output_dir=directory,
        replicates=replicates,
        base_seed=base_seed,
        ticks=ticks,
        warmup_ticks=warmup_ticks,
        progress=reporter("ablation") if verbose else None,
        workers=workers,
    )
    morris_batch, morris_table, sweep = run_morris(
        root,
        output_dir=directory,
        base_seed=base_seed,
        ticks=ticks,
        warmup_ticks=warmup_ticks,
        progress=reporter("morris") if verbose else None,
        workers=workers,
    )
    selected = select_parameters(morris_table, sweep)
    if len(selected) < 2:
        raise ExperimentError("Morris selected fewer than two parameters for the Sobol design")
    sobol_batch, _ = run_sobol(
        root,
        output_dir=directory,
        selected=selected,
        base_seed=base_seed,
        ticks=ticks,
        warmup_ticks=warmup_ticks,
        progress=reporter("sobol") if verbose else None,
        workers=workers,
    )
    tipping = run_tipping_grid(
        root,
        output_dir=directory,
        parameters=strongest_pair(morris_table, sweep),
        base_seed=base_seed,
        ticks=ticks,
        warmup_ticks=warmup_ticks,
        progress=reporter("tipping") if verbose else None,
        workers=workers,
    )
    written = write_experiment_reports(
        root,
        output_dir=report_dir,
        ablations=ablations.directory,
        morris=morris_batch.directory,
        sobol=sobol_batch.directory,
        tipping=tipping.directory,
    )
    return {
        "ablations": ablations.directory,
        "morris": morris_batch.directory,
        "sobol": sobol_batch.directory,
        "tipping": tipping.directory,
        "reports": written[0].parent,
    }


def select_parameters(
    morris_table: pl.DataFrame, sweep: Sequence[SweepParameter]
) -> tuple[SweepParameter, ...]:
    """The Sobol set: Morris's selection rule applied to the primary output, in card order."""
    names = select_influential(
        morris_table, output=PRIMARY_OUTPUT, floor_share=0.1, limit=SOBOL_LIMIT
    )
    return tuple(parameter for parameter in sweep if parameter.name in names)


def strongest_pair(
    morris_table: pl.DataFrame, sweep: Sequence[SweepParameter]
) -> tuple[SweepParameter, ...]:
    """The two strongest parameters by elementary-effect magnitude, for the grid's two axes."""
    ranked = (
        morris_table.filter(pl.col("output") == PRIMARY_OUTPUT)
        .sort("mu_star", descending=True)["parameter"]
        .to_list()
    )
    if len(ranked) < 2:
        raise ExperimentError("fewer than two parameters were analysed")
    by_name = {parameter.name: parameter for parameter in sweep}
    missing = [name for name in ranked[:2] if name not in by_name]
    if missing:
        raise ExperimentError(f"the grid axes are not swept parameters: {missing}")
    return (by_name[ranked[0]], by_name[ranked[1]])


def _resolved_window(ticks: int | None, warmup_ticks: int | None) -> tuple[int, int]:
    """The declared window, replacing only what a caller left unspecified."""
    return (
        RUN_TICK_COUNT if ticks is None else ticks,
        RUN_WARMUP_TICKS if warmup_ticks is None else warmup_ticks,
    )


def reporter(phase: str) -> Callable[[int, Job], None]:
    """A per-run progress line, so a long batch is legible while it runs rather than only after."""

    def report(index: int, job: Job) -> None:
        print(f"[{phase}] run {index}: {job.label} r{job.replicate}", flush=True)

    return report


def _sobol_set(
    design: dict[str, Any], indices: pl.DataFrame, sweep: Sequence[SweepParameter]
) -> tuple[SweepParameter, ...]:
    """The parameters the Sobol batch actually ran: its recorded selection, not a fresh one.

    Re-deriving the set here would silently analyse a different design from the one on disk the
    moment the selection rule or the Morris table changed, and SALib's indices are only meaningful
    against the design they came from.
    """
    recorded = design.get("selected")
    if isinstance(recorded, list) and recorded:
        names = {str(name) for name in recorded}
        return tuple(parameter for parameter in sweep if parameter.name in names)
    return select_parameters(indices, sweep)


def _design_of(manifest: dict[str, Any]) -> dict[str, Any]:
    """The design metadata a batch recorded, so a report never assumes the default size."""
    recorded = manifest.get("design", {})
    return dict(recorded) if isinstance(recorded, dict) else {}


def _outputs(batch: ExperimentBatch) -> dict[str, list[float]]:
    return {metric: batch.runs[metric].to_list() for metric in SENSITIVITY_OUTPUTS}


def load_batch(directory: str | Path) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    """Read a batch's runs, its governance timelines and its manifest."""
    source = Path(directory)
    runs = pl.read_parquet(source / "runs.parquet")
    governance = pl.read_parquet(source / "governance_timeline.parquet")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    return runs, governance, manifest


def write_experiment_reports(
    root: str | Path,
    *,
    output_dir: str | Path | None = None,
    ablations: str | Path,
    morris: str | Path,
    sobol: str | Path,
    tipping: str | Path,
) -> tuple[Path, ...]:
    """Write the four documents from the four batch directories."""
    base = Path(output_dir) if output_dir is not None else Path(root) / REPORT_DIR
    base.mkdir(parents=True, exist_ok=True)
    return (
        _write(base / "ablation.md", ablation_report(ablations)),
        _write(base / "interactions.md", interaction_report(ablations)),
        _write(base / "sensitivity.md", sensitivity_report(root, morris=morris, sobol=sobol)),
        _write(base / "tipping.md", tipping_report(root, morris=morris, tipping=tipping)),
    )


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _table(frame: pl.DataFrame, columns: Sequence[str] | None = None) -> str:
    """A markdown table from a frame, with floats shortened so a row stays readable."""
    selected = frame.select(list(columns)) if columns is not None else frame
    header = "| " + " | ".join(selected.columns) + " |"
    rule = "| " + " | ".join("---" for _ in selected.columns) + " |"
    rows: list[str] = []
    for row in selected.iter_rows():
        cells = [f"{value:.4g}" if isinstance(value, float) else str(value) for value in row]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, rule, *rows])


def ablation_report(directory: str | Path) -> str:
    """The arm table, the paired comparisons and the collapse probability, per line."""
    runs, governance, manifest = load_batch(directory)
    enriched = with_breakdown_lines(runs, governance)
    comparisons = compare_metrics(enriched, baseline=BASELINE, metrics=REPORTED_METRICS)
    probabilities = collapse_probability(enriched)
    timing = time_to_breakdown_summary(enriched)
    binding = binding_table(enriched)
    baseline_config = baseline_configuration()
    arms: list[str] = ["| arm | question | what it changes |", "| --- | --- | --- |"]
    for arm in declared_arms():
        differences = configuration_diff(baseline_config, arm_configuration(arm))
        changed = "; ".join(f"{name}: {before} to {after}" for name, before, after in differences)
        arms.append(
            f"| `{arm}` | {question_for(arm)} | {changed or 'nothing (the reference arm)'} |"
        )
    lines = [
        "# P10 ablation: which mechanisms the crisis needs",
        "",
        f"Batch `{Path(directory).name}`: {manifest['run_count']} runs, "
        f"{len(manifest['labels'])} arms at {len(manifest['replicates'])} replicates, "
        f"{manifest['ticks']} ticks, base seed {manifest['base_seed']}.",
        "",
        "Every arm runs under common random numbers: replicate *r* of every arm starts from the",
        "same root seed, so a paired difference is the declared intervention rather than a fresh",
        "weather sequence. The table reports medians and quartiles per arm, the paired median",
        "difference with a bootstrap interval, the share of replicates that move the same way, and",
        "Cliff's delta. A direction is claimed only when the interval excludes zero.",
        "",
        "## The arms and what each one changes",
        "",
        *arms,
        "",
        "The baseline is the declared reference: the escalating extraction policy and the declared",
        "disruption regime are **on**, which the P07 sandbox leaves off, so the two ablations that",
        "remove them have something to remove. The disruption regime is a scenario declaration,",
        "not a measurement: the model has no endogenous link from armed activity to transport yet.",
        "",
        "## Paired comparisons, per metric and arm",
        "",
        _table(
            comparisons,
            [
                "metric",
                "arm",
                "baseline_median",
                "arm_median",
                "arm_q1",
                "arm_q3",
                "median_difference",
                "difference_low",
                "difference_high",
                "share_increase",
                "cliffs_delta",
                "direction",
            ],
        ),
        "",
        "## Collapse probability",
        "",
        f"A run is *in breakdown* when at least {manifest['breakdown_indicators']} of the eight "
        f"declared governance lines are crossed at a sampled tick (every "
        f"{manifest['breakdown_sample_every']} ticks). The share carries a Wilson interval because "
        "twelve runs is not a probability until its uncertainty is stated.",
        "",
        _table(
            probabilities,
            [
                "label",
                "runs",
                "runs_in_breakdown",
                "collapse_probability",
                "wilson_low",
                "wilson_high",
            ],
        ),
        "",
        "### When each arm broke down, among the runs that did",
        "",
        "A run that never reaches the line carries a sentinel of -1, kept out of every paired",
        "statistic on purpose: a median of -1 is not a time, and subtracting it from a real tick",
        "would make a run that broke down look like one that held out longer. Timing is answered",
        "here instead, conditioned on the runs that reached the line.",
        "",
        _table(
            timing,
            [
                "label",
                "runs",
                "runs_reaching_the_line",
                "runs_never_reaching",
                "median_tick",
                "q1_tick",
                "q3_tick",
            ],
        ),
        "",
        "### Did each arm actually remove its mechanism?",
        "",
        "Each ablatable mechanism leaves a counter in the log. An arm whose counter still moves",
        "as often as the baseline's removed nothing; `baseline_replicates_active` says how many",
        "baseline runs had something to remove at all, so a structural no-op is visible rather",
        "than read as a null result.",
        "",
        _table(
            binding,
            [
                "metric",
                "arm",
                "baseline_replicates_active",
                "baseline_median",
                "arm_median",
                "median_difference",
                "direction",
            ],
        ),
        "",
        "### How many lines each arm actually crosses",
        "",
        _table(
            crossed_count_distribution(enriched),
            ["label", "indicators_crossed_end", "runs", "share"],
        ),
        "",
        "### Is the result the line or the model?",
        "",
        "The breakdown line is a declared reading rule, so the share is recomputed at every",
        "candidate line ("
        + ", ".join(str(line) for line in BREAKDOWN_LINES)
        + "). If the declared line sits where",
        "nothing changes any more, the table says so.",
        "",
        _table(
            line_sensitivity(enriched),
            [
                "label",
                "line",
                "runs_in_breakdown",
                "collapse_probability",
                "wilson_low",
                "wilson_high",
            ],
        ),
    ]
    return "\n".join(lines) + "\n"


def binding_table(runs: pl.DataFrame) -> pl.DataFrame:
    """Per arm and mechanism counter: whether anything was removed, and how much was there.

    The baseline's own counter decides whether an ablation had anything to remove: `band_merges`
    fires in only some replicates, so an arm that removes merging is a structural no-op in the
    replicates where no band ever merged, and a reader has to be able to see which replicates those
    were rather than reading a diluted zero as evidence.
    """
    rows: list[dict[str, object]] = []
    for counter in MECHANISM_COUNTERS:
        baseline_runs = runs.filter(pl.col("label") == BASELINE).sort("replicate")
        active = int((baseline_runs[counter] > 0.0).sum())
        for arm in declared_arms():
            if arm == BASELINE:
                continue
            arm_runs = runs.filter(pl.col("label") == arm).sort("replicate")
            rows.append(
                {
                    "metric": counter,
                    "arm": arm,
                    "baseline_replicates_active": active,
                    "baseline_median": scalar(baseline_runs[counter].median()),
                    "arm_median": scalar(arm_runs[counter].median()),
                    "median_difference": scalar(
                        (arm_runs[counter] - baseline_runs[counter]).median()
                    ),
                    "direction": (
                        "removed" if scalar(arm_runs[counter].max()) == 0.0 else "still active"
                    ),
                }
            )
    return pl.DataFrame(rows)


def interaction_report(directory: str | Path) -> str:
    """The three joint arms against the sum of their parts, with the additivity null."""
    runs, governance, manifest = load_batch(directory)
    enriched = with_breakdown_lines(runs, governance)
    rows: list[dict[str, object]] = []
    for single_a, single_b, joint in INTERACTION_TRIPLES:
        for metric in REPORTED_METRICS:
            effect = interaction_effect(
                enriched,
                metric=metric,
                baseline=BASELINE,
                single_a=single_a,
                single_b=single_b,
                joint=joint,
            )
            rows.append(
                {
                    "metric": metric,
                    "single_a": single_a,
                    "single_b": single_b,
                    "effect_a": effect.effect_a,
                    "effect_b": effect.effect_b,
                    "effect_joint": effect.effect_joint,
                    "interaction": effect.interaction,
                    "low": effect.difference_low,
                    "high": effect.difference_high,
                    "verdict": effect.direction,
                }
            )
    table = pl.DataFrame(rows)
    counts = table.group_by("verdict").len().sort("verdict")
    lines = [
        "# P10 interactions: whether two mechanisms add up",
        "",
        f"Batch `{Path(directory).name}`: {manifest['run_count']} runs.",
        "",
        "Additivity is the null: the joint arm's paired difference is compared with the sum of its",
        "two single-arm differences, and a bootstrap interval on that gap decides. *Additive*",
        "means the interval covers zero — the two mechanisms do not visibly interact at this",
        "sample size, which is not the same as proving them independent.",
        "",
        _table(counts, ["verdict", "len"]),
        "",
        "## Every triple, on every reported metric",
        "",
        _table(
            table,
            [
                "metric",
                "single_a",
                "single_b",
                "effect_a",
                "effect_b",
                "effect_joint",
                "interaction",
                "low",
                "high",
                "verdict",
            ],
        ),
    ]
    return "\n".join(lines) + "\n"


def sensitivity_report(root: str | Path, *, morris: str | Path, sobol: str | Path) -> str:
    """Morris ranking, the selected set, Sobol indices with intervals, and the response curves."""
    morris_runs, _, morris_manifest = load_batch(morris)
    sobol_runs, _, sobol_manifest = load_batch(sobol)
    sweep = sweep_parameters(load_cards(root))
    morris_design = _design_of(morris_manifest)
    sobol_design = _design_of(sobol_manifest)
    indices = morris_indices(
        sweep,
        pl.DataFrame({parameter.name: morris_runs[parameter.name] for parameter in sweep}),
        _outputs_from_runs(morris_runs),
        levels=int(morris_design.get("levels", MORRIS_LEVELS)),
        seed=int(morris_manifest.get("base_seed", P10_BASE_SEED)),
    )
    selected = _sobol_set(sobol_design, indices, sweep)
    second_order = bool(sobol_design.get("second_order", True))
    tables = sobol_indices(
        selected,
        _outputs_from_runs(sobol_runs),
        base=int(sobol_design.get("base", SOBOL_BASE)),
        second_order=second_order,
        seed=int(sobol_manifest.get("base_seed", P10_BASE_SEED)),
    )
    lines = [
        "# P10 sensitivity: which parameters the model's behaviour depends on",
        "",
        f"Morris batch `{Path(morris).name}` ({morris_manifest['run_count']} runs, "
        f"{morris_design.get('trajectories', MORRIS_TRAJECTORIES)} trajectories over "
        f"{len(sweep)} parameters), then Sobol batch `{Path(sobol).name}` "
        f"({sobol_manifest['run_count']} runs, base {sobol_design.get('base', SOBOL_BASE)}, "
        "second-order indices on).",
        "",
        "Every swept parameter has a P08 card range; the design moves it inside that range and",
        "nothing else changes between rows, so a difference across the design is the parameter.",
        "Because a mean would hide everything interesting, the tables carry the elementary-effect",
        "dispersion, the Sobol indices with their confidence intervals, and the binned response",
        "curves that show where a response bends.",
        "",
        "## Morris elementary effects",
        "",
        "`mu_star` is the mean absolute elementary effect (influence), `sigma` its spread",
        "(non-linearity or interaction), `mu` the signed mean (direction).",
        "",
        _table(
            indices.sort(["output", "mu_star"], descending=[False, True]),
            ["output", "parameter", "mu", "mu_star", "sigma"],
        ),
        "",
        f"Selection rule: for `{PRIMARY_OUTPUT}`, the parameters whose `mu_star` is at least a",
        "tenth of the largest, capped at six. Selected: "
        + ", ".join(f"`{parameter.name}`" for parameter in selected)
        + ".",
        "",
        "The Sobol batch ran the selection recorded in its manifest: "
        + ", ".join(f"`{parameter.name}`" for parameter in selected)
        + ".",
        "",
        "## Sobol first-order and total indices",
        "",
        _table(tables["S1"].sort(["output", "value"], descending=[False, True])),
        "",
        _table(tables["ST"].sort(["output", "value"], descending=[False, True])),
        "",
        "## Sobol second-order indices: the interactions",
        "",
        "A second-order index is the share of an output's variance attributable to two parameters",
        "together beyond their separate effects. The five strongest pairs per output are shown;",
        "the confidence interval is in the table for a reason, since this design is small.",
        "",
    ]
    second = tables["S2"]
    if second.is_empty():
        lines.append("The second-order indices were not computed for this batch.")
    else:
        strongest = (
            second.sort("value", descending=True)
            .group_by("output")
            .head(5)
            .sort(["output", "value"], descending=[False, True])
        )
        lines.append(_table(strongest))
    lines += [
        "",
        "## Response curves, and where they bend",
        "",
        f"Binned medians of `{PRIMARY_OUTPUT}` along the three strongest parameters, with the",
        "second difference of those medians: a straight line reads as zero, a bend is a spike.",
        "",
    ]
    for runs, parameter in _response_sources(indices, selected, sobol_runs, morris_runs):
        curve = response_curve(runs, parameter=parameter, metric=PRIMARY_OUTPUT, bins=GRID_POINTS)
        source = "Sobol" if runs is sobol_runs else "Morris"
        lines += [
            f"`{parameter}` against `{PRIMARY_OUTPUT}` ({source} design):",
            "",
            _table(
                curve, ["bin", "bin_low", "bin_high", "runs", "median", "q1", "q3", "curvature"]
            ),
            "",
        ]
    return "\n".join(lines) + "\n"


def _sobol_readability(tables: dict[str, pl.DataFrame]) -> str:
    """Whether the Sobol estimates at this design size can be read at all.

    A variance share lives in [0, 1], and an estimate whose interval covers zero says nothing about
    the sign. Both are computed here rather than left for a reader to notice, because a table of
    numbers outside the range the quantity can take looks like a result and is not one. The phase
    reports the count and its conclusion; the numbers stay in the tables beside it.
    """
    first = tables["S1"]
    total = tables["ST"]
    finite_first = first.filter(pl.col("value").is_finite())
    finite_total = total.filter(pl.col("value").is_finite())
    undefined = first.height - finite_first.height
    beyond = (
        finite_first.filter((pl.col("value") < 0.0) | (pl.col("value") > 1.0)).height
        + finite_total.filter((pl.col("value") < 0.0) | (pl.col("value") > 1.0)).height
    )
    covering_zero = finite_first.filter(
        (pl.col("confidence_low") <= 0.0) & (pl.col("confidence_high") >= 0.0)
    ).height
    lines = [
        (
            f"Of {first.height} first-order indices, {undefined} are undefined — their output does "
            "not vary within the design's slices, as a discrete outcome is flat across a "
            f"four-sample design — {beyond} lie outside the [0, 1] a variance share can take, and "
            f"{covering_zero} have an interval covering zero."
        ),
        "",
    ]
    if beyond > 0 or undefined > 0:
        lines += [
            "**Read this as a failed attempt, not a result.** At this design size the Sobol "
            "estimator has no resolving power: shares outside [0, 1] are not small-sample noise "
            "around a true value but evidence that the estimator is not estimable from four base "
            "samples, and an undefined index is not zero. The phase's sensitivity finding is "
            "therefore the Morris ranking and the response curves above; the Sobol batch is "
            "reported because the plan asks for it and because its failure is informative about "
            "the compute this phase had.",
            "",
        ]
    return "\n".join(lines)


def _response_sources(
    indices: pl.DataFrame,
    selected: Sequence[SweepParameter],
    sobol_runs: pl.DataFrame,
    morris_runs: pl.DataFrame,
) -> tuple[tuple[pl.DataFrame, str], ...]:
    """The three strongest parameters, each read against a design that actually moved it.

    A parameter that made the Sobol set is read off the Sobol design, which varies it together with
    the others; a strong parameter that did not make the cut is read off the Morris design, which
    varies it alone. Reading either off the wrong table would silently plot a constant, or fail.
    """
    ranked = (
        indices.filter(pl.col("output") == PRIMARY_OUTPUT)
        .sort("mu_star", descending=True)["parameter"]
        .to_list()
    )
    chosen = [parameter.name for parameter in selected]
    ordered = [*chosen, *(name for name in ranked if name not in chosen)]
    sources: list[tuple[pl.DataFrame, str]] = []
    for name in ordered[:3]:
        table = sobol_runs if name in chosen else morris_runs
        if name in table.columns:
            sources.append((table, name))
    return tuple(sources)


def tipping_report(root: str | Path, *, morris: str | Path, tipping: str | Path) -> str:
    """The two-parameter surface: collapse probability and peak crossed lines per cell."""
    grid_runs, grid_governance, grid_manifest = load_batch(tipping)
    grid_design = _design_of(grid_manifest)
    morris_runs, _, _ = load_batch(morris)
    sweep = {parameter.name: parameter for parameter in sweep_parameters(load_cards(root))}
    recorded_axes = [str(name) for name in grid_design.get("parameters", [])]
    parameters = [name for name in recorded_axes if name in grid_runs.columns] or [
        name for name in grid_runs.columns if name in sweep
    ][:2]
    enriched = with_breakdown_lines(grid_runs, grid_governance)
    lines = [
        "# P10 tipping: the region, not the curve",
        "",
        f"Grid batch `{Path(tipping).name}`: {grid_manifest['run_count']} runs over "
        f"{parameters} at {grid_design.get('points', GRID_POINTS)} values per axis and "
        f"{grid_design.get('replicates', GRID_REPLICATES)} replicates per cell.",
        "",
        "The two axes are the parameters with the largest Morris elementary effect on",
        f"`{PRIMARY_OUTPUT}`, sampled inside their card ranges. Every cell is the same run under",
        "the same random numbers apart from the two parameters, so the surface is the model's",
        "response to them rather than to a fresh sample.",
        "",
    ]
    if len(parameters) < 2:
        lines.append("The grid batch does not carry two swept parameter columns.")
        return "\n".join(lines) + "\n"
    if recorded_axes:
        lines.append(
            "The axes recorded in the batch manifest are "
            + ", ".join(f"`{name}`" for name in recorded_axes)
            + "."
        )
        lines.append("")
    first, second = parameters[0], parameters[1]
    cells = (
        enriched.group_by(first, second)
        .agg(
            [
                pl.col("breakdown").cast(pl.Float64).mean().alias("collapse_share"),
                pl.col("peak_crossed").mean().alias("mean_peak_crossed"),
                pl.col("time_to_breakdown").median().alias("median_time_to_breakdown"),
                pl.len().alias("runs"),
            ]
        )
        .sort([first, second])
    )
    lines += [
        f"Collapse share: rows `{first}`, columns `{second}`.",
        "",
        _table(cells.pivot(on=second, index=first, values="collapse_share").sort(first)),
        "",
        f"Mean peak crossed lines: rows `{first}`, columns `{second}`.",
        "",
        _table(cells.pivot(on=second, index=first, values="mean_peak_crossed").sort(first)),
        "",
        f"The response to `{first}` at the grid's own values (medians of `{PRIMARY_OUTPUT}`):",
        "",
        _table(
            response_by_value(enriched, parameter=first, metric=PRIMARY_OUTPUT),
            ["value", "runs", "median", "q1", "q3", "curvature"],
        ),
        "",
        f"The response to `{second}`, measured the same way:",
        "",
        _table(
            response_by_value(enriched, parameter=second, metric=PRIMARY_OUTPUT),
            ["value", "runs", "median", "q1", "q3", "curvature"],
        ),
        "",
        "## The Morris ranking behind the axes",
        "",
        _table(
            morris_indices(
                sweep_parameters(load_cards(root)),
                pl.DataFrame(
                    {
                        parameter.name: morris_runs[parameter.name]
                        for parameter in sweep_parameters(load_cards(root))
                    }
                ),
                _outputs_from_runs(morris_runs),
                levels=MORRIS_LEVELS,
                seed=P10_BASE_SEED,
            )
            .filter(pl.col("output") == PRIMARY_OUTPUT)
            .sort("mu_star", descending=True),
            ["parameter", "mu", "mu_star", "sigma"],
        ),
    ]
    return "\n".join(lines) + "\n"


def _outputs_from_runs(runs: pl.DataFrame) -> dict[str, list[float]]:
    return {metric: runs[metric].to_list() for metric in SENSITIVITY_OUTPUTS}
