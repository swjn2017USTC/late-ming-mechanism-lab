"""The model-comparison register: the alternative structures V2-P04 and V2-P05 will test.

V2-P03 freezes what an outcome *is* before a result is read; this module holds the register that
freezes what a *comparison* is before the arms that would settle it are built. Each entry in
``data/protocol/model-comparison-register-v2.yaml`` says:

```text
v1_evidence               the V1 finding it responds to, with the artifact, pattern or card it is
                          read from
candidate_structures      the named alternatives the phase will run against each other
prior_expectation         what the project expects before the arms are run, and why
discriminating_observables primary outcomes of the frozen protocol that can separate the candidates
falsifier                 the observation that would reject the preferred structure
summary_statistic         the quantity a reader looks at to see which candidate won
```

Two refusals keep the register honest. An entry whose discriminating observable is not a primary
outcome of the frozen protocol is refused, so the register cannot invent a reading surface after the
results are in; and an entry that defers its own discriminator instead of declaring one is refused,
because such an entry pre-registers nothing. The required themes are a module constant and every one
of them must be an entry id, so deleting an entry from the file fails the load rather than quietly
shrinking the coverage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from late_ming_lab.protocol.schema import ValidationProtocol, load_protocol

#: The register's own schema, and where it is written.
RegisterSchemaVersion = Literal["model-comparison-register-v2"]
REGISTER_SCHEMA_VERSION: Final[RegisterSchemaVersion] = "model-comparison-register-v2"
REGISTER_PATH: Final[str] = "data/protocol/model-comparison-register-v2.yaml"

#: The two phases that may own an entry. V2-P04 diagnoses the failed hold-out mechanisms; V2-P05
#: builds the mechanisms V1 left unbuilt or rejected. No other phase pre-registers a comparison
#: here.
Phase = Literal["V2-P04", "V2-P05"]

#: The discriminators the register must carry, named by the entry that carries them. A theme is a
#: discriminator, not a topic: each one is answerable by running the candidate structures it names
#: and reading the observables the frozen protocol already defines. Deleting an entry deletes its
#: theme, and the register stops loading.
REQUIRED_COVERAGE: Final[tuple[str, ...]] = (
    "price-formation-alternatives",
    "relief-bottleneck-alternatives",
    "migration-structure-alternatives",
    "climate-forcing-alternatives",
    "famine-mortality-variant",
    "elite-mediation-vs-accumulation",
    "band-consolidation-chain",
    "arrears-persistence-vs-ratchet",
)

#: Phrases that defer a comparison instead of declaring one. Case-insensitive substring match over
#: every prose field, as ``synthesis.schema`` checks the mechanism cards: this is exactly where an
#: entry that names no candidate and no rejecting observation would hide.
VAGUE_PHRASES: Final[tuple[str, ...]] = (
    "more research is needed",
    "further research is needed",
    "needs more research",
    "requires further study",
    "remains to be seen",
    "remains unclear",
    "to be determined",
    "cannot be determined",
    "not enough information",
    "tbd",
)


class ComparisonError(ValueError):
    """Raised when the comparison register cannot be read, or does not hold together."""


class ComparisonEntry(BaseModel):
    """One pre-registered discriminator: the V1 finding, the candidates, and what settles them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$", max_length=64)
    phase: Phase
    title: str = Field(min_length=1, max_length=160)
    v1_evidence: str = Field(
        min_length=1,
        max_length=1200,
        description="the V1 finding this entry responds to, citing the artifact path or card id",
    )
    candidate_structures: tuple[str, ...] = Field(
        min_length=2,
        description="the named alternatives the phase runs against each other; two are needed",
    )
    prior_expectation: str = Field(min_length=1, max_length=1000)
    discriminating_observables: tuple[str, ...] = Field(
        min_length=1, description="primary outcome ids of the frozen protocol that separate them"
    )
    falsifier: str = Field(min_length=1, max_length=1000)
    summary_statistic: str = Field(min_length=1, max_length=800)

    @model_validator(mode="after")
    def _the_entry_states_its_discriminator(self) -> ComparisonEntry:
        for structure in self.candidate_structures:
            if not structure.strip():
                raise ComparisonError(
                    f"{self.id}: a blank candidate structure names no alternative"
                )
        if len(set(self.candidate_structures)) != len(self.candidate_structures):
            raise ComparisonError(f"{self.id}: the same candidate structure is listed twice")
        prose = self.prose().lower()
        for phrase in VAGUE_PHRASES:
            if phrase in prose:
                raise ComparisonError(
                    f"{self.id}: {phrase!r} defers the comparison instead of declaring one; name "
                    "the candidates and the observation that would reject one"
                )
        return self

    def prose(self) -> str:
        """Every prose field joined, for the vagueness check."""
        return " ".join(
            (
                self.title,
                self.v1_evidence,
                *self.candidate_structures,
                self.prior_expectation,
                self.falsifier,
                self.summary_statistic,
            )
        )


