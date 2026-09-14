"""Choosing the nodes of the historical core, and recording what the choice left out.

The core is a *selection* of sourced seats, so the selection is a rule that can be argued with
rather than a list that can only be trusted. Every filter, every parameter and every exclusion is
declared here, and :class:`SelectionReport` counts what each filter removed - including the seats
that were eligible and simply not chosen, because "we picked twelve" is a claim about spread, not
about importance.

```text
candidates   CHGIS V6 seats in present-day Shaanxi and Henan, type Xian or Zhou, with coordinates
eligible     candidates whose CHGIS date range covers 1625-1644, inside a declared agrarian zone,
             and with at least MIN_EVENTS recorded climate events within CLIMATE_RADIUS_KM
selected     TARGET_NODES seats, grown per province from the best-covered eligible seat: each
             step adds the best-covered reachable seat within CHAIN_RADIUS_KM and no closer than
             MIN_SEPARATION_KM, with a quota proportional to each province's eligible seats
exits        one gateway seat per neighbouring province the model uses as an exit
```

Three properties are deliberate. The climate-record requirement makes observed forcing possible: a
seat with no records would enter the model with a silent zero. The spread rule is geographic and
says nothing about historical importance, which is recorded as a limitation rather than smuggled in
through the choice. And the seats outside the two declared agrarian zones are excluded and counted,
because the model has no calendar for them - a scope limit, not a data gap.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np
import polars as pl
from pydantic import BaseModel, ConfigDict

from late_ming_lab.historical.provenance import (
    WINDOW_END,
    WINDOW_START,
    chgis_derived,
)
from late_ming_lab.networks.nodes import AgrarianZone, ExternalRole, Province

#: Present-day province strings inside the CHGIS layer, and the provinces they mean.
CORE_PROVINCES: Final[dict[str, Province]] = {
    "今陕西": Province.SHAANXI,
    "今河南": Province.HENAN,
}

#: Neighbouring provinces used as exits, with the roles each gateway seat serves.
EXIT_PROVINCES: Final[tuple[tuple[str, Province, tuple[ExternalRole, ...]], ...]] = (
    (
        "今山西",
        Province.SHANXI,
        (ExternalRole.MIGRATION_EXIT, ExternalRole.MILITARY_LINK, ExternalRole.TRADE_LINK),
    ),
    ("今湖北", Province.HUGUANG, (ExternalRole.MIGRATION_EXIT, ExternalRole.TRADE_LINK)),
    ("今四川", Province.SICHUAN, (ExternalRole.MIGRATION_EXIT,)),
)

#: Seat types that are administrative seats: county and department seats.
SEAT_TYPES: Final[tuple[str, ...]] = ("Xian", "Zhou")

#: The Qinling line, north of which Shaanxi is loess dryland; south of it is the Han valley, for
#: which this model has no calendar.
LOESS_SOUTHERN_LIMIT_DEG: Final[float] = 34.0

#: The line south of which Henan is not the north China plain in this model's terms.
PLAIN_SOUTHERN_LIMIT_DEG: Final[float] = 32.5

#: Declared selection parameters. Each is a decision, so each is stated here and graded in the
#: report rather than buried in the algorithm.
CLIMATE_RADIUS_KM: Final[float] = 60.0
MIN_EVENTS: Final[int] = 5
TARGET_NODES: Final[int] = 12
#: How far a seat may be from an already-selected one and still join the sample. The core is a
#: *network* sample: seats are added outward from a seed so the set is connected by short links,
#: which is what lets the movement graphs have edges at all.
CHAIN_RADIUS_KM: Final[float] = 80.0
#: Two seats closer than this would be the same place for the model's purposes.
MIN_SEPARATION_KM: Final[float] = 25.0
#: How far a seat may lie from a courier station and still be reachable. A seat off the
#: documented network cannot appear in any of the three movement graphs, so it is not selected.
STATION_SNAP_RADIUS_KM: Final[float] = 40.0
MIN_NODES_PER_PROVINCE: Final[int] = 3

#: CHGIS publishes no uncertainty radius for this layer; this is ours, and the note says so.
LOCATION_UNCERTAINTY_KM: Final[float] = 5.0

#: Bounding box for in-window events, wide enough for the exit provinces and narrow enough to
#: exclude Japan, Korea and the far south-west.
EVENT_BOX: Final[tuple[float, float, float, float]] = (100.0, 120.0, 28.0, 42.0)


class SelectionError(RuntimeError):
    """Raised when the core cannot be built to the declared rule."""


class SelectionRule(BaseModel):
    """The rule, serialised with the dataset so a rebuild states what produced it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window: tuple[int, int] = (WINDOW_START, WINDOW_END)
    core_provinces: tuple[str, ...] = tuple(CORE_PROVINCES)
    seat_types: tuple[str, ...] = SEAT_TYPES
    climate_radius_km: float = CLIMATE_RADIUS_KM
    min_events: int = MIN_EVENTS
    target_nodes: int = TARGET_NODES
    chain_radius_km: float = CHAIN_RADIUS_KM
    station_snap_radius_km: float = STATION_SNAP_RADIUS_KM
    min_separation_km: float = MIN_SEPARATION_KM
    min_nodes_per_province: int = MIN_NODES_PER_PROVINCE
    loess_southern_limit_deg: float = LOESS_SOUTHERN_LIMIT_DEG
    plain_southern_limit_deg: float = PLAIN_SOUTHERN_LIMIT_DEG
    location_uncertainty_km: float = LOCATION_UNCERTAINTY_KM
    zone_rule: str = (
        "Shaanxi seats at or north of 34.0N are loess-dryland; Henan seats at or north of 32.5N "
        "are north-china-plain; seats outside those bands are excluded."
    )
    node_id_rule: str = (
        "hc-sx-* / hc-hn-* from the seat's pinyin name; a duplicated name takes the CHGIS system "
        "id as a suffix"
    )
    spread_rule: str = (
        "per province: seed on the seat with the best record coverage, then repeatedly add the "
        "best-covered eligible seat within CHAIN_RADIUS_KM of an already-selected seat, skipping "
        "any seat closer than MIN_SEPARATION_KM to one already taken, until the province quota is "
        "met"
    )
    limitation: str = (
        "the rule is a network sample: it selects for record coverage and for connectivity along "
        "short links, and it makes no claim that the selected seats were the most important places "
        "in the window"
    )


