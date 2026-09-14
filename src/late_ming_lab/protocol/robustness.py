"""How much of a verdict is the model, and how much is the line somebody chose?

The V1 picture had one headline number — `breakdown`, the count of crossed governance lines —
and a verdict that moved with it. That number is a *function of eight declared thresholds*,
the project grades `S` (assumption). A report that says "the county broke down" without saying how
much of that sentence came from the line rather than the run is reporting the line as if it were
the finding.

So the protocol does the two halves separately:

```text
measures    eight measurements per run, which no threshold can change. They are the run's behaviour.
lines       eight values per ensemble member. They are the project's choices.
verdicts    crossing, the crossed count, breakdown, and the criterion each mechanism card rests
            on, computed once per (run, member) pair
```

Then, for every declared criterion, the share of members under which it holds, changes, or cannot be
decided at all. A criterion that reads no threshold is *provably* invariant, and this module says so
by evaluating it under every member rather than by assertion: if a threshold-free criterion ever
gained a threshold dependency, its invariant share would stop being 1.0 and a test would see it.

Three verdicts are distinguished, and the third is not a failure to report:

```text
holds         satisfied under this member
changes       not satisfied under this member
undetermined  no measurement this project has can decide it, for a reason the table names
```
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

import numpy as np
import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from late_ming_lab.analysis.mechanisms import (
    armed_band_consolidation,
    extraction_inversion,
    fiscal_military_ratchet,
)
from late_ming_lab.protocol.schema import ValidationProtocol

if TYPE_CHECKING:
    from late_ming_lab.protocol.thresholds import ThresholdEnsemble

#: The verdict vocabulary, shared by criteria and by the report.
Verdict = Literal["holds", "changes", "undetermined"]

#: The derived reading whose threshold this module reads out of the protocol rather than restating.
BREAKDOWN_READING: Final[str] = "breakdown"

#: The name the breakdown reading gives its line inside the protocol's threshold block.
BREAKDOWN_LINE_KEY: Final[str] = "breakdown_min_crossed"

#: The arms the declared criteria read: the opened gate, the reference, and the credit mechanism
#: removed. They are named here so a criterion and the pilot's arm list cannot drift apart silently.
GATE_ARM: Final[str] = "OPEN_MIGRATION_EXIT"
REFERENCE_ARM: Final[str] = "BASELINE"
NO_ELITE_CREDIT_ARM: Final[str] = "NO_ELITE_CREDIT"


class RobustnessError(ValueError):
    """Raised when a robustness question cannot be asked of the runs it was given."""


@dataclass(frozen=True, slots=True)
class RunReading:
    """One run as the robustness report sees it: the measures the ensemble moves, the rest.

    `indicators` holds exactly the eight governance measures the ensemble varies. Everything else
    the report reads — the three mechanism readings, elite lending, band counts — is a measurement
    no threshold enters, and is kept separate so the distinction cannot be blurred by accident.
    """

    run_id: str
    arm: str
    root_seed: int
    policy_id: str
    indicators: dict[str, float]
    directions: dict[str, str]
    inversion: float
    ratchet: float
    consolidation: float
    elite_loans: float
    bands_at_end: float

    @property
    def tax_base_contraction(self) -> float:
        return float(self.indicators.get("tax_base_contraction", 0.0))


@dataclass(frozen=True, slots=True)
class CrossedTable:
    """Every (member, run, indicator) crossing, computed once as an array.

    The report is an enumeration over 50,625 members by construction, so crossing is done once,
    vectorised, and every criterion reads the same array. Recomputing crossings per criterion would
    be the same arithmetic done eight times, and it would also give a criterion the chance to be
    evaluated against a table another criterion did not see.
    """

    run_ids: tuple[str, ...]
    arms: tuple[str, ...]
    indicators: tuple[str, ...]
    members: int
    flags: np.ndarray
    counts: np.ndarray

    @property
    def shape(self) -> tuple[int, int, int]:
        return (self.members, len(self.run_ids), len(self.indicators))

    def indicator_index(self, indicator: str) -> int:
        try:
            return self.indicators.index(indicator)
        except ValueError as error:
            raise RobustnessError(f"no indicator {indicator!r} in the crossed table") from error

    def counts_for_arm(self, arm: str) -> np.ndarray:
        """Crossed counts for an arm's replicates, as (members, replicates); empty if absent."""
        positions = [index for index, name in enumerate(self.arms) if name == arm]
        return self.counts[:, positions]

    def any_crossed(self, indicator: str, arm: str | None = None) -> bool:
        """Whether that indicator crossed anywhere (optionally: in one arm)."""
        index = self.indicator_index(indicator)
        columns = (
            [position for position, name in enumerate(self.arms) if name == arm]
            if arm is not None
            else list(range(len(self.run_ids)))
        )
        if not columns:
            return False
        return bool(self.flags[:, columns, index].any())

    def positions_for_arm(self, arm: str) -> tuple[int, ...]:
        return tuple(index for index, name in enumerate(self.arms) if name == arm)


