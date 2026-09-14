"""The mechanism readings: their boundaries, their falsifiers and their refusals.

Each reading is a declared rule over the event log, so each test here builds the smallest log the
rule can read and checks both sides of its line — present just past it, absent just before. The
point is that a verdict is falsifiable: every reading carries the case that would make it false,
and these tests drive that case.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from late_ming_lab.analysis.mechanisms import (
    MECHANISM_IDS,
    MechanismError,
    armed_band_consolidation,
    extraction_inversion,
    fiscal_military_ratchet,
    mechanism_readings,
)


def _log(rows: list[tuple[int, str, dict[str, float], str, str]]) -> pl.DataFrame:
    """An event log with the columns the readings use, built from declared rows.

    Each row carries its agent id, because two of the readings count holders: a band count without
    band identity would be a count of records, not of bands.
    """
    return pl.DataFrame(
        {
            "seq": list(range(len(rows))),
            "tick": [row[0] for row in rows],
            "event_type": [row[1] for row in rows],
            "trigger_json": [json.dumps(row[2]) for row in rows],
            "outcome": [row[3] for row in rows],
            "agent_id": [row[4] for row in rows],
        }
    )


def _extraction(
    tick: int, effort: float, pressure: float
) -> tuple[int, str, dict[str, float], str, str]:
    return (
        tick,
        "EXTRACTION_DECISION",
        {"collection_effort": effort, "pressure": pressure},
        "collected",
        "GOV-L1",
    )


def _assessment(tick: int, quota: float) -> tuple[int, str, dict[str, float], str, str]:
    return (tick, "TAX_ASSESSMENT", {"quota_tael": quota}, "assessed", "GOV-L1")


def _receipt(tick: int, receipts: float) -> tuple[int, str, dict[str, float], str, str]:
    return (tick, "TAX_RECEIPT", {"receipts_tael": receipts}, "household", "toy-sx-a")


def test_extraction_inversion_needs_effort_up_and_realisation_down() -> None:
    """Both halves are required: harder work alone is not the pattern, nor is a shortfall."""
    inverted = _log(
        [
            _extraction(0, 0.3, 0.02),
            _extraction(1, 0.3, 0.02),
            _extraction(2, 0.8, 0.04),
            _extraction(3, 0.8, 0.04),
            _assessment(0, 100.0),
            _assessment(1, 100.0),
            _assessment(2, 100.0),
            _assessment(3, 100.0),
            _receipt(0, 40.0),
            _receipt(1, 40.0),
            _receipt(2, 20.0),
            _receipt(3, 20.0),
        ]
    )
    working_well = _log(
        [
            _extraction(0, 0.3, 0.02),
            _extraction(1, 0.3, 0.02),
            _extraction(2, 0.8, 0.04),
            _extraction(3, 0.8, 0.04),
            _assessment(0, 100.0),
            _assessment(1, 100.0),
            _assessment(2, 100.0),
            _assessment(3, 100.0),
            _receipt(0, 30.0),
            _receipt(1, 30.0),
            _receipt(2, 50.0),
            _receipt(3, 50.0),
        ]
    )
    lazy_but_worse = _log(
        [
            _extraction(0, 0.8, 0.04),
            _extraction(1, 0.8, 0.04),
            _extraction(2, 0.3, 0.02),
            _extraction(3, 0.3, 0.02),
            _assessment(0, 100.0),
            _assessment(1, 100.0),
            _assessment(2, 100.0),
            _assessment(3, 100.0),
            _receipt(0, 60.0),
            _receipt(1, 60.0),
            _receipt(2, 20.0),
            _receipt(3, 20.0),
        ]
    )

    reading = extraction_inversion(inverted)
    assert reading.present and reading.strength > 0.0
    assert "effort" in reading.reading
    assert extraction_inversion(working_well).present is False
    assert extraction_inversion(lazy_but_worse).present is False


def test_the_ratchet_is_about_never_clearing_not_about_size() -> None:
    """A big stock that falls once is not a ratchet; a small one that only grows is."""
    one_way = _log(
        [
            (0, "MILITARY_STATE", {"pay_arrears_tael": 100.0}, "state", "G-1"),
            (1, "MILITARY_STATE", {"pay_arrears_tael": 150.0}, "state", "G-1"),
            (2, "MILITARY_STATE", {"pay_arrears_tael": 150.0}, "state", "G-1"),
            _assessment(0, 100.0),
        ]
    )
    cleared_once = _log(
        [
            (0, "MILITARY_STATE", {"pay_arrears_tael": 100.0}, "state", "G-1"),
            (1, "MILITARY_STATE", {"pay_arrears_tael": 900.0}, "state", "G-1"),
            (2, "MILITARY_STATE", {"pay_arrears_tael": 800.0}, "state", "G-1"),
            _assessment(0, 100.0),
        ]
    )

    reading = fiscal_military_ratchet(one_way)
    assert reading.present is True
    assert reading.strength == pytest.approx(0.5)
    assert reading.detail_map()["months_with_a_decline"] == 0.0
    assert fiscal_military_ratchet(cleared_once).present is False


def test_consolidation_needs_fewer_bands_and_a_rising_largest_share() -> None:
    """Concentration with the same band count is not consolidation, and neither is shrinkage."""
    consolidated = _log(
        [
            (0, "BAND_STATE", {"troops": 10.0}, "band-state", "b1"),
            (0, "BAND_STATE", {"troops": 10.0}, "band-state", "b2"),
            (0, "BAND_STATE", {"troops": 10.0}, "band-state", "b3"),
            (1, "BAND_STATE", {"troops": 10.0}, "band-state", "b1"),
            (1, "BAND_STATE", {"troops": 10.0}, "band-state", "b2"),
            (1, "BAND_STATE", {"troops": 60.0}, "band-state", "b3"),
            (2, "BAND_STATE", {"troops": 80.0}, "band-state", "b3"),
        ]
    )
    fragmented = _log(
        [
            (0, "BAND_STATE", {"troops": 30.0}, "band-state", "b1"),
            (0, "BAND_STATE", {"troops": 10.0}, "band-state", "b2"),
            (1, "BAND_STATE", {"troops": 20.0}, "band-state", "b1"),
            (1, "BAND_STATE", {"troops": 20.0}, "band-state", "b2"),
        ]
    )

    reading = armed_band_consolidation(consolidated)
    assert reading.present is True
    assert reading.detail_map()["bands_last_tick"] < reading.detail_map()["bands_first_tick"]
    assert armed_band_consolidation(fragmented).present is False


def test_a_log_without_the_events_a_reading_needs_is_refused() -> None:
    """A missing mechanism is not "absent": the reading refuses rather than returning a verdict."""
    empty = _log([])

    with pytest.raises(MechanismError, match="extraction decisions"):
        extraction_inversion(empty)
    with pytest.raises(MechanismError, match="military state"):
        fiscal_military_ratchet(empty)
    with pytest.raises(MechanismError, match="band state"):
        armed_band_consolidation(empty)


def test_every_reading_names_its_own_falsifier() -> None:
    log = _log(
        [
            _extraction(0, 0.3, 0.02),
            _extraction(1, 0.8, 0.04),
            _assessment(0, 100.0),
            _assessment(1, 100.0),
            _receipt(0, 40.0),
            _receipt(1, 20.0),
            (0, "MILITARY_STATE", {"pay_arrears_tael": 10.0}, "state", "G-1"),
            (1, "MILITARY_STATE", {"pay_arrears_tael": 20.0}, "state", "G-1"),
            (0, "BAND_STATE", {"troops": 10.0}, "band-state", "b1"),
            (1, "BAND_STATE", {"troops": 30.0}, "band-state", "b1"),
        ]
    )
    readings = mechanism_readings(log)

    assert tuple(reading.mechanism for reading in readings) == MECHANISM_IDS
    for reading in readings:
        assert reading.falsifier
        assert reading.reading
        assert isinstance(reading.strength, float)


def test_a_real_run_produces_one_reading_per_mechanism() -> None:
    """The readings work on an actual log, with no hand-built frame in the way."""
    from late_ming_lab.experiments.institutional_smoke import run_institutional

    run = run_institutional(policy="rule", ticks=48, warmup_ticks=12)
    readings = mechanism_readings(run.events)

    assert len(readings) == len(MECHANISM_IDS)
    assert all(reading.detail for reading in readings)
