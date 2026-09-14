"""Recorded fixtures: what is kept, what a replay may answer, and what it must refuse.

These tests are offline by construction. Every response body is hand-built here, and the only
transport under test answers from a temporary directory, so nothing in this file touches a
network, a credential or a clock.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path

import pytest

from late_ming_lab.policies.base import (
    ChatRequest,
    ChatTransport,
    PolicyError,
    PolicyUnavailableError,
)
from late_ming_lab.policies.recording import (
    FIXTURE_SCHEMA_VERSION,
    FIXTURE_SUFFIX,
    FixtureStore,
    RecordedExchange,
    ReplayTransport,
    sanitize_response,
)

PROMPT_HASH = "6f1c2a9d4b8e5073a1c6f2d9b4e8073a1c6f2d9b4e8073a1c6f2d9b4e8073a1c"
REQUEST_HASH = "1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f809"
ANSWER = (
    '{"action": "RELIEF_TRANSFER", "intensity": 0.35, '
    '"priority": "RELIEVE_DISTRESS", "rationale": "Grain must reach the distressed cohorts."}'
)
OTHER_ANSWER = (
    '{"action": "MAINTAIN", "intensity": 0.0, '
    '"priority": "PRESERVE_ORDER", "rationale": "The granary is empty this month."}'
)

#: Values that describe the account and the moment of one call, never the decision.
DROPPED = ("chatcmpl-9f7c1a2b3c4d5e6f", "chat.completion", "fp_44709d6fcb", "1712345678")


def _body(content: str | None = ANSWER) -> dict[str, object]:
    """A realistic OpenAI-compatible chat completion, with nothing stripped in advance."""
    return {
        "id": "chatcmpl-9f7c1a2b3c4d5e6f",
        "object": "chat.completion",
        "created": 1712345678,
        "model": "ustc-deepseek-v4.1",
        "system_fingerprint": "fp_44709d6fcb",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "logprobs": None,
                "message": {"role": "assistant", "content": content, "refusal": None},
            }
        ],
        "usage": {"prompt_tokens": 291, "completion_tokens": 47, "total_tokens": 338},
    }


def _sanitize(
    body: Mapping[str, object],
    *,
    prompt_hash: str = PROMPT_HASH,
    model_id: str = "ustc-deepseek-v4.1",
    endpoint_model_id: str = "ustc-deepseek-v4.1",
    provenance: str = "live",
) -> RecordedExchange:
    return sanitize_response(
        body,
        model_id=model_id,
        prompt_hash=prompt_hash,
        request_hash=REQUEST_HASH,
        provenance=provenance,
        endpoint_model_id=endpoint_model_id,
        note="recorded once from the smoke scenario",
    )


def _request(prompt_hash: str = PROMPT_HASH) -> ChatRequest:
    return ChatRequest(
        model_id="ustc-deepseek-v4.1",
        prompt="Choose exactly one action from the available actions for this turn.",
        prompt_hash=prompt_hash,
        temperature=0.0,
        max_tokens=512,
    )


def test_sanitize_keeps_the_answer_and_both_model_ids() -> None:
    exchange = _sanitize(_body(), endpoint_model_id="ustc-deepseek-v4.1-2026-05")

    assert exchange.response_content == ANSWER
    assert exchange.model_id == "ustc-deepseek-v4.1"
    assert exchange.response_model_id == "ustc-deepseek-v4.1-2026-05"
    assert exchange.prompt_hash == PROMPT_HASH
    assert exchange.request_hash == REQUEST_HASH
    assert exchange.provenance == "live"
    assert exchange.schema_version == FIXTURE_SCHEMA_VERSION


def test_a_fixture_carries_nothing_but_its_own_fields() -> None:
    text = _sanitize(_body()).to_json()
    payload = json.loads(text)

    assert set(payload) == {field.name for field in fields(RecordedExchange)}
    assert all(isinstance(value, str) for value in payload.values()), "no nested body survived"
    for dropped in DROPPED:
        assert dropped not in text


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"role": "assistant"}}]},
        {"choices": [{"message": {"role": "assistant", "content": None}}]},
        {"choices": [{"message": {"role": "assistant", "content": ""}}]},
        {"choices": [{"message": "not a message object"}]},
    ],
)
def test_sanitize_refuses_a_body_without_an_assistant_answer(
    body: dict[str, object],
) -> None:
    with pytest.raises(PolicyUnavailableError):
        _sanitize(body)


def test_the_hash_covers_the_answer_and_not_the_account() -> None:
    described_differently = _body()
    described_differently["id"] = "chatcmpl-a-different-call"
    described_differently["created"] = 1
    described_differently["usage"] = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}

    first = _sanitize(_body())
    second = _sanitize(described_differently)
    other = _sanitize(_body(content=OTHER_ANSWER))

    assert first.response_hash == second.response_hash
    assert first.to_json() == second.to_json()
    assert other.response_hash != first.response_hash


def test_a_fixture_round_trips_byte_identically() -> None:
    exchange = _sanitize(_body())
    text = exchange.to_json()

    assert RecordedExchange.from_json(text) == exchange
    assert RecordedExchange.from_json(text).to_json() == text

    keys = [line.split('"')[1] for line in text.splitlines() if line.startswith('  "')]
    assert keys == sorted(keys), "to_json is canonical: sorted keys, fixed indent"


def test_from_json_refuses_a_fixture_it_cannot_trust() -> None:
    fixture = json.loads(_sanitize(_body()).to_json())

    with pytest.raises(PolicyError):
        RecordedExchange.from_json(json.dumps({**fixture, "schema_version": "llm-fixture-v2"}))
    with pytest.raises(PolicyError):
        RecordedExchange.from_json(json.dumps({**fixture, "usage": {"total_tokens": 338}}))
    with pytest.raises(PolicyError):
        RecordedExchange.from_json(json.dumps({**fixture, "response_hash": 338}))
    with pytest.raises(PolicyError):
        RecordedExchange.from_json("{not json")


def test_the_store_is_addressed_by_prompt_hash(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path / "llm")

    assert store.path_for(PROMPT_HASH) == tmp_path / "llm" / f"{PROMPT_HASH}{FIXTURE_SUFFIX}"
    assert store.load(PROMPT_HASH) is None

    path = store.record(_sanitize(_body()))
    loaded = store.load(PROMPT_HASH)

    assert path == store.path_for(PROMPT_HASH)
    assert path.read_text(encoding="utf-8") == _sanitize(_body()).to_json()
    assert loaded == _sanitize(_body())


def test_recording_the_same_exchange_again_changes_nothing(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path)
    exchange = _sanitize(_body())

    first = store.record(exchange)
    before = first.read_bytes()

    assert store.record(exchange) == first
    assert first.read_bytes() == before


def test_record_refuses_to_replace_a_different_answer(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path)
    store.record(_sanitize(_body()))

    with pytest.raises(PolicyError):
        store.record(_sanitize(_body(content=OTHER_ANSWER), provenance="hand-built"))

    unchanged = store.load(PROMPT_HASH)
    assert unchanged is not None
    assert unchanged.response_content == ANSWER


def test_load_refuses_a_fixture_filed_under_another_prompt(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path)
    recorded_under = "b" * 64
    store.record(_sanitize(_body(), prompt_hash=recorded_under))
    store.path_for(recorded_under).rename(store.path_for(PROMPT_HASH))

    with pytest.raises(PolicyError):
        store.load(PROMPT_HASH)


def test_load_all_lists_every_fixture_in_path_order(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path)
    hashes = ("b" * 64, "a" * 64)
    store.record(_sanitize(_body(), prompt_hash=hashes[0]))
    store.record(_sanitize(_body(content=OTHER_ANSWER), prompt_hash=hashes[1]))

    assert tuple(exchange.prompt_hash for exchange in store.load_all()) == tuple(sorted(hashes))


def test_replay_returns_the_recorded_answer_and_nothing_of_its_own(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path)
    store.record(_sanitize(_body(), endpoint_model_id="ustc-deepseek-v4.1-2026-05"))
    transport = ReplayTransport(store)

    first = transport.complete(_request())
    second = transport.complete(_request())

    assert first.content == ANSWER
    assert first.model_id == "ustc-deepseek-v4.1-2026-05"
    assert first.latency_ms == 0.0
    assert second == first


def test_replay_is_a_transport_named_for_what_it_does(tmp_path: Path) -> None:
    transport = ReplayTransport(FixtureStore(tmp_path))

    assert transport.name == "replay-v1"
    assert isinstance(transport, ChatTransport)


def test_a_missing_fixture_stops_the_replay(tmp_path: Path) -> None:
    transport = ReplayTransport(FixtureStore(tmp_path))

    with pytest.raises(PolicyUnavailableError):
        transport.complete(_request())

    assert transport.misses == ()


def test_a_recording_pass_collects_missing_prompts_without_answering_them(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path)
    transport = ReplayTransport(store, allow_missing=True)
    absent = ("c" * 64, "d" * 64)

    for prompt_hash in absent:
        with pytest.raises(PolicyUnavailableError):
            transport.complete(_request(prompt_hash))

    assert transport.misses == absent
    assert [store.load(prompt_hash) for prompt_hash in absent] == [None, None]
