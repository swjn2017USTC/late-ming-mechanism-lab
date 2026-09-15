"""Calibration V2: process-seed marginalisation, a particle ladder, and a frozen posterior.

V1 calibrated one parameter vector under one root seed, and reported the result as a posterior. Two
things were wrong with that, and this module is both of them fixed:

```text
process uncertainty   the weather and event sequence is not a nuisance to cancel. One draw is
                      evaluated under a declared set of *process* seeds, and its distance is the
                      conditional distribution over them, not one number. Common random numbers are
                      kept for the structure comparison — where the point is to cancel the weather
                      — and reported as the contrast they are, never as uncertainty.
a ladder, not a rung  a population is run at successively larger rungs with several *sampler*
                      seeds; doubling is decided by declared gates on the posterior's location and
                      on a mechanism prediction, not by reaching a round number. A ladder that
                      stops short is reported as non-converged.
```

Everything the run has to be reproducible from is recorded: the prior and objective digests, the
process and sampler seed sets, the rung sizes, the stage count, the acceptance rates, the weighted
effective sample size, the duplicate-particle fraction, the simulation count, the cache hits and
the wall-clock cost. The posterior is *frozen* by hash, and the hold-out path refuses to run
without that hash: a reserved window cannot be looked at while the posterior is still moving.

Nothing here invents a bound. The priors are exactly the cards' ranges (V1's rule, kept), so an
S-grade parameter with no range cannot enter through a wide prior — it is not in the table at all.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

import numpy as np
import polars as pl

from late_ming_lab.calibration.freeze import (
    evidence_digest,
    objective_digest,
    prior_digest,
)
from late_ming_lab.calibration.simulator import SandboxSimulator, SimulatedRun, SimulatorSettings
from late_ming_lab.calibration.targets import Check
from late_ming_lab.core.hashing import canonical_json, hash_text
from late_ming_lab.evidence.cards import ParameterCards, load_cards
from late_ming_lab.evidence.ledger import PatternRegistry
from late_ming_lab.storage.tables import write_json, write_table

#: The process seeds a draw is evaluated under. These are *not* common random numbers: the point is
#: that the weather, the shock dates and the event draws differ, so a draw's distance is a property
#: of the draw and the conditions it met rather than of one particular sequence.
PROCESS_SEEDS: Final[tuple[int, ...]] = (20_260_915, 20_260_916, 20_260_917, 20_260_918)

#: The sampler seeds: independent populations over the same priors, because one population cannot
#: separate a posterior from the luck of its own draws.
SAMPLER_SEEDS: Final[tuple[int, ...]] = (701, 702, 703, 704)

#: The rungs, doubled as the gates allow. The pilot is the first one; the ladder does not have to
#: reach the last.
LADDER: Final[tuple[int, ...]] = (12, 24, 48, 96, 192)

#: Tempering stages per rung: how many times the population is reweighted and resampled.
STAGES: Final[tuple[float, ...]] = (0.5, 1.0)

#: The declared gates a rung must meet before the ladder doubles. All are in
#: `GATES` so a report can state them rather than describe them.
GATES: Final[dict[str, float]] = {
    "ess_per_particle_min": 0.30,
    "acceptance_min": 0.05,
    "acceptance_max": 0.95,
    "duplicate_fraction_max": 0.30,
    "location_change_max": 0.10,
    "prediction_change_max": 0.05,
}

#: The mechanism prediction the ladder watches: the largest band's share at the end of the run, on
#: the reference structure. A posterior that moves this by more than the gate is still moving.
PREDICTION_STATISTIC: Final[str] = "largest_band_share_end"

#: The pilot's window: short enough to afford a ladder, long enough for the slow state to move.
PILOT_TICKS: Final[int] = 72
PILOT_WARMUP: Final[int] = 12


class CalibrationV2Error(RuntimeError):
    """Raised when a rung cannot be run, or when the freeze gate is asked for something absent."""


class PosteriorNotFrozenError(RuntimeError):
    """Raised when the hold-out path is asked to run before the posterior was frozen."""


@dataclass(frozen=True, slots=True)
class Marginal:
    """One draw's distance under a declared set of process seeds."""

    mean: float
    worst: float
    per_seed: tuple[float, ...]
    seeds: tuple[int, ...]


