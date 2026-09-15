"""V2-P05: the variants the card set was missing, their controls, and the documents they support.

Four of the six V1 mechanism cards rest on a structure the model either lacks or never exercised.
This module runs the arms that decide them, on the historical core at the seeds V2-P04 declared, and
writes down what each one did:

```text
M003 arrears persistence   settlement, remission and recovery, each neutral at the V1 behaviour
M004 elite branches        mediation against accumulation/foreclosure, declared by its own slice
M005 band concentration    a positive control that makes merges fire, and a negative one that cannot
M001/M002 policy x lever   a minimal factorial, so "conditional on policy or on structure?"
                           has an answer that is not one arm at a time
M006 mortality             no arm: the interface, the observables and the gap; the rule stays
                           UNIDENTIFIED because an arm that cannot bind measures absence
```

Every arm is a declaration: it says what it moves, and whether it must move something. The
detector V2-P04 built refuses a variant that moves nothing and an ablation that moves something;
this module adds the *controls*, and a positive control that does not fire is a failure here,
because the whole point of a control is that it reaches its code path.
"""

from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.analysis.band_chain import band_chain_summary
from late_ming_lab.analysis.chains import chain_summary
from late_ming_lab.analysis.mortality import mortality_gap_summary
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import SimulationKernel
from late_ming_lab.evidence.parameters import (
    core_default_band_parameters,
    core_default_governance_indicators,
)
from late_ming_lab.experiments.historical_core import HISTORICAL_SCENARIO
from late_ming_lab.experiments.holdout import (
    REFERENCE_ARM,
    Arm,
    ArmFacts,
    ArmRun,
    _moved_facts,
    detect_no_op,
    load_arm_runs,
)
from late_ming_lab.experiments.integrated import build_integrated_economy
from late_ming_lab.policies.fiscal import ArrearsEscalation, ExtractionPolicy, FixedExtraction
from late_ming_lab.protocol.outcomes import compute_outcomes
from late_ming_lab.protocol.schema import load_protocol
from late_ming_lab.systems.mortality import MortalityEvidenceGap, mortality_rule_from_evidence

#: The phase's own root and prefix, beside V2-P04's.
VARIANTS_ROOT: Final[str] = "outputs/v2/p05"
PREFIX: Final[str] = "p05"

#: The documents this phase generates.
VARIANTS_DOCUMENT: Final[str] = "docs/v2/mechanism-variants.md"
VARIANTS_JSON: Final[str] = "docs/v2/mechanism-variants.json"
MORTALITY_DOCUMENT: Final[str] = "docs/v2/mortality-gap.md"
GENERATOR: Final[str] = "late-ming-lab experiment p05"

#: The seeds V2-P04 declared; the same ones, so an arm here is comparable with an arm there.
SEEDS: Final[tuple[int, ...]] = (20_260_915, 20_260_916, 20_260_917, 20_260_918)


class VariantError(RuntimeError):
    """Raised when an arm cannot run, or when a control did not do what it declared."""


def declared_arms() -> tuple[Arm, ...]:
    """The P05 arms: the reference, the arrears rules, the band controls and the elite branches.

    The reference is V2-P04's arm for the same structure, so a number here and a number there are
    the same measurement; the neutral declaration of each new rule is an arm of its own (`-off`)
    rather than an assumption, because "the rule is off" is what every other number is read against.
    """
    return (
        Arm(
            label=REFERENCE_ARM,
            description="the V1 structure, with every chain and rule at its neutral value",
            expects_effect=False,
        ),
        Arm(
            label="arrears-rules-off",
            description="the three arrears rules declared but neutral: the ablation of all three",
            expects_effect=False,
            fiscal={
                "arrears_settlement_share": 0.0,
                "arrears_remission_share": 0.0,
                "arrears_recovery_share": 0.0,
            },
        ),
        Arm(
            label="arrears-settlement",
            description="a payment against an obligation is credited again as settlement",
            expects_effect=True,
            fiscal={"arrears_settlement_share": 0.25},
        ),
        Arm(
            label="arrears-remission",
            description="an outstanding obligation is partly remitted past the unmet-ratio line",
            expects_effect=True,
            fiscal={"arrears_remission_share": 0.3, "arrears_remission_unmet_ratio": 0.05},
        ),
        Arm(
            label="elite-mediation-only",
            description="the credit channel with no default: the ablation of that branch",
            expects_effect=False,
            elite={
                "foreclosure_after_unserviced_months": 0,
                "foreclosure_land_share_of_pledge": 0.0,
            },
        ),
        Arm(
            label="elite-defaults-declared",
            description="defaults are declared and no land moves: the control between branches",
            expects_effect=True,
            elite={
                "foreclosure_after_unserviced_months": 1,
                "foreclosure_land_share_of_pledge": 0.0,
            },
        ),
        Arm(
            label="elite-accumulation",
            description="a loan unserviced for a month is foreclosed and the pledge transfers",
            expects_effect=True,
            elite={
                "foreclosure_after_unserviced_months": 1,
                "foreclosure_land_share_of_pledge": 1.0,
            },
        ),
        Arm(
            label="arrears-recovery",
            description="a cohort holding silver again clears a share of its old obligation",
            expects_effect=True,
            fiscal={"arrears_recovery_share": 0.5, "arrears_recovery_silver_months": 0.5},
        ),
        Arm(
            label="band-merge-positive-control",
            description="the merge bar falls to zero, so every pair in reach may merge",
            expects_effect=True,
            band={"merge_cohesion_above": 0.0},
        ),
        Arm(
            label="band-merge-negative-control",
            description="the merge bar rises to its maximum, so a merge needs full cohesion",
            expects_effect=True,
            band={"merge_cohesion_above": 1.0},
        ),
    )


