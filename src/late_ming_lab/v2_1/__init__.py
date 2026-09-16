"""V2.1: the closure phase's accessors, its replicate semantics and its three documents.

`docs/OMP_UPGRADE_PLAN_V2_1.md` opens with a question V2 could not answer: whether the historical
core's four seeds are four independent replicates or four executions of one deterministic
trajectory. This package answers it from the artifacts, records what V2 established in the terms
those artifacts support, and recomputes the two parameter-registry defects V2 carried.

```bash
python -m late_ming_lab.v2_1 audit      # write docs/v2_1/*.json and *.md
```

Nothing here runs a simulation. Every number comes from an artifact, and the documents it writes
are rewritten by the command rather than edited: a generated document that no longer matches its
generator is the failure mode the audit exists to prevent.
"""

from __future__ import annotations

from late_ming_lab.v2_1.accessors import (
    KEY_READINGS,
    P05_ROOT,
    P06_POSTERIOR,
    P07_LEVELS,
    P07_MANIFEST,
    P08_ARMS,
    AuditError,
    audit_p05,
    audit_p06,
    audit_p07,
    audit_p08,
)
from late_ming_lab.v2_1.audit import (
    DETERMINISTIC_BY_DESIGN,
    RNG_WIRING_BLOCKER,
    AuditBuildError,
    ReplicateSemantics,
    arm_semantics,
    build_audit_payload,
    build_disposition_payload,
    build_registry_payload,
    determinism_verdict,
    registry_findings,
    semantics_row,
    write_documents,
)

__all__ = [
    "DETERMINISTIC_BY_DESIGN",
    "KEY_READINGS",
    "P05_ROOT",
    "P06_POSTERIOR",
    "P07_LEVELS",
    "P07_MANIFEST",
    "P08_ARMS",
    "RNG_WIRING_BLOCKER",
    "AuditBuildError",
    "AuditError",
    "ReplicateSemantics",
    "arm_semantics",
    "audit_p05",
    "audit_p06",
    "audit_p07",
    "audit_p08",
    "build_audit_payload",
    "build_disposition_payload",
    "build_registry_payload",
    "determinism_verdict",
    "registry_findings",
    "semantics_row",
    "write_documents",
]
