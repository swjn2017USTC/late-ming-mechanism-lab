"""V2.1-P11: the two contrasts the cards left open, run on the historical core at one seed.

```text
M002  crisis gating    reference            against the gate the card names, opened
M004  elite branches   credit closed        against foreclosure and accumulation
```

Four arms, one 240-tick trajectory each, at one declared seed. That is a complete sample rather than
a sample of one: V2.1-P10 established from the artifacts that the historical core consumes no
randomness, so a second seed would be a replay of the first and is not drawn. The contrasts are
therefore *exact paired differences* between two runs of the same code, input and window.

Two declarations this module does not make for itself. The gate is opened by
`experiments.interventions.open_migration_exit_updates` and the credit channel is closed by
`no_elite_credit_updates` — the project's own declared interventions, read from one place
rather than copied here. And the reading surfaces are the frozen protocol's: the whole-run
window, under `purpose="report"`, with every reserved window untouched.

The order is part of the pre-registration and the code keeps it: the continuous base reading is
measured first, and the threshold ensemble is projected onto it afterwards, so the binary
`breakdown` reading can never have chosen the arm. `contrasts_payload` computes the readings in that
order and the status rules read only those readings.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import polars as pl

from late_ming_lab.analysis.chains import chain_summary
from late_ming_lab.analysis.fiscal import tax_base
from late_ming_lab.analysis.governance import governance_indicators
from late_ming_lab.analysis.military import military_totals
from late_ming_lab.analysis.scalars import total
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import SimulationKernel
from late_ming_lab.evidence.parameters import core_default_governance_indicators
from late_ming_lab.experiments.historical_core import HISTORICAL_SCENARIO
from late_ming_lab.experiments.holdout import (
    REFERENCE_ARM,
    Arm,
    ArmFacts,
    ArmRun,
    _write_arm_provenance,
    detect_no_op,
)
from late_ming_lab.experiments.integrated import build_integrated_economy
from late_ming_lab.experiments.interventions import (
    no_elite_credit_updates,
    open_migration_exit_updates,
)
from late_ming_lab.protocol.evaluation import PROTOCOL_STAMP_FILE, stamp_run
from late_ming_lab.protocol.freeze import ProtocolFreeze, assert_batch_protocol
from late_ming_lab.protocol.outcomes import OutcomeVector, compute_outcomes
from late_ming_lab.protocol.robustness import (
    RunReading,
    breakdown_lines,
    crossed_table,
    read_run,
)
from late_ming_lab.protocol.schema import ValidationProtocol, load_protocol
from late_ming_lab.protocol.thresholds import ThresholdEnsemble, load_ensemble, sample_draws
from late_ming_lab.storage.run_store import RunStore
from late_ming_lab.storage.tables import read_json, read_table, write_json, write_text

#: The phase's own root and prefix, beside V2-P10's documents.
CONTRASTS_ROOT: Final[str] = "outputs/v2_1/p11"
PREFIX: Final[str] = "p11"
POLICY_ID: Final[str] = "p11-contrasts-v1"

#: The documents this phase generates.
DOCUMENT: Final[str] = "docs/v2_1/decisive-contrasts.md"
MACHINE: Final[str] = "docs/v2_1/decisive-contrasts.json"
GENERATOR: Final[str] = "late-ming-lab experiment p11"

#: The one seed the four trajectories run at. Not a replicate axis: see the module docstring.
SEED: Final[int] = 20_260_915

#: The window the contrasts read, and the purpose they read it for. `whole-run` is the protocol's
#: reporting window; no reserved window is read, and `"report"` is the purpose that says so.
WINDOW: Final[str] = "whole-run"
PURPOSE: Final[str] = "report"

#: Where P05's arms are declared, and the arms the two cross-checks read: the reference, so the
#: baseline of this phase is the run P05 measured, and the accumulation branch, so the M004 arm is
#: the one the card already cites. Read from that file rather than pinned here, so a re-pin of the
#: phase's own artifacts moves this check with it.
P05_ARMS: Final[str] = "docs/v2/mechanism-variants.json"

#: The event types the elite chain is read from, and the trigger fields a foreclosure carries —
#: so the transfer is a measurement and the count is only a count.
LOAN_EVENT: Final[str] = "ELITE_LOAN"
DEFAULT_EVENT: Final[str] = "ELITE_DEFAULT"
FORECLOSURE_EVENT: Final[str] = "ELITE_FORECLOSURE"
TRANSFER_FIELDS: Final[tuple[str, ...]] = ("mu_transferred", "pledge_mu", "settled_tael")

#: The chain facts the M002 contrast reads beside the base, so the mechanism's own route is visible
#: and not only its end state.
M002_CHAIN_FACTS: Final[tuple[str, ...]] = (
    "migration_gate_share.not-eligible",
    "migration_gate_share.silver",
    "migration_gate_share.moved",
    "migration_gate_share.capacity",
    "migration_movers_households",
    "migration_capacity_refusals",
)


class ContrastError(RuntimeError):
    """Raised when a contrast cannot be run, or when a run is not the run it claims to be."""


def declared_arms() -> tuple[Arm, ...]:
    """The four arms: the reference, the opened gate, and the two elite branches.

    The gate arm's declaration is the project's `OPEN_MIGRATION_EXIT` intervention, read from
    `interventions.open_migration_exit_updates` rather than retyped: an arm that says it opens the
    gate and opens a different one is the failure this indirection prevents. The reference and the
    accumulation arm are P05's declarations, unchanged, so their runs are comparable with the runs
    the cards already cite.
    """
    migration_updates, household_updates = open_migration_exit_updates()
    return (
        Arm(
            label=REFERENCE_ARM,
            description="the historical core, every chain and rule at its neutral value",
            expects_effect=False,
        ),
        Arm(
            label="gate-open",
            description=(
                "the same input with the mobility gate the M002 card names opened: the declared "
                "open-migration-exit intervention, and nothing else"
            ),
            expects_effect=True,
            migration=dict(migration_updates),
            household=dict(household_updates),
        ),
        Arm(
            label="elite-credit-closed",
            description=(
                "the credit channel switched off — the declared no-elite-credit ablation, V1's "
                "null for this mechanism"
            ),
            expects_effect=True,
            elite=no_elite_credit_updates(),
        ),
        Arm(
            label="elite-accumulation",
            description=(
                "a loan unserviced for a month is foreclosed and the pledge transfers to the "
                "lender: P05's declaration, unchanged"
            ),
            expects_effect=True,
            elite={
                "foreclosure_after_unserviced_months": 1.0,
                "foreclosure_land_share_of_pledge": 1.0,
            },
        ),
    )


def arm_runs(
    *, root: str | Path = ".", output_root: str | Path = CONTRASTS_ROOT, seed: int = SEED
) -> tuple[ArmRun, ...]:
    """Run the four arms once each, on the historical core, and write their runs."""
    repository = Path(root)
    protocol = load_protocol(repository)
    runs: list[ArmRun] = []
    for arm in declared_arms():
        economy = build_integrated_economy(HISTORICAL_SCENARIO, parameter_sets=arm.parameter_sets())
        run_config = SimulationConfig.model_validate(
            {
                "tick_count": 240,
                "warmup_ticks": 24,
                "root_seed": seed,
                "scenario_id": f"{PREFIX}-{arm.label}",
                "policy_id": POLICY_ID,
            }
        )
        started = time.perf_counter()
        result = SimulationKernel(run_config, list(economy.systems)).run(run_label=arm.label)
        seconds = time.perf_counter() - started
        directory = RunStore(Path(output_root)).write(result)
        _write_arm_provenance(directory, arm)
        stamp_run(directory, protocol)
        counts = {
            str(row["event_type"]): int(row["len"])
            for row in result.events.group_by("event_type").len().iter_rows(named=True)
        }
        runs.append(
            ArmRun(
                arm=arm,
                facts=ArmFacts(
                    arm=arm.label,
                    run_id=result.manifest.run_id,
                    root_seed=seed,
                    simulation_digest=result.summary.simulation_digest,
                    event_total=result.events.height,
                    event_counts=counts,
                    chains=chain_summary(result.events),
                    seconds=seconds,
                ),
                events=result.events,
            )
        )
    return tuple(runs)


@dataclass(frozen=True, slots=True)
class BaseReading:
    """The assessable base of one run, in mu and as the share the governance line reads."""

    start_mu: float
    end_mu: float
    change_mu: float
    contraction_share: float

    def record(self) -> dict[str, float]:
        return {
            "start_mu": self.start_mu,
            "end_mu": self.end_mu,
            "change_mu": self.change_mu,
            "contraction_share": self.contraction_share,
        }


@dataclass(frozen=True, slots=True)
class EliteChain:
    """What the elite credit chain did in one run, as event counts and moved quantities."""

    loans: int
    defaults: int
    foreclosures: int
    land_transferred_mu: float
    pledge_mu: float
    settled_tael: float

    @property
    def fires(self) -> bool:
        """Whether the foreclosure branch transferred anything at all."""
        return self.foreclosures > 0 and self.land_transferred_mu > 0.0

    def record(self) -> dict[str, object]:
        return {
            "loans": self.loans,
            "defaults": self.defaults,
            "foreclosures": self.foreclosures,
            "land_transferred_mu": self.land_transferred_mu,
            "pledge_mu": self.pledge_mu,
            "settled_tael": self.settled_tael,
            "fires": self.fires,
        }


@dataclass(frozen=True, slots=True)
class ContrastRun:
    """One arm's run, re-read from disk and measured under the frozen protocol."""

    arm: Arm
    run_id: str
    root_seed: int
    simulation_digest: str
    event_total: int
    seconds: float
    base: BaseReading
    outcome: OutcomeVector
    elite: EliteChain
    chains: dict[str, float]
    indicators: dict[str, float]
    directions: dict[str, str]
    reading: RunReading
    starting_households: float
    no_op: str

    @property
    def label(self) -> str:
        return self.arm.label

    @property
    def configuration_diff(self) -> dict[str, float]:
        return self.arm.configuration_diff()

    def chain(self, key: str) -> float:
        if key not in self.chains:
            raise ContrastError(f"{self.run_id}: the log yields no chain fact {key!r}")
        return float(self.chains[key])

    def record(self) -> dict[str, Any]:
        return {
            "arm": self.label,
            "run_id": self.run_id,
            "root_seed": self.root_seed,
            "simulation_digest": self.simulation_digest,
            "event_total": self.event_total,
            "seconds": self.seconds,
            "description": self.arm.description,
            "expects_effect": self.arm.expects_effect,
            "configuration_diff": self.arm.configuration_diff(),
            "no_op_verdict": self.no_op,
            "base": self.base.record(),
            "governance_tax_base_contraction": self.indicators.get("tax_base_contraction"),
            "protocol_fiscal_base_mu": self.outcome.value("fiscal_base").value,
            "fiscal_base_resolution": self.outcome.value("fiscal_base").resolution,
            "migration_outflow": self.outcome.value("migration_outflow").value,
            "elite_chain": self.elite.record(),
            "starting_households": self.starting_households,
            "migration_chain": {name: self.chain(name) for name in M002_CHAIN_FACTS},
        }


