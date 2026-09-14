"""Replay: the decision layer driven by recorded fixtures, with no network and no credential.

P11 recorded what the runtime layer *would* send and receive, and closed the live model by default.
This module is the other half of that design, and the one the HPC rules need: a batch that wants
model-backed decisions records them once in a networked environment and replays them on the cluster,
where there is no key, no endpoint and no route out.

Three properties are the module's reason for existing, and each is enforced rather than described:

- **No credential is read.** The settings here are declared: the confirmed model id, no key, no
  environment lookup. A replay run cannot leak a key it never had.
- **A miss fails closed.** A prompt with no recorded answer raises rather than being answered by a
  fallback model or a default action; the error names the prompt hash so the missing decision can be
  recorded deliberately.
- **The run is an artifact.** Events, decisions, refusals and the fixture identity are written
  together, so a replayed batch is auditable and reproducible like any other run.

Recording is not this module's job: `policies.recording.sanitize_response` turns a live answer
into a fixture, and that pass runs where the network is.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import SecretStr

from late_ming_lab.policies.recording import FixtureStore, ReplayTransport
from late_ming_lab.policies.ustc_v41 import CONFIRMED_MODEL_IDS, UstcSettings

#: The window a replay run uses unless a caller declares another: the institutional smoke's own.
REPLAY_TICKS: Final[int] = 48
REPLAY_WARMUP_TICKS: Final[int] = 8
REPLAY_SEED: Final[int] = 20_260_915

#: Where a replay run writes, relative to the repository root.
REPLAY_ROOT: Final[str] = "outputs/replay"

#: The files one replay run leaves behind.
EVENTS_FILE: Final[str] = "events.parquet"
DECISIONS_FILE: Final[str] = "decisions.parquet"
REFUSALS_FILE: Final[str] = "refusals.parquet"
MANIFEST_FILE: Final[str] = "manifest.json"


class ReplayError(RuntimeError):
    """Raised when a replay run cannot be made from the fixtures it was given."""


@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    """What one replay produced, and where it was written."""

    run_id: str
    directory: Path
    decisions: int
    refusals: int
    fixtures: int
    fixture_digest: str
    seed: int
    ticks: int


def replay_settings() -> UstcSettings:
    """The declared settings a replay runs under: the confirmed id, no credential, no lookup.

    The gate this layer exists to enforce is about *calling* a model. A replay calls none, so the
    settings declare no key rather than reading one, and nothing in this module touches the
    environment or the credential file.
    """
    return UstcSettings(
        base_url="",
        model_id=CONFIRMED_MODEL_IDS[0],
        enabled=True,
        timeout_seconds=0.0,
        api_key=SecretStr(""),
    )


def fixture_digest(store: FixtureStore) -> str:
    """A digest over the recorded exchanges, so a replay names the corpus it replayed."""
    digest = hashlib.sha256()
    for exchange in sorted(store.load_all(), key=lambda item: item.prompt_hash):
        digest.update(exchange.to_json().encode("utf-8"))
    return digest.hexdigest()


def replay_run(
    *,
    fixtures: str | Path,
    output_root: str | Path = REPLAY_ROOT,
    ticks: int = REPLAY_TICKS,
    warmup_ticks: int = REPLAY_WARMUP_TICKS,
    seed: int = REPLAY_SEED,
) -> ReplayOutcome:
    """Run the decision layer from recorded fixtures and write the run's artifacts."""
    from late_ming_lab.experiments.institutional_smoke import run_institutional

    store = FixtureStore(fixtures)
    exchanges = store.load_all()
    if not exchanges:
        raise ReplayError(
            f"no recorded fixtures under {Path(fixtures)}: a replay run needs a recording pass in "
            "a networked environment first, because this layer never answers a prompt it has no "
            "recorded exchange for"
        )
    transport = ReplayTransport(store)
    run = run_institutional(
        policy="replay",
        transport=transport,
        settings=replay_settings(),
        ticks=ticks,
        warmup_ticks=warmup_ticks,
        seed=seed,
    )
    directory = Path(output_root) / run.run_id
    directory.mkdir(parents=True, exist_ok=True)
    run.events.write_parquet(directory / EVENTS_FILE)
    run.traces.write_parquet(directory / DECISIONS_FILE)
    run.refusals.write_parquet(directory / REFUSALS_FILE)
    digest = fixture_digest(store)
    manifest = {
        "run_id": run.run_id,
        "policy": run.policy_name,
        "policy_id": run.policy,
        "config_hash": run.config_hash,
        "seed": seed,
        "ticks": ticks,
        "warmup_ticks": warmup_ticks,
        "events": run.events.height,
        "decisions": run.traces.height,
        "refusals": run.refusals.height,
        "fixtures": len(exchanges),
        "fixture_digest": digest,
        "model_id": CONFIRMED_MODEL_IDS[0],
        "runtime_llm_called": False,
        "note": (
            "replayed from recorded fixtures: no network call was made and no credential was read"
        ),
    }
    (directory / MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return ReplayOutcome(
        run_id=run.run_id,
        directory=directory,
        decisions=run.traces.height,
        refusals=run.refusals.height,
        fixtures=len(exchanges),
        fixture_digest=digest,
        seed=seed,
        ticks=ticks,
    )
