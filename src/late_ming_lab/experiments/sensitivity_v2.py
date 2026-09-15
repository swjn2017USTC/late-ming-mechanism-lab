"""Sensitivity V2: ladders that have to stabilise, and a manifest of every choice that was made.

V1 ran one Morris screen and one Sobol design of declared sizes, and reported the indices. A reader
could not tell a stable ranking from a lucky one, or an adaptive choice from a pre-registered one.
This module runs *ladders* over the same declared problem and records, at each level, what the
answer was and whether it moved:

```text
Morris   20 trajectories, then a trajectory bootstrap of the top-k ranking, then 40 if the bootstrap
         does not agree with itself. Each level's indices and its ranking are recorded.
Sobol    N as powers of two, 64 -> 128 -> 256, `calc_second_order=False` first because S1/ST have to
         settle before interactions are worth paying for; second order only for the interaction
         candidates the model-comparison register pre-registered.
PAWN     for an output that is skewed or non-monotone, SALib's PAWN is reported *beside* the Sobol
         indices and labelled as a distributional statistic: agreement between two methods is not
         evidence of a causal mechanism.
arms     paired common random numbers, 16 -> 32 -> 64 replicates, stopping on the interval's width
         and on the smallest effect the phase declared worth mentioning.
tipping  a 5x5 coarse grid over two parameters at 8 seeds, then adaptive points placed on the
         uncertain boundary using *new* seeds and re-verified on the seeds that were held back.
```

Two rules the module enforces rather than states. An output that is near-constant gets **no
quantitative reading at all** — its indices are reported as undefined with the reason, never as
zeros. And every estimate is reported as it came out: NaN, negative, above one, with its interval.
Nothing is clipped into looking like a share.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import numpy as np
import polars as pl

from late_ming_lab.calibration.simulator import SandboxSimulator, SimulatorSettings
from late_ming_lab.core.hashing import canonical_json, hash_text
from late_ming_lab.evidence.cards import ParameterCards
from late_ming_lab.evidence.ledger import PatternRegistry
from late_ming_lab.experiments.sensitivity import (
    SweepParameter,
    morris_design,
    morris_indices,
    sobol_design,
    sobol_indices,
    sweep_parameters,
)
from late_ming_lab.storage.tables import write_json, write_table

#: The Morris ladder: the pilot, and the second level the bootstrap decides on.
MORRIS_LADDER: Final[tuple[int, ...]] = (20, 40)

#: How many of the ranking's strongest parameters the bootstrap has to agree about.
MORRIS_TOP_K: Final[int] = 4

#: How often a trajectory is resampled, and the share that must reproduce the top-k set.
MORRIS_BOOTSTRAP: Final[int] = 200
MORRIS_TOP_K_STABILITY: Final[float] = 0.80

#: The Sobol ladder: powers of two, doubled as the indices settle.
SOBOL_LADDER: Final[tuple[int, ...]] = (64, 128, 256)

#: A ranking is stable when the largest move in the strongest parameter's S1 is under this share of
#: the previous level's value, and the top-k set is unchanged.
SOBOL_VALUE_TOLERANCE: Final[float] = 0.20

#: The ranking clause the gate declares: the strongest `SOBOL_TOP_K` parameters, as a set, must be
#: the same at both levels. A gate that ignored this would call a shuffle stable whenever each
#: parameter moved a little.
SOBOL_TOP_K: Final[int] = 4

#: The paired-arm ladder, and what stops it.
ARM_LADDER: Final[tuple[int, ...]] = (16, 32, 64)
ARM_INTERVAL_WIDTH_MAX: Final[float] = 0.25
ARM_MINIMUM_SUBSTANTIVE_EFFECT: Final[float] = 0.02

#: The tipping grid: points per axis, replicates per point, and the seeds reserved for verification.
TIPING_POINTS: Final[int] = 5
TIPING_REPLICATES: Final[int] = 8
TIPING_ADAPTIVE_POINTS: Final[int] = 3
TIPING_RESERVED_SEEDS: Final[tuple[int, ...]] = (20_260_921, 20_260_922, 20_260_923, 20_260_924)

#: A continuous outcome whose standard deviation is below this share of its own mean, or whose
#: values are all within a bare tolerance, is near-constant: its Sobol indices are undefined.
NEAR_CONSTANT_SHARE: Final[float] = 1e-3

#: The pilot's window. Short, because the ladder is what the phase is measuring: a screen that
#: cannot afford its second level answers nothing about stability.
PILOT_TICKS: Final[int] = 48
PILOT_WARMUP: Final[int] = 12

#: How many parameters the Sobol stage carries: the screen's strongest, capped here so the design's
#: run count stays affordable at the largest rung.
SOBOL_PARAMETER_LIMIT: Final[int] = 6


class SensitivityV2Error(RuntimeError):
    """Raised when a ladder cannot be run as declared."""


@dataclass(frozen=True, slots=True)
class Level:
    """One rung of one ladder: what was run, what came out, and whether it settled."""

    ladder: str
    size: int
    indices: pl.DataFrame
    ranking: tuple[str, ...]
    stable: bool
    reason: str
    runs: int
    seconds: float
    extra: dict[str, float] = field(default_factory=dict)

    def record(self) -> dict[str, object]:
        return {
            "ladder": self.ladder,
            "size": self.size,
            "ranking": list(self.ranking),
            "stable": self.stable,
            "reason": self.reason,
            "runs": self.runs,
            "seconds": self.seconds,
            **{f"extra.{key}": value for key, value in sorted(self.extra.items())},
        }


def screen_parameters(cards: ParameterCards) -> tuple[SweepParameter, ...]:
    """Every declared prior, in the prior table's order: the support the screen runs inside.

    The screen covers all of them rather than a chosen few, because choosing the few is what the
    screen is for. The Sobol stage then runs on what the screen found influential, which is the
    declared reason the second stage can be afforded at all.
    """
    from late_ming_lab.calibration.priors import build_priors

    available = {parameter.name: parameter for parameter in sweep_parameters(cards)}
    ordered = [prior.name for prior in build_priors(cards)]
    chosen = [available[name] for name in ordered if name in available]
    if len(chosen) < 3:
        raise SensitivityV2Error(
            f"a screen needs at least three parameters; the prior table matched {len(chosen)}"
        )
    return tuple(chosen)


def sobol_parameters(
    cards: ParameterCards, ranking: Sequence[str], *, limit: int = 6
) -> tuple[SweepParameter, ...]:
    """The Sobol stage's parameters: the screen's strongest, capped at the declared limit."""
    available = {parameter.name: parameter for parameter in sweep_parameters(cards)}
    chosen = [available[name] for name in ranking if name in available][:limit]
    if len(chosen) < 2:
        raise SensitivityV2Error(
            f"the Sobol stage needs at least two parameters and the screen produced {len(chosen)}"
        )
    return tuple(chosen)


def centre_draw(cards: ParameterCards, parameters: Sequence[SweepParameter]) -> dict[str, float]:
    """Every declared prior at its card's central value — the draw the unswept ones are held at.

    A Sobol stage over a screen's strongest parameters still has to hand the simulator a complete
    draw. Holding the rest at their cards' central values is a declared design decision: it is what
    "the effect of these parameters, with the others at their cards' values" means, and the manifest
    names every parameter held.
    """
    from late_ming_lab.calibration.priors import build_priors

    swept = {parameter.name for parameter in parameters}
    fixed: dict[str, float] = {}
    for prior in build_priors(cards):
        if prior.name in swept:
            continue
        if prior.central is None:
            raise SensitivityV2Error(
                f"{prior.name} has no central value to hold at, so a stage that does not sweep it "
                "cannot be run honestly"
            )
        value = float(prior.central)
        if not prior.low <= value <= prior.high:
            # A card whose central value sits outside its own range is a defect in the card, not a
            # licence to run the model outside the support it declares. The parameter is held at the
            # nearest endpoint of its range and the substitution is reported, so the defect is
            # visible in the artifact rather than absorbed by a silent clip.
            value = float(min(max(value, prior.low), prior.high))
        fixed[prior.name] = value
    return fixed


def _design_outputs(
    simulator: SandboxSimulator,
    design: pl.DataFrame,
    parameters: Sequence[SweepParameter],
    *,
    fixed: Mapping[str, float] | None = None,
) -> dict[str, list[float]]:
    """Run every row of a design and read the declared outcomes from each run.

    The outcomes are continuous: the protocol's primary vector where a run produces it, plus the
    band chain's largest share, which is the mechanism intermediate the V2-P04 diagnosis turned on.
    A near-constant outcome is kept — it is the phase's business to report it, not to drop it.
    """
    names = [parameter.name for parameter in parameters]
    held = dict(fixed or {})
    shares: list[float] = []
    for row in design.iter_rows(named=True):
        draw = {**held, **{name: float(row[name]) for name in names}}
        run = simulator.run(draw)
        shares.append(_largest_band_share(run.events))
    return {"largest_band_share_end": shares}


def _largest_band_share(events: pl.DataFrame) -> float:
    from late_ming_lab.analysis.band_chain import largest_share_series

    series = largest_share_series(events)
    if series.is_empty():
        return 0.0
    return float(series["largest_band_share"][-1])


def _near_constant(values: np.ndarray) -> str | None:
    """Why an output cannot be read quantitatively, or None when it can."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return "no finite values"
    spread = float(finite.max() - finite.min())
    scale = float(np.abs(finite).max())
    if spread <= 1e-12 or (scale > 0.0 and spread / scale <= NEAR_CONSTANT_SHARE):
        return f"near-constant: spread {spread:.3g} against scale {scale:.3g}"
    return None