def _base_reading(events: pl.DataFrame) -> BaseReading:
    """The assessable base, from the project's own per-county accessor.

    The three numbers a reader needs — the level at each end and the change between them — are read
    once and reported once, and the share is derived from them rather than taken from a second
    definition.
    """
    base = tax_base(events)
    start = total(base, "taxable_land_mu_start")
    end = total(base, "taxable_land_mu_end")
    if start <= 0.0:
        raise ContrastError(f"the run's opening assessable base is {start}, so no share exists")
    return BaseReading(
        start_mu=start,
        end_mu=end,
        change_mu=end - start,
        contraction_share=(start - end) / start,
    )


def _numeric(events: pl.DataFrame, field: str) -> pl.Series:
    """One trigger field as a number, refusing a frame that carries no such field at all."""
    column = events["trigger_json"].str.json_path_match(f"$.{field}").cast(pl.Float64, strict=False)
    if column.null_count() == events.height:
        raise ContrastError(f"no {field!r} in these rows' triggers")
    return column


def elite_chain(events: pl.DataFrame) -> EliteChain:
    """The credit chain as counts and moved quantities, not as a branch-firing verdict."""
    foreclosures = events.filter(pl.col("event_type") == FORECLOSURE_EVENT)
    moved: dict[str, float] = {}
    if not foreclosures.is_empty():
        moved = {
            field: float(_numeric(foreclosures, field).fill_null(0.0).sum())
            for field in TRANSFER_FIELDS
        }
    return EliteChain(
        loans=events.filter(pl.col("event_type") == LOAN_EVENT).height,
        defaults=events.filter(pl.col("event_type") == DEFAULT_EVENT).height,
        foreclosures=foreclosures.height,
        land_transferred_mu=moved.get("mu_transferred", 0.0),
        pledge_mu=moved.get("pledge_mu", 0.0),
        settled_tael=moved.get("settled_tael", 0.0),
    )


