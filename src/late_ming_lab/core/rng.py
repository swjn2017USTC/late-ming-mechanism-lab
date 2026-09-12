"""Subsystem random streams.

One root ``SeedSequence`` is split into one independent stream per subsystem, so that
counterfactuals can reuse common random numbers and so that a draw in one subsystem can
never perturb another. A single global ``random.seed(...)`` is prohibited (RULES 15).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

import numpy as np

#: 128 bits of state derived per subsystem.
STATE_WORDS: Final[int] = 4


class RngStream(StrEnum):
    """Named randomness streams; declaration order fixes the spawn order."""

    CLIMATE = "climate"
    HOUSEHOLD = "household"
    MARKET = "market"
    MIGRATION = "migration"
    MILITARY = "military"
    REBEL = "rebel"
    DECISION = "decision"


RNG_STREAMS: Final[tuple[RngStream, ...]] = tuple(RngStream)


def derive_stream_seeds(root_seed: int) -> dict[str, int]:
    """Derive one 128-bit seed per subsystem from a single root seed.

    ``SeedSequence.spawn`` guarantees the children are not correlated with each other or
    with the parent, which is what makes stream independence a property of construction
    rather than of hope.
    """
    if root_seed < 0:
        raise ValueError(f"root_seed must be non-negative, got {root_seed}")
    children = np.random.SeedSequence(root_seed).spawn(len(RNG_STREAMS))
    return {
        stream.value: _child_seed(child)
        for stream, child in zip(RNG_STREAMS, children, strict=True)
    }


def _child_seed(child: np.random.SeedSequence) -> int:
    words = np.asarray(child.generate_state(STATE_WORDS, dtype=np.uint32))
    return int.from_bytes(words.tobytes(), "little")


class RngStreams:
    """The fixed set of subsystem generators belonging to one run."""

    def __init__(self, root_seed: int) -> None:
        self._root_seed = root_seed
        self._seeds = derive_stream_seeds(root_seed)
        self._generators: dict[RngStream, np.random.Generator] = {
            stream: np.random.default_rng(np.random.SeedSequence(self._seeds[stream.value]))
            for stream in RNG_STREAMS
        }

    @property
    def root_seed(self) -> int:
        return self._root_seed

    @property
    def subsystem_seeds(self) -> Mapping[str, int]:
        """Read-only mapping of stream name to derived seed, as recorded in the manifest."""
        return MappingProxyType(self._seeds)

    def generator(self, stream: RngStream | str) -> np.random.Generator:
        """The persistent generator of ``stream``; drawing from it advances only itself."""
        try:
            return self._generators[RngStream(stream)]
        except ValueError as error:
            known = ", ".join(stream.value for stream in RNG_STREAMS)
            raise ValueError(f"unknown RNG stream {stream!r}; known streams: {known}") from error

    def draw(self, stream: RngStream | str) -> float:
        """One uniform draw in ``[0, 1)`` from ``stream``."""
        return float(self.generator(stream).random())