#: What a criterion may look at: the runs, the crossing table one member set produced, and the
#: crossed count the breakdown reading is being taken at.
CriterionEvaluator = Callable[[tuple[RunReading, ...], CrossedTable, int], Verdict]


class CriterionShare(BaseModel):
    """One criterion's distribution over the threshold ensemble."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion: str
    mechanism: str
    statement: str
    reads_thresholds: bool
    breakdown_line: int = Field(
        gt=0, description="the crossed count the breakdown reading was taken at for this row"
    )
    holds: float = Field(ge=0.0, le=1.0)
    changes: float = Field(ge=0.0, le=1.0)
    undetermined: float = Field(ge=0.0, le=1.0)
    members: int = Field(gt=0)
    runs: int = Field(gt=0)

    @property
    def verdict(self) -> Verdict:
        """The criterion's answer, which is only one word when the ensemble agrees."""
        if self.undetermined == 1.0:
            return "undetermined"
        if self.holds == 1.0:
            return "holds"
        return "changes"

    def moves_with_the_ensemble(self) -> bool:
        """Whether the ensemble decides this criterion differently for different members."""
        return 0.0 < self.holds < 1.0


class IndicatorShare(BaseModel):
    """One indicator's crossing frequency over the ensemble, for the runs evaluated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    indicator: str
    direction: str
    measured_min: float
    measured_max: float
    line_min: float
    line_max: float
    crossed_share: float = Field(ge=0.0, le=1.0)


class ThresholdRobustness(BaseModel):
    """The whole report: criterion shares, indicator shares and the crossed-count distribution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_version: str
    protocol_digest: str
    breakdown_lines: tuple[int, ...]
    ensemble_version: str
    ensemble_digest: str
    members: int = Field(gt=0)
    runs: tuple[str, ...]
    criteria: tuple[CriterionShare, ...]
    indicators: tuple[IndicatorShare, ...]
    crossed_count_share: dict[str, float] = Field(default_factory=dict)
    breakdown_shares: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description=(
            "run id -> breakdown line -> share of ensemble members reading breakdown there; the "
            "protocol declares a range for that line, so the reading is reported at every value"
        ),
    )
    note: str = ""

    def by_criterion(self) -> dict[str, tuple[CriterionShare, ...]]:
        """Each criterion's rows, one per crossed count the protocol allows."""
        grouped: dict[str, list[CriterionShare]] = {}
        for share in self.criteria:
            grouped.setdefault(share.criterion, []).append(share)
        return {name: tuple(rows) for name, rows in grouped.items()}

    def moves(self, criterion: str) -> bool:
        """Whether any member or any allowed crossed count changes this criterion's answer.

        A criterion that holds under some members and not others moves; so does one whose answer
        depends on which crossed count the breakdown reading is taken at.
        """
        rows = self.by_criterion()[criterion]
        if any(0.0 < row.holds < 1.0 for row in rows):
            return True
        return len({row.verdict for row in rows}) > 1

    def moved_criteria(self) -> tuple[str, ...]:
        """The criteria the ensemble or the reading line decides differently, once each."""
        return tuple(name for name in self.by_criterion() if self.moves(name))

    def stable_criteria(self) -> tuple[str, ...]:
        """The criteria nothing here decides differently, with the answer they always give."""
        return tuple(
            f"{name}: {self.by_criterion()[name][0].verdict}"
            for name in self.by_criterion()
            if not self.moves(name)
        )


