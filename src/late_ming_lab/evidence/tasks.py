"""Evidence tasks, ranked: where the next acquisition or verification changes something.

V2-P01's job is not to collect more sources; it is to say which evidence work would change what the
project can conclude. A task here is a *domain* - observed climate, prices, migration, relief,
military pay, mortality, debt and land, governance thresholds - scored from three parts, one
declared and two counted:

```text
relevance   declared 1-5: how much a V2 conclusion depends on this domain. An argument, not a count.
sensitivity counted: how many of the domain's parameter cards the model's behaviour is most
            sensitive to (priority high or screened-first). Reported, and named in the report.
debt        counted: grade-S/D cards in the domain (values that are ours), plus sources whose
            content was never read (unverified, or verified identity-only), plus inputs not yet
            acquired, plus 2 when the domain has no mechanism at all - an absence, not a weak value
score       relevance x debt. Higher is more urgent, and every component is printed so a reader can
            re-rank with different weights instead of arguing with a single number.
```

Two things this module deliberately does not do. It does not decide *which sources are true* - a
grade belongs to a source record, and the ranking only reads grades. And it does not silently
promote a domain by counting its sources: a domain with fifty unread monographs scores worse than
one with three read ones, because unread is the point.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from late_ming_lab.evidence.cards import ParameterCards
from late_ming_lab.evidence.grades import EvidenceGrade, ReadDepth
from late_ming_lab.evidence.registry import SourceRegistry, Verification
from late_ming_lab.evidence.snapshots import SnapshotManifest


@dataclass(frozen=True, slots=True)
class DomainDeclaration:
    """One domain's declared inputs: what it is for, and which registries describe it."""

    key: str
    title: str
    relevance: int
    decision: str
    clusters: tuple[str, ...]
    parameter_sets: tuple[str, ...]
    missing_mechanism: bool
    next_action: str


#: The eight domains, in the order the phase names them. ``relevance`` is the declared judgement;
#: everything else in the ranking is counted from the registries.
DOMAINS: Final[tuple[DomainDeclaration, ...]] = (
    DomainDeclaration(
        key="climate",
        title="Observed drought and famine timing and geography",
        relevance=5,
        decision=(
            "M002's gate, and every hold-out pattern that depends on when the worst years fell: "
            "three reserved patterns fail today because the forcing is stationary, not because a "
            "mechanism failed."
        ),
        clusters=("drought_climate",),
        parameter_sets=("CropParameters", "HouseholdParameters"),
        missing_mechanism=False,
        next_action=(
            "Allocate the REACHES event records to node-months with an explicit annual-to-monthly "
            "model (V2-P02), and check what share of the file is Ming-era before using it."
        ),
    ),
    DomainDeclaration(
        key="prices",
        title="Local grain-price level and cross-node dispersion",
        relevance=4,
        decision=(
            "The price ceiling the cards declare excludes the recorded famine extremes, and the "
            "dispersion check is uninformative in the posterior region - both are evidence gaps "
            "rather than mechanism findings."
        ),
        clusters=("grain_market_prices",),
        parameter_sets=("MarketParameters", "CropParameters"),
        missing_mechanism=False,
        next_action=(
            "Get level observations at county resolution for Shaanxi and Henan out of a library "
            "(Quan Hansheng's series and the gazetteer entries), recording units and commodity."
        ),
    ),
    DomainDeclaration(
        key="migration",
        title="Migration direction, timing and volume",
        relevance=4,
        decision=(
            "M002's gate is the one intervention that breaks the county in every replicate, and "
            "the only migration evidence is a near-zero exit volume; the gate's parameters are "
            "declared rather than estimated."
        ),
        clusters=("population_migration",),
        parameter_sets=("MigrationParameters", "HouseholdParameters"),
        missing_mechanism=False,
        next_action=(
            "Ground destination capacity and transit loss in something other than a declared "
            "constant, and separate temporary from permanent movement in the record."
        ),
    ),
    DomainDeclaration(
        key="relief",
        title="Relief timing, capacity and coverage",
        relevance=4,
        decision=(
            "The relief claim behaves differently by window (0.84 over the whole run, 0.25 in the "
            "hold-out), which is as much an evidence problem as a mechanism one: nothing measures "
            "coverage against need."
        ),
        clusters=("relief",),
        parameter_sets=("FiscalParameters", "EliteParameters"),
        missing_mechanism=False,
        next_action=(
            "Find a relief register or granary account that gives a quantity rather than an "
            "institution: what was released, to whom, in which month."
        ),
    ),
    DomainDeclaration(
        key="military_pay",
        title="Pay arrears, desertion and the fiscal-military link",
        relevance=5,
        decision=(
            "M003 is rejected in its strong form and survives only as a level claim resting on "
            "one held-out pattern; the arrears series is the model's own and no source fixes a "
            "pay rate."
        ),
        clusters=("military_finance",),
        parameter_sets=("MilitaryParameters", "FiscalParameters"),
        missing_mechanism=False,
        next_action=(
            "Read Ray Huang's expenditure figures at their own level of government and record "
            "which level they describe, then look for a garrison payroll or a remittance "
            "schedule."
        ),
    ),
    DomainDeclaration(
        key="mortality",
        title="Famine mortality and population loss",
        relevance=5,
        decision=(
            "M006 is UNIDENTIFIED: no rule, no parameter and no output exist, so no ablation, "
            "hold-out score or counterfactual can say anything about it."
        ),
        clusters=("famine",),
        parameter_sets=(),
        missing_mechanism=True,
        next_action=(
            "Establish whether famine mortality can be constrained at all in this window before "
            "building it; if it cannot, keep the card UNIDENTIFIED and say what would change that."
        ),
    ),
    DomainDeclaration(
        key="debt_land",
        title="Credit, foreclosure and land transfer",
        relevance=3,
        decision=(
            "M004 rests on one measured branch: credit is load-bearing, but the accumulating "
            "branch was never built, so a bifurcation cannot be tested."
        ),
        clusters=("land_debt_elites",),
        parameter_sets=("EliteParameters", "HouseholdParameters"),
        missing_mechanism=False,
        next_action=(
            "Look for a land-transfer or mortgage record at county resolution - the quantity the "
            "elite mechanism is about - rather than another description of elite lending."
        ),
    ),
    DomainDeclaration(
        key="governance_thresholds",
        title="Governance outcome thresholds and reading lines",
        relevance=5,
        decision=(
            "Every V1 status is read through eight declared lines, all eight grade S; the audit's "
            "criteria 7 and 8 therefore sit on reading rules rather than on evidence."
        ),
        clusters=("taxation_levies", "relief"),
        parameter_sets=("GovernanceIndicatorParameters", "FiscalParameters"),
        missing_mechanism=False,
        next_action=(
            "Replace each declared line with a sourced range or an explicit normative band, and "
            "fix the ensemble before any V2 batch is run (V2-P03)."
        ),
    ),
)


