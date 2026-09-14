"""Recorded runtime-model answers, and their deterministic replay.

The project's reproducibility rule has exactly one licensed exception: a runtime LLM decision
cannot be recomputed from code, configuration and seed. A recorded fixture closes that gap without
putting a model back in the loop — one live OpenAI-compatible response is reduced to the few facts
a replay needs, committed under the prompt's hash, and every later run of that prompt is answered
from those bytes.

What the reduction drops is the point. An endpoint's response id, creation timestamp, token
usage and system fingerprint describe an account and a moment, not a decision; a fixture is an
argument about an institutional policy, so it carries the answer, the identity of the model that
gave it, and how it was obtained (``live`` or ``hand-built``), and nothing else.

Replay fails closed. :class:`ReplayTransport` never invents an answer, so a replay run that is
missing an input stops with a :class:`PolicyUnavailableError` instead of quietly deciding
something the recorded run did not.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Final

from late_ming_lab.core.hashing import hash_text
from late_ming_lab.policies.base import (
    ChatRequest,
    ChatResponse,
    PolicyError,
    PolicyUnavailableError,
)
from late_ming_lab.storage.tables import read_text, write_text

#: The fixture format's version. A fixture recorded under another version is refused, not migrated:
#: a replay that silently reinterpreted an old file would attribute an answer to a prompt it may
#: not have been given.
FIXTURE_SCHEMA_VERSION: Final[str] = "llm-fixture-v1"

#: Fixtures live in one directory, one JSON file per prompt, named by the prompt hash.
FIXTURE_SUFFIX: Final[str] = ".json"


@dataclass(frozen=True, slots=True)
class RecordedExchange:
    """One recorded answer, with everything needed to replay it and to explain where it came from.

    ``model_id`` is what the run asked for; ``response_model_id`` is what the endpoint reported,
    which may differ — that difference is recorded rather than reconciled, because a replay has to
    reproduce the answer that was actually given.
    """

    schema_version: str
    prompt_hash: str
    model_id: str
    request_hash: str
    response_content: str
    response_hash: str
    provenance: str
    response_model_id: str
    note: str

    def to_json(self) -> str:
        """The fixture's canonical text: sorted keys, two-space indent, one trailing newline."""
        return f"{json.dumps(asdict(self), indent=2, sort_keys=True, ensure_ascii=False)}\n"

    @classmethod
    def from_json(cls, text: str) -> RecordedExchange:
        """Parse a fixture; a stale schema or an unexpected shape is refused, not repaired."""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise PolicyError(f"the fixture is not JSON: {error.msg}") from error
        if not isinstance(payload, dict):
            raise PolicyError("a fixture must be a JSON object")
        if payload.get("schema_version") != FIXTURE_SCHEMA_VERSION:
            raise PolicyError(
                f"fixture schema {payload.get('schema_version')!r} is not "
                f"{FIXTURE_SCHEMA_VERSION!r}; record the response again rather than migrating it"
            )
        declared = [field.name for field in fields(cls)]
        unexpected = sorted(set(payload) - set(declared))
        if unexpected:
            raise PolicyError(f"the fixture carries unexpected fields: {', '.join(unexpected)}")
        values: dict[str, str] = {}
        for name in declared:
            value = payload.get(name)
            if not isinstance(value, str):
                raise PolicyError(f"the fixture field {name!r} is missing or not a string")
            values[name] = value
        return cls(**values)


def _assistant_content(body: Mapping[str, object]) -> str:
    """The assistant's message content, or a refusal: a body that carries no answer is unusable."""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise PolicyUnavailableError("the response carries no choices")
    first = choices[0]
    message = first.get("message") if isinstance(first, Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str) or not content:
        raise PolicyUnavailableError("the response carries no assistant message content")
    return content


