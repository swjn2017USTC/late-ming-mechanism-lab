"""Simulation configuration: the complete deterministic input contract of a run.

A :class:`SimulationConfig` holds no history. It fixes the time window, the root seed, the
policy identifier and the runtime-LLM switch. Its content hash, together with the code
revision, is the identity of a run: same config + same seed implies the same output
(RULES 14, 15).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from late_ming_lab.core.hashing import canonical_json, hash_text

#: Fixed regression seed for the repeatable smoke run (RULES 15).
DEFAULT_ROOT_SEED: Final[int] = 20260912

#: Highest accepted root seed: 64-bit, so seeds stay portable across JSON, Parquet and DuckDB.
MAX_ROOT_SEED: Final[int] = 2**63 - 1

#: The only runtime institutional-policy model permitted (RULES 8). Disabled by default.
#: The runtime institutional policy's model id: declared by operator decision in
#: `docs/adr/0003-runtime-model-amendment.md`. It is deliberately *not* recorded as a verification
#: against the account's `/v1/models`, and reports must cite the ADR rather than a confirmation.
RUNTIME_LLM_MODEL_ID: Final[str] = "deepseek-flash"

DEFAULT_SCENARIO_ID: Final[str] = "kernel-smoke"
DEFAULT_POLICY_ID: Final[str] = "noop-v1"

_IDENTIFIER_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"


class SimulationConfig(BaseModel):
    """Validated, frozen configuration of one simulation run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["simulation-config-v1"] = "simulation-config-v1"
    scenario_id: str = Field(
        default=DEFAULT_SCENARIO_ID, pattern=_IDENTIFIER_PATTERN, max_length=64
    )
    policy_id: str = Field(default=DEFAULT_POLICY_ID, pattern=_IDENTIFIER_PATTERN, max_length=64)

    start_year: int = Field(default=1625, ge=1000, le=9999)
    start_month: int = Field(default=1, ge=1, le=12)
    tick_count: int = Field(default=240, ge=1, le=1200, description="Monthly ticks in the window.")
    warmup_ticks: int = Field(default=24, ge=0, description="Leading ticks treated as baseline.")

    root_seed: int = Field(default=DEFAULT_ROOT_SEED, ge=0, le=MAX_ROOT_SEED)

    llm_enabled: bool = False
    llm_model_id: str | None = None
    llm_prompt_version: str | None = None

    @model_validator(mode="after")
    def _validate_consistency(self) -> SimulationConfig:
        if self.warmup_ticks > self.tick_count:
            raise ValueError(
                f"warmup_ticks ({self.warmup_ticks}) must not exceed tick_count ({self.tick_count})"
            )
        if self.llm_enabled:
            if self.llm_model_id != RUNTIME_LLM_MODEL_ID:
                raise ValueError(
                    f"llm_enabled requires llm_model_id == {RUNTIME_LLM_MODEL_ID!r}; "
                    f"got {self.llm_model_id!r} (no fallback model is permitted)"
                )
            if self.llm_prompt_version is None:
                raise ValueError("llm_enabled requires an explicit llm_prompt_version")
        elif self.llm_model_id is not None or self.llm_prompt_version is not None:
            raise ValueError(
                "llm_model_id/llm_prompt_version must stay unset while llm_enabled is false"
            )
        return self

    def content_hash(self) -> str:
        """SHA-256 over the canonical form of the whole configuration."""
        return hash_text(canonical_json(self.model_dump(mode="json")))

    def to_yaml(self) -> str:
        """Canonical YAML snapshot; round-trips through :meth:`from_yaml`."""
        return yaml.safe_dump(self.model_dump(mode="json"), sort_keys=True, allow_unicode=True)

    @classmethod
    def from_yaml(cls, text: str) -> SimulationConfig:
        payload = yaml.safe_load(text)
        if not isinstance(payload, dict):
            raise ValueError("configuration document must be a YAML mapping")
        return cls.model_validate(payload)

    @classmethod
    def from_file(cls, path: str | Path) -> SimulationConfig:
        return cls.from_yaml(Path(path).read_text(encoding="utf-8"))

    def with_overrides(self, **changes: Any) -> SimulationConfig:
        """Return a re-validated copy with ``changes`` applied.

        Re-validation matters: overrides must not be able to produce a configuration that
        the constructor would have rejected.
        """
        payload = {**self.model_dump(mode="json"), **changes}
        return type(self).model_validate(payload)