@dataclass(frozen=True, slots=True)
class Criterion:
    """A declared reading of one mechanism card, and whether a line enters it."""

    id: str
    mechanism: str
    statement: str
    reads_thresholds: bool
    evaluate: CriterionEvaluator

    def share(
        self,
        runs: tuple[RunReading, ...],
        members: tuple[dict[str, float], ...],
        *,
        breakdown_line: int,
        table: CrossedTable | None = None,
    ) -> CriterionShare:
        """The criterion's distribution over the ensemble members, at one breakdown line.

        The line is an argument rather than a constant because the protocol declares it with a
        range and requires the reading to be reported at every value in it. A criterion reading
        it gets a row per value; one that does not gets the same row at every value, which is how
        invariance is shown rather than asserted.
        """
        if not runs:
            raise RobustnessError(f"{self.id}: no runs to evaluate")
        crossed = table if table is not None else crossed_table(runs, members)
        holds = 0
        undetermined = 0
        for index in range(crossed.members):
            verdict = self.evaluate(runs, _one_member(crossed, index), breakdown_line)
            if verdict == "holds":
                holds += 1
            elif verdict == "undetermined":
                undetermined += 1
        return CriterionShare(
            criterion=self.id,
            mechanism=self.mechanism,
            statement=self.statement,
            reads_thresholds=self.reads_thresholds,
            breakdown_line=breakdown_line,
            holds=holds / crossed.members,
            changes=(crossed.members - holds - undetermined) / crossed.members,
            undetermined=undetermined / crossed.members,
            members=crossed.members,
            runs=len(runs),
        )


def read_run(
    *,
    run_id: str,
    arm: str,
    root_seed: int,
    policy_id: str,
    indicators: dict[str, float],
    directions: dict[str, str],
    events: pl.DataFrame,
    elite_loans: float = 0.0,
    bands_at_end: float = 0.0,
) -> RunReading:
    """Read one run's threshold-free readings.

    The three mechanism readings consume the event log only, which the module's own test pins,
    because the claim "these verdicts do not move with the ensemble" depends on their input.
    """
    inversion = extraction_inversion(events)
    ratchet = fiscal_military_ratchet(events)
    consolidation = armed_band_consolidation(events)
    return RunReading(
        run_id=run_id,
        arm=arm,
        root_seed=root_seed,
        policy_id=policy_id,
        indicators=dict(indicators),
        directions=dict(directions),
        inversion=float(inversion.strength) if inversion.present else 0.0,
        ratchet=float(ratchet.strength) if ratchet.present else 0.0,
        consolidation=float(consolidation.strength) if consolidation.present else 0.0,
        elite_loans=float(elite_loans),
        bands_at_end=float(bands_at_end),
    )


def crossed_flags(run: RunReading, member: dict[str, float]) -> dict[str, bool]:
    """Which of the eight lines one run crosses under one member.

    The direction is the model's own, taken from the run's indicator frame rather than restated
    here: a line is a failure when the measure is *below* it for a below-is-failure indicator and
    *above* it otherwise. A member that does not name an indicator the run measured is refused
    rather than defaulted, because a partial member would silently decide the report.

    This is the definition; `crossed_table` is the same arithmetic vectorised over the ensemble. The
    test that holds the two together is what licenses reading the report's shares as this rule's.
    """
    flags: dict[str, bool] = {}
    for indicator, measure in run.indicators.items():
        if indicator not in member:
            raise RobustnessError(
                f"{run.run_id}: the ensemble has no value for {indicator!r}; a partially specified "
                "member is refused rather than defaulted"
            )
        line = float(member[indicator])
        direction = run.directions.get(indicator, "above-is-failure")
        flags[indicator] = measure < line if direction == "below-is-failure" else measure > line
    return flags


def crossed_count(run: RunReading, member: dict[str, float]) -> int:
    """How many of the eight lines one run crosses under one member."""
    return sum(crossed_flags(run, member).values())


def reads_breakdown(run: RunReading, member: dict[str, float], *, minimum: int) -> bool:
    """Whether one run, under one member, reaches the breakdown reading at this line."""
    return crossed_count(run, member) >= minimum


