"""The institutional policy interface: structured state in, one bounded action out.

Everything the runtime decision layer may do passes through this module, so the boundary the
project committed to in P00 is expressed once rather than re-argued in each policy:

- a **bounded action space**, scoped by the actor's role: an institutional actor chooses among a
  handful of declared actions with an intensity in ``[0, 1]``, nothing else;
- **structured input**: an anonymized observation with named, dimensionless readings and no dates,
  no dynastic or personal names, and no region the model could recognize;
- **structured output**: a Pydantic-validated decision whose only world-facing fields are the action
  and its intensity;
- **`rationale` is explanation, never instruction**: it is recorded for a reader and is never
  parsed, evaluated, or allowed to touch simulation state. Only :func:`apply_decision` changes
  anything, and it consults the action enum alone.

The observation carries the tick for the trace's sake but the prompt payload does not, because the
tick is a date in disguise: an actor that knows it is 1643 knows more than the actor it stands for.

Policies implemented beside this interface: a declared rule table, a bounded utility rule, a seeded
random choice, and the USTC V4.1 runtime model. The first three exist so the fail-closed path has
somewhere to land, and so a decision layer can be tested without a network.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

#: The policy surface default: nothing the runtime layer does is on unless a caller turns it on.
DEFAULT_ENABLED: Final[bool] = False

#: A decision's rationale is stored, never executed. The cap keeps a trace readable and bounds
#: what a misbehaving model can inflate.
MAX_RATIONALE_CHARS: Final[int] = 600


class PolicyError(RuntimeError):
    """Base class for a decision layer that cannot proceed."""


class ModelNotConfirmedError(PolicyError):
    """The endpoint's model id is not the operator-confirmed runtime model.

    Raised *before* any credential is read and before any request is made. There is deliberately
    no fallback path: a caller that catches this may switch to a declared rule-based policy, but
    nothing in this package will silently call another model.
    """


class PolicyUnavailableError(PolicyError):
    """The runtime model could not be reached, or gave an answer that cannot be used."""


class ObservationRejectedError(PolicyError):
    """An observation would leak identity, date or outcome information into a prompt."""


class DecisionRejectedError(PolicyError):
    """A decision is outside the action space, or is not the shape the contract declares."""


class InstitutionalAction(StrEnum):
    """Every action an institutional actor may take. Nothing outside this enum can change state."""

    MAINTAIN = "MAINTAIN"
    RELAX_EXTRACTION = "RELAX_EXTRACTION"
    INTENSIFY_EXTRACTION = "INTENSIFY_EXTRACTION"
    RELIEF_TRANSFER = "RELIEF_TRANSFER"
    BLOCK_LINK = "BLOCK_LINK"
    REOPEN_LINK = "REOPEN_LINK"


class ActorRole(StrEnum):
    """The institutional seats the plan allows a runtime decision layer to occupy."""

    CENTRAL_FISCAL = "central-fiscal-authority"
    PROVINCIAL = "provincial-authority"
    COUNTY = "county-authority"
    ARMED_GROUP = "armed-group-leadership"


class Priority(StrEnum):
    """What the actor says it is optimizing. Explanation, and a trace column."""

    MAINTAIN = "MAINTAIN"
    STABILIZE_TAX_BASE = "STABILIZE_TAX_BASE"
    SUSTAIN_ARMY = "SUSTAIN_ARMY"
    PRESERVE_ORDER = "PRESERVE_ORDER"
    RELIEVE_DISTRESS = "RELIEVE_DISTRESS"


#: The action space, per role. A policy is handed only its own role's actions and a decision outside
#: them is refused, which is what makes the space bounded rather than merely declared.
ROLE_ACTIONS: Final[Mapping[ActorRole, tuple[InstitutionalAction, ...]]] = {
    ActorRole.CENTRAL_FISCAL: (
        InstitutionalAction.MAINTAIN,
        InstitutionalAction.RELAX_EXTRACTION,
        InstitutionalAction.INTENSIFY_EXTRACTION,
        InstitutionalAction.RELIEF_TRANSFER,
    ),
    ActorRole.PROVINCIAL: (
        InstitutionalAction.MAINTAIN,
        InstitutionalAction.RELAX_EXTRACTION,
        InstitutionalAction.INTENSIFY_EXTRACTION,
        InstitutionalAction.RELIEF_TRANSFER,
    ),
    ActorRole.COUNTY: (
        InstitutionalAction.MAINTAIN,
        InstitutionalAction.RELAX_EXTRACTION,
        InstitutionalAction.INTENSIFY_EXTRACTION,
        InstitutionalAction.RELIEF_TRANSFER,
    ),
    ActorRole.ARMED_GROUP: (
        InstitutionalAction.MAINTAIN,
        InstitutionalAction.BLOCK_LINK,
        InstitutionalAction.REOPEN_LINK,
    ),
}

#: The levers a decision can reach. Every action in :class:`InstitutionalAction` has one, so no
#: decision is recorded as taken while changing nothing.
ACTION_LEVERS: Final[Mapping[InstitutionalAction, str]] = {
    InstitutionalAction.MAINTAIN: "none",
    InstitutionalAction.RELAX_EXTRACTION: "extraction-policy",
    InstitutionalAction.INTENSIFY_EXTRACTION: "extraction-policy",
    InstitutionalAction.RELIEF_TRANSFER: "relief-share",
    InstitutionalAction.BLOCK_LINK: "trade-disruption",
    InstitutionalAction.REOPEN_LINK: "trade-disruption",
}


@dataclass(frozen=True, slots=True)
class PolicyObservation:
    """What an actor is told: opaque identities, dimensionless readings, and its action space."""

    actor: str
    role: ActorRole
    region: str
    tick: int
    measures: tuple[tuple[str, float], ...]
    action_space: tuple[InstitutionalAction, ...]

    def measure_map(self) -> dict[str, float]:
        return dict(self.measures)

    def payload(self) -> dict[str, object]:
        """The structured input a policy sees, and the exact text a prompt is rendered from.

        No tick, no date and no calendar field: the tick is what the *trace* records, and an actor
        that can count months from a date can count its way to the historical outcome.
        """
        return {
            "actor": self.actor,
            "role": self.role.value,
            "region": self.region,
            "observed": {name: round(value, 6) for name, value in self.measures},
            "available_actions": [action.value for action in self.action_space],
        }


class InstitutionalDecision(BaseModel):
    """One bounded decision. Only ``action`` and ``intensity`` may reach the world."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: InstitutionalAction
    intensity: float = Field(ge=0.0, le=1.0)
    priority: Priority
    rationale: str = Field(min_length=1, max_length=MAX_RATIONALE_CHARS)


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    """The record of one decision: what was asked, what came back, and what it changed."""

    actor: str
    role: str
    region: str
    tick: int
    policy: str
    model_id: str | None
    prompt_hash: str
    response_hash: str | None
    action: str
    intensity: float
    priority: str
    rationale: str
    outcome: str
    levers: tuple[str, ...]
    latency_ms: float | None

    def as_row(self) -> dict[str, object]:
        return {
            "tick": self.tick,
            "actor": self.actor,
            "role": self.role,
            "region": self.region,
            "policy": self.policy,
            "model_id": self.model_id,
            "prompt_hash": self.prompt_hash,
            "response_hash": self.response_hash,
            "action": self.action,
            "intensity": self.intensity,
            "priority": self.priority,
            "rationale": self.rationale,
            "outcome": self.outcome,
            "levers": ",".join(self.levers),
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True, slots=True)
class ChatRequest:
    """One structured request to a runtime model: a prompt, and nothing else.

    The payload is built here rather than at the client, because two properties have to hold for
    every call the project ever makes: there is no ``tools`` key (the runtime model gets no tools),
    and the prompt is exactly the audited text whose hash is recorded.
    """

    model_id: str
    prompt: str
    prompt_hash: str
    temperature: float
    max_tokens: int

    def payload(self) -> dict[str, object]:
        return {
            "model": self.model_id,
            "messages": [{"role": "user", "content": self.prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }


@dataclass(frozen=True, slots=True)
class ChatResponse:
    """What came back, with the identity of the model that answered it."""

    content: str
    model_id: str
    latency_ms: float

    def content_hash(self) -> str:
        """The hash recorded in the trace: the answer's bytes, not its interpretation."""
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@runtime_checkable
class ChatTransport(Protocol):
    """The only way a policy reaches a model. Tests substitute it; replay implements it."""

    def complete(self, request: ChatRequest) -> ChatResponse: ...


@runtime_checkable
class InstitutionalPolicy(Protocol):
    """Choose one action for one actor. The whole runtime decision surface is this method."""

    @property
    def name(self) -> str: ...

    def choose_action(
        self,
        observation: PolicyObservation,
        action_space: Sequence[InstitutionalAction],
    ) -> InstitutionalDecision: ...


@dataclass(frozen=True, slots=True)
class PolicyRecord:
    """What a policy that talks to a model must be able to say about its last decision.

    A rule-based policy has nothing to record here, and the engine fills the trace's provenance
    columns with empty values for it; a model-backed policy records the model it reached, the prompt
    it sent and the answer it received, by hash.
    """

    model_id: str | None = None
    prompt_hash: str | None = None
    response_hash: str | None = None
    latency_ms: float | None = None
    outcome: str = "decided"


@runtime_checkable
class TracedPolicy(Protocol):
    """A policy that can explain which model answered, and to which prompt."""

    def last_record(self) -> PolicyRecord: ...


#: Tokens that would tell a model where and when it is. Checked against every rendered prompt, so a
#: future observation that starts carrying a place name or a date fails loudly instead of quietly
#: handing the model the answer. Lower-cased before comparison; Chinese tokens compare verbatim.
FORBIDDEN_TOKENS: Final[tuple[str, ...]] = (
    "ming",
    "chongzhen",
    "崇祯",
    "天启",
    "李自成",
    "张献忠",
    "li zicheng",
    "zhang xianzhong",
    "shaanxi",
    "shanxi",
    "henan",
    "sichuan",
    "huguang",
    "陕西",
    "山西",
    "河南",
    "四川",
    "湖广",
    "beijing",
    "北京",
    "toy-sx",
    "toy-hn",
)

#: A four-digit year, or a bare year pair such as ``1643``. The observation carries no date, so any
#: of these in a prompt is a leak.
_YEAR_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b(1[5-9]\d\d|2\d{3})\b")


def render_prompt(observation: PolicyObservation) -> str:
    """The one canonical prompt text for an observation.

    Deterministic and sorted, so a prompt hash identifies a decision context and two runs of the
    same context hash the same. The audit below runs on the rendered text, which is what the model
    actually receives.
    """
    payload = observation.payload()
    lines = [
        "You are an institutional actor in a simulation of a pre-modern agrarian crisis.",
        "Choose exactly one action from the available actions for this turn.",
        "",
        "Actor:",
        str(payload["actor"]),
        "",
        "Role:",
        str(payload["role"]),
        "",
        "Region:",
        str(payload["region"]),
        "",
        "Observed conditions:",
    ]
    observed = payload["observed"]
    assert isinstance(observed, dict)
    for name in sorted(observed):
        lines.append(f"- {name}: {observed[name]}")
    lines += [
        "",
        "Available policy actions:",
    ]
    for action in observation.action_space:
        lines.append(f"- {action.value}")
    lines += [
        "",
        "Answer with a single JSON object with exactly these keys:",
        '{"action": <one of the available actions>, "intensity": <0.0 to 1.0>, '
        '"priority": <one of MAINTAIN, STABILIZE_TAX_BASE, SUSTAIN_ARMY, PRESERVE_ORDER, '
        'RELIEVE_DISTRESS>, "rationale": <one short sentence>}',
        "Do not add keys. Do not explain outside the JSON object.",
    ]
    prompt = "\n".join(lines)
    audit_prompt(prompt)
    return prompt


def audit_prompt(prompt: str) -> None:
    """Refuse a prompt that names a place, a dynasty, a person or a date.

    An alphabetic token is matched on a word boundary, so a reading called ``incoming_grain`` or
    ``households_migrating`` is not mistaken for the dynasty it happens to spell inside; a token in
    a script without word breaks is matched as a substring.
    """
    lowered = prompt.lower()
    for token in FORBIDDEN_TOKENS:
        if token.isascii() and token.isalpha():
            found = re.search(rf"\b{re.escape(token)}\b", lowered) is not None
        else:
            found = token in lowered
        if found:
            raise ObservationRejectedError(
                f"the prompt names {token!r}; actor and region identities must stay opaque"
            )
    match = _YEAR_PATTERN.search(prompt)
    if match is not None:
        raise ObservationRejectedError(
            f"the prompt carries the year-like token {match.group(0)!r}; "
            "an actor that can date itself can date the outcome"
        )


def validate_decision(
    decision: InstitutionalDecision, *, action_space: Sequence[InstitutionalAction]
) -> None:
    """Refuse a decision outside the role's action space, before anything acts on it."""
    if decision.action not in action_space:
        allowed = ", ".join(action.value for action in action_space)
        raise DecisionRejectedError(
            f"{decision.action.value!r} is not in this actor's action space ({allowed})"
        )


def decision_from_json(
    text: str, *, action_space: Sequence[InstitutionalAction]
) -> InstitutionalDecision:
    """Parse and validate a model's answer; anything unexpected is refused, not repaired."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise DecisionRejectedError(f"the answer is not JSON: {error.msg}") from error
    if not isinstance(payload, dict):
        raise DecisionRejectedError("the answer must be a JSON object")
    try:
        decision = InstitutionalDecision.model_validate(payload)
    except Exception as error:  # pydantic's ValidationError, reported as a policy refusal
        raise DecisionRejectedError(
            f"the answer does not match the decision schema: {error}"
        ) from error
    validate_decision(decision, action_space=action_space)
    return decision
