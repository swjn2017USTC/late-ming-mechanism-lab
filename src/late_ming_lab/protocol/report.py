"""The threshold-robustness report: what the ensemble does and does not decide.

The document this writes is generated, never hand-edited: `docs/v2/threshold-robustness.md` carries
its generator in the header and is rewritten by `late-ming-lab protocol robustness`, the same way
`docs/v2/baseline-v1.json` is rewritten by `late-ming-lab baseline build`.

What it reports, and why each part is there:

```text
runs                 the declared protocol pilot: which arms, which seeds, which run ids, and the
                     simulation digest of each, so a reader can check the inputs instead of
                     trusting the summary
criteria             for each mechanism card, the share of ensemble members under which its reading
                     holds, changes, or cannot be decided — at every crossed count the protocol
                     allows the breakdown reading to be taken at
indicators           per line: the range the measurements occupied, the range the lines occupied,
                     and how often any of them crossed
line                the sentence a reader needs most: which verdicts move with the ensemble and
                     which do not, and which of the moving ones change the mechanism cards
```

A pilot run is not a result and the document says so in its own first paragraph: the report is a
property of the protocol and of the runs it was pointed at, and it fits nothing.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.evidence.parameters import core_default_governance_indicators
from late_ming_lab.experiments.integrated import build_integrated_economy
from late_ming_lab.experiments.interventions import arm_configuration, declared_arms
from late_ming_lab.experiments.runner import arm_parameter_sets
from late_ming_lab.protocol.evaluation import (
    PILOT_ARMS,
    PILOT_BASE_SEED,
    PILOT_REPLICATES,
    PROTOCOL_STAMP_FILE,
    PilotRun,
    _scenario_id,
    measures_of,
    run_protocol_pilot,
)
from late_ming_lab.protocol.freeze import (
    ProtocolFreeze,
    ProtocolMismatchError,
    assert_batch_protocol,
)
from late_ming_lab.protocol.robustness import (
    RunReading,
    ThresholdRobustness,
    evaluate,
    read_run,
)
from late_ming_lab.protocol.schema import ValidationProtocol, load_protocol
from late_ming_lab.protocol.thresholds import ThresholdEnsemble, sample_draws
from late_ming_lab.storage.run_store import (
    EVENTS_FILE,
    MANIFEST_FILE,
    SUMMARY_FILE,
    RunStore,
)
from late_ming_lab.storage.tables import read_json, read_table

#: Where the generated document and its machine-readable twin live.
REPORT_DOCUMENT: Final[str] = "docs/v2/threshold-robustness.md"
REPORT_JSON: Final[str] = "docs/v2/threshold-robustness.json"
GENERATOR: Final[str] = "late-ming-lab protocol robustness"

#: How many ensemble members the report enumerates. The declared design is small enough to take
#: whole, and taking it whole removes the question of which members were looked at; a `None` here
#: means every member of the design.
DEFAULT_MEMBERS: Final[int | None] = None


def _assert_stamp(directory: Path, *, protocol: ValidationProtocol) -> None:
    """Refuse a pilot run that does not record the frozen protocol."""
    path = directory / PROTOCOL_STAMP_FILE
    if not path.is_file():
        raise ReportError(
            f"{directory.name} carries no {PROTOCOL_STAMP_FILE}; nothing says which rules scored "
            "it, so re-run the pilot rather than reading it as if it had been scored under these"
        )
    try:
        recorded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ReportError(f"{path} is not valid JSON: {error}") from error
    try:
        assert_batch_protocol(recorded, ProtocolFreeze.of(protocol))
    except ProtocolMismatchError as error:
        raise ReportError(f"{directory.name}: {error}") from error


class ReportError(RuntimeError):
    """Raised when the report cannot be built from what is on disk."""


def load_pilot_runs(root: str | Path, *, output_root: str | Path) -> tuple[PilotRun, ...]:
    """Re-open the pilot's runs from their directories: log, measures, and the frames to measure.

    The denominators and the trade graph are rebuilt from the arm's own declaration rather than read
    from the artifact, because they are properties of the arm, and rebuilding them is the check that
    the declaration on disk still produces the run that was written.

    Each run must carry the protocol it was scored under, and the stamp is checked here rather than
    trusted: a run without one, or one recording another protocol, is refused. That is what makes
    "the protocol is frozen" a property of the tree instead of a habit of the author.
    """
    repository = Path(root)
    store = RunStore(output_root)
    directories = sorted(path for path in Path(output_root).iterdir() if path.is_dir())
    if not directories:
        raise ReportError(f"{store.root} holds no pilot run; run the pilot first")
    protocol = load_protocol(repository)
    runs: list[PilotRun] = []
    for directory in directories:
        run_id = directory.name
        arm = _arm_of(run_id)
        configuration = arm_configuration(arm)
        economy = build_integrated_economy(
            configuration.scenario,
            parameter_sets=arm_parameter_sets(configuration),
            disruption=configuration.disruption,
            extraction_policy=configuration.extraction_policy,
            capacity=configuration.capacity,
        )
        _assert_stamp(directory, protocol=protocol)
        events = read_table(directory / EVENTS_FILE)
        manifest = read_json(directory / MANIFEST_FILE)
        # The simulation digest is the run's, and it is written to the summary; a report that shows
        # an empty digest column cannot be checked against the runs it claims to have read.
        summary = read_json(directory / SUMMARY_FILE)
        thresholds = core_default_governance_indicators()
        measures = measures_of(
            events=events,
            run_id=run_id,
            simulation_digest=str(summary.get("simulation_digest", "")),
            policy_id=str(manifest.get("policy_id", "")),
            arm=arm,
            root_seed=int(manifest.get("root_seed", PILOT_BASE_SEED)),
            thresholds=thresholds,
            population_adults=sum(cohort.adults for cohort in economy.population),
            starting_households=sum(cohort.households for cohort in economy.population),
            trade_graph=economy.graphs.trade,
        )
        runs.append(
            PilotRun(
                measures=measures,
                events=events,
                population_adults=sum(cohort.adults for cohort in economy.population),
                starting_households=sum(cohort.households for cohort in economy.population),
                trade_graph=economy.graphs.trade,
                thresholds=thresholds,
                directory=directory,
            )
        )
    return tuple(runs)


def _arm_of(run_id: str) -> str:
    """The arm a run id names, by matching the declared arms' own run-id spelling."""
    for arm in declared_arms():
        if run_id.startswith(f"{_scenario_id(arm)}-"):
            return arm
    raise ReportError(f"{run_id}: no declared arm produces a run id like this")