def _arm_of(run_id: str) -> Arm:
    """The declared arm a run id names, by the spelling the declaration produces."""
    for arm in declared_arms():
        if run_id.startswith(f"{PREFIX}-{arm.label}-"):
            return arm
    raise ContrastError(f"{run_id}: no declared arm produces a run id like this")


def _assert_stamp(directory: Path, *, protocol: ValidationProtocol) -> None:
    """Refuse a run that does not record the frozen protocol it was scored under."""
    path = directory / PROTOCOL_STAMP_FILE
    if not path.is_file():
        raise ContrastError(f"{directory.name} carries no {PROTOCOL_STAMP_FILE}")
    assert_batch_protocol(read_json(path), ProtocolFreeze.of(protocol))


def load_runs(
    *, root: str | Path = ".", output_root: str | Path = CONTRASTS_ROOT
) -> tuple[ContrastRun, ...]:
    """Re-open the four arms from disk and measure them under the frozen protocol.

    The denominators and the trade graph are rebuilt from each arm's declaration rather than read
    from the artifact, because they are properties of the arm: rebuilding them is what checks that
    the declaration on disk still produces the run that was written.
    """
    repository = Path(root)
    store = RunStore(Path(output_root))
    protocol = load_protocol(repository)
    thresholds = core_default_governance_indicators()
    run_ids = store.list_runs()
    if not run_ids:
        raise ContrastError(f"{store.root} holds no run; run the phase's four arms first")

    declared = {arm.label: arm for arm in declared_arms()}
    arms = tuple(_arm_of(run_id) for run_id in run_ids)
    if sorted(arm.label for arm in arms) != sorted(declared):
        raise ContrastError(
            f"{store.root} holds the arms {sorted(arm.label for arm in arms)}, and the phase "
            f"declares {sorted(declared)}"
        )
    read: list[tuple[ArmRun, pl.DataFrame, dict[str, Any], dict[str, Any]]] = []
    for run_id, arm in zip(run_ids, arms, strict=True):
        directory = store.run_dir(run_id)
        _assert_stamp(directory, protocol=protocol)
        events = read_table(directory / "agent_events.parquet")
        manifest = read_json(directory / "manifest.json")
        summary = read_json(directory / "summary.json")
        counts = {
            str(row["event_type"]): int(row["len"])
            for row in events.group_by("event_type").len().iter_rows(named=True)
        }
        read.append(
            (
                ArmRun(
                    arm=arm,
                    facts=ArmFacts(
                        arm=arm.label,
                        run_id=run_id,
                        root_seed=int(manifest["root_seed"]),
                        simulation_digest=str(summary["simulation_digest"]),
                        event_total=events.height,
                        event_counts=counts,
                        chains=chain_summary(events),
                    ),
                    events=events,
                ),
                events,
                manifest,
                summary,
            )
        )
    verdicts = {
        line.split(":", 1)[0]: line for line in detect_no_op(tuple(item[0] for item in read))
    }
    # The detector reports every *other* arm against the reference and says nothing about the
    # reference itself; the document says what it is instead of printing an empty cell.
    verdicts[REFERENCE_ARM] = "the neutral structure every other arm is compared against"
    runs: list[ContrastRun] = []
    for arm_run, events, _manifest, summary in read:
        arm = arm_run.arm
        economy = build_integrated_economy(HISTORICAL_SCENARIO, parameter_sets=arm.parameter_sets())
        population_adults = sum(cohort.adults for cohort in economy.population)
        starting_households = sum(cohort.households for cohort in economy.population)
        outcome = compute_outcomes(
            events,
            protocol,
            window_id=WINDOW,
            run_id=arm_run.facts.run_id,
            purpose=PURPOSE,  # type: ignore[arg-type]
            thresholds=thresholds,
            population_adults=population_adults,
            starting_households=starting_households,
            trade_graph=economy.graphs.trade,
        )
        indicators = governance_indicators(
            events,
            thresholds=thresholds,
            population_adults=population_adults,
            starting_households=starting_households,
        )
        chain = elite_chain(events)
        readings = read_run(
            run_id=arm_run.facts.run_id,
            arm=arm.label,
            root_seed=arm_run.facts.root_seed,
            policy_id=POLICY_ID,
            indicators={
                str(row["indicator"]): float(row["measure"])
                for row in indicators.select(["indicator", "measure"]).iter_rows(named=True)
            },
            directions={
                str(row["indicator"]): str(row["direction"])
                for row in indicators.select(["indicator", "direction"]).iter_rows(named=True)
            },
            events=events,
            elite_loans=float(chain.loans),
            bands_at_end=float(military_totals(events).get("bands_end", 0.0)),
        )
        runs.append(
            ContrastRun(
                arm=arm,
                run_id=arm_run.facts.run_id,
                root_seed=arm_run.facts.root_seed,
                simulation_digest=arm_run.facts.simulation_digest,
                event_total=arm_run.facts.event_total,
                seconds=float(summary.get("duration_seconds", 0.0)),
                base=_base_reading(events),
                outcome=outcome,
                elite=chain,
                chains=dict(arm_run.facts.chains),
                indicators=dict(readings.indicators),
                directions=dict(readings.directions),
                reading=readings,
                starting_households=starting_households,
                no_op=verdicts.get(arm.label, "no verdict"),
            )
        )
    return tuple(runs)


