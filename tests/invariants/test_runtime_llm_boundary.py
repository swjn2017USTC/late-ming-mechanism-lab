"""Invariants guarding the development/runtime LLM boundary.

P00 ships no runtime LLM layer, so these tests protect the two properties that must hold
before that layer exists: the runtime LLM is off by default, and the USTC credential
cannot be committed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_runtime_llm_disabled_by_default() -> None:
    env = _read_env_example()

    assert env["USTC_LLM_ENABLED"] == "0"


def test_ustc_credential_cannot_be_committed() -> None:
    assert _git("ls-files", "--", ".env").stdout.strip() == "", ".env must not be tracked"
    assert _git("check-ignore", "-q", ".env").returncode == 0, ".env must be gitignored"
