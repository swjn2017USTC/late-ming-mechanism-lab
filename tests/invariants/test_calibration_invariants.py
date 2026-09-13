"""The calibration phase's invariants: the window discipline, the freeze, and the refusal paths.

These tests defend the properties the phase cannot afford to get wrong, and they defend them at the
cheapest level that still exercises the real code: the blindness test runs the sandbox once, the
determinism test twice, and everything else is pure arithmetic over the declared tables and the
registries.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import polars as pl
import pytest

from late_ming_lab.calibration.ensemble import (
    Draw,
    Ensemble,
    EnsembleError,
    Identification,
    Provenance,
    weighted_correlation,
    weighted_quantile,
)
from late_ming_lab.calibration.freeze import (
    evidence_digest,
    frozen_file_digests,
    objective_digest,
    prior_digest,
)
from late_ming_lab.calibration.prediction import (
    CHECKS as PREDICTION_CHECKS,
)
from late_ming_lab.calibration.prediction import (
    UNCHECKED,
    PredictionError,
    PredictiveChecks,
    predictive_pattern_ids,
)
from late_ming_lab.calibration.priors import PriorTable, build_priors
from late_ming_lab.calibration.simulator import SandboxSimulator, SimulatedRun, SimulatorError
from late_ming_lab.calibration.summary_stats import (
    SERIES_COLUMNS,
    YEARLY_LAST_COLUMNS,
    YEARLY_MEAN_COLUMNS,
    YEARLY_SUM_COLUMNS,
)
from late_ming_lab.calibration.targets import (
    CHECKS,
    CalibrationObjectiveError,
    Objective,
    objective_payload,
)
from late_ming_lab.calibration.windows import (
    WHOLE_RUN_WINDOW,
    WINDOWS,
    WindowRole,
    calibration_window,
    hold_out_window,
    whole_run_window,
    window_covering_tick,
)
from late_ming_lab.evidence.cards import ParameterCards, load_cards
from late_ming_lab.evidence.ledger import CalibrationRole, PatternRegistry, load_patterns

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def cards() -> ParameterCards:
    return load_cards(REPO_ROOT)


@pytest.fixture(scope="module")
def patterns() -> PatternRegistry:
    return load_patterns(REPO_ROOT)


@pytest.fixture(scope="module")
def objective(patterns: PatternRegistry) -> Objective:
    return Objective.from_registry(patterns)


def test_the_split_windows_tile_the_run_without_a_gap_or_an_overlap() -> None:
    """The three-way split is the phase's contract; a gap would hide ticks from every report."""
    assert WINDOWS[0].first_tick == 0
    assert WINDOWS[-1].last_tick == WHOLE_RUN_WINDOW.last_tick
    for earlier, later in pairwise(WINDOWS):
        assert later.first_tick == earlier.last_tick + 1, f"{earlier.label} -> {later.label}"
    for window in WINDOWS:
        for tick in range(window.first_tick, window.last_tick + 1):
            assert window_covering_tick(tick) is window
    assert [window.role for window in WINDOWS] == [
        WindowRole.CALIBRATION,
        WindowRole.HOLD_OUT,
        WindowRole.EXTRAPOLATION,
    ]
    assert sum(window.tick_count for window in WINDOWS) == WHOLE_RUN_WINDOW.tick_count == 240
    assert whole_run_window() is WHOLE_RUN_WINDOW


def test_the_whole_run_window_is_not_the_calibration_window() -> None:
    """The prediction view and the fitting view must not be the same object or the same range."""
    assert WHOLE_RUN_WINDOW.role is not WindowRole.CALIBRATION
    assert WHOLE_RUN_WINDOW.tick_count > calibration_window().tick_count
    assert WHOLE_RUN_WINDOW.contains(calibration_window().first_tick)
    assert WHOLE_RUN_WINDOW.contains(calibration_window().last_tick)


