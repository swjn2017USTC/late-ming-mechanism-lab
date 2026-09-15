"""The calibration phase's entry point: run the batch, then write the reports it supports.

```bash
uv run python -c "from late_ming_lab.experiments.calibration import run_calibration_batch; \
    run_calibration_batch('.')"
uv run python -c "from late_ming_lab.experiments.calibration import write_calibration_reports; \
    write_calibration_reports('.')"
```

The batch is deliberately small. It runs the toy sandbox in the synthetic historical-shock scenario,
scores the calibration window, samples the declared priors with SMC, and writes the particle set to
``outputs/calibration/<batch_id>/`` with the digests that identify it — the frozen registry, the
declared bounds, the declared checks, the scenario, the seeds. Nothing about the run is chosen after
seeing a score, and no single draw is selected as the answer.

Writing the reports is a separate step because it reads the batch back from disk: a report that
cannot be regenerated from the artifact is a claim nobody can check.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from late_ming_lab.calibration.ensemble import Draw, Ensemble, build_provenance
from late_ming_lab.calibration.freeze import evidence_digest, objective_digest
from late_ming_lab.calibration.prediction import (
    load_posterior_predictive,
    posterior_predictive,
    write_posterior_predictive,
)
from late_ming_lab.calibration.priors import PriorTable, build_priors
from late_ming_lab.calibration.reports import CalibrationReportInputs, write_reports
from late_ming_lab.calibration.simulator import SandboxSimulator
from late_ming_lab.calibration.smc import SmcDiagnostics, SmcSettings, sample
from late_ming_lab.calibration.targets import Objective, objective_payload
from late_ming_lab.evidence.cards import ParameterCards, load_cards
from late_ming_lab.evidence.ledger import PatternRegistry, load_patterns

#: Where batches are written. The directory is under the run store's tree so a batch sits beside the
#: runs it was built from rather than in a place of its own.
BATCH_ROOT: Final[str] = "outputs/calibration"
DIAGNOSTICS_FILE: Final[str] = "smc_diagnostics.json"
REPORT_DIR: Final[str] = "docs/calibration"

#: The batch every report in this phase is generated from unless another is named.
DEFAULT_PARTICLES: Final[int] = 40
DEFAULT_SAMPLER_SEED: Final[int] = 20_260_913


@dataclass(frozen=True, slots=True)
class CalibrationInputs:
    """The frozen side of the experiment: cards, patterns, priors and the objective."""

    cards: ParameterCards
    patterns: PatternRegistry
    priors: PriorTable
    objective: Objective


def load_calibration_inputs(root: str | Path) -> CalibrationInputs:
    directory = Path(root)
    cards = load_cards(directory)
    patterns = load_patterns(directory)
    return CalibrationInputs(
        cards=cards,
        patterns=patterns,
        priors=build_priors(cards),
        objective=Objective.from_registry(patterns),
    )


def batch_id(inputs: CalibrationInputs, settings: SmcSettings, *, root: str | Path) -> str:
    """A name that carries the frozen registry and the sampler settings it belongs to."""
    digest = evidence_digest(root)[:8]
    return f"p09-cards{digest}-{settings.particles}p-ch{settings.chains}-s{settings.random_seed}"


def run_calibration_batch(
    root: str | Path,
    *,
    particles: int = DEFAULT_PARTICLES,
    chains: int = 1,
    sampler_seed: int = DEFAULT_SAMPLER_SEED,
    output_dir: str | Path | None = None,
    progressbar: bool = False,
) -> tuple[Ensemble, SmcDiagnostics, Path]:
    """Run one SMC batch and write the ensemble, its manifest and the stage diagnostics."""
    directory = Path(root)
    inputs = load_calibration_inputs(directory)
    settings = SmcSettings(particles=particles, chains=chains, random_seed=sampler_seed)
    simulator = SandboxSimulator(inputs.cards, inputs.patterns)
    idata, diagnostics = sample(simulator, settings=settings, progressbar=progressbar)
    ensemble = ensemble_from(
        idata=idata,
        simulator=simulator,
        inputs=inputs,
        settings=settings,
        root=directory,
        name=batch_id(inputs, settings, root=directory),
    )
    target = Path(output_dir) if output_dir is not None else directory / BATCH_ROOT
    batch_dir = target / ensemble.provenance.batch_id
    ensemble.write(batch_dir)
    (batch_dir / DIAGNOSTICS_FILE).write_text(
        json.dumps(
            {
                "stages": diagnostics.stages,
                "beta": list(diagnostics.beta),
                "accept_rate": list(diagnostics.accept_rate),
                "log_marginal_likelihood": list(diagnostics.log_marginal_likelihood),
                "distinct_draws": diagnostics.distinct_draws,
                "simulations": diagnostics.simulations,
                "caveat": (
                    "the marginal likelihood is computed against a pseudo-likelihood, so it ranks "
                    "this batch's own settings and is not evidence about the model"
                ),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return ensemble, diagnostics, batch_dir


def ensemble_from(
    *,
    idata: object,
    simulator: SandboxSimulator,
    inputs: CalibrationInputs,
    settings: SmcSettings,
    root: str | Path,
    name: str,
) -> Ensemble:
    """Turn the sampler's final particles into an ensemble with its provenance."""
    posterior = idata.posterior  # type: ignore[attr-defined]
    names = inputs.priors.names()
    chains = int(posterior.sizes["chain"])
    draws_per_chain = int(posterior.sizes["draw"])
    draws = []
    for chain in range(chains):
        for index in range(draws_per_chain):
            parameters = tuple(
                (name, float(posterior[name].values[chain, index])) for name in names
            )
            scores = simulator.distance(dict(parameters))
            draws.append(
                Draw(
                    parameters=parameters,
                    scores=scores,
                    weight=1.0 / (chains * draws_per_chain),
                )
            )
    scenario = simulator.settings.scenario()
    provenance = build_provenance(
        batch_id=name,
        root=root,
        priors=inputs.priors,
        objective_digest=objective_digest(objective_payload()),
        pattern_schema_version=inputs.patterns.schema_version,
        simulation_config_hash=simulator.settings.config().content_hash(),
        root_seed=simulator.settings.root_seed,
        scenario={
            "dataset": scenario.dataset,
            "monthly_event_probability": scenario.monthly_event_probability,
            "severity_floor": scenario.severity_floor,
            "nominal_pressure": scenario.nominal_pressure,
            "pay_share_of_treasury": scenario.pay_share_of_treasury,
            "garrison_troops": scenario.garrison_troops,
        },
        target_ids=inputs.objective.pattern_ids,
        hold_out_ids=tuple(sorted(inputs.patterns.hold_out_ids)),
        particles=settings.particles,
        chains=settings.chains,
        tolerance=settings.tolerance,
        sampler_seed=settings.random_seed,
    )
    return Ensemble(
        provenance=provenance, draws=tuple(draws), pattern_ids=inputs.objective.pattern_ids
    )