# --------------------------------------------------------------------------------------
# The continuous reading, then the projection
# --------------------------------------------------------------------------------------


def _run(runs: tuple[ContrastRun, ...], label: str) -> ContrastRun:
    for run in runs:
        if run.label == label:
            return run
    raise ContrastError(f"the contrast needs the {label!r} arm and the run set has no such arm")


@dataclass(frozen=True, slots=True)
class ContrastReading:
    """One paired contrast: the continuous difference between two runs, and its verdict."""

    name: str
    question: str
    arm_a: str
    arm_b: str
    reading: str
    value_a: float
    value_b: float
    difference: float
    minimum_substantive_effect: float
    direction_holds: bool
    substantive: bool
    falsifier: str
    falsifier_fires: bool

    def record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "question": self.question,
            "arm_a": self.arm_a,
            "arm_b": self.arm_b,
            "reading": self.reading,
            "value_a": self.value_a,
            "value_b": self.value_b,
            "difference": self.difference,
            "minimum_substantive_effect": self.minimum_substantive_effect,
            "direction_holds": self.direction_holds,
            "substantive": self.substantive,
            "falsifier": self.falsifier,
            "falsifier_fires": self.falsifier_fires,
        }


def _contrast(
    runs: tuple[ContrastRun, ...],
    *,
    name: str,
    question: str,
    arm_a: str,
    arm_b: str,
    reading: str,
    value_a: float,
    value_b: float,
    minimum_substantive_effect: float,
    falsifier: str,
) -> ContrastReading:
    difference = value_b - value_a
    direction_holds = difference > 0.0
    return ContrastReading(
        name=name,
        question=question,
        arm_a=arm_a,
        arm_b=arm_b,
        reading=reading,
        value_a=value_a,
        value_b=value_b,
        difference=difference,
        minimum_substantive_effect=minimum_substantive_effect,
        direction_holds=direction_holds,
        substantive=difference >= minimum_substantive_effect,
        falsifier=falsifier,
        falsifier_fires=not direction_holds,
    )


#: The M002 falsifier, verbatim from `docs/mechanisms/v2/M002.md`.
M002_FALSIFIER: Final[str] = (
    "A run in which the gate arm's tax base contracts no further than the baseline's would falsify "
    "the mechanism; no member of the ensemble shows it."
)

#: The M004 falsifier, verbatim from `docs/mechanisms/v2/M004.md`.
M004_FALSIFIER: Final[str] = (
    "The accumulating branch should contract the assessable base further than the closed-credit "
    "arm; if it does not, the bifurcation has no second branch and the card should say so in one "
    "sentence."
)


