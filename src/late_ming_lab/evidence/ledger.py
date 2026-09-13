"""The evidence ledger and the historical pattern registry.

Two records that keep the phase honest about the difference between *what the sources say* and
*what the model does*.

```text
evidence ledger     one entry per claim: what a source reports, under which interpretation, and
                    which model element (parameter or rule) rests on it
historical patterns one entry per pattern: a sequence the historical record shows, its window and
                    geography, the sources for it, and the observable signature the model would
                    have to reproduce for a pattern-oriented comparison to be possible
```

The ledger's `assertion` field is deliberately narrow: it is what the cited source states, not what
we want the model to do. Where a source supports a *form* (a mechanism existed) without a
magnitude, the entry says so, and the parameter card that leans on it remains theoretically
assumed. Where nothing in the registry supports a claim, the entry does not exist — the gap is
recorded in the coverage report instead, which is the point of having one.

Patterns are **not calibration targets yet**. Each carries `calibration_role`:

```text
hold_out          kept out of any future fit so it can falsify the model afterwards
target            a candidate fitting target, once P09 decides how to score it
constraint        a fact the model must not contradict (an inequality or a direction)
not_calibrated    recorded for orientation only
```

Grading a pattern means grading the *record* of the pattern, not our ability to reproduce it; that
second question is P09's and P13's.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from late_ming_lab.evidence.cards import SupportClass
from late_ming_lab.evidence.grades import SOURCED_GRADES, EvidenceGrade
from late_ming_lab.evidence.registry import EVIDENCE_CLUSTERS

LEDGER_SCHEMA_VERSION: Final[str] = "evidence-ledger-v1"
LEDGER_GLOB: Final[str] = "data/normalized/evidence_ledger*.yaml"
PATTERN_SCHEMA_VERSION: Final[str] = "historical-patterns-v1"
PATTERN_GLOB: Final[str] = "data/historical_patterns/*.yaml"


class ClaimStrength(StrEnum):
    """How far a ledger entry can carry a model rule."""

    MAGNITUDE = "magnitude"  # the source states a quantity the model can use as a value
    FORM = "form"  # the source establishes that the mechanism existed, not its size
    DIRECTION = "direction"  # the source establishes a sign or an ordering, not a size
    CONTEXT = "context"  # background that frames a rule without constraining it


class CalibrationRole(StrEnum):
    """What a pattern is for, decided now so P09 cannot quietly fit everything."""

    HOLD_OUT = "hold-out"
    TARGET = "target"
    CONSTRAINT = "constraint"
    NOT_CALIBRATED = "not-calibrated"


class EvidenceEntry(BaseModel):
    """One claim, its sources, and what in the model depends on it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=128)
    cluster: str
    assertion: str = Field(
        min_length=1,
        max_length=1000,
        description="what the cited sources state — never what the model is expected to produce",
    )
    interpretation: str = Field(
        min_length=1,
        max_length=1000,
        description="the step from what the source says to what the model may use, stated openly",
    )
    strength: ClaimStrength
    evidence_grade: EvidenceGrade
    sources: tuple[str, ...] = Field(min_length=1)
    locators: tuple[str, ...] = Field(
        min_length=1, description="where inside each source the claim is found"
    )
    supports_parameters: tuple[str, ...] = ()
    supports_rules: tuple[str, ...] = ()
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _entry_is_checkable(self) -> EvidenceEntry:
        if self.cluster not in EVIDENCE_CLUSTERS:
            raise ValueError(f"{self.id}: unknown evidence cluster {self.cluster!r}")
        if len(self.locators) != len(self.sources):
            raise ValueError(
                f"{self.id}: {len(self.sources)} sources but {len(self.locators)} locators; "
                "every source needs its own locator"
            )
        if self.evidence_grade in SOURCED_GRADES and not self.sources:
            raise ValueError(f"{self.id}: grade {self.evidence_grade.value} needs sources")
        return self

    @property
    def carries_a_magnitude(self) -> bool:
        return self.strength is ClaimStrength.MAGNITUDE


