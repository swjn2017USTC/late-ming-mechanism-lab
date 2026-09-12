"""Run directory layout and access.

```text
outputs/runs/<run_id>/
├── manifest.json
├── config.snapshot.yaml
├── macro_timeseries.parquet
├── agent_events.parquet
└── summary.json
```

The run id is derived from scenario, root seed and configuration hash, so re-running the
same configuration and seed targets the same directory. Writing over a directory that holds
a *different* run is refused rather than silently mixing provenance; the caller can pass a
distinct run label.

County, parameter and decision-trace artifacts are absent because P01 produces no such
data. Each arrives with the phase that produces it.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from late_ming_lab.core.kernel import KernelResult
from late_ming_lab.core.manifest import RunManifest, RunSummary
from late_ming_lab.storage.tables import (
    read_json,
    read_table,
    read_text,
    write_json,
    write_table,
    write_text,
)

MANIFEST_FILE = "manifest.json"
CONFIG_SNAPSHOT_FILE = "config.snapshot.yaml"
EVENTS_FILE = "agent_events.parquet"
MACRO_FILE = "macro_timeseries.parquet"
SUMMARY_FILE = "summary.json"

_RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class RunConflictError(RuntimeError):
    """Raised when a run directory already holds a different run."""


class UnknownRunError(FileNotFoundError):
    """Raised when a run id has no manifest under this store root."""


class RunStore:
    """Reads and writes immutable run directories under one root."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def run_dir(self, run_id: str) -> Path:
        return self._root / _validated_run_id(run_id)

    def write(self, result: KernelResult) -> Path:
        """Persist one kernel result; return the run directory."""
        directory = self.run_dir(result.manifest.run_id)
        manifest_path = directory / MANIFEST_FILE
        if manifest_path.is_file():
            previous = RunManifest.from_json(read_text(manifest_path))
            if previous.deterministic_digest() != result.manifest.deterministic_digest():
                raise RunConflictError(
                    f"{directory} already holds a different run "
                    f"(code revision, configuration or seed changed); "
                    "pass a distinct run label or remove the directory"
                )
        directory.mkdir(parents=True, exist_ok=True)
        write_text(directory / CONFIG_SNAPSHOT_FILE, result.config.to_yaml())
        write_table(directory / EVENTS_FILE, result.events)
        write_table(directory / MACRO_FILE, result.macro)
        write_json(directory / SUMMARY_FILE, result.summary.model_dump(mode="json"))
        # Written last: the manifest marks a complete run.
        write_json(manifest_path, result.manifest.model_dump(mode="json"))
        return directory

    def list_runs(self) -> list[str]:
        if not self._root.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self._root.iterdir()
            if entry.is_dir() and (entry / MANIFEST_FILE).is_file()
        )

    def read_manifest(self, run_id: str) -> RunManifest:
        return RunManifest.from_json(read_text(self._existing_run_dir(run_id) / MANIFEST_FILE))

    def read_summary(self, run_id: str) -> RunSummary:
        payload = read_json(self._existing_run_dir(run_id) / SUMMARY_FILE)
        return RunSummary.model_validate(payload)

    def read_events(self, run_id: str) -> pl.DataFrame:
        return read_table(self._existing_run_dir(run_id) / EVENTS_FILE)

    def read_macro(self, run_id: str) -> pl.DataFrame:
        return read_table(self._existing_run_dir(run_id) / MACRO_FILE)

    def read_config_snapshot(self, run_id: str) -> str:
        return read_text(self._existing_run_dir(run_id) / CONFIG_SNAPSHOT_FILE)

    def _existing_run_dir(self, run_id: str) -> Path:
        directory = self.run_dir(run_id)
        if not (directory / MANIFEST_FILE).is_file():
            raise UnknownRunError(f"no run {run_id!r} under {self._root}")
        return directory


def _validated_run_id(run_id: str) -> str:
    if not _RUN_ID_PATTERN.match(run_id):
        raise ValueError(
            f"invalid run id {run_id!r}: expected lowercase alphanumerics, '.', '_' or '-'"
        )
    return run_id
