"""The accepted-draw ensemble: the particle set, its frozen inputs, and what it can say about
the parameters.

The phase forbids a single best fit, so the artifact is the whole particle set: each draw's
parameter vector and each draw's pattern-distance vector, together with the digests that make the
batch identifiable — the frozen P08 registry, the declared bounds, the declared checks, the fixed
scenario and seed, and the sampler's own settings. Nothing here selects a winner.

Two questions are answered from the same draws, each by a rule stated in advance rather than chosen
after seeing the numbers:

- **identifiability** — how far the posterior moves away from the prior. The rule is the contraction
  of the weighted interquartile range against the prior's full range: at most half is *identified*,
  at least four fifths is *unresolved*, and anything between is *weak*.
- **equifinality** — which pairs of parameters trade off against each other. The rule is the
  weighted correlation between two parameters' draws: ``|r| >= 0.7`` is reported as a trade-off,
  because at this scale the ensemble cannot separate them and a reader must not read either one
  alone.

Both rules are coarse on purpose. Their thresholds are declared in this module so a reader can see
where a verdict comes from, and every underlying number is persisted beside it.

The manifest is a Pydantic record like every other persisted record in this project, so a batch that
is read back is validated rather than parsed by hand.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Final, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict

from late_ming_lab import __version__ as engine_version
from late_ming_lab.calibration.freeze import evidence_digest, frozen_file_digests, prior_digest
from late_ming_lab.calibration.priors import PriorTable
from late_ming_lab.calibration.windows import WINDOWS
from late_ming_lab.core.hashing import canonical_json, hash_text
from late_ming_lab.evidence.provenance import git_provenance

ENSEMBLE_FILE: Final[str] = "ensemble.parquet"
MANIFEST_FILE: Final[str] = "manifest.json"

#: A parameter is *identified* when the posterior interquartile range is at most this share of the
#: prior's range, and *unresolved* when it is at least the larger share. The band between the two is
#: reported as weak identification rather than forced into a verdict.
IDENTIFIED_CONTRACTION: Final[float] = 0.5
UNRESOLVED_CONTRACTION: Final[float] = 0.8

#: Two parameters are reported as trading off when their weighted draws correlate at least this
#: strongly in absolute value.
TRADE_OFF_CORRELATION: Final[float] = 0.7

#: A draw counts as consistent with a pattern when its score for that pattern is at most this.
CONSISTENT_SCORE: Final[float] = 0.0

#: Two batches at the same settings with different sampler seeds are called *reproducible* in a
#: parameter when their medians differ by less than this share of the prior range. A narrower shift
#: than this is what separates a posterior the data supports from a particle cloud that collapsed
#: around one resampled ancestor: a collapsed cloud moves with the seed, a supported posterior does
#: not.
REPRODUCIBLE_SHIFT: Final[float] = 0.25


class EnsembleError(RuntimeError):
    """Raised when an ensemble cannot be written or read back."""


class Identification(StrEnum):
    """What the posterior says about one parameter."""

    IDENTIFIED = "identified"
    WEAK = "weak"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class Draw:
    """One accepted particle: its parameter vector, its pattern scores and its weight."""

    parameters: tuple[tuple[str, float], ...]
    scores: tuple[float, ...]
    weight: float

    def parameter_map(self) -> dict[str, float]:
        return dict(self.parameters)


class Provenance(BaseModel):
    """The frozen inputs a batch was run against, recorded rather than reconstructed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["calibration-manifest-v1"] = "calibration-manifest-v1"
    batch_id: str
    generated_at_utc: str
    git_sha: str | None
    git_dirty: bool | None
    engine_version: str
    pymc_version: str
    arviz_version: str
    evidence_digest: str
    evidence_files: tuple[tuple[str, str], ...]
    pattern_schema_version: str
    prior_digest: str
    objective_digest: str
    simulation_config_hash: str
    root_seed: int
    scenario: dict[str, float | str]
    windows: dict[str, tuple[int, int]]
    target_ids: tuple[str, ...]
    hold_out_ids: tuple[str, ...]
    particles: int
    chains: int
    tolerance: float
    sampler_seed: int
    parameter_names: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> Provenance:
        return cls.model_validate_json(text)


@dataclass(frozen=True, slots=True)
class ParameterVerdict:
    """One parameter's prior-versus-posterior comparison."""

    name: str
    prior_low: float
    prior_high: float
    posterior_median: float
    posterior_q1: float
    posterior_q3: float
    contraction: float
    verdict: Identification


@dataclass(frozen=True, slots=True)
class TradeOff:
    """Two parameters the posterior cannot separate at this scale."""

    left: str
    right: str
    correlation: float


@dataclass(frozen=True, slots=True)
class PatternVerdict:
    """One target pattern's distance vector across the ensemble."""

    pattern_id: str
    consistent_share: float
    mean_score: float
    worst_score: float


@dataclass(frozen=True, slots=True)
class SeedComparison:
    """One parameter's location in two batches that differ only in the sampler's seed."""

    name: str
    prior_low: float
    prior_high: float
    first_median: float
    second_median: float
    shift: float
    reproducible: bool


