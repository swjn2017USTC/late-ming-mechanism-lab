"""The experiment families: what "run an experiment" means, one declaration per family.

P10 to P13 each built a runner and its artifact directory. This module is the single place that
names them, so the command line does not grow a branch per phase and a reader can see what the
project can run in one table. It adds no behaviour: every entry calls the runner the phase wrote.

A family is only listed here when it can be run *on its own*. The Morris and Sobol designs are not:
they need the parameter selection that :func:`~late_ming_lab.experiments.ablation.run_p10` computes
from the card ranges, so they are steps inside ``p10`` rather than families a caller can start
half-way through.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: Where a family's artifact directory sits, relative to the repository root.
EXPERIMENT_ROOT: Final[str] = "outputs/experiments"
INTEGRATED_LABEL: Final[str] = "p07-sandbox"
CALIBRATION_ROOT: Final[str] = "outputs/calibration"
CARD_ROOT: Final[str] = "docs/mechanisms"


class ExperimentError(RuntimeError):
    """Raised when a family cannot be run as declared."""


@dataclass(frozen=True, slots=True)
class Family:
    """One runnable experiment: what it is, where it writes, and what runs it."""

    name: str
    description: str
    runner: Callable[..., tuple[Path, ...]]


def _run_p10(root: Path, *, replicates: int | None, seed: int | None) -> tuple[Path, ...]:
    from late_ming_lab.experiments.ablation import P10_BASE_SEED, run_p10
    from late_ming_lab.experiments.runner import DEFAULT_REPLICATES

    written = run_p10(
        root,
        replicates=replicates if replicates is not None else DEFAULT_REPLICATES,
        base_seed=seed if seed is not None else P10_BASE_SEED,
    )
    return tuple(written.values())


def _run_ablations(root: Path, *, replicates: int | None, seed: int | None) -> tuple[Path, ...]:
    from late_ming_lab.experiments.ablation import (
        ABLATION_LABEL,
        P10_BASE_SEED,
        run_ablation_experiment,
    )
    from late_ming_lab.experiments.runner import DEFAULT_REPLICATES

    return run_ablation_experiment(
        root,
        output_dir=root / EXPERIMENT_ROOT / ABLATION_LABEL,
        replicates=replicates if replicates is not None else DEFAULT_REPLICATES,
        base_seed=seed if seed is not None else P10_BASE_SEED,
    ).write()


def _run_p12(root: Path, *, replicates: int | None, seed: int | None) -> tuple[Path, ...]:
    from late_ming_lab.experiments.policy_robustness import BASE_SEED, DEFAULT_REPLICATES, run_p12

    result = run_p12(
        root,
        replicates=replicates if replicates is not None else DEFAULT_REPLICATES,
        base_seed=seed if seed is not None else BASE_SEED,
    )
    return (result.directory, result.report)


def _run_integrated(root: Path, *, replicates: int | None, seed: int | None) -> tuple[Path, ...]:
    """The sandbox over its declared scenarios: deterministic, so it has no replicate axis."""
    from late_ming_lab.experiments.integrated import run_integrated_experiment

    if replicates not in (None, 1):
        raise ExperimentError(
            "the integrated family runs each declared scenario once: it has no replicate "
            "axis, so a count above one would duplicate identical runs"
        )
    results = run_integrated_experiment()
    return results.write(root / EXPERIMENT_ROOT / INTEGRATED_LABEL)


def _run_evidence(root: Path, *, replicates: int | None, seed: int | None) -> tuple[Path, ...]:
    from late_ming_lab.experiments.evidence import write_evidence_reports

    if replicates is not None or seed is not None:
        raise ExperimentError("the evidence family writes documents; it has no seeds to override")
    return write_evidence_reports(root)


def _run_mechanisms(root: Path, *, replicates: int | None, seed: int | None) -> tuple[Path, ...]:
    from late_ming_lab.synthesis.cards import build_cards
    from late_ming_lab.synthesis.evidence import load_evidence
    from late_ming_lab.synthesis.report import write_mechanism_docs, write_synthesis

    if replicates is not None or seed is not None:
        raise ExperimentError("the mechanisms family writes cards; it has no seeds to override")
    bundle = load_evidence(root)
    book = build_cards(bundle)
    return (*write_mechanism_docs(root, book), write_synthesis(root, book, bundle))


def _run_p06(root: Path, *, replicates: int | None, seed: int | None) -> tuple[Path, ...]:
    """The V2-P06 pilot ladder: rungs, the gate, the freeze and the generated document.

    A driver of its own, because the phase's artifact must be reproducible from the tree: the
    review found the first pilot had been run by hand and its hash could not be regenerated.
    """
    from late_ming_lab.calibration.simulator import SimulatorSettings
    from late_ming_lab.calibration.v2 import (
        PROCESS_SEEDS,
        SAMPLER_SEEDS,
        SeedConditionedSimulator,
        freeze_posterior,
        ladder_gate,
        prior_widths,
        run_rung,
        write_calibration_document,
        write_rung_table,
    )
    from late_ming_lab.evidence.cards import load_cards
    from late_ming_lab.evidence.ledger import load_patterns

    if replicates is not None or seed is not None:
        raise ExperimentError("the p06 pilot's rungs and seeds are declared; it has no overrides")
    cards = load_cards(root)
    registry = load_patterns(root)
    settings = SimulatorSettings(tick_count=72, warmup_ticks=12)
    widths = prior_widths(cards)
    rungs = []
    stop = None
    for particles in (4, 8):
        for sampler_seed in SAMPLER_SEEDS:
            simulator = SeedConditionedSimulator(
                cards, registry, mode="process-seeds", seeds=PROCESS_SEEDS, settings=settings
            )
            rung = run_rung(simulator, cards, particles=particles, sampler_seed=sampler_seed)
            rungs.append(rung)
        if len(rungs) >= 2 * len(SAMPLER_SEEDS):
            stop = ladder_gate(
                rungs[0],
                rungs[-1],
                prior_widths=widths,
                previous_prediction=rungs[0].prediction,
            )
            if stop.converged:
                break
    if stop is None:
        raise ExperimentError("the p06 pilot produced no gate verdict")
    freeze_posterior(
        root,
        rungs=tuple(rungs),
        stop=stop,
        simulator=simulator,
        sampler_seeds=SAMPLER_SEEDS,
    )
    return (write_rung_table(root, tuple(rungs)), write_calibration_document(root))


def _run_p04(root: Path, *, replicates: int | None, seed: int | None) -> tuple[Path, ...]:
    """The V2-P04 arms, the no-op check and the generated diagnosis.

    `replicates` is refused rather than reinterpreted: the phase's arms are fixed to a declared set
    of world seeds, and a different count would be a different comparison.
    """
    from late_ming_lab.experiments.holdout import HOLDOUT_SEEDS, load_arm_runs, protocol_scores
    from late_ming_lab.experiments.holdout_report import write_documents

    if replicates is not None:
        raise ExperimentError(
            "the p04 family runs its declared seeds; it has no replicate override"
        )
    if seed is not None and seed != HOLDOUT_SEEDS[0]:
        raise ExperimentError(
            "the p04 family's seeds are declared with the phase; a different base seed would be a "
            "different comparison"
        )
    runs = load_arm_runs(root=root)
    scores = protocol_scores(runs, root=root)
    return write_documents(root, runs, scores=scores)


#: Every family a caller may run, in the order the phases introduced them.
FAMILIES: Final[dict[str, Family]] = {
    "ablations": Family(
        name="ablations",
        description="the baseline, the nine ablations and the joint arms, at every replicate",
        runner=_run_ablations,
    ),
    "p10": Family(
        name="p10",
        description="the ablations, the Morris screen, the Sobol indices and the tipping grid",
        runner=_run_p10,
    ),
    "p12": Family(
        name="p12",
        description="three declared decision policies under common random numbers",
        runner=_run_p12,
    ),
    "p06": Family(
        name="p06",
        description="the V2-P06 calibration pilot ladder, its gate, its freeze and its document",
        runner=_run_p06,
    ),
    "p04": Family(
        name="p04",
        description=(
            "the V2-P04 hold-out arms on the historical core, their no-op check and the diagnosis"
        ),
        runner=_run_p04,
    ),
    "integrated": Family(
        name="integrated",
        description="the sandbox over its declared scenarios, once each",
        runner=_run_integrated,
    ),
    "evidence": Family(
        name="evidence",
        description="regenerate the evidence coverage, gaps and uncertainty documents",
        runner=_run_evidence,
    ),
    "mechanisms": Family(
        name="mechanisms",
        description="regenerate the mechanism cards and the synthesis report from the artifacts",
        runner=_run_mechanisms,
    ),
}


def run_family(
    name: str, *, root: str | Path, replicates: int | None = None, seed: int | None = None
) -> tuple[Path, ...]:
    """Run one family and return what it wrote."""
    try:
        family = FAMILIES[name]
    except KeyError as error:
        raise ExperimentError(
            f"unknown family {name!r}; expected one of {', '.join(sorted(FAMILIES))}"
        ) from error
    return family.runner(Path(root), replicates=replicates, seed=seed)
