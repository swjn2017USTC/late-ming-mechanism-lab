"""The protocol's evaluation set: runs whose event logs are kept, so a line can be moved later.

The threshold ensemble is only worth reporting if the same run can be re-scored under a different
set of lines. That needs the run's *measurements*, not its verdicts, and the measurements live in
the event log. An artifact that stores only "crossed 5 of 8" cannot answer "what if the line
were 0.35 instead of 0.30", and no amount of care at report time recovers it.

So this module runs a declared, small set of arms and writes each run's log through the ordinary
`RunStore`, then publishes two things per run:

```text
measures      the eight governance measures, which no threshold can change
readings      the three mechanism readings, which read no threshold at all
events        the log itself, so per-node and per-month series stay re-derivable
```

This is a protocol pilot, not a V2 result: it fits nothing, it calibrates nothing, and its purpose
is to exercise the frozen protocol end to end and give the ensemble something real to move.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import networkx as nx
import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from late_ming_lab.analysis.governance import governance_indicators
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.kernel import SimulationKernel
from late_ming_lab.evidence.parameters import (
    GovernanceIndicatorParameters,
    core_default_governance_indicators,
)
from late_ming_lab.experiments.integrated import build_integrated_economy
from late_ming_lab.experiments.interventions import arm_configuration
from late_ming_lab.experiments.runner import RUN_TICK_COUNT, RUN_WARMUP_TICKS, arm_parameter_sets
from late_ming_lab.protocol.freeze import ProtocolFreeze, stamp_batch
from late_ming_lab.protocol.measures import protocol_measurements
from late_ming_lab.protocol.schema import ValidationProtocol
from late_ming_lab.storage.run_store import RunStore

#: The pilot's default arms: the declared baseline, the arm that opens the migration gate, and the
#: arm that removes elite credit. Each is the contrast one declared criterion needs — the gate for
#: M002, the removed credit for M004 — so the robustness report has something to read for them.
PILOT_ARMS: Final[tuple[str, ...]] = ("BASELINE", "OPEN_MIGRATION_EXIT", "NO_ELITE_CREDIT")

#: The pilot's default replicate count. Four is the smallest number for which "in every replicate"
#: is a statement with any content; it is not an uncertainty estimate and is not reported as one.
PILOT_REPLICATES: Final[int] = 4

#: The pilot's base seed, declared here so a report can name the runs it read.
PILOT_BASE_SEED: Final[int] = 20_260_915

#: The file a pilot run carries the protocol identity in. A run directory is written by `RunStore`,
#: which knows the model's provenance and not the protocol's; the stamp is what makes "this run was
#: scored under these rules" checkable later, and `report.load_pilot_runs` refuses a run without it.
PROTOCOL_STAMP_FILE: Final[str] = "validation-protocol.json"


class EvaluationError(RuntimeError):
    """Raised when a pilot run cannot be built at all."""


class RunMeasures(BaseModel):
    """One run's threshold-free measurements and the identity of the run that produced them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    arm: str
    root_seed: int
    policy_id: str
    simulation_digest: str
    indicators: dict[str, float] = Field(
        default_factory=dict,
        description="indicator id -> measure; the numbers a threshold is applied to",
    )
    directions: dict[str, str] = Field(default_factory=dict)
    measurements: dict[str, float] = Field(
        default_factory=dict, description="the protocol's own measures for this run"
    )


@dataclass(frozen=True, slots=True)
class PilotRun:
    """A run, its log, and the frames the protocol needs to measure it."""

    measures: RunMeasures
    events: pl.DataFrame
    population_adults: float
    starting_households: float
    trade_graph: nx.Graph[str]
    thresholds: GovernanceIndicatorParameters
    directory: Path | None


