"""The sampler: the sandbox's pattern-distance vector as a PyMC ``Simulator``, sampled by SMC.

The objective is a deterministic function of the draw — the sandbox is seeded once and every
proposal runs under the same random numbers — so the pseudo-likelihood PyMC maximises is a Laplace
kernel on the pattern scores against a vector of zeros: *five patterns, each as close to fully
consistent as it can be*. The kernel's width is a declared tolerance per pattern, not a number
chosen to make the posterior look sharp.

Two consequences are deliberate:

- **The result is a particle set, never an optimum.** SMC returns the final population; the ensemble
  module reports each draw's scores and lets a reader see the whole surface.
- **Nothing is fitted to a historical magnitude.** The target vector is zeros — a statement about
  agreement with the pattern's own wording, not about matching a recorded number. Where P08 recorded
  a magnitude (the price ceiling, for instance) it is compared in the report, outside the objective.

The simulator caches its runs by draw, so the replicates PyMC requests for one particle cost a
lookup rather than a simulation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import pymc as pm

from late_ming_lab.calibration.simulator import SandboxSimulator

#: How far a pattern's score may sit from full consistency before the kernel discounts it. A score
#: is the share of a pattern's checks that failed, and the target patterns carry two or three checks
#: each, so a quarter allows a single failed check while still separating a run that fails half of
#: them. The number is declared here, is recorded in the manifest, and is not tuned.
TOLERANCE_PER_PATTERN: Final[float] = 0.25


class SamplerError(RuntimeError):
    """Raised when the sampler cannot be built or run against the given settings."""


@dataclass(frozen=True, slots=True)
class SmcSettings:
    """How the batch is sampled: particles, chains, seed, tolerance."""

    particles: int = 40
    chains: int = 1
    random_seed: int = 20_260_913
    tolerance: float = TOLERANCE_PER_PATTERN


@dataclass(frozen=True, slots=True)
class SmcDiagnostics:
    """What the sampler itself reported: the tempered stages and their acceptance rates."""

    stages: int
    beta: tuple[float, ...]
    accept_rate: tuple[float, ...]
    log_marginal_likelihood: tuple[float, ...]
    distinct_draws: int
    simulations: int


def build_model(simulator: SandboxSimulator, *, settings: SmcSettings) -> pm.Model:
    """The P09 model: uniform priors on the card ranges, one Simulator RV holding the objective."""
    priors = simulator.priors
    order = priors.names()

    def pattern_scores(
        rng: np.random.Generator, *theta: object, size: int | Sequence[int] | None = None
    ) -> np.ndarray:
        """The objective vector for each requested replicate, one sandbox run per distinct draw."""
        replicated = 1 if size is None else int(np.prod(np.asarray(size, dtype=int)))
        values = [np.asarray(value, dtype=float).ravel() for value in theta]
        rows: list[np.ndarray] = []
        for index in range(replicated):
            draw = {
                name: float(values[position][index % values[position].size])
                for position, name in enumerate(order)
            }
            rows.append(np.asarray(simulator.distance(draw), dtype=float))
        data = np.stack(rows)
        return data[0] if size is None else data

    pattern_count = len(simulator.objective.pattern_ids)
    with pm.Model() as model:
        # The uniform priors, one variable per parameter, in the declared order.
        draws = {
            prior.name: pm.Uniform(prior.name, lower=prior.low, upper=prior.high)
            for prior in priors
        }
        pm.Simulator(
            "patterns",
            pattern_scores,
            params=[draws[name] for name in order],
            sum_stat="identity",
            distance="laplace",
            epsilon=np.full(pattern_count, settings.tolerance),
            observed=np.zeros(pattern_count),
        )
    return model


def sample(
    simulator: SandboxSimulator, *, settings: SmcSettings, progressbar: bool = False
) -> tuple[object, SmcDiagnostics]:
    """Run SMC and return the inference data with its diagnostics."""
    model = build_model(simulator, settings=settings)
    idata = pm.sample_smc(
        draws=settings.particles,
        chains=settings.chains,
        cores=1,
        random_seed=settings.random_seed,
        model=model,
        progressbar=progressbar,
        compute_convergence_checks=False,
    )
    return idata, diagnostics_from(idata, simulator)


def diagnostics_from(idata: object, simulator: SandboxSimulator) -> SmcDiagnostics:
    """Read the stage schedule, acceptance and the number of distinct simulated draws."""
    stats = idata.sample_stats  # type: ignore[attr-defined]
    beta = tuple(float(value) for value in np.asarray(stats["beta"].values).ravel())
    accept = tuple(float(value) for value in np.asarray(stats["accept_rate"].values).ravel())
    marginal = tuple(
        float(value) for value in np.asarray(stats["log_marginal_likelihood"].values).ravel()
    )
    return SmcDiagnostics(
        stages=len(beta),
        beta=beta,
        accept_rate=accept,
        log_marginal_likelihood=marginal,
        distinct_draws=simulator.distinct_draw_count(),
        simulations=simulator.simulation_count(),
    )