def m002_contrast(runs: tuple[ContrastRun, ...], *, root: str | Path = ".") -> ContrastReading:
    """The gate contrast, on the continuous reading the protocol declares for the base."""
    protocol = load_protocol(Path(root))
    outcome = protocol.outcome("fiscal_base")
    reference = _run(runs, REFERENCE_ARM)
    gate = _run(runs, "gate-open")
    return _contrast(
        runs,
        name="M002",
        question="On the historical core, does opening the gate the card names contract the base "
        "further than the reference?",
        arm_a=reference.label,
        arm_b=gate.label,
        reading="governance tax_base_contraction, the share the protocol's fiscal_base measures",
        value_a=reference.base.contraction_share,
        value_b=gate.base.contraction_share,
        minimum_substantive_effect=outcome.minimum_substantive_effect,
        falsifier=M002_FALSIFIER,
    )


def m004_contrast(runs: tuple[ContrastRun, ...], *, root: str | Path = ".") -> ContrastReading:
    """The elite contrast, accumulation against closed credit, on the same continuous reading."""
    protocol = load_protocol(Path(root))
    outcome = protocol.outcome("fiscal_base")
    closed = _run(runs, "elite-credit-closed")
    accumulation = _run(runs, "elite-accumulation")
    return _contrast(
        runs,
        name="M004",
        question="Does the accumulating branch contract the assessable base further than the "
        "closed-credit arm?",
        arm_a=closed.label,
        arm_b=accumulation.label,
        reading="governance tax_base_contraction, the share the protocol's fiscal_base measures",
        value_a=closed.base.contraction_share,
        value_b=accumulation.base.contraction_share,
        minimum_substantive_effect=outcome.minimum_substantive_effect,
        falsifier=M004_FALSIFIER,
    )


@dataclass(frozen=True, slots=True)
class BreakdownProjection:
    """The derived `breakdown` reading for one arm, over the frozen threshold ensemble."""

    arm: str
    lines: tuple[int, ...]
    shares: tuple[float, ...]
    mean_crossed: float
    members: int

    def record(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "members": self.members,
            "lines": list(self.lines),
            "shares": list(self.shares),
            "mean_crossed": self.mean_crossed,
        }


def readings_of(runs: tuple[ContrastRun, ...]) -> tuple[RunReading, ...]:
    """The four runs as the threshold machinery reads them.

    Built when the run was read, from that run's own log: the mechanism readings consume the event
    log, and a second construction here could measure a different frame than the one that produced
    the numbers beside it.
    """
    return tuple(run.reading for run in runs)


def threshold_projection(
    runs: tuple[ContrastRun, ...], *, root: str | Path = "."
) -> tuple[BreakdownProjection, ...]:
    """Project the runs onto the frozen ensemble: the share of members that reach each line.

    Computed *after* the continuous readings, and reported at every crossed count the protocol
    allows. The binary reading is never the headline, and no arm was chosen by looking at it.
    """
    repository = Path(root)
    protocol = load_protocol(repository)
    ensemble: ThresholdEnsemble = load_ensemble(repository)
    members = tuple(
        ensemble.by_indicator(draw) for draw in sample_draws(ensemble, draws=None, seed=20_260_915)
    )
    table = crossed_table(readings_of(runs), members)
    lines = breakdown_lines(protocol)
    projections: list[BreakdownProjection] = []
    for position, run in enumerate(runs):
        counts = table.counts[:, position]
        projections.append(
            BreakdownProjection(
                arm=run.label,
                lines=lines,
                shares=tuple(float((counts >= line).mean()) for line in lines),
                mean_crossed=float(counts.mean()),
                members=len(members),
            )
        )
    return tuple(projections)


# --------------------------------------------------------------------------------------
# The pre-registered status rules
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatusRecommendation:
    """A card's status, as the pre-registered rule decides it from the readings above."""

    card: str
    v2_status: str
    recommended: str
    rule: str
    evidence: tuple[str, ...]
    rejected: str

    def record(self) -> dict[str, Any]:
        return {
            "card": self.card,
            "v2_status": self.v2_status,
            "recommended": self.recommended,
            "rule": self.rule,
            "evidence": list(self.evidence),
            "rejected": self.rejected,
        }


def m002_status(reading: ContrastReading) -> StatusRecommendation:
    """M002's status under the rule the upgrade plan pre-registered.

    `CONDITIONAL` is kept only if the historical-core gate arm's contraction is larger *and* the
    difference reaches the protocol's declared minimum substantive effect. Below the effect the
    direction is there and the size is not, which is `WEAK`; a difference that is not positive at
    all is the card's own falsifier firing.
    """
    rule = (
        "the upgrade plan: M002 keeps CONDITIONAL only if the historical-core gate arm's "
        "continuous contraction differs from the reference in the pre-registered direction and by "
        "at least the fiscal_base minimum substantive effect "
        f"({reading.minimum_substantive_effect})"
    )
    evidence = (
        f"reference contraction {reading.value_a:.6f}, gate-open {reading.value_b:.6f}, "
        f"difference {reading.difference:+.6f}",
        "the threshold projection is reported beside this and decided nothing here",
    )
    if reading.falsifier_fires:
        return StatusRecommendation(
            card="M002",
            v2_status="CONDITIONAL",
            recommended="REJECTED",
            rule=rule,
            evidence=evidence,
            rejected=(
                "the mechanism claim: the falsifier fired, because the gate arm's base contracts "
                "no further than the reference's on this input"
            ),
        )
    if not reading.substantive:
        return StatusRecommendation(
            card="M002",
            v2_status="CONDITIONAL",
            recommended="WEAK",
            rule=rule,
            evidence=evidence,
            rejected=(
                "CONDITIONAL: the direction holds and the difference is below the declared "
                "minimum substantive effect, so the contrast is present but not of the size the "
                "status would rest on"
            ),
        )
    return StatusRecommendation(
        card="M002",
        v2_status="CONDITIONAL",
        recommended="CONDITIONAL",
        rule=rule,
        evidence=evidence,
        rejected="REJECTED: the falsifier did not fire and the difference is substantive",
    )