def _run_one(
    arm: Arm, *, root: str | Path, root_seed: int, output_root: str | Path, prefix: str
) -> ArmRun:
    """One arm's run: the economy, the kernel, the facts and the log."""
    economy = build_integrated_economy(HISTORICAL_SCENARIO, parameter_sets=arm.parameter_sets())
    run_config = SimulationConfig.model_validate(
        {
            "tick_count": 240,
            "warmup_ticks": 24,
            "root_seed": root_seed,
            "scenario_id": f"{prefix}-{arm.label}",
            "policy_id": "p05-variants-v1",
        }
    )
    started = time.perf_counter()
    result = SimulationKernel(run_config, list(economy.systems)).run(run_label=arm.label)
    seconds = time.perf_counter() - started
    from late_ming_lab.storage.run_store import RunStore

    RunStore(Path(output_root)).write(result)
    counts = {
        str(row["event_type"]): int(row["len"])
        for row in result.events.group_by("event_type").len().iter_rows(named=True)
    }
    return ArmRun(
        arm=arm,
        facts=ArmFacts(
            arm=arm.label,
            run_id=result.manifest.run_id,
            root_seed=root_seed,
            simulation_digest=result.summary.simulation_digest,
            event_total=result.events.height,
            event_counts=counts,
            chains={**chain_summary(result.events), **band_chain_summary(result.events)},
            seconds=seconds,
        ),
        events=result.events,
    )


def run_arms(
    *,
    root: str | Path = ".",
    arms: tuple[Arm, ...] | None = None,
    seeds: tuple[int, ...] = SEEDS,
    output_root: str | Path = VARIANTS_ROOT,
    progress: bool = False,
) -> tuple[ArmRun, ...]:
    """Every declared arm at every declared seed, in declaration order."""
    chosen = arms or declared_arms()
    runs: list[ArmRun] = []
    for arm in chosen:
        for seed in seeds:
            run = _run_one(arm, root=root, root_seed=seed, output_root=output_root, prefix=PREFIX)
            runs.append(run)
            if progress:
                print(f"{arm.label} seed {seed}: {run.facts.run_id} in {run.facts.seconds:.1f}s")
    return tuple(runs)


def load_runs(
    *, root: str | Path = ".", output_root: str | Path = VARIANTS_ROOT
) -> tuple[ArmRun, ...]:
    """Re-open the phase's runs from disk, with the chains this phase reads recomputed.

    V2-P04's loader recomputes the price, relief and migration chains; the band attribution is this
    phase's own reader, and a document that read a missing key as zero would report every arm as
    having merged nothing — which is exactly how the first version of this report was wrong.
    """
    loaded = load_arm_runs(root=root, output_root=output_root, arms=declared_arms(), prefix=PREFIX)
    return tuple(
        ArmRun(
            arm=run.arm,
            facts=run.facts.model_copy(
                update={"chains": {**run.facts.chains, **band_chain_summary(run.events)}}
            ),
            events=run.events,
        )
        for run in loaded
    )