class ComparisonRegister(BaseModel):
    """Every pre-registered discriminator, with the coverage the two phases require."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: RegisterSchemaVersion = REGISTER_SCHEMA_VERSION
    version: str = Field(min_length=1)
    frozen_on: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    entries: tuple[ComparisonEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _entry_ids_are_unique(self) -> ComparisonRegister:
        ids = [entry.id for entry in self.entries]
        if len(set(ids)) != len(ids):
            raise ComparisonError("entry ids must be unique")
        return self

    @model_validator(mode="after")
    def _required_coverage_is_present(self) -> ComparisonRegister:
        declared = {entry.id for entry in self.entries}
        missing = [theme for theme in REQUIRED_COVERAGE if theme not in declared]
        if missing:
            raise ComparisonError(
                f"the register does not pre-register {', '.join(missing)}; the required coverage "
                f"is {', '.join(REQUIRED_COVERAGE)}"
            )
        return self


def load_register(
    root: str | Path, *, protocol: ValidationProtocol | None = None
) -> ComparisonRegister:
    """Read the register, refusing an entry the frozen protocol could not score.

    ``protocol`` defaults to the frozen protocol read from ``root``. ``root`` is the repository
    root, the same argument :func:`late_ming_lab.protocol.schema.load_protocol` takes.
    """
    source = Path(root) / REGISTER_PATH
    if not source.is_file():
        raise ComparisonError(
            f"{source} is missing; the comparison register is pre-registered there"
        )
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ComparisonError(f"{source} is not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise ComparisonError(f"{source} must hold a mapping, not {type(raw).__name__}")
    if raw.get("schema_version") != REGISTER_SCHEMA_VERSION:
        raise ComparisonError(
            f"{source} declares schema {raw.get('schema_version')!r}, not "
            f"{REGISTER_SCHEMA_VERSION!r}"
        )
    register = ComparisonRegister.model_validate(json.loads(json.dumps(raw)))
    frozen = protocol if protocol is not None else load_protocol(root)
    known = {outcome.id for outcome in frozen.primary_outcomes}
    for entry in register.entries:
        unknown = sorted(set(entry.discriminating_observables) - known)
        if unknown:
            raise ComparisonError(
                f"{entry.id}: {', '.join(unknown)} are not primary outcomes of the frozen protocol "
                f"{frozen.version!r}"
            )
    return register


def entries_for(register: ComparisonRegister, phase: Phase) -> tuple[ComparisonEntry, ...]:
    """The entries pre-registered for one phase, in the order the file lists them."""
    return tuple(entry for entry in register.entries if entry.phase == phase)


def by_id(register: ComparisonRegister, entry_id: str) -> ComparisonEntry:
    """One entry by id; an id the register does not hold is refused rather than returned as None."""
    for entry in register.entries:
        if entry.id == entry_id:
            return entry
    raise KeyError(f"no pre-registered entry {entry_id!r}")
