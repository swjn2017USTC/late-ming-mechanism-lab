"""DuckDB query helper over immutable run outputs.

DuckDB reads the Parquet artifacts directly, so the run warehouse is a query layer with no
copied state: cross-run and cross-run analysis always operates on the files that were
actually written.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Self

import duckdb
import polars as pl

from late_ming_lab.storage.run_store import (
    EVENTS_FILE,
    MACRO_FILE,
    MANIFEST_FILE,
    RunStore,
)


class RunWarehouse:
    """SQL access to the artifacts of a :class:`RunStore`."""

    def __init__(self, store: RunStore, database: str | Path = ":memory:") -> None:
        self._store = store
        self._connection = duckdb.connect(str(database))

    def execute(self, sql: str, parameters: Sequence[Any] | None = None) -> pl.DataFrame:
        """Run SQL against the warehouse and return a Polars frame."""
        cursor = (
            self._connection.execute(sql, parameters)
            if parameters
            else self._connection.execute(sql)
        )
        return cursor.pl()

    def events(self, run_id: str) -> pl.DataFrame:
        """The event log of one run, in replay order."""
        return self.execute(
            f"SELECT * FROM read_parquet({self._literal(self._artifact(run_id, EVENTS_FILE))}) "
            "ORDER BY tick, seq"
        )

    def macro(self, run_id: str) -> pl.DataFrame:
        """The macro index of one run, in tick order."""
        return self.execute(
            f"SELECT * FROM read_parquet({self._literal(self._artifact(run_id, MACRO_FILE))}) "
            "ORDER BY tick"
        )

    def manifests(self) -> pl.DataFrame:
        """Every run manifest under the store root, one row per run."""
        run_ids = self._store.list_runs()
        if not run_ids:
            raise FileNotFoundError(f"no runs under {self._store.root}")
        pattern = f"{self._store.root}/*/{MANIFEST_FILE}"
        return self.execute(f"SELECT * FROM read_json_auto({self._literal(pattern)})")

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _artifact(self, run_id: str, filename: str) -> Path:
        return self._store.run_dir(run_id) / filename

    @staticmethod
    def _literal(value: str | Path) -> str:
        return "'" + str(value).replace("'", "''") + "'"
