"""Run provenance and run summary.

:class:`RunManifest` answers "what code, configuration, seed and policy produced this
output?"; :class:`RunSummary` answers "what came out, and how long did it take?". The
manifest is the replay key of a run. Its deterministic digest deliberately excludes
wall-clock fields, so two runs of the same code, config and seed share an identity while
still recording when each of them happened.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from late_ming_lab import __version__
from late_ming_lab.core.clock import Clock
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.hashing import canonical_json, hash_text
from late_ming_lab.core.rng import RngStreams
from late_ming_lab.core.tick import TICK_ORDER_VERSION
from late_ming_lab.evidence.provenance import Provenance

RUN_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"
_HASH_PATTERN = r"^[0-9a-f]{64}$"


def make_run_id(config: SimulationConfig, label: str | None = None) -> str:
    """Deterministic run identity: scenario, root seed and configuration hash.

    Repeating the same configuration and seed therefore writes to the same directory and
    reproduces the same artifacts instead of accumulating near-duplicates.
    """
    run_id = f"{config.scenario_id}-{config.root_seed}-{config.content_hash()[:12]}"
    return run_id if label is None else f"{run_id}-{label}"


class RunManifest(BaseModel):
    """Replay key of one run: code, configuration, seed, policy and LLM switch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["run-manifest-v1"] = "run-manifest-v1"
    run_id: str = Field(pattern=RUN_ID_PATTERN, max_length=128)
    engine_version: str
    git_sha: str | None = None
    git_dirty: bool | None = None
    config_hash: str = Field(pattern=_HASH_PATTERN)
    parameter_hash: str | None = Field(
        default=None,
        pattern=_HASH_PATTERN,
        description="Parameter-registry hash; unset until the evidence registry exists (P08).",
    )
    root_seed: int = Field(ge=0)
    subsystem_seeds: dict[str, int]
    scenario_id: str
    policy_id: str
    tick_count: int = Field(ge=1)
    tick_order_version: str
    llm_enabled: bool
    llm_model_id: str | None = None
    llm_prompt_version: str | None = None
    created_at: datetime

    @classmethod
    def for_run(
        cls,
        *,
        config: SimulationConfig,
        clock: Clock,
        rng: RngStreams,
        provenance: Provenance,
        created_at: datetime,
        run_label: str | None = None,
    ) -> RunManifest:
        return cls(
            run_id=make_run_id(config, run_label),
            engine_version=__version__,
            git_sha=provenance.git_sha,
            git_dirty=provenance.git_dirty,
            config_hash=config.content_hash(),
            root_seed=config.root_seed,
            subsystem_seeds=dict(rng.subsystem_seeds),
            scenario_id=config.scenario_id,
            policy_id=config.policy_id,
            tick_count=clock.tick_count,
            tick_order_version=TICK_ORDER_VERSION,
            llm_enabled=config.llm_enabled,
            llm_model_id=config.llm_model_id,
            llm_prompt_version=config.llm_prompt_version,
            created_at=created_at,
        )

    def deterministic_payload(self) -> dict[str, Any]:
        """Manifest content that must be identical for identical code, config and seed."""
        payload = self.model_dump(mode="json")
        payload.pop("created_at")
        return payload

    def deterministic_digest(self) -> str:
        """SHA-256 of :meth:`deterministic_payload`."""
        return hash_text(canonical_json(self.deterministic_payload()))

    def to_json(self) -> str:
        return canonical_json(self.model_dump(mode="json"))

    @classmethod
    def from_json(cls, text: str) -> RunManifest:
        return cls.model_validate_json(text)


class RunSummary(BaseModel):
    """Result summary of one run.

    ``created_at`` and ``duration_seconds`` are wall-clock diagnostics and are deliberately
    outside every reproducibility claim; :attr:`simulation_digest` is the part that must
    repeat exactly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["run-summary-v1"] = "run-summary-v1"
    run_id: str
    tick_count: int = Field(ge=1)
    warmup_ticks: int = Field(ge=0)
    event_count: int = Field(ge=0)
    simulation_digest: str = Field(pattern=_HASH_PATTERN)
    created_at: datetime
    duration_seconds: float = Field(ge=0.0)

    def to_json(self) -> str:
        return canonical_json(self.model_dump(mode="json"))

    @classmethod
    def from_json(cls, text: str) -> RunSummary:
        return cls.model_validate_json(text)
