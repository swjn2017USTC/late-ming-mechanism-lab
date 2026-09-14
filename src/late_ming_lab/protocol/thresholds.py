"""The threshold ensemble: what each governance reading line could be instead, and how it is drawn.

`GovernanceIndicatorParameters` declares eight lines that turn a measurement into a verdict, and
every one of its cards says the same thing: this is a reading rule, not evidence. A report that
counts crossed lines without saying what would happen at another line has hidden its own choice, so
the phase freezes the alternatives first, in `data/protocol/threshold-ensemble-v2.yaml`:

```text
entry      one per line: the live value, the band it could be read over, what the band rests on,
           what kind of choice the line is, and how the band is sampled
grid       the band is read at `points` evenly spaced values; the band is symmetric about the live
           line with an odd count, so the line the model actually runs is always one member
uniform    the band is read at `draws` independently drawn values, which privileges no end of it
design     the product over the eight entries: 5^4 grid points times 3^4 uniform draws, 50,625
           members, each one a full parameter set a run could have been read at
```

Everything here is deterministic from the seed and the file: no wall clock, no ambient state, and no
shared global generator (:func:`sample_draws` makes its own `numpy` generator from the seed it is
given). Two callers with the same file and the same seed get the same draws, in the same order, and
that order is part of the run's provenance: the uniform rules draw in entry order and the design
enumerates in entry order, so reordering the entries changes the ensemble rather than its
presentation.

The refusals are the point of the loader, and they are the same ones the protocol loader makes: a
file whose schema is not this one, an entry for a line the parameter set does not have, a line left
out, an inverted or zero-width band, a live value outside its band, and a sampling rule too thin to
be a band. Entry-level refusals surface as pydantic `ValidationError` (whose message names the
entry); file-level ones raise :class:`ThresholdEnsembleError`. Nothing here widens a band, and
nothing reads a band off the record: what each band rests on is stated in the file per line.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Final, Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from late_ming_lab.core.hashing import canonical_json, hash_text
from late_ming_lab.evidence.parameters import (
    GovernanceIndicatorParameters,
    core_default_governance_indicators,
)
from late_ming_lab.protocol.schema import ThresholdIdentity

ENSEMBLE_SCHEMA_VERSION: Final[str] = "threshold-ensemble-v2"
ENSEMBLE_PATH: Final[str] = "data/protocol/threshold-ensemble-v2.yaml"

#: The direction the crossing is computed in, exactly as ``analysis/governance.py`` reads it:
#: ``below-is-failure`` crosses when the measurement is under the line, ``above-is-failure`` when
#: it is over it.
CrossingDirection = Literal["below-is-failure", "above-is-failure"]

#: The live parameter set's fields that are not reading lines: the set's own bookkeeping.
NON_LINE_FIELDS: Final[frozenset[str]] = frozenset({"version", "provenance"})

#: The reading lines the ensemble must carry, in the parameter set's own declaration order. Read
#: from the parameter set rather than written out again, so the two cannot drift apart.
LINE_FIELDS: Final[tuple[str, ...]] = tuple(
    name for name in GovernanceIndicatorParameters.model_fields if name not in NON_LINE_FIELDS
)

#: The smallest band a grid can be read over: one point is a declaration, not an ensemble.
MIN_GRID_POINTS: Final[int] = 2


class ThresholdEnsembleError(ValueError):
    """Raised when the ensemble cannot be read, or when a draw cannot honour it."""


class GridRule(BaseModel):
    """The band is read at evenly spaced values, from its low bound to its high one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["grid"] = "grid"
    points: int = Field(ge=MIN_GRID_POINTS)


