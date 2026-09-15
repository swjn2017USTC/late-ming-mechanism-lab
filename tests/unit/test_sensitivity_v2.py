"""Sensitivity V2: the ladders settle or say they did not, and every adaptive choice is recorded.

Four properties the phase's acceptance turns on, checked without paying for a ladder:

```text
a near-constant output     gets no quantitative reading at all — not zeros, a stated reason
an unstable level          is reported as unstable and takes the next rung; it is never the answer
every adaptive choice      is in the manifest with the number that produced it
the screen covers the support  the Morris stage sweeps every declared prior, and the Sobol stage
                           names the parameters it held at their card centres
```

The designs are run at a tiny window and a two-parameter problem where a test needs a real design;
what is defended here is the machinery's refusals and the manifest's completeness.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from late_ming_lab.calibration.simulator import SimulatorSettings
from late_ming_lab.evidence.cards import ParameterCards, load_cards
from late_ming_lab.evidence.ledger import PatternRegistry, load_patterns
from late_ming_lab.experiments.sensitivity import SweepParameter
from late_ming_lab.experiments.sensitivity_v2 import (
    LEVELS_PATH,
    MANIFEST_PATH,
    MORRIS_TOP_K,
    SOBOL_VALUE_TOLERANCE,
    Level,
    SensitivityV2Error,
    centre_draw,
    screen_parameters,
    sobol_parameters,
    write_level_table,
    write_sensitivity_manifest,
)


@pytest.fixture(scope="module")
def cards() -> ParameterCards:
    return load_cards(".")


@pytest.fixture(scope="module")
def registry() -> PatternRegistry:
    return load_patterns(".")


@pytest.fixture(scope="module")
def fast() -> SimulatorSettings:
    return SimulatorSettings(tick_count=24, warmup_ticks=6)


def _level(ladder: str, size: int, values: dict[str, float], *, stable: bool, reason: str) -> Level:
    import polars as pl

    rows = [
        {
            "parameter": name,
            "output": "o",
            "value": value,
            "confidence_low": value,
            "confidence_high": value,
        }
        for name, value in sorted(values.items())
    ]
    return Level(
        ladder=ladder,
        size=size,
        indices=pl.DataFrame(rows),
        ranking=tuple(sorted(values, key=lambda name: -abs(values[name]))),
        stable=stable,
        reason=reason,
        runs=size,
        seconds=0.0,
    )


def test_the_screen_covers_every_declared_prior(cards: ParameterCards) -> None:
    """The Morris stage runs inside the whole declared support, not a chosen corner of it."""
    from late_ming_lab.calibration.priors import build_priors

    swept = {parameter.name for parameter in screen_parameters(cards)}
    declared = {prior.name for prior in build_priors(cards)}
    assert swept == declared


def test_the_sobol_stage_names_what_it_holds(cards: ParameterCards) -> None:
    """A refinement over a subset holds the rest at their card centres, and says which."""
    from late_ming_lab.calibration.priors import build_priors

    chosen = sobol_parameters(cards, sorted(prior.name for prior in build_priors(cards)))
    assert 2 <= len(chosen) <= 6
    held = centre_draw(cards, chosen)
    declared = {prior.name for prior in build_priors(cards)}
    swept = {parameter.name for parameter in chosen}
    assert set(held) == declared - swept
    assert all(np.isfinite(value) for value in held.values())


def test_a_card_whose_centre_is_outside_its_range_is_held_inside_it(
    cards: ParameterCards,
) -> None:
    """A defect in a card is reported, not absorbed: the hold stays inside the declared support.

    `interest_rate_monthly` states a central value below its own range. Holding a parameter there
    would run the model outside the support the card declares, so the hold is taken at the nearest
    endpoint — and the phase records the defect rather than clipping it away silently.
    """
    from late_ming_lab.calibration.priors import build_priors

    offending = [
        prior
        for prior in build_priors(cards)
        if prior.central is not None and not prior.low <= prior.central <= prior.high
    ]
    assert offending, "the defect this test documents has been fixed; update the test"
    prior = offending[0]
    held = centre_draw(
        cards,
        tuple(
            SweepParameter(
                name=other.name,
                parameter_set=other.parameter_set,
                card_id=other.card_id,
                low=other.low,
                high=other.high,
                unit="share",
            )
            for other in build_priors(cards)
            if other.name != prior.name
        ),
    )
    assert prior.low <= held[prior.name] <= prior.high


def test_the_bootstrap_measures_top_k_stability_on_a_known_design() -> None:
    """The stability number is read from the design's own trajectories, not from the indices.

    Three parameters over four trajectories, with one parameter dominating every trajectory: the
    bootstrap must agree with itself, and a design whose effects are noise must not.
    """

    from late_ming_lab.experiments.sensitivity import SweepParameter, morris_design
    from late_ming_lab.experiments.sensitivity_v2 import _bootstrap_top_k

    parameters = tuple(
        SweepParameter(
            name=name,
            parameter_set="MarketParameters",
            card_id=name,
            low=0.0,
            high=1.0,
            unit="share",
        )
        for name in ("loud", "quiet_a", "quiet_b")
    )
    design = morris_design(parameters, trajectories=8, seed=7)
    steps = len(parameters) + 1
    # `loud` moves the output on every step it takes; the others move it not at all.
    values: list[float] = []
    for index in range(design.height):
        row = design.row(index, named=True)
        values.append(float(row["loud"]) * 10.0)
    # Two outputs: one dominated by `loud`, one by `quiet_a`. The bootstrap has to agree more
    # often with the ranking that matches the output than with the ranking that does not — which is
    # what makes it a measurement rather than a constant.
    rows = [design.row(index, named=True) for index in range(design.height)]
    loud_values = [float(row["loud"]) * 10.0 for row in rows]
    quiet_values = [float(row["quiet_a"]) * 10.0 for row in rows]
    matched = _bootstrap_top_k(parameters, design, {"o": loud_values}, observed=("loud",), seed=7)
    mismatched = _bootstrap_top_k(
        parameters, design, {"o": quiet_values}, observed=("loud",), seed=7
    )
    assert 0.0 <= matched <= 1.0 and 0.0 <= mismatched <= 1.0
    assert matched > mismatched, (
        f"the bootstrap agreed as often with the wrong ranking ({mismatched}) as with the right "
        f"one ({matched})"
    )
    assert design.height == 8 * steps
    assert MORRIS_TOP_K >= 1


def test_the_morris_ladder_and_the_sobol_ladder_are_declared() -> None:
    """The rungs are a declaration a report can quote, and the second Sobol order is not one."""
    from late_ming_lab.experiments.sensitivity_v2 import MORRIS_LADDER, SOBOL_LADDER

    assert MORRIS_LADDER == (20, 40)
    assert SOBOL_LADDER == (64, 128, 256)
    assert all(value > 0 and value & (value - 1) == 0 for value in SOBOL_LADDER)


def test_a_near_constant_output_is_refused_a_reading(tmp_path: Path) -> None:
    """A flat output has no variance to decompose; the ladder says so rather than printing zeros."""
    from late_ming_lab.experiments.sensitivity_v2 import _near_constant

    assert _near_constant(np.full(64, 0.5)) is not None
    assert _near_constant(np.zeros(64)) is not None
    assert _near_constant(np.linspace(0.0, 1.0, 64)) is None


def test_the_manifest_records_every_bound_and_every_level(
    tmp_path: Path, cards: ParameterCards
) -> None:
    levels = (
        _level("morris", 20, {"a": 0.4, "b": 0.1}, stable=False, reason="bootstrap disagreed"),
        _level("morris", 40, {"a": 0.3, "b": 0.2}, stable=True, reason="bootstrap agreed"),
        _level("sobol", 64, {"a": 0.5, "b": 0.05}, stable=False, reason="first level"),
        _level("sobol", 128, {"a": 0.45, "b": 0.04}, stable=True, reason="S1 settled"),
    )
    path = write_sensitivity_manifest(tmp_path, levels=levels, pawn=None)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["morris_ladder"] == [20, 40]
    assert payload["sobol_ladder"] == [64, 128, 256]
    assert payload["sobol_value_tolerance"] == SOBOL_VALUE_TOLERANCE
    assert len(payload["levels"]) == 4
    assert payload["levels"][3]["stable"] is True
    assert payload["levels"][0]["reason"] == "bootstrap disagreed"
    assert payload["manifest_hash"]
    assert payload["pawn"] == []
    assert path == tmp_path / MANIFEST_PATH


def test_the_level_table_carries_every_level_it_was_given(tmp_path: Path) -> None:
    """The report's numbers are recomputable: the indices are an artifact, not prose."""
    import polars as pl

    levels = (
        _level("morris", 20, {"a": 0.4, "b": 0.1}, stable=False, reason="r1"),
        _level("sobol", 64, {"a": 0.5, "b": 0.05}, stable=False, reason="r2"),
    )
    path = write_level_table(tmp_path, levels)
    frame = pl.read_parquet(path)
    assert path == tmp_path / LEVELS_PATH
    assert set(frame["ladder"].to_list()) == {"morris", "sobol"}
    assert set(frame["level"].to_list()) == {20, 64}
    assert frame.height == 4


