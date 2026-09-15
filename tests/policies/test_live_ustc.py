"""The live USTC tests: opt-in, and fail-closed when the runtime model is not confirmed.

Nothing here runs in the default suite — `pyproject.toml` excludes the marker — and nothing here
runs at all until the runtime model id is declared (ADR 0003) and the switch is on. When it is not,
the first test fails with the refusal rather than skipping: a silent skip would read as "the live
layer is fine, it just did not run today".

The environment is read through the policy's own reader, so the uncommitted ``.env`` the operator
edits is what drives this suite; an exported variable still wins over it.

```bash
# .env: base url, key, the declared model id, USTC_LLM_ENABLED=1
uv run pytest -m live_ustc
```
"""

from __future__ import annotations

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
    """The runtime settings, or a failure that says exactly what is missing.

    Read through `_process_environment`, the reader the policy itself uses, so this suite sees the
    same environment the layer does — `.env` underneath, the process on top.
    """
    from late_ming_lab.policies.ustc_v41 import _process_environment

    return load_settings(environ=_process_environment(Path(__file__).resolve().parents[2]))


def test_the_configured_model_is_the_confirmed_runtime_model() -> None:
    """The gate itself, against the real environment. Refused rather than skipped when it fails."""
    from late_ming_lab.policies.ustc_v41 import _process_environment

    configured = _process_environment(Path(__file__).resolve().parents[2]).get(ENV_MODEL, "")
    if configured not in CONFIRMED_MODEL_IDS:
        with pytest.raises(ModelNotConfirmedError):
            _live_settings()
        pytest.fail(
            f"{ENV_MODEL}={configured!r} is not the declared runtime model; declared ids are "
            f"{CONFIRMED_MODEL_IDS}. This fails closed on purpose: set {ENV_MODEL} to the id ADR "
            f"0003 declares and {ENV_ENABLED}=1 in the uncommitted .env."
        )
    settings = _live_settings()
    assert settings.model_id in CONFIRMED_MODEL_IDS
    assert settings.enabled


def test_one_live_decision_round_trips_through_a_recorded_fixture() -> None:
    """The phase's recording contract: a live answer becomes a fixture and replays identically."""
    from late_ming_lab.policies.ustc_v41 import _process_environment

    policy = policy_from_environment(
        environ=_process_environment(Path(__file__).resolve().parents[2])
    )
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