class EvidenceLedger:
    """Every recorded claim, indexed by id and groupable by cluster."""

    def __init__(self, entries: tuple[EvidenceEntry, ...], *, schema_version: str) -> None:
        if schema_version != LEDGER_SCHEMA_VERSION:
            raise ValueError(f"ledger schema {schema_version!r} is not {LEDGER_SCHEMA_VERSION!r}")
        ordered = tuple(sorted(entries, key=lambda entry: entry.id))
        ids = [entry.id for entry in ordered]
        duplicates = sorted({entry_id for entry_id in ids if ids.count(entry_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate ledger ids: {', '.join(duplicates)}")
        self._entries = ordered
        self._by_id = {entry.id: entry for entry in ordered}
        self._schema_version = schema_version

    def __iter__(self) -> Iterator[EvidenceEntry]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> tuple[EvidenceEntry, ...]:
        return self._entries

    @property
    def schema_version(self) -> str:
        return self._schema_version

    def require(self, entry_id: str) -> EvidenceEntry:
        try:
            return self._by_id[entry_id]
        except KeyError as error:
            raise KeyError(f"no ledger entry {entry_id!r}") from error

    def by_cluster(self, cluster: str) -> tuple[EvidenceEntry, ...]:
        return tuple(entry for entry in self._entries if entry.cluster == cluster)

    def clusters_without_entries(self) -> tuple[str, ...]:
        return tuple(cluster for cluster in EVIDENCE_CLUSTERS if not self.by_cluster(cluster))

    def supporting(self, parameter_set: str, parameter: str) -> tuple[EvidenceEntry, ...]:
        """Entries that claim to support one parameter, named as ``Set.field``."""
        key = f"{parameter_set}.{parameter}"
        return tuple(entry for entry in self._entries if key in entry.supports_parameters)


RULE_CLAIMS_SCHEMA_VERSION: Final[str] = "rule-claims-v1"
RULE_CLAIMS_GLOB: Final[str] = "data/normalized/rule_claims*.yaml"


class RuleClaim(BaseModel):
    """One simulation rule, its support class, and the evidence that carries it.

    The phase requires that *every* rule can be related to evidence-backed, theoretically-assumed
    or exploratory. This record is that relation: a rule with no ledger entry behind it must be
    declared exploratory, and a rule declared evidence-backed must cite entries.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=128)
    name: str = Field(min_length=1, max_length=200)
    module: str = Field(
        min_length=1,
        max_length=200,
        description="where the rule lives in the code, e.g. 'systems/migration.py'",
    )
    rule_version: str | None = Field(
        default=None, max_length=64, description="the rule version string the code records"
    )
    statement: str = Field(
        min_length=1, max_length=1000, description="what the rule computes, in one or two sentences"
    )
    support_class: SupportClass
    parameters: tuple[str, ...] = ()
    ledger_entries: tuple[str, ...] = ()
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _rule_is_related_to_evidence(self) -> RuleClaim:
        if self.support_class is SupportClass.EVIDENCE_BACKED and not self.ledger_entries:
            raise ValueError(
                f"{self.id}: a rule cannot be evidence-backed without citing ledger entries"
            )
        return self


class RuleClaimSet:
    """Every declared rule, indexed by id."""

    def __init__(self, rules: tuple[RuleClaim, ...], *, schema_version: str) -> None:
        if schema_version != RULE_CLAIMS_SCHEMA_VERSION:
            raise ValueError(
                f"rule-claims schema {schema_version!r} is not {RULE_CLAIMS_SCHEMA_VERSION!r}"
            )
        ordered = tuple(sorted(rules, key=lambda rule: rule.id))
        ids = [rule.id for rule in ordered]
        duplicates = sorted({rule_id for rule_id in ids if ids.count(rule_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate rule ids: {', '.join(duplicates)}")
        self._rules = ordered
        self._by_id = {rule.id: rule for rule in ordered}
        self._schema_version = schema_version

    def __iter__(self) -> Iterator[RuleClaim]:
        return iter(self._rules)

    def __len__(self) -> int:
        return len(self._rules)

    @property
    def rules(self) -> tuple[RuleClaim, ...]:
        return self._rules

    @property
    def schema_version(self) -> str:
        return self._schema_version

    def require(self, rule_id: str) -> RuleClaim:
        try:
            return self._by_id[rule_id]
        except KeyError as error:
            raise KeyError(f"no declared rule {rule_id!r}") from error

    def by_support_class(self, support: SupportClass) -> tuple[RuleClaim, ...]:
        return tuple(rule for rule in self._rules if rule.support_class is support)

    def ids(self) -> frozenset[str]:
        return frozenset(self._by_id)


def load_rule_claims(root: str | Path, *, glob: str = RULE_CLAIMS_GLOB) -> RuleClaimSet:
    """Read the rule-claim file(s) under ``root`` and return the validated set."""
    directory = Path(root)
    files = sorted(directory.glob(glob))
    if not files:
        raise FileNotFoundError(f"no rule-claims file matched {glob!r} under {directory}")
    rules: list[RuleClaim] = []
    schema_versions: set[str] = set()
    for path in files:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "rules" not in payload:
            raise ValueError(f"{path}: rule-claim files must hold a 'rules' list")
        schema_versions.add(str(payload.get("schema_version", "")))
        for raw in payload["rules"]:
            rules.append(RuleClaim.model_validate(raw))
    if len(schema_versions) != 1:
        raise ValueError(f"rule files disagree on schema_version: {sorted(schema_versions)}")
    return RuleClaimSet(tuple(rules), schema_version=schema_versions.pop())


class ObservableSignature(BaseModel):
    """What the model would have to show for this pattern to be comparable at all."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    quantity: str = Field(
        min_length=1,
        max_length=200,
        description="a quantity the model already reports, named as analysis names it",
    )
    expected: str = Field(
        min_length=1,
        max_length=500,
        description="the shape the historical record shows: direction, ordering, timing or bound",
    )
    scoring: str = Field(
        min_length=1,
        max_length=300,
        description="how P09 could score it without fitting the model to the pattern",
    )


class HistoricalPattern(BaseModel):
    """A sequence the record shows, recorded for pattern-oriented comparison later."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=128)
    cluster: str
    name: str = Field(min_length=1, max_length=200)
    statement: str = Field(
        min_length=1,
        max_length=1500,
        description="what happened, in the record's own terms, with the uncertainty it carries",
    )
    window: str = Field(min_length=1, max_length=128, description="e.g. '1628-1631'")
    geography: str = Field(min_length=1, max_length=300)
    evidence_grade: EvidenceGrade
    sources: tuple[str, ...] = Field(min_length=1)
    locators: tuple[str, ...] = Field(min_length=1)
    calibration_role: CalibrationRole
    signatures: tuple[ObservableSignature, ...] = Field(min_length=1)
    falsifiers: tuple[str, ...] = Field(
        default=(),
        description="observations that would count against the model having captured the pattern",
    )

    @model_validator(mode="after")
    def _pattern_is_checkable(self) -> HistoricalPattern:
        if self.cluster not in EVIDENCE_CLUSTERS:
            raise ValueError(f"{self.id}: unknown evidence cluster {self.cluster!r}")
        if len(self.locators) != len(self.sources):
            raise ValueError(
                f"{self.id}: {len(self.sources)} sources but {len(self.locators)} locators"
            )
        if self.evidence_grade in SOURCED_GRADES and not self.sources:
            raise ValueError(f"{self.id}: grade {self.evidence_grade.value} needs sources")
        return self


class PatternRegistry:
    """Every recorded pattern, indexed by id."""

    def __init__(self, patterns: tuple[HistoricalPattern, ...], *, schema_version: str) -> None:
        if schema_version != PATTERN_SCHEMA_VERSION:
            raise ValueError(f"pattern schema {schema_version!r} is not {PATTERN_SCHEMA_VERSION!r}")
        ordered = tuple(sorted(patterns, key=lambda pattern: pattern.id))
        ids = [pattern.id for pattern in ordered]
        duplicates = sorted({pattern_id for pattern_id in ids if ids.count(pattern_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate pattern ids: {', '.join(duplicates)}")
        self._patterns = ordered
        self._by_id = {pattern.id: pattern for pattern in ordered}
        self._schema_version = schema_version

    def __iter__(self) -> Iterator[HistoricalPattern]:
        return iter(self._patterns)

    def __len__(self) -> int:
        return len(self._patterns)

    @property
    def patterns(self) -> tuple[HistoricalPattern, ...]:
        return self._patterns

    @property
    def schema_version(self) -> str:
        return self._schema_version

    def require(self, pattern_id: str) -> HistoricalPattern:
        try:
            return self._by_id[pattern_id]
        except KeyError as error:
            raise KeyError(f"no recorded pattern {pattern_id!r}") from error

    def by_cluster(self, cluster: str) -> tuple[HistoricalPattern, ...]:
        return tuple(pattern for pattern in self._patterns if pattern.cluster == cluster)

    def by_role(self, role: CalibrationRole) -> tuple[HistoricalPattern, ...]:
        return tuple(pattern for pattern in self._patterns if pattern.calibration_role is role)

    def clusters_without_patterns(self) -> tuple[str, ...]:
        return tuple(cluster for cluster in EVIDENCE_CLUSTERS if not self.by_cluster(cluster))

    @property
    def hold_out_ids(self) -> tuple[str, ...]:
        return tuple(pattern.id for pattern in self.by_role(CalibrationRole.HOLD_OUT))


def load_ledger(root: str | Path, *, glob: str = LEDGER_GLOB) -> EvidenceLedger:
    """Read the ledger file(s) under ``root`` and return the validated ledger."""
    directory = Path(root)
    files = sorted(directory.glob(glob))
    if not files:
        raise FileNotFoundError(f"no evidence ledger matched {glob!r} under {directory}")
    entries: list[EvidenceEntry] = []
    schema_versions: set[str] = set()
    for path in files:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "entries" not in payload:
            raise ValueError(f"{path}: ledger files must hold an 'entries' list")
        schema_versions.add(str(payload.get("schema_version", "")))
        for raw in payload["entries"]:
            entries.append(EvidenceEntry.model_validate(raw))
    if len(schema_versions) != 1:
        raise ValueError(f"ledger files disagree on schema_version: {sorted(schema_versions)}")
    return EvidenceLedger(tuple(entries), schema_version=schema_versions.pop())


def load_patterns(root: str | Path, *, glob: str = PATTERN_GLOB) -> PatternRegistry:
    """Read every pattern file under ``root`` and return the validated registry."""
    directory = Path(root)
    files = sorted(directory.glob(glob))
    if not files:
        raise FileNotFoundError(f"no pattern files matched {glob!r} under {directory}")
    patterns: list[HistoricalPattern] = []
    schema_versions: set[str] = set()
    for path in files:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "patterns" not in payload:
            raise ValueError(f"{path}: pattern files must hold a 'patterns' list")
        schema_versions.add(str(payload.get("schema_version", "")))
        for raw in payload["patterns"]:
            patterns.append(HistoricalPattern.model_validate(raw))
    if len(schema_versions) != 1:
        raise ValueError(f"pattern files disagree on schema_version: {sorted(schema_versions)}")
    return PatternRegistry(tuple(patterns), schema_version=schema_versions.pop())
