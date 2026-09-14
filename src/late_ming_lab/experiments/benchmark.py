"""The benchmark: what the model costs, on which machine, against which declared threshold.

Two threshold sets, because the two environments answer different questions:

- **dev** is a laptop, one process, and it is *enforced*: :func:`compare_to_thresholds` says
  whether a measurement clears it, and ``late-ming-lab bench --enforce`` exits non-zero when it
  does not. The
  bounds are set from measurements P14 actually made on this machine, with headroom, and each one
  names what it is protecting: a developer waiting, or a batch that has to finish inside a walltime.
- **hpc** is a declared budget for sizing a Slurm array - per-task cost times tasks, against a
  walltime, with a safety factor. Nothing here pretends a cluster was available: the template
  takes its walltime from a *measured* per-task cost, and the budget check exists so that the
  arithmetic is done from a number rather than from optimism.

The measurement is the medium integrated sandbox at full window length, because that is the workload
a batch is made of. Ticks per second and peak resident memory are read from the process itself, and
the run's own digest is captured so a benchmark that silently ran something else is visible.
"""

from __future__ import annotations

import cProfile
import platform
import pstats
import resource
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.experiments.integrated import (
    INTEGRATED_TICK_COUNT,
    INTEGRATED_WARMUP_TICKS,
    IntegratedScenario,
    run_integrated_scenario,
)

#: The workload: the medium sandbox over the full window, which is what one batch task runs.
BENCHMARK_SCENARIO: Final[IntegratedScenario] = IntegratedScenario(
    label="bench-medium", dataset="medium"
)
BENCHMARK_SEED: Final[int] = 20_260_915

#: Where a benchmark report is written, and how many functions the profile lists.
REPORT_PATH: Final[str] = "outputs/reports/benchmark.md"
PROFILE_DEPTH: Final[int] = 15


class BenchmarkError(RuntimeError):
    """Raised when a benchmark cannot be measured or summarised as declared."""


@dataclass(frozen=True, slots=True)
class Threshold:
    """One declared bound, and what it protects."""

    name: str
    metric: str  # "ticks_per_second" | "peak_mib" | "seconds"
    bound: float
    direction: str  # "at_least" | "at_most"
    protects: str

    def cleared(self, measured: float) -> bool:
        if self.direction == "at_least":
            return measured >= self.bound
        return measured <= self.bound


#: The laptop thresholds, enforced by ``late-ming-lab bench --enforce``.
#:
#: Measured on the development machine during P14 (Apple M4, Python 3.12): the medium sandbox runs
#: 240 ticks in about 10 seconds, so ~24 ticks per second, with a peak resident set well under a
#: gigabyte. The bounds sit below the measurement with room for a slower laptop rather than at it,
#: because a threshold that only the machine it was written on can clear protects nothing.
DEV_THRESHOLDS: Final[tuple[Threshold, ...]] = (
    Threshold(
        name="dev-throughput",
        metric="ticks_per_second",
        bound=5.0,
        direction="at_least",
        protects="a developer's edit-run loop: a full window in under a minute",
    ),
    Threshold(
        name="dev-window",
        metric="seconds",
        bound=120.0,
        direction="at_most",
        protects="a single full-window run inside a short interactive session",
    ),
    Threshold(
        name="dev-memory",
        metric="peak_mib",
        bound=2048.0,
        direction="at_most",
        protects="a laptop running the model beside an editor and a browser",
    ),
)

#: The cluster budget, declared for sizing an array rather than for a pass/fail on this machine.
HPC_THRESHOLDS: Final[tuple[Threshold, ...]] = (
    Threshold(
        name="hpc-per-task",
        metric="seconds",
        bound=600.0,
        direction="at_most",
        protects="one array task inside a ten-minute walltime with a 1.5 safety factor",
    ),
    Threshold(
        name="hpc-memory",
        metric="peak_mib",
        bound=4096.0,
        direction="at_most",
        protects="the per-task memory ceiling a shared cluster node enforces",
    ),
)

#: The safety factor a walltime is sized with: measured cost times this, rounded up.
WALLTIME_SAFETY: Final[float] = 1.5


