"""RNG contract: one root seed, seven independent streams, no shared state."""

from __future__ import annotations

import pytest

from late_ming_lab.core.rng import RNG_STREAMS, RngStream, RngStreams, derive_stream_seeds


def test_every_subsystem_has_a_stream() -> None:
    assert [stream.value for stream in RNG_STREAMS] == [
        "climate",
        "household",
        "market",
        "migration",
        "military",
        "rebel",
        "decision",
    ]


def test_stream_seeds_are_derived_deterministically_from_the_root_seed() -> None:
    first = derive_stream_seeds(42)
    second = derive_stream_seeds(42)

    assert first == second
    assert sorted(first) == sorted(stream.value for stream in RNG_STREAMS)
    assert len(set(first.values())) == len(RNG_STREAMS)
    assert derive_stream_seeds(43) != first


def test_same_root_seed_reproduces_every_draw() -> None:
    first = RngStreams(20260912)
    second = RngStreams(20260912)

    for stream in RNG_STREAMS:
        assert [first.draw(stream) for _ in range(4)] == [second.draw(stream) for _ in range(4)]


def test_different_root_seeds_produce_different_draws() -> None:
    first = [RngStreams(1).draw(RngStream.HOUSEHOLD) for _ in range(1)]
    second = [RngStreams(2).draw(RngStream.HOUSEHOLD) for _ in range(1)]

    assert first != second


def test_drawing_from_one_stream_never_disturbs_another() -> None:
    untouched = RngStreams(7)
    disturbed = RngStreams(7)

    expected = [untouched.draw(RngStream.MARKET) for _ in range(5)]

    for _ in range(31):
        disturbed.draw(RngStream.HOUSEHOLD)
    for stream in (RngStream.CLIMATE, RngStream.MILITARY, RngStream.DECISION):
        disturbed.draw(stream)

    assert [disturbed.draw(RngStream.MARKET) for _ in range(5)] == expected


def test_streams_start_from_distinct_positions() -> None:
    streams = RngStreams(20260912)

    first_draws = [round(streams.draw(stream), 12) for stream in RNG_STREAMS]

    assert len(set(first_draws)) == len(RNG_STREAMS)


def test_subsystem_seeds_are_reported_read_only() -> None:
    streams = RngStreams(3)

    assert dict(streams.subsystem_seeds) == derive_stream_seeds(3)

    with pytest.raises(TypeError):
        streams.subsystem_seeds["climate"] = 0  # type: ignore[index]


def test_unknown_streams_are_rejected() -> None:
    streams = RngStreams(1)

    with pytest.raises(ValueError, match="unknown RNG stream"):
        streams.generator("harvest")
    with pytest.raises(ValueError):
        derive_stream_seeds(-1)
