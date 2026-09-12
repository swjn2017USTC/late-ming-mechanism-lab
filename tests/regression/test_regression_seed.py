"""Regression baseline for the fixed regression seed.

The pinned digests are the kernel's deterministic output for the default configuration and
:data:`late_ming_lab.core.config.DEFAULT_ROOT_SEED`: once with no system registered, once
with the toy spatial dataset and synthetic climate forcing. They change only when the clock,
the event representation, the configuration defaults or the climate draw order change on
purpose — which is exactly what a regression seed is for. Update them deliberately, in the
commit that changes the contract, never to make a red test go green.

The household and market baselines pin more than the clock: they fix the order in which climate
draws are consumed, the production function, the coping ladder, the price rule, the clearing
order, arbitrage and the credit rules. A change to any of them moves the digest, which is the
point.
"""

from __future__ import annotations

from late_ming_lab.core.config import DEFAULT_ROOT_SEED, SimulationConfig
from late_ming_lab.core.kernel import SimulationKernel
from late_ming_lab.core.manifest import make_run_id
from late_ming_lab.experiments.household_shock import ScenarioRun, ShockScenario, run_scenario
from late_ming_lab.experiments.market_credit import (
    MarketRun,
    MarketScenario,
    run_market_scenario,
)
from late_ming_lab.networks.fixtures import toy_spatial_dataset
from late_ming_lab.systems.calendar import core_default_calendar
from late_ming_lab.systems.climate import ClimateSystem, SyntheticClimate

#: Expected simulation digest and event count for the default config and regression seed.
REGRESSION_SIMULATION_DIGEST = "c34bd4998586d1e72217ef64b834386cef0b30b805ac3291a8b721f8301cf379"
REGRESSION_EVENT_COUNT = 240

#: Same, with the toy dataset and synthetic climate forcing over five county nodes.
CLIMATE_SIMULATION_DIGEST = "6a03cce6cfdc4e8c426f19ec839f7d8ea3e2a0d9628e8e03c80fb2f238ce0755"
CLIMATE_EVENT_COUNT = 240 * 6

#: The P05 fiscal economy: county governments, assessment, collection and official relief.
#:
#: Re-pinned in P06 for instrumentation only: the county's monthly state record now carries the
#: military decomposition (``military_pay_tael``, ``military_grain_shi``), both zero when no
#: garrison is wired. Verified by row-level diff against the P05 log: 480 of 28764 events changed,
#: each gaining those two keys and nothing else, and event count is unchanged.
#:
#: Re-pinned in P07 for instrumentation only, with the market-phase correction described above and
#: verified the same way (the fiscal run's event count is unchanged at 28764). Both re-pins are
#: recorded in their phase reports.
FISCAL_DIGEST = "c9a1d9d56f84617e2a78c9428207f5cd513d3e4662e07284d945c9ff6efe977d"
FISCAL_EVENT_COUNT = 28764

#: Same, with the whole P04 economy (market, merchants, elites, credit): two short windows.
#:
#: Re-pinned in P05 for instrumentation only: the log now tags why a sale happened
#: (``reason_is_*``) and names the rent counterparty, so digests move while balances, flows and
#: every published P03/P04 answer stay identical. The P05 report records the change.
#:
#: Re-pinned again in P07 for instrumentation only: a market trade now records the phase of the
#: system that asked for it rather than the market's own phase, so a ration purchase is logged
#: under ``military_finance`` and a household's dinner under ``household_consumption``. The calm
#: market baseline is untouched (no cross-phase trade happens in it); the severe one moves, and an
#: A/B run of the same scenario showed identical sequence numbers, identical event count and every
#: column byte-identical except the ``phase`` token on 600 merchant rows. The P07 report records
#: it, and both earlier re-pins stand on the same row-level evidence.
MARKET_BASELINE_DIGEST = "4b98410a02a5400c20f148ab0ee26a971cb6379807285337ed00a3274587c545"
MARKET_BASELINE_EVENT_COUNT = 10618
MARKET_SEVERE_DIGEST = "dd7d6e7d4df8c26e64e33349f4547ef1c6f0d214192cd5089d47924f7bcd0fed"
MARKET_SEVERE_EVENT_COUNT = 14108