@dataclass(slots=True)
class SelectionReport:
    """What the rule saw, chose and left out; every count computed, none written by hand."""

    candidates: int = 0
    non_seat_types: int = 0
    outside_core_provinces: int = 0
    unlocated: int = 0
    date_range_excludes_window: int = 0
    outside_declared_zones: int = 0
    below_event_threshold: int = 0
    off_the_documented_network: int = 0
    eligible: int = 0
    selected: int = 0
    selected_by_province: dict[str, int] = field(default_factory=dict)
    quota_by_province: dict[str, int] = field(default_factory=dict)
    eligible_by_province: dict[str, int] = field(default_factory=dict)
    seed_sys_ids: tuple[str, ...] = ()
    omitted_eligible: tuple[str, ...] = ()
    stopped_before_target: str = ""
    exits: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def record(self) -> dict[str, object]:
        """The report as plain data, for the manifest and the coverage document."""
        return {
            "candidates": self.candidates,
            "excluded": {
                "not_a_seat": self.non_seat_types,
                "outside_core_provinces": self.outside_core_provinces,
                "no_coordinates": self.unlocated,
                "date_range_excludes_window": self.date_range_excludes_window,
                "outside_declared_agrarian_zones": self.outside_declared_zones,
                "below_climate_event_threshold": self.below_event_threshold,
            },
            "eligible": self.eligible,
            "reachable": self.eligible - self.off_the_documented_network,
            "off_the_documented_courier_network": self.off_the_documented_network,
            "candidate_filters_account_for_candidates": (
                sum(
                    (
                        self.non_seat_types,
                        self.outside_core_provinces,
                        self.unlocated,
                        self.date_range_excludes_window,
                        self.outside_declared_zones,
                        self.below_event_threshold,
                    )
                )
                + self.eligible
                == self.candidates
            ),
            "eligible_by_province": self.eligible_by_province,
            "selected": self.selected,
            "selected_by_province": self.selected_by_province,
            "quota_by_province": self.quota_by_province,
            "seed_sys_ids": list(self.seed_sys_ids),
            "omitted_eligible": list(self.omitted_eligible),
            "stopped_before_target": self.stopped_before_target,
            "exits": list(self.exits),
            "notes": list(self.notes),
        }