class DomainTask(BaseModel):
    """One domain's evidence debt, with every component that produced its rank."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    title: str
    rank: int = Field(ge=1)
    score: int = Field(ge=0)
    relevance: int = Field(ge=1, le=5)
    debt: int = Field(ge=0)
    decision: str = Field(min_length=1)
    next_action: str = Field(min_length=1)
    parameter_sets: tuple[str, ...] = ()
    weak_cards: tuple[str, ...] = ()
    sensitivity_cards: tuple[str, ...] = ()
    unread_sources: tuple[str, ...] = ()
    unverified_sources: tuple[str, ...] = ()
    pending_snapshots: tuple[str, ...] = ()
    missing_mechanism: bool = False

    def components(self) -> str:
        """The arithmetic, written out, so the rank can be recomputed by hand."""
        parts = (
            f"{len(self.weak_cards)} weak + {len(self.unread_sources)} unread + "
            f"{len(self.pending_snapshots)} pending"
        )
        if self.missing_mechanism:
            parts += " + 2 no mechanism"
        return f"{self.relevance} x ({parts}) = {self.score}"


class EvidenceTaskList(BaseModel):
    """Every domain, ranked, with the formula the document renders beside it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "evidence-tasks-v1"
    formula: str = Field(min_length=1)
    tasks: tuple[DomainTask, ...] = Field(min_length=1)


FORMULA: Final[str] = (
    "score = relevance x debt, where relevance is declared (1-5) and debt is counted: cards graded "
    "S or D in the domain's parameter sets, plus sources whose content was never read (unverified, "
    "or verified with read depth identity-only), plus inputs not yet acquired, plus 2 for a domain "
    "whose mechanism does not exist at all. Every component is printed, so a reader can re-rank."
)