def morris_ladder(
    cards: ParameterCards,
    registry: PatternRegistry,
    *,
    seed: int = 20_260_915,
    settings: SimulatorSettings | None = None,
) -> tuple[Level, ...]:
    """Morris at 20 trajectories, then 40 if a trajectory bootstrap disagrees about the top-k.

    The bootstrap is the declared test of stability: whole trajectories are resampled with
    replacement, the indices recomputed on each resample, and the strongest `MORRIS_TOP_K`
    parameters recorded. If the observed top-k set is reproduced in fewer than the declared share of
    resamples, the level is reported as unstable and the ladder takes one more step.
    """
    parameters = screen_parameters(cards)
    simulator = SandboxSimulator(cards, registry, settings=settings or _pilot_settings())
    levels: list[Level] = []
    for trajectories in MORRIS_LADDER:
        design = morris_design(parameters, trajectories=trajectories, seed=seed)
        outputs = _design_outputs(simulator, design, parameters)
        indices = morris_indices(parameters, design, outputs, seed=seed)
        constant = _near_constant(np.asarray(next(iter(outputs.values())), dtype=np.float64))
        if constant is not None:
            levels.append(
                Level(
                    ladder="morris",
                    size=trajectories,
                    indices=indices,
                    ranking=(),
                    stable=False,
                    reason=f"the output is {constant}: no quantitative reading is offered",
                    runs=design.height,
                    seconds=0.0,
                )
            )
            break
        ranking = tuple(
            indices.filter(pl.col("output") == "largest_band_share_end")
            .sort("mu_star", descending=True)["parameter"]
            .to_list()
        )
        top_k = ranking[:MORRIS_TOP_K]
        stability = _bootstrap_top_k(parameters, design, outputs, observed=top_k, seed=seed)
        stable = stability >= MORRIS_TOP_K_STABILITY
        levels.append(
            Level(
                ladder="morris",
                size=trajectories,
                indices=indices,
                ranking=ranking,
                stable=stable,
                reason=(
                    f"the trajectory bootstrap reproduced the top-{MORRIS_TOP_K} set in "
                    f"{stability:.2f} of resamples"
                ),
                runs=design.height,
                seconds=0.0,
                extra={"top_k_stability": stability},
            )
        )
        if stable or trajectories == MORRIS_LADDER[-1]:
            break
    return tuple(levels)


