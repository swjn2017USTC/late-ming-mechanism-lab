"""V2-P04: competing structures on the historical core, and the diagnosis they support.

V1's reserved windows failed in four places. This module runs the structures that test what each
failure points at — on the *same* historical input, at the *same* world seeds, and with the same
protocol scoring them — and writes down what each failure turns out to be:

```text
data            the input the model was given, not the mechanism
observation      the quantity the check reads, not the process it reads it from
parameter        a declared number
structure        a mechanism the model lacks, or has in a form that cannot produce the pattern
undetermined     nothing this model currently measures can decide it
```

Three things keep the phase honest, and each is a refusal rather than a promise:

1. **Every arm must intervene.** An arm whose configuration diff is empty, or whose event counts and
   chain intermediates are identical to the reference at the same seeds, is refused. The phase also
   runs a deliberate no-op control — the variants with their new parameters at neutral values — and
   requires the detector to catch it.
2. **The reference must still reproduce.** The historical-core scenario declares the digest of its
   own run; the reference arm is required to reproduce it, so a variant cannot quietly become the
   new baseline.
3. **The hold-out is reported, never optimised.** The checks are printed beside the protocol's
   primary outcome vector and its mechanism criteria; no arm is selected because a reserved
   window turned green, and no threshold in the frozen protocol is moved to make one do so.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, TypeVar

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from late_ming_lab.analysis.chains import chain_deltas, chain_summary
from late_ming_lab.analysis.governance import governance_indicators
from late_ming_lab.calibration.prediction import PredictiveChecks, observe
from late_ming_lab.calibration.windows import CalibrationWindow, window
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import SimulationKernel
from late_ming_lab.evidence.ledger import load_patterns
from late_ming_lab.evidence.parameters import (
    MarketParameters,
    MigrationParameters,
    core_default_governance_indicators,
    core_default_market_parameters,
    core_default_migration_parameters,
)
from late_ming_lab.experiments.historical_core import HISTORICAL_SCENARIO
from late_ming_lab.experiments.integrated import build_integrated_economy
from late_ming_lab.protocol.outcomes import compute_outcomes
from late_ming_lab.protocol.robustness import evaluate, read_run
from late_ming_lab.protocol.schema import load_protocol
from late_ming_lab.protocol.thresholds import load_ensemble, sample_draws
from late_ming_lab.storage.run_store import RunStore
from late_ming_lab.storage.tables import read_json, read_table

_T = TypeVar("_T", MarketParameters, MigrationParameters)

#: The file an arm writes beside its run: the declaration, the diff, and the parameter sets used.
ARM_PROVENANCE_FILE: Final[str] = "holdout-arm.json"

#: Where the phase's runs are written. A V2 root, like every other V2 output.
HOLDOUT_ROOT: Final[str] = "outputs/v2/p04"

#: The reference arm's label: the V1 structure on the V2 input.
REFERENCE_ARM: Final[str] = "reference"

#: The declared world seeds. Identical across arms: a structural difference read across different
#: seeds would be a difference between seeds.
HOLDOUT_SEEDS: Final[tuple[int, ...]] = (20_260_915, 20_260_916, 20_260_917, 20_260_918)

#: The four V1 failures this phase diagnoses: the pattern, the check, the surface the check was read
#: on, and the V1 numbers as the calibration documents record them.
#:
#: The surface matters and is not decoration: three of the four are hold-out or extrapolation checks
#: (`docs/calibration/prediction.md`), and the price-dispersion failure is a calibration-window
#: mismatch check (`docs/calibration/mismatch.md`). A check read on the calibration window cannot be
#: re-scored by V2-P04's machinery — the prediction path refuses that window, which is the isolation
#: V2-P03 froze — so for that one the recorded V1 share is reported and the phase reports the chain
#: facts beside it instead.
FAILED_CHECKS: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "chongzhen-drought-sequence",
        "shock-peak-in-late-years",
        "hold-out / whole-run",
    ),
    (
        "famine-local-price-extremes",
        "dispersion-widens",
        "calibration mismatch",
    ),
    (
        "relief-overwhelmed-in-worst-years",
        "relief-coverage-falls-as-need-peaks",
        "hold-out / extrapolation",
    ),
    ("shaanxi-net-outflow", "exits-in-crisis-years", "hold-out / extrapolation"),
)

#: What V1 recorded for these checks, read from the two calibration documents. These are V1's own
#: numbers, cited rather than recomputed: re-deriving them would mean re-running V1's ensemble.
V1_RECORDED: Final[dict[str, dict[str, float]]] = {
    "shock-peak-in-late-years": {"hold-out": 0.0, "whole-run": 0.0},
    "dispersion-widens": {"calibration": 0.44},
    "dispersion-tracks-distress": {"calibration": 0.38},
    "relief-coverage-falls-as-need-peaks": {"hold-out": 0.25, "extrapolation": 0.0},
    "exits-in-crisis-years": {"hold-out": 0.16, "extrapolation": 0.0},
}

#: Where those numbers are recorded, so a reader can open the file rather than trust this table.
V1_RECORDED_SOURCE: Final[str] = "docs/calibration/prediction.md and docs/calibration/mismatch.md"


class HoldoutError(RuntimeError):
    """Raised when an arm cannot be run, or when an arm did not do what it declared."""


@dataclass(frozen=True, slots=True)
class Arm:
    """One declared structure: what it changes, and what it must and must not move.

    `expects_effect` is the declaration the detector checks. A *variant* declares True and must move
    at least one event count or chain fact against the reference at the same seeds; an *ablation*
    declares False and must reproduce the reference exactly. Both directions are refusals: an arm
    that does nothing when it declared a structure would be a null result reported as a contrast,
    and an ablation that does something would mean the parameter is not what carries it.
    """

    label: str
    description: str
    expects_effect: bool
    market: dict[str, float] = field(default_factory=dict)
    migration: dict[str, float] = field(default_factory=dict)

    def market_parameters(self) -> MarketParameters:
        return self._applied(core_default_market_parameters(), self.market)

    def migration_parameters(self) -> MigrationParameters:
        return self._applied(core_default_migration_parameters(), self.migration)

    @staticmethod
    def _applied(base: _T, overrides: dict[str, float]) -> _T:
        """The base set with this arm's overrides, refusing a name the set does not have.

        `model_copy(update=...)` ignores a field it does not recognise, so a misspelled override
        would leave the arm running the reference's value while its declaration says otherwise — a
        silent no-op. The check is here rather than in the diff, which is what a reader trusts.
        """
        unknown = sorted(set(overrides) - set(type(base).model_fields))
        if unknown:
            raise HoldoutError(
                f"{type(base).__name__} has no field {', '.join(unknown)}; an override that names "
                "nothing would leave this arm running the reference's value"
            )
        return base if not overrides else base.model_copy(update=overrides)

    def configuration_diff(self) -> dict[str, float]:
        """The parameters this arm moves away from the reference, by name."""
        moved: dict[str, float] = {}
        for name, value in self.market.items():
            reference = getattr(core_default_market_parameters(), name)
            if value != reference:
                moved[f"MarketParameters.{name}"] = float(value)
        for name, value in self.migration.items():
            reference = getattr(core_default_migration_parameters(), name)
            if value != reference:
                moved[f"MigrationParameters.{name}"] = float(value)
        return moved


def declared_arms() -> tuple[Arm, ...]:
    """The arms this phase runs: the reference, two competing structures, their ablations, and the
    declared forcing contrast.

    The two structures answer the two failures whose evidence points at the mechanism rather than at
    the input or at a number: the price rule that cannot see demand without silver, and the
    departure rule that needs silver and a rolling unmet ratio before it will let anyone go.
    """
    return (
        Arm(
            label=REFERENCE_ARM,
            description="the V1 structure on the historical core, with the chains recorded",
            expects_effect=False,
            market={"demand_pressure_weight": 0.0},
            migration={"destitution_departure_share": 0.0, "destitution_exit_share": 0.0},
        ),
        Arm(
            label="price-demand-pressure",
            description=(
                "the posted price responds to the grain buyers wanted and did not get, beside the "
                "inventory rule"
            ),
            expects_effect=True,
            market={"demand_pressure_weight": 2.0, "demand_pressure_cap": 4.0},
        ),
        Arm(
            label="price-demand-pressure-off",
            description="the same declaration with the weight at zero: its ablation",
            expects_effect=False,
            market={"demand_pressure_weight": 0.0, "demand_pressure_cap": 4.0},
        ),
        Arm(
            label="migration-distress-route",
            description=(
                "a destitute cohort may leave without eligibility or silver, and a declared "
                "share of those departures takes the out-of-region road"
            ),
            expects_effect=True,
            migration={"destitution_departure_share": 0.05, "destitution_exit_share": 0.5},
        ),
        Arm(
            label="migration-distress-route-off",
            description="the same declaration with both shares at zero: the ablation",
            expects_effect=False,
            migration={"destitution_departure_share": 0.0, "destitution_exit_share": 0.0},
        ),
    )


class ArmFacts(BaseModel):
    """What one arm's run produced, in the terms the detector compares."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    arm: str
    run_id: str
    root_seed: int
    simulation_digest: str
    event_total: int
    event_counts: dict[str, int] = Field(default_factory=dict)
    chains: dict[str, float] = Field(default_factory=dict)
    seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class ArmRun:
    """One arm's run: its facts, its log, and the window scores read from it."""

    arm: Arm
    facts: ArmFacts
    events: pl.DataFrame
    checks: dict[str, dict[str, float]] = field(default_factory=dict)


