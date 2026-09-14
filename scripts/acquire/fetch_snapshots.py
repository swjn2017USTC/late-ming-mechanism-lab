#!/usr/bin/env python
"""Acquire or verify the raw snapshots the manifest declares.

The manifest (`sources/snapshots/*.yaml`) is the record; this script is how the files behind it are
obtained or re-checked. Three rules it keeps, all of them the point of the record rather than
convenience:

```text
a human-only acquisition is never fetched here  the record says what a person is being asked for
nothing is written outside data/raw/private      that directory is gitignored, and must stay so
a file that does not hash to the record is deleted  a wrong file is worse than a missing one
```

```bash
uv run python scripts/acquire/fetch_snapshots.py --check    # verify; download nothing
uv run python scripts/acquire/fetch_snapshots.py             # fetch what is missing, then verify
uv run python scripts/acquire/fetch_snapshots.py --queue     # print the queue only a human can work
```
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path
from typing import Final

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src"))

from late_ming_lab.evidence.snapshots import (  # noqa: E402
    RAW_ROOT,
    AcquisitionMethod,
    SnapshotManifest,
    SnapshotRecord,
    load_snapshots,
)

USER_AGENT: Final[str] = "late-ming-mechanism-lab/0.1 (academic research; snapshot acquisition)"


def digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(record: SnapshotRecord, root: Path) -> str:
    """Return 'verified', 'absent', or a message describing the mismatch."""
    local = root / str(record.acquisition.local_path)
    if not local.is_file():
        return "absent"
    if local.stat().st_size != record.acquisition.bytes:
        return f"size {local.stat().st_size} != recorded {record.acquisition.bytes}"
    if digest_of(local) != record.acquisition.sha256:
        return "sha256 does not match the record"
    return "verified"


def fetch(record: SnapshotRecord, root: Path) -> str:
    """Download one record. Refuses anything the record does not permit."""
    if record.acquisition.method is not AcquisitionMethod.HTTP:
        return "skipped: not an http acquisition"
    local = root / str(record.acquisition.local_path)
    if not local.is_relative_to(root / RAW_ROOT):
        return f"refused: {local} is outside {RAW_ROOT}"
    local.parent.mkdir(parents=True, exist_ok=True)
    url = record.acquisition.fetch_url
    if not url:
        return "skipped: no fetch_url recorded"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
    except (OSError, ValueError) as error:
        return f"failed: {error}"
    local.write_bytes(payload)
    problem = verify(record, root)
    if problem != "verified":
        local.unlink()
        return f"refused and discarded: {problem}"
    return "downloaded and verified"


def report(record: SnapshotRecord, outcome: str) -> None:
    state = "acquired" if record.acquired else record.acquisition.method.value
    print(f"{record.id:34s} {state:8s} {outcome}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(REPOSITORY), help="repository root")
    parser.add_argument("--check", action="store_true", help="verify only; download nothing")
    parser.add_argument("--queue", action="store_true", help="print the human acquisition queue")
    arguments = parser.parse_args(argv)
    root = Path(arguments.root).resolve()
    manifest: SnapshotManifest = load_snapshots(root)

    if arguments.queue:
        for record in manifest.pending_records:
            print(f"{record.id}: {record.acquisition.human_note}")
        return 0

    failures = 0
    for record in manifest:
        if not record.acquired:
            report(record, f"queue (human): {record.acquisition.human_note}")
            continue
        outcome = verify(record, root)
        if outcome == "absent" and not arguments.check:
            outcome = fetch(record, root)
            outcome = verify(record, root) if outcome == "downloaded and verified" else outcome
        if outcome not in {"verified", "absent"}:
            failures += 1
        report(record, outcome)
    if failures:
        print(f"{failures} snapshot(s) do not match the manifest", file=sys.stderr)
        return 1
    print("ok: every present snapshot hashes to its record; absent files are simply not downloaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