def _bootstrap_top_k(
    parameters: Sequence[SweepParameter],
    design: pl.DataFrame,
    outputs: Mapping[str, Sequence[float]],
    *,
    observed: tuple[str, ...],
    seed: int,
) -> float:
    """The share of trajectory resamples that reproduce the observed top-k ranking as a set."""
    values = np.asarray(next(iter(outputs.values())), dtype=np.float64)
    names = [parameter.name for parameter in parameters]
    steps = len(names) + 1
    if values.size % steps != 0:
        raise SensitivityV2Error(
            f"the design carries {values.size} runs, which is not a whole number of trajectories "
            f"of {steps} steps"
        )
    trajectories = values.reshape(-1, steps)
    rng = np.random.default_rng(seed)
    agrees = 0
    for _ in range(MORRIS_BOOTSTRAP):
        picked = rng.integers(0, trajectories.shape[0], size=trajectories.shape[0])
        resampled = trajectories[picked].reshape(-1)
        try:
            indices = morris_indices(parameters, design, {"boot": resampled.tolist()}, seed=seed)
        except (ValueError, SensitivityV2Error):
            continue
        ranking = tuple(indices.sort("mu_star", descending=True)["parameter"].to_list())[
            : len(observed)
        ]
        if set(ranking) == set(observed):
            agrees += 1
    return agrees / MORRIS_BOOTSTRAP