class UniformRule(BaseModel):
    """The band is read at independently drawn values across its whole width."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["uniform"] = "uniform"
    draws: int = Field(ge=1)


#: How one line's band is sampled. A grid is enumerable and a uniform rule is drawn; both are
#: finite, because a report has to recompute the same distribution twice to be checkable.
SamplingRule = Annotated[GridRule | UniformRule, Field(discriminator="kind")]


class ThresholdEntry(BaseModel):
    """One reading line: its live value, its band, and what that band rests on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", description="the parameter field name")
    indicator: str = Field(
        pattern=r"^[a-z][a-z0-9_]*$",
        description="the id analysis/governance.py reports this line's row under",
    )
    direction: CrossingDirection
    value: float = Field(description="the live line, from core_default_governance_indicators()")
    identity: ThresholdIdentity = Field(
        description="read from the line's own card: a ledger claim or only an assumption"
    )
    range: tuple[float, float]
    source: str = Field(min_length=1, description="what the band rests on, with a locator")
    sampling: SamplingRule
    note: str = Field(min_length=1)

    @model_validator(mode="after")
    def _range_brackets_the_value(self) -> ThresholdEntry:
        low, high = self.range
        if low > high:
            raise ThresholdEnsembleError(f"{self.id}: threshold range [{low}, {high}] is inverted")
        if low == high:
            raise ThresholdEnsembleError(
                f"{self.id}: the range [{low}, {high}] is a single point; a line sampled there "
                "would be the declared line under another name"
            )
        if not low <= self.value <= high:
            raise ThresholdEnsembleError(
                f"{self.id}: the live line {self.value} lies outside its range "
                f"[{low}, {high}], so the ensemble would never read the line the model runs"
            )
        return self


class ThresholdEnsemble(BaseModel):
    """The eight reading lines with their bands, and the rule that samples each one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["threshold-ensemble-v2"] = "threshold-ensemble-v2"
    version: str = Field(min_length=1)
    frozen_on: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    entries: tuple[ThresholdEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ensemble_covers_every_line(self) -> ThresholdEnsemble:
        ids = [entry.id for entry in self.entries]
        if len(set(ids)) != len(ids):
            raise ThresholdEnsembleError("threshold ensemble entry ids must be unique")
        declared = set(LINE_FIELDS)
        missing = [name for name in LINE_FIELDS if name not in set(ids)]
        unread = [name for name in ids if name not in declared]
        if missing or unread:
            faults = [
                f"the ensemble carries one entry per reading line ({', '.join(LINE_FIELDS)}) and "
                "nothing else"
            ]
            if unread:
                faults.append(f"{', '.join(unread)} is not a reading line")
            if missing:
                faults.append(
                    f"{', '.join(missing)} has no entry, and a line left out is the one nobody "
                    "can move"
                )
            raise ThresholdEnsembleError("; ".join(faults))
        return self

    @property
    def ids(self) -> tuple[str, ...]:
        """The line ids, in the file's declaration order, which is the design's order."""
        return tuple(entry.id for entry in self.entries)

    @property
    def total_draws(self) -> int:
        """How many members the design holds: the product over entries of each line's rule."""
        total = 1
        for entry in self.entries:
            total *= _rule_size(entry.sampling)
        return total

    @property
    def indicator_ids(self) -> tuple[str, ...]:
        """The analysis ids of the lines, in the same order as `ids`."""
        return tuple(entry.indicator for entry in self.entries)

    def by_indicator(self, draw: Mapping[str, float]) -> dict[str, float]:
        """One member keyed by indicator id, which is how a measured run carries its values.

        A draw is keyed by the parameter field name, so `to_parameters` can build the parameter
        set; a run's measurements are keyed by the id the analysis reports them under. Crossing
        a line against a measurement needs the second keying, and translating here keeps one place
        responsible for the correspondence.
        """
        missing = [entry.id for entry in self.entries if entry.id not in draw]
        if missing:
            raise ThresholdEnsembleError(
                f"the draw does not carry {', '.join(sorted(missing))}; a partial member would be "
                "crossed as if those lines did not exist"
            )
        return {entry.indicator: float(draw[entry.id]) for entry in self.entries}

    def digest(self) -> str:
        """The ensemble's identity: its content, canonicalised, with no clock and no seed in it.

        A robustness report is only comparable with another one if both name which lines were moved
        and how far, so the report records this digest beside the ProtocolFreeze digest that says
        which definitions were read.
        """
        return hash_text(canonical_json(self.model_dump(mode="json")))


