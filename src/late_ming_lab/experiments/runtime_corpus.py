"""The runtime observation corpus: one observation per declared role and trigger, audited anonymous.

The phase's first gate-open task is a corpus that covers the roles, the actions and the triggers
the decision layer can face, with an audit for what a prompt must never carry — a place, a
dynasty, a person, a date, or anything telling the actor where it is in the historical sequence.

Two rules the module keeps:

```text
the corpus is derived   every observation is built from the declared roles and triggers, so a
                        trigger added to the layer without a corpus entry is a failing test
every prompt is audited `render_prompt` audits each one, and the corpus audit re-runs that
                        over the whole set and records the result
```

The recording pass sends the corpus to the live policy one observation at a time, sanitises what
comes back, and stores it as a fixture keyed by prompt hash. Nothing here reads, prints or stores a
credential, and nothing here lets a model's answer change a simulation state: the corpus is the
input side, the fixtures are the output side, and the arm that consumes them replays.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

import polars as pl

from late_ming_lab.policies.base import (
    ROLE_ACTIONS,
    ActorRole,
    InstitutionalAction,
    ObservationRejectedError,
    PolicyObservation,
    PolicyRecord,
    audit_prompt,
    render_prompt,
)
from late_ming_lab.policies.institutional import default_triggers
from late_ming_lab.policies.recording import RecordedExchange, sanitize_response
from late_ming_lab.storage.tables import write_table

#: The readings every corpus observation carries. They are named quantities of the model, with no
#: unit, no place and no date: the actor sees the shape of its situation and not the year.
CORPUS_MEASURES: Final[tuple[tuple[str, float], ...]] = (
    ("armed_share_of_adults", 0.006),
    ("largest_band_share", 0.33),
    ("out_migration_share", 0.004),
    ("receipts_over_quota", 0.27),
    ("tax_arrears_months", 7.2),
    ("unmet_need_share", 0.18),
    ("food_months_of_cover", 2.4),
    ("garrison_pay_shortfall", 0.41),
)

#: The regions the corpus uses: opaque labels, never a place name. A corpus that carried a real
#: region would leak the geography the boundary exists to keep out of the prompt.
CORPUS_REGIONS: Final[tuple[str, ...]] = ("R1", "R2", "R3", "R4")


class CorpusError(RuntimeError):
    """Raised when the corpus cannot be built or a prompt fails its audit."""


@runtime_checkable
class Policy(Protocol):
    """What the recording pass needs from a decision policy: an answer, a trace, and its id."""

    @property
    def model_id(self) -> str: ...

    def choose_action(
        self, observation: PolicyObservation, action_space: Iterable[InstitutionalAction]
    ) -> object: ...

    def last_record(self) -> PolicyRecord | None: ...


@dataclass(frozen=True, slots=True)
class CorpusEntry:
    """One audited observation: the role and trigger it stands for, and its anonymous prompt."""

    role: ActorRole
    trigger: str
    observation: PolicyObservation
    prompt: str
    prompt_hash: str
    action_space: tuple[str, ...]

    def record(self) -> dict[str, object]:
        return {
            "role": self.role.value,
            "trigger": self.trigger,
            "actor": self.observation.actor,
            "region": self.observation.region,
            "measures": dict(self.observation.measures),
            "actions": list(self.action_space),
            "prompt_hash": self.prompt_hash,
        }


def corpus() -> tuple[CorpusEntry, ...]:
    """One observation per declared trigger, plus one per role for the roles no trigger names.

    The trigger set is read from the layer rather than restated: a trigger that exists and has no
    corpus entry would mean the layer can ask a question the corpus never exercises, which is the
    gap this function exists to make impossible.
    """
    from late_ming_lab.core.hashing import hash_text

    entries: list[CorpusEntry] = []
    seen_roles: set[ActorRole] = set()
    for index, trigger in enumerate(default_triggers()):
        measures = _measures_firing(trigger.measure, trigger.direction, trigger.threshold)
        observation = PolicyObservation(
            actor=f"SEAT-{trigger.role.value.upper()}-{index}",
            role=trigger.role,
            region=CORPUS_REGIONS[index % len(CORPUS_REGIONS)],
            tick=48 + 12 * index,
            measures=measures,
            action_space=ROLE_ACTIONS[trigger.role],
        )
        entries.append(_audited(observation, trigger=trigger.name))
        seen_roles.add(trigger.role)
    for role in ActorRole:
        if role in seen_roles:
            continue
        observation = PolicyObservation(
            actor=f"SEAT-{role.value.upper()}-BASE",
            role=role,
            region=CORPUS_REGIONS[0],
            tick=48,
            measures=CORPUS_MEASURES,
            action_space=ROLE_ACTIONS[role],
        )
        entries.append(_audited(observation, trigger=f"{role.value}-baseline"))
    del hash_text
    return tuple(entries)


def _measures_firing(
    measure: str, direction: str, threshold: float
) -> tuple[tuple[str, float], ...]:
    """The corpus readings with one measure pushed past its trigger, the rest left neutral."""
    values = dict(CORPUS_MEASURES)
    if measure not in values:
        raise CorpusError(
            f"the trigger reads {measure!r}, which the corpus does not carry; a trigger whose "
            "measure the corpus cannot set would be exercised against a missing reading"
        )
    step = max(abs(threshold) * 0.5, 0.5) if threshold else 1.0
    values[measure] = threshold + step if direction == "above" else max(threshold - step, 0.0)
    return tuple(values.items())


def _audited(observation: PolicyObservation, *, trigger: str) -> CorpusEntry:
    """Render one observation's prompt and audit it, refusing a prompt that leaks anything."""
    from late_ming_lab.core.hashing import hash_text

    prompt = render_prompt(observation)
    try:
        audit_prompt(prompt)
    except ObservationRejectedError as error:
        raise CorpusError(f"{observation.actor} ({trigger}): {error}") from error
    for name, _value in observation.measures:
        if any(token in name for token in ("year", "date", "dynasty", "province")):
            raise CorpusError(
                f"{observation.actor}: the measure name {name!r} names a time or a place"
            )
    return CorpusEntry(
        role=observation.role,
        trigger=trigger,
        observation=observation,
        prompt=prompt,
        prompt_hash=hash_text(prompt),
        action_space=tuple(action.value for action in observation.action_space),
    )


