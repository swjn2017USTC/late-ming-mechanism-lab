"""Coverage of the historical core: the window is materialised, and every gap is named."""

from __future__ import annotations

import re
from collections.abc import Sequence

import polars as pl
import pytest
from pydantic import ValidationError

from late_ming_lab.evidence.grades import EvidenceGrade
from late_ming_lab.historical.coverage import (
    CATEGORY_COLUMNS,
    FieldProvenance,
    edge_type_coverage,
    field_coverage,
    node_year_coverage,
    render_coverage_report,
    uncovered_periods,
)
from late_ming_lab.historical.provenance import CORE_DATASET_ID, WINDOW_END, WINDOW_START

_ANNUAL_DTYPES = {
    "node_id": pl.String(),
    "year": pl.Int32(),
    **{category: pl.Int64() for category in CATEGORY_COLUMNS},
}

_EDGE_DTYPES = {"evidence_grade": pl.String(), "source_id": pl.String()}


def _nodes(node_ids: Sequence[str], *, grade: str = "B") -> pl.DataFrame:
    return pl.DataFrame(
        {
            "node_id": list(node_ids),
            "kind": ["county"] * len(node_ids),
            "province": ["shaanxi"] * len(node_ids),
            "evidence_grade": [grade] * len(node_ids),
            "source_id": ["chgis-v6"] * len(node_ids),
            "locator": ["CHGIS v6 county points, seat point"] * len(node_ids),
        }
    )


def _annual(rows: Sequence[tuple[str, int, int, int, int, int]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "node_id": [row[0] for row in rows],
            "year": [row[1] for row in rows],
            "drought_events": [row[2] for row in rows],
            "famine_events": [row[3] for row in rows],
            "crop_events": [row[4] for row in rows],
            "pest_events": [row[5] for row in rows],
        },
        schema=dict(_ANNUAL_DTYPES),
    )


def _sections(report: str) -> dict[str, str]:
    """The report body under each heading, so a test can read one section without the rest."""
    sections: dict[str, str] = {}
    heading: str | None = None
    buffer: list[str] = []
    for line in report.splitlines():
        if line.startswith("#"):
            if heading is not None:
                sections[heading] = "\n".join(buffer)
            heading, buffer = line.strip(), []
        elif heading is not None:
            buffer.append(line)
    if heading is not None:
        sections[heading] = "\n".join(buffer)
    return sections


def test_the_whole_window_is_materialised_even_when_the_aggregate_is_sparse() -> None:
    nodes = _nodes([f"n{index:02d}" for index in range(20)])
    annual = _annual([("n00", 1625, 1, 0, 0, 0), ("n19", 1644, 0, 2, 0, 0)])

    coverage = node_year_coverage(nodes, annual)

    assert coverage.height == 20 * 20
    assert coverage.columns == [
        "node_id",
        "year",
        *CATEGORY_COLUMNS,
        "total_events",
        "covered",
        "evidence_grade",
        "source_id",
        "locator",
    ]
    assert coverage.get_column("year").min() == WINDOW_START
    assert coverage.get_column("year").max() == WINDOW_END
    pairs = coverage.select("node_id", "year").rows()
    assert pairs == sorted(pairs)
    assert coverage.filter(pl.col("covered")).height == 2

    recorded = coverage.filter((pl.col("node_id") == "n00") & (pl.col("year") == 1625)).row(
        0, named=True
    )
    assert (recorded["drought_events"], recorded["total_events"], recorded["covered"]) == (
        1,
        1,
        True,
    )
    assert (recorded["evidence_grade"], recorded["source_id"]) == ("B", "chgis-v6")
    assert recorded["locator"] == "CHGIS v6 county points, seat point"

    absent = coverage.filter((pl.col("node_id") == "n19") & (pl.col("year") == 1626)).row(
        0, named=True
    )
    assert (absent["total_events"], absent["covered"]) == (0, False)


def test_a_recorded_year_of_zeros_is_covered_and_an_absent_year_is_not() -> None:
    coverage = node_year_coverage(_nodes(["n00"]), _annual([("n00", 1625, 0, 0, 0, 0)]))

    assert coverage.height == 20
    recorded = coverage.row(0, named=True)
    absent = coverage.row(1, named=True)

    assert (recorded["year"], recorded["total_events"], recorded["covered"]) == (1625, 0, True)
    assert (absent["year"], absent["total_events"], absent["covered"]) == (1626, 0, False)


def test_uncovered_periods_collapse_each_run_and_leave_covered_nodes_out() -> None:
    annual = _annual([("b", 1626, 1, 0, 0, 0), ("b", 1627, 1, 0, 0, 0)])

    coverage = node_year_coverage(_nodes(["a", "b", "c"]), annual)

    assert uncovered_periods(coverage) == (
        ("a", 1625),
        ("b", 1625),
        ("b", 1628),
        ("c", 1625),
    )


def test_inputs_that_cannot_produce_a_grid_are_refused() -> None:
    nodes = _nodes(["n00"])
    partial = pl.DataFrame({"node_id": ["n00"], "year": [1625], "drought_events": [1]})

    with pytest.raises(ValueError, match="annual is missing famine_events"):
        node_year_coverage(nodes, partial)

    with pytest.raises(ValueError, match="more than one row for a node-year"):
        node_year_coverage(nodes, _annual([("n00", 1625, 1, 0, 0, 0), ("n00", 1625, 0, 1, 0, 0)]))

    with pytest.raises(ValueError, match="window 1644-1625 is empty"):
        node_year_coverage(nodes, _annual([]), start=WINDOW_END, end=WINDOW_START)


