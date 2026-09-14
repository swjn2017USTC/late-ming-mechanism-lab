"""What the historical core is, and what every derived field may claim.

The V2 historical core is a *derived selection* of sourced material, not a new dataset. This module
is the single place that says which sources it comes from, how they may be cited, and what grade a
derived field may carry — so a builder, a coverage report and a test all answer those questions the
same way.

```text
CHGIS V6            administrative seats, their dates and coordinates   (academic use, no
                    redistribution; a derived selection may be published with the mandatory
                    citation and a description of the changes)
REACHES (NOAA)      documentary climate events, 1368-1911               (licence unresolved;
                    aggregated derived series may be published, individual records may not)
courier routes      Ming postal/relay routes and stations, CHGIS 2016   (same CHGIS terms)
```

Three rules are enforced by the constants and helpers here rather than restated per module:

- **A derived claim is graded, never asserted.** :func:`chgis_derived` and :func:`declared` return a
  :class:`DataProvenance`, so a derived field cannot enter a table without a grade, a source and a
  locator.
- **The citation travels with the data.** Every CHGIS-derived row carries the mandatory citation
  string in its locator, because the licence requires attribution and a description of changes.
- **A model assumption says so.** Anything this project *decides* rather than *finds* is grade ``S``
  with the rule named in the note, which is what makes it visible in the coverage reports.
"""

from __future__ import annotations

from typing import Final

from late_ming_lab.evidence.grades import DataProvenance, EvidenceGrade

CORE_DATASET_ID: Final[str] = "historical-core-v1"
CORE_SCHEMA_VERSION: Final[str] = "historical-core-v1"

#: The window the core has to cover, inclusive.
WINDOW_START: Final[int] = 1625
WINDOW_END: Final[int] = 1644

CHGIS_SOURCE_ID: Final[str] = "chgis-v6"
REACHES_SOURCE_ID: Final[str] = "reaches-noaa"

#: The citation the CHGIS licence makes mandatory, verbatim from the EULA and the landing page.
CHGIS_CITATION: Final[str] = (
    "CHGIS, Version: 6. (c) Fairbank Center for Chinese Studies of Harvard University and the "
    "Center for Historical Geographical Studies at Fudan University, 2016."
)

#: Where each input came from, as a locator a reader can resolve, with the snapshot id that holds
#: the bytes and their hash.
CHGIS_COUNTY_POINTS: Final[tuple[str, str]] = (
    "snapshot:chgis-v6-county-points",
    f"{CHGIS_CITATION} Distribution: https://doi.org/10.7910/DVN/Q9VOF5 "
    "(v6_time_cnty_pts_utf_wgs84.zip)",
)
COURIER_ROUTES: Final[tuple[str, str]] = (
    "snapshot:chgis-v6-courier-routes",
    f"{CHGIS_CITATION} Ming courier routes and stations, 2016: "
    "https://doi.org/10.7910/DVN/SB8ZTM (Ming_Routes_2016.zip)",
)
COURIER_STATIONS: Final[tuple[str, str]] = (
    "snapshot:chgis-v6-courier-stations",
    f"{CHGIS_CITATION} Ming courier routes and stations, 2016: "
    "https://doi.org/10.7910/DVN/SB8ZTM (Ming_Stations_2016.zip)",
)
COURIER_SOURCES: Final[str] = (
    "Mingdai Yizhankao (Yang Zhengtai) and the 1903 Postal Atlas, per the layer README"
)
REACHES_EVENTS: Final[tuple[str, str]] = (
    "snapshot:reaches-noaa-data-v31",
    "REACHES Chinese Historical Climate Database, complete records 1368-1911, World Data Service "
    "for Paleoclimatology study 23410: "
    "https://www.ncei.noaa.gov/access/paleo-search/study/23410",
)
REACHES_CODES: Final[tuple[str, str]] = (
    "snapshot:reaches-noaa-codes",
    "REACHES event coding guide version 4.4, "
    "https://www.ncei.noaa.gov/pub/data/paleo/historical/china/reaches/",
)

#: Description of the changes the licence asks for, recorded once and reused in every derived row's
#: note: a reader must be able to see what this project did to the source.
CHGIS_CHANGES: Final[str] = (
    "Derived: filtered to county and department seats within the present-day Shaanxi and Henan "
    "provinces whose CHGIS date range covers 1625-1644, selected for spread and climate-record "
    "coverage, re-projected to WGS84 by taking the layer's WGS84 variant, with our own node ids, "
    "uncertainty radii and agrarian zone assigned. Attributes not used by the model were dropped."
)


def chgis_derived(*, note: str, locator: tuple[str, str] = CHGIS_COUNTY_POINTS) -> DataProvenance:
    """Provenance for a field derived from a CHGIS layer: grade B, citation, changes described."""
    return DataProvenance(
        grade=EvidenceGrade.B,
        source_id=CHGIS_SOURCE_ID,
        locator=locator[1],
        note=f"{CHGIS_CHANGES} {note}".strip(),
    )


def reaches_derived(*, note: str) -> DataProvenance:
    """Provenance for a count aggregated out of the REACHES file: grade B, no transcription."""
    return DataProvenance(
        grade=EvidenceGrade.B,
        source_id=REACHES_SOURCE_ID,
        locator=REACHES_EVENTS[1],
        note=(
            "Derived: events dated 1625-1644, located by the record's own coordinates, assigned to "
            "the nearest selected seat within the declared radius, and counted by the main event "
            "category of the nine-digit code from the REACHES coding guide. Only counts leave this "
            "project; the record file is not redistributed. " + note
        ).strip(),
    )


def declared(*, note: str) -> DataProvenance:
    """Provenance for a modelling decision: grade S, and the rule is in the note."""
    return DataProvenance(grade=EvidenceGrade.S, note=note)


def courier_derived(
    *,
    note: str,
    locator: tuple[str, str] = COURIER_ROUTES,
    grade: EvidenceGrade = EvidenceGrade.B,
) -> DataProvenance:
    """Provenance for a field derived from the courier-route layer.

    Grade ``B`` when the field is what the layer records (a station, a route segment, an
    adjacency), and ``C`` when the field is an inference *from* the layer - the trade graph, whose
    roads are documented and whose grain movement is ours.
    """
    return DataProvenance(
        grade=grade,
        source_id=CHGIS_SOURCE_ID,
        locator=locator[1],
        note=(
            f"{CHGIS_CITATION} Route and station geometry as published (EPSG:4326), linked "
            f"to the selected seats by nearest station within the declared radius. Sources: "
            f"{COURIER_SOURCES}. " + note
        ).strip(),
    )