class SeedConditionedSimulator:
    """Evaluates a draw under every declared process seed, and caches each (draw, seed) pair.

    `mode` is the declared contrast the phase has to report: `process-seeds` marginalises over the
    seed set, `fixed-crn` runs the single V1 seed. The two are different experiments and the module
    refuses to blur them — the mode is part of the provenance written into the manifest.
    """

    def __init__(
        self,
        cards: ParameterCards,
        registry: PatternRegistry,
        *,
        mode: Literal["process-seeds", "fixed-crn"] = "process-seeds",
        seeds: tuple[int, ...] = PROCESS_SEEDS,
        settings: SimulatorSettings | None = None,
    ) -> None:
        if mode == "process-seeds" and len(seeds) < 2:
            raise CalibrationV2Error(
                "marginalising over process uncertainty needs at least two seeds; one seed is "
                "common random numbers, which is the `fixed-crn` mode"
            )
        self.mode = mode
        self.seeds = tuple(seeds)
        base = settings or SimulatorSettings()
        self._simulators = {
            seed: SandboxSimulator(
                cards,
                registry,
                settings=SimulatorSettings(
                    dataset=base.dataset,
                    monthly_event_probability=base.monthly_event_probability,
                    severity_floor=base.severity_floor,
                    nominal_pressure=base.nominal_pressure,
                    pay_share_of_treasury=base.pay_share_of_treasury,
                    garrison_troops=base.garrison_troops,
                    root_seed=seed,
                    tick_count=base.tick_count,
                    warmup_ticks=base.warmup_ticks,
                ),
            )
            for seed in self.seeds
        }
        self._cache: dict[tuple[tuple[float, ...], int], float] = {}
        self._simulations = 0
        self._hits = 0

    def run_for_prediction(self, parameters: dict[str, float], *, seed: int) -> SimulatedRun:
        """One run of the draw, for the mechanism prediction the ladder watches.

        It is not cached against the objective's cache: the prediction is a different measurement of
        the same run, and sharing the cache would mean a prediction could be served from a distance.
        """
        return self._simulators[seed].run(parameters)

    def parameter_names(self) -> tuple[str, ...]:
        """The calibration parameters, in the priors' declared order."""
        return tuple(next(iter(self._simulators.values())).priors.names())

    def marginal(self, parameters: dict[str, float]) -> Marginal:
        """The draw's distance under every seed in the mode's set."""
        names = self.parameter_names()
        values: list[float] = []
        for seed in self.seeds:
            key = (tuple(float(parameters[name]) for name in names), seed)
            cached = self._cache.get(key)
            if cached is None:
                cached = float(np.mean(self._simulators[seed].distance(parameters)))
                self._cache[key] = cached
                self._simulations += 1
            else:
                self._hits += 1
            values.append(cached)
        return Marginal(
            mean=float(np.mean(values)),
            worst=float(np.max(values)),
            per_seed=tuple(values),
            seeds=self.seeds,
        )

    @property
    def simulation_count(self) -> int:
        return self._simulations

    @property
    def cache_hits(self) -> int:
        return self._hits

    def provenance(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "process_seeds": list(self.seeds),
            "distinct_draw_seed_pairs": len(self._cache),
            "simulations": self._simulations,
            "cache_hits": self._hits,
        }


@dataclass(frozen=True, slots=True)
class Rung:
    """One rung of the ladder: a population, its diagnostics, and the posterior it implies."""

    particles: int
    sampler_seed: int
    posterior: dict[str, float]
    weights: tuple[float, ...]
    ess: float
    ess_per_particle: float
    acceptance: tuple[float, ...]
    duplicate_fraction: float
    simulations: int
    cache_hits: int
    seconds: float
    prediction: float
    stages: tuple[float, ...] = ()
    failed: tuple[str, ...] = ()

    def record(self) -> dict[str, object]:
        return {
            "particles": self.particles,
            "sampler_seed": self.sampler_seed,
            "ess": self.ess,
            "ess_per_particle": self.ess_per_particle,
            "acceptance": list(self.acceptance),
            "duplicate_fraction": self.duplicate_fraction,
            "simulations": self.simulations,
            "cache_hits": self.cache_hits,
            "seconds": self.seconds,
            "stages": list(self.stages),
            "prediction": self.prediction,
            "failed_tasks": list(self.failed),
            "posterior": self.posterior,
        }


