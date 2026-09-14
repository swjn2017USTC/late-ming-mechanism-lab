"""The environment checks: which questions they ask, and what they refuse to say.

The synthetic projects here are written to ``tmp_path`` on purpose. A check that only ever runs
against this repository cannot show that it *fails* when it should, and the failure that matters
most — a lockfile that no longer covers the declared dependencies — cannot be staged in the real
tree without breaking it.

Two rules are asserted directly rather than described: a credential-shaped variable is named and
its value never appears in the report, and a directory that is not a git repository is a warning
rather than a silent pass.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from late_ming_lab.env_checks import (
    API_KEY_VARIABLES,
    ENV_LLM_ENABLED,
    ERROR,
    INFO,
    WARNING,
    EnvironmentReport,
    Finding,
    check_environment,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: A key-shaped value that must never reach the report. It is not a credential, and it is not used
#: anywhere: its only job is to be looked for in the serialized findings.
FAKE_KEY = "sk-not-a-credential-only-a-marker"


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The checks read the process environment; each test decides what is in it."""
    for name in (ENV_LLM_ENABLED, *API_KEY_VARIABLES):
        monkeypatch.delenv(name, raising=False)


def _finding(report: EnvironmentReport, name: str) -> Finding:
    (finding,) = [item for item in report.findings if item.name == name]
    return finding


def _write_project(
    root: Path,
    *,
    dependencies: list[str],
    locked: list[str],
    requires_python: str = ">=3.12",
    locked_python: str | None = None,
) -> None:
    """A synthetic ``pyproject.toml``/``uv.lock`` pair, as uv would write them."""
    root.mkdir(parents=True, exist_ok=True)
    declared = ", ".join(f'"{dependency}"' for dependency in dependencies)
    (root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "synthetic"\n'
        'version = "0.1.0"\n'
        f'requires-python = "{requires_python}"\n'
        f"dependencies = [{declared}]\n",
        encoding="utf-8",
    )
    packages = "".join(f'[[package]]\nname = "{name}"\nversion = "1.0.0"\n\n' for name in locked)
    (root / "uv.lock").write_text(
        "version = 1\n"
        "revision = 3\n"
        f'requires-python = "{locked_python or requires_python}"\n\n'
        f"{packages}",
        encoding="utf-8",
    )


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )


def test_the_repository_environment_passes_and_serializes() -> None:
    report = check_environment(REPO_ROOT)

    assert report.ok()
    names = {finding.name for finding in report.findings}
    assert {"python", "uv-lock", "dependencies", "dotenv", "artifacts-root", "cards"} <= names

    payload = json.loads(report.to_json())
    assert payload["ok"] is True
    assert payload["findings"] == [asdict(finding) for finding in report.findings]


def test_a_consistent_project_and_lock_pass(tmp_path: Path) -> None:
    root = tmp_path / "clean"
    _write_project(root, dependencies=["polars>=1.0", "typer>=0.1"], locked=["polars", "typer"])

    report = check_environment(root)

    assert report.ok()
    assert _finding(report, "dependencies").severity == INFO
    assert _finding(report, "dependencies").ok
    # A directory that is not a git repository is a caveat, not a failure.
    assert _finding(report, "dotenv").severity == WARNING
    assert _finding(report, "dotenv").ok


def test_a_lock_missing_a_declared_dependency_is_an_error(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    _write_project(root, dependencies=["polars>=1.0", "typer>=0.1"], locked=["polars"])

    report = check_environment(root)

    dependencies = _finding(report, "dependencies")
    assert dependencies.severity == ERROR
    assert not dependencies.ok
    assert "typer" in dependencies.detail
    # Nothing else about this project is wrong, so the missing dependency is what fails it.
    assert [finding.name for finding in report.findings if not finding.ok] == ["dependencies"]
    assert not report.ok()


def test_a_lock_declaring_another_interpreter_is_an_error(tmp_path: Path) -> None:
    root = tmp_path / "mismatched"
    _write_project(
        root,
        dependencies=["polars>=1.0"],
        locked=["polars"],
        requires_python=">=3.12",
        locked_python=">=3.11",
    )

    lock = _finding(check_environment(root), "uv-lock")

    assert lock.severity == ERROR
    assert ">=3.11" in lock.detail and ">=3.12" in lock.detail


def test_a_tracked_env_file_is_an_error_and_the_key_is_never_printed(tmp_path: Path) -> None:
    root = tmp_path / "tracked"
    _write_project(root, dependencies=["polars>=1.0"], locked=["polars"])
    (root / ".env").write_text(f"USTC_LLM_API_KEY={FAKE_KEY}\n", encoding="utf-8")
    _git(root, "init", "--quiet")
    _git(root, "add", ".env")

    tracked = check_environment(root)
    dotenv = _finding(tracked, "dotenv")
    assert dotenv.severity == ERROR
    assert not dotenv.ok
    assert not tracked.ok()
    assert FAKE_KEY not in tracked.to_json()

    _git(root, "rm", "--cached", "--force", ".env")
    (root / ".gitignore").write_text(".env\n", encoding="utf-8")

    ignored = check_environment(root)
    assert _finding(ignored, "dotenv").ok
    assert _finding(ignored, "dotenv").severity == INFO
    assert ignored.ok()
    assert FAKE_KEY not in ignored.to_json()


def test_the_runtime_switch_is_off_by_default_and_on_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "switch"
    _write_project(root, dependencies=["polars>=1.0"], locked=["polars"])

    for value in ("0", "false", "False"):
        monkeypatch.setenv(ENV_LLM_ENABLED, value)
        assert _finding(check_environment(root), "llm-enabled").ok

    monkeypatch.setenv(ENV_LLM_ENABLED, "1")
    enabled = _finding(check_environment(root), "llm-enabled")
    assert enabled.severity == ERROR
    assert not enabled.ok
    assert not check_environment(root).ok()


def test_a_visible_key_variable_is_named_and_its_value_is_never_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "secrets"
    _write_project(root, dependencies=["polars>=1.0"], locked=["polars"])
    monkeypatch.setenv("USTC_API_KEY", FAKE_KEY)

    report = check_environment(root)

    named = _finding(report, "api-key")
    assert named.severity == WARNING
    assert named.ok
    assert "USTC_API_KEY" in named.detail
    assert FAKE_KEY not in report.to_json()
