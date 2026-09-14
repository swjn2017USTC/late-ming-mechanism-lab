"""Global sensitivity: which parameters, if any, the run's outcomes actually move.

P09 calibrated thirteen parameters against the target patterns. This module asks the prior
question — whether an outcome depends on a parameter *at all* — with the two methods the plan names,
in the order it names them:

```text
Morris    a screening design. A few trajectories per parameter give mu (mean elementary effect),
          mu_star (its mean magnitude, the one to rank on) and sigma (how much the effect varies),
          which is a cheap first pass over every declared parameter.
Sobol     the variance decomposition. S1 is a parameter's own share of the outcome's variance, ST
          its share including every interaction it takes part in, and S2 the pairwise interactions
          between parameters — the interaction evidence this phase reports.
```

**The sweep set is deliberately wider than the calibration set.** A parameter that no target
pattern's checks reach can still move an outcome, and it is exactly the parameter a calibration is
most likely to leave unexamined, so the two medium-priority range-carrying cards that
`late_ming_lab.calibration.priors` excludes from calibration — ``land_per_adult_capacity_mu`` and
``wage_grain_shi_per_adult_month`` — are swept here.

**Two range-carrying cards are not swept, and the reason is the field, not the card.** A design
column holds one number per run, so a parameter can be swept only where the live parameter set
holds one number. ``yield_shi_per_mu`` is a baseline per agrarian zone and ``rent_share_of_harvest``
a rent share per cohort class: both cards declare a range, but the field in use is a mapping, and
turning a mapping into one column would mean choosing a reduction — a mean, a single zone, a single
class — that neither the card nor the evidence behind it states. They are therefore not swept at
all, rather than swept by a number the model never runs.

Nothing here decides what an outcome *is*: the caller hands in the model's outputs and gets back
the same indices whatever they are. Indices are computed, never scored against anything. Every
design is drawn from the seed it is given, so `same code + same config + same seed` reproduces a
design exactly; no module-level state and no clock reading enters either sampler.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import polars as pl
from pydantic import BaseModel

# The first import of each SALib package carries the ignore: mypy reports the missing marker once
# per package, so a second one beside `sobol` would be an unused ignore.
from SALib.analyze import morris as morris_analyze  # type: ignore[import-untyped]
from SALib.analyze import sobol as sobol_analyze
from SALib.sample import morris as morris_sample  # type: ignore[import-untyped]
from SALib.sample import sobol as sobol_sample

from late_ming_lab.evidence import parameters as parameter_sets
from late_ming_lab.evidence.cards import ParameterCards


class SensitivityError(ValueError):
    """Raised when a design or an index frame cannot be built from what was handed in."""


@dataclass(frozen=True, slots=True)
class SweepParameter:
    """One parameter a global sensitivity analysis may move."""

    name: str
    """The field name the parameter set declares."""

    parameter_set: str
    """The parameter set class the field belongs to, e.g. ``FiscalParameters``."""

    card_id: str
    """The P08 card id. Equal to :attr:`name` in every card today; checked, not assumed."""

    low: float
    """The card's lower bound — the design's low end, unadjusted."""

    high: float
    """The card's upper bound — the design's high end, unadjusted."""

    unit: str
    """The card's unit, carried so a report can label what a moved value means."""


#: Parameter sets a sandbox sweep does not touch, with the reason. A swept number has to be set on
#: a parameter model the *economy* holds, because that is what an arm copies into a run; the
#: historical core's set is consumed by the dataset build and by the climate allocator, so a sweep
#: here would set a value no arm reads. V2-P07 owns sensitivity for that allocator, where the
#: ablation is the allocation mode rather than a single number.
NON_ECONOMY_PARAMETER_SETS: Final[dict[str, str]] = {
    "HistoricalCoreParameters": (
        "consumed by the historical core's dataset build and climate allocator, not by the sandbox "
        "economy; V2-P07 sweeps the allocator as a mode ablation instead"
    ),
}


def _is_scalar_field(parameter_set: str, name: str) -> bool:
    """Whether the live parameter set declares ``name`` as a single-number float field.

    The field, not the card, decides: a design column sets one number, so a set that holds a
    mapping under that name cannot be swept however bounded its card is. A card naming a set or a
    field the live models do not have is an error rather than a quiet omission — that is the one
    way a sweep could shrink without anyone noticing.
    """
    model = getattr(parameter_sets, parameter_set, None)
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        raise SensitivityError(
            f"{parameter_set} is not a live parameter set, so its card cannot be swept"
        )
    field = model.model_fields.get(name)
    if field is None:
        raise SensitivityError(f"{parameter_set}.{name} has a card but is not a field of the set")
    return field.annotation is float