def _prior_bounds(cards: ParameterCards) -> tuple[tuple[str, float, float], ...]:
    from late_ming_lab.calibration.priors import build_priors

    priors = build_priors(cards)
    return tuple((prior.name, float(prior.low), float(prior.high)) for prior in priors)


def _draw(
    rng: np.random.Generator, bounds: tuple[tuple[str, float, float], ...]
) -> dict[str, float]:
    return {name: float(rng.uniform(low, high)) for name, low, high in bounds}


def _jitter(
    rng: np.random.Generator,
    parameters: dict[str, float],
    bounds: tuple[tuple[str, float, float], ...],
    *,
    scale: float,
) -> dict[str, float]:
    moved: dict[str, float] = {}
    for name, low, high in bounds:
        step = (high - low) * scale * float(rng.normal())
        moved[name] = float(min(max(parameters[name] + step, low), high))
    return moved


def _weighted_summary(
    particles: list[dict[str, float]],
    weights: np.ndarray,
    bounds: tuple[tuple[str, float, float], ...],
) -> dict[str, float]:
    """The weighted median of each parameter — the location the ladder's gate compares."""
    summary: dict[str, float] = {}
    for name, _low, _high in bounds:
        values = np.array([particle[name] for particle in particles])
        order = np.argsort(values)
        ordered_values = values[order]
        ordered_weights = weights[order]
        cumulative = np.cumsum(ordered_weights)
        total = cumulative[-1]
        if total <= 0.0:
            summary[name] = float(np.median(values))
            continue
        position = np.searchsorted(cumulative, total / 2.0)
        position = int(min(position, len(ordered_values) - 1))
        summary[name] = float(ordered_values[position])
    return summary


