"""The calibration pipeline end to end, at the smallest batch that still runs the real sampler.

The batch here is two particles. That is not a calibration anyone should read — the identifiability
report says so — but it exercises every link: SMC over the pinned Simulator, the ensemble on disk,
the posterior predictive runs into all four windows, and the four generated reports. The unit-level
contracts live in the invariant suite; this file is the proof that the chain as a whole runs.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from late_ming_lab.calibration.ensemble import Ensemble, Identification
from late_ming_lab.calibration.freeze import evidence_digest
from late_ming_lab.calibration.prediction import CHECKS as PREDICTION_CHECKS
from late_ming_lab.calibration.prediction import load_posterior_predictive
from late_ming_lab.calibration.priors import build_priors
from late_ming_lab.calibration.simulator import SandboxSimulator
from late_ming_lab.calibration.smc import SmcSettings, build_model
from late_ming_lab.evidence.cards import ParameterCards, load_cards
from late_ming_lab.evidence.ledger import PatternRegistry, load_patterns
from late_ming_lab.experiments.calibration import (
    BATCH_ROOT,
    load_calibration_inputs,
    run_calibration_batch,
    run_posterior_predictive,
    write_calibration_reports,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PARTICLES = 2
SEED = 4_242


@pytest.fixture(scope="module")
def cards() -> ParameterCards:
    return load_cards(REPO_ROOT)


@pytest.fixture(scope="module")
def patterns() -> PatternRegistry:
    return load_patterns(REPO_ROOT)


@pytest.fixture(scope="module")
def batch(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Run one real batch into a temporary tree and return (batch dir, output root)."""
    root = tmp_path_factory.mktemp("calibration")
    _, diagnostics, batch_dir = run_calibration_batch(
        REPO_ROOT,
        particles=PARTICLES,
        chains=1,
        sampler_seed=SEED,
        output_dir=root / "batch",
    )
    assert diagnostics.stages >= 1
    assert batch_dir.parent == root / "batch"
    return batch_dir, root


def test_the_batch_records_the_registry_it_was_run_against(batch: tuple[Path, Path]) -> None:
    batch_dir, _ = batch
    ensemble = Ensemble.load(batch_dir)
    provenance = ensemble.provenance

    assert provenance.evidence_digest == evidence_digest(REPO_ROOT)
    assert provenance.pattern_schema_version == load_patterns(REPO_ROOT).schema_version
    assert len(provenance.parameter_names) == len(build_priors(load_cards(REPO_ROOT)))
    assert len(provenance.target_ids) == 5
    assert len(provenance.hold_out_ids) == 8
    assert not set(provenance.target_ids) & set(provenance.hold_out_ids)
    assert provenance.particles == PARTICLES
    assert provenance.sampler_seed == SEED
    assert provenance.scenario["dataset"] == "toy"


def test_every_draw_lies_inside_the_declared_bounds_and_carries_its_scores(
    batch: tuple[Path, Path],
) -> None:
    batch_dir, _ = batch
    ensemble = Ensemble.load(batch_dir)
    priors = build_priors(load_cards(REPO_ROOT))

    assert len(ensemble.draws) == PARTICLES
    for draw in ensemble.draws:
        for prior in priors:
            assert prior.low <= draw.parameter_map()[prior.name] <= prior.high
        assert len(draw.scores) == len(ensemble.pattern_ids)

    verdicts = ensemble.verdicts(priors)
    assert len(verdicts) == len(priors)
    assert all(verdict.verdict in set(Identification) for verdict in verdicts)
    assert all(verdict.contraction >= 0.0 for verdict in verdicts)


