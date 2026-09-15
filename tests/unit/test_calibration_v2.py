"""Calibration V2: the ladder's gates, the freeze, and the isolation the hold-out waits behind.

Three properties the phase's acceptance turns on, each checked without running a full calibration:

```text
the gates decide, not the rung number   a converged stop needs the location, the mechanism
                                        prediction, ESS, acceptance and the duplicate fraction all
                                        inside their declared bounds; one failure is a
                                        non-converged report, never an `identified` label
the freeze is content-addressed         editing any rung, seed or digest changes the posterior hash
the hold-out waits                      a reserved window cannot be scored without the frozen hash,
                                        and a stale hash is refused the same way an absent one is
```

The sampler and the simulator are exercised on a tiny declared rung — four particles, two process
seeds, one stage — because what these tests defend is the machinery's refusals, not a posterior.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest

from late_ming_lab.calibration.simulator import SimulatorSettings
from late_ming_lab.calibration.v2 import (
    FROZEN_POSTERIOR_PATH,
    GATES,
    PROCESS_SEEDS,
    SAMPLER_SEEDS,
    CalibrationV2Error,
    LadderStop,
    PosteriorNotFrozenError,
    Rung,
    SeedConditionedSimulator,
    assert_holdout_allowed,
    freeze_posterior,
    ladder_gate,
    prior_widths,
    run_rung,
)
from late_ming_lab.evidence.cards import ParameterCards, load_cards
from late_ming_lab.evidence.ledger import PatternRegistry, load_patterns

TICKS = 48
WARMUP = 12


@pytest.fixture(scope="module")
def cards() -> ParameterCards:
    return load_cards(".")


@pytest.fixture(scope="module")
def registry() -> PatternRegistry:
    return load_patterns(".")


@pytest.fixture(scope="module")
def simulator(cards: ParameterCards, registry: PatternRegistry) -> SeedConditionedSimulator:
    return SeedConditionedSimulator(
        cards,
        registry,
        mode="process-seeds",
        seeds=PROCESS_SEEDS[:2],
        settings=SimulatorSettings(tick_count=TICKS, warmup_ticks=WARMUP),
    )


def test_one_seed_is_refused_as_process_uncertainty(
    cards: ParameterCards, registry: PatternRegistry
) -> None:
    """One seed is common random numbers; calling it process uncertainty is the V1 mistake."""
    with pytest.raises(CalibrationV2Error, match="at least two seeds"):
        SeedConditionedSimulator(cards, registry, mode="process-seeds", seeds=(PROCESS_SEEDS[0],))


def test_the_marginal_reports_every_seed_and_its_aggregate(
    simulator: SeedConditionedSimulator, cards: ParameterCards
) -> None:
    assert simulator.parameter_names() == tuple(name for name, _l, _h in _bounds(cards))
    draw = {name: float(low) for name, low, _high in _bounds(cards)}
    marginal = simulator.marginal(draw)
    assert marginal.seeds == PROCESS_SEEDS[:2]
    assert len(marginal.per_seed) == 2
    assert marginal.mean == pytest.approx(float(np.mean(marginal.per_seed)))
    assert marginal.worst >= marginal.mean - 1e-12


def test_a_repeated_draw_is_served_from_cache(
    simulator: SeedConditionedSimulator, cards: ParameterCards
) -> None:
    """The cache is exact because the simulator is deterministic per seed; a hit is not a run."""
    draw = {name: float(low) + 1e-9 for name, low, _high in _bounds(cards)}
    simulator.marginal(draw)
    after_first = simulator.simulation_count
    hits_before = simulator.cache_hits
    simulator.marginal(draw)
    assert simulator.simulation_count == after_first, "a repeated draw was run again"
    assert simulator.cache_hits == hits_before + len(simulator.seeds)


def test_a_rung_records_every_diagnostic_the_manifest_needs(
    cards: ParameterCards, simulator: SeedConditionedSimulator
) -> None:
    rung = run_rung(simulator, cards, particles=4, sampler_seed=SAMPLER_SEEDS[0], stages=(1.0,))
    record = rung.record()
    for field in (
        "particles",
        "sampler_seed",
        "ess",
        "ess_per_particle",
        "acceptance",
        "duplicate_fraction",
        "simulations",
        "cache_hits",
        "seconds",
        "failed_tasks",
        "posterior",
    ):
        assert field in record, field
    assert record["particles"] == 4
    assert 0.0 <= rung.duplicate_fraction <= 1.0


def test_a_converged_stop_needs_every_gate() -> None:
    """One gate outside its bound is a non-converged report, however small the others are."""

    def rung(particles: int, location: float, prediction: float, **overrides: float) -> Rung:
        posterior = {"p": location}
        return Rung(
            particles=particles,
            sampler_seed=1,
            posterior=posterior,
            weights=(1.0 / particles,) * particles,
            ess=float(particles),
            ess_per_particle=overrides.get("ess_per_particle", 0.5),
            acceptance=(overrides.get("acceptance", 0.5),),
            duplicate_fraction=overrides.get("duplicate_fraction", 0.0),
            simulations=particles,
            cache_hits=0,
            seconds=1.0,
            prediction=prediction,
        )

    widths = {"p": 1.0}
    stopped = ladder_gate(
        rung(4, 0.0, 0.0), rung(8, 0.05, 0.01), prior_widths=widths, previous_prediction=0.0
    )
    assert stopped.converged, stopped.reason
    for overrides in (
        {"ess_per_particle": GATES["ess_per_particle_min"] - 0.01},
        {"acceptance": GATES["acceptance_min"] - 0.01},
        {"acceptance": GATES["acceptance_max"] + 0.01},
        {"duplicate_fraction": GATES["duplicate_fraction_max"] + 0.01},
    ):
        failed = ladder_gate(
            rung(4, 0.0, 0.0),
            rung(8, 0.05, 0.01, **overrides),
            prior_widths=widths,
            previous_prediction=0.0,
        )
        assert not failed.converged, overrides
    too_far = ladder_gate(
        rung(4, 0.0, 0.0), rung(8, 0.2, 0.01), prior_widths=widths, previous_prediction=0.0
    )
    assert not too_far.converged
    moving = ladder_gate(
        rung(4, 0.0, 0.0), rung(8, 0.05, 0.2), prior_widths=widths, previous_prediction=0.0
    )
    assert not moving.converged


def test_the_freeze_is_content_addressed(tmp_path: Path, cards: ParameterCards) -> None:
    """Editing a rung changes the hash: a scorer cannot claim to belong to an earlier posterior."""
    rung = Rung(
        particles=4,
        sampler_seed=1,
        posterior={"p": 0.5},
        weights=(0.25,) * 4,
        ess=4.0,
        ess_per_particle=1.0,
        acceptance=(0.5,),
        duplicate_fraction=0.0,
        simulations=4,
        cache_hits=0,
        seconds=1.0,
        prediction=float("nan"),
    )
    stop = LadderStop(
        rung=4,
        converged=True,
        reason="declared",
        location_change=0.0,
        prediction_change=None,
    )
    simulator = SeedConditionedSimulator(
        cards, load_patterns("."), mode="process-seeds", seeds=PROCESS_SEEDS[:2]
    )
    first = freeze_posterior(
        ".",
        rungs=(rung,),
        stop=stop,
        simulator=simulator,
        sampler_seeds=SAMPLER_SEEDS,
        output_root=tmp_path,
    )
    edited = dataclasses.replace(rung, particles=5)
    second = freeze_posterior(
        ".",
        rungs=(edited,),
        stop=stop,
        simulator=simulator,
        sampler_seeds=SAMPLER_SEEDS,
        output_root=tmp_path,
    )
    assert first["posterior_hash"] != second["posterior_hash"]
    assert first["prior_digest"] == second["prior_digest"]
    assert first["mode"] == "process-seeds"
    assert first["process_seeds"] == list(PROCESS_SEEDS[:2])
    assert first["sampler_seeds"] == list(SAMPLER_SEEDS)
    assert first["gates"] == GATES


def test_the_hold_out_is_refused_before_the_posterior_is_frozen(tmp_path: Path) -> None:
    """No freeze, no reserved window: the isolation rule V2-P03 froze, enforced at the call site."""
    with pytest.raises(PosteriorNotFrozenError, match="has not been frozen"):
        assert_holdout_allowed(tmp_path, posterior_hash="0" * 64)
    path = tmp_path / FROZEN_POSTERIOR_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"posterior_hash": "a" * 64}), encoding="utf-8")
    assert_holdout_allowed(tmp_path, posterior_hash="a" * 64)
    with pytest.raises(PosteriorNotFrozenError, match="another posterior"):
        assert_holdout_allowed(tmp_path, posterior_hash="b" * 64)


def test_the_prior_widths_come_from_the_cards(cards: ParameterCards) -> None:
    widths = prior_widths(cards)
    for name, low, high in _bounds(cards):
        assert widths[name] == pytest.approx(high - low)


def _bounds(cards: ParameterCards) -> tuple[tuple[str, float, float], ...]:
    from late_ming_lab.calibration.priors import build_priors

    return tuple((prior.name, float(prior.low), float(prior.high)) for prior in build_priors(cards))
