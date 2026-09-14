"""Read what a run or a batch produced, and say its headline numbers.

``analyze`` is the read-only command: it identifies the artifact it was pointed at, prints the
numbers that identify it, and - only when asked - regenerates the documents those artifacts support.
It runs no model, so it is safe on a login node, over a mounted output directory, or on a laptop.

Identification is by layout, not by guessing: each kind below is a set of files that must be
present, and an unknown directory is refused with what was found rather than summarised as empty.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.calibration.summary_stats import scalar

#: The files that identify each kind of artifact. The event log is written by the run store as
#: ``agent_events.parquet``; ``events.parquet`` is accepted too, because that is the name the phase
#: brief and the older documents use and a reader may well have copied it out under that name.
RUN_MARKERS: Final[tuple[str, ...]] = ("manifest.json", "summary.json")
EVENT_FILES: Final[tuple[str, ...]] = ("agent_events.parquet", "events.parquet")
EXPERIMENT_MARKERS: Final[tuple[str, ...]] = ("runs.parquet", "manifest.json")
ROBUSTNESS_MARKERS: Final[tuple[str, ...]] = ("mechanism_readings.parquet", "manifest.json")
ENSEMBLE_MARKERS: Final[tuple[str, ...]] = ("ensemble.parquet", "manifest.json")
CARD_MARKER: Final[str] = "cards.yaml"

#: The directories that identify the P10 root, whose reports read all four batches.
P10_BATCHES: Final[tuple[str, ...]] = ("p10-ablations", "p10-morris", "p10-sobol", "p10-tipping")


class AnalysisError(RuntimeError):
    """Raised when the target is not an artifact this command knows how to read."""


@dataclass(frozen=True, slots=True)
class Summary:
    """What one artifact is, and the numbers that identify it."""

    kind: str
    source: Path
    headline: tuple[tuple[str, object], ...]

    def to_json(self) -> str:
        return json.dumps(
            {
                "kind": self.kind,
                "source": str(self.source),
                "headline": {name: value for name, value in self.headline},
            },
            indent=2,
            sort_keys=True,
            default=str,
        )


def _heading(frame: pl.DataFrame, column: str) -> object:
    if column not in frame.columns:
        return None
    return scalar(frame[column].cast(pl.Float64).mean())


def summarize(target: str | Path) -> Summary:
    """Identify the artifact and read its headline numbers."""
    path = Path(target)
    if not path.exists():
        raise AnalysisError(f"{path} does not exist")
    if path.is_dir():
        if all((path / marker).exists() for marker in RUN_MARKERS) and any(
            (path / name).exists() for name in EVENT_FILES
        ):
            return _summarize_run(path)
        if all((path / marker).exists() for marker in EXPERIMENT_MARKERS):
            return _summarize_experiment(path)
        if all((path / marker).exists() for marker in ROBUSTNESS_MARKERS):
            return _summarize_robustness(path)
        if all((path / marker).exists() for marker in ENSEMBLE_MARKERS):
            return _summarize_ensemble(path)
        if (path / CARD_MARKER).exists():
            return _summarize_cards(path)
        if all((path / batch).is_dir() for batch in P10_BATCHES):
            return _summarize_p10_root(path)
    raise AnalysisError(
        f"{path} is not an artifact this command reads: expected a run directory "
        f"({', '.join((*RUN_MARKERS, '/'.join(EVENT_FILES)))}), an experiment batch "
        f"({', '.join(EXPERIMENT_MARKERS)}), a "
        f"calibration batch ({', '.join(ENSEMBLE_MARKERS)}), a cards directory ({CARD_MARKER}), or "
        f"the P10 root ({', '.join(P10_BATCHES)})"
    )


def _summarize_run(path: Path) -> Summary:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    return Summary(
        kind="run",
        source=path,
        headline=(
            ("run_id", manifest.get("run_id")),
            ("engine_version", manifest.get("engine_version")),
            ("git_sha", manifest.get("git_sha")),
            ("config_hash", manifest.get("config_hash")),
            ("llm_enabled", manifest.get("llm_enabled")),
            ("ticks", summary.get("tick_count")),
            ("events", summary.get("event_count")),
            ("simulation_digest", summary.get("simulation_digest")),
        ),
    )


def _summarize_experiment(path: Path) -> Summary:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    runs = pl.read_parquet(path / "runs.parquet")
    labels = sorted(set(runs["label"].to_list())) if "label" in runs.columns else ()
    return Summary(
        kind="experiment-batch",
        source=path,
        headline=(
            ("label", manifest.get("label")),
            ("phase", manifest.get("phase")),
            ("base_seed", manifest.get("base_seed")),
            ("runs", runs.height),
            ("labels", len(labels)),
            ("breakdown_share", _heading(runs, "breakdown")),
            ("mean_crossed_end", _heading(runs, "indicators_crossed_end")),
            ("mean_largest_band_share", _heading(runs, "largest_band_share_max")),
            ("mean_tax_base_change_mu", _heading(runs, "tax_base_change_mu")),
        ),
    )


def _summarize_robustness(path: Path) -> Summary:
    from late_ming_lab.experiments.policy_robustness import load_p12

    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    loaded = load_p12(path)
    arms = {status.policy: status.status for status in loaded.arms}
    verdicts = {row["mechanism"]: row["verdict"] for row in loaded.verdicts.iter_rows(named=True)}
    return Summary(
        kind="policy-robustness-batch",
        source=path,
        headline=(
            ("base_seed", manifest.get("base_seed")),
            ("replicates", manifest.get("replicates")),
            ("arms", ", ".join(f"{name}:{status}" for name, status in sorted(arms.items()))),
            ("mechanisms", ", ".join(f"{name}:{verdict}" for name, verdict in verdicts.items())),
            ("rows", loaded.levels.height),
            ("grid_cells", loaded.summary.height),
        ),
    )


def _summarize_ensemble(path: Path) -> Summary:
    from late_ming_lab.calibration.ensemble import Ensemble

    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    ensemble = Ensemble.load(path)
    draws = len(ensemble.draws)
    weights = ensemble.weights()
    parameters = ensemble.parameter_names()
    return Summary(
        kind="calibration-batch",
        source=path,
        headline=(
            ("draws", draws),
            ("parameter_names", len(parameters)),
            ("target_ids", len(ensemble.pattern_ids)),
            ("distinct_parameter_vectors", ensemble.distinct_parameter_vectors()),
            ("total_weight", sum(weights)),
            ("sampler_seed", manifest.get("sampler_seed")),
            ("particles", manifest.get("particles")),
        ),
    )


def _summarize_cards(path: Path) -> Summary:
    from late_ming_lab.synthesis.schema import load_book

    book = load_book(path / CARD_MARKER)
    counts = book.status_counts()
    return Summary(
        kind="mechanism-cards",
        source=path,
        headline=(
            ("schema_version", book.schema_version),
            ("cards", len(book.cards)),
            ("ids", ", ".join(card.id for card in book.cards)),
            *((f"status_{status.lower()}", count) for status, count in sorted(counts.items())),
        ),
    )


def _summarize_p10_root(path: Path) -> Summary:
    total = 0
    seeds: set[object] = set()
    for batch in P10_BATCHES:
        manifest = json.loads((path / batch / "manifest.json").read_text(encoding="utf-8"))
        total += int(manifest.get("run_count", 0))
        seeds.add(manifest.get("base_seed"))
    return Summary(
        kind="p10-root",
        source=path,
        headline=(
            ("batches", ", ".join(P10_BATCHES)),
            ("runs", total),
            ("base_seeds", ", ".join(str(seed) for seed in sorted(seeds, key=str))),
        ),
    )


def _write_robustness_report(path: Path) -> tuple[Path, ...]:
    from late_ming_lab.experiments.policy_robustness import load_p12, write_report

    loaded = load_p12(path)
    return (
        write_report(
            path.parent.parent,
            arms=loaded.arms,
            matrix=loaded.matrix,
            verdicts=loaded.verdicts,
            levels=loaded.levels,
            summary=loaded.summary,
            movement=loaded.movement,
            directory=loaded.directory,
        ),
    )


def write_reports(target: str | Path) -> tuple[Path, ...]:
    """Regenerate the documents the artifacts at ``target`` support, and nothing else."""
    path = Path(target)
    summary = summarize(path)
    if summary.kind == "p10-root":
        from late_ming_lab.experiments.ablation import (
            ABLATION_LABEL,
            GRID_LABEL,
            MORRIS_LABEL,
            SOBOL_LABEL,
            write_experiment_reports,
        )

        return write_experiment_reports(
            path.parent.parent,
            ablations=path / ABLATION_LABEL,
            morris=path / MORRIS_LABEL,
            sobol=path / SOBOL_LABEL,
            tipping=path / GRID_LABEL,
        )
    if summary.kind == "policy-robustness-batch":
        return _write_robustness_report(path)
    if summary.kind == "experiment-batch":
        from late_ming_lab.experiments.policy_robustness import load_p12, write_report

        loaded = load_p12(path)
        return (
            write_report(
                path.parent.parent,
                arms=loaded.arms,
                matrix=loaded.matrix,
                verdicts=loaded.verdicts,
                levels=loaded.levels,
                summary=loaded.summary,
                movement=loaded.movement,
                directory=loaded.directory,
            ),
        )
    if summary.kind == "calibration-batch":
        from late_ming_lab.experiments.calibration import write_calibration_reports

        return write_calibration_reports(path.parent.parent, batch=path)
    if summary.kind == "mechanism-cards":
        from late_ming_lab.synthesis.cards import build_cards
        from late_ming_lab.synthesis.evidence import load_evidence
        from late_ming_lab.synthesis.report import write_mechanism_docs, write_synthesis

        root = path.parent.parent
        bundle = load_evidence(root)
        book = build_cards(bundle)
        return (*write_mechanism_docs(root, book), write_synthesis(root, book, bundle))
    raise AnalysisError(
        f"a {summary.kind} artifact has no document to regenerate: it is already the record"
    )