@dataclass(frozen=True, slots=True)
class BenchmarkMeasurement:
    """What one benchmark run cost."""

    label: str
    ticks: int
    seconds: float
    ticks_per_second: float
    peak_mib: float
    simulation_digest: str
    event_count: int
    python: str
    platform: str


@dataclass(frozen=True, slots=True)
class ThresholdResult:
    """One threshold against one measurement."""

    threshold: Threshold
    measured: float

    @property
    def cleared(self) -> bool:
        return self.threshold.cleared(self.measured)


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """The measurement, both threshold sets, and the profile of the same workload."""

    measurement: BenchmarkMeasurement
    dev: tuple[ThresholdResult, ...]
    hpc: tuple[ThresholdResult, ...]
    profile: tuple[tuple[str, float, float], ...]  # (function, cumulative seconds, call count)

    def failures(self) -> tuple[ThresholdResult, ...]:
        """The dev thresholds the measurement did not clear; the enforced set is dev."""
        return tuple(result for result in self.dev if not result.cleared)


def measure(
    *, scenario: IntegratedScenario = BENCHMARK_SCENARIO, seed: int = BENCHMARK_SEED
) -> BenchmarkMeasurement:
    """Time one full-window run of the declared workload and read the process's own peak memory."""
    config = SimulationConfig.model_validate(
        {
            "root_seed": seed,
            "tick_count": INTEGRATED_TICK_COUNT,
            "warmup_ticks": INTEGRATED_WARMUP_TICKS,
            "scenario_id": f"{scenario.dataset}-benchmark",
            "policy_id": "benchmark-v1",
        }
    )
    before = _peak_mib()
    start = time.perf_counter()
    run = run_integrated_scenario(scenario, config=config)
    elapsed = time.perf_counter() - start
    peak = max(_peak_mib() - before, 0.0)
    summary = run.result.summary
    return BenchmarkMeasurement(
        label=scenario.label,
        ticks=summary.tick_count,
        seconds=elapsed,
        ticks_per_second=summary.tick_count / elapsed if elapsed > 0 else float("inf"),
        peak_mib=peak,
        simulation_digest=summary.simulation_digest,
        event_count=summary.event_count,
        python=platform.python_version(),
        platform=f"{platform.system()} {platform.machine()}",
    )


def _peak_mib() -> float:
    """The process's peak resident set in MiB; ``ru_maxrss`` is bytes on macOS and KiB on Linux."""
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024


def compare_to_thresholds(
    measurement: BenchmarkMeasurement, thresholds: tuple[Threshold, ...]
) -> tuple[ThresholdResult, ...]:
    """Every declared threshold against its metric on this measurement."""
    values = {
        "ticks_per_second": measurement.ticks_per_second,
        "seconds": measurement.seconds,
        "peak_mib": measurement.peak_mib,
    }
    return tuple(
        ThresholdResult(threshold=threshold, measured=values[threshold.metric])
        for threshold in thresholds
    )


def profile(
    *,
    scenario: IntegratedScenario = BENCHMARK_SCENARIO,
    seed: int = BENCHMARK_SEED,
    depth: int = PROFILE_DEPTH,
) -> tuple[tuple[str, float, float], ...]:
    """Profile the same workload and return the heaviest functions by cumulative time."""
    config = SimulationConfig.model_validate(
        {
            "root_seed": seed,
            "tick_count": INTEGRATED_TICK_COUNT,
            "warmup_ticks": INTEGRATED_WARMUP_TICKS,
            "scenario_id": f"{scenario.dataset}-profile",
            "policy_id": "benchmark-v1",
        }
    )
    profiler = cProfile.Profile()
    profiler.enable()
    run_integrated_scenario(scenario, config=config)
    profiler.disable()
    return _profile_rows(pstats.Stats(profiler), depth)


