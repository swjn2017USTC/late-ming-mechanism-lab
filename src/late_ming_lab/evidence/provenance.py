"""Runtime provenance: which code revision produced an output.

The repository is discovered by walking up from the working directory, falling back to the
installed package location, so a run started from anywhere still records its code identity.
Missing or unavailable git yields ``None`` rather than a fabricated revision (RULES 14).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

GIT_TIMEOUT_SECONDS: Final[float] = 10.0


@dataclass(frozen=True, slots=True)
class Provenance:
    """Code identity of a run; ``None`` marks provenance that could not be observed."""

    git_sha: str | None
    git_dirty: bool | None


def find_repo_root(start: str | Path | None = None) -> Path | None:
    """Nearest ancestor containing a ``.git`` entry, or ``None``."""
    for candidate in _candidates(start):
        if (candidate / ".git").exists():
            return candidate
    return None


def _candidates(start: str | Path | None) -> tuple[Path, ...]:
    origin = Path(start).resolve() if start is not None else Path.cwd()
    package_root = Path(__file__).resolve().parents[2]
    seen: list[Path] = []
    for root in (origin, package_root):
        for directory in (root, *root.parents):
            if directory not in seen:
                seen.append(directory)
    return tuple(seen)


def git_provenance(repo_root: str | Path | None = None) -> Provenance:
    """Observe the current revision and dirty flag of the project repository."""
    root = Path(repo_root).resolve() if repo_root is not None else find_repo_root()
    if root is None:
        return Provenance(git_sha=None, git_dirty=None)
    revision = _git(root, "rev-parse", "HEAD")
    if revision is None:
        return Provenance(git_sha=None, git_dirty=None)
    status = _git(root, "status", "--porcelain")
    return Provenance(git_sha=revision, git_dirty=None if status is None else bool(status))


def _git(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()
