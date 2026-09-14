"""Running the historical core: a smoke window and the full declared window.

This is the phase's evidence that the reconstructed core actually runs, and it is deliberately
separate from the synthetic fixtures' runs:

```text
smoke   24 ticks, the wiring and the fail-closed coverage check
full    240 ticks (1625-01 to 1644-12), the declared scenario, written under outputs/v2/
```

The runs go to `outputs/v2/historical-core-v1/`, not into the V1 artifact tree, and every summary
records what forcing it used: which series, which allocation mode, how many node-years were imputed
and how many monthly values were clipped by the allocator. A run of this scenario is never reported
as a synthetic run, and a synthetic run is never offered as the historical baseline.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.experiments.integrated import (
    INTEGRATED_TICK_COUNT,
    INTEGRATED_WARMUP_TICKS,
    IntegratedRun,
    IntegratedScenario,
    run_integrated_scenario,
)
from late_ming_lab.historical.build import load_core
from late_ming_lab.storage.run_store import RunStore

#: Where a historical run is written. A V2 root, so no V1 artifact directory is ever touched.
HISTORICAL_OUTPUT_ROOT: Final[str] = "outputs/v2/historical-core-v1"

#: The declared scenario: the historical core's space, the observed forcing, the same 240 ticks.
HISTORICAL_SCENARIO: Final[IntegratedScenario] = IntegratedScenario(
    label="historical-core-v1",
    dataset="historical-core-v1",
    climate_mode="observed-historical",
    allocation_mode="seasonal",
    nominal_pressure=0.02,
    pay_share_of_treasury=0.5,
    garrison_troops=300.0,
)

SMOKE_TICKS: Final[int] = 24
SMOKE_WARMUP_TICKS: Final[int] = 6


@dataclass(frozen=True, slots=True)
class HistoricalRunOutcome:
    """What one historical run produced, with the forcing provenance that goes with it."""

    label: str
    ticks: int
    warmup_ticks: int
    simulation_digest: str
    event_count: int
    seconds: float
    climate: dict[str, Any]
    node_count: int
    county_count: int
    directory: Path | None

    def record(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "ticks": self.ticks,
            "warmup_ticks": self.warmup_ticks,
            "simulation_digest": self.simulation_digest,
            "event_count": self.event_count,
            "seconds": round(self.seconds, 3),
            "climate": self.climate,
            "nodes": self.node_count,
            "counties": self.county_count,
            "directory": None if self.directory is None else str(self.directory),
        }


def run_historical(
    *,
    ticks: int = INTEGRATED_TICK_COUNT,
    warmup_ticks: int = INTEGRATED_WARMUP_TICKS,
    label: str | None = None,
    root: str | Path = ".",
    output_root: str | Path | None = None,
) -> HistoricalRunOutcome:
    """Run the declared historical scenario, optionally writing it, and report its provenance."""
    repository = Path(root)
    scenario = HISTORICAL_SCENARIO
    config = SimulationConfig.model_validate(
        {
            "tick_count": ticks,
            "warmup_ticks": warmup_ticks,
            "scenario_id": f"{scenario.dataset}-{ticks}t",
            "policy_id": "integrated-v1",
        }
    )
    core = load_core(repository)
    started = time.perf_counter()
    run = run_integrated_scenario(scenario, config=config, root=repository)
    seconds = time.perf_counter() - started
    summary = run.result.summary
    climate = _climate_summary(run)
    directory: Path | None = None
    if output_root is not None:
        # The run id already carries the dataset, the window length and the seed, so the store's
        # collision check is meaningful: the same declaration cannot quietly change under it.
        directory = RunStore(Path(output_root)).write(run.result)
        _write_provenance(directory, run, core, climate)
    return HistoricalRunOutcome(
        label=label or scenario.label,
        ticks=ticks,
        warmup_ticks=warmup_ticks,
        simulation_digest=summary.simulation_digest,
        event_count=summary.event_count,
        seconds=seconds,
        climate=climate,
        node_count=len(run.economy.graphs.nodes),
        county_count=len(run.economy.graphs.nodes.counties),
        directory=directory,
    )


def _write_provenance(
    directory: Path,
    run: IntegratedRun,
    core: Any,
    climate: dict[str, Any],
) -> None:
    """Write what a historical run read, beside the run: the V2 provenance sidecar.

    The V1 run manifest records the code, the seed and the scenario but knows nothing about the
    dataset the run was built from or the forcing that drove it. A V2 historical run has to say
    both, so this sidecar records the core's dataset id and manifest digest, the source snapshots
    with their hashes, the allocator's mode and weights, and how many node-years were imputed.
    """
    payload = {
        "schema_version": "historical-run-provenance-v1",
        "run_id": run.result.manifest.run_id,
        "dataset": core.manifest.dataset_id,
        "dataset_manifest": {
            "stations": core.manifest.stations,
            "tables": core.manifest.tables,
            "selection_report": core.manifest.selection_report,
            "edges": core.manifest.edges,
        },
        "sources": core.manifest.built_from,
        "climate": climate,
        "rights": core.manifest.rights,
    }
    (directory / "v2-provenance.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _climate_summary(run: IntegratedRun) -> dict[str, Any]:
    """What forcing the run actually used, read back from the economy that ran it."""
    from late_ming_lab.historical.forcing import AllocatedObservedClimate

    for system in run.economy.systems:
        model = getattr(system, "_model", None)
        if isinstance(model, AllocatedObservedClimate):
            return model.summary()
    return {"series_id": None, "note": "the run did not use the allocated observed forcing"}


def main(argv: list[str] | None = None) -> int:
    """Run the smoke window and the declared window, printing what each produced."""
    parser = argparse.ArgumentParser(description="Run the historical core")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--output-root", default=HISTORICAL_OUTPUT_ROOT)
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args(argv)
    core = load_core(arguments.root)
    smoke = run_historical(
        ticks=SMOKE_TICKS,
        warmup_ticks=SMOKE_WARMUP_TICKS,
        label="historical-core-v1-smoke",
        root=arguments.root,
        output_root=None,
    )
    outcomes = [smoke]
    if not arguments.smoke_only:
        outcomes.append(run_historical(root=arguments.root, output_root=arguments.output_root))
    payload = {
        "dataset": core.manifest.dataset_id,
        "nodes": len(core.nodes),
        "counties": core.county_ids(),
        "runs": [outcome.record() for outcome in outcomes],
    }
    if arguments.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(f"dataset {payload['dataset']}: {payload['nodes']} nodes")
        for outcome in outcomes:
            record = outcome.record()
            print(
                f"{record['label']}: {record['ticks']} ticks, {record['event_count']} events, "
                f"{record['seconds']}s, digest {record['simulation_digest'][:12]}"
            )
            print(
                f"  forcing: {record['climate'].get('series_id')} "
                f"{record['climate'].get('allocation_mode')}, imputed "
                f"{record['climate'].get('imputed_node_years')} node-years"
            )
            if record["directory"]:
                print(f"  wrote {record['directory']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
