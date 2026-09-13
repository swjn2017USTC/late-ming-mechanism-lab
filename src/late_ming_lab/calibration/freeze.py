"""Freezing the P08 evidence registry: the digests a calibration batch is run against.

The phase's first instruction is to freeze the registry before fitting anything. A freeze that is
only a sentence in a report is not a freeze, so the registry's *contents* are hashed — every source
record, parameter card, ledger entry, rule claim and historical pattern, plus the schema version
each file declares — and the digest is recorded in the ensemble's manifest. A later edit to any of
those files changes the digest, so an ensemble cannot silently outlive the evidence it was
calibrated against, and a report can state exactly which registry it belongs to.

The prior table and the objective are hashed the same way, for the same reason: the ensemble is a
claim about *these* bounds and *these* checks, and a change to either is a different experiment
rather than a detail of presentation.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Final

from late_ming_lab.core.hashing import canonical_json, hash_records, hash_text
from late_ming_lab.evidence.ledger import PatternRegistry

#: Registry files whose contents the freeze covers, relative to the repository root.
FROZEN_GLOBS: Final[tuple[str, ...]] = (
    "sources/registry/*.yaml",
    "data/parameters/*.yaml",
    "data/normalized/evidence_ledger*.yaml",
    "data/normalized/rule_claims.yaml",
    "data/historical_patterns/*.yaml",
)


class FreezeError(RuntimeError):
    """Raised when the freeze cannot be taken because a registry file is missing."""


def _frozen_files(root: str | Path) -> tuple[Path, ...]:
    directory = Path(root)
    files: list[Path] = []
    for pattern in FROZEN_GLOBS:
        matched = sorted(directory.glob(pattern))
        if not matched:
            raise FreezeError(f"the freeze matched no file for {pattern!r} under {directory}")
        files.extend(matched)
    return tuple(files)


def evidence_digest(root: str | Path) -> str:
    """A digest over the registry files' paths and contents, independent of file order on disk."""
    directory = Path(root)
    records = (
        f"{path.relative_to(directory).as_posix()}:{hash_text(path.read_text(encoding='utf-8'))}"
        for path in _frozen_files(directory)
    )
    return hash_records(records)


def frozen_file_digests(root: str | Path) -> tuple[tuple[str, str], ...]:
    """Per-file digests, so a report can name which file moved rather than only that one did."""
    directory = Path(root)
    return tuple(
        (
            path.relative_to(directory).as_posix(),
            hash_text(path.read_text(encoding="utf-8")),
        )
        for path in _frozen_files(directory)
    )


def prior_digest(priors: Iterable[tuple[str, str, float, float]]) -> str:
    """The digest of the declared bounds: ``(name, parameter_set, low, high)`` per parameter."""
    return hash_text(
        canonical_json(
            [
                {"name": name, "parameter_set": parameter_set, "low": low, "high": high}
                for name, parameter_set, low, high in priors
            ]
        )
    )


def objective_digest(checks: Iterable[tuple[str, str, str, str]]) -> str:
    """The digest of the declared checks: ``(pattern_id, check_id, kind, statistic)`` each."""
    return hash_text(
        canonical_json(
            [
                {"pattern_id": pattern_id, "check_id": check_id, "kind": kind, "statistic": stat}
                for pattern_id, check_id, kind, stat in checks
            ]
        )
    )


def registry_schema_versions(registry: PatternRegistry) -> dict[str, str]:
    """The schema version every pattern file declares, as the registry reports it."""
    return {"historical_patterns": registry.schema_version}