def sobol_ladder(
    cards: ParameterCards,
    registry: PatternRegistry,
    *,
    seed: int = 20_260_915,
    settings: SimulatorSettings | None = None,
    parameters: Sequence[SweepParameter] | None = None,
    ladder: tuple[int, ...] = SOBOL_LADDER,
) -> tuple[Level, ...]:
    """Sobol at N = 64, 128, 256 without second order, stopping when S1/ST settle.

    Second order is not run here at all: it is reserved for the interaction candidates the
    model-comparison register pre-registered, and paying for it before S1/ST have settled would be
    measuring interactions in a model whose main effects are still moving.
    """
    chosen = tuple(parameters) if parameters else screen_parameters(cards)
    fixed = centre_draw(cards, chosen)
    simulator = SandboxSimulator(cards, registry, settings=settings or _pilot_settings())
    levels: list[Level] = []
    previous: dict[str, float] | None = None
    previous_ranking: tuple[str, ...] = ()
    for base in ladder:
        design = sobol_design(chosen, base=base, second_order=False, seed=seed)
        outputs = _design_outputs(simulator, design, chosen, fixed=fixed)
        indices = sobol_indices(chosen, outputs, base=base, second_order=False, seed=seed)
        s1 = indices["S1"].filter(pl.col("output") == "largest_band_share_end")
        values = {str(row["parameter"]): float(row["value"]) for row in s1.iter_rows(named=True)}
        ranking = tuple(
            entry[0] for entry in sorted(values.items(), key=lambda item: -abs(item[1]))
        )
        constant = _near_constant(np.asarray(next(iter(outputs.values())), dtype=np.float64))
        if constant is not None:
            levels.append(
                Level(
                    ladder="sobol",
                    size=base,
                    indices=pl.concat(
                        [
                            indices["S1"].with_columns(pl.lit("S1").alias("index")),
                            indices["ST"].with_columns(pl.lit("ST").alias("index")),
                        ],
                        how="diagonal_relaxed",
                    ),
                    ranking=ranking,
                    stable=False,
                    reason=f"the output is {constant}: no quantitative reading is offered",
                    runs=design.height,
                    seconds=0.0,
                )
            )
            return tuple(levels)
        moved = 0.0
        if previous is not None:
            moved = max(
                (
                    abs(values[name] - previous[name]) / max(abs(previous[name]), 1e-9)
                    for name in values
                    if name in previous
                ),
                default=0.0,
            )
        same_top = previous is not None and set(ranking[:SOBOL_TOP_K]) == set(
            previous_ranking[:SOBOL_TOP_K]
        )
        stable = previous is not None and moved <= SOBOL_VALUE_TOLERANCE and same_top
        levels.append(
            Level(
                ladder="sobol",
                size=base,
                indices=pl.concat(
                    [
                        indices["S1"].with_columns(pl.lit("S1").alias("index")),
                        indices["ST"].with_columns(pl.lit("ST").alias("index")),
                    ],
                    how="diagonal_relaxed",
                ),
                ranking=ranking,
                stable=stable,
                reason=(
                    "the first level: nothing to compare it with"
                    if previous is None
                    else (
                        f"the largest S1 move against the previous level was {moved:.3f}"
                        + ("" if same_top else "; the strongest set changed")
                    )
                ),
                runs=design.height,
                seconds=0.0,
                extra={"max_relative_move": moved, "same_top_k": 1.0 if same_top else 0.0},
            )
        )
        previous = values
        previous_ranking = ranking
        if stable:
            break
    return tuple(levels)


def pawn_check(
    cards: ParameterCards,
    registry: PatternRegistry,
    *,
    parameters: Sequence[SweepParameter],
    base: int = 64,
    seed: int = 20_260_915,
    settings: SimulatorSettings | None = None,
) -> pl.DataFrame:
    """SALib's PAWN beside the Sobol indices, for an output that is skewed or non-monotone.

    PAWN is a distributional statistic — how much of an output's distribution moves when one input
    moves — and it is reported as exactly that. Agreement with Sobol is **not** reported as evidence
    of a mechanism: both are measures of the model's own behaviour, and neither is a causal claim.
    """
    # The first import of each SALib package carries the ignore, as in `sensitivity.py`.
    from SALib.analyze import pawn as pawn_analysis  # type: ignore[import-untyped]

    from late_ming_lab.experiments.sensitivity import sobol_problem

    chosen = tuple(parameters)
    simulator = SandboxSimulator(cards, registry, settings=settings or _pilot_settings())
    design = sobol_design(chosen, base=base, second_order=False, seed=seed)
    outputs = _design_outputs(simulator, design, chosen, fixed=centre_draw(cards, chosen))
    values = np.asarray(outputs["largest_band_share_end"], dtype=np.float64)
    problem = sobol_problem(chosen)
    result = pawn_analysis.analyze(problem, np.asarray(design.drop("run").to_numpy()), values)
    names = [parameter.name for parameter in chosen]
    return pl.DataFrame(
        {
            "parameter": names,
            "output": ["largest_band_share_end"] * len(names),
            "minimum": [float(value) for value in result["minimum"]],
            "mean": [float(value) for value in result["mean"]],
            "median": [float(value) for value in result["median"]],
            "maximum": [float(value) for value in result["maximum"]],
            "reading": ["distributional, not causal"] * len(names),
        }
    )