def _profile_rows(stats: pstats.Stats, depth: int) -> tuple[tuple[str, float, float], ...]:
    """The heaviest functions by cumulative time, read from a profiler whose data is untyped.

    ``typeshed`` declares ``pstats.Stats``' methods but not its data attributes, so the table is
    read through ``getattr`` and validated rather than assumed; the key is the function's
    ``(file, line, name)`` tuple and the row is
    ``(calls, non-recursive calls, total time, cumulative time, ...)``, both as ``pstats`` documents
    them.
    """
    table = getattr(stats, "stats", None)
    if not isinstance(table, dict):
        raise BenchmarkError("the profiler returned no table; nothing can be ranked")
    ranked = sorted(table.items(), key=lambda item: -float(item[1][3]))[:depth]
    return tuple(
        (
            f"{key[2]} ({Path(key[0]).name}:{key[1]})",
            float(row[3]),
            float(row[0]),
        )
        for key, row in ranked
    )


def run_benchmarks(
    *,
    path: str | Path = REPORT_PATH,
    with_profile: bool = True,
    with_hpc: bool = True,
    scenario: IntegratedScenario = BENCHMARK_SCENARIO,
) -> tuple[BenchmarkReport, Path]:
    """Measure, compare against both declared sets, optionally profile, and write the report."""
    measurement = measure(scenario=scenario)
    report = BenchmarkReport(
        measurement=measurement,
        dev=compare_to_thresholds(measurement, DEV_THRESHOLDS),
        hpc=compare_to_thresholds(measurement, HPC_THRESHOLDS) if with_hpc else (),
        profile=profile(scenario=scenario) if with_profile else (),
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_report(report), encoding="utf-8")
    return report, target


def render_report(report: BenchmarkReport) -> str:
    """The benchmark as Markdown: the measurement, both sets, and the profile."""
    measurement = report.measurement
    lines = [
        "# Benchmark",
        "",
        f"Workload: the `{measurement.label}` integrated sandbox, {measurement.ticks} ticks "
        f"({INTEGRATED_WARMUP_TICKS} warm-up), seed {BENCHMARK_SEED}.",
        f"Machine: {measurement.platform}, Python {measurement.python}.",
        "",
        "| metric | measured |",
        "|---|---|",
        f"| seconds | {measurement.seconds:.2f} |",
        f"| ticks per second | {measurement.ticks_per_second:.1f} |",
        f"| peak resident memory | {measurement.peak_mib:.0f} MiB |",
        f"| events | {measurement.event_count} |",
        f"| simulation digest | `{measurement.simulation_digest}` |",
        "",
        "## Development thresholds (enforced by `late-ming-lab bench --enforce`)",
        "",
        "| name | metric | bound | measured | cleared | protects |",
        "|---|---|---|---|---|---|",
    ]
    for result in report.dev:
        threshold = result.threshold
        mark = "yes" if result.cleared else "**no**"
        lines.append(
            f"| `{threshold.name}` | {threshold.metric} | {threshold.direction} "
            f"{threshold.bound:g} | {result.measured:.2f} | {mark} | {threshold.protects} |"
        )
    if report.hpc:
        lines.extend(
            [
                "",
                "## Cluster budget (declared; sizes the Slurm array, grades no machine)",
                "",
                "| name | metric | bound | measured | cleared | protects |",
                "|---|---|---|---|---|---|",
            ]
        )
        for result in report.hpc:
            threshold = result.threshold
            mark = "yes" if result.cleared else "no"
            lines.append(
                f"| `{threshold.name}` | {threshold.metric} | {threshold.direction} "
                f"{threshold.bound:g} | {result.measured:.2f} | {mark} | {threshold.protects} |"
            )
    walltime = walltime_for(measurement.seconds)
    lines.extend(
        [
            "",
            f"A task measured at {measurement.seconds:.1f} s is given a walltime of {walltime} "
            f"(safety factor {WALLTIME_SAFETY:g}) by the Slurm template.",
        ]
    )
    if report.profile:
        lines.extend(
            [
                "",
                "## Profile of the same workload",
                "",
                "| function | cumulative seconds | calls |",
                "|---|---|---|",
            ]
        )
        for function, cumulative, calls in sorted(
            report.profile, key=lambda row: row[1], reverse=True
        ):
            lines.append(f"| `{function}` | {cumulative:.2f} | {calls:.0f} |")
    lines.append("")
    return "\n".join(lines)


def walltime_for(seconds: float, *, safety: float = WALLTIME_SAFETY) -> str:
    """A Slurm walltime for one task, in ``HH:MM:SS``, from its measured cost."""
    total = max(int(seconds * safety) + 1, 60)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
