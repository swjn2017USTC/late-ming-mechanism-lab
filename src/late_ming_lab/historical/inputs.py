"""Readers for the two raw inputs the historical core is built from.

Both loaders are read-only, hash-checked against the snapshot manifest, and return tidy frames with
the columns the rest of the package expects. Nothing here decides anything: what counts as a seat,
which events are in the window, and how an event reaches a node are rules of the builder, and they
live there so they can be reviewed.

```text
CHGIS V6 county points   one row per administrative seat per date range (10,522 rows)
REACHES event records    one row per recorded event, with Gregorian dates, coordinates and a
                         nine-digit category code (148,132 rows, 1368-1911)
```
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

import geopandas as gpd
import polars as pl

from late_ming_lab.evidence.snapshots import RAW_ROOT, load_snapshots

#: Where the loaders read, relative to the repository root. Raw files are never tracked.
COUNTY_POINTS_ZIP: Final[str] = f"{RAW_ROOT}/chgis-v6/v6_time_cnty_pts_utf_wgs84.zip"
REACHES_DATA: Final[str] = f"{RAW_ROOT}/reaches/reachesv3.1data.txt"
REACHES_CODES: Final[tuple[str, ...]] = (
    f"{RAW_ROOT}/reaches/reachesv3.1codes-haz.txt",
    f"{RAW_ROOT}/reaches/reachesv3.1codes-met.txt",
    f"{RAW_ROOT}/reaches/reachesv3.1codes-other.txt",
)

#: The snapshot ids the loaders check their files against, so a rebuilt core names its bytes.
SNAPSHOT_FOR_FILE: Final[dict[str, str]] = {
    COUNTY_POINTS_ZIP: "chgis-v6-county-points",
    REACHES_DATA: "reaches-noaa-data-v31",
    f"{RAW_ROOT}/reaches/reachesv3.1codes-haz.txt": "reaches-noaa-codes-haz",
    f"{RAW_ROOT}/reaches/reachesv3.1codes-met.txt": "reaches-noaa-codes-met",
    f"{RAW_ROOT}/reaches/reachesv3.1codes-other.txt": "reaches-noaa-codes-other",
}


class InputError(RuntimeError):
    """Raised when a raw input is absent or does not hash to its snapshot record."""


def check_input(root: str | Path, relative: str) -> None:
    """Refuse to build from a file that is missing or does not match its snapshot record."""
    repository = Path(root)
    path = repository / relative
    if not path.is_file():
        raise InputError(
            f"{relative} is not present; run scripts/acquire/fetch_snapshots.py first. The raw "
            "files are not tracked, so a fresh clone has to acquire them."
        )
    snapshot_id = SNAPSHOT_FOR_FILE.get(relative)
    if snapshot_id is None:
        return
    manifest = load_snapshots(repository)
    record = manifest.require(snapshot_id)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != record.acquisition.sha256:
        raise InputError(
            f"{relative} does not hash to snapshot {snapshot_id}: {digest[:12]} against "
            f"{str(record.acquisition.sha256)[:12]}"
        )


def load_county_points(root: str | Path) -> pl.DataFrame:
    """CHGIS V6 time-series county points, one row per seat and date range.

    The zip holds the WGS84 variant of the layer, so ``X_COOR``/``Y_COOR`` are the published
    coordinates and no reprojection happens here. Present-day province is carried by
    ``PRES_LOC``, whose first three characters are the modern province name.
    """
    check_input(root, COUNTY_POINTS_ZIP)
    frame = gpd.read_file(f"zip://{Path(root) / COUNTY_POINTS_ZIP}")
    table = pl.from_pandas(frame.drop(columns=["geometry"]))
    return table.with_columns(
        pl.col("NAME_PY").cast(pl.Utf8).str.strip_chars().alias("name_py"),
        pl.col("NAME_CH").cast(pl.Utf8).str.strip_chars().alias("name_ch"),
        pl.col("PRES_LOC").cast(pl.Utf8).str.slice(0, 3).alias("present_province"),
        pl.col("TYPE_PY").cast(pl.Utf8).alias("seat_type"),
        pl.col("X_COOR").cast(pl.Float64, strict=False).alias("longitude"),
        pl.col("Y_COOR").cast(pl.Float64, strict=False).alias("latitude"),
        pl.col("BEG_YR").cast(pl.Int32, strict=False).alias("begin_year"),
        pl.col("END_YR").cast(pl.Int32, strict=False).alias("end_year"),
        pl.col("SYS_ID").cast(pl.Utf8).alias("sys_id"),
        pl.col("GEO_SRC").cast(pl.Utf8).alias("geo_source"),
    )


def load_reaches_events(root: str | Path) -> pl.DataFrame:
    """REACHES events with Gregorian dates, coordinates and the main category of their code.

    The file is a tab-separated table under a commented header. Only the fields the model uses are
    kept: the Gregorian start year and month, the event's own coordinates, and the first two digits
    of the nine-digit event code, which the coding guide defines as the main category.
    """
    check_input(root, REACHES_DATA)
    frame = pl.read_csv(
        Path(root) / REACHES_DATA,
        separator="\t",
        comment_prefix="#",
        quote_char=None,
        infer_schema_length=0,
    )
    return frame.select(
        pl.col("year_greg_st").cast(pl.Int32, strict=False).alias("year"),
        pl.col("mon_greg_st").cast(pl.Int32, strict=False).alias("month"),
        pl.col("place_longit").cast(pl.Float64, strict=False).alias("longitude"),
        pl.col("place_latitu").cast(pl.Float64, strict=False).alias("latitude"),
        pl.col("event_code").cast(pl.Utf8).str.slice(0, 2).alias("category"),
        pl.col("new_ID").cast(pl.Utf8).alias("record_id"),
    ).filter(pl.col("year").is_not_null())


def load_category_names(root: str | Path) -> dict[str, str]:
    """The coding guide's main-category labels, keyed by the two-digit code.

    Read from the three guide files, whose first two tab-separated columns are a label and a code;
    the guide is the only thing that makes a code mean 'Drought' rather than '30'.
    """
    names: dict[str, str] = {}
    for relative in REACHES_CODES:
        check_input(root, relative)
        lines = (Path(root) / relative).read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines:
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            label, code = parts[0].strip(), parts[1].strip()
            if len(code) == 2 and code.isdigit() and label and code not in names:
                names[code] = label
    return names