def sweep_parameters(cards: ParameterCards) -> tuple[SweepParameter, ...]:
    """Every parameter whose P08 card declares a bounded range and whose field is a scalar.

    The sweep set is deliberately wider than the calibration set: sensitivity asks whether a
    parameter matters at all, so the two medium-priority cards the prior table excludes are swept
    here, and the two dict-valued cards are excluded with the reason recorded in the module
    docstring. Order is the registry's card file order — parameter set, then card id — so a design
    is reproducible.
    """
    parameters: list[SweepParameter] = []
    for card in cards:
        card_range = card.range
        if card_range is None or card_range.low is None or card_range.high is None:
            continue
        if card.parameter_set in NON_ECONOMY_PARAMETER_SETS:
            continue
        if not _is_scalar_field(card.parameter_set, card.id):
            continue
        low, high = card_range.low, card_range.high
        if low >= high:
            raise SensitivityError(
                f"{card.parameter_set}.{card.id}: the card range [{low:g}, {high:g}] is not a range"
            )
        parameters.append(
            SweepParameter(
                name=card.id,
                parameter_set=card.parameter_set,
                card_id=card.id,
                low=low,
                high=high,
                unit=card.unit,
            )
        )
    if not parameters:
        raise SensitivityError("the registry declares no bounded scalar parameter to sweep")
    return tuple(parameters)


def _names(parameters: Sequence[SweepParameter]) -> list[str]:
    """The parameter names, refused when a design column could not tell two of them apart."""
    names = [parameter.name for parameter in parameters]
    if not names:
        raise SensitivityError("a sensitivity design needs at least one parameter")
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise SensitivityError(
            f"a design column cannot carry two parameters: {', '.join(duplicates)}"
        )
    return names


def _problem(parameters: Sequence[SweepParameter]) -> dict[str, object]:
    """The SALib problem both samplers take: names, bounds, and one group per name."""
    names = _names(parameters)
    problem: dict[str, object] = {
        "num_vars": len(names),
        "names": names,
        "bounds": [[parameter.low, parameter.high] for parameter in parameters],
        # One group per parameter: SALib substitutes exactly these names for a missing key, and
        # writing them out keeps the problem dict self-contained and identical for both samplers.
        "groups": list(names),
    }
    return problem


def morris_problem(parameters: Sequence[SweepParameter]) -> dict[str, object]:
    """The SALib problem dict: names, bounds, and the groups key SALib expects."""
    return _problem(parameters)


def sobol_problem(parameters: Sequence[SweepParameter]) -> dict[str, object]:
    """The Sobol problem dict; the same shape, so a caller need not know the two agree."""
    return _problem(parameters)


def _design_frame(parameters: Sequence[SweepParameter], values: np.ndarray) -> pl.DataFrame:
    """The sampled matrix as a tidy frame: a ``run`` id, then one column per parameter."""
    columns: dict[str, np.ndarray] = {"run": np.arange(values.shape[0], dtype=np.int64)}
    for index, parameter in enumerate(parameters):
        columns[parameter.name] = values[:, index]
    return pl.DataFrame(columns)


def _plain_float(value: object) -> float:
    """One SALib index as a plain float; a masked entry becomes nan rather than a hidden object."""
    return float(np.ma.filled(np.ma.asarray(value, dtype=np.float64), np.nan))


def morris_design(
    parameters: Sequence[SweepParameter], *, trajectories: int, levels: int = 4, seed: int
) -> pl.DataFrame:
    """The Morris design: one row per run, one column per parameter, plus a `run` id column."""
    if trajectories < 1:
        raise SensitivityError("a Morris screen needs at least one trajectory")
    problem = morris_problem(parameters)
    sample = morris_sample.sample(problem, trajectories, num_levels=levels, seed=seed)
    return _design_frame(parameters, np.asarray(sample, dtype=np.float64))


