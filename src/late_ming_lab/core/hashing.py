"""Canonical hashing helpers shared by configuration, events and manifests.

Every deterministic artifact of this project is identified by the SHA-256 of its canonical
JSON form, so two runs of the same code, configuration and seed produce the same digest on
any machine. Canonical means: sorted keys, no insignificant whitespace, and Python's
shortest round-tripping float rendering.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any


def canonical_json(payload: Any) -> str:
    """Render ``payload`` as canonical JSON."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_text(text: str) -> str:
    """SHA-256 hex digest of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_records(records: Iterable[str]) -> str:
    """SHA-256 hex digest of an ordered sequence of records, one record per line."""
    digest = hashlib.sha256()
    for record in records:
        digest.update(record.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()
