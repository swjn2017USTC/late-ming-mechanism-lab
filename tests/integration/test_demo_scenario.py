"""The declared demo scenario: it reproduces, and it refuses what it cannot read."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from late_ming_lab.experiments.demo import DemoError, load_scenario, run_demo

REPOSITORY = Path(__file__).resolve().parents[2]


def test_the_declared_scenario_reproduces_its_recorded_digest() -> None:
    """The phase's runnability claim: one command, the declared window, the recorded digest.

    The digest was observed once and written into the scenario file, so a change to the kernel shows
    up here rather than as a silently different demonstration. Nothing is persisted.
    """
    outcome = run_demo(output_root=None)
    assert outcome.reproduced, outcome.details
    assert outcome.simulation_digest == outcome.scenario.expected.simulation_digest
    assert outcome.event_count == outcome.scenario.expected.event_count
    assert outcome.tick_count == outcome.scenario.expected.tick_count


def test_the_scenario_declares_a_window_and_a_sandbox_the_kernel_accepts() -> None:
    scenario = load_scenario()
    assert scenario.ticks == scenario.expected.tick_count
    assert scenario.ticks > scenario.warmup_ticks
    assert scenario.sandbox.dataset in {"toy", "medium"}
    config = scenario.config()
    assert (config.root_seed, config.tick_count, config.warmup_ticks) == (
        scenario.seed,
        scenario.ticks,
        scenario.warmup_ticks,
    )
    assert config.llm_enabled is False


def test_a_missing_scenario_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(DemoError, match="is missing"):
        load_scenario(tmp_path / "absent.yaml")


def test_a_scenario_from_another_schema_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    """A demo that silently ignores a field is not a demonstration of anything."""
    source = tmp_path / "demo.yaml"
    document = yaml.safe_load((REPOSITORY / "data/scenarios/demo.yaml").read_text(encoding="utf-8"))
    document["schema_version"] = "demo-scenario-v2"
    source.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(DemoError, match="schema"):
        load_scenario(source)


def test_a_changed_field_is_reported_as_a_non_reproduction(tmp_path: Path) -> None:
    """A digest that no longer matches is a failure with a reason, not a warning."""
    source = tmp_path / "demo.yaml"
    document = yaml.safe_load((REPOSITORY / "data/scenarios/demo.yaml").read_text(encoding="utf-8"))
    document["expected"]["event_count"] = int(document["expected"]["event_count"]) + 1
    source.write_text(yaml.safe_dump(document), encoding="utf-8")
    outcome = run_demo(source, output_root=None)
    assert not outcome.reproduced
    assert any("event count" in detail for detail in outcome.details)