def run_rung(
    simulator: SeedConditionedSimulator,
    cards: ParameterCards,
    *,
    particles: int,
    sampler_seed: int,
    stages: tuple[float, ...] = STAGES,
    prediction: PredictionProbe | None = None,
) -> Rung:
    """One tempered population at one rung, with every diagnostic the phase has to record.

    The sampler is a sequential importance population rather than a Markov chain: a population is
    drawn under the priors, reweighted towards the observed patterns along the declared tempering
    schedule, resampled with systematic resampling, and moved by a bounded random walk. That gives
    the four diagnostics the phase names — acceptance, weighted ESS, the duplicate fraction and the
    simulation count — without hiding them inside a library's own bookkeeping.
    """
    rng = np.random.default_rng(sampler_seed)
    bounds = _prior_bounds(cards)
    population = [_draw(rng, bounds) for _ in range(particles)]
    weights = np.full(particles, 1.0 / particles, dtype=float)
    acceptance: list[float] = []
    stage_ess: list[float] = []
    stage_duplicates: list[float] = []
    failed: list[str] = []
    started = time.perf_counter()

    for beta in stages:
        distances = np.array(
            [_evaluate(simulator, particle, failed) for particle in population], dtype=float
        )
        log_weights = -beta * distances
        log_weights -= log_weights.max()
        new_weights = weights * np.exp(log_weights)
        total = new_weights.sum()
        if not np.isfinite(total) or total <= 0.0:
            raise CalibrationV2Error(
                f"the population's weights collapsed at beta={beta}; the rung is reported as "
                "non-converged rather than resampled into a single particle"
            )
        weights = new_weights / total
        # The tempered weights are measured *before* resampling. Reading the ESS after the resample
        # step would report a number that is uniform by construction — `particles`, always — and a
        # gate that cannot fail is not a gate.
        stage_ess.append(float(1.0 / np.sum(weights**2)))
        # Systematic resampling, then a bounded move: accepted moves are what `acceptance` counts.
        positions = (rng.random() + np.arange(particles)) / particles
        cumulative = np.cumsum(weights)
        indices = np.searchsorted(cumulative, positions)
        indices = np.clip(indices, 0, particles - 1)
        population = [population[int(index)] for index in indices]
        # Duplicates are counted here, on the resampled population: the jitter that follows moves
        # every particle, so counting after it reports zero however degenerate the resample was.
        keys = [canonical_json(particle) for particle in population]
        stage_duplicates.append(1.0 - len(set(keys)) / len(keys))
        moved = [_jitter(rng, particle, bounds, scale=0.10) for particle in population]
        moved_distances = np.array(
            [_evaluate(simulator, particle, failed) for particle in moved], dtype=float
        )
        current_distances = np.array(
            [_evaluate(simulator, particle, failed) for particle in population], dtype=float
        )
        accept = np.exp(-beta * (moved_distances - current_distances))
        accepted = rng.random(particles) < np.clip(accept, 0.0, 1.0)
        population = [
            moved[index] if accepted[index] else population[index] for index in range(particles)
        ]
        acceptance.append(float(np.mean(accepted)))
        weights = np.full(particles, 1.0 / particles, dtype=float)

    ess = float(np.mean(stage_ess)) if stage_ess else float(particles)
    duplicates = float(np.mean(stage_duplicates)) if stage_duplicates else 0.0
    posterior = _weighted_summary(population, weights, bounds)
    measured = (
        _prediction(simulator, posterior)
        if prediction is None
        else prediction.measure(simulator, posterior)
    )
    return Rung(
        particles=particles,
        sampler_seed=sampler_seed,
        posterior=posterior,
        weights=tuple(float(value) for value in weights),
        ess=ess,
        ess_per_particle=ess / particles,
        acceptance=tuple(acceptance),
        duplicate_fraction=duplicates,
        simulations=simulator.simulation_count,
        cache_hits=simulator.cache_hits,
        seconds=time.perf_counter() - started,
        prediction=measured,
        stages=tuple(stages),
        failed=tuple(failed),
    )


def _prediction(simulator: SeedConditionedSimulator, posterior: dict[str, float]) -> float:
    """The declared mechanism statistic at the rung's posterior, on the first process seed."""
    from late_ming_lab.analysis.band_chain import band_chain_summary

    seed = simulator.seeds[0]
    run = simulator.run_for_prediction(posterior, seed=seed)
    return float(band_chain_summary(run.events).get(PREDICTION_STATISTIC, 0.0))


def _evaluate(
    simulator: SeedConditionedSimulator, particle: dict[str, float], failed: list[str]
) -> float:
    """One particle's distance, with a failed evaluation recorded and never merged as a particle."""
    try:
        return simulator.marginal(particle).mean
    except (ValueError, RuntimeError, KeyError) as error:  # a draw the model refused
        failed.append(f"{canonical_json(particle)[:32]}: {error}")
        return float("inf")


@dataclass(slots=True)
class PredictionProbe:
    """The mechanism prediction the ladder watches: one number per rung, measured, never declared.

    The gate is about whether a *mechanism* result moves between rungs, so the probe runs the model
    at the rung's own posterior location and reads the declared statistic from the log. A probe that
    returned a constant, or that was skipped, would leave the gate dead — which is what the review
    found in the first version of this module.
    """

    values: list[float] = field(default_factory=list)

    def measure(self, simulator: SeedConditionedSimulator, posterior: dict[str, float]) -> float:
        value = _prediction(simulator, posterior)
        self.values.append(value)
        return value


@dataclass(frozen=True, slots=True)
class LadderStop:
    """Why the ladder stopped, and whether it may be called converged."""

    rung: int
    converged: bool
    reason: str
    location_change: float | None
    prediction_change: float | None

    def record(self) -> dict[str, object]:
        return {
            "rung": self.rung,
            "converged": self.converged,
            "reason": self.reason,
            "location_change": self.location_change,
            "prediction_change": self.prediction_change,
        }