def sanitize_response(
    body: Mapping[str, object],
    *,
    model_id: str,
    prompt_hash: str,
    request_hash: str,
    provenance: str,
    endpoint_model_id: str,
    note: str = "",
) -> RecordedExchange:
    """Reduce one OpenAI-compatible chat response to what a replay needs.

    Keeps the assistant's message content and the model ids. Drops everything else — ids, created
    timestamps, usage, headers, system fingerprints — because a fixture is committed and a fixture
    is not a transcript of an account.
    """
    content = _assistant_content(body)
    return RecordedExchange(
        schema_version=FIXTURE_SCHEMA_VERSION,
        prompt_hash=prompt_hash,
        model_id=model_id,
        request_hash=request_hash,
        response_content=content,
        response_hash=hash_text(content),
        provenance=provenance,
        response_model_id=endpoint_model_id,
        note=note,
    )


class FixtureStore:
    """A directory of fixtures, addressed by prompt hash."""

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)

    def path_for(self, prompt_hash: str) -> Path:
        """The one path a prompt's fixture can occupy: its hash, under this directory."""
        return self._directory / f"{prompt_hash}{FIXTURE_SUFFIX}"

    def record(self, exchange: RecordedExchange) -> Path:
        """Write ``exchange``; an existing fixture with different content is refused.

        Re-recording the same exchange is a no-op, so a recording pass can be re-run, while a
        prompt that already holds a different answer stays put: a fixture that changed silently
        would make two runs of the same prompt disagree with nothing recording why.
        """
        path = self.path_for(exchange.prompt_hash)
        if path.exists():
            existing = RecordedExchange.from_json(read_text(path))
            if existing != exchange:
                raise PolicyError(
                    f"{path} already holds a different fixture for prompt "
                    f"{exchange.prompt_hash!r}; delete it deliberately to re-record"
                )
            return path
        return write_text(path, exchange.to_json())

    def load(self, prompt_hash: str) -> RecordedExchange | None:
        """The fixture for ``prompt_hash``, or ``None``; a file under the wrong name is refused."""
        path = self.path_for(prompt_hash)
        if not path.exists():
            return None
        exchange = RecordedExchange.from_json(read_text(path))
        if exchange.prompt_hash != prompt_hash:
            raise PolicyError(
                f"{path} answers prompt {exchange.prompt_hash!r}, not the {prompt_hash!r} it is "
                "named for"
            )
        return exchange

    def load_all(self) -> tuple[RecordedExchange, ...]:
        """Every fixture in the directory, in path order, so a listing is deterministic."""
        return tuple(
            RecordedExchange.from_json(read_text(path))
            for path in sorted(self._directory.glob(f"*{FIXTURE_SUFFIX}"))
        )


class ReplayTransport:
    """A ``ChatTransport`` that answers from recorded fixtures and refuses to invent one.

    A replay run exists to show that the same prompts produce the same decisions with no network.
    That claim dies if a missing fixture is papered over, so every miss raises and there is no
    fallback model and no default answer.

    ``allow_missing`` belongs to a recording pass, not to a simulation: in that mode a miss is
    remembered in :attr:`misses` — the prompts a live pass still has to answer — and the call
    raises on first use anyway, because the only thing this transport may not do is answer a prompt
    it has no answer for.
    """

    name = "replay-v1"

    def __init__(self, store: FixtureStore, *, allow_missing: bool = False) -> None:
        self._store = store
        self._allow_missing = allow_missing
        self._misses: list[str] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        exchange = self._store.load(request.prompt_hash)
        if exchange is None:
            if self._allow_missing:
                self._misses.append(request.prompt_hash)
            raise PolicyUnavailableError(
                f"no recorded fixture for prompt {request.prompt_hash}: record the live response "
                "rather than letting a replay invent one"
            )
        return ChatResponse(
            content=exchange.response_content,
            model_id=exchange.response_model_id,
            latency_ms=0.0,
        )

    @property
    def misses(self) -> tuple[str, ...]:
        """Prompts a recording pass still has to answer, in the order they were asked."""
        return tuple(self._misses)