def _zone_value(row: dict[str, Any]) -> str | None:
    """The declared zone of one seat row, as a string the frame can hold."""
    zone = zone_for(CORE_PROVINCES[str(row["present_province"])].value, float(row["latitude"]))
    return None if zone is None else zone.value


def _mean(column: pl.Series) -> float:
    """The mean of a numeric column, as a float, with an empty column meaning zero."""
    value = column.mean()
    return 0.0 if value is None else float(str(value))


def haversine_km(
    latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float
) -> float:
    """Great-circle distance in kilometres, on the sphere the model reports distances on."""
    radius_km = 6371.0088
    phi_a, phi_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_phi = phi_b - phi_a
    delta_lambda = math.radians(longitude_b - longitude_a)
    haversine = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(haversine))


def zone_for(province: str, latitude: float) -> AgrarianZone | None:
    """The declared agrarian zone of a seat, or ``None`` when the model has no zone for it."""
    if province == Province.SHAANXI.value and latitude >= LOESS_SOUTHERN_LIMIT_DEG:
        return AgrarianZone.LOESS_DRYLAND
    if province == Province.HENAN.value and latitude >= PLAIN_SOUTHERN_LIMIT_DEG:
        return AgrarianZone.NORTH_CHINA_PLAIN
    return None


def slug(name_py: str) -> str:
    """A lowercase, hyphen-separated slug of a pinyin seat name."""
    rendered = "".join(character if character.isalnum() else "-" for character in name_py.lower())
    return "-".join(part for part in rendered.split("-") if part)


def node_id_for(province: Province, name_py: str, sys_id: str, taken: set[str]) -> str:
    """A stable node id from the seat's pinyin name, with the CHGIS system id on collision."""
    prefix = "hc-sx" if province is Province.SHAANXI else "hc-hn"
    candidate = f"{prefix}-{slug(name_py)}"
    if candidate in taken:
        candidate = f"{candidate}-{sys_id}"
    return candidate


def window_events(events: pl.DataFrame) -> pl.DataFrame:
    """The events that fall in the window and inside the bounding box, with usable coordinates."""
    west, east, south, north = EVENT_BOX
    return events.filter(
        pl.col("year").is_between(WINDOW_START, WINDOW_END)
        & pl.col("longitude").is_between(west, east)
        & pl.col("latitude").is_between(south, north)
    )


def assign_events_to_seats(
    seats: pl.DataFrame, events: pl.DataFrame, *, radius_km: float = CLIMATE_RADIUS_KM
) -> pl.DataFrame:
    """Attach every in-window event to its nearest seat, or to none beyond ``radius_km``.

    One rule, used by both the counts and the forcing, so the two cannot disagree: an event belongs
    to the closest seat within the radius, and ties break on the CHGIS system id, which is stable.
    """
    window = window_events(events)
    if seats.height == 0 or window.height == 0:
        return window.head(0).with_columns(
            pl.lit(None, dtype=pl.Utf8).alias("sys_id"),
            pl.lit(None, dtype=pl.Float64).alias("distance_km"),
        )
    event_latitude = window["latitude"].to_numpy()
    event_longitude = window["longitude"].to_numpy()
    seat_latitude = seats["latitude"].to_numpy()
    seat_longitude = seats["longitude"].to_numpy()

    phi_events = np.radians(event_latitude)[:, None]
    phi_seats = np.radians(seat_latitude)[None, :]
    delta_phi = phi_seats - phi_events
    delta_lambda = np.radians(seat_longitude)[None, :] - np.radians(event_longitude)[:, None]
    haversine = (
        np.sin(delta_phi / 2) ** 2
        + np.cos(phi_events) * np.cos(phi_seats) * np.sin(delta_lambda / 2) ** 2
    )
    distances = 2 * 6371.0088 * np.arcsin(np.sqrt(np.clip(haversine, 0.0, 1.0)))
    nearest = np.argmin(distances, axis=1)
    nearest_distance = distances[np.arange(distances.shape[0]), nearest]
    within = nearest_distance <= radius_km
    ids = seats["sys_id"].to_numpy()
    assigned_ids: list[str | None] = [
        str(ids[index]) if keep else None for index, keep in zip(nearest, within, strict=True)
    ]
    assigned_km: list[float | None] = [
        float(distance) if keep else None
        for distance, keep in zip(nearest_distance, within, strict=True)
    ]
    return window.with_columns(
        pl.Series("sys_id", assigned_ids, dtype=pl.Utf8),
        pl.Series("distance_km", assigned_km, dtype=pl.Float64),
    )


