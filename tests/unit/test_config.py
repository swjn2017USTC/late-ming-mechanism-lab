"""Configuration validation: the deterministic input contract must reject bad input."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from late_ming_lab.core.config import (
    DEFAULT_POLICY_ID,
    DEFAULT_ROOT_SEED,
    DEFAULT_SCENARIO_ID,
    RUNTIME_LLM_MODEL_ID,
    SimulationConfig,
)


def test_defaults_fix_the_documented_window_and_seed() -> None:
    config = SimulationConfig()

    assert (config.start_year, config.start_month, config.tick_count) == (1625, 1, 240)
    assert config.warmup_ticks == 24
    assert config.root_seed == DEFAULT_ROOT_SEED
    assert config.scenario_id == DEFAULT_SCENARIO_ID
    assert config.policy_id == DEFAULT_POLICY_ID
    assert config.llm_enabled is False
    assert config.llm_model_id is None
    assert config.llm_prompt_version is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"start_month": 0},
        {"start_month": 13},
        {"start_year": 0},
        {"tick_count": 0},
        {"warmup_ticks": 241},
        {"root_seed": -1},
        {"scenario_id": "Kernel Smoke"},
        {"policy_id": ""},
    ],
)
def test_out_of_contract_values_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SimulationConfig.model_validate(overrides)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SimulationConfig.model_validate({"mystery_option": 1})


def test_configuration_is_frozen() -> None:
    config = SimulationConfig()

    with pytest.raises(ValidationError):
        config.root_seed = DEFAULT_ROOT_SEED + 1


def test_warmup_must_fit_inside_the_window() -> None:
    with pytest.raises(ValidationError):
        SimulationConfig.model_validate({"tick_count": 10, "warmup_ticks": 11})


def test_runtime_llm_accepts_only_the_single_permitted_model() -> None:
    with pytest.raises(ValidationError):
        SimulationConfig.model_validate(
            {"llm_enabled": True, "llm_model_id": "another-model", "llm_prompt_version": "v1"}
        )
    with pytest.raises(ValidationError):
        SimulationConfig.model_validate({"llm_enabled": True, "llm_model_id": RUNTIME_LLM_MODEL_ID})

    enabled = SimulationConfig.model_validate(
        {
            "llm_enabled": True,
            "llm_model_id": RUNTIME_LLM_MODEL_ID,
            "llm_prompt_version": "institutional-v1",
        }
    )

    assert enabled.llm_enabled is True


def test_llm_identifiers_must_stay_unset_while_disabled() -> None:
    with pytest.raises(ValidationError):
        SimulationConfig.model_validate({"llm_prompt_version": "institutional-v1"})


def test_content_hash_identifies_the_configuration() -> None:
    assert SimulationConfig().content_hash() == SimulationConfig().content_hash()
    assert (
        SimulationConfig().content_hash()
        != SimulationConfig(root_seed=DEFAULT_ROOT_SEED + 1).content_hash()
    )
    assert SimulationConfig().content_hash() != SimulationConfig(tick_count=48).content_hash()


def test_yaml_snapshot_is_canonical_and_round_trips(tmp_path: Path) -> None:
    config = SimulationConfig.model_validate({"tick_count": 12, "warmup_ticks": 2, "root_seed": 7})
    snapshot = tmp_path / "config.yaml"
    snapshot.write_text(config.to_yaml(), encoding="utf-8")

    assert SimulationConfig.from_file(snapshot) == config
    assert config.to_yaml() == SimulationConfig.from_yaml(config.to_yaml()).to_yaml()


def test_non_mapping_documents_are_rejected() -> None:
    with pytest.raises(ValueError, match="mapping"):
        SimulationConfig.from_yaml("- not\n- a\n- mapping\n")


def test_overrides_are_revalidated() -> None:
    config = SimulationConfig()

    assert config.with_overrides(root_seed=5).root_seed == 5
    with pytest.raises(ValidationError):
        config.with_overrides(tick_count=0)
    with pytest.raises(ValidationError):
        config.with_overrides(warmup_ticks=999)