def load_ensemble(root: str | Path, *, path: str = ENSEMBLE_PATH) -> ThresholdEnsemble:
    """Read the frozen threshold ensemble, refusing a file of another schema or a broken band."""
    source = Path(root) / path
    if not source.is_file():
        raise ThresholdEnsembleError(
            f"{source} is missing; the threshold ensemble is frozen there, beside the protocol"
        )
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ThresholdEnsembleError(f"{source} is not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise ThresholdEnsembleError(f"{source} must hold a mapping, not {type(raw).__name__}")
    if raw.get("schema_version") != ENSEMBLE_SCHEMA_VERSION:
        raise ThresholdEnsembleError(
            f"{source} declares schema {raw.get('schema_version')!r}, not "
            f"{ENSEMBLE_SCHEMA_VERSION!r}"
        )
    return ThresholdEnsemble.model_validate(json.loads(json.dumps(raw)))


def sample_draws(
    ensemble: ThresholdEnsemble, *, draws: int | None = None, seed: int
) -> tuple[dict[str, float], ...]:
    """The ensemble's parameter draws, deterministic in ``seed`` and in the declared rules.

    ``draws`` is ``None`` for the whole design, in design order, or a count for that many members
    chosen without replacement from it (returned in design order as well). A count larger than the
    design is refused rather than padded: the ensemble is the file's, and a sample cannot invent
    members the rules do not offer.
    """
    generator = np.random.default_rng(seed)
    names = ensemble.ids
    columns = tuple(_line_values(entry, generator) for entry in ensemble.entries)
    total = ensemble.total_draws
    if draws is None:
        return tuple(_draw(names, columns, index) for index in range(total))
    if not 1 <= draws <= total:
        raise ThresholdEnsembleError(
            f"{draws} ensemble members were asked for and the design holds {total}; the design is "
            "the product over entries of each line's rule"
        )
    picked = sorted(int(index) for index in generator.choice(total, size=draws, replace=False))
    return tuple(_draw(names, columns, index) for index in picked)


def to_parameters(
    draw: Mapping[str, float], *, base: GovernanceIndicatorParameters | None = None
) -> GovernanceIndicatorParameters:
    """The live parameter set with the drawn lines in place of the declared ones.

    The base set's provenance is carried through unchanged, because a drawn line is the same kind
    of claim as the line it replaces, and the result is validated: a draw outside a field's own
    bounds, or a key that is not a reading line, is refused instead of returned.
    """
    parameters = core_default_governance_indicators() if base is None else base
    return GovernanceIndicatorParameters.model_validate({**parameters.model_dump(), **draw})


def _rule_size(rule: SamplingRule) -> int:
    """How many values one line contributes to the design."""
    return rule.points if isinstance(rule, GridRule) else rule.draws


def _line_values(entry: ThresholdEntry, generator: np.random.Generator) -> tuple[float, ...]:
    """The values one line contributes to the design, in the order the design enumerates them."""
    rule = entry.sampling
    low, high = entry.range
    if isinstance(rule, GridRule):
        return tuple(float(value) for value in np.linspace(low, high, rule.points))
    return tuple(float(value) for value in generator.uniform(low, high, size=rule.draws))


def _draw(
    names: tuple[str, ...], columns: tuple[tuple[float, ...], ...], index: int
) -> dict[str, float]:
    """One member of the design, read off at a flat index; the last line's rule varies fastest."""
    offsets = [0] * len(columns)
    remainder = index
    for position in range(len(columns) - 1, -1, -1):
        remainder, offsets[position] = divmod(remainder, len(columns[position]))
    return {
        name: column[offset] for name, column, offset in zip(names, columns, offsets, strict=True)
    }
