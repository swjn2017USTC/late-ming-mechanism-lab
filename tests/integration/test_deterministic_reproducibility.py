"""Reproducibility: same config + same seed must imply the same output.

This is the central P01 acceptance criterion (RULES 15). Byte-level equality is asserted
for the Parquet artifacts; semantic equality is asserted for the digests and the recovered
event log, which are stable across Parquet writer versions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.events import events_from_frame
from late_ming_lab.core.kernel import SimulationKernel
from late_ming_lab.core.manifest import RunManifest
from late_ming_lab.storage.run_store import (
    CONFIG_SNAPSHOT_FILE,
    EVENTS_FILE,
    MANIFEST_FILE,
    RunStore,
)


@pytest.fixture
def config() -> SimulationConfig:
    return SimulationConfig.model_validate({"tick_count": 8, "warmup_ticks": 3, "root_seed": 4242})


def _run_into(root: Path, config: SimulationConfig) -> tuple[RunStore, Path]:
    store = RunStore(root)
    directory = store.write(SimulationKernel(config).run())
    return store, directory


def test_same_config_and_seed_reproduce_the_same_run(
    tmp_path: Path, config: SimulationConfig
) -> None:
    first_store, first_dir = _run_into(tmp_path / "first", config)
    second_store, second_dir = _run_into(tmp_path / "second", config)
    run_id = first_dir.name

    assert second_dir.name == run_id
    assert (first_dir / EVENTS_FILE).read_bytes() == (second_dir / EVENTS_FILE).read_bytes()
    assert (first_dir / CONFIG_SNAPSHOT_FILE).read_bytes() == (
        second_dir / CONFIG_SNAPSHOT_FILE
    ).read_bytes()

    first = first_store.read_manifest(run_id)
    second = second_store.read_manifest(run_id)
    assert first.deterministic_digest() == second.deterministic_digest()
    assert (
        first_store.read_summary(run_id).simulation_digest
        == second_store.read_summary(run_id).simulation_digest
    )


def test_stored_events_replay_identically(tmp_path: Path, config: SimulationConfig) -> None:
    store, directory = _run_into(tmp_path, config)
    run_id = directory.name

    stored = events_from_frame(store.read_events(run_id))
    replayed = SimulationKernel(config).run()

    assert [event.to_json() for event in stored] == [
        event.to_json() for event in events_from_frame(replayed.events)
    ]
    persisted = RunManifest.from_json((directory / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert persisted == store.read_manifest(run_id)


def test_the_seed_changes_run_identity_even_without_mechanisms(
    tmp_path: Path, config: SimulationConfig
) -> None:
    """P01 registers no system, so nothing draws yet: the seed changes identity, not output.

    The observable effect of the seed on *data* is proven in
    ``tests/unit/test_kernel.py::test_same_seed_replays_systems_exactly``, where a system
    draws from a stream.
    """
    baseline_store, baseline_dir = _run_into(tmp_path / "baseline", config)
    reseeded_store, reseeded_dir = _run_into(
        tmp_path / "reseeded", config.with_overrides(root_seed=config.root_seed + 1)
    )

    assert baseline_dir.name != reseeded_dir.name
    assert baseline_store.read_manifest(baseline_dir.name).root_seed != (
        reseeded_store.read_manifest(reseeded_dir.name).root_seed
    )
    assert baseline_store.read_events(baseline_dir.name).equals(
        reseeded_store.read_events(reseeded_dir.name)
    )


def test_the_macro_index_never_depends_on_the_seed(
    tmp_path: Path, config: SimulationConfig
) -> None:
    """The clock is a function of the configuration alone."""
    first_store, first_dir = _run_into(tmp_path / "first", config)
    second_store, second_dir = _run_into(
        tmp_path / "second", config.with_overrides(root_seed=config.root_seed + 1)
    )

    assert first_store.read_macro(first_dir.name).equals(second_store.read_macro(second_dir.name))