def readings_of(runs: Iterable[PilotRun]) -> tuple[RunReading, ...]:
    """Every pilot run as the robustness report reads it."""
    from late_ming_lab.analysis.military import military_totals

    readings: list[RunReading] = []
    for run in runs:
        totals = military_totals(run.events)
        readings.append(
            read_run(
                run_id=run.measures.run_id,
                arm=run.measures.arm,
                root_seed=run.measures.root_seed,
                policy_id=run.measures.policy_id,
                indicators=run.measures.indicators,
                directions=run.measures.directions,
                events=run.events,
                elite_loans=float(run.events.filter(pl.col("event_type") == "ELITE_LOAN").height),
                bands_at_end=float(totals.get("bands_end", 0.0)),
            )
        )
    return tuple(readings)


def build_report(
    *,
    root: str | Path,
    protocol: ValidationProtocol,
    ensemble: ThresholdEnsemble,
    runs: tuple[RunReading, ...],
    members: int | None = DEFAULT_MEMBERS,
) -> ThresholdRobustness:
    """Evaluate every criterion over the ensemble, for these runs."""
    whole = sample_draws(ensemble, draws=members, seed=PILOT_BASE_SEED)
    # Keyed by indicator id, which is how a run's own measurements are keyed.
    keyed = tuple(ensemble.by_indicator(draw) for draw in whole)
    return evaluate(runs, protocol=protocol, ensemble=ensemble, members=keyed)


