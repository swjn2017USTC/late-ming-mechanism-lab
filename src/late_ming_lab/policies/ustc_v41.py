"""The USTC DeepSeek V4.1 runtime policy: the one model the boundary allows, or nothing at all.

This is the only place in the repository that talks to a model at runtime, and it is built so that
the ways it can fail are all refusals:

- **the model is confirmed or the policy does not exist.** The configured id must equal the id the
  operator confirmed against the account's ``/v1/models``; anything else raises
  :class:`ModelNotConfirmedError` before a credential is read or a socket is opened. The forbidden
  fallbacks (V4 Pro, legacy V4 Flash, Qwen, GLM, OpenCode Go, OpenAI) are named in the refusal so a
  reader can see what was refused rather than guessing.
- **the endpoint must confirm it answered.** A response whose own model id is not the confirmed one
  is refused, because an endpoint that silently serves another model has broken the only guarantee
  this layer exists to provide.
- **disabled means disabled.** Nothing runs unless the environment turns it on explicitly.

Everything else follows the contract in :mod:`late_ming_lab.policies.base`: no tools in the payload,
a structured and audited prompt, a Pydantic-validated decision, a timeout on every call, retries
only for transport failures, an explicit answer to 429, and a record of the model id, prompt hash
and response hash for every decision.

The credential is read lazily and never printed: it lives in a :class:`~pydantic.SecretStr`, is
handed straight to the client, and is not available to any log, trace or report. The model gate runs
*before* the credential is touched, which is a property the tests assert by handing this module a
credential source that fails the test if it is called.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Final, Protocol, runtime_checkable

import httpx
import openai
from pydantic import BaseModel, ConfigDict, SecretStr

from late_ming_lab.core.config import RUNTIME_LLM_MODEL_ID
from late_ming_lab.core.hashing import hash_text
from late_ming_lab.policies.base import (
    ChatRequest,
    ChatResponse,
    ChatTransport,
    InstitutionalAction,
    InstitutionalDecision,
    ModelNotConfirmedError,
    PolicyObservation,
    PolicyRecord,
    PolicyUnavailableError,
    decision_from_json,
    render_prompt,
)

#: The model ids the operator has confirmed for runtime use. Exactly one today, matched exactly: a
#: near-miss such as a variant suffix is not a confirmation, and this package will not treat it as
#: one. Adding an id here is an operator act, not a configuration change.
CONFIRMED_MODEL_IDS: Final[tuple[str, ...]] = (RUNTIME_LLM_MODEL_ID,)

#: Ids that must never be reached from this layer, named so a refusal can say what it refused. They
#: are matched as substrings of a candidate id; the confirmed id is checked first.
FORBIDDEN_MODEL_MARKERS: Final[tuple[str, ...]] = (
    "pro",
    "flash",
    "qwen",
    "glm",
    "gpt",
    "claude",
    "opencode",
    "legacy",
)

#: The prompt version is part of a decision's identity: a change to the rendering must be visible in
#: the trace even when the observation is unchanged.
PROMPT_VERSION: Final[str] = "institutional-prompt-v1"

#: Declared call settings. Temperature is 0 because the phase wants a decision layer whose output is
#: reproducible enough to replay, not a creative one.
DEFAULT_TEMPERATURE: Final[float] = 0.0
DEFAULT_MAX_TOKENS: Final[int] = 400
DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0

#: Retry policy: bounded attempts, transport failures only, and a backoff that a 429 may override
#: with the server's own ``Retry-After``.
DEFAULT_MAX_ATTEMPTS: Final[int] = 3
DEFAULT_BACKOFF_SECONDS: Final[float] = 0.5
MAX_RETRY_AFTER_SECONDS: Final[float] = 30.0

#: The environment surface. Only these four names are read, and only three of them here.
ENV_BASE_URL: Final[str] = "USTC_LLM_BASE_URL"
ENV_API_KEY: Final[str] = "USTC_LLM_API_KEY"
ENV_MODEL: Final[str] = "USTC_LLM_MODEL"
ENV_ENABLED: Final[str] = "USTC_LLM_ENABLED"


@runtime_checkable
class CredentialSource(Protocol):
    """Where the API key comes from. Nothing else in this module may read it."""

    def api_key(self) -> SecretStr: ...


@dataclass(frozen=True, slots=True)
class EnvironmentCredential:
    """The key from a mapping of environment values, wrapped so it cannot be printed by accident."""

    environ: Mapping[str, str]

    def api_key(self) -> SecretStr:
        value = self.environ.get(ENV_API_KEY, "")
        if not value:
            raise PolicyUnavailableError(f"{ENV_API_KEY} is not set")
        return SecretStr(value)


class UstcSettings(BaseModel):
    """The runtime model's declared settings, as validated before anything is called."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str
    model_id: str
    enabled: bool
    timeout_seconds: float
    api_key: SecretStr