def event_counts_by_seat(
    seats: pl.DataFrame, events: pl.DataFrame, *, radius_km: float = CLIMATE_RADIUS_KM
) -> pl.DataFrame:
    """Per seat: how many in-window events fall within the radius, and of which category."""
    assigned = assign_events_to_seats(seats, events, radius_km=radius_km)
    counts = (
        assigned.filter(pl.col("sys_id").is_not_null())
        .group_by("sys_id")
        .agg(
            pl.len().alias("events"),
            pl.col("year").n_unique().alias("years_covered"),
            (pl.col("category") == "30").sum().alias("drought_events"),
            (pl.col("category") == "35").sum().alias("famine_events"),
            (pl.col("category") == "33").sum().alias("crop_events"),
            (pl.col("category") == "32").sum().alias("pest_events"),
            (pl.col("category") == "31").sum().alias("flood_events"),
        )
    )
    return (
        seats.select("sys_id")
        .join(counts, on="sys_id", how="left")
        .with_columns(
            pl.col("events").fill_null(0),
            pl.col("drought_events").fill_null(0),
            pl.col("famine_events").fill_null(0),
            pl.col("crop_events").fill_null(0),
            pl.col("pest_events").fill_null(0),
            pl.col("flood_events").fill_null(0),
        )
    )


def candidate_filters(
    seats: pl.DataFrame, events: pl.DataFrame, report: SelectionReport
) -> pl.DataFrame:
    """Apply the declared filters in order, counting what each one removes."""
    report.candidates = seats.height
    core = seats.filter(pl.col("present_province").is_in(list(CORE_PROVINCES)))
    report.outside_core_provinces = report.candidates - core.height
    report.non_seat_types = core.filter(
        pl.col("seat_type").is_null() | ~pl.col("seat_type").is_in(SEAT_TYPES)
    ).height
    typed = core.filter(pl.col("seat_type").is_in(SEAT_TYPES))
    report.unlocated = typed.filter(
        pl.col("latitude").is_null() | pl.col("longitude").is_null()
    ).height
    located = typed.filter(pl.col("latitude").is_not_null() & pl.col("longitude").is_not_null())
    in_window = located.filter(
        (pl.col("begin_year") <= WINDOW_START) & (pl.col("end_year") >= WINDOW_END)
    )
    report.date_range_excludes_window = located.height - in_window.height
    zoned = in_window.with_columns(
        pl.struct(["present_province", "latitude"])
        .map_elements(_zone_value, return_dtype=pl.Utf8)
        .alias("zone")
    )
    inside_zones = zoned.filter(pl.col("zone").is_not_null())
    report.outside_declared_zones = zoned.height - inside_zones.height
    counts = event_counts_by_seat(inside_zones, events)
    eligible = inside_zones.join(counts, on="sys_id", how="left").filter(
        pl.col("events") >= MIN_EVENTS
    )
    report.below_event_threshold = inside_zones.height - eligible.height
    report.eligible = eligible.height
    report.eligible_by_province = {
        province.value: eligible.filter(pl.col("present_province") == key).height
        for key, province in CORE_PROVINCES.items()
    }
    return eligible