def run_and_report(
    *,
    root: str | Path,
    protocol: ValidationProtocol,
    ensemble: ThresholdEnsemble,
    pilot_root: str | Path,
    rerun_pilot: bool = False,
    members: int | None = DEFAULT_MEMBERS,
    progress: bool = False,
) -> tuple[ThresholdRobustness, tuple[PilotRun, ...]]:
    """The pilot (re-used from disk unless asked to re-run) and the report over it."""
    if rerun_pilot or not _has_runs(pilot_root):
        runs = run_protocol_pilot(root=root, output_root=pilot_root, progress=progress)
    else:
        runs = load_pilot_runs(root, output_root=pilot_root)
    report = build_report(
        root=root, protocol=protocol, ensemble=ensemble, runs=readings_of(runs), members=members
    )
    return report, runs


def _has_runs(pilot_root: str | Path) -> bool:
    root = Path(pilot_root)
    return root.is_dir() and any(path.is_dir() for path in root.iterdir())


def write_report(
    root: str | Path,
    report: ThresholdRobustness,
    *,
    runs: tuple[PilotRun, ...],
    arms: tuple[str, ...] = PILOT_ARMS,
    replicates: int = PILOT_REPLICATES,
    base_seed: int = PILOT_BASE_SEED,
) -> tuple[Path, Path]:
    """Write the generated document and its machine-readable twin; return both paths."""
    repository = Path(root)
    document = repository / REPORT_DOCUMENT
    machine = repository / REPORT_JSON
    document.parent.mkdir(parents=True, exist_ok=True)
    machine.write_text(
        json.dumps(
            {
                "generator": GENERATOR,
                "report": report.model_dump(mode="json"),
                "pilot": {
                    "arms": list(arms),
                    "replicates": replicates,
                    "base_seed": base_seed,
                    "runs": [
                        {
                            "run_id": run.measures.run_id,
                            "arm": run.measures.arm,
                            "root_seed": run.measures.root_seed,
                            "simulation_digest": run.measures.simulation_digest,
                        }
                        for run in runs
                    ],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    document.write_text(
        _markdown(report, runs=runs, replicates=replicates, base_seed=base_seed),
        encoding="utf-8",
    )
    return document, machine


def _markdown(
    report: ThresholdRobustness,
    *,
    runs: tuple[PilotRun, ...],
    replicates: int,
    base_seed: int,
) -> str:
    moved = report.moved_criteria()
    undecided = [share for share in report.criteria if share.verdict == "undetermined"]
    lines = [
        f"<!-- generated by: {GENERATOR} -->",
        "",
        "# Threshold robustness: what the ensemble decides, and what it does not",
        "",
        f"Generated by `{GENERATOR}` over `docs/v2/threshold-robustness.json`. Do not edit: the",
        "command rewrites this file.",
        "",
        "**This is a property of the protocol and of the runs it was pointed at, not a historical",
        "result.** It fits nothing and calibrates nothing. The runs below are a declared protocol",
        "pilot: they exist to give the ensemble something real to move, and their own measurements",
        "are reported as measurements, not as findings.",
        "",
        "## What was evaluated",
        "",
        f"- protocol `{report.protocol_version}` digest `{report.protocol_digest[:16]}…`",
        f"- threshold ensemble `{report.ensemble_version}` digest `{report.ensemble_digest[:16]}…`,"
        f" {report.members:,} members enumerated in full",
        f"- breakdown reading taken at every crossed count the protocol declares: "
        f"{', '.join(str(line) for line in report.breakdown_lines)}",
        f"- pilot: {len(runs)} runs, {replicates} replicates per arm, base seed {base_seed}",
        "",
        "| run id | arm | root seed | simulation digest |",
        "| --- | --- | --- | --- |",
    ]
    for run in runs:
        digest = run.measures.simulation_digest
        lines.append(
            f"| `{run.measures.run_id}` | {run.measures.arm} | {run.measures.root_seed} | "
            f"`{digest[:16]}…` |"
        )
    lines += [
        "",
        "## Which verdicts move with the ensemble",
        "",
    ]
    if moved:
        lines.append(
            "These criteria are decided differently by different members, and each is a mechanism "
            "card's status:"
        )
        lines.append("")
        lines.append("| criterion | mechanism | holds | changes | at crossed count |")
        lines.append("| --- | --- | --- | --- | --- |")
        for share in report.criteria:
            if share.criterion in moved:
                lines.append(
                    f"| `{share.criterion}` | {share.mechanism} | {share.holds:.3f} | "
                    f"{share.changes:.3f} | {share.breakdown_line} |"
                )
    else:
        lines.append(
            "No criterion moves with the ensemble: every one is either satisfied under every "
            "member or under none, which is what a threshold-free reading should look like."
        )
    lines += ["", "## Every criterion", ""]
    lines.append(
        "Rows are repeated at each crossed count the protocol allows, so a criterion that reads "
        "the breakdown line shows its dependence and one that does not repeats its row."
    )
    lines.append("")
    lines.append(
        "| criterion | mechanism | reads a line | crossed count | holds | changes | undetermined |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for share in report.criteria:
        reads_line = "yes" if share.reads_thresholds else "no"
        lines.append(
            f"| `{share.criterion}` | {share.mechanism} | {reads_line} | {share.breakdown_line} "
            f"| {share.holds:.3f} | {share.changes:.3f} | {share.undetermined:.3f} |"
        )
    lines += ["", "## Criteria no measurement decides", ""]
    if undecided:
        for share in undecided:
            lines.append(f"- `{share.criterion}` ({share.mechanism}): {share.statement}")
    else:
        lines.append(
            "None: every declared criterion is decided by a measurement this protocol names."
        )
    lines += ["", "## The eight lines and the measurements they cross", ""]
    lines.append(
        "The measured range is what the runs produced; the line range is what the ensemble allows. "
        "An indicator whose lines sit outside its measured range crosses the same way under every "
        "member, and its crossed share says so."
    )
    lines.append("")
    lines.append(
        "| indicator | direction | measured min | measured max | line min | line max | crossed |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for indicator in report.indicators:
        lines.append(
            f"| `{indicator.indicator}` | {indicator.direction} | {indicator.measured_min:.4g} | "
            f"{indicator.measured_max:.4g} | {indicator.line_min:.4g} | {indicator.line_max:.4g} "
            f"| {indicator.crossed_share:.3f} |"
        )
    lines += ["", "## How many lines the pilot runs cross", ""]
    lines.append("| crossed count | share of (run, member) pairs |")
    lines.append("| --- | --- |")
    for count, fraction in sorted(
        report.crossed_count_share.items(), key=lambda item: int(item[0])
    ):
        lines.append(f"| {count} | {fraction:.4f} |")
    lines += ["", "## Breakdown share per run, at each allowed line", ""]
    lines.append("| run id | " + " | ".join(str(line) for line in report.breakdown_lines) + " |")
    lines.append("| --- | " + " | ".join("---" for _ in report.breakdown_lines) + " |")
    for run_id, shares in report.breakdown_shares.items():
        cells = " | ".join(f"{shares[str(line)]:.3f}" for line in report.breakdown_lines)
        lines.append(f"| `{run_id}` | {cells} |")
    invariants = report.stable_criteria()
    lines += [
        "",
        "## What this report does not say",
        "",
        "- It does not say any threshold is historically correct. The eight lines are declared",
        "  reading rules; the ensemble says how far a verdict depends on them, not which is right.",
        "- It does not turn the pilot into evidence about the 1625-1644 crisis. The pilot's arms",
        "  are the sandbox's declared scenarios, and the historical core is not among them.",
        f"- It does not decide every card: {len(undecided)} criteria are undetermined for a reason",
        "  named above, which is a statement about the model's measurements rather than a result.",
        "",
        f"{len(invariants)} criteria give the same answer under every member and at every allowed",
        "crossed count:",
        "",
        *[f"- {line}" for line in invariants],
    ]
    return "\n".join(lines) + "\n"
