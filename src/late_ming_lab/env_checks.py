"""Environment validation: what ``late-ming-lab doctor`` checks before a run is trusted.

Every check is one :class:`Finding`, so the report can be printed, serialized or asserted on without
the caller knowing which question was asked. Two rules shape the checks themselves:

* **a secret is never read, and therefore never printed.** The API-key check names the variable it
  found and says nothing about its value; that is the whole of its report.
* **a check that cannot be answered says so.** Outside a git repository, or with a lockfile that
  cannot be parsed, the finding is a warning that names what could not be verified rather than a
  silent pass.

Severity is how much a failing check matters, not whether it failed: ``ok`` on a finding means the
check itself was satisfied, so an unverifiable check is ``ok`` with a warning.
:meth:`EnvironmentReport.ok` is false only when a finding at severity ``error`` is not ``ok``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

#: The files the checks read, all relative to the repository root.
PYPROJECT_FILE: Final[str] = "pyproject.toml"
LOCK_FILE: Final[str] = "uv.lock"
ARTIFACTS_ROOT: Final[str] = "outputs"
CARDS_FILE: Final[str] = "docs/mechanisms/cards.yaml"
P10_MANIFEST_FILE: Final[str] = "outputs/experiments/p10-ablations/manifest.json"

#: The switch the runtime decision layer reads. Off is the environment this check expects: a compute
#: node runs the model with no credential and no endpoint, and a batch that turns the layer on there
#: is a configuration error. An operator turning it on for a local runtime run is a *declared* state
#: (ADR 0003), and `doctor` reports it as such rather than as a fault.
#:
#: The check reads the same environment the policy reads — the process's, with the repository's
#: `.env` underneath it — so `doctor` cannot say "off" while the policy is calling a model.
ENV_LLM_ENABLED: Final[str] = "USTC_LLM_ENABLED"
_OFF_VALUES: Final[tuple[str, ...]] = ("", "0", "false", "no", "off")

#: The variables that look like credentials. They are checked for *presence* only, and named by
#: name; nothing in this module reads, copies, logs or prints a value.
API_KEY_VARIABLES: Final[tuple[str, ...]] = ("USTC_API_KEY", "USTC_LLM_API_KEY", "OPENAI_API_KEY")

ERROR: Final[str] = "error"
WARNING: Final[str] = "warning"
INFO: Final[str] = "info"

#: A PEP 508 requirement's name: everything before the version specifier, the extra or the marker.
_REQUIREMENT_NAME: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9._-]+")

#: A `requires-python` clause this checker can decide. `~=` and the wildcard forms are refused
#: rather than approximated: an interpreter check that guesses is worse than one that refuses.
_CLAUSE: Final[re.Pattern[str]] = re.compile(r"^(==|!=|>=|<=|>|<)\s*(\d+(?:\.\d+)*)$")


@dataclass(frozen=True, slots=True)
class Finding:
    """One answered question about the environment."""

    name: str
    ok: bool
    detail: str
    severity: str


@dataclass(frozen=True, slots=True)
class EnvironmentReport:
    """Every finding, in the order the checks were made."""

    findings: tuple[Finding, ...]

    def ok(self) -> bool:
        """Whether the environment passed: no finding at severity ``error`` failed."""
        return all(finding.ok for finding in self.findings if finding.severity == ERROR)

    def to_json(self) -> str:
        return json.dumps(
            {"ok": self.ok(), "findings": [asdict(finding) for finding in self.findings]},
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )


def check_environment(root: str | Path) -> EnvironmentReport:
    """Check the interpreter, the lock, the secret surface and the artifact roots under ``root``."""
    repository_root = Path(root)
    project, project_error = _load_toml(repository_root / PYPROJECT_FILE)
    lock, lock_error = _load_toml(repository_root / LOCK_FILE)
    return EnvironmentReport(
        findings=(
            _python_finding(project, project_error),
            _lock_finding(project, lock, lock_error),
            _dependencies_finding(project, project_error, lock, lock_error),
            _dotenv_finding(repository_root),
            _api_key_finding(),
            _llm_switch_finding(),
            _artifacts_root_finding(repository_root),
            _presence_finding("cards", repository_root, CARDS_FILE, "the parameter cards"),
            _presence_finding(
                "p10-artifacts",
                repository_root,
                P10_MANIFEST_FILE,
                "the P10 ablation batch a report is generated from",
            ),
        )
    )


def _load_toml(path: Path) -> tuple[dict[str, Any] | None, str]:
    """A TOML file, or the reason it could not be read."""
    if not path.is_file():
        return None, f"{path.name} does not exist"
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle), ""
    except (tomllib.TOMLDecodeError, OSError) as error:
        return None, f"{path.name} could not be parsed: {error}"


def _requires_python(project: dict[str, Any] | None) -> str | None:
    if project is None:
        return None
    section = project.get("project")
    declared = section.get("requires-python") if isinstance(section, dict) else None
    return declared if isinstance(declared, str) and declared.strip() else None


def _python_finding(project: dict[str, Any] | None, error: str) -> Finding:
    declared = _requires_python(project)
    if declared is None:
        return Finding(
            "python", False, f"{PYPROJECT_FILE} declares no requires-python ({error})", ERROR
        )
    running = sys.version_info[:3]
    satisfied, reason = _satisfies(declared, running)
    rendered = ".".join(str(part) for part in running)
    if not satisfied:
        return Finding(
            "python",
            False,
            f"running Python {rendered} does not satisfy requires-python {declared!r}: {reason}",
            ERROR,
        )
    return Finding(
        "python", True, f"running Python {rendered} satisfies requires-python {declared!r}", INFO
    )


def _lock_finding(
    project: dict[str, Any] | None, lock: dict[str, Any] | None, error: str
) -> Finding:
    if lock is None:
        return Finding("uv-lock", False, f"{error}: the environment is not reproducible", ERROR)
    locked = lock.get("requires-python")
    if not isinstance(locked, str) or not locked.strip():
        return Finding("uv-lock", False, f"{LOCK_FILE} declares no requires-python", ERROR)
    declared = _requires_python(project)
    if declared is not None and declared != locked:
        return Finding(
            "uv-lock",
            False,
            f"{LOCK_FILE} requires-python {locked!r} differs from {PYPROJECT_FILE}'s "
            f"{declared!r}; the lock was not made from this project file",
            ERROR,
        )
    return Finding(
        "uv-lock",
        True,
        f"{LOCK_FILE} exists and declares requires-python {locked!r}, as {PYPROJECT_FILE} does",
        INFO,
    )


def _dependencies_finding(
    project: dict[str, Any] | None,
    project_error: str,
    lock: dict[str, Any] | None,
    lock_error: str,
) -> Finding:
    if project is None:
        return Finding("dependencies", False, project_error, ERROR)
    section = project.get("project")
    declared = section.get("dependencies") if isinstance(section, dict) else None
    if not isinstance(declared, list):
        return Finding("dependencies", False, f"{PYPROJECT_FILE} declares no dependencies", ERROR)
    names = sorted({_requirement_name(str(requirement)) for requirement in declared})
    if lock is None:
        return Finding(
            "dependencies",
            False,
            f"the declared dependencies cannot be checked against a lock: {lock_error}",
            ERROR,
        )
    locked = {
        _requirement_name(str(entry.get("name", "")))
        for entry in lock.get("package", [])
        if isinstance(entry, dict)
    }
    missing = [name for name in names if name not in locked]
    if missing:
        return Finding(
            "dependencies",
            False,
            f"{LOCK_FILE} does not declare {', '.join(missing)}: the lock is not this project's",
            ERROR,
        )
    return Finding(
        "dependencies",
        True,
        f"every declared dependency ({len(names)}) appears in {LOCK_FILE}",
        INFO,
    )


def _requirement_name(requirement: str) -> str:
    match = _REQUIREMENT_NAME.match(requirement.strip())
    return match.group(0).lower().replace("_", "-") if match else requirement.strip().lower()


def _dotenv_finding(repository_root: Path) -> Finding:
    """Whether ``.env`` is tracked. A tracked ``.env`` is an error: it carries the key."""
    listed = _git(repository_root, "ls-files", "--", ".env")
    if listed is None:
        return Finding(
            "dotenv",
            True,
            f"git cannot answer here, so whether .env is tracked was not verified under "
            f"{repository_root}",
            WARNING,
        )
    if listed.stdout.strip():
        return Finding(
            "dotenv",
            False,
            ".env is tracked by git; it must stay untracked, and only .env.example is committed",
            ERROR,
        )
    ignored = _git(repository_root, "check-ignore", "--quiet", ".env")
    if ignored is None or ignored.returncode != 0:
        return Finding(
            "dotenv",
            True,
            ".env is not tracked by git, but git does not ignore it either: an untracked file is "
            "one `git add -A` away from being committed",
            WARNING,
        )
    return Finding("dotenv", True, ".env is not tracked by git, and git ignores it", INFO)


def _api_key_finding() -> Finding:
    """Which credential-shaped variables are visible, by name, and never by value."""
    present = [name for name in API_KEY_VARIABLES if os.environ.get(name)]
    if present:
        return Finding(
            "api-key",
            True,
            f"{', '.join(present)} is set in this environment; the value is not read, printed or "
            "logged here, and a batch run does not need it",
            WARNING,
        )
    return Finding("api-key", True, "no credential-shaped variable is visible here", INFO)


def _llm_switch_finding() -> Finding:
    from late_ming_lab.policies.ustc_v41 import _process_environment

    value = _process_environment().get(ENV_LLM_ENABLED)
    if value is None:
        return Finding(
            "llm-enabled", True, f"{ENV_LLM_ENABLED} is unset: the runtime layer is off", INFO
        )
    if value.strip().lower() in _OFF_VALUES:
        return Finding(
            "llm-enabled", True, f"{ENV_LLM_ENABLED}={value!r}: the runtime layer is off", INFO
        )
    return Finding(
        "llm-enabled",
        True,
        f"{ENV_LLM_ENABLED}={value!r}: the runtime decision layer is on for this environment. "
        "That is a declared operator state (ADR 0003), and it must never hold on a compute node: "
        "the node sets no endpoint and no credential, and a batch that calls a model from one is a "
        "configuration error",
        WARNING,
    )


def _artifacts_root_finding(repository_root: Path) -> Finding:
    target = repository_root / ARTIFACTS_ROOT
    if _writable(target):
        return Finding("artifacts-root", True, f"{ARTIFACTS_ROOT}/ is writable", INFO)
    return Finding(
        "artifacts-root",
        False,
        f"{target} is not writable, so a run could not write its artifacts there",
        ERROR,
    )


def _writable(path: Path) -> bool:
    """Whether ``path`` can be written to, checked at the nearest directory that exists."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return os.access(probe, os.W_OK)


