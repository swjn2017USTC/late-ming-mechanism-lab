"""The demo scenario: one declared run whose digest a regression test reproduces.

P14's claim is that the model is *runnable*: a declared scenario file, one command, and the same
digest every time. The scenario lives in `data/scenarios/demo.yaml` and this module is the only
code that reads it, so the claim has one implementation behind it: parse the declared fields, run
the sandbox, compare what came out with what the file records, and persist the run.

The expected values are a *reproducibility pin*, not a target: the digest and the event count were
observed once and recorded so that a later change to the kernel shows up as a failing test rather
than as a silently different demonstration. Nothing here fits anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.experiments.integrated import (
    INTEGRATED_TICK_COUNT,
    INTEGRATED_WARMUP_TICKS,
    IntegratedRun,
    IntegratedScenario,
    run_integrated_scenario,
)
from late_ming_lab.storage.run_store import RunStore

#: Where the declared scenario lives, and where a demo run goes unless a caller says otherwise.
SCENARIO_PATH: Final[str] = "data/scenarios/demo.yaml"
DEMO_OUTPUT_ROOT: Final[str] = "outputs/runs"

#: The scenario schema this module understands. A file with another version is refused rather than
#: read optimistically: a demo that silently ignores a field is not a demonstration of anything.
SCENARIO_SCHEMA_VERSION: Final[str] = "demo-scenario-v1"


class DemoError(RuntimeError):
    """Raised when the declared scenario cannot be read, run, or reproduced."""


class ExpectedOutcome(BaseModel):
    """What the scenario file records about the run it declares."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    simulation_digest: str = Field(min_length=1)
    event_count: int = Field(ge=0)
    tick_count: int = Field(ge=1)


class DemoScenario(BaseModel):
    """The declared demo: a sandbox point, a seed, and what running it produced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    label: str = Field(min_length=1)
    seed: int = Field(ge=0)
    ticks: int = Field(ge=1)
    warmup_ticks: int = Field(ge=0)
    sandbox: IntegratedScenario
    expected: ExpectedOutcome

    def config(self) -> SimulationConfig:
        """The kernel configuration the scenario declares."""
        return SimulationConfig.model_validate(
            {
                "root_seed": self.seed,
                "tick_count": self.ticks,
                "warmup_ticks": self.warmup_ticks,
                "scenario_id": self.id,
                "policy_id": "demo-v1",
            }
        )


@dataclass(frozen=True, slots=True)
class DemoOutcome:
    """What running the demo produced: the run, the digest comparison, and where it was written."""

    scenario: DemoScenario
    run: IntegratedRun
    simulation_digest: str
    event_count: int
    tick_count: int
    reproduced: bool
    details: tuple[str, ...]
    directory: Path | None


def load_scenario(path: str | Path = SCENARIO_PATH) -> DemoScenario:
    """Read the declared scenario, refusing a version or a field this module does not understand."""
    source = Path(path)
    if not source.exists():
        raise DemoError(f"{source} is missing; the demo scenario is declared there")
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise DemoError(f"{source} is not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise DemoError(f"{source} must hold a mapping, not {type(raw).__name__}")
    if raw.get("schema_version") != SCENARIO_SCHEMA_VERSION:
        raise DemoError(
            f"{source} declares schema {raw.get('schema_version')!r}, "
            f"not {SCENARIO_SCHEMA_VERSION!r}"
        )
    try:
        return DemoScenario.model_validate(raw)
    except ValidationError as error:
        raise DemoError(f"{source} does not match the scenario schema: {error}") from error


def run_demo(
    path: str | Path = SCENARIO_PATH,
    *,
    output_root: str | Path | None = DEMO_OUTPUT_ROOT,
    root: str | Path = ".",
) -> DemoOutcome:
    """Run the declared scenario and compare it with what the file says it produces.

    ``output_root=None`` runs the demo without persisting it, which is what the regression test
    uses: the point of the test is the digest, not another batch on disk.
    """
    scenario = load_scenario(path)
    run = run_integrated_scenario(scenario.sandbox, config=scenario.config(), root=root)
    summary = run.result.summary
    digest = summary.simulation_digest
    details: list[str] = []
    if digest != scenario.expected.simulation_digest:
        details.append(
            f"simulation digest {digest} differs from the recorded "
            f"{scenario.expected.simulation_digest}"
        )
    if summary.event_count != scenario.expected.event_count:
        details.append(
            f"event count {summary.event_count} differs from the recorded "
            f"{scenario.expected.event_count}"
        )
    if summary.tick_count != scenario.expected.tick_count:
        details.append(
            f"tick count {summary.tick_count} differs from the recorded "
            f"{scenario.expected.tick_count}"
        )
    directory = None
    if output_root is not None:
        directory = RunStore(Path(output_root)).write(run.result)
    return DemoOutcome(
        scenario=scenario,
        run=run,
        simulation_digest=digest,
        event_count=summary.event_count,
        tick_count=summary.tick_count,
        reproduced=not details,
        details=tuple(details),
        directory=directory,
    )


#: The sandbox point the demo declares, re-exported so a caller can see the two windows at a glance.
DEMO_WINDOW: Final[tuple[int, int]] = (INTEGRATED_TICK_COUNT, INTEGRATED_WARMUP_TICKS)