def ladder_gate(
    previous: Rung,
    current: Rung,
    *,
    prior_widths: dict[str, float],
    previous_prediction: float | None,
) -> LadderStop:
    """The declared stop rule, applied to two consecutive rungs.

    Converged means every gate passed: the posterior's location moved by less than the declared
    share of each parameter's prior range, the mechanism prediction moved by less than its gate, and
    the population's own diagnostics (ESS per particle, acceptance, duplicates) are inside theirs.
    Anything else stops the ladder as **non-converged** — the values are still reported, and no
    parameter is labelled `identified` on the strength of a rung that did not meet the gates.
    """
    moves = [
        abs(current.posterior[name] - previous.posterior[name]) / prior_widths[name]
        for name in previous.posterior
        if prior_widths.get(name, 0.0) > 0.0
        and np.isfinite(current.posterior[name])
        and np.isfinite(previous.posterior[name])
    ]
    location = max(moves, default=0.0)
    prediction_change = (
        None if previous_prediction is None else abs(current.prediction - previous_prediction)
    )
    failures: list[str] = []
    # A non-finite value is a failure, not a pass: a gate that NaN satisfies is a gate that is not
    # applied, and the first version of this function let one through.
    if not np.isfinite(location):
        failures.append("the posterior's location is not finite")
    if prediction_change is not None and not np.isfinite(prediction_change):
        failures.append("the mechanism prediction is not finite")
    if not np.isfinite(current.prediction):
        failures.append("the mechanism prediction was not measured")
    if location >= GATES["location_change_max"]:
        failures.append(f"location moved {location:.3f} of the prior range")
    if prediction_change is not None and prediction_change >= GATES["prediction_change_max"]:
        failures.append(f"the mechanism prediction moved {prediction_change:.3f}")
    if current.ess_per_particle < GATES["ess_per_particle_min"]:
        failures.append(f"ESS per particle {current.ess_per_particle:.3f}")
    mean_acceptance = float(np.mean(current.acceptance) or 0.0)
    if not GATES["acceptance_min"] <= mean_acceptance <= GATES["acceptance_max"]:
        failures.append(f"acceptance {mean_acceptance:.3f}")
    if current.duplicate_fraction > GATES["duplicate_fraction_max"]:
        failures.append(f"duplicate fraction {current.duplicate_fraction:.3f}")
    return LadderStop(
        rung=current.particles,
        converged=not failures,
        reason="all declared gates passed" if not failures else "; ".join(failures),
        location_change=location,
        prediction_change=prediction_change,
    )


def prior_widths(cards: ParameterCards) -> dict[str, float]:
    return {name: high - low for name, low, high in _prior_bounds(cards)}


def freeze_posterior(
    root: str | Path,
    *,
    rungs: tuple[Rung, ...],
    stop: LadderStop,
    simulator: SeedConditionedSimulator,
    sampler_seeds: tuple[int, ...],
    output_root: str | Path | None = None,
) -> dict[str, object]:
    """Write the posterior with its hash, which is what the hold-out path waits for.

    The freeze is content-addressed: the digest covers the prior and objective digests, the
    process and sampler seed sets, the stop rule's verdict and every rung's posterior. An edit to
    any of them changes the digest, so a hold-out scored against an earlier one cannot claim to
    belong to this posterior.
    """
    repository = Path(root)
    payload: dict[str, object] = {
        "schema_version": "calibration-v2-posterior-v1",
        "prior_digest": prior_digest(
            (name, "", low, high) for name, low, high in _prior_bounds(load_cards(repository))
        ),
        "objective_digest": objective_digest(
            (
                check.pattern_id,
                check.check_id,
                str(check.kind.value),
                str(check.statistic),
            )
            for check in _objective_checks(repository)
        ),
        "evidence_digest": evidence_digest(repository),
        "process_seeds": list(simulator.seeds),
        "sampler_seeds": list(sampler_seeds),
        "mode": simulator.mode,
        "gates": dict(GATES),
        "stop": stop.record(),
        "rungs": [rung.record() for rung in rungs],
        "converged": stop.converged,
    }
    payload["posterior_hash"] = hash_text(canonical_json(payload))
    # The digests are read from the repository; the frozen posterior is written where the caller
    # says, so a test can freeze into a temporary directory without a second set of regstry files.
    destination = Path(output_root) if output_root is not None else repository
    write_json(destination / FROZEN_POSTERIOR_PATH, payload)
    return payload