def m004_status(
    reading: ContrastReading, *, accumulation: ContrastRun, closed: ContrastRun
) -> StatusRecommendation:
    """M004's status under the rule the upgrade plan pre-registered.

    The card rises only if the accumulating branch contracts the base further than the closed-credit
    arm *and* the foreclosure/land-transfer chain is non-zero. A branch that does not fire measures
    nothing, and a branch that fires without an effect above the declared level is the card's
    falsifier: the second branch would then not be a different trajectory.
    """
    fires = accumulation.elite.fires
    rule = (
        "the upgrade plan: M004 rises from WEAK only if the accumulation arm's contraction exceeds "
        f"the closed-credit arm's by at least the minimum substantive effect "
        f"({reading.minimum_substantive_effect}) and the foreclosure/land-transfer chain is "
        "non-zero"
    )
    evidence = (
        f"credit-closed contraction {reading.value_a:.6f}, accumulation {reading.value_b:.6f}, "
        f"difference {reading.difference:+.6f}",
        f"accumulation chain: {accumulation.elite.foreclosures} foreclosures, "
        f"{accumulation.elite.land_transferred_mu:.1f} mu transferred, "
        f"{accumulation.elite.settled_tael:.1f} tael settled",
        f"credit-closed chain: {closed.elite.foreclosures} foreclosures, "
        f"{closed.elite.defaults} defaults, {closed.elite.loans} loans",
    )
    if not fires:
        return StatusRecommendation(
            card="M004",
            v2_status="WEAK",
            recommended="WEAK",
            rule=rule,
            evidence=evidence,
            rejected=(
                "any move: the accumulating branch transferred no land on this input, so the arm "
                "measures the absence of a chain rather than its effect"
            ),
        )
    if reading.substantive:
        return StatusRecommendation(
            card="M004",
            v2_status="WEAK",
            recommended="CONDITIONAL",
            rule=rule,
            evidence=evidence,
            rejected="WEAK: the branch fires and the base difference reaches the declared effect",
        )
    return StatusRecommendation(
        card="M004",
        v2_status="WEAK",
        recommended="WEAK",
        rule=rule,
        evidence=evidence,
        rejected=(
            "CONDITIONAL: the branch fires but the base difference is below the declared minimum "
            "substantive effect, so the branch's existence is measured and its effect is not"
        ),
    )


# --------------------------------------------------------------------------------------
# Cross-checks against what the cards were written against
# --------------------------------------------------------------------------------------


def p05_arm_digest(*, root: str | Path = ".", arm: str, seed: int) -> str:
    """One P05 arm's recorded digest, read from the phase's own declaration."""
    payload = json.loads((Path(root) / P05_ARMS).read_text(encoding="utf-8"))
    for entry in payload["arms"]:
        if entry["arm"] == arm and int(entry["root_seed"]) == seed:
            return str(entry["simulation_digest"])
    raise ContrastError(f"{P05_ARMS} declares no {arm!r} arm at seed {seed}")


def cross_checks(runs: tuple[ContrastRun, ...], *, root: str | Path = ".") -> dict[str, Any]:
    """Whether these runs are the experiments the cards were written against.

    Two arms are P05's own declarations run again, so their digests must repeat. A mismatch would
    mean the mechanism path moved since P05 and the contrasts are not comparable with the evidence
    the cards cite — which the phase reports rather than proceeding past.
    """
    reference = _run(runs, REFERENCE_ARM)
    accumulation = _run(runs, "elite-accumulation")
    expected_reference = p05_arm_digest(root=root, arm=REFERENCE_ARM, seed=SEED)
    expected_accumulation = p05_arm_digest(root=root, arm="elite-accumulation", seed=SEED)
    return {
        "reference": {
            "expected": expected_reference,
            "observed": reference.simulation_digest,
            "agrees": reference.simulation_digest == expected_reference,
        },
        "elite-accumulation": {
            "expected": expected_accumulation,
            "observed": accumulation.simulation_digest,
            "agrees": accumulation.simulation_digest == expected_accumulation,
        },
    }


# --------------------------------------------------------------------------------------
# The document
# --------------------------------------------------------------------------------------