def morris_indices(
    parameters: Sequence[SweepParameter],
    design: pl.DataFrame,
    outputs: Mapping[str, Sequence[float]],
    *,
    levels: int = 4,
    seed: int,
) -> pl.DataFrame:
    """Per parameter and per output: `mu`, `mu_star`, `sigma` — long format, sorted by
    mu_star descending within each output.

    ``design`` is the frame :func:`morris_design` returned for the same parameters: the elementary
    effects are read off the design's steps, so the outputs must be the runs of that design.
    """
    names = _names(parameters)
    problem = morris_problem(parameters)
    sampled = design.select(names).to_numpy()
    expected = len(sampled)
    frames: list[pl.DataFrame] = []
    for output, series in outputs.items():
        values = np.asarray(series, dtype=np.float64)
        if values.shape != (expected,):
            raise SensitivityError(
                f"output {output!r} carries {values.size} runs, but the design has {expected}: "
                "its elementary effects would be read against a design it did not come from"
            )
        result = morris_analyze.analyze(
            problem,
            sampled,
            values,
            num_levels=levels,
            seed=seed,
        )
        rows = [
            {
                "parameter": name,
                "output": output,
                "mu": _plain_float(result["mu"][index]),
                "mu_star": _plain_float(result["mu_star"][index]),
                "sigma": _plain_float(result["sigma"][index]),
            }
            for index, name in enumerate(names)
        ]
        frames.append(
            pl.DataFrame(
                rows,
                schema={
                    "parameter": pl.String,
                    "output": pl.String,
                    "mu": pl.Float64,
                    "mu_star": pl.Float64,
                    "sigma": pl.Float64,
                },
            ).sort("mu_star", descending=True, maintain_order=True)
        )
    if not frames:
        raise SensitivityError("no outputs were handed in to compute indices for")
    return pl.concat(frames)


def select_influential(
    indices: pl.DataFrame, *, output: str, floor_share: float = 0.1, limit: int = 8
) -> tuple[str, ...]:
    """The declared selection rule: parameters whose mu_star for `output` is at least
    `floor_share` of that output's largest mu_star, capped at `limit`, strongest first.

    The floor is relative to the strongest parameter rather than an absolute mu_star, because
    mu_star is in whatever unit the outcome carries; the cap keeps the Sobol stage affordable on
    the count of runs, not on a guess about which parameters matter.
    """
    if limit < 1:
        raise SensitivityError("the selection cap must keep at least one parameter")
    scored = indices.filter(pl.col("output") == output)
    if scored.is_empty():
        raise SensitivityError(f"no sensitivity indices for output {output!r}")
    floor = floor_share * _plain_float(scored["mu_star"].max())
    ranked = scored.filter(pl.col("mu_star") >= floor).sort(
        "mu_star", descending=True, maintain_order=True
    )
    return tuple(ranked["parameter"].head(limit).to_list())


def sobol_design(
    parameters: Sequence[SweepParameter], *, base: int, second_order: bool = True, seed: int
) -> pl.DataFrame:
    """The Sobol design: one row per run, one column per parameter, plus a `run` id column."""
    if base < 1:
        raise SensitivityError("a Sobol design needs at least one base draw")
    problem = sobol_problem(parameters)
    sample = sobol_sample.sample(problem, base, calc_second_order=second_order, seed=seed)
    return _design_frame(parameters, np.asarray(sample, dtype=np.float64))


def _sobol_run_count(num_vars: int, *, base: int, second_order: bool) -> int:
    """How many runs a Sobol design of this size holds: SALib's A/B/AB blocks, or A/B alone."""
    return base * (2 * num_vars + 2) if second_order else base * (num_vars + 2)


def _undefined_reason(
    values: np.ndarray, *, num_vars: int, base: int, second_order: bool
) -> str | None:
    """Why this output has no Sobol indices, or None when they are defined.

    SALib estimates each index from a ratio whose denominator is the variance of one slice of the
    design: the A or B matrix, a per-parameter replacement, or the union of A and B. The slices are
    strided, not contiguous — `A = Y[0::step]`, `B = Y[step-1::step]`, `AB[:, j] = Y[j+1::step]` —
    and this function mirrors that layout because a slice with no variance leaves the estimator
    undefined. SALib's own arithmetic then returns a one-element array where the caller expects a
    scalar and fails on the shape, which is a poor way to learn that an output did not move.
    """
    if values.size == 0:
        return "the output carries no runs"
    if float(np.ptp(values)) == 0.0:
        return "the output does not vary across the whole design"
    step = 2 * num_vars + 2 if second_order else num_vars + 2
    a = values[0::step]
    b = values[step - 1 :: step]
    if a.size and b.size and float(np.ptp(np.concatenate([a, b]))) == 0.0:
        return "the A and B slices of the output do not vary"
    slices: list[tuple[str, np.ndarray]] = [("A", a), ("B", b)]
    for index in range(num_vars):
        slices.append((f"AB[{index}]", values[index + 1 :: step]))
        if second_order:
            slices.append((f"BA[{index}]", values[index + 1 + num_vars :: step]))
    for label, block in slices:
        if block.size and float(np.ptp(block)) == 0.0:
            return f"the {label} slice of the output does not vary"
    return None


