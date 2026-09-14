"""The P11 smoke scenario: a short run with a few institutional seats and one decision layer.

This is deliberately tiny. Its job is to show the runtime boundary working end to end — a seat is
occupied, an event triggers a decision, a bounded action reaches a declared lever, and the trace
records the model, the prompt hash and the answer hash — not to produce a historical result. The
phase report says the same thing in the same words.

```bash
uv run python -c "from late_ming_lab.experiments.institutional_smoke import run_smoke; \\
    print(run_smoke('.', policy='rule').traces)"
```

Three ways to run it, and the difference between them is the point:

- ``policy="rule"`` — a declared threshold policy, offline and deterministic. This is the fallback
  the boundary allows, and it is what runs when the runtime model is not available; ``"utility"``
  and ``"random"`` are the other two declared policies P12 compares it against.
- ``policy="replay"`` — the same layer driven by recorded fixtures: the model id, prompts and
  answers come from `tests/fixtures/llm/`, so a recorded live decision replays with no network.
- ``policy="ustc"`` — the live runtime model. It fails closed unless ``USTC_LLM_MODEL`` is the
  operator-confirmed id and ``USTC_LLM_ENABLED=1``; there is no fallback to another model.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.analysis.outcomes import outcome_scalars
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import SimulationKernel
from late_ming_lab.core.tick import System
from late_ming_lab.evidence.parameters import core_default_governance_indicators
from late_ming_lab.evidence.provenance import git_provenance
from late_ming_lab.experiments.assembly import Economy
from late_ming_lab.experiments.integrated import build_integrated_economy
from late_ming_lab.experiments.interventions import (
    ArmConfiguration,
    baseline_configuration,
    configuration_hash,
)
from late_ming_lab.policies.base import (
    ActorRole,
    ChatTransport,
    InstitutionalPolicy,
)
from late_ming_lab.policies.institutional import (
    ActorSeat,
    InstitutionalDecisionSystem,
    InstitutionalLevers,
)
from late_ming_lab.policies.random_policy import RandomPolicy
from late_ming_lab.policies.rules import RulePolicy
from late_ming_lab.policies.ustc_v41 import policy_from_environment
from late_ming_lab.policies.utility import UtilityPolicy
from late_ming_lab.systems.fiscal import OfficialReliefSystem, TaxCollectionSystem
from late_ming_lab.systems.markets import MarketClearingSystem

#: The smoke window: a third of the real run, enough for the seats to see arrears, a shortfall, a
#: distress line and armed concentration move past their declared lines.
SMOKE_TICK_COUNT: Final[int] = 96
SMOKE_WARMUP_TICKS: Final[int] = 12

#: Where a smoke run writes its trace. Under the run store's tree, beside the batches it belongs to.
OUTPUT_ROOT: Final[str] = "outputs/institutional"
TRACE_FILE: Final[str] = "decision_trace.parquet"
MANIFEST_FILE: Final[str] = "manifest.json"

#: The seats the plan allows, and no others: the centre, one province, two counties, one band.
SEAT_ROLES: Final[tuple[tuple[str, ActorRole], ...]] = (
    ("GOV-F1", ActorRole.CENTRAL_FISCAL),
    ("GOV-P1", ActorRole.PROVINCIAL),
    ("GOV-L1", ActorRole.COUNTY),
    ("GOV-L2", ActorRole.COUNTY),
    ("BAND-1", ActorRole.ARMED_GROUP),
)


class SmokeError(RuntimeError):
    """Raised when the smoke scenario cannot be built as declared."""


@dataclass(frozen=True, slots=True)
class InstitutionalRun:
    """One run with the decision layer armed: the log, the decisions and the refusals."""

    policy: str
    policy_name: str
    run_id: str
    events: pl.DataFrame
    traces: pl.DataFrame
    refusals: pl.DataFrame
    seats: tuple[ActorSeat, ...]
    config_hash: str
    outcomes: dict[str, float]


@dataclass(frozen=True, slots=True)
class SmokeResult:
    """What the smoke run produced: the decisions, the refusals, and where they were written."""

    policy: str
    traces: pl.DataFrame
    refusals: pl.DataFrame
    run_id: str
    directory: Path

    @property
    def decisions(self) -> int:
        return self.traces.height

    @property
    def ticks_covered(self) -> int:
        return SMOKE_TICK_COUNT


def smoke_seats(regions: tuple[str, ...]) -> tuple[ActorSeat, ...]:
    """Occupy the declared seats, with opaque region codes drawn from the counties the run has."""
    if len(regions) < 2:
        raise SmokeError("the smoke scenario needs at least two county regions")
    return tuple(
        ActorSeat(code=code, role=role, region=regions[index % len(regions)])
        for index, (code, role) in enumerate(SEAT_ROLES)
    )


def build_policy(
    name: str,
    *,
    transport: ChatTransport | None = None,
    seed: int = 20_260_915,
    settings: object | None = None,
) -> InstitutionalPolicy:
    """The policy the smoke run is asked for, refused loudly when it is not available.

    ``settings`` lets a caller supply declared settings instead of reading the environment: the
    replay path needs that, because a cluster has no credential to read and the gate must stay shut
    there. Without it the settings come from :func:`~late_ming_lab.policies.ustc_v41.load_settings`,
    which is what every other caller wants.
    """
    if name == "rule":
        return RulePolicy()
    if name == "utility":
        return UtilityPolicy()
    if name == "random":
        return RandomPolicy(seed=seed)
    if name == "ustc":
        return policy_from_environment(transport=transport)
    if name == "replay":
        if transport is None:
            raise SmokeError("policy='replay' needs a transport built from the fixture store")
        from late_ming_lab.policies.ustc_v41 import load_settings

        resolved = settings if settings is not None else load_settings()
        return _ustc_with_transport(transport, resolved)
    raise SmokeError(
        f"unknown policy {name!r}; expected 'rule', 'utility', 'random', 'replay' or 'ustc'"
    )


def _ustc_with_transport(transport: ChatTransport, settings: object) -> InstitutionalPolicy:
    """A USTC policy over a substituted transport: the replay path, and the offline tests."""
    from late_ming_lab.policies.ustc_v41 import UstcSettings, USTCV41Policy

    if not isinstance(settings, UstcSettings):
        raise SmokeError("a USTC policy needs validated settings")
    return USTCV41Policy(transport=transport, settings=settings)


def run_institutional(
    *,
    policy: str = "rule",
    transport: ChatTransport | None = None,
    settings: object | None = None,
    config: ArmConfiguration | None = None,
    ticks: int = SMOKE_TICK_COUNT,
    warmup_ticks: int = SMOKE_WARMUP_TICKS,
    seed: int = 20_260_915,
) -> InstitutionalRun:
    """One run with the decision layer armed, without writing anything.

    P12 needs the event log as well as the trace — the mechanisms are read off the log — so the run
    itself lives here and the artifact writing is a caller's business.
    """
    arm = config or baseline_configuration()
    economy = build_integrated_economy(
        arm.scenario,
        disruption=arm.disruption,
        extraction_policy=arm.extraction_policy,
        capacity=arm.capacity,
    )
    tax = _system_of_type(economy.systems, TaxCollectionSystem)
    relief = _system_of_type(economy.systems, OfficialReliefSystem)
    market = _system_of_type(economy.systems, MarketClearingSystem)
    county_nodes = tuple(node.node_id for node in economy.graphs.nodes.counties)
    link = _first_link(economy)
    levers = InstitutionalLevers(
        tax=tax,
        relief=relief,
        market=market,
        base_disruption=arm.disruption,
        blocked_link=link,
        fiscal_parameters=arm.fiscal,
    )
    seats = smoke_seats(county_nodes)
    layer = InstitutionalDecisionSystem(
        seats=seats,
        policy=build_policy(policy, transport=transport, settings=settings, seed=seed),
        fallback=None if policy in {"rule", "random"} else RulePolicy(),
        levers=levers,
        adults=sum(cohort.adults for cohort in economy.population),
        starting_households=sum(cohort.households for cohort in economy.population),
    )
    run_config = SimulationConfig.model_validate(
        {
            "tick_count": ticks,
            "warmup_ticks": warmup_ticks,
            "root_seed": seed,
            "scenario_id": "institutional-smoke",
            "policy_id": f"institutional-{policy}-v1",
        }
    )
    systems = _with_layer(economy.systems, layer)
    result = SimulationKernel(run_config, systems).run(run_label="institutional-smoke")
    traces = pl.DataFrame(layer.decisions) if layer.decisions else _empty_trace()
    refusals_frame = _refusals_frame(layer)
    thresholds = core_default_governance_indicators()
    outcomes = outcome_scalars(
        result.events,
        thresholds=thresholds,
        population_adults=sum(cohort.adults for cohort in economy.population),
        starting_households=sum(cohort.households for cohort in economy.population),
        trade_graph=economy.graphs.trade,
    )
    return InstitutionalRun(
        policy=policy,
        policy_name=layer.policy_name,
        run_id=result.manifest.run_id,
        events=result.events,
        traces=traces,
        refusals=refusals_frame,
        seats=seats,
        config_hash=configuration_hash(arm),
        outcomes=outcomes,
    )


def _refusals_frame(layer: InstitutionalDecisionSystem) -> pl.DataFrame:
    """The refusals as a table; empty when nothing was refused."""
    if not layer.refusals:
        return pl.DataFrame(
            schema={
                "tick": pl.Int64,
                "actor": pl.String,
                "role": pl.String,
                "policy": pl.String,
                "reason": pl.String,
            }
        )
    return pl.DataFrame(
        [
            {
                "tick": refusal.tick,
                "actor": refusal.actor,
                "role": refusal.role,
                "policy": refusal.policy,
                "reason": refusal.reason,
            }
            for refusal in layer.refusals
        ]
    )


def run_smoke(
    root: str | Path,
    *,
    policy: str = "rule",
    transport: ChatTransport | None = None,
    output_dir: str | Path | None = None,
    config: ArmConfiguration | None = None,
    ticks: int = SMOKE_TICK_COUNT,
    warmup_ticks: int = SMOKE_WARMUP_TICKS,
    seed: int = 20_260_915,
) -> SmokeResult:
    """Run the smoke window with the decision layer armed, and write its trace."""
    directory = Path(root)
    arm = config or baseline_configuration()
    run = run_institutional(
        policy=policy,
        transport=transport,
        config=arm,
        ticks=ticks,
        warmup_ticks=warmup_ticks,
        seed=seed,
    )
    target = Path(output_dir) if output_dir is not None else directory / OUTPUT_ROOT
    run_dir = target / run.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run.traces.write_parquet(run_dir / TRACE_FILE)
    provenance = git_provenance(directory)
    (run_dir / MANIFEST_FILE).write_text(
        json.dumps(
            {
                "schema_version": "institutional-smoke-v1",
                "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                "git_sha": provenance.git_sha,
                "git_dirty": provenance.git_dirty,
                "policy": policy,
                "policy_name": run.policy_name,
                "ticks": ticks,
                "warmup_ticks": warmup_ticks,
                "seed": seed,
                "seats": [
                    {"code": seat.code, "role": seat.role.value, "region": seat.region}
                    for seat in run.seats
                ],
                "arm_configuration_hash": run.config_hash,
                "decisions": run.traces.height,
                "refusals": run.refusals.height,
                "decision_events_in_log": int(
                    run.events.filter(pl.col("event_type") == "INSTITUTIONAL_DECISION").height
                ),
                "note": (
                    "a smoke scenario: a handful of seats, event-triggered decisions, and a trace "
                    "that records the model, the prompt hash and the answer hash of each one"
                ),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return SmokeResult(
        policy=policy,
        traces=run.traces,
        refusals=run.refusals,
        run_id=run.run_id,
        directory=run_dir,
    )


def _with_layer(systems: Sequence[System], layer: System) -> list[System]:
    """Place the decision layer where its declared phase puts it.

    The scheduler refuses a system whose registration order contradicts the versioned tick order, so
    the layer is merged in by phase rather than appended: it belongs after military finance and
    before bookkeeping, which is the slot P01 declared for institutional decisions.
    """
    return sorted([*systems, layer], key=lambda system: int(system.phase))


def _system_of_type[T](systems: Sequence[object], kind: type[T]) -> T:
    """The one system of a kind the economy wired, or a refusal: the layer needs a real lever."""
    for system in systems:
        if isinstance(system, kind):
            return system
    raise SmokeError(f"the economy has no {kind.__name__}")


def _first_link(economy: Economy) -> tuple[str, str] | None:
    """One declared trade edge, as the link a band leadership may close."""
    for origin, destination in sorted(economy.graphs.trade.edges):
        return (str(origin), str(destination))
    return None


def _empty_trace() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "tick": pl.Int64,
            "actor": pl.String,
            "role": pl.String,
            "region": pl.String,
            "policy": pl.String,
            "model_id": pl.String,
            "prompt_hash": pl.String,
            "response_hash": pl.String,
            "action": pl.String,
            "intensity": pl.Float64,
            "priority": pl.String,
            "rationale": pl.String,
            "outcome": pl.String,
            "trigger": pl.String,
            "levers": pl.String,
            "latency_ms": pl.Float64,
        }
    )