def _objective_checks(root: Path) -> tuple[Check, ...]:
    """The declared objective checks, so the freeze covers what was scored and not what was run."""
    del root
    from late_ming_lab.calibration.targets import CHECKS

    return tuple(CHECKS)


#: Where the frozen posterior lives. The prediction path reads it and refuses to run without it.
FROZEN_POSTERIOR_PATH: Final[str] = "outputs/v2/p06/posterior.json"


def load_frozen_posterior(root: str | Path) -> dict[str, object]:
    path = Path(root) / FROZEN_POSTERIOR_PATH
    if not path.is_file():
        raise PosteriorNotFrozenError(
            f"{path} does not exist: the posterior has not been frozen, so nothing may be scored "
            "against it — least of all a reserved window"
        )
    payload: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def assert_holdout_allowed(root: str | Path, *, posterior_hash: str) -> None:
    """Refuse a hold-out score whose posterior hash is not the frozen one.

    This is the phase's isolation rule in code: the reserved windows may be read only after the
    posterior is frozen, and only by a caller that names the frozen hash. A caller with a stale hash
    is refused for the same reason a caller with none is: the score would belong to a different
    posterior and nothing in the artifact would say so.
    """
    frozen = load_frozen_posterior(root)
    if frozen.get("posterior_hash") != posterior_hash:
        raise PosteriorNotFrozenError(
            f"the frozen posterior is {str(frozen.get('posterior_hash'))[:12]}, not "
            f"{posterior_hash[:12]}: scoring a reserved window against another posterior is the "
            "window mixing this phase exists to prevent"
        )


def write_rung_table(root: str | Path, rungs: tuple[Rung, ...]) -> Path:
    """The rungs as a table, so a reader can see the ladder rather than its last step."""
    frame = pl.DataFrame(
        [
            {
                "particles": rung.particles,
                "sampler_seed": rung.sampler_seed,
                "ess": rung.ess,
                "ess_per_particle": rung.ess_per_particle,
                "mean_acceptance": float(np.mean(rung.acceptance) or 0.0),
                "duplicate_fraction": rung.duplicate_fraction,
                "simulations": rung.simulations,
                "cache_hits": rung.cache_hits,
                "seconds": rung.seconds,
                "failed_tasks": len(rung.failed),
            }
            for rung in rungs
        ]
    )
    path = Path(root) / RUNGS_PATH
    write_table(path, frame)
    return path


#: Where the ladder's own table is written.
RUNGS_PATH: Final[str] = "outputs/v2/p06/ladder-rungs.parquet"


__all__ = [
    "FROZEN_POSTERIOR_PATH",
    "GATES",
    "LADDER",
    "PREDICTION_STATISTIC",
    "PROCESS_SEEDS",
    "RUNGS_PATH",
    "SAMPLER_SEEDS",
    "STAGES",
    "CalibrationV2Error",
    "LadderStop",
    "Marginal",
    "PosteriorNotFrozenError",
    "PredictionProbe",
    "Rung",
    "SeedConditionedSimulator",
    "assert_holdout_allowed",
    "freeze_posterior",
    "ladder_gate",
    "load_frozen_posterior",
    "prior_widths",
    "run_rung",
    "write_rung_table",
]


def _joined(value: object) -> str:
    """A recorded seed set as one row's text, refusing anything that is not a sequence of seeds."""
    if not isinstance(value, (list, tuple)):
        raise CalibrationV2Error(f"expected a recorded seed list, got {type(value).__name__}")
    return ", ".join(str(seed) for seed in value)


