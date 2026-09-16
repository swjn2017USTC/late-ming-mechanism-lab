"""``python -m late_ming_lab.release`` — build, verify or audit the V1 baseline.

V2-P00 ships this entry point rather than a tenth command on the main CLI, so that the baseline can
be frozen and checked without editing a single V1 file. Every action fails closed: a build over a
modified frozen file, a verification with any drift, and an audit with an unresolvable citation all
exit non-zero with the reason named.

```text
build    write docs/v2/baseline-v1.json from the current commit and the artifacts on disk
verify   re-hash the tree and the frozen commit against that file; non-zero on any drift
audit    write docs/v2/v1-acceptance-matrix.{json,md} from the frozen baseline and the cards
v2       recompute the V2 mechanism cards, the synthesis, the rights notice, the reproduction
         guide, the release bundle and the limitations report
```
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from late_ming_lab.release.audit import build_audit, verify_audit, write_audit
from late_ming_lab.release.baseline import (
    BASELINE_PATH,
    BaselineError,
    build_baseline,
    load_baseline,
    verify_baseline,
    write_baseline,
)

ACTIONS: Final[tuple[str, ...]] = ("build", "verify", "audit", "v2", "v2_1")


def main(argv: list[str] | None = None) -> int:
    """Run one action; return the process exit code."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in ACTIONS:
        actions = "|".join(ACTIONS)
        _echo(f"usage: python -m late_ming_lab.release [{actions}] [--root PATH]", err=True)
        return 2
    action = arguments[0]
    root = Path(_option(arguments[1:], "--root") or ".")
    if action == "build":
        return _build(root)
    if action == "verify":
        return _verify(root)
    if action == "audit":
        return _audit(root)
    if action == "v2_1":
        return _v2_1(root)
    return _v2(root)


def _v2(root: Path) -> int:
    """Recompute the V2 cards and everything the release bundle binds to them."""
    from late_ming_lab.release.bundle import ReleaseError, build_v2_release

    try:
        outcome = build_v2_release(root)
    except ReleaseError as error:
        _echo(f"refused: {error}", err=True)
        return 1
    _echo(f"cards: {outcome.card_count} ({outcome.changed} status changed)")
    for row in outcome.gates:
        _echo(f"gate {row['gate']}: {row['status']}")
    _echo(f"tagged: {outcome.tagged}")
    for path in outcome.written:
        _echo(f"wrote: {path}")
    return 0 if not outcome.refusals else 1


def _v2_1(root: Path) -> int:
    """The V2.1 closure pass: the cards, the documents and the bundle, with the gates re-decided."""
    from late_ming_lab.synthesis.v2_1 import run_pass

    try:
        outcome = run_pass(root)
    except (OSError, RuntimeError) as error:
        _echo(f"the closure pass refused: {error}", err=True)
        return 1
    for path in outcome.written:
        _echo(f"wrote: {path}")
    _echo(
        f"cards: {outcome.card_count}, statuses moved: {outcome.moved}, "
        f"gates met: {len(outcome.gates) - len(outcome.unmet)} of {len(outcome.gates)}"
    )
    for refusal in outcome.refusals:
        _echo(f"  {refusal}")
    _echo(f"no tag is created; the bundle is at {outcome.bundle}")
    return 0


def _build(root: Path) -> int:
    try:
        baseline = build_baseline(root)
    except BaselineError as error:
        _echo(f"refused: {error}", err=True)
        return 1
    path = write_baseline(root, baseline)
    _echo(f"baseline_id: {baseline.baseline_id}")
    _echo(f"commit: {baseline.commit}")
    _echo(f"tracked files: {baseline.tracked_file_count} ({baseline.group_counts()})")
    _echo(f"artifacts: {baseline.artifact_count} directories, {baseline.artifact_file_count} files")
    _echo(f"content digest: {baseline.content_digest}")
    _echo(f"wrote: {path}")
    return 0


def _verify(root: Path) -> int:
    baseline = load_baseline(root / BASELINE_PATH)
    verification = verify_baseline(root, baseline)
    _echo(f"baseline: {verification.baseline_id} ({verification.commit[:12]})")
    _echo(f"head: {(verification.head or 'unknown')[:12]}")
    _echo(f"frozen tracked files: {baseline.tracked_file_count} checked")
    _echo(f"frozen artifacts: {baseline.artifact_count} directories checked")
    for drift in verification.failures():
        _echo(f"DRIFT [{drift.section}] {drift.kind}: {drift.path}", err=True)
    for changed in verification.modified():
        _echo(f"changed since the baseline: {changed.path}")
    for addition in verification.additions():
        _echo(f"added: {addition.path}")
    for note in verification.notes:
        _echo(f"note: {note}")
    _echo(
        f"drift: {len(verification.failures())}, changed: {len(verification.modified())}, "
        f"additions: {len(verification.additions())}"
    )
    if not verification.ok:
        _echo("FAILED: the baseline is not reproducible from this tree", err=True)
        return 1
    _echo("ok: no frozen file was modified, removed or rewritten")
    return 0


def _audit(root: Path) -> int:
    audit = build_audit(root)
    json_path, markdown_path = write_audit(root, audit)
    missing = verify_audit(root, audit)
    for path in missing:
        _echo(f"unresolved citation: {path}", err=True)
    _echo(f"statuses: {audit.status_counts()}")
    _echo(f"cards: {len(audit.cards)}, discrepancies: {len(audit.discrepancies)}")
    _echo(f"content digest: {audit.content_digest}")
    _echo(f"wrote: {json_path}")
    _echo(f"wrote: {markdown_path}")
    if missing:
        _echo("FAILED: the audit cites paths that do not exist", err=True)
        return 1
    return 0


def _echo(message: str, *, err: bool = False) -> None:
    """One line of output; failures go to stderr so a pipe can tell them apart."""
    print(message, file=sys.stderr if err else sys.stdout)


def _option(arguments: list[str], name: str) -> str | None:
    for index, argument in enumerate(arguments):
        if argument == name and index + 1 < len(arguments):
            return arguments[index + 1]
        if argument.startswith(f"{name}="):
            return argument.split("=", 1)[1]
    return None


if __name__ == "__main__":
    raise SystemExit(main())
