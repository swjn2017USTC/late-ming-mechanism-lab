"""The sensitivity wiring's observable contract, checked against a model whose answer is known.

The sandbox cannot certify a global sensitivity method: its own outcomes are the thing under study,
so a test that ran it would only show that the wiring returns numbers. The Ishigami function is the
canonical SALib example instead, and its decomposition is published, so each assertion below is one
of its known properties rather than a property of the code that produced it:

```text
Morris   mu_star ranks x1 above x0 above x2, whatever the seed;
Sobol    x0 and x2 carry interactions (ST > S1) and x0's interaction is with x2, while x1's S1 —
         the only parameter whose effect is additive — is the largest single index;
designs  same seed, same design; a different seed, a different design.
```

The sweep set is checked against the real parameter cards, because which cards it admits is the
whole of that function and only the registry can say.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from late_ming_lab.evidence import parameters as P
from late_ming_lab.evidence.cards import ParameterCards, load_cards
from late_ming_lab.experiments.sensitivity import (
    NON_ECONOMY_PARAMETER_SETS,
    SensitivityError,
    SweepParameter,
    morris_design,
    morris_indices,
    morris_problem,
    select_influential,
    sobol_design,
    sobol_indices,
    sweep_parameters,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _parameter(name: str) -> SweepParameter:
    """One Ishigami parameter, on the canonical bounds, as a card range would declare it."""
    return SweepParameter(
        name=name,
        parameter_set="IshigamiFunction",
        card_id=name,
        low=-np.pi,
        high=np.pi,
        unit="rad",
    )


#: The three-parameter problem this test defines.
PARAMETERS = (_parameter("x0"), _parameter("x1"), _parameter("x2"))

#: The design sizes and seeds every assertion below is pinned to.
TRAJECTORIES = 1_000
LEVELS = 4
BASE = 512
SEED = 20_260_914

#: The two cards whose range the sweep set must decline, because their field is a mapping.
DICT_VALUED = ("yield_shi_per_mu", "rent_share_of_harvest")

#: The two medium-priority cards the prior table leaves out of calibration and this sweep keeps.
MEDIUM_PRIORITY = ("land_per_adult_capacity_mu", "wage_grain_shi_per_adult_month")


def _ishigami(design: pl.DataFrame) -> dict[str, list[float]]:
    """The canonical model, as the mapping of output name to one value per run."""
    x = design.select([parameter.name for parameter in PARAMETERS]).to_numpy()
    y = np.sin(x[:, 0]) + 7.0 * np.sin(x[:, 1]) ** 2 + 0.1 * x[:, 2] ** 4 * np.sin(x[:, 0])
    return {"y": y.tolist()}


def _by_parameter(frame: pl.DataFrame) -> dict[str, float]:
    return dict(zip(frame["parameter"], frame["value"], strict=True))


def _small_morris(seed: int) -> pl.DataFrame:
    """A design small enough to draw twice: reproducibility is a property of the seed, not size."""
    return morris_design(PARAMETERS, trajectories=8, levels=LEVELS, seed=seed)


def _small_sobol(seed: int) -> pl.DataFrame:
    return sobol_design(PARAMETERS, base=8, second_order=True, seed=seed)


@pytest.fixture(scope="module")
def cards() -> ParameterCards:
    return load_cards(REPO_ROOT)


@pytest.fixture(scope="module")
def morris_scored() -> pl.DataFrame:
    design = morris_design(PARAMETERS, trajectories=TRAJECTORIES, levels=LEVELS, seed=SEED)
    return morris_indices(PARAMETERS, design, _ishigami(design), levels=LEVELS, seed=SEED)


def test_a_constant_output_reports_undefined_indices_rather_than_crashing() -> None:
    """An output with no variance has indices that are undefined, not zero."""
    design = sobol_design(PARAMETERS, base=4, second_order=True, seed=SEED)
    outputs = {"flat": [3.0] * design.height, **_ishigami(design)}
    tables = sobol_indices(PARAMETERS, outputs, base=4, second_order=True, seed=SEED)

    flat_s1 = tables["S1"].filter(pl.col("output") == "flat")
    assert flat_s1.height == len(PARAMETERS)
    assert flat_s1["value"].is_nan().all()
    assert flat_s1["confidence_low"].is_nan().all()
    assert tables["S1"].filter(pl.col("output") == "y")["value"].is_finite().all()
    assert tables["S2"].filter(pl.col("output") == "flat")["value"].is_nan().all()


def test_an_output_whose_salib_slices_are_constant_is_undefined_not_a_crash() -> None:
    """SALib divides by a slice's variance and fails on the shape when one is flat.

    The slices are strided: A is every `step`-th value and B the one before the next A. An output
    that varies overall while A and B stay put is exactly the case that raised inside SALib before
    this guard, so it is the case the test pins.
    """
    design = sobol_design(PARAMETERS, base=4, second_order=True, seed=SEED)
    step = 2 * len(PARAMETERS) + 2
    values = [float(index) for index in range(design.height)]
    for position in range(0, design.height, step):
        values[position] = 0.0
        values[position + step - 1] = 0.0
    tables = sobol_indices(
        PARAMETERS, {"flat-blocks": values}, base=4, second_order=True, seed=SEED
    )

    assert tables["S1"]["value"].is_nan().all()
    assert tables["ST"]["value"].is_nan().all()


def test_sweep_parameters_are_the_bounded_scalar_cards(cards: ParameterCards) -> None:
    sweeps = sweep_parameters(cards)
    bounded = [
        card
        for card in cards
        if card.range is not None and card.range.low is not None and card.range.high is not None
    ]

    # The sweep set is the bounded scalar cards of the *economy* sets: a swept number has to be a
    # field an arm can set on a parameter model, and the historical core's set is consumed by the
    # dataset build and the climate allocator instead. The exclusion is pinned here so it cannot
    # grow quietly.
    economy_bounded = [
        card for card in bounded if card.parameter_set not in NON_ECONOMY_PARAMETER_SETS
    ]
    excluded = [card for card in bounded if card.parameter_set in NON_ECONOMY_PARAMETER_SETS]
    assert {card.parameter_set for card in excluded} == set(NON_ECONOMY_PARAMETER_SETS)
    assert len(excluded) == 8
    assert len(sweeps) == 15
    assert len(economy_bounded) == 17
    assert {sweep.name for sweep in sweeps} == {card.id for card in economy_bounded} - set(
        DICT_VALUED
    )
    assert set(MEDIUM_PRIORITY) <= {sweep.name for sweep in sweeps}
    # The registry's card order, which is what makes two designs comparable column by column.
    assert tuple(sweep.name for sweep in sweeps) == tuple(
        card.id for card in economy_bounded if card.id not in DICT_VALUED
    )
    for sweep in sweeps:
        card = cards.require(sweep.parameter_set, sweep.name)
        assert card.range is not None
        assert (sweep.low, sweep.high) == (card.range.low, card.range.high)
        assert sweep.card_id == sweep.name == card.id
        assert sweep.unit == card.unit
        assert getattr(P, sweep.parameter_set).model_fields[sweep.name].annotation is float


def test_morris_design_is_one_run_per_step_inside_every_bound() -> None:
    design = morris_design(PARAMETERS, trajectories=TRAJECTORIES, levels=LEVELS, seed=SEED)

    assert design.columns == ["run", "x0", "x1", "x2"]
    assert design.height == (len(PARAMETERS) + 1) * TRAJECTORIES
    assert design["run"].to_list() == list(range(design.height))
    for parameter in PARAMETERS:
        values = design[parameter.name].to_numpy()
        assert float(values.min()) >= parameter.low
        assert float(values.max()) <= parameter.high
    assert morris_problem(PARAMETERS)["groups"] == ["x0", "x1", "x2"]


def test_morris_mu_star_ranks_the_ishigami_parameters(morris_scored: pl.DataFrame) -> None:
    assert set(morris_scored["output"]) == {"y"}
    assert morris_scored["parameter"].to_list() == ["x1", "x0", "x2"]
    mu_star = morris_scored["mu_star"].to_list()
    assert mu_star == sorted(mu_star, reverse=True)


def test_sobol_finds_the_interactions_ishigami_is_known_for() -> None:
    design = sobol_design(PARAMETERS, base=BASE, second_order=True, seed=SEED)
    indices = sobol_indices(PARAMETERS, _ishigami(design), base=BASE, second_order=True, seed=SEED)

    assert design.height == BASE * (2 * len(PARAMETERS) + 2)
    assert indices["S1"].columns == [
        "parameter",
        "output",
        "value",
        "confidence_low",
        "confidence_high",
    ]
    s1 = _by_parameter(indices["S1"])
    st = _by_parameter(indices["ST"])
    # x0 appears inside the x2 term, and x2's own share is that term's nonlinearity, so both
    # parameters carry variance through interactions; x1's effect is additive, so it does not.
    assert st["x0"] > s1["x0"]
    assert st["x2"] > s1["x2"]
    assert max(s1, key=lambda name: s1[name]) == "x1"
    strongest = indices["S2"].sort("value", descending=True).row(0, named=True)
    assert (strongest["parameter_a"], strongest["parameter_b"]) == ("x0", "x2")


def test_second_order_indices_are_empty_when_they_are_not_computed() -> None:
    design = sobol_design(PARAMETERS, base=BASE, second_order=False, seed=SEED)
    indices = sobol_indices(PARAMETERS, _ishigami(design), base=BASE, second_order=False, seed=SEED)

    assert design.height == BASE * (len(PARAMETERS) + 2)
    assert indices["S2"].is_empty()
    assert indices["S2"].columns == [
        "parameter_a",
        "parameter_b",
        "output",
        "value",
        "confidence_low",
        "confidence_high",
    ]
    assert indices["ST"].height == len(PARAMETERS)


def test_indices_refuse_outputs_from_another_design() -> None:
    design = sobol_design(PARAMETERS, base=BASE, second_order=True, seed=SEED)

    with pytest.raises(SensitivityError, match="would be read against a design"):
        sobol_indices(
            PARAMETERS,
            {"y": _ishigami(design)["y"][:-1]},
            base=BASE,
            second_order=True,
            seed=SEED,
        )


def test_select_influential_applies_the_floor_then_the_cap(morris_scored: pl.DataFrame) -> None:
    assert select_influential(morris_scored, output="y", floor_share=0.1, limit=2) == ("x1", "x0")
    # The floor keeps x2 — it is more than a tenth of the strongest mu_star — so the cap is what
    # leaves it out at two parameters, which is the difference between the two stages.
    assert select_influential(morris_scored, output="y", floor_share=0.1, limit=3) == (
        "x1",
        "x0",
        "x2",
    )
    assert select_influential(morris_scored, output="y", floor_share=0.99, limit=8) == ("x1",)
    with pytest.raises(SensitivityError, match="no sensitivity indices"):
        select_influential(morris_scored, output="not-an-output")


def test_designs_reproduce_from_the_seed_and_only_from_the_seed() -> None:
    for build in (_small_morris, _small_sobol):
        assert build(SEED).equals(build(SEED))
        assert not build(SEED).equals(build(SEED + 1))