def crossed_table(
    runs: tuple[RunReading, ...], members: tuple[dict[str, float], ...]
) -> CrossedTable:
    """Every crossing at once: (members, runs, indicators) booleans, and their row sums.

    Sign convention: an above-is-failure line is crossed when the measure exceeds it, a
    below-is-failure line when the measure falls short, which is `sign * measure > sign * line`.
    """
    if not runs:
        raise RobustnessError("a crossed table needs at least one run")
    if not members:
        raise RobustnessError("a crossed table needs at least one ensemble member")
    indicators = tuple(sorted(runs[0].indicators))
    for run in runs:
        if set(run.indicators) != set(indicators):
            raise RobustnessError(
                f"{run.run_id}: the runs disagree on which indicators they measured; a table cannot"
                "hold a ragged set"
            )
    measure = np.array([[run.indicators[name] for name in indicators] for run in runs], dtype=float)
    signs = np.array(
        [
            [
                -1.0 if run.directions.get(name, "above-is-failure") == "below-is-failure" else 1.0
                for name in indicators
            ]
            for run in runs
        ],
        dtype=float,
    )
    design = np.array([[member[name] for name in indicators] for member in members], dtype=float)
    # (members, runs, indicators): the same comparison crossed_flags makes, once per member.
    flags = signs[None, :, :] * measure[None, :, :] > signs[None, :, :] * design[:, None, :]
    return CrossedTable(
        run_ids=tuple(run.run_id for run in runs),
        arms=tuple(run.arm for run in runs),
        indicators=indicators,
        members=len(members),
        flags=flags,
        counts=flags.sum(axis=2),
    )


def _one_member(table: CrossedTable, index: int) -> CrossedTable:
    """A one-member view of the table, so a criterion can be written against a single ensemble."""
    return CrossedTable(
        run_ids=table.run_ids,
        arms=table.arms,
        indicators=table.indicators,
        members=1,
        flags=table.flags[index : index + 1],
        counts=table.counts[index : index + 1],
    )


def evaluate(
    runs: tuple[RunReading, ...],
    *,
    protocol: ValidationProtocol,
    ensemble: ThresholdEnsemble,
    members: tuple[dict[str, float], ...],
) -> ThresholdRobustness:
    """The report: every declared criterion's share, and every indicator's crossing frequency.

    The breakdown line is read from the protocol, not chosen here: the protocol declares its value
    and the range it may be read over, and the report gives a row for every value in that range. A
    report that picked one value would be the thing this phase exists to stop.
    """
    if not members:
        raise RobustnessError("an ensemble with no members decides nothing")
    lines = breakdown_lines(protocol)
    # The ensemble names its lines by parameter field; a run measures them under the indicator ids
    # the analysis reports (`thresholds.by_indicator` is the translation, and this check uses it).
    for run in runs:
        differing = set(ensemble.indicator_ids) - set(run.indicators)
        if differing:
            raise RobustnessError(
                f"{run.run_id}: the run measured no value for {', '.join(sorted(differing))}, "
                "which the ensemble moves; a missing measure would be crossed as if it were zero"
            )
    table = crossed_table(runs, members)
    # One observation per (member, run) pair: a per-member sum over runs would report a count no run
    # can reach, and the histogram is read by eye as "how many lines a run crosses".
    per_run = table.counts.reshape(-1)
    histogram = np.bincount(per_run, minlength=len(table.indicators) + 1)
    crossed_count_share = {
        str(value): float(share) / per_run.size
        for value, share in enumerate(histogram)
        if share > 0
    }
    breakdown_shares = {
        run.run_id: {str(line): float((table.counts[:, index] >= line).mean()) for line in lines}
        for index, run in enumerate(runs)
    }
    return ThresholdRobustness(
        protocol_version=protocol.version,
        protocol_digest=protocol.digest(),
        breakdown_lines=lines,
        ensemble_version=ensemble.version,
        ensemble_digest=ensemble.digest(),
        members=len(members),
        runs=tuple(run.run_id for run in runs),
        criteria=tuple(
            criterion.share(runs, members, breakdown_line=line, table=table)
            for line in lines
            for criterion in declared_criteria()
        ),
        indicators=_indicator_shares(runs, table, members),
        crossed_count_share=crossed_count_share,
        breakdown_shares=breakdown_shares,
        note=(
            f"{len(members)} ensemble members over {len(runs)} run(s); the breakdown reading is "
            f"reported at every crossed count the protocol declares ({lines[0]} to {lines[-1]}), "
            "so no single value of it carries a conclusion."
        ),
    )