def _quota(eligible: pl.DataFrame) -> dict[str, int]:
    """Seats per province, proportional to the eligible seats, never below the declared minimum.

    Proportionality is the rule because the eligible set is what the sources support: Shaanxi
    contributes fewer seats than Henan because fewer of its seats survive the zone and coverage
    filters, and the report says so rather than compensating with a quota nobody sourced.
    """
    counts = {
        province.value: eligible.filter(pl.col("present_province") == key).height
        for key, province in CORE_PROVINCES.items()
    }
    total = sum(counts.values())
    quota = {
        name: max(MIN_NODES_PER_PROVINCE, round(TARGET_NODES * count / total))
        for name, count in counts.items()
    }
    while sum(quota.values()) > TARGET_NODES:
        largest = max(quota, key=lambda name: (quota[name], name))
        quota[largest] -= 1
    return quota


def station_distances(seats: pl.DataFrame, stations: pl.DataFrame) -> pl.DataFrame:
    """For every seat, the distance to its nearest courier station and which station that is."""
    if seats.height == 0 or stations.height == 0:
        return seats.select("sys_id").with_columns(
            pl.lit(None, dtype=pl.Int64).alias("station_id"),
            pl.lit(None, dtype=pl.Float64).alias("station_km"),
        )
    seat_latitude = seats["latitude"].to_numpy()
    seat_longitude = seats["longitude"].to_numpy()
    station_latitude = stations["latitude"].to_numpy()
    station_longitude = stations["longitude"].to_numpy()
    phi_seats = np.radians(seat_latitude)[:, None]
    phi_stations = np.radians(station_latitude)[None, :]
    delta_phi = phi_stations - phi_seats
    delta_lambda = np.radians(station_longitude)[None, :] - np.radians(seat_longitude)[:, None]
    haversine = (
        np.sin(delta_phi / 2) ** 2
        + np.cos(phi_seats) * np.cos(phi_stations) * np.sin(delta_lambda / 2) ** 2
    )
    distances = 2 * 6371.0088 * np.arcsin(np.sqrt(np.clip(haversine, 0.0, 1.0)))
    nearest = np.argmin(distances, axis=1)
    nearest_km = distances[np.arange(distances.shape[0]), nearest]
    ids = stations["station_id"].to_numpy()
    return seats.select("sys_id").with_columns(
        pl.Series("station_id", ids[nearest], dtype=pl.Int64),
        pl.Series("station_km", nearest_km.astype(float), dtype=pl.Float64),
    )