def test_the_objective_refuses_every_window_but_the_calibration_window(
    objective: Objective, patterns: PatternRegistry
) -> None:
    for window in (hold_out_window(), whole_run_window()):
        with pytest.raises(CalibrationObjectiveError, match="calibration window"):
            objective.score(_empty_events(), window=window)


def test_the_prediction_checks_refuse_the_calibration_window(patterns: PatternRegistry) -> None:
    checks = PredictiveChecks.from_registry(patterns)
    with pytest.raises(PredictionError, match="never calibration"):
        checks.score(_empty_events(), window=calibration_window())


def test_the_two_check_tables_are_disjoint_and_cover_their_roles(
    patterns: PatternRegistry,
) -> None:
    """A held-out pattern in an objective would end the phase's central claim."""
    target_ids = {check.pattern_id for check in CHECKS}
    reserved_ids = {check.pattern_id for check in PREDICTION_CHECKS} | {p for p, _ in UNCHECKED}
    assert not target_ids & reserved_ids
    assert target_ids == set(pattern.id for pattern in patterns.by_role(CalibrationRole.TARGET))
    assert reserved_ids == set(predictive_pattern_ids(patterns))
    assert set(UNCHECKED) <= reserved_ids
    for check in CHECKS:
        pattern = patterns.require(check.pattern_id)
        assert pattern.calibration_role is CalibrationRole.TARGET


def test_every_check_cites_a_signature_the_pattern_has(patterns: PatternRegistry) -> None:
    PredictiveChecks.from_registry(patterns)
    for check in (*CHECKS, *PREDICTION_CHECKS):
        pattern = patterns.require(check.pattern_id)
        assert 0 <= check.signature_index < len(pattern.signatures)
        assert check.question.strip()


def test_the_yearly_reduction_partitions_the_series_columns() -> None:
    """A series column in no group would silently vanish from every yearly check."""
    grouped = (*YEARLY_MEAN_COLUMNS, *YEARLY_SUM_COLUMNS, *YEARLY_LAST_COLUMNS)
    assert set(grouped) == set(SERIES_COLUMNS) - {"tick"}
    assert len(grouped) == len(set(grouped))


def test_the_freeze_changes_when_a_registry_file_changes(tmp_path: Path) -> None:
    """A freeze that cannot notice an edit is not a freeze."""
    source = REPO_ROOT / "data" / "historical_patterns"
    original = evidence_digest(REPO_ROOT)
    assert original == evidence_digest(REPO_ROOT)
    assert len(frozen_file_digests(REPO_ROOT)) >= len(list(source.glob("*.yaml")))

    copied = tmp_path / "repo"
    (copied / "data").mkdir(parents=True)
    (copied / "data" / "historical_patterns").mkdir()
    (copied / "data" / "parameters").mkdir()
    (copied / "data" / "normalized").mkdir()
    (copied / "sources" / "registry").mkdir(parents=True)
    for pattern in (
        "sources/registry/*.yaml",
        "data/parameters/*.yaml",
        "data/normalized/evidence_ledger*.yaml",
        "data/normalized/rule_claims.yaml",
        "data/historical_patterns/*.yaml",
    ):
        for path in REPO_ROOT.glob(pattern):
            target = copied / path.relative_to(REPO_ROOT)
            target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    assert evidence_digest(copied) == original
    first = sorted((copied / "data" / "historical_patterns").glob("*.yaml"))[0]
    first.write_text(first.read_text(encoding="utf-8") + "\n# an edit\n", encoding="utf-8")
    assert evidence_digest(copied) != original


def test_the_declared_digests_separate_bounds_from_checks() -> None:
    """The prior and objective digests must move independently, or they are not two records."""
    bounds = (("a", "A", 0.0, 1.0), ("b", "B", 2.0, 3.0))
    checks = (("p", "c", "rises", "x"),)
    assert prior_digest(bounds) != prior_digest((("a", "A", 0.0, 2.0), ("b", "B", 2.0, 3.0)))
    assert objective_digest(checks) != objective_digest((("p", "c", "falls", "x"),))
    assert objective_digest(objective_payload()) == objective_digest(objective_payload())


