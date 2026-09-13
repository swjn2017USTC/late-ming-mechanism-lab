"""The evidence phase's entry point: write the three reports from the four registries.

```text
docs/evidence/coverage.md       what the evidence base supports, per cluster and per rule
docs/evidence/uncertainty.md    every parameter's grade, range and reasoning
docs/evidence/gaps.md           what is missing, including the human-only acquisition queue
```

Run it after touching any registry, ledger, card or pattern file:

```bash
uv run python -c "from late_ming_lab.experiments.evidence import write_evidence_reports; \
    write_evidence_reports('.')"
```

Nothing here fits, tunes or scores anything. The reports are generated from the registries so that
a reader can check the phase's claims about its own evidence base without trusting a summary, and
so that the gap list cannot quietly shrink when nobody is looking.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from late_ming_lab.evidence.cards import ParameterCards, load_cards
from late_ming_lab.evidence.coverage import coverage_report, gap_report, uncertainty_report
from late_ming_lab.evidence.ledger import (
    EvidenceLedger,
    PatternRegistry,
    RuleClaimSet,
    load_ledger,
    load_patterns,
    load_rule_claims,
)
from late_ming_lab.evidence.registry import SourceRegistry, load_registry

COVERAGE_ARTIFACT: Final[str] = "coverage.md"
UNCERTAINTY_ARTIFACT: Final[str] = "uncertainty.md"
GAPS_ARTIFACT: Final[str] = "gaps.md"
REPORT_DIR: Final[str] = "docs/evidence"


@dataclass(frozen=True, slots=True)
class EvidenceBase:
    """Everything the reports are generated from, loaded and validated together."""

    registry: SourceRegistry
    ledger: EvidenceLedger
    cards: ParameterCards
    rules: RuleClaimSet
    patterns: PatternRegistry


def load_evidence_base(root: str | Path) -> EvidenceBase:
    directory = Path(root)
    return EvidenceBase(
        registry=load_registry(directory),
        ledger=load_ledger(directory),
        cards=load_cards(directory),
        rules=load_rule_claims(directory),
        patterns=load_patterns(directory),
    )


def write_evidence_reports(
    root: str | Path, *, output_dir: str | Path | None = None
) -> tuple[Path, ...]:
    """Load the registries, write the three reports, and return the paths written."""
    base = load_evidence_base(root)
    directory = Path(output_dir) if output_dir is not None else Path(root) / REPORT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    coverage = coverage_report(
        registry=base.registry,
        ledger=base.ledger,
        cards=base.cards,
        patterns=base.patterns,
        rules=base.rules,
    )
    uncertainty = uncertainty_report(base.cards)
    gaps = gap_report(
        registry=base.registry,
        ledger=base.ledger,
        cards=base.cards,
        patterns=base.patterns,
        rules=base.rules,
    )
    written: list[Path] = []
    for name, text in (
        (COVERAGE_ARTIFACT, coverage),
        (UNCERTAINTY_ARTIFACT, uncertainty),
        (GAPS_ARTIFACT, gaps),
    ):
        path = directory / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return tuple(written)
