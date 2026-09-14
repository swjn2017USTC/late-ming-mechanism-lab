"""The frozen protocol: what it declares, and what it refuses.

The protocol is only a protocol if a later report cannot quietly read a different one. These tests
hold the file to its own shape (nine outcomes over seven dimensions, windows that tile the run, a
comparison level the record can support) and hold the identity to its content, because the batch
check that refuses a mismatched digest is only as good as the digest's determinism.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from late_ming_lab.protocol.schema import (
    PROTOCOL_PATH,
    ProtocolError,
    ValidationProtocol,
    load_protocol,
)

EXPECTED_DIMENSIONS = (
    "fiscal",
    "relief",
    "military_supply",
    "migration",
    "market",
    "livelihood",
    "armed_concentration",
)


@pytest.fixture(scope="module")
def protocol() -> ValidationProtocol:
    return load_protocol(".")


def test_the_protocol_loads_frozen_with_a_version(protocol: ValidationProtocol) -> None:
    assert protocol.status == "frozen"
    assert protocol.version
    assert protocol.run_ticks == 240


def test_the_primary_vector_covers_every_dimension_the_phase_names(
    protocol: ValidationProtocol,
) -> None:
    """A dimension the phase names and the protocol omits would be a gap in the headline vector."""
    assert protocol.dimensions == EXPECTED_DIMENSIONS
    assert len(protocol.primary_outcomes) >= len(EXPECTED_DIMENSIONS)


def test_no_outcome_is_an_unreadable_name_or_an_invented_quantity(
    protocol: ValidationProtocol,
) -> None:
    for outcome in protocol.primary_outcomes:
        assert outcome.measurements, outcome.id
        assert outcome.minimum_substantive_effect > 0.0
        assert outcome.definition.strip()


def test_breakdown_is_derived_and_never_primary(protocol: ValidationProtocol) -> None:
    """The V1 headline is a derived reading: that is the point of the phase, so it is pinned."""
    assert "breakdown" not in {outcome.id for outcome in protocol.primary_outcomes}
    assert "breakdown" in {reading.id for reading in protocol.derived_readings}


def test_the_scoring_windows_tile_the_run_exactly(protocol: ValidationProtocol) -> None:
    scoring = sorted(
        (window for window in protocol.windows if window.role == "scoring"),
        key=lambda window: window.start_tick,
    )
    assert scoring[0].start_tick == 0
    assert scoring[-1].end_tick == protocol.run_ticks - 1
    for earlier, later in itertools.pairwise(scoring):
        assert later.start_tick == earlier.end_tick + 1


def test_a_window_that_overlaps_another_scoring_window_is_refused() -> None:
    payload = _payload()
    payload["windows"].append(
        {
            "id": "overlap",
            "role": "scoring",
            "start_tick": 100,
            "end_tick": 150,
            "note": "an overlapping scoring window",
        }
    )
    with pytest.raises(ValidationError, match="overlap"):
        ValidationProtocol.model_validate(payload)


def test_a_scoring_window_that_leaves_a_gap_is_refused() -> None:
    payload = _payload()
    payload["windows"] = [window for window in payload["windows"] if window["id"] != "hold-out"]
    with pytest.raises(ValidationError, match=r"gap|end"):
        ValidationProtocol.model_validate(payload)


def test_an_outcome_claiming_more_than_the_record_supports_is_refused() -> None:
    """The ladder is closed: a report cannot invent a rung above what a source can carry."""
    payload = _payload()
    payload["primary_outcomes"][0]["historical_comparison"] = "exact"
    with pytest.raises(ValidationError, match="historical_comparison"):
        ValidationProtocol.model_validate(payload)


def test_an_outcome_with_no_measurement_is_refused() -> None:
    payload = _payload()
    payload["primary_outcomes"][0]["measurements"] = []
    with pytest.raises(ValidationError):
        ValidationProtocol.model_validate(payload)


def test_a_draft_protocol_is_refused_by_the_loader(tmp_path: Path) -> None:
    """A batch may not be scored against a draft: an unfrozen definition is not a definition."""
    payload = _payload()
    payload["status"] = "draft"
    path = tmp_path / PROTOCOL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ProtocolError, match="draft"):
        load_protocol(tmp_path)


def test_a_protocol_of_another_schema_is_refused(tmp_path: Path) -> None:
    payload = _payload()
    payload["schema_version"] = "validation-protocol-v3"
    path = tmp_path / PROTOCOL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ProtocolError, match="schema"):
        load_protocol(tmp_path)


def test_the_digest_follows_the_content_and_not_the_clock(protocol: ValidationProtocol) -> None:
    """Two loads agree, and an edit changes the identity: the batch check rests on this."""
    same = load_protocol(".")
    assert same.digest() == protocol.digest()

    changed = _payload()
    changed["primary_outcomes"][0]["minimum_substantive_effect"] = 0.5
    edited = ValidationProtocol.model_validate(changed)
    assert edited.digest() != protocol.digest()


def test_the_protocol_declares_which_readings_a_threshold_enters(
    protocol: ValidationProtocol,
) -> None:
    assert protocol.threshold_dependence() == ("breakdown",)


def _payload() -> dict[str, Any]:
    """A fresh copy of the frozen file's content, for a test to damage one field at a time.

    Through JSON so nothing in the returned mapping is shared with the parsed original: a test that
    mutated a nested dict it borrowed would be editing the next test's protocol.
    """
    raw = yaml.safe_load(Path(PROTOCOL_PATH).read_text(encoding="utf-8"))
    loaded: dict[str, Any] = json.loads(json.dumps(raw))
    return loaded