def _indicator_shares(
    runs: tuple[RunReading, ...],
    table: CrossedTable,
    members: tuple[dict[str, float], ...],
) -> tuple[IndicatorShare, ...]:
    """Per indicator: the measured range, the line range, and how often a line crossed."""
    shares: list[IndicatorShare] = []
    for position, indicator in enumerate(table.indicators):
        measured = [run.indicators[indicator] for run in runs]
        lines = [float(member[indicator]) for member in members if indicator in member]
        crosses = table.flags[:, :, position]
        shares.append(
            IndicatorShare(
                indicator=indicator,
                direction=runs[0].directions.get(indicator, "above-is-failure"),
                measured_min=min(measured),
                measured_max=max(measured),
                line_min=min(lines) if lines else 0.0,
                line_max=max(lines) if lines else 0.0,
                crossed_share=float(crosses.mean()),
            )
        )
    return tuple(shares)


def declared_criteria() -> tuple[Criterion, ...]:
    """The declared criteria: one reading per mechanism card the protocol can decide.

    Each is the reading that decided, or would decide, the card's V1 status. Where a card's status
    rests on evidence the protocol cannot measure, the criterion says so and returns
    ``undetermined`` for every member rather than being dropped: a status no measurement supports
    is a finding about the model, and it belongs in the table.
    """
    return (
        Criterion(
            id="M001.policy-dependent-inversion",
            mechanism="M001",
            statement=(
                "the CONDITIONAL status is a contrast across decision policies: the inversion "
                "present under one and absent under another"
            ),
            reads_thresholds=False,
            evaluate=_inversion_separates_policies,
        ),
        Criterion(
            id="M002.breakdown-in-every-arm-replicate",
            mechanism="M002",
            statement=(
                "every replicate of the gate arm crosses the breakdown line and no replicate of the"
                "baseline does"
            ),
            reads_thresholds=True,
            evaluate=_breakdown_separates_arms,
        ),
        Criterion(
            id="M002.base-contraction-separates-arms",
            mechanism="M002",
            statement=(
                "the gate arm's measured tax-base contraction exceeds the baseline's in every "
                "replicate, which reads no line at all"
            ),
            reads_thresholds=False,
            evaluate=_contraction_separates_arms,
        ),
        Criterion(
            id="M003.ratchet-absent-in-the-reference-arm",
            mechanism="M003",
            statement=(
                "the REJECTED status, as the card states it: the ratchet reading is absent in the "
                "reference arm's replicates, because arrears rise and then come down"
            ),
            reads_thresholds=False,
            evaluate=_ratchet_absent_in_reference,
        ),
        Criterion(
            id="M003.ratchet-present-with-the-gate-open",
            mechanism="M003",
            statement=(
                "the card's own counterexample direction: the ratchet reading is present in the "
                "gate arm's replicates, where the tax base is leaving and arrears only accumulate"
            ),
            reads_thresholds=False,
            evaluate=_ratchet_present_with_gate_open,
        ),
        Criterion(
            id="M004.lending-fires-and-stops-firing",
            mechanism="M004",
            statement=(
                "the WEAK status rests on elite lending firing where the mechanism is present and "
                "not firing where it is removed"
            ),
            reads_thresholds=False,
            evaluate=_lending_bounds_the_mechanism,
        ),
        Criterion(
            id="M005.consolidation-reading",
            mechanism="M005",
            statement=(
                "the SUPPORTED status rests on the consolidation reading being present: fewer "
                "bands, with the largest holding a growing share"
            ),
            reads_thresholds=False,
            evaluate=lambda runs, table, line: (
                "holds" if any(run.consolidation > 0.0 for run in runs) else "changes"
            ),
        ),
        Criterion(
            id="M005.above-declared-share-line",
            mechanism="M005",
            statement=(
                "the largest band's share exceeds the declared line, which is the part of that card"
                "a threshold can move"
            ),
            reads_thresholds=True,
            evaluate=_largest_band_above_line,
        ),
        Criterion(
            id="M006.famine-mortality",
            mechanism="M006",
            statement=(
                "no threshold and no run decides the famine-mortality chain: the model has no "
                "mortality channel, so the reading is undetermined rather than merely unstable"
            ),
            reads_thresholds=False,
            evaluate=lambda runs, table, line: "undetermined",
        ),
    )