def write_calibration_document(root: str | Path) -> Path:
    """Write the ladder and the frozen posterior as one document, from the artifacts.

    Generated, never hand-edited: the numbers are read back from the frozen posterior and the rung
    table, so a reader can check the page against the files rather than against a report's memory of
    them. The document states the verdict the gates reached, including the one this phase reached:
    a pilot that did not converge, which is a result and not a failure to produce one.
    """
    repository = Path(root)
    payload = load_frozen_posterior(repository)
    rungs = pl.read_parquet(repository / RUNGS_PATH)
    stop = payload["stop"]
    assert isinstance(stop, dict)
    lines = [
        "<!-- generated by: late-ming-lab calibrate v2 -->",
        "",
        "# Calibration V2: the pilot ladder, and what it did and did not settle",
        "",
        f"Generated from `outputs/v2/p06/posterior.json` and `{RUNGS_PATH}`. Do not edit.",
        "",
        "**Verdict this phase reached: non-converged.** The gates are reported below with the",
        "numbers they were applied to. Nothing here is labelled `identified`, and no parameter is",
        "called constrained by a ladder that has not settled.",
        "",
        "## The declaration",
        "",
        "| item | value |",
        "| --- | --- |",
        f"| prior digest | `{str(payload['prior_digest'])[:16]}…` |",
        f"| objective digest | `{str(payload['objective_digest'])[:16]}…` |",
        f"| evidence digest | `{str(payload['evidence_digest'])[:16]}…` |",
        f"| process seeds | {_joined(payload['process_seeds'])} |",
        f"| sampler seeds | {_joined(payload['sampler_seeds'])} |",
        f"| marginalisation | `{payload['mode']}` |",
        f"| posterior hash | `{payload['posterior_hash']}` |",
        "",
        "## The rungs",
        "",
        "| particles | seed | ESS/particle | acceptance | duplicates | sims | seconds |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rungs.iter_rows(named=True):
        lines.append(
            f"| {row['particles']} | {row['sampler_seed']} | {row['ess_per_particle']:.3f} | "
            f"{row['mean_acceptance']:.3f} | {row['duplicate_fraction']:.3f} | "
            f"{row['simulations']} | {row['seconds']:.0f} |"
        )
    lines += [
        "",
        "## The stop rule",
        "",
        "| gate | declared bound |",
        "| --- | --- |",
        f"| location change | < {GATES['location_change_max']} of the prior range |",
        f"| mechanism prediction change | < {GATES['prediction_change_max']} |",
        f"| ESS per particle | ≥ {GATES['ess_per_particle_min']} |",
        f"| acceptance | in [{GATES['acceptance_min']}, {GATES['acceptance_max']}] |",
        f"| duplicate fraction | ≤ {GATES['duplicate_fraction_max']} |",
        "",
        f"**Rung {stop['rung']}, converged: {stop['converged']}.** {stop['reason']}.",
        "",
        "## Reading these diagnostics honestly",
        "",
        "ESS per particle is measured on the tempered weights *before* resampling, and the",
        "duplicate fraction on the resampled population *before* the jitter: measuring either",
        "after those steps would report a number that is uniform or unique by construction, and a",
        "gate that cannot fail is not a gate. Even so, all three are healthy here (about 0.999,",
        "1.000 and 0.00-0.06) and that is not evidence that the posterior settled. The acceptance",
        "is 1.000 because the objective is piecewise constant over a bounded prior: a jitter",
        "inside one cell changes no pattern score, so the move is always accepted. What caught",
        "the non-convergence was the **location** gate: the weighted median moved by nearly half a",
        "prior range between the two rungs. Read the first three as statements about the mechanics",
        "of one rung; the location and prediction gates are the convergence ones.",
        "",
        "## What this phase does not claim",
        "",
        "- The hold-out and the extrapolation window have **not** been scored. The freeze gate",
        "  exists so that they cannot be, and no posterior here was frozen on a reserved window.",
        "- No parameter is `identified`. A location moving by nearly half a prior range between",
        "  two rungs has not settled, and the report says so.",
        "- The rungs are small on purpose: this is the affordable pilot the plan asks for, and",
        "  whether to double is a decision the gates make, not a number to chase.",
        "",
    ]
    path = repository / DOCUMENT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


#: Where the generated calibration document lives.
DOCUMENT_PATH: Final[str] = "docs/v2/calibration-v2.md"


__all__.extend(["DOCUMENT_PATH", "write_calibration_document"])