@dataclass(frozen=True, slots=True)
class Ensemble:
    """The particle set and the provenance that identifies it."""

    provenance: Provenance
    draws: tuple[Draw, ...]
    pattern_ids: tuple[str, ...]

    def parameter_names(self) -> tuple[str, ...]:
        return self.provenance.parameter_names

    def weights(self) -> tuple[float, ...]:
        return tuple(draw.weight for draw in self.draws)

    def parameter_values(self, name: str) -> tuple[float, ...]:
        return tuple(draw.parameter_map()[name] for draw in self.draws)

    def scores(self) -> tuple[tuple[float, ...], ...]:
        return tuple(draw.scores for draw in self.draws)

    def verdicts(self, priors: PriorTable) -> tuple[ParameterVerdict, ...]:
        """Prior versus posterior per parameter, by the declared contraction rule."""
        verdicts: list[ParameterVerdict] = []
        weights = self.weights()
        for prior in priors:
            values = self.parameter_values(prior.name)
            median = weighted_quantile(values, weights, 0.5)
            q1 = weighted_quantile(values, weights, 0.25)
            q3 = weighted_quantile(values, weights, 0.75)
            span = prior.high - prior.low
            contraction = (q3 - q1) / span if span > 0.0 else 1.0
            verdicts.append(
                ParameterVerdict(
                    name=prior.name,
                    prior_low=prior.low,
                    prior_high=prior.high,
                    posterior_median=median,
                    posterior_q1=q1,
                    posterior_q3=q3,
                    contraction=contraction,
                    verdict=_verdict_for(contraction),
                )
            )
        return tuple(verdicts)

    def trade_offs(self, priors: PriorTable) -> tuple[TradeOff, ...]:
        """Parameter pairs whose weighted draws move together, strongest first."""
        names = priors.names()
        found: list[TradeOff] = []
        for left_index, left in enumerate(names):
            for right in names[left_index + 1 :]:
                rho = weighted_correlation(
                    self.parameter_values(left), self.parameter_values(right), self.weights()
                )
                if abs(rho) >= TRADE_OFF_CORRELATION:
                    found.append(TradeOff(left, right, rho))
        return tuple(sorted(found, key=lambda item: abs(item.correlation), reverse=True))

    def distinct_parameter_vectors(self) -> int:
        """How many distinct parameter vectors the particle set holds, duplicates collapsed."""
        return len({draw.parameters for draw in self.draws})

    def compare_with(self, other: Ensemble, priors: PriorTable) -> tuple[SeedComparison, ...]:
        """Per parameter, how far two batches' locations sit apart, as a share of the prior range.

        The comparison is the phase's check on its own identifiability verdicts: a parameter whose
        location moves drastically with the sampler's seed was never pinned by the calibration
        window, however narrow its marginal in either batch.
        """
        if self.parameter_names() != other.parameter_names():
            raise EnsembleError("two batches can only be compared on the same parameters")
        mine = self.weights()
        theirs = other.weights()
        comparisons: list[SeedComparison] = []
        for prior in priors:
            first = weighted_quantile(self.parameter_values(prior.name), mine, 0.5)
            second = weighted_quantile(other.parameter_values(prior.name), theirs, 0.5)
            span = prior.high - prior.low
            shift = abs(first - second) / span if span > 0.0 else 1.0
            comparisons.append(
                SeedComparison(
                    name=prior.name,
                    prior_low=prior.low,
                    prior_high=prior.high,
                    first_median=first,
                    second_median=second,
                    shift=shift,
                    reproducible=shift < REPRODUCIBLE_SHIFT,
                )
            )
        return tuple(comparisons)

    def pattern_verdicts(self) -> tuple[PatternVerdict, ...]:
        """Per pattern: how often the ensemble is consistent with it, and how far off when not."""
        verdicts: list[PatternVerdict] = []
        weights = self.weights()
        total = sum(weights) or 1.0
        for index, pattern_id in enumerate(self.pattern_ids):
            values = tuple(row[index] for row in self.scores())
            consistent = sum(
                weight
                for weight, value in zip(weights, values, strict=True)
                if value <= CONSISTENT_SCORE
            )
            verdicts.append(
                PatternVerdict(
                    pattern_id=pattern_id,
                    consistent_share=consistent / total,
                    mean_score=sum(
                        weight * value for weight, value in zip(weights, values, strict=True)
                    )
                    / total,
                    worst_score=max(values),
                )
            )
        return tuple(verdicts)

    def write(self, directory: str | Path) -> tuple[Path, ...]:
        """Write the draws and the manifest into a batch directory."""
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        names = self.parameter_names()
        rows = [
            {
                "draw": index,
                **draw.parameter_map(),
                "weight": draw.weight,
                "parameter_hash": hash_text(
                    canonical_json({name: value for name, value in draw.parameters})
                ),
                **{
                    f"score::{pattern_id}": draw.scores[position]
                    for position, pattern_id in enumerate(self.pattern_ids)
                },
            }
            for index, draw in enumerate(self.draws)
        ]
        frame = pl.DataFrame(rows).select(
            ["draw", *names, "weight", "parameter_hash"]
            + [f"score::{pattern_id}" for pattern_id in self.pattern_ids]
        )
        ensemble_path = target / ENSEMBLE_FILE
        frame.write_parquet(ensemble_path)
        manifest_path = target / MANIFEST_FILE
        manifest_path.write_text(self.provenance.to_json(), encoding="utf-8")
        return ensemble_path, manifest_path

    @classmethod
    def load(cls, directory: str | Path) -> Ensemble:
        """Read a batch back; the draws and the manifest must agree on the parameters."""
        source = Path(directory)
        provenance = Provenance.from_json((source / MANIFEST_FILE).read_text(encoding="utf-8"))
        names = provenance.parameter_names
        pattern_ids = provenance.target_ids
        frame = pl.read_parquet(source / ENSEMBLE_FILE)
        missing = [name for name in names if name not in frame.columns]
        if missing:
            raise EnsembleError(f"ensemble is missing parameter columns: {missing}")
        draws = tuple(
            Draw(
                parameters=tuple((name, float(row[name])) for name in names),
                scores=tuple(float(row[f"score::{pattern_id}"]) for pattern_id in pattern_ids),
                weight=float(row["weight"]),
            )
            for row in frame.iter_rows(named=True)
        )
        return cls(provenance=provenance, draws=draws, pattern_ids=pattern_ids)


