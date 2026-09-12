"""The scheduler contract: registration order, dependency claims, diagram and digest.

The checks are declared here as the systems declare them: a phase-level claim about which shared
resource is produced when, not a field-level dataflow analysis. A system that reads a resource
nobody writes is reading initial actor state, which is allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from late_ming_lab.core import scheduler
from late_ming_lab.core.clock import Clock
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.manifest import RunManifest
from late_ming_lab.core.rng import RngStreams
from late_ming_lab.core.scheduler import SchedulerError
from late_ming_lab.core.tick import (
    RESOURCE_COHORT_GRAIN,
    RESOURCE_COHORT_SILVER,
    TICK_ORDER_VERSION,
    System,
    TickContext,
    TickPhase,
)
from late_ming_lab.evidence.provenance import Provenance
from late_ming_lab.experiments.assembly import build_toy_economy

CREATED_AT = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)


@dataclass(slots=True)
class _FakeSystem:
    """A test-only system whose dependency claim is exactly what the test declares."""

    name: str
    phase: TickPhase
    reads: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset()

    def step(self, ctx: TickContext) -> None: ...


def test_a_system_registered_out_of_phase_order_is_refused() -> None:
    systems: tuple[System, ...] = (
        _FakeSystem(name="late", phase=TickPhase.TAXATION),
        _FakeSystem(name="early", phase=TickPhase.CLIMATE_UPDATE),
    )

    with pytest.raises(SchedulerError, match="versioned tick order"):
        scheduler.validate(systems)


def test_a_duplicate_system_name_is_refused() -> None:
    systems: tuple[System, ...] = (
        _FakeSystem(name="same", phase=TickPhase.TAXATION),
        _FakeSystem(name="same", phase=TickPhase.RELIEF),
    )

    with pytest.raises(SchedulerError, match="duplicate system name 'same'"):
        scheduler.validate(systems)


def test_a_reader_before_the_earliest_writer_is_refused() -> None:
    systems: tuple[System, ...] = (
        _FakeSystem(
            name="early-reader",
            phase=TickPhase.AGRICULTURAL_STATE,
            reads=frozenset({RESOURCE_COHORT_GRAIN}),
        ),
        _FakeSystem(
            name="first-writer",
            phase=TickPhase.HOUSEHOLD_CONSUMPTION,
            writes=frozenset({RESOURCE_COHORT_GRAIN}),
        ),
        _FakeSystem(
            name="later-writer",
            phase=TickPhase.TAXATION,
            writes=frozenset({RESOURCE_COHORT_GRAIN}),
        ),
    )

    with pytest.raises(SchedulerError) as raised:
        scheduler.validate(systems)

    message = str(raised.value)
    assert RESOURCE_COHORT_GRAIN in message
    assert "early-reader" in message
    assert "agricultural_state" in message
    assert "household_consumption" in message


def test_a_read_of_a_resource_nobody_writes_is_initial_state() -> None:
    systems: tuple[System, ...] = (
        _FakeSystem(
            name="reader",
            phase=TickPhase.CLIMATE_UPDATE,
            reads=frozenset({RESOURCE_COHORT_SILVER}),
        ),
    )

    assert scheduler.validate(systems) == systems
    assert scheduler.dependency_report(systems) == ()


def test_the_integrated_toy_economy_declares_a_consistent_dependency_order() -> None:
    economy = build_toy_economy(with_military=True)
    systems = economy.systems

    assert scheduler.validate(systems) == systems
    report = scheduler.dependency_report(systems)
    assert report
    assert [edge for edge in report if not edge.satisfied] == []

    diagram = scheduler.as_mermaid(systems)
    lines = diagram.splitlines()
    assert lines[0].startswith("%%") and TICK_ORDER_VERSION in lines[0]
    assert lines[1] == "flowchart LR"
    for system in systems:
        assert f': {system.name}"]' in diagram


def test_the_systems_digest_pins_the_registrations() -> None:
    systems: tuple[System, ...] = (
        _FakeSystem(
            name="reader",
            phase=TickPhase.AGRICULTURAL_STATE,
            reads=frozenset({RESOURCE_COHORT_GRAIN}),
        ),
        _FakeSystem(
            name="writer", phase=TickPhase.TAXATION, writes=frozenset({RESOURCE_COHORT_SILVER})
        ),
    )

    digest = scheduler.systems_digest(systems)

    assert scheduler.systems_digest(tuple(systems)) == digest
    rephased: tuple[System, ...] = (
        systems[0],
        _FakeSystem(name="writer", phase=TickPhase.RELIEF),
    )
    reread: tuple[System, ...] = (
        systems[0],
        _FakeSystem(
            name="writer",
            phase=TickPhase.TAXATION,
            reads=frozenset({RESOURCE_COHORT_GRAIN}),
            writes=frozenset({RESOURCE_COHORT_SILVER}),
        ),
    )

    assert scheduler.systems_digest(rephased) != digest
    assert scheduler.systems_digest(reread) != digest


def test_the_manifest_records_the_registered_systems() -> None:
    config = SimulationConfig(tick_count=12, warmup_ticks=2)
    systems = build_toy_economy(with_military=True).systems

    manifest = RunManifest.for_run(
        config=config,
        clock=Clock.from_config(config),
        rng=RngStreams(config.root_seed),
        provenance=Provenance(git_sha="a" * 40, git_dirty=False),
        created_at=CREATED_AT,
        systems=systems,
    )

    assert manifest.systems == tuple(system.name for system in systems)
    assert manifest.systems_digest == scheduler.systems_digest(systems)
    for field in ("systems", "systems_digest"):
        incomplete = manifest.model_dump(mode="json")
        incomplete.pop(field)
        with pytest.raises(ValidationError):
            RunManifest.model_validate(incomplete)