def run_arm(
    arm: Arm,
    *,
    root: str | Path = ".",
    root_seed: int,
    output_root: str | Path = HOLDOUT_ROOT,
    ticks: int = 240,
    warmup_ticks: int = 24,
) -> ArmRun:
    """Run one declared structure on the historical core, keeping its log."""
    economy = build_integrated_economy(
        HISTORICAL_SCENARIO,
        parameter_sets={
            "MarketParameters": arm.market_parameters(),
            "MigrationParameters": arm.migration_parameters(),
        },
    )
    run_config = SimulationConfig.model_validate(
        {
            "tick_count": ticks,
            "warmup_ticks": warmup_ticks,
            "root_seed": root_seed,
            "scenario_id": f"p04-{arm.label}",
            "policy_id": "p04-holdout-v1",
        }
    )
    started = time.perf_counter()
    result = SimulationKernel(run_config, list(economy.systems)).run(run_label=arm.label)
    seconds = time.perf_counter() - started
    directory = RunStore(Path(output_root)).write(result)
    _write_arm_provenance(directory, arm)
    counts = {
        str(row["event_type"]): int(row["len"])
        for row in result.events.group_by("event_type").len().iter_rows(named=True)
    }
    facts = ArmFacts(
        arm=arm.label,
        run_id=result.manifest.run_id,
        root_seed=root_seed,
        simulation_digest=result.summary.simulation_digest,
        event_total=result.events.height,
        event_counts=counts,
        chains=chain_summary(
            result.events,
            windows=(
                ("calibration", 0, 119),
                ("hold-out", 120, 215),
                ("extrapolation", 216, 239),
            ),
        ),
        seconds=seconds,
    )
    return ArmRun(arm=arm, facts=facts, events=result.events)