def select_nodes(
    eligible: pl.DataFrame,
    events: pl.DataFrame,
    report: SelectionReport,
    *,
    attached: set[str] | None = None,
) -> pl.DataFrame:
    """Evidence-ranked selection per province, grown outward in short steps.

    Candidates are ordered by the coverage the sources give them - years of the window with a
    recorded event within the radius, then total events, then the CHGIS system id so the result is
    deterministic. Each province seeds on its best-covered seat and grows outward, adding the
    best-covered eligible seat within ``CHAIN_RADIUS_KM`` of one already taken and no closer than
    ``MIN_SEPARATION_KM`` to it, until the province's quota is met. The gaps a graph may still have
    after this are completed later by labelled connector links, and the coverage report counts them.
    """
    if eligible.height == 0:
        raise SelectionError(
            "no seat passed the declared filters; the core cannot be built. The report counts what "
            "each filter removed, and the phase must deliver a gap packet instead of filling "
            "values."
        )
    if attached is not None:
        on_network = eligible.filter(pl.col("sys_id").is_in(sorted(attached)))
        report.off_the_documented_network = eligible.height - on_network.height
        if on_network.height == 0:
            raise SelectionError(
                "no eligible seat lies within "
                f"{STATION_SNAP_RADIUS_KM:.0f} km of a courier station, so no movement graph "
                "could reach any of them"
            )
        eligible = on_network
    quota = _quota(eligible)
    chosen: list[dict[str, Any]] = []
    seeds: list[str] = []
    for key, province in CORE_PROVINCES.items():
        candidates = eligible.filter(pl.col("present_province") == key).sort(
            ["years_covered", "events", "sys_id"], descending=[True, True, False]
        )
        pool = candidates.to_dicts()
        if not pool:
            report.notes = (*report.notes, f"{province.value}: no eligible seat to seed from")
            continue
        taken: list[dict[str, Any]] = [pool[0]]
        seeds.append(str(pool[0]["sys_id"]))
        remaining = pool[1:]
        while len(taken) < quota[province.value]:
            reachable = []
            for row in remaining:
                separation = min(
                    haversine_km(
                        row["latitude"],
                        row["longitude"],
                        seat["latitude"],
                        seat["longitude"],
                    )
                    for seat in taken
                )
                if MIN_SEPARATION_KM <= separation <= CHAIN_RADIUS_KM:
                    reachable.append((separation, row))
            if not reachable:
                break
            best = sorted(
                reachable,
                key=lambda item: (
                    -int(item[1]["years_covered"]),
                    -int(item[1]["events"]),
                    item[0],
                    str(item[1]["sys_id"]),
                ),
            )[0][1]
            taken.append(best)
            remaining = [row for row in remaining if row["sys_id"] != best["sys_id"]]
        if len(taken) < quota[province.value]:
            report.notes = (
                *report.notes,
                f"{province.value}: {len(taken)} of the declared quota {quota[province.value]} "
                f"seats were reachable within {CHAIN_RADIUS_KM:.0f} km of the chain",
            )
        chosen.extend(taken)
    selected = pl.DataFrame(chosen, schema=eligible.schema).sort("sys_id")
    report.seed_sys_ids = tuple(sorted(seeds))
    report.selected = selected.height
    report.selected_by_province = {
        province.value: selected.filter(pl.col("present_province") == key).height
        for key, province in CORE_PROVINCES.items()
    }
    report.quota_by_province = dict(quota)
    selected_ids = set(selected["sys_id"].to_list())
    report.omitted_eligible = tuple(
        sorted(row["sys_id"] for row in eligible.to_dicts() if row["sys_id"] not in selected_ids)
    )
    if report.selected < TARGET_NODES:
        report.stopped_before_target = (
            f"selected {report.selected} of the {TARGET_NODES} target seats: no further eligible "
            f"seat lies within {CHAIN_RADIUS_KM:.0f} km of a chain in a province still short of "
            "its quota"
        )
    thin = [
        province.value
        for province in CORE_PROVINCES.values()
        if report.selected_by_province.get(province.value, 0) < MIN_NODES_PER_PROVINCE
    ]
    if thin:
        report.notes = (
            *report.notes,
            f"province(s) {', '.join(thin)} carry fewer than {MIN_NODES_PER_PROVINCE} selected "
            "seats: the growth follows proximity and record coverage, and it does not weight the "
            "provinces",
        )
    return selected


def external_exits(
    seats: pl.DataFrame, selected: pl.DataFrame, report: SelectionReport
) -> pl.DataFrame:
    """One gateway seat per usable neighbouring province, chosen as the nearest such seat.

    A neighbouring province is *usable* only when the corridor that reaches it is inside the
    modelled space. The Han valley, which is how Shaanxi is reached from Sichuan, is out of zone in
    this model, so the Sichuan exit is not built; the same holds for the northern plain corridor to
    Beizhili. Both omissions are recorded rather than filled with a distant seat.
    """
    rows: list[dict[str, Any]] = []
    usable = {
        "今山西": "the Shaanxi-Shanxi corridor along the Yellow River",
        "今湖北": "the Nanyang-Xiangyang corridor",
    }
    for key, province, roles in EXIT_PROVINCES:
        if key not in usable:
            report.notes = (
                *report.notes,
                (
                    f"exit toward {province.value} not built: the corridor that reaches it lies "
                    "outside the declared agrarian zones, so no gateway seat inside the modelled "
                    "space exists"
                ),
            )
            continue
        # A gateway seat has to exist in the window like any other node: a 6th-century county seat
        # is a real place but not this window's place, and the note has to state its own dates.
        candidates = seats.filter(
            (pl.col("present_province") == key)
            & pl.col("latitude").is_not_null()
            & pl.col("longitude").is_not_null()
            & (pl.col("begin_year") <= WINDOW_START)
            & (pl.col("end_year") >= WINDOW_END)
        )
        if candidates.height == 0:
            report.notes = (
                *report.notes,
                f"exit toward {province.value} not built: no located seat in that province whose "
                "CHGIS date range covers 1625-1644",
            )
            continue
        best_row: dict[str, Any] | None = None
        best_distance = float("inf")
        for candidate in candidates.to_dicts():
            for seat in selected.to_dicts():
                distance = haversine_km(
                    candidate["latitude"],
                    candidate["longitude"],
                    seat["latitude"],
                    seat["longitude"],
                )
                if distance < best_distance:
                    best_row, best_distance = candidate, distance
        assert best_row is not None
        best_row = {
            **best_row,
            "province": province.value,
            "roles": ",".join(role.value for role in roles),
            "distance_km": best_distance,
        }
        rows.append(best_row)
    if not rows:
        return seats.head(0)
    report.exits = tuple(f"{row['province']}:{row['name_py']}" for row in rows)
    return pl.DataFrame(rows)