def contrasts_payload(
    *, root: str | Path = ".", runs: tuple[ContrastRun, ...] | None = None
) -> dict[str, Any]:
    """The whole phase's numbers, with the continuous readings computed before the projection."""
    repository = Path(root)
    chosen = runs if runs is not None else load_runs(root=repository)
    protocol = load_protocol(repository)
    m002 = m002_contrast(chosen, root=repository)
    m004 = m004_contrast(chosen, root=repository)
    checks = cross_checks(chosen, root=repository)
    # The projection is computed here, after both continuous readings exist in memory, which is the
    # order the pre-registration fixes.
    projection = threshold_projection(chosen, root=repository)
    accumulation = _run(chosen, "elite-accumulation")
    closed = _run(chosen, "elite-credit-closed")
    return {
        "schema_version": "v2_1-decisive-contrasts-v1",
        "generator": GENERATOR,
        "protocol": {
            "version": protocol.version,
            "digest": protocol.digest(),
            "window": WINDOW,
            "purpose": PURPOSE,
            "outcome": "fiscal_base",
            "minimum_substantive_effect": protocol.outcome(
                "fiscal_base"
            ).minimum_substantive_effect,
        },
        "design": {
            "seed": SEED,
            "trajectories": len(chosen),
            "seed_is_a_replicate_axis": False,
            "note": (
                "one deterministic trajectory per arm; the historical core consumes no randomness, "
                "so a second seed would be a replay and not a sample"
            ),
        },
        "runs": [run.record() for run in chosen],
        "cross_checks": checks,
        "contrasts": {"M002": m002.record(), "M004": m004.record()},
        "projection": [entry.record() for entry in projection],
        "status": [
            m002_status(m002).record(),
            m004_status(m004, accumulation=accumulation, closed=closed).record(),
        ],
        "caveats": list(caveats(chosen)),
        "unchanged": [
            "M001, M003, M005 and M006: not touched by this phase",
            "no outcome, threshold band, hold-out window, historical input or core state "
            "transition",
        ],
    }


def caveats(runs: tuple[ContrastRun, ...]) -> tuple[str, ...]:
    """What the contrast's own chains say about reading its size as an effect.

    Measured rather than asserted: the arm's cumulative moves against the households that started,
    the exits it produced, and the declared accounting property that makes both matter. A reader who
    saw only the paired difference would take a property of the declaration for a property of the
    gate, which is the failure this list exists to prevent.
    """
    gate = _run(runs, "gate-open")
    moves = gate.chain("migration_movers_households")
    exits = float(gate.outcome.value("migration_outflow").value or 0.0)
    lines = [
        (
            f"the gate arm is the declared intervention at its open values — no move cost, no "
            f"transit loss, both unmet-ratio lines at zero — so its cohorts move every month: "
            f"{moves:.0f} cumulative household-moves against {gate.starting_households:.0f} "
            f"households that started, and {exits:.0f} out-of-region exits. The movers figure is a "
            "flow over 240 months and not a count of distinct households"
        ),
        (
            "an in-region move abandons land at the origin and the receiving cohort gains none — "
            "`receive_migrant_households` carries households, adults, grain, silver and assets, "
            "and no land — so repeated moves erode the assessable base further than the population "
            "that left would suggest. The direction of the contrast is not in doubt; its size is "
            "a property of those two declarations"
        ),
    ]
    if gate.base.end_mu < gate.base.start_mu * 0.05:
        lines.append(
            f"the gate arm's assessable base ends at {gate.base.end_mu:.0f} mu against "
            f"{gate.base.start_mu:.0f} at the start, a contraction of "
            f"{gate.base.contraction_share:.4f}"
        )
    return tuple(lines)


def _table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return lines


def _fired(value: bool) -> str:
    """Whether a falsifier fired, as the document prints it."""
    return "fired" if value else "did not fire"


def _accumulation_fires(runs: list[dict[str, Any]]) -> bool:
    """Whether the accumulating arm transferred any land, read from its own recorded chain."""
    return any(run["arm"] == "elite-accumulation" and run["elite_chain"]["fires"] for run in runs)


