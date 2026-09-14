"""The live USTC tests: opt-in, and fail-closed when the runtime model is not confirmed.

Nothing here runs in the default suite — `pyproject.toml` excludes the marker — and nothing here
runs at all until an operator has confirmed the model id against the account's ``/v1/models`` and
set ``USTC_LLM_ENABLED=1``. When it is not confirmed, the first test fails with the refusal rather
than skipping: a silent skip would read as "the live layer is fine, it just did not run today".

```bash
cp .env.example .env && chmod 600 .env      # then set the key and the confirmed model id
USTC_LLM_ENABLED=1 uv run pytest -m live_ustc
```
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from late_ming_lab.core.hashing import hash_text
from late_ming_lab.policies.base import (
    ROLE_ACTIONS,
    ActorRole,
    ModelNotConfirmedError,
    PolicyObservation,
)
from late_ming_lab.policies.recording import FixtureStore, ReplayTransport, sanitize_response
from late_ming_lab.policies.ustc_v41 import (
    CONFIRMED_MODEL_IDS,
    ENV_ENABLED,
    ENV_MODEL,
    UstcSettings,
    USTCV41Policy,
    load_settings,
    policy_from_environment,
)

pytestmark = pytest.mark.live_ustc

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "llm"


def _live_settings() -> UstcSettings:
    """The runtime settings, or a failure that says exactly what is missing."""
    return load_settings(environ=dict(os.environ))


def test_the_configured_model_is_the_confirmed_runtime_model() -> None:
    """The gate itself, against the real environment. Refused rather than skipped when it fails."""
    configured = os.environ.get(ENV_MODEL, "")
    if configured not in CONFIRMED_MODEL_IDS:
        with pytest.raises(ModelNotConfirmedError):
            _live_settings()
        pytest.fail(
            f"{ENV_MODEL}={configured!r} is not a confirmed runtime model; confirmed ids are "
            f"{CONFIRMED_MODEL_IDS}. P11 fails closed here on purpose: set {ENV_MODEL} to the id "
            f"an operator confirmed against the account's /v1/models and {ENV_ENABLED}=1."
        )
    settings = _live_settings()
    assert settings.model_id in CONFIRMED_MODEL_IDS
    assert settings.enabled


def test_one_live_decision_round_trips_through_a_recorded_fixture() -> None:
    """The phase's recording contract: a live answer becomes a fixture and replays identically."""
    policy = policy_from_environment(environ=dict(os.environ))
    observation = PolicyObservation(
        actor="GOV-L1",
        role=ActorRole.COUNTY,
        region="R2",
        tick=48,
        measures=(
            ("armed_share_of_adults", 0.006),
            ("largest_band_share", 0.33),
            ("out_migration_share", 0.004),
            ("receipts_over_quota", 0.27),
            ("tax_arrears_months", 7.2),
            ("unmet_need_share", 0.18),
        ),
        action_space=ROLE_ACTIONS[ActorRole.COUNTY],
    )
    decision = policy.choose_action(observation, observation.action_space)
    record = policy.last_record()

    assert decision.action in observation.action_space
    assert 0.0 <= decision.intensity <= 1.0
    assert record.model_id == policy.model_id
    assert record.prompt_hash is not None and record.response_hash is not None

    # Record what the live model said, then replay it with no network at all.
    from late_ming_lab.policies.base import render_prompt

    prompt = render_prompt(observation)
    exchange = sanitize_response(
        {
            "model": record.model_id,
            "choices": [{"message": {"role": "assistant", "content": decision.model_dump_json()}}],
        },
        model_id=policy.model_id,
        prompt_hash=hash_text(prompt),
        request_hash=record.prompt_hash or "",
        provenance="live",
        endpoint_model_id=record.model_id or "",
        note="recorded by tests/policies/test_live_ustc.py",
    )
    store = FixtureStore(FIXTURE_DIR)
    store.record(exchange)
    replayed = USTCV41Policy(
        transport=ReplayTransport(store), settings=_live_settings()
    ).choose_action(observation, observation.action_space)

    assert replayed.action is decision.action
    assert replayed.intensity == pytest.approx(decision.intensity)