def _breakdown_separates_arms(
    runs: tuple[RunReading, ...], table: CrossedTable, line: int
) -> Verdict:
    gate = table.counts_for_arm(GATE_ARM)
    reference = table.counts_for_arm(REFERENCE_ARM)
    if gate.size == 0 or reference.size == 0:
        return "undetermined"
    gate_hits = bool((gate >= line).all())
    reference_hits = bool((reference >= line).any())
    return "holds" if gate_hits and not reference_hits else "changes"


def _contraction_separates_arms(
    runs: tuple[RunReading, ...], table: CrossedTable, line: int
) -> Verdict:
    gate = [runs[index] for index in table.positions_for_arm(GATE_ARM)]
    reference = [runs[index] for index in table.positions_for_arm(REFERENCE_ARM)]
    if not gate or not reference:
        return "undetermined"
    worst_reference = max(run.tax_base_contraction for run in reference)
    return "holds" if all(run.tax_base_contraction > worst_reference for run in gate) else "changes"


def _largest_band_above_line(
    runs: tuple[RunReading, ...], table: CrossedTable, line: int
) -> Verdict:
    return "holds" if table.any_crossed("largest_band_share") else "changes"


def _inversion_separates_policies(
    runs: tuple[RunReading, ...], table: CrossedTable, line: int
) -> Verdict:
    """The inversion present under one decision policy and absent under another.

    Computed rather than declared: a pilot that ran two policies can decide this, and one that ran a
    single policy cannot, so the verdict follows from the runs instead of from a comment about them.
    """
    policies = {run.policy_id for run in runs}
    if len(policies) < 2:
        return "undetermined"
    present = {run.policy_id for run in runs if run.inversion > 0.0}
    absent = policies - present
    return "holds" if present and absent else "changes"


def _ratchet_absent_in_reference(
    runs: tuple[RunReading, ...], table: CrossedTable, line: int
) -> Verdict:
    reference = [run for run in runs if run.arm == REFERENCE_ARM]
    if not reference:
        return "undetermined"
    return "holds" if all(run.ratchet == 0.0 for run in reference) else "changes"


def _ratchet_present_with_gate_open(
    runs: tuple[RunReading, ...], table: CrossedTable, line: int
) -> Verdict:
    gate = [run for run in runs if run.arm == GATE_ARM]
    if not gate:
        return "undetermined"
    return "holds" if all(run.ratchet > 0.0 for run in gate) else "changes"


def _lending_bounds_the_mechanism(
    runs: tuple[RunReading, ...], table: CrossedTable, line: int
) -> Verdict:
    """Elite lending observed with the mechanism, and not observed once it is removed.

    The WEAK card's own reasoning is that lending fires but does not change the outcomes, so the
    criterion cannot be "lending happened": it needs the arm without the credit mechanism. A pilot
    that does not run that arm says so rather than reporting the weaker observation as the status.
    """
    with_credit = [run for run in runs if run.arm == REFERENCE_ARM]
    without = [run for run in runs if run.arm == NO_ELITE_CREDIT_ARM]
    if not with_credit or not without:
        return "undetermined"
    fired = all(run.elite_loans > 0.0 for run in with_credit)
    silent = all(run.elite_loans == 0.0 for run in without)
    return "holds" if fired and silent else "changes"


def breakdown_lines(protocol: ValidationProtocol) -> tuple[int, ...]:
    """The crossed counts the protocol allows the breakdown reading to be taken at.

    Read from the frozen file: the value, and the range around it. A protocol that declared no range
    would be answered with its single declared value, which is the honest reading of a different
    declaration rather than a reason to substitute one here.
    """
    for reading in protocol.derived_readings:
        if reading.id != BREAKDOWN_READING:
            continue
        entry = reading.thresholds.get(BREAKDOWN_LINE_KEY)
        if entry is None:
            raise RobustnessError(
                f"the protocol's {BREAKDOWN_READING!r} reading declares no {BREAKDOWN_LINE_KEY!r}"
            )
        low, high = entry.range
        return tuple(range(int(low), int(high) + 1))
    raise RobustnessError(f"the protocol declares no {BREAKDOWN_READING!r} derived reading")