def decisive_markdown(payload: dict[str, Any]) -> str:
    """The document, rendered from the payload rather than from a second set of numbers."""
    runs = payload["runs"]
    m002 = payload["contrasts"]["M002"]
    m004 = payload["contrasts"]["M004"]
    lines = [
        "<!-- generated by: late-ming-lab experiment p11 -->",
        "",
        "# The two decisive contrasts",
        "",
        "Four arms, one 240-tick trajectory each, on the historical core at one seed. The seed "
        "is not a replicate axis: V2.1-P10 established from the artifacts that the historical core "
        "consumes no randomness, so a second seed would be a replay. Every number below is read "
        "from the run's own directory through a typed accessor, under the frozen protocol, on the "
        "whole-run window.",
        "",
        "## The arms",
        "",
    ]
    lines += _table(
        ("arm", "declares", "configuration diff", "no-op verdict", "digest"),
        [
            (
                run["arm"],
                run["description"],
                ", ".join(f"`{k}`={v}" for k, v in sorted(run["configuration_diff"].items()))
                or "*(nothing)*",
                run["no_op_verdict"],
                f"`{run['simulation_digest'][:12]}…`",
            )
            for run in runs
        ],
    )
    lines += [
        "",
        "### Are these the experiments the cards were written against?",
        "",
    ]
    lines += _table(
        ("arm", "P05's digest", "this run", "agrees"),
        [
            (name, f"`{entry['expected'][:12]}…`", f"`{entry['observed'][:12]}…`", entry["agrees"])
            for name, entry in payload["cross_checks"].items()
        ],
    )
    lines += [
        "",
        "## The continuous reading, first",
        "",
    ]
    lines += _table(
        ("reading", "reference-side", "value", "gate/branch side", "value", "paired difference"),
        [
            (
                "assessable base contraction share",
                m002["arm_a"],
                f"{m002['value_a']:.6f}",
                m002["arm_b"],
                f"{m002['value_b']:.6f}",
                f"{m002['difference']:+.6f}",
            ),
            (
                "assessable base contraction share",
                m004["arm_a"],
                f"{m004['value_a']:.6f}",
                m004["arm_b"],
                f"{m004['value_b']:.6f}",
                f"{m004['difference']:+.6f}",
            ),
        ],
    )
    lines += [
        "",
    ]
    lines += _table(
        ("arm", "base start (mu)", "base end (mu)", "change (mu)", "contraction share"),
        [
            (
                run["arm"],
                f"{run['base']['start_mu']:.1f}",
                f"{run['base']['end_mu']:.1f}",
                f"{run['base']['change_mu']:.1f}",
                f"{run['base']['contraction_share']:.6f}",
            )
            for run in runs
        ],
    )
    lines += [
        "",
        "### The chains behind them",
        "",
    ]
    lines += _table(
        (
            "arm",
            "migration not-eligible",
            "migration moved",
            "cumulative household-moves",
            "loans",
            "defaults",
            "foreclosures",
            "land transferred (mu)",
            "settled (tael)",
        ),
        [
            (
                run["arm"],
                f"{run['migration_chain']['migration_gate_share.not-eligible']:.4f}",
                f"{run['migration_chain']['migration_gate_share.moved']:.4f}",
                f"{run['migration_chain']['migration_movers_households']:.1f}",
                run["elite_chain"]["loans"],
                run["elite_chain"]["defaults"],
                run["elite_chain"]["foreclosures"],
                f"{run['elite_chain']['land_transferred_mu']:.1f}",
                f"{run['elite_chain']['settled_tael']:.1f}",
            )
            for run in runs
        ],
    )
    lines += [
        "",
        "### What the chains say about reading this size as an effect",
        "",
    ]
    lines += [f"- {item}" for item in payload["caveats"]]
    lines += [
        "",
        "## Falsifiers, as the cards state them",
        "",
        f"- **M002** — {m002['falsifier']} → **{_fired(m002['falsifier_fires'])}**",
        f"- **M004** — {m004['falsifier']} → **{_fired(m004['falsifier_fires'])}**",
        f"  (the paired base difference is {m004['difference']:+.6f}, and the accumulating branch "
        f"fires: {'yes' if _accumulation_fires(runs) else 'no'})",
        "",
        "## The threshold projection, second",
        "",
        "The derived `breakdown` reading, projected onto the frozen ensemble: the share of "
        "members under which each arm crosses at least that many of the eight reading lines. "
        "Reported at every crossed count the protocol allows, and it decided nothing above.",
        "",
    ]
    lines += _table(
        ("arm", "members", *[str(line) for line in payload["projection"][0]["lines"]]),
        [
            (
                entry["arm"],
                entry["members"],
                *[f"{share:.3f}" for share in entry["shares"]],
            )
            for entry in payload["projection"]
        ],
    )
    lines += [
        "",
        "## Status, as the pre-registered rules decide it",
        "",
    ]
    for entry in payload["status"]:
        lines += [
            f"### {entry['card']} — {entry['v2_status']} → **{entry['recommended']}**",
            "",
            f"- rule: {entry['rule']}",
            *[f"- evidence: {item}" for item in entry["evidence"]],
            f"- rejected: {entry['rejected']}",
            "",
        ]
    lines += [
        "## What this phase does not say",
        "",
        "- The engine is not the record: these are statements about this model under a declared "
        "  configuration, not findings about the past.",
        "- One trajectory per arm is a complete sample *because* the run is deterministic; it is "
        "not an uncertainty estimate, and no interval is reported.",
        "- M001, M003, M005 and M006 are not touched, and no card is rewritten here: the "
        "recommendations above are for V2.1-P12.",
        "",
    ]
    return "\n".join(lines)


def write_documents(
    *, root: str | Path = ".", runs: tuple[ContrastRun, ...] | None = None
) -> tuple[Path, Path]:
    """Write both documents; return their paths."""
    repository = Path(root)
    payload = contrasts_payload(root=repository, runs=runs)
    return (
        write_json(repository / MACHINE, payload),
        write_text(repository / DOCUMENT, decisive_markdown(payload) + "\n"),
    )


__all__ = [
    "CONTRASTS_ROOT",
    "DOCUMENT",
    "GENERATOR",
    "M002_FALSIFIER",
    "M004_FALSIFIER",
    "MACHINE",
    "PREFIX",
    "SEED",
    "BaseReading",
    "BreakdownProjection",
    "ContrastError",
    "ContrastReading",
    "ContrastRun",
    "EliteChain",
    "StatusRecommendation",
    "arm_runs",
    "contrasts_payload",
    "cross_checks",
    "decisive_markdown",
    "declared_arms",
    "elite_chain",
    "load_runs",
    "m002_contrast",
    "m002_status",
    "m004_contrast",
    "m004_status",
    "p05_arm_digest",
    "readings_of",
    "threshold_projection",
    "write_documents",
]