def run_posterior_predictive(
    root: str | Path,
    *,
    batch_dir: str | Path,
    posterior_hash: str,
    draw_limit: int | None = None,
) -> Path:
    """Run the ensemble forward into every window and persist the predictive tables.

    The reserved windows may be read only against a frozen posterior, and only by a caller that
    names its hash: this is the isolation V2-P03 froze and V2-P06 built the gate for. A caller
    without the hash, or with another one, is refused before a single run starts — the check is here
    rather than in the report because a report cannot refuse anything.
    """
    from late_ming_lab.calibration.v2 import assert_holdout_allowed

    assert_holdout_allowed(root, posterior_hash=posterior_hash)
    directory = Path(root) / str(batch_dir)
    inputs = load_calibration_inputs(root)
    ensemble = Ensemble.load(directory)
    result = posterior_predictive(ensemble, inputs.cards, inputs.patterns, draw_limit=draw_limit)
    write_posterior_predictive(result, directory)
    return directory


def write_calibration_reports(
    root: str | Path,
    *,
    batch: str | Path | None = None,
    comparison: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> tuple[Path, ...]:
    """Regenerate the reports from a batch directory on disk.

    A second batch, at the same settings and a different sampler seed, adds the stability report;
    without one the four documents are written and the absence is not dressed up as agreement.
    """
    directory = Path(root)
    batch_dir = Path(batch) if batch is not None else latest_batch(directory)
    inputs = load_calibration_inputs(directory)
    ensemble = Ensemble.load(batch_dir)
    arguments = CalibrationReportInputs(
        root=directory,
        cards=inputs.cards,
        patterns=inputs.patterns,
        priors=inputs.priors,
        objective=inputs.objective,
        ensemble=ensemble,
        predictive=load_posterior_predictive(batch_dir),
        diagnostics=json.loads((batch_dir / DIAGNOSTICS_FILE).read_text(encoding="utf-8")),
        comparison=None if comparison is None else Ensemble.load(comparison),
    )
    target = Path(output_dir) if output_dir is not None else directory / REPORT_DIR
    return write_reports(arguments, target)


def latest_batch(root: str | Path) -> Path:
    """The most recently written batch directory, so the reports need no argument."""
    candidates = sorted(Path(root, BATCH_ROOT).glob("p09-*"))
    if not candidates:
        raise FileNotFoundError(
            f"no calibration batch under {Path(root, BATCH_ROOT)}; run run_calibration_batch first"
        )
    return candidates[-1]
