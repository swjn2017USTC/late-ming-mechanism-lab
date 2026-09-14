"""The integrated fixed-seed regression: 240 ticks of the whole sandbox, pinned.

The two digests below are the sandbox's deterministic output for the default configuration and
:data:`late_ming_lab.core.config.DEFAULT_ROOT_SEED` over the full 1625-01 to 1644-12 window: the
five-county fixture and the twelve-county fixture, with every mechanism from P02 to P06 plus
migration wired in the same order.

They change when any mechanism, its parameters, the tick order, the event vocabulary or the
ordering of draws inside a subsystem changes — as they did in V2-P04, when the price, relief
and migration chains began recording their own constraints: the vocabulary grew, the
behavioural counts did not, and the phase report shows the row-level difference.

They are also the first pins taken *after* the sandbox was proved deterministic across processes:
iterating a set of node ids had made the number of events depend on the interpreter's string hash
seed, which no single-process replay could detect — which is exactly what a regression seed is for:
without it, "the sandbox still works" would be an opinion. Update them deliberately, in the commit
that changes the contract, and record the row-level difference in the phase report; never to make
a red test go green.

The wiring is pinned too (`systems` and `systems_digest` in the manifest): a run that quietly lost
a mechanism would keep reproducing a stale digest forever, so the test asserts the registered
system list and its digest as well.
"""

from __future__ import annotations

import polars as pl

from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.experiments.integrated import (
    INTEGRATED_TICK_COUNT,
    INTEGRATED_WARMUP_TICKS,
    IntegratedScenario,
    run_integrated_scenario,
)

#: The five-county fixture over the full window.
TOY_DIGEST = "c221b8e1dc807166304af1fcf3bda8b7b36effd9b75b2eda2000de3d843cb575"
TOY_EVENT_COUNT = 108_617

#: The twelve-county fixture over the full window.
MEDIUM_DIGEST = "525048b64a7614488adc2b45110815175cda8896413bbd854c42b59450ca240e"
MEDIUM_EVENT_COUNT = 255_982

#: The wiring every integrated run must register, in phase order.
EXPECTED_SYSTEMS: tuple[str, ...] = (
    "climate",
    "agricultural-state",
    "harvest",
    "household-consumption",
    "market-clearing",
    "debt-service",
    "tax-collection",
    "official-relief",
    "elite-actions",
    "migration",
    "military-finance",
    "desertion",
    "band-recruitment",
    "band-actions",
    "violence",
    "military-bookkeeping",
    "cohort-bookkeeping",
    "county-bookkeeping",
)

#: Digest of that wiring: name, phase, reads and writes for every registered system.
EXPECTED_SYSTEMS_DIGEST = "822625248093abe5e47622afc6f17d7f8946837cf408aba6f78532e8ae4334ff"


def test_the_toy_regression_run_matches_its_pinned_sandbox() -> None:
    run = run_integrated_scenario(IntegratedScenario(label="toy-240", dataset="toy"))

    assert run.result.summary.tick_count == INTEGRATED_TICK_COUNT
    assert run.result.summary.event_count == TOY_EVENT_COUNT
    assert run.result.summary.simulation_digest == TOY_DIGEST


def test_the_medium_regression_run_matches_its_pinned_sandbox() -> None:
    run = run_integrated_scenario(IntegratedScenario(label="medium-240", dataset="medium"))

    assert run.result.summary.tick_count == INTEGRATED_TICK_COUNT
    assert run.result.summary.event_count == MEDIUM_EVENT_COUNT
    assert run.result.summary.simulation_digest == MEDIUM_DIGEST


def test_the_registered_wiring_is_pinned_with_the_run() -> None:
    run = run_integrated_scenario(IntegratedScenario(label="toy-240", dataset="toy"))

    assert run.result.manifest.systems == EXPECTED_SYSTEMS
    assert run.result.manifest.systems_digest == EXPECTED_SYSTEMS_DIGEST


def test_a_replay_of_the_regression_run_is_event_for_event_identical() -> None:
    """The replay property the manifest exists for: same code, config, seed, policy, same events."""
    scenario = IntegratedScenario(label="replay", dataset="toy")
    first = run_integrated_scenario(
        scenario,
        config=SimulationConfig.model_validate(
            {"tick_count": 60, "warmup_ticks": 12, "scenario_id": "toy-fixture"}
        ),
    )
    replay = run_integrated_scenario(
        scenario,
        config=SimulationConfig.model_validate(
            {"tick_count": 60, "warmup_ticks": 12, "scenario_id": "toy-fixture"}
        ),
    )

    assert replay.result.events.equals(first.result.events)
    assert replay.result.summary.simulation_digest == first.result.summary.simulation_digest


def test_the_warmup_window_is_the_declared_one() -> None:
    run = run_integrated_scenario(IntegratedScenario(label="toy-240", dataset="toy"))

    assert run.result.config.warmup_ticks == INTEGRATED_WARMUP_TICKS
    assert run.result.config.start_year == 1625
    assert run.result.config.start_month == 1
    first = run.result.events.filter(pl.col("event_type") == "TICK").sort("tick")
    ticks = first["tick"].to_list()
    assert ticks[0] == 0
    assert ticks[-1] == INTEGRATED_TICK_COUNT - 1
    assert len(ticks) == INTEGRATED_TICK_COUNT