def _verdict_for(contraction: float) -> Identification:
    if contraction <= IDENTIFIED_CONTRACTION:
        return Identification.IDENTIFIED
    if contraction >= UNRESOLVED_CONTRACTION:
        return Identification.UNRESOLVED
    return Identification.WEAK


def weighted_quantile(values: Sequence[float], weights: Sequence[float], quantile: float) -> float:
    """The value at a quantile of the weighted distribution, by the usual cumulative rule."""
    if len(values) != len(weights):
        raise EnsembleError("weighted quantile needs one weight per value")
    if not values:
        raise EnsembleError("weighted quantile needs at least one value")
    ordered = sorted(zip(values, weights, strict=True))
    total = sum(weight for _, weight in ordered)
    if total <= 0.0:
        return ordered[len(ordered) // 2][0]
    threshold = quantile * total
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def weighted_correlation(
    left: Sequence[float], right: Sequence[float], weights: Sequence[float]
) -> float:
    """Pearson correlation of two series under the ensemble's weights; 0.0 when flat."""
    if not (len(left) == len(right) == len(weights)):
        raise EnsembleError("weighted correlation needs three equally long series")
    total = sum(weights)
    if total <= 0.0 or not left:
        return 0.0
    mean_left = sum(w * x for x, w in zip(left, weights, strict=True)) / total
    mean_right = sum(w * y for y, w in zip(right, weights, strict=True)) / total
    covariance = sum(
        w * (x - mean_left) * (y - mean_right) for x, y, w in zip(left, right, weights, strict=True)
    )
    variance_left = sum(w * (x - mean_left) ** 2 for x, w in zip(left, weights, strict=True))
    variance_right = sum(w * (y - mean_right) ** 2 for y, w in zip(right, weights, strict=True))
    denominator = (variance_left * variance_right) ** 0.5
    return 0.0 if denominator == 0.0 else covariance / denominator


def build_provenance(
    *,
    batch_id: str,
    root: str | Path,
    priors: PriorTable,
    objective_digest: str,
    pattern_schema_version: str,
    simulation_config_hash: str,
    root_seed: int,
    scenario: dict[str, float | str],
    target_ids: Iterable[str],
    hold_out_ids: Iterable[str],
    particles: int,
    chains: int,
    tolerance: float,
    sampler_seed: int,
) -> Provenance:
    """Assemble the provenance record for one batch, hashing the frozen inputs as it goes."""
    environment = git_provenance(root)
    return Provenance(
        batch_id=batch_id,
        generated_at_utc=datetime.now(UTC).isoformat(timespec="seconds"),
        git_sha=environment.git_sha,
        git_dirty=environment.git_dirty,
        engine_version=engine_version,
        pymc_version=distribution_version("pymc"),
        arviz_version=distribution_version("arviz"),
        evidence_digest=evidence_digest(root),
        evidence_files=frozen_file_digests(root),
        pattern_schema_version=pattern_schema_version,
        prior_digest=prior_digest(
            (prior.name, prior.parameter_set, prior.low, prior.high) for prior in priors
        ),
        objective_digest=objective_digest,
        simulation_config_hash=simulation_config_hash,
        root_seed=root_seed,
        scenario=scenario,
        windows={window.role.value: (window.first_tick, window.last_tick) for window in WINDOWS},
        target_ids=tuple(target_ids),
        hold_out_ids=tuple(hold_out_ids),
        particles=particles,
        chains=chains,
        tolerance=tolerance,
        sampler_seed=sampler_seed,
        parameter_names=priors.names(),
    )