def run_pilot_arm(
    *,
    arm: str,
    root_seed: int,
    root: str | Path = ".",
    output_root: str | Path | None = None,
    protocol: ValidationProtocol | None = None,
    ticks: int = RUN_TICK_COUNT,
    warmup_ticks: int = RUN_WARMUP_TICKS,
) -> PilotRun:
    """Build one declared arm, run the window, and keep everything a later re-scoring needs."""
    try:
        configuration = arm_configuration(arm)
    except KeyError as error:
        raise EvaluationError(f"unknown arm {arm!r}") from error
    economy = build_integrated_economy(
        configuration.scenario,
        parameter_sets=arm_parameter_sets(configuration),
        disruption=configuration.disruption,
        extraction_policy=configuration.extraction_policy,
        capacity=configuration.capacity,
    )
    run_config = SimulationConfig.model_validate(
        {
            "tick_count": ticks,
            "warmup_ticks": warmup_ticks,
            "root_seed": root_seed,
            "scenario_id": _scenario_id(arm),
            "policy_id": "protocol-pilot-v1",
        }
    )
    result = SimulationKernel(run_config, list(economy.systems)).run(run_label=_scenario_id(arm))
    # The governance lines are not part of an arm: they are the reading protocol's own parameters,
    # and the ensemble moves them afterwards. The pilot runs under the live declaration.
    thresholds = core_default_governance_indicators()
    starting_households = sum(cohort.households for cohort in economy.population)
    starting_adults = sum(cohort.adults for cohort in economy.population)
    directory = None
    if output_root is not None:
        directory = RunStore(Path(output_root)).write(result)
        if protocol is not None:
            stamp_run(directory, protocol)
    measures = measures_of(
        events=result.events,
        run_id=result.manifest.run_id,
        simulation_digest=result.summary.simulation_digest,
        policy_id=result.manifest.policy_id,
        arm=arm,
        root_seed=root_seed,
        thresholds=thresholds,
        population_adults=starting_adults,
        starting_households=starting_households,
        trade_graph=economy.graphs.trade,
    )
    return PilotRun(
        measures=measures,
        events=result.events,
        population_adults=starting_adults,
        starting_households=starting_households,
        trade_graph=economy.graphs.trade,
        thresholds=thresholds,
        directory=directory,
    )


def run_protocol_pilot(
    *,
    root: str | Path = ".",
    output_root: str | Path,
    protocol: ValidationProtocol | None = None,
    arms: tuple[str, ...] = PILOT_ARMS,
    replicates: int = PILOT_REPLICATES,
    base_seed: int = PILOT_BASE_SEED,
    ticks: int = RUN_TICK_COUNT,
    warmup_ticks: int = RUN_WARMUP_TICKS,
    progress: bool = False,
) -> tuple[PilotRun, ...]:
    """Run every declared arm at every replicate, in declaration order."""
    runs: list[PilotRun] = []
    for arm in arms:
        for replicate in range(replicates):
            started = time.perf_counter()
            run = run_pilot_arm(
                arm=arm,
                root_seed=base_seed + replicate,
                root=root,
                output_root=output_root,
                protocol=protocol,
                ticks=ticks,
                warmup_ticks=warmup_ticks,
            )
            runs.append(run)
            if progress:
                print(
                    f"{arm} replicate {replicate}: {run.measures.run_id} in "
                    f"{time.perf_counter() - started:.1f}s"
                )
    return tuple(runs)


def measures_of(
    *,
    events: pl.DataFrame,
    run_id: str,
    simulation_digest: str,
    policy_id: str,
    arm: str,
    root_seed: int,
    thresholds: GovernanceIndicatorParameters,
    population_adults: float,
    starting_households: float,
    trade_graph: nx.Graph[str],
) -> RunMeasures:
    """The eight measures, their directions, and the protocol's own measures for one run.

    It takes the log and the identity rather than a kernel result, so a run re-opened from disk is
    measured by exactly the function that measured it when it was produced. A second path for the
    second case would be a second definition of the same measures.
    """
    indicators = governance_indicators(
        events,
        thresholds=thresholds,
        population_adults=population_adults,
        starting_households=starting_households,
    )
    return RunMeasures(
        run_id=run_id,
        arm=arm,
        root_seed=root_seed,
        policy_id=policy_id,
        simulation_digest=simulation_digest,
        indicators={
            row["indicator"]: float(row["measure"])
            for row in indicators.select(["indicator", "measure"]).iter_rows(named=True)
        },
        directions={
            row["indicator"]: row["direction"]
            for row in indicators.select(["indicator", "direction"]).iter_rows(named=True)
        },
        measurements=protocol_measurements(
            events,
            thresholds=thresholds,
            population_adults=population_adults,
            starting_households=starting_households,
            trade_graph=trade_graph,
        ),
    )


def _scenario_id(arm: str) -> str:
    """A run id fragment for an arm: lower case, and the same spelling the batch path uses."""
    return arm.lower().replace("+", "-").replace("_", "-")


def stamp_run(directory: Path, protocol: ValidationProtocol) -> Path:
    """Record the protocol identity beside a run, so a later read can refuse a stale one.

    Public because more than one phase now writes it: a run scored under the frozen protocol says
    so in its own directory, whichever batch produced it.
    """
    path = directory / PROTOCOL_STAMP_FILE
    path.write_text(
        json.dumps(stamp_batch({}, ProtocolFreeze.of(protocol)), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