def audit_corpus(entries: Iterable[CorpusEntry]) -> dict[str, object]:
    """Re-audit every prompt and report the coverage the corpus claims to have."""
    checked = 0
    for entry in entries:
        audit_prompt(entry.prompt)
        checked += 1
    triggers = {entry.trigger for entry in entries}
    roles = {entry.role for entry in entries}
    declared = {trigger.name for trigger in default_triggers()}
    missing = declared - triggers
    if missing:
        raise CorpusError(f"the corpus does not cover the declared triggers {sorted(missing)}")
    return {
        "entries": checked,
        "roles": sorted(role.value for role in roles),
        "triggers": sorted(triggers),
        "declared_triggers": sorted(declared),
        "every_role_covered": roles == set(ActorRole),
    }


@dataclass(frozen=True, slots=True)
class Recording:
    """What one recording call produced: the fixture, its hashes, and what it cost."""

    role: str
    trigger: str
    prompt_hash: str
    response_hash: str
    model_id: str
    response_model_id: str
    seconds: float

    def record(self) -> dict[str, object]:
        return {
            "role": self.role,
            "trigger": self.trigger,
            "prompt_hash": self.prompt_hash,
            "response_hash": self.response_hash,
            "model_id": self.model_id,
            "response_model_id": self.response_model_id,
            "seconds": self.seconds,
        }


@dataclass(slots=True)
class RecordingPass:
    """A recording run over the corpus: the fixtures it wrote and what each call cost."""

    store: Path
    recordings: list[Recording] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def table(self) -> pl.DataFrame:
        if not self.recordings:
            return pl.DataFrame(
                schema={
                    "role": pl.Utf8,
                    "trigger": pl.Utf8,
                    "prompt_hash": pl.Utf8,
                    "response_hash": pl.Utf8,
                    "model_id": pl.Utf8,
                    "response_model_id": pl.Utf8,
                    "seconds": pl.Float64,
                }
            )
        return pl.DataFrame([recording.record() for recording in self.recordings])