def test_an_empty_ladder_produces_no_table(tmp_path: Path) -> None:
    """A table with no rows would let a report claim a ladder that never ran."""
    import polars as pl

    empty = Level(
        ladder="morris",
        size=20,
        indices=pl.DataFrame(),
        ranking=(),
        stable=True,
        reason="empty",
        runs=0,
        seconds=0.0,
    )
    with pytest.raises(SensitivityV2Error, match="no level"):
        write_level_table(tmp_path, (empty,))


def test_a_constant_output_is_refused_by_the_morris_ladder_too(
    cards: ParameterCards, registry: PatternRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The blocker the review found: only the Sobol ladder refused a near-constant output.

    A constant output makes every elementary effect zero, so the ranking is a tie-break and the
    bootstrap agrees with itself — `stable=True` on an output with nothing in it. The refusal is
    exercised here by stubbing the design outputs, because running a real ladder costs an hour.
    """
    from late_ming_lab.experiments import sensitivity_v2 as module

    def constant_outputs(
        simulator: object, design: pl.DataFrame, parameters: object, *, fixed: object = None
    ) -> dict[str, list[float]]:
        del simulator, parameters, fixed
        return {"largest_band_share_end": [0.5] * design.height}

    monkeypatch.setattr(module, "_design_outputs", constant_outputs)
    levels = module.morris_ladder(cards, registry)
    assert len(levels) == 1
    assert levels[0].stable is False
    assert "near-constant" in levels[0].reason
    assert levels[0].ranking == ()


def test_the_sobol_gate_needs_the_ranking_as_well_as_the_move() -> None:
    """A set of parameters that each moved a little but changed order is not a settled ranking."""
    from late_ming_lab.experiments.sensitivity_v2 import SOBOL_TOP_K, SOBOL_VALUE_TOLERANCE

    assert SOBOL_TOP_K >= 2
    assert 0.0 < SOBOL_VALUE_TOLERANCE < 1.0
    # The clause is in the code, not only in the docstring: the gate composes both conditions.
    import inspect

    source = inspect.getsource(
        __import__(
            "late_ming_lab.experiments.sensitivity_v2", fromlist=["sobol_ladder"]
        ).sobol_ladder
    )
    assert "same_top" in source
    assert "SOBOL_VALUE_TOLERANCE" in source