def build_tasks(
    *,
    registry: SourceRegistry,
    cards: ParameterCards,
    snapshots: SnapshotManifest,
) -> EvidenceTaskList:
    """Score every domain from the registries; declared relevance is the only authored input."""
    tasks: list[DomainTask] = []
    for declaration in DOMAINS:
        domain_cards = tuple(
            card
            for parameter_set in declaration.parameter_sets
            for card in cards.for_set(parameter_set)
        )
        weak = tuple(
            sorted(
                f"{card.parameter_set}.{card.id}"
                for card in domain_cards
                if card.evidence_grade in {EvidenceGrade.S, EvidenceGrade.D}
            )
        )
        sensitive = tuple(
            sorted(
                f"{card.parameter_set}.{card.id}"
                for card in domain_cards
                if card.sensitivity_priority in {"high", "screened-first"}
            )
        )
        domain_sources = {
            source.id: source
            for cluster in declaration.clusters
            for source in registry.by_cluster(cluster)
        }
        unread = tuple(
            sorted(
                source_id
                for source_id, source in domain_sources.items()
                if source.verification is Verification.UNVERIFIED
                or source.read_depth is ReadDepth.IDENTITY_ONLY
            )
        )
        unverified = tuple(
            sorted(
                source_id
                for source_id, source in domain_sources.items()
                if source.verification is Verification.UNVERIFIED
            )
        )
        pending = tuple(
            sorted(
                record.id
                for record in snapshots
                if record.pending and record.source_id in domain_sources
            )
        )
        debt = len(weak) + len(unread) + len(pending) + (2 if declaration.missing_mechanism else 0)
        tasks.append(
            DomainTask(
                key=declaration.key,
                title=declaration.title,
                rank=1,
                score=declaration.relevance * debt,
                relevance=declaration.relevance,
                debt=debt,
                decision=declaration.decision,
                next_action=declaration.next_action,
                parameter_sets=declaration.parameter_sets,
                weak_cards=weak,
                sensitivity_cards=sensitive,
                unread_sources=unread,
                unverified_sources=unverified,
                pending_snapshots=pending,
                missing_mechanism=declaration.missing_mechanism,
            )
        )
    ordered = sorted(tasks, key=lambda task: (-task.score, task.key))
    ranked = tuple(
        task.model_copy(update={"rank": position}) for position, task in enumerate(ordered, 1)
    )
    return EvidenceTaskList(formula=FORMULA, tasks=ranked)


def render_tasks(tasks: EvidenceTaskList) -> str:
    """The tasks as a document: the formula, the table, then one block per domain."""
    lines: list[str] = [
        "# Evidence tasks, ranked",
        "",
        "Generated by `late_ming_lab.evidence.tasks` from the source registry, the parameter",
        "cards and the snapshot manifest. It says where evidence work would change a conclusion,",
        "not what the sources are.",
        "",
        f"- formula: {tasks.formula}",
        "",
        "| rank | domain | relevance | debt | score | weak cards | unread sources | pending |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for task in tasks.tasks:
        lines.append(
            f"| {task.rank} | {task.title} | {task.relevance} | {task.debt} | "
            f"**{task.score}** | {len(task.weak_cards)} | {len(task.unread_sources)} | "
            f"{len(task.pending_snapshots)} |"
        )
    for task in tasks.tasks:
        lines += [
            "",
            f"## {task.rank}. {task.title}",
            "",
            f"**Score.** {task.components()}",
            "",
            f"**Why it matters.** {task.decision}",
            "",
            f"**Next action.** {task.next_action}",
            "",
        ]
        if task.parameter_sets:
            lines.append(f"**Parameter sets.** {', '.join(task.parameter_sets)}")
        else:
            lines.append("**Parameter sets.** none: the domain has no card because it has no rule")
        lines.append("")
        if task.sensitivity_cards:
            lines.append(
                f"**Sensitivity.** {len(task.sensitivity_cards)} high-priority card(s): "
                + ", ".join(f"`{name}`" for name in task.sensitivity_cards)
            )
        else:
            lines.append("**Sensitivity.** no high-priority card in this domain")
        lines.append("")
        if task.weak_cards:
            lines.append(
                f"**Values that are ours.** {len(task.weak_cards)} card(s) graded S or D: "
                + ", ".join(f"`{name}`" for name in task.weak_cards)
            )
        else:
            lines.append("**Values that are ours.** no grade-S or grade-D card in this domain")
        lines.append("")
        if task.unread_sources:
            lines.append(
                f"**Sources whose content was never read.** {len(task.unread_sources)}: "
                + ", ".join(f"`{name}`" for name in task.unread_sources)
            )
            if task.unverified_sources:
                lines.append(
                    f"**Of those, unverified.** {len(task.unverified_sources)}: "
                    + ", ".join(f"`{name}`" for name in task.unverified_sources)
                )
        else:
            lines.append("**Sources whose content was never read.** none")
        lines.append("")
        if task.pending_snapshots:
            lines.append(
                "**Inputs not acquired.** "
                + ", ".join(f"`{name}`" for name in task.pending_snapshots)
            )
        else:
            lines.append("**Inputs not acquired.** none recorded as pending in this domain")
        if task.missing_mechanism:
            lines.append(
                "**Missing mechanism.** no rule, parameter or output exists, so no arm can bind "
                "and no hold-out score can speak to it"
            )
    lines.append("")
    return "\n".join(lines)


def render_tasks_json(tasks: EvidenceTaskList) -> str:
    """The same ranking, machine-readable."""
    payload = tasks.model_dump(mode="json")
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