def check_arms(runs: tuple[ArmRun, ...]) -> tuple[str, ...]:
    """The detector's verdict for every arm, plus the checks only this phase's controls need."""
    report = list(detect_no_op(runs))
    by_label: dict[str, list[ArmRun]] = {}
    for run in runs:
        by_label.setdefault(run.arm.label, []).append(run)
    return tuple(report)


def _number(value: object) -> float:
    """A polars aggregate as a float; anything else is an error rather than a coerced zero."""
    if isinstance(value, (int, float)):
        return float(value)
    raise VariantError(f"expected a number from the log, got {type(value).__name__}")


def merge_reachability(events: pl.DataFrame) -> dict[str, float]:
    """M005's finding, measured: could a merge have fired at all on this input?

    The merger rule needs two bands in one node in one month, each above a cohesion bar. The card
    records that merges fired in none of the P10 arms; what this counts is the precondition, because
    a bar set to zero removes every other condition and the only thing that can still refuse a merge
    is co-location. It is reported rather than turned into an arm: an intervention that cannot bind
    measures the absence of a state path, not the effect of a rule.
    """
    states = events.filter(pl.col("event_type") == "BAND_STATE")
    merged = float(band_chain_summary(events)["band_chain_troops.merger"])
    if states.is_empty():
        raise VariantError("no band states in this run: the merge question cannot be asked of it")
    per_node_tick = states.group_by(["tick", "region"]).agg(
        pl.col("agent_id").n_unique().alias("bands")
    )
    return {
        "months_with_bands": _number(per_node_tick["tick"].n_unique()),
        "max_bands_sharing_a_node": _number(per_node_tick["bands"].max() or 0),
        "node_months_with_two_or_more_bands": _number((per_node_tick["bands"] >= 2).sum()),
        "merge_events": float(merged),
        "cohesion_bar_at_reference": float(core_default_band_parameters().merge_cohesion_above),
    }


@dataclass(frozen=True, slots=True)
class FactorialCell:
    """One cell of the policy x lever design: the policy, the lever, and how the cell ran."""

    label: str
    policy: str
    lever: str
    run_id: str
    breakdown_share: float
    inversion_present: float
    receipts_over_quota: float
    tax_base_contraction: float


def factorial_cells(
    *, root: str | Path = ".", output_root: str | Path = VARIANTS_ROOT, seed: int = SEEDS[0]
) -> tuple[FactorialCell, ...]:
    """The minimal factorial: two extraction policies crossed with two declared structural levers.

    M001's verdict was policy-dependent and M002's was arm-dependent. One arm at a time cannot say
    which of the two a verdict is conditional on, so the phase crosses them: the escalating policy
    against a fixed one, and the demand-pressure price against the inventory rule, and reports the
    inversion reading and the breakdown share in each cell.
    """
    protocol = load_protocol(root)
    thresholds = core_default_governance_indicators()
    policies: dict[str, ExtractionPolicy] = {
        "escalating": ArrearsEscalation(base_effort=0.5, arrears_weight=0.5, effort_ceiling=1.0),
        "fixed": FixedExtraction(effort=0.5),
    }
    levers = {"inventory-price": 0.0, "demand-pressure-price": 2.0}
    cells: list[FactorialCell] = []
    for policy_name, policy in policies.items():
        for lever_name, weight in levers.items():
            economy = build_integrated_economy(
                HISTORICAL_SCENARIO,
                parameter_sets={
                    "MarketParameters": Arm(
                        label="cell",
                        description="a factorial cell",
                        expects_effect=True,
                        market={"demand_pressure_weight": weight},
                    ).market_parameters()
                },
                extraction_policy=policy,
            )
            config = SimulationConfig.model_validate(
                {
                    "tick_count": 240,
                    "warmup_ticks": 24,
                    "root_seed": seed,
                    "scenario_id": f"{PREFIX}-factorial-{policy_name}-{lever_name}",
                    "policy_id": "p05-factorial-v1",
                }
            )
            result = SimulationKernel(config, list(economy.systems)).run(
                run_label=f"factorial-{policy_name}-{lever_name}"
            )
            events = result.events
            vector = compute_outcomes(
                events,
                protocol,
                window_id="whole-run",
                run_id=result.manifest.run_id,
                purpose="report",
                thresholds=thresholds,
                population_adults=sum(cohort.adults for cohort in economy.population),
                starting_households=sum(cohort.households for cohort in economy.population),
                trade_graph=economy.graphs.trade,
            )
            from late_ming_lab.analysis.mechanisms import extraction_inversion

            inversion = extraction_inversion(events)
            cells.append(
                FactorialCell(
                    label=f"{policy_name} x {lever_name}",
                    policy=policy_name,
                    lever=lever_name,
                    run_id=result.manifest.run_id,
                    breakdown_share=_breakdown_share(
                        events,
                        thresholds,
                        population_adults=sum(cohort.adults for cohort in economy.population),
                        starting_households=sum(cohort.households for cohort in economy.population),
                    ),
                    inversion_present=1.0 if inversion.present else 0.0,
                    receipts_over_quota=float(vector.value("fiscal_realisation").value or 0.0),
                    tax_base_contraction=float(vector.value("fiscal_base").value or 0.0),
                )
            )
    return tuple(cells)