def node_table(selected: pl.DataFrame, exits: pl.DataFrame) -> pl.DataFrame:
    """The node frame the adapter reads: one row per node, with provenance on every row."""
    taken: set[str] = set()
    rows: list[dict[str, Any]] = []
    for seat in selected.sort("sys_id").to_dicts():
        province = CORE_PROVINCES[str(seat["present_province"])]
        node_id = node_id_for(province, str(seat["name_py"]), str(seat["sys_id"]), taken)
        taken.add(node_id)
        provenance = chgis_derived(
            note=(
                f"Seat identity, CHGIS date range {seat['begin_year']}-{seat['end_year']} and "
                f"published coordinates; the agrarian zone and the {LOCATION_UNCERTAINTY_KM:.0f} "
                "km uncertainty radius are this project's declarations, and the selection rule "
                "chose this seat for spread and climate-record coverage, not for importance."
            )
        )
        rows.append(
            {
                "node_id": node_id,
                "kind": "county",
                "province": province.value,
                "zone": str(seat["zone"]),
                "external_roles": "",
                "latitude": float(seat["latitude"]),
                "longitude": float(seat["longitude"]),
                "location_precision": "seat-point",
                "location_uncertainty_km": LOCATION_UNCERTAINTY_KM,
                "evidence_grade": provenance.grade.value,
                "source_id": provenance.source_id,
                "locator": provenance.locator,
                "note": provenance.note,
                "name_py": str(seat["name_py"]),
                "name_ch": str(seat["name_ch"]),
                "chgis_sys_id": str(seat["sys_id"]),
                "begin_year": int(seat["begin_year"]),
                "end_year": int(seat["end_year"]),
            }
        )
    for exit_row in exits.to_dicts() if exits.height else []:
        province = Province(str(exit_row["province"]))
        node_id = f"hc-ext-{province}"
        provenance = chgis_derived(
            note=(
                f"Gateway seat on the {province} border, chosen as the nearest located "
                f"seat in that present-day province to a selected core seat "
                f"({exit_row['distance_km']:.0f} km). Its CHGIS date range "
                f"{exit_row['begin_year']}-{exit_row['end_year']} covers the window. The seat "
                "identity and coordinates are CHGIS; the exit role is this project's declaration, "
                "and the corridor claim is stated in the coverage report."
            )
        )
        rows.append(
            {
                "node_id": node_id,
                "kind": "external",
                "province": province.value,
                "zone": "",
                "external_roles": str(exit_row["roles"]),
                "latitude": float(exit_row["latitude"]),
                "longitude": float(exit_row["longitude"]),
                "location_precision": "seat-point",
                "location_uncertainty_km": LOCATION_UNCERTAINTY_KM,
                "evidence_grade": provenance.grade.value,
                "source_id": provenance.source_id,
                "locator": provenance.locator,
                "note": provenance.note,
                "name_py": str(exit_row["name_py"]),
                "name_ch": str(exit_row["name_ch"]),
                "chgis_sys_id": str(exit_row["sys_id"]),
                "begin_year": int(exit_row["begin_year"]),
                "end_year": int(exit_row["end_year"]),
            }
        )
    return pl.DataFrame(rows)