def _write_arm_provenance(directory: Path, arm: Arm) -> Path:
    """Record what this arm declared and what it actually ran, beside its run.

    A run's `manifest.json` and `config.snapshot.yaml` carry the kernel configuration, and the
    parameter sets are not part of it: without this file an arm's parameters would be recoverable
    only from the log's effects, which is what a reviewer should not have to do. The values written
    here are the ones the economy was built with, not the ones the declaration named.
    """
    market = arm.market_parameters()
    migration = arm.migration_parameters()
    path = directory / ARM_PROVENANCE_FILE
    path.write_text(
        json.dumps(
            {
                "schema_version": "holdout-arm-v1",
                "arm": arm.label,
                "description": arm.description,
                "expects_effect": arm.expects_effect,
                "configuration_diff": arm.configuration_diff(),
                "market_parameters": market.model_dump(mode="json"),
                "migration_parameters": migration.model_dump(mode="json"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def window_checks(
    events: pl.DataFrame, *, registry_root: str | Path = "."
) -> dict[str, dict[str, float]]:
    """The reserved windows' checks for one run, read through the code the objective uses.

    These are the numbers V1 failed on. They are reported for every arm and never used to select
    one: a structure is chosen on the evidence a failure points at, not on whether a reserved
    window improves.
    """
    predictive = PredictiveChecks.from_registry(load_patterns(registry_root))
    scores: dict[str, dict[str, float]] = {}
    for window_id in ("hold-out", "extrapolation", "whole-run"):
        scored = observe(events, window=_window(window_id), predictive=predictive).scores
        for pattern in scored.patterns:
            for outcome in pattern.checks:
                key = f"{window_id}.{outcome.check_id}"
                scores[key] = {
                    "value": float(outcome.value),
                    "satisfied": 1.0 if outcome.satisfied else 0.0,
                }
    return scores


def _window(window_id: str) -> CalibrationWindow:
    """The declared window of that role; the whole run is declared separately from the split."""
    from late_ming_lab.calibration.windows import WindowRole, whole_run_window

    if window_id == WindowRole.WHOLE_RUN.value:
        return whole_run_window()
    return window(WindowRole(window_id))


def run_declared_arms(
    *,
    root: str | Path = ".",
    arms: tuple[Arm, ...] | None = None,
    seeds: tuple[int, ...] = HOLDOUT_SEEDS,
    output_root: str | Path = HOLDOUT_ROOT,
    progress: bool = False,
) -> tuple[ArmRun, ...]:
    """Every arm at every declared seed, in declaration order."""
    chosen = arms or declared_arms()
    runs: list[ArmRun] = []
    for arm in chosen:
        for seed in seeds:
            run = run_arm(arm, root=root, root_seed=seed, output_root=output_root)
            runs.append(run)
            if progress:
                print(f"{arm.label} seed {seed}: {run.facts.run_id} in {run.facts.seconds:.1f}s")
    return tuple(runs)


def detect_no_op(runs: tuple[ArmRun, ...]) -> tuple[str, ...]:
    """Refuse an arm that did not do what it declared, and report what each one moved.

    Returns one line per arm: either what it moved (variant) or that it reproduced the reference
    exactly (ablation). Raises when an arm's behaviour contradicts its declaration, or when an arm
    declares an intervention but has an empty configuration diff — which is the no-op the phase's
    acceptance says must fail it.
    """
    by_arm: dict[str, list[ArmRun]] = {}
    declared: dict[str, Arm] = {}
    for run in runs:
        by_arm.setdefault(run.arm.label, []).append(run)
        previous = declared.setdefault(run.arm.label, run.arm)
        if previous != run.arm:
            raise HoldoutError(
                f"{run.arm.label}: two different arms share one label, so the comparison would "
                "depend on which of them the baseline happened to collect"
            )
    if REFERENCE_ARM not in by_arm:
        raise HoldoutError(f"the {REFERENCE_ARM!r} arm is required to compare against")
    reference_arm = declared[REFERENCE_ARM]
    if reference_arm.expects_effect or reference_arm.configuration_diff():
        raise HoldoutError(
            f"the {REFERENCE_ARM!r} arm must be the neutral structure: it declares "
            f"expects_effect={reference_arm.expects_effect} and moves "
            f"{sorted(reference_arm.configuration_diff())}; every other arm is compared against it"
        )
    reference = {run.facts.root_seed: run for run in by_arm[REFERENCE_ARM]}
    report: list[str] = []
    for label, arm_runs in by_arm.items():
        if label == REFERENCE_ARM:
            continue
        arm = arm_runs[0].arm
        diff = arm.configuration_diff()
        if arm.expects_effect and not diff:
            raise HoldoutError(
                f"{label}: declares a structural change but moves no parameter; an arm with an "
                "empty configuration diff is a no-op"
            )
        verdicts: set[bool] = set()
        movers: list[str] = []
        for run in arm_runs:
            baseline = reference.get(run.facts.root_seed)
            if baseline is None:
                raise HoldoutError(f"{label}: seed {run.facts.root_seed} has no reference run")
            moved = _moved_facts(baseline.facts, run.facts)
            verdicts.add(bool(moved))
            if moved:
                movers.extend(sorted(moved))
        if len(verdicts) != 1:
            raise HoldoutError(
                f"{label}: the same declaration moved facts at some seeds and not others, so the "
                "difference is not attributable to the structure"
            )
        did_move = verdicts.pop()
        if arm.expects_effect and not did_move:
            raise HoldoutError(
                f"{label}: declared a structure and produced no difference from the reference at "
                "any declared seed — a no-op arm"
            )
        if not arm.expects_effect and diff:
            raise HoldoutError(
                f"{label}: an ablation must sit at the reference's parameter values, and it moves "
                f"{sorted(diff)}; an inert override would make the ablation a claim rather than a "
                "control"
            )
        if not arm.expects_effect and did_move:
            raise HoldoutError(
                f"{label}: an ablation must reproduce the reference exactly, and it moved "
                f"{', '.join(sorted(set(movers)))}; the parameter is then not what carries the "
                "intervention"
            )
        detail = ", ".join(sorted(set(movers))) if did_move else "reproduced the reference"
        report.append(f"{label}: {detail}")
    return tuple(report)


def _moved_facts(reference: ArmFacts, arm: ArmFacts) -> set[str]:
    """Which declared facts differ between two runs at the same seed."""
    moved: set[str] = set()
    if arm.simulation_digest != reference.simulation_digest:
        moved.add("simulation_digest")
    if arm.event_total != reference.event_total:
        moved.add("event_total")
    for name in sorted(set(reference.event_counts) | set(arm.event_counts)):
        if arm.event_counts.get(name, 0) != reference.event_counts.get(name, 0):
            moved.add(f"events.{name}")
    for name, delta in chain_deltas(reference.chains, arm.chains).items():
        if delta != 0.0:
            moved.add(f"chains.{name}")
    return moved


class FailureDiagnosis(BaseModel):
    """One V1 failure, what the evidence says it was, and what stays open."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern: str
    check: str
    classification: Literal["data", "observation", "parameter", "structure", "undetermined"]
    surface: str
    v1_recorded: dict[str, float] = Field(default_factory=dict)
    reference_checks: dict[str, dict[str, float]] = Field(default_factory=dict)
    evidence: dict[str, float | str | None] = Field(default_factory=dict)
    boundary: str


def diagnosis_table(
    runs: tuple[ArmRun, ...], *, root: str | Path = "."
) -> tuple[FailureDiagnosis, ...]:
    """Each V1 failure, what its evidence points at, and the boundary that stays open.

    The classification is written here rather than inferred, because it is an argument about what
    the evidence shows, and a reader has to be able to disagree with it by reading the numbers.
    """
    reference = next(run for run in runs if run.arm.label == REFERENCE_ARM)
    checks = window_checks(reference.events, registry_root=root)
    chains = reference.facts.chains
    return (
        FailureDiagnosis(
            pattern="chongzhen-drought-sequence",
            check="shock-peak-in-late-years",
            surface="hold-out / whole-run",
            classification="data",
            v1_recorded=dict(V1_RECORDED["shock-peak-in-late-years"]),
            reference_checks={
                "hold-out": checks.get("hold-out.shock-peak-in-late-years", {}),
                "whole-run": checks.get("whole-run.shock-peak-in-late-years", {}),
            },
            evidence={
                "forcing": "observed-historical",
                "peak_severity_year": _peak_year(reference.events),
                "note": (
                    "the synthetic mode draws severity uniformly, so its worst year is anywhere; "
                    "the observed series peaks in the late 1630s and early 1640s"
                ),
            },
            boundary=(
                "one regional annual index allocated to months by a declared seasonal profile, not "
                "a per-node reconstruction; the index's own uncertainty is not propagated"
            ),
        ),
        FailureDiagnosis(
            pattern="famine-local-price-extremes",
            check="dispersion-widens",
            surface="calibration mismatch",
            classification="structure",
            v1_recorded=dict(V1_RECORDED["dispersion-widens"]),
            reference_checks={},
            evidence={
                "price_ceiling_share": chains.get("price_ceiling_share"),
                "price_max_tael_per_shi": chains.get("price_max_tael_per_shi"),
                "price_dispersion_mean": chains.get("price_dispersion_mean"),
                "unfilled_demand_shi": chains.get("price_unfilled_demand_shi"),
                "unaffordable_demand_shi": chains.get("price_unaffordable_demand_shi"),
                "bound_share_inventory": chains.get("price_bound_share.inventory"),
                "bound_share_ceiling": chains.get("price_bound_share.ceiling"),
                "dependency": "recorded: 4 tael per dou at Shangzhou in 1631, i.e. 40 tael per shi",
            },
            boundary=(
                "the price rule's ceiling is a declared ratio of the reference price, so a "
                "magnitude comparison with the record is out of reach until the rule is rebuilt on "
                "evidence; what the phase can say is which constraint bound and by how much"
            ),
        ),
        FailureDiagnosis(
            pattern="relief-overwhelmed-in-worst-years",
            check="relief-coverage-falls-as-need-peaks",
            surface="hold-out / extrapolation",
            classification="structure",
            v1_recorded=dict(V1_RECORDED["relief-coverage-falls-as-need-peaks"]),
            reference_checks={
                "hold-out": checks.get("hold-out.relief-coverage-falls-as-need-peaks", {}),
                "extrapolation": checks.get(
                    "extrapolation.relief-coverage-falls-as-need-peaks", {}
                ),
            },
            evidence={
                "coverage_share": chains.get("relief_coverage_share"),
                "bound_share_stock": chains.get("relief_bound_share.stock"),
                "bound_share_capacity": chains.get("relief_bound_share.capacity"),
                "bound_share_eligibility": chains.get("relief_bound_share.eligibility"),
                "bound_share_silver": chains.get("relief_bound_share.silver"),
                "bound_share_none": chains.get("relief_bound_share.none"),
            },
            boundary=(
                "the chain shows what the ratio cannot: on this run the granary and the roads "
                "never bind and the eligibility line binds most county-months, so what the model "
                "reports as coverage is largely an eligibility composition — a structure, not a "
                "shortage of grain. Two things stay open. The statistic itself: coverage divides "
                "relief by the whole subsistence floor, which no granary was ever sized to meet, "
                "so it cannot separate 'overwhelmed by need' from 'refused by a rule', and the "
                "chain events are what the phase adds to fix that. And the mechanism: whether the "
                "eligibility line is the right relief rule is a V2-P05 question, and the record "
                "does not yet say which bottleneck the historical system actually hit"
            ),
        ),
        FailureDiagnosis(
            pattern="shaanxi-net-outflow",
            check="exits-in-crisis-years",
            surface="hold-out / extrapolation",
            classification="structure",
            v1_recorded=dict(V1_RECORDED["exits-in-crisis-years"]),
            reference_checks={
                "hold-out": checks.get("hold-out.exits-in-crisis-years", {}),
                "extrapolation": checks.get("extrapolation.exits-in-crisis-years", {}),
            },
            evidence={
                "exit_events": float(reference.facts.event_counts.get("MIGRATION_EXIT", 0)),
                "departures": float(reference.facts.event_counts.get("MIGRATION_DEPARTURE", 0)),
                "movers_households": chains.get("migration_movers_households"),
                "gate_silver_share": chains.get("migration_gate_share.silver"),
                "gate_not_eligible_share": chains.get("migration_gate_share.not-eligible"),
                "dependency": "V1 sends a mover to the cheapest reachable county and exits last",
            },
            boundary=(
                "the distress route's shares are assumptions, not measurements, and the split "
                "between internal and out-of-region movement in this window is not established by "
                "any source the project holds"
            ),
        ),
    )


def _peak_year(events: pl.DataFrame) -> int:
    shocks = events.filter(pl.col("event_type") == "CLIMATE_SHOCK")
    yearly = (
        shocks.with_columns(
            pl.col("trigger_json")
            .str.json_path_match("$.severity")
            .cast(pl.Float64)
            .alias("severity")
        )
        .with_columns((1625 + (pl.col("tick") // 12)).alias("year"))
        .group_by("year")
        .agg(pl.col("severity").mean().alias("severity"))
        .sort("severity", descending=True)
    )
    return int(yearly["year"][0]) if yearly.height else 0


__all__ = [
    "FAILED_CHECKS",
    "HOLDOUT_ROOT",
    "HOLDOUT_SEEDS",
    "REFERENCE_ARM",
    "Arm",
    "ArmFacts",
    "ArmRun",
    "HoldoutError",
    "declared_arms",
    "detect_no_op",
    "diagnosis_table",
    "load_arm_runs",
    "protocol_scores",
    "run_arm",
    "run_declared_arms",
    "window_checks",
]


def load_arm_runs(
    *,
    root: str | Path = ".",
    output_root: str | Path = HOLDOUT_ROOT,
    arms: tuple[Arm, ...] | None = None,
) -> tuple[ArmRun, ...]:
    """Re-open the arms' runs from disk, so a document can be rewritten without re-running them.

    The facts are recomputed from the stored logs by the same functions that produced them, so a
    regenerated document is a re-reading rather than a copy. An arm whose run is missing is refused
    instead of being silently dropped: a comparison against a subset of the declared arms would be a
    different comparison.
    """
    chosen = arms or declared_arms()
    directory_root = Path(output_root)
    runs: list[ArmRun] = []
    for arm in chosen:
        prefix = f"p04-{arm.label}-"
        directories = sorted(
            path
            for path in directory_root.glob(f"{prefix}*")
            if path.name[len(prefix) :].split("-", 1)[0].isdigit()
            and (path / "agent_events.parquet").is_file()
        )
        if not directories:
            raise HoldoutError(
                f"{arm.label}: no stored run under {directory_root}; run the phase first"
            )
        for directory in directories:
            events = read_table(directory / "agent_events.parquet")
            manifest = read_json(directory / "manifest.json")
            summary = read_json(directory / "summary.json")
            counts = {
                str(row["event_type"]): int(row["len"])
                for row in events.group_by("event_type").len().iter_rows(named=True)
            }
            runs.append(
                ArmRun(
                    arm=arm,
                    facts=ArmFacts(
                        arm=arm.label,
                        run_id=str(manifest["run_id"]),
                        root_seed=int(manifest["root_seed"]),
                        simulation_digest=str(summary["simulation_digest"]),
                        event_total=events.height,
                        event_counts=counts,
                        chains=chain_summary(
                            events,
                            windows=(
                                ("calibration", 0, 119),
                                ("hold-out", 120, 215),
                                ("extrapolation", 216, 239),
                            ),
                        ),
                    ),
                    events=events,
                )
            )
    return tuple(runs)


def protocol_scores(
    runs: tuple[ArmRun, ...], *, root: str | Path = ".", ensemble_members: int | None = None
) -> dict[str, dict[str, object]]:
    """Score every arm with the protocol V2-P03 froze: the outcome vector, and the reading lines'.

    The protocol's mechanism criteria are bound to the arms of V2-P03's own pilot, so on these runs
    the ones that need a contrast between arms report ``undetermined`` — which is the honest answer
    and is printed as one, rather than being re-pointed at whichever of these arms looks closest.
    The outcome vector and the crossed-line distribution are the part that transfers.
    """
    repository = Path(root)
    protocol = load_protocol(repository)
    ensemble = load_ensemble(repository)
    draws = sample_draws(ensemble, draws=ensemble_members, seed=20_260_915)
    members = tuple(ensemble.by_indicator(draw) for draw in draws)
    thresholds = core_default_governance_indicators()
    scores: dict[str, dict[str, object]] = {}
    for run in runs:
        economy = build_integrated_economy(
            HISTORICAL_SCENARIO,
            parameter_sets={
                "MarketParameters": run.arm.market_parameters(),
                "MigrationParameters": run.arm.migration_parameters(),
            },
        )
        population_adults = sum(cohort.adults for cohort in economy.population)
        starting_households = sum(cohort.households for cohort in economy.population)
        vector = compute_outcomes(
            run.events,
            protocol,
            window_id="whole-run",
            run_id=run.facts.run_id,
            purpose="report",
            thresholds=thresholds,
            population_adults=population_adults,
            starting_households=starting_households,
            trade_graph=economy.graphs.trade,
        )
        indicators_frame = governance_indicators(
            run.events,
            thresholds=thresholds,
            population_adults=population_adults,
            starting_households=starting_households,
        )
        reading = read_run(
            run_id=run.facts.run_id,
            arm=run.arm.label,
            root_seed=run.facts.root_seed,
            policy_id="p04-holdout-v1",
            indicators={
                row["indicator"]: float(row["measure"])
                for row in indicators_frame.select(["indicator", "measure"]).iter_rows(named=True)
            },
            directions={
                row["indicator"]: row["direction"]
                for row in indicators_frame.select(["indicator", "direction"]).iter_rows(named=True)
            },
            events=run.events,
            elite_loans=float((run.events["event_type"] == "ELITE_LOAN").sum()),
            bands_at_end=_bands_at_end(run.events),
        )
        robustness = evaluate((reading,), protocol=protocol, ensemble=ensemble, members=members)
        scores[run.facts.run_id] = {
            "arm": run.arm.label,
            "outcomes": {
                name: value.model_dump(mode="json") for name, value in vector.values.items()
            },
            "refused_outcomes": list(vector.refused()),
            "breakdown_shares": robustness.breakdown_shares[run.facts.run_id],
            "crossed_count_share": robustness.crossed_count_share,
            "criteria": [
                {
                    "criterion": share.criterion,
                    "holds": share.holds,
                    "changes": share.changes,
                    "undetermined": share.undetermined,
                }
                for share in robustness.criteria
                if share.breakdown_line == robustness.breakdown_lines[0]
            ],
        }
    return scores


def _bands_at_end(events: pl.DataFrame) -> float:
    from late_ming_lab.analysis.military import military_totals

    return float(military_totals(events).get("bands_end", 0.0))