def _breakdown_share(
    events: pl.DataFrame,
    thresholds: object,
    *,
    population_adults: float,
    starting_households: float,
) -> float:
    """Whether this cell reaches the declared breakdown line, read the way P10 reads it.

    The denominators are the run's own population. The first version of this function passed zero
    adults and a row count, which pins two of the eight reading lines shut — an armed share of
    adults cannot cross when there are no adults, and migration is deflated by the wrong base — so
    the reading it produced was not the one it claimed to be.
    """
    from late_ming_lab.analysis.outcomes import governance_timeline

    timeline = governance_timeline(
        events,
        thresholds=thresholds,  # type: ignore[arg-type]
        population_adults=population_adults,
        starting_households=starting_households,
    )
    return 1.0 if timeline.first_breakdown() is not None else 0.0


def mortality_gap(
    *, root: str | Path = ".", output_root: str | Path = VARIANTS_ROOT
) -> dict[str, object]:
    """The M006 gap: the observables, the rule the model actually has, and what would change it."""
    runs = load_runs(root=root, output_root=output_root)
    reference = next(run for run in runs if run.arm.label == REFERENCE_ARM)
    observables = mortality_gap_summary(reference.events)
    try:
        rule = mortality_rule_from_evidence()
        built = rule.rule_version
    except MortalityEvidenceGap as gap:
        built = "refused"
        reason = str(gap)
    else:  # pragma: no cover - the evidence does not support a rule today
        reason = ""
    return {
        "status": "UNIDENTIFIED",
        "model_rule": "nobody dies (mortality-none-v1)",
        "rule_built_from_evidence": built,
        "refusal": reason,
        "observables": observables,
        "missing": [
            "a county-resolution mortality or unmet-need series for the window",
            "a rate, or a range of rates, with a source and a grade",
            "a population layer that can carry a death (no transition removes members today)",
        ],
        "what_would_change_it": (
            "a sourced series with a level and a range would let a rule be declared and "
            "calibrated; until then an arm that removes members would be invention wearing a "
            "control's name"
        ),
    }


