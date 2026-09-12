"""The monthly agricultural calendar.

An agricultural season is a property of an agrarian zone, not of a province: the loess
dryland and the north China plain plant and harvest in different months and are damaged by
anomalies in different months. The calendar states, for each zone and calendar month, the
crop phase and how damaging an adverse anomaly in that month is.

Two caveats are part of the model contract, not fine print:

1. months are Gregorian. The lunar calendar — which governed actual agricultural practice,
   with its intercalary months and its drift against the solar year — is **not** modelled
   here. The agricultural calendar of P02 is a seasonality skeleton, not a claim about
   specific months of specific years.
2. every sensitivity value is grade ``S``: a modelling assumption awaiting a sourced
   parameter card in P08, and a mandatory sensitivity-analysis target.

The calendar is a lookup structure. It changes no state and emits no events; the climate
system uses it to weight the exogenous forcing, and the production function will use it in
P03.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from late_ming_lab.evidence.grades import DataProvenance
from late_ming_lab.networks.nodes import AgrarianZone

CALENDAR_VERSION: Final[str] = "agricultural-calendar-v1"

ALL_MONTHS: Final[tuple[int, ...]] = tuple(range(1, 13))

#: Recorded in every default calendar entry; repeated here so the caveat travels with the data.
GREGORIAN_MONTH_CAVEAT: Final[str] = (
    "Gregorian months approximate the agricultural season; the lunar calendar and its "
    "intercalary months are not modelled"
)


class CropPhase(StrEnum):
    """What the fields are doing in a month."""

    FALLOW = "fallow"
    PLANTING = "planting"
    GROWING = "growing"
    HARVEST = "harvest"


class ZoneCalendar(BaseModel):
    """Phase and anomaly sensitivity for every month of one agrarian zone."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    zone: AgrarianZone
    phases: dict[int, CropPhase]
    shock_sensitivity: dict[int, float]
    provenance: DataProvenance

    @field_validator("phases", "shock_sensitivity", mode="after")
    @classmethod
    def _cover_every_month(cls, value: dict[int, float]) -> dict[int, float]:
        months = tuple(sorted(value))
        if months != ALL_MONTHS:
            raise ValueError(f"calendar entries must cover months 1-12 exactly, got {months}")
        return value

    @field_validator("shock_sensitivity", mode="after")
    @classmethod
    def _bounded_sensitivity(cls, value: dict[int, float]) -> dict[int, float]:
        for month, sensitivity in value.items():
            if not 0.0 <= sensitivity <= 1.0:
                raise ValueError(
                    f"shock_sensitivity for month {month} must lie in [0, 1], got {sensitivity}"
                )
        return value

    @property
    def harvest_months(self) -> tuple[int, ...]:
        return tuple(
            month for month, phase in sorted(self.phases.items()) if phase is CropPhase.HARVEST
        )

    def sensitivity_for(self, month: int) -> float:
        _require_month(month)
        return self.shock_sensitivity[month]


class AgriculturalCalendar(BaseModel):
    """The zone calendars available to a run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = CALENDAR_VERSION
    zones: tuple[ZoneCalendar, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_zones(self) -> AgriculturalCalendar:
        seen = [zone.zone for zone in self.zones]
        if len(set(seen)) != len(seen):
            raise ValueError("a calendar holds exactly one entry per agrarian zone")
        return self

    @property
    def zone_names(self) -> tuple[AgrarianZone, ...]:
        return tuple(entry.zone for entry in self.zones)

    def calendar_for(self, zone: AgrarianZone | None) -> ZoneCalendar:
        if zone is None:
            raise ValueError("this node has no agrarian zone, so no calendar applies to it")
        for entry in self.zones:
            if entry.zone is zone:
                return entry
        known = ", ".join(entry.value for entry in self.zone_names)
        raise ValueError(f"no calendar for zone {str(zone)!r}; known zones: {known}")

    def phase(self, zone: AgrarianZone, month: int) -> CropPhase:
        return self.calendar_for(zone).phases[month]

    def shock_sensitivity(self, zone: AgrarianZone, month: int) -> float:
        return self.calendar_for(zone).sensitivity_for(month)

    def harvest_months(self, zone: AgrarianZone) -> tuple[int, ...]:
        return self.calendar_for(zone).harvest_months


def _require_month(month: int) -> None:
    if month not in ALL_MONTHS:
        raise ValueError(f"month must be 1-12, got {month}")


def core_default_calendar() -> AgriculturalCalendar:
    """The two core zones, with explicitly assumed phase and sensitivity values.

    Loess dryland: spring-sown millet and wheat, harvest in early autumn, so a growing-season
    anomaly from May to August is what damages the crop.

    North China plain: winter wheat harvested in late spring plus a summer crop, so both the
    spring grain-filling window and the autumn sowing window are sensitive.
    """
    loess = ZoneCalendar(
        zone=AgrarianZone.LOESS_DRYLAND,
        phases={
            1: CropPhase.FALLOW,
            2: CropPhase.FALLOW,
            3: CropPhase.PLANTING,
            4: CropPhase.PLANTING,
            5: CropPhase.GROWING,
            6: CropPhase.GROWING,
            7: CropPhase.GROWING,
            8: CropPhase.GROWING,
            9: CropPhase.HARVEST,
            10: CropPhase.HARVEST,
            11: CropPhase.FALLOW,
            12: CropPhase.FALLOW,
        },
        shock_sensitivity={
            1: 0.0,
            2: 0.05,
            3: 0.6,
            4: 0.5,
            5: 0.7,
            6: 0.9,
            7: 0.9,
            8: 0.7,
            9: 0.3,
            10: 0.2,
            11: 0.05,
            12: 0.0,
        },
        provenance=DataProvenance.assumption(
            "loess dryland spring-sown millet and wheat pattern with monthly sensitivity "
            f"weights; grade S pending a sourced parameter card; {GREGORIAN_MONTH_CAVEAT}"
        ),
    )
    plain = ZoneCalendar(
        zone=AgrarianZone.NORTH_CHINA_PLAIN,
        phases={
            1: CropPhase.FALLOW,
            2: CropPhase.FALLOW,
            3: CropPhase.GROWING,
            4: CropPhase.GROWING,
            5: CropPhase.HARVEST,
            6: CropPhase.PLANTING,
            7: CropPhase.GROWING,
            8: CropPhase.GROWING,
            9: CropPhase.HARVEST,
            10: CropPhase.PLANTING,
            11: CropPhase.GROWING,
            12: CropPhase.FALLOW,
        },
        shock_sensitivity={
            1: 0.1,
            2: 0.2,
            3: 0.5,
            4: 0.9,
            5: 0.7,
            6: 0.6,
            7: 0.6,
            8: 0.7,
            9: 0.5,
            10: 0.6,
            11: 0.2,
            12: 0.1,
        },
        provenance=DataProvenance.assumption(
            "north China plain winter wheat plus summer crop pattern with monthly "
            f"sensitivity weights; grade S pending a sourced parameter card; "
            f"{GREGORIAN_MONTH_CAVEAT}"
        ),
    )
    return AgriculturalCalendar(zones=(loess, plain))
