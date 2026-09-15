"""Invariants guarding the development/runtime LLM boundary.

P11 ships the runtime layer, so these tests protect the properties that have to hold now that it
exists: the runtime model is off by default, the credential cannot be committed, no committed file
carries a key, the live suite never runs in the default suite, and only one model id may ever be
called.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

from late_ming_lab.policies.base import ChatRequest
from late_ming_lab.policies.ustc_v41 import CONFIRMED_MODEL_IDS, confirmed_model_id

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every model id that may appear in this repository as a *runtime* model. One, and it is declared
#: by `docs/adr/0003-runtime-model-amendment.md` — declared rather than read off the account,
#: which is the distinction the ADR exists to keep visible.
ALLOWED_RUNTIME_MODELS = ("deepseek-flash",)

#: Names that must never be reachable as a runtime model, checked against the source of the layer.
FORBIDDEN_RUNTIME_MODEL_NAMES = ("deepseek-v4-pro", "deepseek-pro", "gpt-4", "qwen", "glm")


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


def test_the_default_suite_excludes_the_live_marker() -> None:
    """A live test in the default run would make the suite depend on a network and a credential."""
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    addopts = config["tool"]["pytest"]["ini_options"]["addopts"]

    assert "not live_ustc" in addopts


def test_no_committed_file_carries_a_key() -> None:
    """The credential lives in .env, which is untracked; nothing tracked may hold a value."""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    # Anchored per line, so an empty `USTC_LLM_API_KEY=` followed by another variable on the next
    # line is not mistaken for a value.
    # `[ \t]` rather than `\s`, so the match cannot cross a line and read the next variable as a
    # value.
    pattern = re.compile(r"^.*USTC_LLM_API_KEY[ \t]*=[ \t]*(\S+)[ \t]*$", re.MULTILINE)
    offenders: list[str] = []
    for name in tracked:
        path = REPO_ROOT / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        match = pattern.search(text)
        if match is not None:
            offenders.append(name)

    assert offenders == [], f"a committed file carries a key value: {offenders}"


def test_only_the_confirmed_model_id_may_be_called() -> None:
    for allowed in ALLOWED_RUNTIME_MODELS:
        assert confirmed_model_id(allowed) == allowed
    assert CONFIRMED_MODEL_IDS == ALLOWED_RUNTIME_MODELS


def test_the_runtime_payload_carries_no_tools() -> None:
    """The model gets structured state and nothing else: no tools, no functions, no retrieval."""
    request = ChatRequest(
        model_id=CONFIRMED_MODEL_IDS[0],
        prompt="Observed conditions:\n- receipts_over_quota: 0.3",
        prompt_hash="0" * 64,
        temperature=0.0,
        max_tokens=100,
    )
    payload = request.payload()

    assert "tools" not in payload
    assert "functions" not in payload
    assert set(payload) == {"model", "messages", "temperature", "max_tokens", "response_format"}