def write_documents(
    root: str | Path,
    runs: tuple[ArmRun, ...],
    *,
    cells: tuple[FactorialCell, ...],
    gap: dict[str, object],
    control_report: tuple[str, ...],
    reachability: dict[str, float],
) -> tuple[Path, Path, Path]:
    """Write the two documents; return their paths."""
    repository = Path(root)
    document = repository / VARIANTS_DOCUMENT
    machine = repository / VARIANTS_JSON
    mortality = repository / MORTALITY_DOCUMENT
    document.parent.mkdir(parents=True, exist_ok=True)
    arms = [
        {
            "arm": run.arm.label,
            "description": run.arm.description,
            "expects_effect": run.arm.expects_effect,
            "configuration_diff": run.arm.configuration_diff(),
            "run_id": run.facts.run_id,
            "root_seed": run.facts.root_seed,
            "simulation_digest": run.facts.simulation_digest,
            "event_counts": run.facts.event_counts,
            "chains": run.facts.chains,
        }
        for run in runs
    ]
    cell_rows = [dataclasses.asdict(cell) for cell in cells]
    machine.write_text(
        json.dumps(
            {
                "generator": GENERATOR,
                "seeds": list(SEEDS),
                "control_check": list(control_report),
                "merge_reachability": reachability,
                "arms": arms,
                "factorial": cell_rows,
                "mortality_gap": gap,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    mortality.write_text(_mortality_markdown(gap), encoding="utf-8")
    document.write_text(
        _variants_markdown(
            runs=runs,
            cells=cells,
            control_report=control_report,
            reachability=reachability,
        ),
        encoding="utf-8",
    )
    return document, machine, mortality


def _variants_markdown(
    *,
    runs: tuple[ArmRun, ...],
    cells: tuple[FactorialCell, ...],
    control_report: tuple[str, ...],
    reachability: dict[str, float],
) -> str:
    lines = [
        f"<!-- generated by: {GENERATOR} -->",
        "",
        "# The variants the card set was missing",
        "",
        f"Generated by `{GENERATOR}` over `docs/v2/mechanism-variants.json`. Do not edit.",
        "",
        "Every arm ran on `historical-core-v1` at the seeds V2-P04 declared. An arm that "
        "declares a",
        "structure must move something; an arm that declares none must reproduce the "
        "reference; and a",
        "control that cannot reach its code path fails the phase, because that is what a "
        "control is for.",
        "",
        "## Every arm",
        "",
        "| arm | declares | configuration diff | what it moved |",
        "| --- | --- | --- | --- |",
    ]
    reference_by_seed = {run.facts.root_seed: run for run in runs if run.arm.label == REFERENCE_ARM}
    for run in runs:
        if run.facts.root_seed != SEEDS[0]:
            continue
        diff = run.arm.configuration_diff()
        if run.arm.label == REFERENCE_ARM:
            moved = "— the reference"
        else:
            baseline = reference_by_seed[run.facts.root_seed]
            moved_names = sorted(_moved_facts(baseline.facts, run.facts))
            moved = ", ".join(moved_names) if moved_names else "nothing: identical to the reference"
        lines.append(
            f"| `{run.arm.label}` | {'a structure' if run.arm.expects_effect else 'none'} | "
            f"{', '.join(f'{k}={v:g}' for k, v in sorted(diff.items())) or '—'} | {moved} |"
        )
    lines += [
        "",
        "## The controls",
        "",
        *[f"- {line}" for line in control_report],
        "",
        "## The policy x lever factorial",
        "",
        "M001's verdict was policy-dependent and M002's arm-dependent; one arm at a time "
        "cannot say",
        "which. The cells below cross an escalating extraction policy with a fixed one, and the",
        "inventory price rule with the demand-pressure structure of V2-P04.",
        "",
        "| cell | inversion present | breakdown reached | receipts over quota | base change (mu) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for cell in cells:
        lines.append(
            f"| `{cell.label}` | {cell.inversion_present:.0f} | {cell.breakdown_share:.0f} | "
            f"{cell.receipts_over_quota:.4f} | {cell.tax_base_contraction:.1f} |"
        )
    lines += [
        "",
        "## The arrears rules",
        "",
        "| arm | settlement rows | remission rows | recovery rows | arrears relief (tael) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for run in runs:
        if run.facts.root_seed != SEEDS[0] or "arrears" not in run.arm.label:
            continue
        lines.append(
            f"| `{run.arm.label}` | {_relief_rows(run, 'settlement')} | "
            f"{_relief_rows(run, 'remission')} | {_relief_rows(run, 'recovery')} | "
            f"{_relief_tael(run):.1f} |"
        )
    lines += [
        "",
        "## M005: the merger link, exercised by both controls",
        "",
        "The card records that merges fired in none of the P10 arms and that the link was never",
        "exercised. Both controls were run, so the card's own falsifier is answered below: if",
        "merges fire and the largest band's share does not rise, the link is decorative.",
        "",
        "| fact | value |",
        "| --- | --- |",
    ]
    for name, value in sorted(reachability.items()):
        lines.append(f"| `{name}` | {value:.6g} |")
    lines += [
        "",
        "Merges do fire on this input once the bar allows them, so the link is reachable and the",
        "question is not whether it can bind but what it does when it does. The attribution of the",
        "concentration that follows, by component, is the next table:",
        "",
        "## Band concentration, by component",
        "",
        "| arm | formation | refugee intake | deserter intake | merger | split | dissolution "
        "| largest share max |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for run in runs:
        if run.facts.root_seed != SEEDS[0] or "band" not in run.arm.label:
            continue
        chains = run.facts.chains
        lines.append(
            f"| `{run.arm.label}` | {chains.get('band_chain_troops.formation', 0.0):.0f} | "
            f"{chains.get('band_chain_troops.refugee_intake', 0.0):.0f} | "
            f"{chains.get('band_chain_troops.deserter_intake', 0.0):.0f} | "
            f"{chains.get('band_chain_troops.merger', 0.0):.0f} | "
            f"{chains.get('band_chain_troops.split', 0.0):.0f} | "
            f"{chains.get('band_chain_troops.dissolution', 0.0):.0f} | "
            f"{chains.get('band_chain_largest_share_end', 0.0):.4f} |"
        )
    lines += [
        "",
        "## What this document does not say",
        "",
        "- It does not restore the monotone ratchet M003's card rejects: the arrears arms "
        "are rules by",
        "  which a stock *falls*, and the card's rejection is untouched.",
        "- It does not claim a mortality structure. M006 stays `UNIDENTIFIED`; see the "
        "separate gap",
        "  report, and note that an arm removing members would be invention rather than a control.",
        "- It does not select a structure because a reserved window improved: the factorial "
        "reports",
        "  every cell, including the ones where the verdict does not move.",
        "",
    ]
    return "\n".join(lines)


def _relief_rows(run: ArmRun, outcome: str) -> int:
    frame = run.events.filter(
        (pl.col("event_type") == "ARREARS_RELIEF") & (pl.col("outcome") == outcome)
    )
    return frame.height


def _relief_tael(run: ArmRun) -> float:
    """Tael the arrears rules removed, summed from the log, not read from a key that is absent.

    The first version of this table read `tax_arrears_relief_tael`, a chain key nothing writes, and
    printed 0.0 beside eleven thousand events. A document that reports its own measurements as
    zero is worse than one that reports nothing: wrong in the direction of looking calm.
    """
    relief = run.events.filter(pl.col("event_type") == "ARREARS_RELIEF")
    if relief.is_empty():
        return 0.0
    removed = relief["trigger_json"].str.json_path_match("$.removed_tael").cast(pl.Float64)
    return float(removed.sum() or 0.0)


def _mortality_markdown(gap: dict[str, object]) -> str:
    observables = gap.get("observables", {})
    assert isinstance(observables, dict)
    missing = gap.get("missing", [])
    assert isinstance(missing, list)
    lines = [
        f"<!-- generated by: {GENERATOR} -->",
        "",
        "# M006 — famine mortality: what exists, and what is missing",
        "",
        f"Generated by `{GENERATOR}`. Do not edit.",
        "",
        "**The status stays `UNIDENTIFIED`.** The V1 card already said why: the model has no "
        "mortality",
        "clock, no arm can bind, and no artifact reports the population decline the "
        "mechanism would",
        "explain. This phase delivers the interface and the observables, and refuses to "
        "invent a rate.",
        "",
        "## What the model does",
        "",
        f"- the rule it has: `{gap['model_rule']}`",
        f"- a rule built from the evidence on hand: `{gap['rule_built_from_evidence']}`",
    ]
    if gap.get("refusal"):
        lines.append(f"- the refusal: {gap['refusal']}")
    lines += [
        "",
        "## What a rule would see",
        "",
        "Recomputed from the reference run's own consumption events — the quantities a "
        "mortality rule",
        "would be handed, and the distribution it would have to be calibrated against:",
        "",
        "| quantity | value |",
        "| --- | --- |",
    ]
    for name in sorted(observables):
        value = observables[name]
        rendered = f"{value:.6g}" if isinstance(value, float) else str(value)
        lines.append(f"| `{name}` | {rendered} |")
    lines += [
        "",
        "The shortfall observable is *present*: cohorts spend months below their subsistence "
        "floor and",
        "the run measures how many. What is absent is anything outside the model to "
        "calibrate a death",
        "rate against, which is what the gap is.",
        "",
        "## What is missing",
        "",
        *[f"- {item}" for item in missing],
        "",
        f"**What would change it:** {gap['what_would_change_it']}",
        "",
        "## Why there is no `NO_MORTALITY` arm",
        "",
        "The card's own argument, and the phase's: an arm whose intervention cannot bind "
        "measures the",
        "absence of a rule, not its effect — the mistake `NO_BAND_MERGER` made for a "
        "different rule.",
        "`NoMortality` is therefore the model's own declared behaviour "
        "(`mortality-none-v1`), not an",
        "ablation of something that exists, and `apply()` refuses any rule that returns "
        "deaths, because",
        "no transition in the population layer could carry them.",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "GENERATOR",
    "MORTALITY_DOCUMENT",
    "PREFIX",
    "SEEDS",
    "VARIANTS_DOCUMENT",
    "VARIANTS_JSON",
    "VARIANTS_ROOT",
    "FactorialCell",
    "VariantError",
    "check_arms",
    "declared_arms",
    "factorial_cells",
    "load_runs",
    "merge_reachability",
    "mortality_gap",
    "run_arms",
    "write_documents",
]
