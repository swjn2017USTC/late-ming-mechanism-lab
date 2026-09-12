"""Calendar contract: every zone covers every month, and the seasons have structure."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from late_ming_lab.evidence.grades import DataProvenance
from late_ming_lab.networks.nodes import AgrarianZone
from late_ming_lab.systems.calendar import (
    ALL_MONTHS,
    CALENDAR_VERSION,
    AgriculturalCalendar,
    CropPhase,
    ZoneCalendar,
    core_default_calendar,
)

ASSUMED = DataProvenance.assumption("test fixture assumption")


def test_a_zone_calendar_must_cover_every_month() -> None:
    with pytest.raises(ValidationError, match="months 1-12 exactly"):
        ZoneCalendar(
            zone=AgrarianZone.LOESS_DRYLAND,
            phases={1: CropPhase.FALLOW},
            shock_sensitivity={1: 0.0},
            provenance=ASSUMED,
        )
    with pytest.raises(ValidationError, match="must lie in"):
        ZoneCalendar(
            zone=AgrarianZone.LOESS_DRYLAND,
            phases=dict.fromkeys(ALL_MONTHS, CropPhase.FALLOW),
            shock_sensitivity={**dict.fromkeys(ALL_MONTHS, 0.0), 7: 1.5},
            provenance=ASSUMED,
        )


def test_the_default_calendar_covers_both_core_zones() -> None:
    calendar = core_default_calendar()

    assert calendar.version == CALENDAR_VERSION
    assert set(calendar.zone_names) == {
        AgrarianZone.LOESS_DRYLAND,
        AgrarianZone.NORTH_CHINA_PLAIN,
    }
    assert [entry.zone for entry in calendar.zones] == list(calendar.zone_names)


def test_every_default_entry_is_an_assumption_not_a_sourced_claim() -> None:
    for entry in core_default_calendar().zones:
        assert entry.provenance.is_assumption, entry.zone
        assert not entry.provenance.source_id


def test_harvest_months_follow_the_two_cropping_systems() -> None:
    calendar = core_default_calendar()

    assert calendar.harvest_months(AgrarianZone.LOESS_DRYLAND) == (9, 10)
    assert calendar.harvest_months(AgrarianZone.NORTH_CHINA_PLAIN) == (5, 9)
    for zone in calendar.zone_names:
        assert all(
            calendar.phase(zone, month) is CropPhase.HARVEST
            for month in calendar.harvest_months(zone)
        )


def test_seasons_have_structure_an_anomaly_can_act_on() -> None:
    calendar = core_default_calendar()

    for entry in calendar.zones:
        fallow = [
            entry.shock_sensitivity[month]
            for month, phase in entry.phases.items()
            if phase is CropPhase.FALLOW
        ]
        active = [
            entry.shock_sensitivity[month]
            for month, phase in entry.phases.items()
            if phase is not CropPhase.FALLOW
        ]
        assert max(fallow) <= min(active), entry.zone
        assert all(entry.shock_sensitivity[month] > 0.0 for month in entry.harvest_months)


def test_lookups_reject_months_and_zones_outside_the_calendar() -> None:
    calendar = core_default_calendar()
    loess_only = AgriculturalCalendar(zones=(calendar.calendar_for(AgrarianZone.LOESS_DRYLAND),))

    with pytest.raises(ValueError, match="month must be 1-12"):
        calendar.shock_sensitivity(AgrarianZone.LOESS_DRYLAND, 13)
    with pytest.raises(ValueError, match="no calendar for zone"):
        loess_only.calendar_for(AgrarianZone.NORTH_CHINA_PLAIN)
    with pytest.raises(ValueError, match="no agrarian zone"):
        calendar.calendar_for(None)


def test_duplicate_zone_entries_are_refused() -> None:
    entry = ZoneCalendar(
        zone=AgrarianZone.LOESS_DRYLAND,
        phases=dict.fromkeys(ALL_MONTHS, CropPhase.FALLOW),
        shock_sensitivity=dict.fromkeys(ALL_MONTHS, 0.0),
        provenance=ASSUMED,
    )

    with pytest.raises(ValidationError, match="exactly one entry per agrarian zone"):
        type(core_default_calendar())(zones=(entry, entry))


def test_calendar_phase_and_sensitivity_agree_with_the_entries() -> None:
    calendar = core_default_calendar()
    entry = calendar.calendar_for(AgrarianZone.NORTH_CHINA_PLAIN)
    phases: Sequence[CropPhase] = [entry.phases[month] for month in ALL_MONTHS]

    assert len(phases) == 12
    assert calendar.phase(AgrarianZone.NORTH_CHINA_PLAIN, 4) is CropPhase.GROWING
    assert calendar.shock_sensitivity(AgrarianZone.NORTH_CHINA_PLAIN, 4) == 0.9