def test_edge_coverage_counts_candidates_accepted_and_their_evidence() -> None:
    candidates = pl.DataFrame({"source": ["a", "b", "c", "d"], "target": ["b", "c", "d", "a"]})
    accepted = pl.DataFrame(
        {
            "source": ["a", "b", "c"],
            "target": ["b", "c", "d"],
            "evidence_grade": ["B", "B", "S"],
            "source_id": ["chgis-v6", "chgis-v6", None],
        }
    )

    frame = edge_type_coverage(candidates, accepted, kind="trade")

    assert frame.height == 1
    row = frame.row(0, named=True)
    assert (row["graph"], row["candidates"], row["accepted"]) == ("trade", 4, 3)
    assert row["acceptance_share"] == pytest.approx(3 / 4)
    assert row["grades"] == "B:2, S:1"
    assert row["sources"] == "chgis-v6"


def test_a_graph_with_no_candidates_accepts_nothing_and_does_not_divide_by_zero() -> None:
    nothing = pl.DataFrame(schema=dict(_EDGE_DTYPES))

    frame = edge_type_coverage(nothing, nothing, kind="military")

    row = frame.row(0, named=True)
    assert (row["candidates"], row["accepted"], row["acceptance_share"]) == (0, 0, 0.0)
    assert (row["grades"], row["sources"]) == ("-", "-")


def test_field_coverage_renders_the_missing_share_and_refuses_impossible_claims() -> None:
    frame = field_coverage(
        [
            FieldProvenance(
                table="edges",
                field="distance_km",
                grade=EvidenceGrade.B,
                source_id="chgis-v6",
                locator="CHGIS v6 county points",
                basis="ground distance between two seat points",
                rows=40,
                missing=10,
            ),
            FieldProvenance(
                table="edges",
                field="risk",
                grade=EvidenceGrade.S,
                basis="declared risk class, not a measurement",
                rows=0,
                missing=0,
            ),
            FieldProvenance(
                table="nodes",
                field="zone",
                grade=EvidenceGrade.S,
                basis="agrarian zone assigned from the province and terrain",
                rows=20,
                missing=0,
            ),
        ]
    )

    assert frame.columns == [
        "table",
        "field",
        "grade",
        "source_id",
        "locator",
        "basis",
        "rows",
        "missing",
        "missing_share",
    ]
    assert frame.select("table", "field").rows() == [
        ("edges", "distance_km"),
        ("edges", "risk"),
        ("nodes", "zone"),
    ]
    assert frame.get_column("missing_share").to_list() == [0.25, 0.0, 0.0]

    with pytest.raises(ValidationError, match="requires both source_id and locator"):
        FieldProvenance(
            table="nodes",
            field="latitude",
            grade=EvidenceGrade.B,
            basis="seat point",
            rows=20,
            missing=0,
        )

    with pytest.raises(ValidationError, match="not a share of anything"):
        FieldProvenance(
            table="nodes",
            field="latitude",
            grade=EvidenceGrade.S,
            basis="seat point",
            rows=3,
            missing=4,
        )


def test_the_report_is_generated_names_its_inputs_and_counts_the_uncovered_node_years() -> None:
    nodes = _nodes(["n0", "n1", "n2", "n3", "n4"])
    annual = _annual([("n0", 1625, 2, 0, 0, 0), ("n0", 1626, 0, 0, 0, 0), ("n1", 1625, 1, 0, 0, 0)])
    trade = pl.DataFrame({"source": ["n0", "n1"], "target": ["n1", "n2"]})
    trade_accepted = pl.DataFrame(
        {
            "source": ["n0"],
            "target": ["n1"],
            "evidence_grade": ["B"],
            "source_id": ["chgis-v6"],
        }
    )
    nothing = pl.DataFrame(schema=dict(_EDGE_DTYPES))
    edges = {"trade": (trade, trade_accepted), "military": (nothing, nothing)}

    report = render_coverage_report(
        nodes=nodes,
        annual=annual,
        edges=edges,
        fields=[
            FieldProvenance(
                table="edges",
                field="distance_km",
                grade=EvidenceGrade.B,
                source_id="chgis-v6",
                locator="CHGIS v6 county points",
                basis="ground distance between two seat points",
                rows=1,
                missing=0,
            )
        ],
        start=1625,
        end=1626,
    )

    first_paragraph = report.split("\n\n")[0]
    assert "Generated" in first_paragraph
    assert "node table" in first_paragraph
    assert "annual event aggregate" in first_paragraph
    assert re.search(r"\b7 node-years are uncovered\b", first_paragraph)

    sections = _sections(report)
    assert set(sections) == {
        "## Window and completeness",
        "## Node-year coverage",
        "### Uncovered node-periods",
        "## Edge-type coverage",
        "## Field-level provenance",
    }
    assert CORE_DATASET_ID in sections["## Window and completeness"]
    assert "1625 to 1626 inclusive" in sections["## Window and completeness"]
    assert "node-years uncovered: 7 (70.0%)" in sections["## Window and completeness"]

    listed = [
        line
        for line in sections["### Uncovered node-periods"].splitlines()
        if line.startswith("- ")
    ]
    assert len(listed) == 4
    for node_id, first_year in (("n1", 1626), ("n2", 1625), ("n3", 1625), ("n4", 1625)):
        assert any(node_id in line and str(first_year) in line for line in listed)
    assert not any("n0" in line for line in listed)

    assert ("trade" in sections["## Edge-type coverage"]) and (
        "military" in sections["## Edge-type coverage"]
    )
    assert "0.0%" in sections["## Edge-type coverage"]
    assert "distance_km" in sections["## Field-level provenance"]