def record_corpus(
    entries: Iterable[CorpusEntry],
    *,
    policy: Policy,
    store_path: str | Path,
    record_exchange: Callable[[RecordedExchange], Path],
) -> RecordingPass:
    """Send every corpus observation to a live policy and store the sanitised answer as a fixture.

    The policy is passed in rather than built here: this module must not be a second place that
    knows how to construct one, and a caller that has no usable policy simply cannot call this. The
    policy is asked for the trace of each decision, so the fixture records the model the answer came
    from and not the model that was requested.
    """
    from late_ming_lab.core.hashing import hash_text

    pass_ = RecordingPass(store=Path(store_path))
    for entry in entries:
        started = time.perf_counter()
        try:
            decision = policy.choose_action(entry.observation, entry.observation.action_space)
            trace = policy.last_record()
        except Exception as error:  # a refusal, a timeout, a schema failure: all recorded
            pass_.failures.append(f"{entry.observation.actor}/{entry.trigger}: {error}")
            continue
        if trace is None or trace.model_id is None:
            pass_.failures.append(
                f"{entry.observation.actor}: the policy recorded no model, so the fixture would "
                "not say which model answered"
            )
            continue
        answered_as = trace.model_id
        exchange = sanitize_response(
            {
                "model": trace.model_id,
                "choices": [{"message": {"content": _response_content(decision)}}],
            },
            model_id=answered_as,
            prompt_hash=entry.prompt_hash,
            request_hash=hash_text(entry.prompt),
            provenance=policy.model_id,
            endpoint_model_id=answered_as,
            note="recorded by the V2-P08 corpus pass",
        )
        record_exchange(exchange)
        pass_.recordings.append(
            Recording(
                role=entry.role.value,
                trigger=entry.trigger,
                prompt_hash=entry.prompt_hash,
                response_hash=exchange.response_hash,
                model_id=exchange.model_id,
                response_model_id=exchange.response_model_id,
                seconds=time.perf_counter() - started,
            )
        )
    return pass_


def _response_content(decision: object) -> str:
    """The decision as the JSON the fixture stores, so a replay rebuilds the same object."""
    from pydantic import BaseModel

    from late_ming_lab.core.hashing import canonical_json

    if isinstance(decision, BaseModel):
        return canonical_json(decision.model_dump(mode="json"))
    raise CorpusError(f"the policy returned {type(decision).__name__}, which cannot be recorded")


def write_corpus_table(root: str | Path, entries: Iterable[CorpusEntry]) -> Path:
    """The corpus itself as an artifact: what was asked, and which reading fired each trigger."""
    rows = [entry.record() for entry in entries]
    path = Path(root) / CORPUS_PATH
    write_table(path, pl.DataFrame(rows))
    return path


CORPUS_PATH: Final[str] = "outputs/v2/p08/observation-corpus.parquet"
RECORDINGS_PATH: Final[str] = "outputs/v2/p08/recordings.parquet"


def write_recordings_table(root: str | Path, pass_: RecordingPass) -> Path:
    path = Path(root) / RECORDINGS_PATH
    write_table(path, pass_.table())
    return path


def corpus_manifest(
    entries: Iterable[CorpusEntry], pass_: RecordingPass | None = None
) -> Mapping[str, object]:
    """The audit and the recording pass in one mapping, for the phase's manifest."""
    audit = audit_corpus(entries)
    payload: dict[str, object] = {"corpus": audit}
    if pass_ is not None:
        payload["recordings"] = {
            "written": len(pass_.recordings),
            "failures": list(pass_.failures),
            "model_ids": sorted({recording.model_id for recording in pass_.recordings}),
            "response_model_ids": sorted(
                {recording.response_model_id for recording in pass_.recordings}
            ),
            "total_seconds": round(sum(recording.seconds for recording in pass_.recordings), 3),
        }
    return payload


__all__ = [
    "CORPUS_MEASURES",
    "CORPUS_PATH",
    "CORPUS_REGIONS",
    "RECORDINGS_PATH",
    "CorpusEntry",
    "CorpusError",
    "Recording",
    "RecordingPass",
    "audit_corpus",
    "corpus",
    "corpus_manifest",
    "record_corpus",
    "write_corpus_table",
    "write_recordings_table",
]