def test_the_simulator_refuses_a_draw_outside_its_card_range(
    cards: ParameterCards, patterns: PatternRegistry
) -> None:
    simulator = SandboxSimulator(cards, patterns)
    centre = simulator.priors.centre()
    outside = {**centre, "yield_loss_scale": simulator.priors.by_name("yield_loss_scale").high * 2}
    with pytest.raises(SimulatorError, match="outside its card range"):
        simulator.distance(outside)
    short = {name: value for name, value in centre.items() if name != "yield_loss_scale"}
    with pytest.raises(SimulatorError, match="does not match the priors"):
        simulator.distance(short)


@pytest.fixture(scope="module")
def sandbox(
    cards: ParameterCards, patterns: PatternRegistry
) -> tuple[SandboxSimulator, dict[str, float], SimulatedRun]:
    """One sandbox run at the midpoint of every declared range, reused by the expensive tests."""
    simulator = SandboxSimulator(cards, patterns)
    midpoint = {prior.name: (prior.low + prior.high) / 2.0 for prior in simulator.priors}
    return simulator, midpoint, simulator.run(midpoint)


def test_the_objective_cannot_see_anything_after_the_calibration_window(
    sandbox: tuple[SandboxSimulator, dict[str, float], SimulatedRun], objective: Objective
) -> None:
    """The hold-out cannot be in the objective if deleting it changes nothing."""
    _, _, run = sandbox
    window = calibration_window()
    everything = objective.score(run.events, window=window, county_nodes=run.county_nodes)
    truncated = run.events.filter(pl.col("tick") <= window.last_tick)
    only_the_window = objective.score(truncated, window=window, county_nodes=run.county_nodes)
    assert everything.vector() == only_the_window.vector()
    assert everything.patterns == only_the_window.patterns
    assert run.events.height > truncated.height


def test_the_simulator_is_deterministic_under_common_random_numbers(
    sandbox: tuple[SandboxSimulator, dict[str, float], SimulatedRun],
) -> None:
    """Same parameters, same seed, same run — the sampler's distance difference is the parameter."""
    simulator, midpoint, first = sandbox
    second = simulator.run(midpoint)
    assert second.simulation_digest == first.simulation_digest
    assert second.parameter_hash == first.parameter_hash
    assert second.scores.vector() == first.scores.vector()
    other = dict(midpoint)
    other["yield_loss_scale"] = midpoint["yield_loss_scale"] * 1.5
    third = simulator.run(other)
    assert third.parameter_hash != first.parameter_hash
    assert third.simulation_digest != first.simulation_digest


def test_the_ensemble_round_trips_through_disk(tmp_path: Path) -> None:
    patterns = ("first-target", "second-target")
    provenance = _provenance(("a", "b"), patterns)
    draws = (
        Draw((("a", 0.25), ("b", 0.75)), (0.0, 0.5), 0.5),
        Draw((("a", 0.30), ("b", 0.70)), (0.5, 0.0), 0.5),
    )
    ensemble = Ensemble(provenance=provenance, draws=draws, pattern_ids=patterns)
    ensemble.write(tmp_path)
    loaded = Ensemble.load(tmp_path)
    assert loaded.provenance == provenance
    assert loaded.draws == draws
    assert loaded.parameter_values("a") == (0.25, 0.30)
    assert loaded.scores() == ((0.0, 0.5), (0.5, 0.0))


