"""The model-comparison register: what it pre-registers, and what it refuses to pre-register.

The register is the phase's claim that the V2-P04 and V2-P05 comparisons were named before their
results existed. These tests read the written file against the frozen protocol, and build bad
payloads - one change at a time, from the register's own payload - for every refusal the loader
promises.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from pydantic import ValidationError

from late_ming_lab.protocol.comparison import (
    REGISTER_PATH,
    REGISTER_SCHEMA_VERSION,
    REQUIRED_COVERAGE,
    ComparisonError,
    ComparisonRegister,
    by_id,
    entries_for,
    load_register,
)
from late_ming_lab.protocol.schema import ValidationProtocol, load_protocol

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def protocol() -> ValidationProtocol:
    return load_protocol(REPO_ROOT)


@pytest.fixture(scope="module")
def payload() -> dict[str, Any]:
    """The register's own payload, so a test changes exactly one thing about it."""
    raw = yaml.safe_load((REPO_ROOT / REGISTER_PATH).read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return cast("dict[str, Any]", json.loads(json.dumps(raw)))


@pytest.fixture(scope="module")
def register(protocol: ValidationProtocol) -> ComparisonRegister:
    return load_register(REPO_ROOT, protocol=protocol)


def _copy(payload: dict[str, Any]) -> dict[str, Any]:
    """A mutable copy: the fixture is module-scoped, so a test never edits what it read."""
    return cast("dict[str, Any]", json.loads(json.dumps(payload)))


def _written(tmp_path: Path, payload: dict[str, Any]) -> Path:
    """Write a payload where the loader reads it, under the test's own root."""
    path = tmp_path / REGISTER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return tmp_path


def test_the_register_loads_and_covers_the_declared_themes(register: ComparisonRegister) -> None:
    assert register.schema_version == REGISTER_SCHEMA_VERSION
    declared = {entry.id for entry in register.entries}
    assert set(REQUIRED_COVERAGE) <= declared
    assert len(register.entries) >= len(REQUIRED_COVERAGE)


def test_every_discriminating_observable_is_a_primary_outcome(
    register: ComparisonRegister, protocol: ValidationProtocol
) -> None:
    known = {outcome.id for outcome in protocol.primary_outcomes}
    for entry in register.entries:
        unknown = sorted(set(entry.discriminating_observables) - known)
        assert not unknown, f"{entry.id} reads {unknown}, which the protocol does not score"


def test_both_phases_own_entries_and_are_addressable(register: ComparisonRegister) -> None:
    for phase in ("V2-P04", "V2-P05"):
        owned = entries_for(register, phase)
        assert owned, f"no entry pre-registered for {phase}"
        first = owned[0]
        assert by_id(register, first.id) is first
        assert all(entry.phase == phase for entry in owned)
    with pytest.raises(KeyError):
        by_id(register, "no-such-entry")


def test_an_observable_the_protocol_does_not_have_is_refused(
    tmp_path: Path, payload: dict[str, Any], protocol: ValidationProtocol
) -> None:
    patched = _copy(payload)
    patched["entries"][0]["discriminating_observables"] = ["market_dispersion"]
    with pytest.raises(ComparisonError, match="market_dispersion"):
        load_register(_written(tmp_path, patched), protocol=protocol)


def test_a_single_candidate_structure_is_refused(payload: dict[str, Any]) -> None:
    patched = _copy(payload)
    patched["entries"][0]["candidate_structures"] = [
        patched["entries"][0]["candidate_structures"][0]
    ]
    with pytest.raises(ValidationError, match="candidate_structures"):
        ComparisonRegister.model_validate(patched)


def test_an_empty_falsifier_is_refused(payload: dict[str, Any]) -> None:
    patched = _copy(payload)
    patched["entries"][1]["falsifier"] = ""
    with pytest.raises(ValidationError, match="falsifier"):
        ComparisonRegister.model_validate(patched)


def test_an_entry_that_defers_its_discriminator_is_refused(payload: dict[str, Any]) -> None:
    patched = _copy(payload)
    patched["entries"][5]["falsifier"] = "More research is needed before a falsifier can be named."
    with pytest.raises(ValidationError, match="defers the comparison"):
        ComparisonRegister.model_validate(patched)


def test_a_missing_theme_is_refused(payload: dict[str, Any]) -> None:
    patched = _copy(payload)
    patched["entries"] = [
        entry for entry in patched["entries"] if entry["id"] != "band-consolidation-chain"
    ]
    with pytest.raises(ValidationError, match="band-consolidation-chain"):
        ComparisonRegister.model_validate(patched)


def test_a_duplicate_id_is_refused(payload: dict[str, Any]) -> None:
    patched = _copy(payload)
    patched["entries"].append(patched["entries"][0])
    with pytest.raises(ValidationError, match="unique"):
        ComparisonRegister.model_validate(patched)


def test_a_phase_other_than_the_two_declared_is_refused(payload: dict[str, Any]) -> None:
    patched = _copy(payload)
    patched["entries"][0]["phase"] = "V2-P06"
    with pytest.raises(ValidationError, match="V2-P06"):
        ComparisonRegister.model_validate(patched)