def _constant_output_rows(
    names: Sequence[str],
    *,
    output: str,
    second_order: bool,
    s1_rows: list[dict[str, object]],
    st_rows: list[dict[str, object]],
    s2_rows: list[dict[str, object]],
) -> None:
    """Undefined indices for an output that does not move across the design."""
    undefined = float("nan")
    for name in names:
        for rows in (s1_rows, st_rows):
            rows.append(
                {
                    "parameter": name,
                    "output": output,
                    "value": undefined,
                    "confidence_low": undefined,
                    "confidence_high": undefined,
                }
            )
    if second_order:
        for first, left in enumerate(names):
            for right in names[first + 1 :]:
                s2_rows.append(
                    {
                        "parameter_a": left,
                        "parameter_b": right,
                        "output": output,
                        "value": undefined,
                        "confidence_low": undefined,
                        "confidence_high": undefined,
                    }
                )


def sobol_indices(
    parameters: Sequence[SweepParameter],
    outputs: Mapping[str, Sequence[float]],
    *,
    base: int,
    second_order: bool = True,
    seed: int,
) -> dict[str, pl.DataFrame]:
    """`{'S1': …, 'ST': …, 'S2': …}` as tidy frames: S1/ST long with columns
    ['parameter','output','value','confidence_low','confidence_high'], S2 with
    ['parameter_a','parameter_b','output','value','confidence_low','confidence_high'] (empty when
    `second_order` is False). Second-order indices are the interaction effects this phase reports.

    The output column is added to the declared columns because a frame that cannot name its outcome
    would be unreadable the moment a caller passes more than one. Each output must carry exactly
    the runs of the design drawn from ``base`` and ``second_order``: an output of another length
    would be read against the wrong design, which no numerical check inside SALib could see.

    An output that does not vary across the design has no variance to decompose. SALib divides by
    that variance, so the indices are not zero but undefined; they are reported as NaN rows with
    both confidence bounds NaN, which is what a report should print rather than a crash or a
    confident zero.
    """
    if base < 1:
        raise SensitivityError("a Sobol design needs at least one base draw")
    names = _names(parameters)
    problem = sobol_problem(parameters)
    expected = _sobol_run_count(len(names), base=base, second_order=second_order)
    s1_rows: list[dict[str, object]] = []
    st_rows: list[dict[str, object]] = []
    s2_rows: list[dict[str, object]] = []
    for output, series in outputs.items():
        values = np.asarray(series, dtype=np.float64)
        if values.shape != (expected,):
            raise SensitivityError(
                f"output {output!r} carries {values.size} runs, but a Sobol design with base "
                f"{base} over {len(names)} parameters has {expected}: its indices would be read "
                "against a design it did not come from"
            )
        if (
            _undefined_reason(values, num_vars=len(names), base=base, second_order=second_order)
            is not None
        ):
            _constant_output_rows(
                names,
                output=output,
                second_order=second_order,
                s1_rows=s1_rows,
                st_rows=st_rows,
                s2_rows=s2_rows,
            )
            continue
        result = sobol_analyze.analyze(problem, values, calc_second_order=second_order, seed=seed)
        for index, name in enumerate(names):
            s1 = _plain_float(result["S1"][index])
            s1_confidence = _plain_float(result["S1_conf"][index])
            st = _plain_float(result["ST"][index])
            st_confidence = _plain_float(result["ST_conf"][index])
            s1_rows.append(
                {
                    "parameter": name,
                    "output": output,
                    "value": s1,
                    "confidence_low": s1 - s1_confidence,
                    "confidence_high": s1 + s1_confidence,
                }
            )
            st_rows.append(
                {
                    "parameter": name,
                    "output": output,
                    "value": st,
                    "confidence_low": st - st_confidence,
                    "confidence_high": st + st_confidence,
                }
            )
        if second_order:
            pairs = result["S2"]
            pair_confidence = result["S2_conf"]
            for first in range(len(names)):
                for second in range(first + 1, len(names)):
                    value = _plain_float(pairs[first][second])
                    confidence = _plain_float(pair_confidence[first][second])
                    s2_rows.append(
                        {
                            "parameter_a": names[first],
                            "parameter_b": names[second],
                            "output": output,
                            "value": value,
                            "confidence_low": value - confidence,
                            "confidence_high": value + confidence,
                        }
                    )
    index_schema = {
        "parameter": pl.String,
        "output": pl.String,
        "value": pl.Float64,
        "confidence_low": pl.Float64,
        "confidence_high": pl.Float64,
    }
    pair_schema = {
        "parameter_a": pl.String,
        "parameter_b": pl.String,
        "output": pl.String,
        "value": pl.Float64,
        "confidence_low": pl.Float64,
        "confidence_high": pl.Float64,
    }
    return {
        "S1": pl.DataFrame(s1_rows, schema=index_schema),
        "ST": pl.DataFrame(st_rows, schema=index_schema),
        "S2": pl.DataFrame(s2_rows, schema=pair_schema),
    }