def test_the_posterior_predictive_covers_every_window_and_reserved_pattern(
    batch: tuple[Path, Path],
) -> None:
    batch_dir, root = batch
    run_posterior_predictive(REPO_ROOT, batch_dir=batch_dir)
    predictive = load_posterior_predictive(batch_dir)

    windows = set(predictive.statistics["window"].unique())
    assert windows == {"calibration", "hold-out", "extrapolation", "whole-run"}
    assert predictive.statistics.height == PARTICLES * 4
    reserved = {check.pattern_id for check in PREDICTION_CHECKS}
    scored = set(predictive.checks.filter(kind="reserved")["pattern_id"].unique())
    assert scored == reserved
    assert set(predictive.checks.filter(kind="target")["window"].unique()) == {"calibration"}
    assert set(predictive.checks.filter(kind="reserved")["window"].unique()) == {
        "hold-out",
        "extrapolation",
        "whole-run",
    }
    assert report_paths(root, batch_dir)  # the reports are generated from this artifact


def report_paths(root: Path, batch_dir: Path, comparison: Path | None = None) -> tuple[Path, ...]:
    return write_calibration_reports(
        REPO_ROOT, batch=batch_dir, comparison=comparison, output_dir=root / "reports"
    )


def test_the_reports_agree_with_the_ensemble_they_describe(batch: tuple[Path, Path]) -> None:
    batch_dir, root = batch
    written = report_paths(root, batch_dir)
    names = {path.name for path in written}
    assert names == {"objective.md", "posterior.md", "mismatch.md", "prediction.md"}

    # The stability report is written when a second batch is named. A batch is compared against
    # itself here so the default suite does not pay for a second sampling run; the comparison's own
    # semantics — a seed-dependent shift being called unpinned — are covered in the invariant suite.
    with_stability = report_paths(root, batch_dir, comparison=batch_dir)
    assert {path.name for path in with_stability} == names | {"stability.md"}
    stability = (root / "reports" / "stability.md").read_text(encoding="utf-8")
    assert "Reproducible in" in stability

    ensemble = Ensemble.load(batch_dir)
    priors = build_priors(load_cards(REPO_ROOT))
    posterior = (root / "reports" / "posterior.md").read_text(encoding="utf-8")
    objective = (root / "reports" / "objective.md").read_text(encoding="utf-8")

    for prior in priors:
        assert f"`{prior.name}`" in objective
    for verdict in ensemble.verdicts(priors):
        assert f"| {verdict.contraction:.3f} | {verdict.verdict.value} |" in posterior
    for pattern_id in ensemble.pattern_ids:
        assert f"`{pattern_id}`" in posterior
    assert ensemble.provenance.evidence_digest in objective

    prediction = (root / "reports" / "prediction.md").read_text(encoding="utf-8")
    for pattern_id in ensemble.provenance.hold_out_ids:
        assert f"`{pattern_id}`" in prediction


def test_the_simulator_rv_maps_each_position_to_the_parameter_it_declares(
    cards: ParameterCards, patterns: PatternRegistry
) -> None:
    """A scrambled positional mapping would calibrate the wrong parameter and never look wrong."""
    simulator = SandboxSimulator(cards, patterns)
    seen: list[dict[str, float]] = []

    def record(parameters: dict[str, float]) -> tuple[float, ...]:
        seen.append(dict(parameters))
        return tuple(0.0 for _ in simulator.objective.pattern_ids)

    simulator.distance = record  # type: ignore[assignment]
    model = build_model(simulator, settings=SmcSettings(particles=2, random_seed=1))
    # The class-level function, not the bound attribute: PyTensor binds `op.fn` to the op instance.
    fn = type(model["patterns"].owner.op).fn
    offsets = [prior.low + 0.01 * (index + 1) for index, prior in enumerate(simulator.priors)]
    output = fn(np.random.default_rng(0), *[np.array([value]) for value in offsets], size=(1,))

    assert len(seen) == 1
    for prior, expected in zip(simulator.priors, offsets, strict=True):
        assert seen[0][prior.name] == pytest.approx(expected)
    assert output.shape == (1, len(simulator.objective.pattern_ids))


def test_the_batch_root_is_where_the_entry_point_looks() -> None:
    """The reports read the newest batch under the declared root; the two must not drift."""
    assert BATCH_ROOT == "outputs/calibration"
    inputs = load_calibration_inputs(REPO_ROOT)
    assert len(inputs.priors) > 0
    assert len(inputs.objective.pattern_ids) > 0
