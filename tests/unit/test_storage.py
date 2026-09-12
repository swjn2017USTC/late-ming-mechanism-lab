"""Storage contract: run layout, conflict refusal, Parquet and SQL access."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import polars as pl
import pytest

from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import KernelResult, SimulationKernel
from late_ming_lab.storage.run_store import (
    CONFIG_SNAPSHOT_FILE,
    EVENTS_FILE,
    MACRO_FILE,
    MANIFEST_FILE,
    SUMMARY_FILE,
    RunConflictError,
    RunStore,
    UnknownRunError,
)
from late_ming_lab.storage.tables import read_json, read_table, read_text, write_json, write_table
from late_ming_lab.storage.warehouse import RunWarehouse


def _run(store: RunStore, **config_overrides: object) -> KernelResult:
    config = SimulationConfig.model_validate(
        {"tick_count": 4, "warmup_ticks": 1, **config_overrides}
    )
    result = SimulationKernel(config).run()
    store.write(result)
    return result


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "runs")


def test_tables_round_trip(tmp_path: Path) -> None:
    frame = pl.DataFrame({"a": [1, 2], "b": ["x", None]})
    path = write_table(tmp_path / "nested" / "table.parquet", frame)

    assert path.is_file()
    assert read_table(path).equals(frame)
    assert not list(path.parent.glob("*.tmp"))


def test_json_artifacts_are_canonical(tmp_path: Path) -> None:
    path = write_json(tmp_path / "payload.json", {"b": 1, "a": [1, 2]})

    assert read_text(path) == '{\n  "a": [\n    1,\n    2\n  ],\n  "b": 1\n}\n'
    assert read_json(path) == {"a": [1, 2], "b": 1}


def test_run_layout(store: RunStore) -> None:
    result = _run(store)
    directory = store.run_dir(result.manifest.run_id)

    assert sorted(entry.name for entry in directory.iterdir()) == sorted(
        [
            MANIFEST_FILE,
            CONFIG_SNAPSHOT_FILE,
            EVENTS_FILE,
            MACRO_FILE,
            SUMMARY_FILE,
        ]
    )
    assert store.list_runs() == [result.manifest.run_id]


def test_run_artifacts_read_back_identically(store: RunStore) -> None:
    result = _run(store)
    run_id = result.manifest.run_id

    assert store.read_manifest(run_id) == result.manifest
    assert store.read_summary(run_id) == result.summary
    assert store.read_events(run_id).equals(result.events)
    assert store.read_macro(run_id).equals(result.macro)
    assert SimulationConfig.from_yaml(store.read_config_snapshot(run_id)) == result.config, (
        "the config snapshot must reproduce the configuration that was hashed"
    )


def test_repeating_a_run_overwrites_identical_artifacts(store: RunStore) -> None:
    result = _run(store)
    events_path = store.run_dir(result.manifest.run_id) / EVENTS_FILE
    first_bytes = events_path.read_bytes()

    repeat = _run(store)

    assert repeat.manifest.deterministic_digest() == result.manifest.deterministic_digest()
    assert events_path.read_bytes() == first_bytes


def test_conflicting_provenance_is_refused(store: RunStore) -> None:
    result = _run(store)
    foreign = dataclasses.replace(
        result, manifest=result.manifest.model_copy(update={"git_sha": "f" * 40})
    )

    with pytest.raises(RunConflictError, match="different run"):
        store.write(foreign)


def test_unknown_and_malformed_run_ids_are_rejected(store: RunStore) -> None:
    _run(store)

    with pytest.raises(UnknownRunError):
        store.read_manifest("kernel-smoke-1-000000000000")
    with pytest.raises(ValueError, match="invalid run id"):
        store.run_dir("../escape")

    empty = RunStore(store.root / "does-not-exist")
    assert empty.list_runs() == []


def test_a_partial_run_is_never_visible(store: RunStore) -> None:
    result = _run(store)
    directory = store.run_dir(result.manifest.run_id)

    # A directory without a manifest is not a run.
    (directory / MANIFEST_FILE).unlink()
    assert store.list_runs() == []
    with pytest.raises(UnknownRunError):
        store.read_summary(result.manifest.run_id)


def test_warehouse_queries_the_written_artifacts(store: RunStore) -> None:
    result = _run(store)
    run_id = result.manifest.run_id

    with RunWarehouse(store) as warehouse:
        events = warehouse.events(run_id)
        macro = warehouse.macro(run_id)
        grouped = warehouse.execute(
            f"SELECT period, count(*) AS ticks FROM "
            f"read_parquet('{store.run_dir(run_id) / MACRO_FILE}') GROUP BY period ORDER BY period"
        )
        summary_glob = f"{store.root}/*/{SUMMARY_FILE}"
        summaries = warehouse.execute(
            f"SELECT event_count, simulation_digest FROM read_json_auto('{summary_glob}')"
        )
        manifests = warehouse.manifests()

    assert events.height == 4
    assert events["tick"].to_list() == [0, 1, 2, 3]
    assert macro.height == 4
    assert grouped.to_dicts() == [
        {"period": "shock", "ticks": 3},
        {"period": "warmup", "ticks": 1},
    ]
    assert manifests["run_id"].to_list() == [run_id]
    assert manifests["config_hash"].to_list() == [result.manifest.config_hash]
    assert manifests["llm_enabled"].to_list() == [False]
    assert summaries.to_dicts() == [
        {"event_count": 4, "simulation_digest": result.summary.simulation_digest}
    ]


def test_warehouse_reports_an_empty_store(store: RunStore) -> None:
    with RunWarehouse(store) as warehouse, pytest.raises(FileNotFoundError, match="no runs"):
        warehouse.manifests()


def test_warehouse_rejects_path_traversal_run_ids(store: RunStore) -> None:
    with (
        RunWarehouse(store) as warehouse,
        pytest.raises(ValueError, match="invalid run id"),
    ):
        warehouse.events("../../etc")
