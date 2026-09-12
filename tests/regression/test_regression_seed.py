"""Regression baseline for the fixed regression seed.

The pinned digest is the kernel's deterministic output for the default configuration and
:data:`late_ming_lab.core.config.DEFAULT_ROOT_SEED`. It changes only when the clock, the
event representation or the configuration defaults change on purpose — which is exactly
what a regression seed is for. Update it deliberately, in the commit that changes the
kernel contract, never to make a red test go green.
"""

from __future__ import annotations

from late_ming_lab.core.config import DEFAULT_ROOT_SEED, SimulationConfig
from late_ming_lab.core.kernel import SimulationKernel
from late_ming_lab.core.manifest import make_run_id

#: Expected simulation digest and event count for the default config and regression seed.
REGRESSION_SIMULATION_DIGEST = "c34bd4998586d1e72217ef64b834386cef0b30b805ac3291a8b721f8301cf379"
REGRESSION_EVENT_COUNT = 240


def _regression_run() -> SimulationKernel:
    return SimulationKernel(SimulationConfig())


def test_regression_seed_is_the_documented_default() -> None:
    assert DEFAULT_ROOT_SEED == 20260912
    assert SimulationConfig().root_seed == DEFAULT_ROOT_SEED


def test_default_window_is_the_documented_240_month_span() -> None:
    kernel = _regression_run()

    assert kernel.clock.tick_count == 240
    assert str(kernel.clock.start) == "1625-01"
    assert str(kernel.clock.end) == "1644-12"
    assert make_run_id(kernel.config).startswith("kernel-smoke-20260912-")


def test_regression_run_matches_the_pinned_baseline() -> None:
    result = _regression_run().run()

    assert result.summary.event_count == REGRESSION_EVENT_COUNT
    assert result.summary.simulation_digest == REGRESSION_SIMULATION_DIGEST


def test_repeating_the_regression_run_is_bit_identical() -> None:
    first = _regression_run().run()
    second = _regression_run().run()

    assert first.summary.simulation_digest == second.summary.simulation_digest
    assert first.events.equals(second.events)
    assert first.macro.equals(second.macro)
