"""Manifest and summary contract: provenance identity, round-trip, digest scope."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from late_ming_lab import __version__
from late_ming_lab.core.clock import Clock
from late_ming_lab.core.config import RUNTIME_LLM_MODEL_ID, SimulationConfig
from late_ming_lab.core.manifest import RunManifest, RunSummary, make_run_id
from late_ming_lab.core.rng import RngStreams, derive_stream_seeds
from late_ming_lab.core.tick import TICK_ORDER_VERSION
from late_ming_lab.evidence.provenance import Provenance, git_provenance

CREATED_AT = datetime(2026, 9, 12, 8, 0, 0, tzinfo=UTC)


def _manifest(config: SimulationConfig | None = None, **manifest_fields: object) -> RunManifest:
    config = config or SimulationConfig(tick_count=12, warmup_ticks=2)
    manifest = RunManifest.for_run(
        config=config,
        clock=Clock.from_config(config),
        rng=RngStreams(config.root_seed),
        provenance=Provenance(git_sha="a" * 40, git_dirty=False),
        created_at=CREATED_AT,
    )
    if not manifest_fields:
        return manifest
    return RunManifest.model_validate({**manifest.model_dump(mode="json"), **manifest_fields})


def test_manifest_records_the_replay_key() -> None:
    config = SimulationConfig(tick_count=12, warmup_ticks=2, policy_id="noop-v1")
    manifest = _manifest(config)

    assert manifest.engine_version == __version__
    assert manifest.git_sha == "a" * 40
    assert manifest.git_dirty is False
    assert manifest.config_hash == config.content_hash()
    assert manifest.root_seed == config.root_seed
    assert manifest.subsystem_seeds == derive_stream_seeds(config.root_seed)
    assert manifest.scenario_id == config.scenario_id
    assert manifest.policy_id == config.policy_id
    assert manifest.tick_count == 12
    assert manifest.tick_order_version == TICK_ORDER_VERSION
    assert manifest.llm_enabled is False
    assert manifest.llm_model_id is None
    assert manifest.parameter_hash is None


def test_manifest_carries_the_llm_switch_from_the_config() -> None:
    config = SimulationConfig.model_validate(
        {
            "tick_count": 12,
            "warmup_ticks": 2,
            "llm_enabled": True,
            "llm_model_id": RUNTIME_LLM_MODEL_ID,
            "llm_prompt_version": "institutional-v1",
        }
    )

    manifest = _manifest(config)

    assert (manifest.llm_enabled, manifest.llm_model_id, manifest.llm_prompt_version) == (
        True,
        RUNTIME_LLM_MODEL_ID,
        "institutional-v1",
    )


def test_manifest_round_trips_through_json() -> None:
    manifest = _manifest()

    restored = RunManifest.from_json(manifest.to_json())

    assert restored == manifest
    assert restored.deterministic_digest() == manifest.deterministic_digest()


def test_run_id_is_derived_from_scenario_seed_and_config_hash() -> None:
    config = SimulationConfig(tick_count=12, warmup_ticks=2)
    run_id = make_run_id(config)

    assert run_id == f"{config.scenario_id}-{config.root_seed}-{config.content_hash()[:12]}"
    assert make_run_id(config) == run_id
    assert make_run_id(config, label="dev") == f"{run_id}-dev"
    assert make_run_id(SimulationConfig(tick_count=13, warmup_ticks=2)) != run_id


def test_deterministic_digest_ignores_wall_clock_fields() -> None:
    manifest = _manifest()

    later = manifest.model_copy(update={"created_at": CREATED_AT + timedelta(hours=3)})

    assert later.deterministic_digest() == manifest.deterministic_digest()
    assert "created_at" not in manifest.deterministic_payload()


def test_deterministic_digest_reacts_to_provenance() -> None:
    manifest = _manifest()
    changed = [
        manifest.model_copy(update={"git_sha": "b" * 40}),
        manifest.model_copy(update={"git_dirty": True}),
        manifest.model_copy(update={"policy_id": "other-policy-v1"}),
        manifest.model_copy(update={"config_hash": "0" * 64}),
        manifest.model_copy(update={"root_seed": manifest.root_seed + 1}),
    ]

    digests = {manifest.deterministic_digest(), *(item.deterministic_digest() for item in changed)}

    assert len(digests) == len(changed) + 1


def test_manifest_rejects_a_malformed_run_id() -> None:
    with pytest.raises(ValidationError):
        _manifest(run_id="Kernel Smoke")


def test_provenance_is_observed_from_the_repository() -> None:
    provenance = git_provenance()

    assert provenance.git_sha is not None
    assert len(provenance.git_sha) == 40
    assert provenance.git_dirty in (True, False)


def test_summary_round_trips_and_pins_the_digest_format() -> None:
    manifest = _manifest()
    summary = RunSummary(
        run_id=manifest.run_id,
        tick_count=12,
        warmup_ticks=2,
        event_count=12,
        simulation_digest="c" * 64,
        created_at=CREATED_AT,
        duration_seconds=0.25,
    )

    assert RunSummary.from_json(summary.to_json()) == summary
    with pytest.raises(ValidationError):
        RunSummary.model_validate({**summary.model_dump(), "simulation_digest": "nope"})
