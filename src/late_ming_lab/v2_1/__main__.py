"""``python -m late_ming_lab.v2_1`` — build the V2.1 audit documents.

One action, one purpose: read the V2 artifacts, decide the replicate semantics, and rewrite
`docs/v2_1/*.json` and `*.md` from what was read. It runs no simulation and touches no V2 artifact,
which is the property a phase that audits a frozen tree has to have.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from late_ming_lab.v2_1.audit import (
    DETERMINISTIC_BY_DESIGN,
    GENERATOR,
    build_audit_payload,
    write_documents,
)

ACTIONS: Final[tuple[str, ...]] = ("audit",)


def main(argv: list[str] | None = None) -> int:
    """Run one action; return the process exit code."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    action = arguments[0] if arguments else "audit"
    if action not in ACTIONS:
        _echo(f"unknown action {action!r}; expected one of {', '.join(ACTIONS)}", err=True)
        return 2
    return _audit(Path("."))


def _audit(root: Path) -> int:
    """Write the three document pairs and report what the verdict was."""
    payload = build_audit_payload(root)
    verdict = payload["determinism"]
    for path in write_documents(root):
        _echo(f"wrote: {path}")
    _echo(f"generator: {GENERATOR}")
    _echo(f"verdict: {verdict['verdict']}")
    for finding in verdict["findings"]:
        _echo(f"  {finding}")
    if verdict["verdict"] != DETERMINISTIC_BY_DESIGN:
        _echo(
            "the historical core's determinism is not a declared property: V2.1-P11 must not run",
            err=True,
        )
        return 1
    return 0


def _echo(message: str, *, err: bool = False) -> None:
    """One line of output; failures go to stderr so a pipe can tell them apart."""
    print(message, file=sys.stderr if err else sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