#: Same, with the toy cohort population: a normal year and a severe synthetic shock.
HOUSEHOLD_BASELINE_DIGEST = "39d980735462639c2ea0cc837751eac97b6fec488b828747d6ada3fc1ae50a2d"
HOUSEHOLD_BASELINE_EVENT_COUNT = 25606
HOUSEHOLD_SEVERE_DIGEST = "f61073359378ac876913689259e08d925f42be1d4e38be1ea089b9e334197060"
HOUSEHOLD_SEVERE_EVENT_COUNT = 33606


def _regression_run() -> SimulationKernel:
    return SimulationKernel(SimulationConfig())


def _climate_run() -> SimulationKernel:
    nodes = toy_spatial_dataset().build().nodes
    model = SyntheticClimate(monthly_event_probability=0.25, severity_floor=0.3)
    return SimulationKernel(
        SimulationConfig(), [ClimateSystem(nodes, core_default_calendar(), model)]
    )


def _household_runs() -> tuple[ScenarioRun, ScenarioRun]:
    return (
        run_scenario(ShockScenario("baseline", 0.0, 0.0)),
        run_scenario(ShockScenario("severe", 0.5, 0.6)),
    )


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


def test_climate_regression_run_matches_the_pinned_baseline() -> None:
    result = _climate_run().run()

    assert result.summary.event_count == CLIMATE_EVENT_COUNT
    assert result.summary.simulation_digest == CLIMATE_SIMULATION_DIGEST


def test_climate_forcing_replays_draw_for_draw() -> None:
    first = _climate_run().run()
    second = _climate_run().run()

    assert first.events.equals(second.events)
    assert first.summary.simulation_digest == second.summary.simulation_digest


def test_household_regression_runs_match_their_pinned_baselines() -> None:
    baseline, severe = _household_runs()

    assert baseline.result.summary.event_count == HOUSEHOLD_BASELINE_EVENT_COUNT
    assert baseline.result.summary.simulation_digest == HOUSEHOLD_BASELINE_DIGEST
    assert severe.result.summary.event_count == HOUSEHOLD_SEVERE_EVENT_COUNT
    assert severe.result.summary.simulation_digest == HOUSEHOLD_SEVERE_DIGEST


def _market_runs() -> tuple[MarketRun, MarketRun]:
    compact = SimulationConfig.model_validate({"tick_count": 96, "warmup_ticks": 24})
    return (
        run_market_scenario(MarketScenario("market-baseline"), config=compact),
        run_market_scenario(
            MarketScenario("market-severe", monthly_event_probability=0.5, severity_floor=0.6),
            config=compact,
        ),
    )


def test_market_regression_runs_match_their_pinned_baselines() -> None:
    baseline, severe = _market_runs()

    assert baseline.result.summary.event_count == MARKET_BASELINE_EVENT_COUNT
    assert baseline.result.summary.simulation_digest == MARKET_BASELINE_DIGEST
    assert severe.result.summary.event_count == MARKET_SEVERE_EVENT_COUNT
    assert severe.result.summary.simulation_digest == MARKET_SEVERE_DIGEST


def test_market_regression_run_replays_exactly() -> None:
    first, _ = _market_runs()
    second, _ = _market_runs()

    assert first.result.events.equals(second.result.events)


def test_household_forcing_replays_and_the_shock_changes_it() -> None:
    baseline, severe = _household_runs()
    replay = run_scenario(ShockScenario("severe", 0.5, 0.6))

    assert severe.result.events.equals(replay.result.events)
    assert not baseline.result.events.equals(severe.result.events)


def test_fiscal_regression_run_matches_its_pinned_baseline() -> None:
    from late_ming_lab.experiments.extraction import ExtractionScenario, run_extraction_scenario

    compact = SimulationConfig.model_validate({"tick_count": 96, "warmup_ticks": 24})
    run = run_extraction_scenario(
        ExtractionScenario(
            label="fiscal-baseline",
            nominal_pressure=0.02,
            monthly_event_probability=0.5,
            severity_floor=0.6,
        ),
        config=compact,
    )

    assert run.result.summary.event_count == FISCAL_EVENT_COUNT
    assert run.result.summary.simulation_digest == FISCAL_DIGEST