def _presence_finding(name: str, repository_root: Path, relative: str, description: str) -> Finding:
    if (repository_root / relative).exists():
        return Finding(name, True, f"{relative} is present", INFO)
    return Finding(
        name, True, f"{relative} is absent: {description} has not been produced here yet", INFO
    )


def _git(repository_root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    """Run one git query, or return ``None`` when git cannot answer for this directory."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository_root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    # 128 is git's "not a repository here"; anything else is an answer, even an empty one.
    return None if completed.returncode == 128 else completed


def _satisfies(specifier: str, version: tuple[int, ...]) -> tuple[bool, str]:
    """Whether ``version`` satisfies every clause of a ``requires-python`` specifier."""
    for clause in specifier.split(","):
        text = clause.strip()
        if not text:
            continue
        match = _CLAUSE.match(text)
        if match is None:
            return False, f"the clause {text!r} is not one this check can decide"
        bound = tuple(int(part) for part in match.group(2).split("."))
        left, right = _padded(version, bound)
        if not _compare(match.group(1), left, right):
            return False, f"{_render(version)} fails {text}"
    return True, ""


def _padded(
    left: tuple[int, ...], right: tuple[int, ...]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Both versions at the same width, so ``3.12`` and ``3.12.0`` are the same version."""
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)), right + (0,) * (width - len(right))


def _compare(operator: str, left: tuple[int, ...], right: tuple[int, ...]) -> bool:
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    return left < right


def _render(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)