def test_the_identifiability_rule_reads_the_contraction_it_declares(
    cards: ParameterCards,
) -> None:
    """A posterior as wide as the prior is unresolved; one that is tight is identified."""
    full = build_priors(cards)
    prior = full.by_name("yield_loss_scale")
    priors = PriorTable((prior,))
    tight = _ensemble_from_ranges(("yield_loss_scale",), ((prior.low + 0.01,), (prior.low + 0.02,)))
    flat = _ensemble_from_ranges(
        ("yield_loss_scale",), ((prior.low + 0.001,), (prior.high - 0.001,))
    )
    assert tight.verdicts(priors)[0].verdict is Identification.IDENTIFIED
    assert flat.verdicts(priors)[0].verdict is Identification.UNRESOLVED


def test_two_batches_are_compared_on_location_as_a_share_of_the_prior_range(
    cards: ParameterCards,
) -> None:
    """A collapse that moves with the seed must be reported, however narrow its marginals look."""
    full = build_priors(cards)
    prior = full.by_name("yield_loss_scale")
    priors = PriorTable((prior,))
    agreeing = _ensemble_from_ranges(
        ("yield_loss_scale",), ((prior.low + 0.05,), (prior.low + 0.06,))
    )
    elsewhere = _ensemble_from_ranges(
        ("yield_loss_scale",), ((prior.low + 0.80,), (prior.low + 0.81,))
    )

    comparison = agreeing.compare_with(elsewhere, priors)
    assert len(comparison) == 1
    assert comparison[0].shift == pytest.approx(0.5)
    assert comparison[0].shift > 0.25
    assert comparison[0].reproducible is False
    assert agreeing.compare_with(agreeing, priors)[0].reproducible is True
    assert agreeing.distinct_parameter_vectors() == 2

    with pytest.raises(EnsembleError, match="same parameters"):
        agreeing.compare_with(
            _ensemble_from_ranges(("subsistence_grain_per_adult_month_shi",), ((0.3,), (0.3,))),
            priors,
        )


def test_the_weighted_statistics_are_the_plain_ones_when_weights_are_equal() -> None:
    values = (1.0, 2.0, 3.0, 4.0)
    weights = (1.0, 1.0, 1.0, 1.0)
    assert weighted_quantile(values, weights, 0.5) in {2.0, 3.0}
    assert weighted_quantile(values, weights, 0.25) == 1.0
    assert weighted_correlation(values, values, weights) == pytest.approx(1.0)
    assert weighted_correlation(values, tuple(reversed(values)), weights) == pytest.approx(-1.0)
    assert weighted_correlation((1.0, 1.0), (1.0, 2.0), (1.0, 1.0)) == 0.0


def _empty_events() -> pl.DataFrame:
    """No events at all: the guards fire before any statistic is computed."""
    return pl.DataFrame()


def _provenance(names: tuple[str, ...], target_ids: tuple[str, ...]) -> Provenance:
    return Provenance(
        batch_id="test-batch",
        generated_at_utc="2026-09-13T00:00:00+00:00",
        git_sha=None,
        git_dirty=None,
        engine_version="test",
        pymc_version="test",
        arviz_version="test",
        evidence_digest="0" * 64,
        evidence_files=(),
        pattern_schema_version="pattern-cards-v1",
        prior_digest="1" * 64,
        objective_digest="2" * 64,
        simulation_config_hash="3" * 64,
        root_seed=1,
        scenario={"dataset": "toy"},
        windows={"calibration": (0, 119)},
        target_ids=target_ids,
        hold_out_ids=("reserved",),
        particles=2,
        chains=1,
        tolerance=0.25,
        sampler_seed=1,
        parameter_names=names,
    )


def _ensemble_from_ranges(
    names: tuple[str, ...], values: tuple[tuple[float, ...], ...]
) -> Ensemble:
    draws = tuple(
        Draw(
            parameters=tuple(zip(names, draw_values, strict=True)),
            scores=(0.0,),
            weight=1.0 / len(values),
        )
        for draw_values in values
    )
    return Ensemble(
        provenance=_provenance(names, ("reserved",)), draws=draws, pattern_ids=("reserved",)
    )
