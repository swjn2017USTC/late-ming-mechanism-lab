"""The acquisition script, exercised the way an operator runs it: check first, queue second.

The script is the only path from the manifest to a raw file, so the two things it must never do are
tested here rather than trusted: it verifies hashes without touching the network, and it refuses to
fetch anything the manifest marks as a human acquisition.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "acquire" / "fetch_snapshots.py"


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(ROOT), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_checking_verifies_every_present_snapshot_without_downloading() -> None:
    completed = _run("--check")
    assert completed.returncode == 0, completed.stderr
    assert "ok:" in completed.stdout
    assert "downloaded and verified" not in completed.stdout


def test_the_queue_names_what_only_a_person_can_obtain() -> None:
    completed = _run("--queue")
    assert completed.returncode == 0, completed.stderr
    assert "reaches-sinica-full-database" in completed.stdout
    assert "account" in completed.stdout