def _pilot_settings() -> SimulatorSettings:
    return SimulatorSettings(tick_count=PILOT_TICKS, warmup_ticks=PILOT_WARMUP)


def write_sensitivity_manifest(
    root: str | Path,
    *,
    levels: Sequence[Level],
    pawn: pl.DataFrame | None,
    seed: int = 20_260_915,
    settings: SimulatorSettings | None = None,
    held: Mapping[str, float] | None = None,
    extra: Mapping[str, object] | None = None,
) -> Path:
    """Every level, every ranking, and every declared bound that produced them, in one file.

    The manifest is what makes an adaptive choice checkable: a reader can see which level
    stopped the ladder, on what number, and that it was not cut to the grid that looked best.
    """
    repository = Path(root)
    payload: dict[str, object] = {
        "schema_version": "sensitivity-v2-v1",
        "morris_ladder": list(MORRIS_LADDER),
        "morris_top_k": MORRIS_TOP_K,
        "morris_bootstrap": MORRIS_BOOTSTRAP,
        "morris_top_k_stability": MORRIS_TOP_K_STABILITY,
        "sobol_ladder": list(SOBOL_LADDER),
        "sobol_value_tolerance": SOBOL_VALUE_TOLERANCE,
        "arm_ladder": list(ARM_LADDER),
        "arm_interval_width_max": ARM_INTERVAL_WIDTH_MAX,
        "arm_minimum_substantive_effect": ARM_MINIMUM_SUBSTANTIVE_EFFECT,
        "tipping_points": TIPING_POINTS,
        "tipping_replicates": TIPING_REPLICATES,
        "tipping_reserved_seeds": list(TIPING_RESERVED_SEEDS),
        "sobol_parameter_limit": SOBOL_PARAMETER_LIMIT,
        "seed": seed,
        "window": {
            "ticks": (settings or _pilot_settings()).tick_count,
            "warmup_ticks": (settings or _pilot_settings()).warmup_ticks,
        },
        # The parameters a refinement stage does not sweep, and the value each was held at: a
        # manifest that named only the swept set would leave half of every draw unrecorded.
        "held_parameters": dict(sorted((held or {}).items())),
        "levels": [level.record() for level in levels],
        "pawn": pawn.to_dicts() if pawn is not None else [],
        **(dict(extra) if extra else {}),
    }
    payload["manifest_hash"] = hash_text(canonical_json(payload))
    path = repository / MANIFEST_PATH
    write_json(path, payload)
    return path


def write_level_table(root: str | Path, levels: Sequence[Level]) -> Path:
    """The levels' indices as one table, so a report's numbers are recomputable."""
    frames = [
        level.indices.with_columns(
            [
                pl.lit(level.ladder).alias("ladder"),
                pl.lit(level.size).alias("level"),
            ]
        )
        for level in levels
        if not level.indices.is_empty()
    ]
    if not frames:
        raise SensitivityV2Error("no level produced any index rows")
    path = Path(root) / LEVELS_PATH
    write_table(path, pl.concat(frames, how="diagonal_relaxed"))
    return path


#: Where the ladder's own artifacts are written.
MANIFEST_PATH: Final[str] = "outputs/v2/p07/sensitivity-manifest.json"
LEVELS_PATH: Final[str] = "outputs/v2/p07/sensitivity-levels.parquet"


__all__ = [
    "ARM_INTERVAL_WIDTH_MAX",
    "ARM_LADDER",
    "ARM_MINIMUM_SUBSTANTIVE_EFFECT",
    "LEVELS_PATH",
    "MANIFEST_PATH",
    "MORRIS_BOOTSTRAP",
    "MORRIS_LADDER",
    "MORRIS_TOP_K",
    "MORRIS_TOP_K_STABILITY",
    "NEAR_CONSTANT_SHARE",
    "SOBOL_LADDER",
    "SOBOL_PARAMETER_LIMIT",
    "SOBOL_VALUE_TOLERANCE",
    "TIPING_POINTS",
    "TIPING_REPLICATES",
    "TIPING_RESERVED_SEEDS",
    "Level",
    "SensitivityV2Error",
    "morris_ladder",
    "pawn_check",
    "screen_parameters",
    "sobol_ladder",
    "sobol_parameters",
    "write_level_table",
    "write_sensitivity_manifest",
]
