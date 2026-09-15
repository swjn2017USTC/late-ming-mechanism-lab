"""The runtime arm over the historical core, from recorded fixtures, paired with the other policies.

The phase's decision-layer comparison is V1's `policy_robustness` module, which runs rule, utility,
random and the live model. This module runs the same four arms on the **historical core** — the
input V2 is about — with the runtime arm driven by *fixtures* rather than by the endpoint, so the
arm is re-runnable offline and byte-identically anywhere.

Two properties it keeps, both of them things the earlier version of this run got wrong:

```text
no fallback in a model arm   a refused decision leaves the state alone. Nothing imputes a rule
                             policy's answer into the arm the model was supposed to be tested on.
every decision is kept       the traces and the refusals are written, so "this decision came from a
                             fixture" is checkable rather than asserted
```
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.analysis.mechanisms import mechanism_readings
from late_ming_lab.core.hashing import canonical_json, hash_text
from late_ming_lab.experiments.historical_core import HISTORICAL_SCENARIO
from late_ming_lab.experiments.institutional_smoke import run_institutional
from late_ming_lab.experiments.interventions import ArmConfiguration, baseline_configuration
from late_ming_lab.experiments.replay import fixture_digest, replay_settings
from late_ming_lab.policies.recording import FixtureStore, ReplayTransport
from late_ming_lab.storage.tables import write_json, write_table

#: The arms, in declaration order: three offline policies and the model.
ARM_POLICIES: Final[tuple[str, ...]] = ("rule", "utility", "random", "ustc")

#: The core window and the paired world seeds. Two seeds is a pilot: the phase's own arm ladder is
#: 16 → 32 → 64, and this run reports itself as short of it rather than pretending otherwise.
CORE_TICKS: Final[int] = 96
CORE_WARMUP: Final[int] = 12
CORE_SEEDS: Final[tuple[int, ...]] = (20_260_915, 20_260_916)

#: Where the arms and their per-decision evidence are written.
ARMS_ROOT: Final[str] = "outputs/v2/p08"
ARMS_FILE: Final[str] = "policy-arms.parquet"
TRACES_FILE: Final[str] = "policy-arm-traces.parquet"
REFUSALS_FILE: Final[str] = "policy-arm-refusals.parquet"
ARMS_MANIFEST: Final[str] = "runtime-arms.json"


class RuntimeArmError(RuntimeError):
    """Raised when the arms cannot run at all."""


@dataclass(frozen=True, slots=True)
class ArmOutcome:
    """One arm at one seed: what ran, what it decided, and what it refused."""

    policy: str
    seed: int
    status: str
    reason: str
    decisions: int
    from_model: int
    refusals: int
    readings: dict[str, float]

    def record(self) -> dict[str, object]:
        return {
            "policy": self.policy,
            "seed": self.seed,
            "status": self.status,
            "reason": self.reason,
            "decisions": self.decisions,
            "decisions_from_model": self.from_model,
            "refusals": self.refusals,
            **{f"reading.{name}": value for name, value in sorted(self.readings.items())},
        }


def historical_arm_configuration() -> ArmConfiguration:
    """The declared baseline arm with the historical core as its scenario."""
    return baseline_configuration().with_updates(scenario=HISTORICAL_SCENARIO)


def run_runtime_arms(
    *,
    root: str | Path = ".",
    fixtures: str | Path = "tests/fixtures/llm",
    policies: Sequence[str] = ARM_POLICIES,
    seeds: Sequence[int] = CORE_SEEDS,
    ticks: int = CORE_TICKS,
    warmup_ticks: int = CORE_WARMUP,
    output_root: str | Path = ARMS_ROOT,
) -> tuple[ArmOutcome, ...]:
    """Run every arm at every seed on the historical core, keeping every decision and refusal."""
    repository = Path(root)
    store = FixtureStore(Path(fixtures))
    config = historical_arm_configuration()
    outcomes: list[ArmOutcome] = []
    trace_frames: list[pl.DataFrame] = []
    refusal_frames: list[pl.DataFrame] = []
    for policy in policies:
        for seed in seeds:
            transport = ReplayTransport(store) if policy in ("ustc", "replay") else None
            settings = replay_settings() if policy in ("ustc", "replay") else None
            try:
                run = run_institutional(
                    policy=policy,
                    config=config,
                    ticks=ticks,
                    warmup_ticks=warmup_ticks,
                    seed=seed,
                    transport=transport,
                    settings=settings,
                )
            except Exception as error:  # the gate itself, or a scenario that cannot run
                outcomes.append(
                    ArmOutcome(
                        policy=policy,
                        seed=seed,
                        status="refused",
                        reason=str(error)[:200],
                        decisions=0,
                        from_model=0,
                        refusals=0,
                        readings={},
                    )
                )
                continue
            traces = run.traces.with_columns(
                pl.lit(policy).alias("policy"), pl.lit(seed).alias("seed")
            )
            refusals = run.refusals.with_columns(
                pl.lit(policy).alias("policy"), pl.lit(seed).alias("seed")
            )
            trace_frames.append(traces)
            refusal_frames.append(refusals)
            from_model = (
                traces.filter(pl.col("model_id").is_not_null()).height
                if "model_id" in traces.columns
                else 0
            )
            outcomes.append(
                ArmOutcome(
                    policy=policy,
                    seed=seed,
                    status="ran",
                    reason="",
                    decisions=traces.height,
                    from_model=int(from_model),
                    refusals=refusals.height,
                    readings={
                        reading.mechanism: (1.0 if reading.present else 0.0)
                        for reading in mechanism_readings(run.events)
                    },
                )
            )
    write_arms(repository, outcomes, trace_frames, refusal_frames, store, ticks, warmup_ticks)
    return tuple(outcomes)


def write_arms(
    root: Path,
    outcomes: Sequence[ArmOutcome],
    trace_frames: Sequence[pl.DataFrame],
    refusal_frames: Sequence[pl.DataFrame],
    store: FixtureStore,
    ticks: int,
    warmup_ticks: int,
) -> tuple[Path, ...]:
    """Write the arms, their decisions and their refusals, with the provenance behind them."""
    directory = root / ARMS_ROOT
    directory.mkdir(parents=True, exist_ok=True)
    arms = Path(write_table(directory / ARMS_FILE, pl.DataFrame([o.record() for o in outcomes])))
    traces = write_table(
        directory / TRACES_FILE,
        pl.concat(trace_frames, how="diagonal_relaxed") if trace_frames else pl.DataFrame(),
    )
    refusals = write_table(
        directory / REFUSALS_FILE,
        pl.concat(refusal_frames, how="diagonal_relaxed") if refusal_frames else pl.DataFrame(),
    )
    manifest = {
        "schema_version": "runtime-arms-v1",
        "policies": [outcome.policy for outcome in outcomes],
        "seeds": sorted({outcome.seed for outcome in outcomes}),
        "ticks": ticks,
        "warmup_ticks": warmup_ticks,
        "scenario": HISTORICAL_SCENARIO.label,
        "fixture_digest": fixture_digest(store),
        "fallback": "none: a refused decision leaves the state alone",
        "decisions_from_model": sum(outcome.from_model for outcome in outcomes),
        "refusals": sum(outcome.refusals for outcome in outcomes),
    }
    manifest["manifest_hash"] = hash_text(canonical_json(manifest))
    write_json(directory / ARMS_MANIFEST, manifest)
    return (arms, traces, refusals)


def load_arms_manifest(root: str | Path) -> Mapping[str, object]:
    path = Path(root) / ARMS_ROOT / ARMS_MANIFEST
    payload: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return payload


__all__ = [
    "ARMS_FILE",
    "ARMS_MANIFEST",
    "ARMS_ROOT",
    "ARM_POLICIES",
    "CORE_SEEDS",
    "CORE_TICKS",
    "CORE_WARMUP",
    "REFUSALS_FILE",
    "TRACES_FILE",
    "ArmOutcome",
    "RuntimeArmError",
    "historical_arm_configuration",
    "load_arms_manifest",
    "run_runtime_arms",
    "write_arms",
]