def confirmed_model_id(model_id: str) -> str:
    """Return the id if it is the operator-confirmed runtime model, otherwise refuse.

    The refusal names the id it saw and the ids this layer may never use, and it happens without any
    network call and without reading a credential — which is what makes "fail closed" true rather
    than aspirational.
    """
    if model_id in CONFIRMED_MODEL_IDS:
        return model_id
    forbidden = ", ".join(FORBIDDEN_MODEL_MARKERS)
    raise ModelNotConfirmedError(
        f"{ENV_MODEL}={model_id!r} is not a confirmed runtime model. Confirmed: "
        f"{', '.join(CONFIRMED_MODEL_IDS)}. There is no fallback from here: this layer never calls "
        f"a model whose id carries {forbidden}."
    )


def load_settings(
    *,
    environ: Mapping[str, str] | None = None,
    credential_source: CredentialSource | None = None,
) -> UstcSettings:
    """Validate the model gate and the enable switch, and only then read the credential.

    The order is the point. A misconfigured model must fail before the key is touched, so a refusal
    cannot be mistaken for a credential problem and a wrong model cannot be called "just once".
    """
    values = environ if environ is not None else _process_environment()
    model_id = confirmed_model_id(values.get(ENV_MODEL, ""))
    if values.get(ENV_ENABLED, "0") not in {"1", "true", "True"}:
        raise PolicyUnavailableError(
            f"{ENV_ENABLED} is not set to 1: the runtime decision layer is disabled by default and "
            "stays disabled until an operator turns it on"
        )
    source = credential_source or EnvironmentCredential(values)
    return UstcSettings(
        base_url=values.get(ENV_BASE_URL, "").rstrip("/"),
        model_id=model_id,
        enabled=True,
        timeout_seconds=float(values.get("USTC_LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
        api_key=source.api_key(),
    )


def _process_environment() -> Mapping[str, str]:
    import os

    return dict(os.environ)


class _RetryDecision:
    """What to do after a failed attempt: retry after a delay, or refuse."""

    __slots__ = ("delay_seconds", "reason", "retry")

    def __init__(self, *, retry: bool, delay_seconds: float, reason: str) -> None:
        self.retry = retry
        self.delay_seconds = delay_seconds
        self.reason = reason


def classify_failure(error: Exception) -> _RetryDecision:
    """Decide whether a failure is worth another attempt, from its type and status alone.

    Retryable: timeouts, connection failures and 5xx. Not retryable: every other 4xx — a request the
    server rejected will be rejected again. 429 is retryable but explicitly bounded, and it is the
    one case where the server's own ``Retry-After`` wins over the declared backoff.
    """
    if isinstance(error, (httpx.TimeoutException, openai.APITimeoutError)):
        return _RetryDecision(retry=True, delay_seconds=DEFAULT_BACKOFF_SECONDS, reason="timeout")
    if isinstance(error, (httpx.TransportError, openai.APIConnectionError)):
        return _RetryDecision(retry=True, delay_seconds=DEFAULT_BACKOFF_SECONDS, reason="transport")
    status = _status_of(error)
    if status == 429:
        return _RetryDecision(
            retry=True,
            delay_seconds=_retry_after_seconds(error),
            reason="rate-limited",
        )
    if isinstance(status, int) and 500 <= status < 600:
        return _RetryDecision(retry=True, delay_seconds=DEFAULT_BACKOFF_SECONDS, reason="server")
    return _RetryDecision(retry=False, delay_seconds=0.0, reason="refused")


def _status_of(error: Exception) -> int | None:
    """The HTTP status a failure carries, from the two places a client puts it.

    ``openai``'s errors expose ``status_code``; a bare ``httpx.HTTPStatusError`` exposes only the
    response. Reading one and not the other would silently make 429 handling depend on which layer
    raised, which is exactly the kind of quiet difference this module exists to prevent.
    """
    direct = getattr(error, "status_code", None)
    if isinstance(direct, int):
        return direct
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _retry_after_seconds(error: Exception) -> float:
    """The server's own wait, or the declared backoff when it does not say."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None:
        return DEFAULT_BACKOFF_SECONDS
    try:
        return min(float(raw), MAX_RETRY_AFTER_SECONDS)
    except ValueError:
        try:
            when = parsedate_to_datetime(str(raw))
        except (TypeError, ValueError):
            return DEFAULT_BACKOFF_SECONDS
        wait = when.timestamp() - time.time()
        return max(0.0, min(wait, MAX_RETRY_AFTER_SECONDS))


class OpenAIChatTransport:
    """The live transport: an OpenAI-compatible chat completion, with this module's retry policy."""

    name: str = "openai-compatible-ustc"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._sleeper = sleeper
        # max_retries=0 on purpose: the SDK's own retries would make this module's declared policy a
        # fiction, and a hidden retry is exactly what the boundary forbids.
        self._client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key.get_secret_value(),
            timeout=timeout_seconds,
            max_retries=0,
        )

    def complete(self, request: ChatRequest) -> ChatResponse:
        attempts = 0
        last_reason = "no attempt was made"
        while attempts < self._max_attempts:
            attempts += 1
            started = time.perf_counter()
            try:
                # The payload is a plain mapping built in `policies.base`, so that "no tools key"
                # is a property a test can assert on the bytes that would be sent; the SDK's own
                # parameter classes cannot express that, hence the widening here and nowhere else.
                payload: Any = request.payload()
                completion = self._client.chat.completions.create(**payload)
            except Exception as error:  # classified below; nothing is retried blindly
                decision = classify_failure(error)
                last_reason = f"{decision.reason}: {error}"
                if not decision.retry or attempts >= self._max_attempts:
                    raise PolicyUnavailableError(
                        f"the runtime model could not be reached after {attempts} attempt(s) "
                        f"({last_reason}); no other model will be called"
                    ) from error
                self._sleeper(decision.delay_seconds)
                continue
            content = completion.choices[0].message.content if completion.choices else None
            if not content:
                raise PolicyUnavailableError("the runtime model returned no content")
            return ChatResponse(
                content=content,
                model_id=str(getattr(completion, "model", "") or ""),
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )
        raise PolicyUnavailableError(  # pragma: no cover - the loop always raises or returns
            f"the runtime model could not be reached ({last_reason})"
        )


class USTCV41Policy:
    """The runtime policy: one confirmed model, one structured question, one bounded answer."""

    def __init__(
        self,
        *,
        transport: ChatTransport,
        settings: UstcSettings,
        require_endpoint_model: bool = True,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        confirmed_model_id(settings.model_id)  # the gate, again, at construction
        if not settings.enabled:
            raise PolicyUnavailableError("the runtime decision layer is disabled")
        self._transport = transport
        self._settings = settings
        self._require_endpoint_model = require_endpoint_model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._record = PolicyRecord(model_id=settings.model_id, outcome="not-asked")

    @property
    def name(self) -> str:
        return f"ustc-v41-{PROMPT_VERSION}"

    @property
    def model_id(self) -> str:
        return self._settings.model_id

    def last_record(self) -> PolicyRecord:
        return self._record

    def choose_action(
        self,
        observation: PolicyObservation,
        action_space: Sequence[InstitutionalAction],
    ) -> InstitutionalDecision:
        """Ask the model for one action and validate the answer against the actor's action space.

        The prompt is rendered and audited first (no place, no dynasty, no person, no date), then
        sent with no tools. The answer is parsed into the decision schema, checked against the
        action space, and recorded by hash. A malformed or out-of-space answer is refused rather
        than repaired, because a repaired answer is this layer's decision, not the model's.
        """
        prompt = render_prompt(observation)
        request = ChatRequest(
            model_id=self._settings.model_id,
            prompt=prompt,
            prompt_hash=hash_text(prompt),
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        response = self._transport.complete(request)
        if self._require_endpoint_model and response.model_id != self._settings.model_id:
            self._record = PolicyRecord(
                model_id=response.model_id,
                prompt_hash=request.prompt_hash,
                response_hash=response.content_hash(),
                latency_ms=response.latency_ms,
                outcome="endpoint-model-mismatch",
            )
            raise ModelNotConfirmedError(
                f"the endpoint answered as {response.model_id!r}, not "
                f"{self._settings.model_id!r}; a swapped model is refused rather than used"
            )
        try:
            decision = decision_from_json(response.content, action_space=action_space)
        except Exception:
            self._record = PolicyRecord(
                model_id=response.model_id,
                prompt_hash=request.prompt_hash,
                response_hash=response.content_hash(),
                latency_ms=response.latency_ms,
                outcome="invalid-answer",
            )
            raise
        self._record = PolicyRecord(
            model_id=response.model_id,
            prompt_hash=request.prompt_hash,
            response_hash=response.content_hash(),
            latency_ms=response.latency_ms,
            outcome="decided",
        )
        return decision


def policy_from_environment(
    *,
    environ: Mapping[str, str] | None = None,
    credential_source: CredentialSource | None = None,
    transport: ChatTransport | None = None,
) -> USTCV41Policy:
    """Build the runtime policy from the environment, or refuse with the reason.

    This is the one call a simulation run makes to reach the model. It fails closed on a disabled
    switch, an unconfirmed model or a missing credential, and it never constructs a policy for a
    model other than the confirmed one.
    """
    settings = load_settings(environ=environ, credential_source=credential_source)
    live = transport or OpenAIChatTransport(
        base_url=settings.base_url,
        api_key=settings.api_key,
        timeout_seconds=settings.timeout_seconds,
    )
    return USTCV41Policy(transport=live, settings=settings)
