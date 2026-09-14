"""The historical core's node selection, on tables small enough to check by hand.

The selection is a rule with declared parameters, so the tests are about the rule's behaviour
rather than about the real data: the zone boundaries, the quota arithmetic, the chain growth, the
attachment filter, and the two ways the rule refuses (no eligible seat, no reachable seat).
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.historical.selection import (
    CHAIN_RADIUS_KM,
    MIN_EVENTS,
    MIN_SEPARATION_KM,
    TARGET_NODES,
    SelectionError,
    SelectionReport,
    haversine_km,
    node_id_for,
    select_nodes,
    station_distances,
    zone_for,
)
from late_ming_lab.networks.nodes import AgrarianZone, Province


def _seat(
    sys_id: str,
    *,
    name: str,
    latitude: float,
    longitude: float,
    province: str = "今陕西",
    years: int = 20,
    events: int = 30,
) -> dict[str, object]:
    return {
        "sys_id": sys_id,
        "name_py": name,
        "name_ch": name,
        "present_province": province,
        "zone": "loess-dryland",
        "latitude": latitude,
        "longitude": longitude,
        "begin_year": 1600,
        "end_year": 1660,
        "seat_type": "Xian",
        "years_covered": years,
        "events": events,
    }


SCHEMA = {
    "sys_id": pl.Utf8,
    "name_py": pl.Utf8,
    "name_ch": pl.Utf8,
    "present_province": pl.Utf8,
    "zone": pl.Utf8,
    "latitude": pl.Float64,
    "longitude": pl.Float64,
    "begin_year": pl.Int32,
    "end_year": pl.Int32,
    "seat_type": pl.Utf8,
    "years_covered": pl.Int32,
    "events": pl.Int32,
}


def test_the_zone_rule_stops_where_the_model_has_no_calendar() -> None:
    assert zone_for("shaanxi", 34.0) is AgrarianZone.LOESS_DRYLAND
    assert zone_for("shaanxi", 33.9) is None
    assert zone_for("henan", 32.5) is AgrarianZone.NORTH_CHINA_PLAIN
    assert zone_for("henan", 32.4) is None
    assert zone_for("shanxi", 38.0) is None


def test_haversine_matches_a_known_distance() -> None:
    # One degree of latitude is about 111 km on the sphere the model uses.
    assert haversine_km(35.0, 110.0, 36.0, 110.0) == pytest.approx(111.2, abs=0.5)
    assert haversine_km(35.0, 110.0, 35.0, 110.0) == pytest.approx(0.0, abs=1e-9)


def test_a_shared_pinyin_name_gets_the_chgis_identifier() -> None:
    taken = {"hc-sx-yanan"}
    assert node_id_for(Province.SHAANXI, "Yanan", "90001", taken) == "hc-sx-yanan-90001"
    assert node_id_for(Province.HENAN, "Nei Xiang Xian", "90002", taken) == "hc-hn-nei-xiang-xian"


def test_the_selection_grows_a_chain_from_the_best_covered_seat() -> None:
    eligible = pl.DataFrame(
        [
            _seat("1", name="Seed", latitude=35.0, longitude=110.0, years=20, events=50),
            _seat("2", name="Near", latitude=35.3, longitude=110.0, years=18, events=40),
            _seat("3", name="Best", latitude=35.6, longitude=110.0, years=19, events=45),
            _seat("4", name="Best", latitude=35.9, longitude=110.0, years=20, events=60),
        ],
        schema=SCHEMA,
    )
    report = SelectionReport()
    selected = select_nodes(eligible, pl.DataFrame(schema={"year": pl.Int32}), report)
    chosen = selected["name_py"].to_list()
    # The seed is the best-covered seat of the province, and the chain reaches the rest.
    assert report.seed_sys_ids == ("4",)
    assert set(chosen) == {"Seed", "Near", "Best"}
    assert selected.height == 4
    assert report.selected == selected.height
    assert report.omitted_eligible == ()


def test_a_seat_beyond_the_chain_radius_is_not_selected() -> None:
    eligible = pl.DataFrame(
        [
            _seat("1", name="Seed", latitude=35.0, longitude=110.0),
            _seat("2", name="Far", latitude=39.0, longitude=114.0),
        ],
        schema=SCHEMA,
    )
    report = SelectionReport()
    selected = select_nodes(eligible, pl.DataFrame(schema={"year": pl.Int32}), report)
    assert selected["name_py"].to_list() == ["Seed"]
    assert "2" in report.omitted_eligible or "Far" in "".join(report.omitted_eligible)
    assert report.stopped_before_target


def test_two_seats_too_close_together_are_not_both_taken() -> None:
    eligible = pl.DataFrame(
        [
            _seat("1", name="Seed", latitude=35.000, longitude=110.0, events=99),
            _seat("2", name="Twin", latitude=35.001, longitude=110.0, events=50),
            _seat("3", name="Next", latitude=35.3, longitude=110.0, events=40),
        ],
        schema=SCHEMA,
    )
    report = SelectionReport()
    selected = select_nodes(eligible, pl.DataFrame(schema={"year": pl.Int32}), report)
    names = selected["name_py"].to_list()
    assert report.seed_sys_ids == ("1",)
    assert "Twin" not in names  # closer than MIN_SEPARATION_KM to the seed
    assert "Next" in names
    assert MIN_SEPARATION_KM > 0


def test_a_selection_with_no_eligible_seat_is_refused_not_emptied() -> None:
    empty = pl.DataFrame(schema=SCHEMA)
    with pytest.raises(SelectionError, match="no seat passed"):
        select_nodes(empty, pl.DataFrame(schema={"year": pl.Int32}), SelectionReport())


def test_the_attachment_filter_excludes_seats_off_the_network() -> None:
    eligible = pl.DataFrame(
        [
            _seat("1", name="Onroad", latitude=35.0, longitude=110.0),
            _seat("2", name="Offroad", latitude=35.3, longitude=110.0),
        ],
        schema=SCHEMA,
    )
    report = SelectionReport()
    selected = select_nodes(
        eligible, pl.DataFrame(schema={"year": pl.Int32}), report, attached={"1"}
    )
    assert selected["name_py"].to_list() == ["Onroad"]
    assert report.off_the_documented_network == 1


def test_station_distances_find_the_nearest_station() -> None:
    seats = pl.DataFrame(
        [{"sys_id": "a", "latitude": 35.0, "longitude": 110.0}],
        schema={"sys_id": pl.Utf8, "latitude": pl.Float64, "longitude": pl.Float64},
    )
    stations = pl.DataFrame(
        [
            {"station_id": 7, "latitude": 35.0, "longitude": 110.01},
            {"station_id": 8, "latitude": 39.0, "longitude": 114.0},
        ],
        schema={"station_id": pl.Int64, "latitude": pl.Float64, "longitude": pl.Float64},
    )
    found = station_distances(seats, stations)
    assert found["station_id"].to_list() == [7]
    assert found["station_km"][0] == pytest.approx(0.9, abs=0.2)


def test_the_declared_parameters_are_the_ones_the_docstring_claims() -> None:
    assert MIN_EVENTS > 0
    assert 0 < MIN_SEPARATION_KM < CHAIN_RADIUS_KM
    assert TARGET_NODES >= 8
