"""The benchmark's arithmetic: thresholds, walltime sizing, and the report it writes."""

from __future__ import annotations

from pathlib import Path

import pytest

from late_ming_lab.experiments.benchmark import (
    DEV_THRESHOLDS,
    HPC_THRESHOLDS,
    WALLTIME_SAFETY,
    BenchmarkMeasurement,
    BenchmarkReport,
    Threshold,
    ThresholdResult,
    compare_to_thresholds,
    render_report,
    run_benchmarks,
    walltime_for,
)


def _measurement(
    *, ticks_per_second: float, seconds: float, peak_mib: float
) -> BenchmarkMeasurement:
    return BenchmarkMeasurement(
        label="synthetic",
        ticks=240,
        seconds=seconds,
        ticks_per_second=ticks_per_second,
        peak_mib=peak_mib,
        simulation_digest="0" * 64,
        event_count=1,
        python="3.12.0",
        platform="test",
    )


def test_a_threshold_is_cleared_in_the_direction_it_declares() -> None:
    """`at_least` and `at_most` are different claims: reading one as the other hides a miss."""
    at_least = Threshold(
        name="t", metric="ticks_per_second", bound=10.0, direction="at_least", protects="x"
    )
    at_most = Threshold(name="t", metric="seconds", bound=10.0, direction="at_most", protects="x")
    assert at_least.cleared(10.0) and at_least.cleared(11.0) and not at_least.cleared(9.9)
    assert at_most.cleared(10.0) and at_most.cleared(9.9) and not at_most.cleared(10.1)


def test_the_dev_set_is_enforced_and_names_what_each_bound_protects() -> None:
    fast = compare_to_thresholds(
        _measurement(ticks_per_second=30.0, seconds=8.0, peak_mib=512.0), DEV_THRESHOLDS
    )
    assert [result.cleared for result in fast] == [True, True, True]
    slow = compare_to_thresholds(
        _measurement(ticks_per_second=1.0, seconds=240.0, peak_mib=4096.0), DEV_THRESHOLDS
    )
    assert [result.cleared for result in slow] == [False, False, False]
    assert all(threshold.protects for threshold in DEV_THRESHOLDS)


def test_walltime_grows_with_the_measured_cost_and_the_safety_factor() -> None:
    """The Slurm walltime comes from a measurement times the declared safety factor."""
    assert walltime_for(60.0, safety=1.0) == "00:01:01"
    assert walltime_for(60.0, safety=WALLTIME_SAFETY) == "00:01:31"
    assert walltime_for(3600.0, safety=1.0) == "01:00:01"
    assert walltime_for(0.1, safety=1.0) == "00:01:00"
    assert int(walltime_for(600.0, safety=1.0)[-2:]) >= 0


def test_the_report_carries_the_measurement_both_sets_and_the_profile(tmp_path: Path) -> None:
    measurement = _measurement(ticks_per_second=24.0, seconds=10.0, peak_mib=900.0)
    report = BenchmarkReport(
        measurement=measurement,
        dev=compare_to_thresholds(measurement, DEV_THRESHOLDS),
        hpc=compare_to_thresholds(measurement, HPC_THRESHOLDS),
        profile=(("run (kernel.py:80)", 9.5, 1.0),),
    )
    text = render_report(report)
    assert "| ticks per second | 24.0 |" in text
    assert "dev-throughput" in text and "hpc-per-task" in text
    assert "run (kernel.py:80)" in text
    assert walltime_for(10.0) in text
    assert report.failures() == ()


def test_a_missed_development_threshold_is_reported_as_a_failure() -> None:
    measurement = _measurement(ticks_per_second=0.5, seconds=500.0, peak_mib=100.0)
    report = BenchmarkReport(
        measurement=measurement,
        dev=compare_to_thresholds(measurement, DEV_THRESHOLDS),
        hpc=compare_to_thresholds(measurement, HPC_THRESHOLDS),
        profile=(),
    )
    assert {result.threshold.name for result in report.failures()} == {
        "dev-throughput",
        "dev-window",
    }
    assert "**no**" in render_report(report)


def test_the_cluster_table_can_be_left_out(tmp_path: Path) -> None:
    """A caller who only wants the development numbers gets a report without the budget table."""
    measurement = _measurement(ticks_per_second=24.0, seconds=10.0, peak_mib=900.0)
    report = BenchmarkReport(
        measurement=measurement,
        dev=compare_to_thresholds(measurement, DEV_THRESHOLDS),
        hpc=(),
        profile=(),
    )
    text = render_report(report)
    assert "Cluster budget" not in text
    assert "Development thresholds" in text


def test_a_measurement_of_the_real_workload_has_the_declared_shape(tmp_path: Path) -> None:
    """The workload is the declared one; the profile is skipped here to stay quick."""
    report, path = run_benchmarks(path=tmp_path / "benchmark.md", with_profile=False)
    assert report.measurement.ticks == 240
    assert report.measurement.ticks_per_second > 0
    assert len(report.measurement.simulation_digest) == 64
    assert path.exists() and path.read_text(encoding="utf-8").startswith("# Benchmark")


@pytest.mark.parametrize("direction", ["at_least", "at_most"])
def test_a_threshold_result_reads_its_own_threshold(direction: str) -> None:
    threshold = Threshold(name="t", metric="seconds", bound=10.0, direction=direction, protects="x")
    assert ThresholdResult(threshold=threshold, measured=5.0).cleared is (direction == "at_most")
