"""Atomic artifact I/O.

Run outputs are immutable: every artifact is written to a temporary file in the destination
directory and moved into place, so a partially written run is never observable, and a
repeated run of the same configuration overwrites its artifacts byte for byte rather than
appending to them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import polars as pl


def write_table(path: str | Path, frame: pl.DataFrame) -> Path:
    """Write ``frame`` as Parquet (Zstandard, with statistics)."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    frame.write_parquet(temporary, compression="zstd", statistics=True)
    os.replace(temporary, destination)
    return destination


def read_table(path: str | Path) -> pl.DataFrame:
    return pl.read_parquet(path)


def write_json(path: str | Path, payload: Any) -> Path:
    """Write canonical, human-readable JSON."""
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    return write_text(path, f"{text}\n")


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_text(path: str | Path, text: str) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")
