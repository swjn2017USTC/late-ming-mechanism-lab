"""The historical core's invariants: provenance per field, separate graphs, honest edges.

These tests defend what the core claims about itself: that every stored fact carries a grade and a
source, that the three graphs are separate and each one respects the roles it may use, that a link
is either documented or explicitly labelled a connector, that the selected seats are on the
documented network, and that nothing the licences forbid has been written into the repository.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import polars as pl
import pytest

from late_ming_lab.evidence.grades import EvidenceGrade
from late_ming_lab.historical import edges as edges_module
from late_ming_lab.historical.build import (
    CLIMATE_TABLE,
    CORE_ROOT,
    NODES_TABLE,
    HistoricalCore,
    build_core,
    load_core,
)
from late_ming_lab.historical.selection import STATION_SNAP_RADIUS_KM, station_distances
from late_ming_lab.networks.edges import GraphKind

ROOT = Path(__file__).resolve().parents[2]
GRAPH_NAMES = ("trade", "migration", "military")
REQUIRED_ROLE = {
    "trade": "trade-link",
    "migration": "migration-exit",
    "military": "military-link",
}


@pytest.fixture(scope="module")
def core() -> HistoricalCore:
    """The core as built now, so the tests do not depend on a stale directory on disk."""
    return build_core(ROOT)


def _skip_if_raw_absent() -> None:
    if not (ROOT / "data/raw/private/chgis-v6/v6_time_cnty_pts_utf_wgs84.zip").is_file():
        pytest.skip("the raw snapshots are not present; run scripts/acquire/fetch_snapshots.py")


def test_the_core_is_reproducible_from_the_same_snapshots() -> None:
    _skip_if_raw_absent()
    first = build_core(ROOT)
    second = build_core(ROOT)
    assert first.manifest.built_from == second.manifest.built_from
    for name in ("nodes", "annual"):
        left = first.nodes if name == "nodes" else first.annual
        right = second.nodes if name == "nodes" else second.annual
        assert left.equals(right), name
    for graph in GRAPH_NAMES:
        assert first.edges[graph][1].equals(second.edges[graph][1]), graph


def test_every_stored_node_fact_carries_a_grade_and_a_source(core: HistoricalCore) -> None:
    nodes = core.nodes
    assert nodes.height >= 8, "the core must hold at least eight nodes or deliver a gap packet"
    for row in nodes.iter_rows(named=True):
        grade = EvidenceGrade(row["evidence_grade"])
        if grade in {EvidenceGrade.A, EvidenceGrade.B, EvidenceGrade.C, EvidenceGrade.D}:
            assert row["source_id"], row["node_id"]
            assert row["locator"], row["node_id"]
        assert row["note"], row["node_id"]
        assert row["latitude"] is not None and row["longitude"] is not None
        assert row["location_uncertainty_km"] is not None


def test_county_nodes_declare_a_zone_and_external_nodes_declare_roles(core: HistoricalCore) -> None:
    for row in core.nodes.iter_rows(named=True):
        if row["kind"] == "county":
            assert row["zone"] in {"loess-dryland", "north-china-plain"}, row["node_id"]
            assert row["external_roles"] == ""
        else:
            assert row["zone"] == ""
            assert row["external_roles"], row["node_id"]


def test_every_selected_seat_lies_on_the_documented_courier_network(core: HistoricalCore) -> None:
    _skip_if_raw_absent()
    stations = edges_module.load_stations(ROOT)
    counties = core.nodes.filter(pl.col("kind") == "county")
    snapped = station_distances(
        counties.select(pl.col("node_id").alias("sys_id"), "latitude", "longitude"),
        stations,
    )
    nearest = [float(value) for value in snapped["station_km"].to_list()]
    assert nearest and max(nearest) <= STATION_SNAP_RADIUS_KM


def test_the_three_graphs_are_separate_and_auditable(core: HistoricalCore) -> None:
    node_ids = set(core.nodes["node_id"].to_list())
    roles = {
        row["node_id"]: str(row["external_roles"]).split(",")
        for row in core.nodes.iter_rows(named=True)
        if row["kind"] == "external"
    }
    for graph in GRAPH_NAMES:
        candidates, accepted = core.edges[graph]
        assert candidates.height > 0
        candidate_pairs = {
            (row["source"], row["target"]) for row in candidates.iter_rows(named=True)
        }
        accepted_pairs = {(row["source"], row["target"]) for row in accepted.iter_rows(named=True)}
        assert accepted_pairs, graph
        # A documented link is a screened candidate; a connector may exceed the screening radius,
        # which is itself a finding about how far apart the sampled seats are.
        documented = {
            (row["source"], row["target"])
            for row in accepted.iter_rows(named=True)
            if not str(row["note"]).startswith("Connector")
            # An external node's link follows its own rule and carries no radius, so it is not
            # expected in the proximity-screened pool.
            and row["source"] not in roles
            and row["target"] not in roles
        }
        assert documented <= candidate_pairs, f"{graph}: a documented link was not a candidate"
        for row in accepted.iter_rows(named=True):
            assert row["source"] in node_ids and row["target"] in node_ids
            for endpoint in (row["source"], row["target"]):
                if endpoint in roles:
                    assert REQUIRED_ROLE[graph] in roles[endpoint], (
                        f"{graph} touches {endpoint}, which does not declare {REQUIRED_ROLE[graph]}"
                    )


def test_a_link_is_documented_or_labelled_a_connector(core: HistoricalCore) -> None:
    for graph in GRAPH_NAMES:
        _, accepted = core.edges[graph]
        for row in accepted.iter_rows(named=True):
            note = str(row["note"])
            if note.startswith("Connector"):
                assert row["evidence_grade"] == EvidenceGrade.S.value
                assert "not a documented link" in note
            elif row["evidence_grade"] in {
                EvidenceGrade.B.value,
                EvidenceGrade.C.value,
            }:
                # A sourced link: the source and the locator must be on the row.
                assert row["source_id"], f"{graph}: a graded link with no source"
                assert row["locator"], f"{graph}: a graded link with no locator"
            else:
                # A declared rule: grade S, and the note has to say what was declared.
                assert row["evidence_grade"] == EvidenceGrade.S.value
                assert "declared" in note or "inferred" in note, note[:80]


def test_every_graph_is_connected_after_the_connectors(core: HistoricalCore) -> None:
    import networkx as nx

    roles = {
        row["node_id"]: str(row["external_roles"]).split(",")
        for row in core.nodes.iter_rows(named=True)
        if row["kind"] == "external"
    }
    county_ids = set(core.nodes.filter(pl.col("kind") == "county")["node_id"].to_list())
    for graph in GRAPH_NAMES:
        allowed = county_ids | {
            node_id for node_id, declared in roles.items() if REQUIRED_ROLE[graph] in declared
        }
        instance: nx.Graph[str] = nx.Graph()
        instance.add_nodes_from(sorted(allowed))
        for row in core.edges[graph][1].iter_rows(named=True):
            instance.add_edge(row["source"], row["target"])
        assert nx.is_connected(instance), f"{graph} is not connected"


def test_the_climate_table_covers_the_window_and_only_counties(core: HistoricalCore) -> None:
    annual = core.annual
    county_ids = set(core.nodes.filter(pl.col("kind") == "county")["node_id"].to_list())
    assert set(annual["node_id"].unique().to_list()) == county_ids
    assert sorted(annual["year"].unique().to_list()) == list(range(1625, 1645))
    assert annual.height == len(county_ids) * 20
    assert annual["records"].sum() > 0
    assert annual.filter(pl.col("severity_index") > 1.0).height == 0


def test_the_selection_reports_what_it_excluded(core: HistoricalCore) -> None:
    selection = core.manifest.selection_report
    assert selection["eligible"] >= selection["selected"] >= 8
    assert selection["off_the_documented_courier_network"] >= 0
    assert selection["reachable"] == (
        selection["eligible"] - selection["off_the_documented_courier_network"]
    )
    assert selection["candidate_filters_account_for_candidates"], (
        "every candidate must be accounted for by a filter or by eligibility"
    )
    assert len(selection["omitted_eligible"]) == (selection["reachable"] - selection["selected"])
    assert selection["quota_by_province"], "the quota rule must be recorded"
    assert core.manifest.selection.limitation, "the rule's limitation must be stated"


def test_the_manifest_pins_the_bytes_and_the_tables(core: HistoricalCore) -> None:
    assert core.manifest.built_from, "the build must name its source snapshots"
    for digest in core.manifest.built_from.values():
        assert len(digest) == 64
    for name, digest in core.manifest.tables.items():
        assert len(digest) == 64
        assert (ROOT / CORE_ROOT / name).is_file()


def test_the_written_core_verifies_against_its_manifest(core: HistoricalCore) -> None:
    _skip_if_raw_absent()
    loaded = load_core(ROOT)
    assert loaded.manifest.dataset_id == "historical-core-v1"
    assert loaded.nodes.height == core.nodes.height
    assert loaded.annual.height == core.annual.height
    assert (ROOT / CORE_ROOT / NODES_TABLE).is_file()
    assert (ROOT / CORE_ROOT / CLIMATE_TABLE).is_file()


def test_no_raw_snapshot_is_tracked_and_no_record_is_transcribed(core: HistoricalCore) -> None:
    if not (ROOT / ".git").exists():
        pytest.skip("needs a git checkout to ask what is tracked")
    tracked = subprocess.run(
        ["git", "ls-files", "data/raw"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert tracked == "", f"raw snapshots must never be tracked: {tracked}"
    for frame in (core.nodes, core.annual, *(accepted for _, accepted in core.edges.values())):
        assert "record_id" not in frame.columns
        assert "source_text" not in frame.columns
    assert core.manifest.rights.strip()


def test_the_household_facing_paths_still_work_with_the_core(core: HistoricalCore) -> None:
    """A core that validates but cannot build the graphs is not a dataset."""
    from late_ming_lab.historical.build import core_dataset

    dataset = core_dataset(core)
    graphs = dataset.build()
    assert len(graphs.nodes.counties) == len(core.county_ids())
    for graph in (GraphKind.TRADE, GraphKind.MIGRATION, GraphKind.MILITARY):
        assert graphs.graph(graph).number_of_edges() > 0


def test_the_boundary_exits_are_seats_of_the_window(core: HistoricalCore) -> None:
    """A gateway seat has to exist in the window like any other node."""
    for row in core.nodes.filter(pl.col("kind") == "external").iter_rows(named=True):
        assert row["begin_year"] <= 1625 and row["end_year"] >= 1644, row["node_id"]
        assert "covers the window" in row["note"], row["node_id"]
    assert core.manifest.selection_report["exits"], "the report must name the exits it built"
