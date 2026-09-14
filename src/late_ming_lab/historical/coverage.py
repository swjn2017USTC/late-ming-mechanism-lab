"""Coverage and missingness of the historical core: what the sources actually reach.

A core is only as good as what it covers, so every gap has to be countable and nameable rather
than smoothed over. This module computes three coverages from tables the caller passes in and
renders them as one document. It is pure: polars in, polars or markdown out, and it writes no
file, so a builder can call it and a test can read it without a repository.

```text
node_year_coverage       the full node x year grid, with the node-years nothing was read for
edge_type_coverage       candidate against accepted links for one graph, with grades and sources
field_coverage           every field of the derived tables, with its grade, source and missing count
uncovered_periods        the uncovered node-periods, so a caller can fail closed and name them
render_coverage_report   all of it as one markdown document
```

Two conventions matter more than the code:

- **Presence is a claim; absence is not.** A node-year appears in the caller's annual aggregate
  only when the climate record was read for it, so ``covered`` is true for a row that says "no
  event" and false for a node-year nobody looked at. Zero events and no record are different
  states, and neither the frame nor the report merges them.
- **A gap is named, not summarised.** :func:`uncovered_periods` returns each maximal run of
  consecutive uncovered years, and the report prints one line per run, so a reader can see which
  node and which years the core does not stand on.

The shapes this module reads, each refused rather than guessed at when it does not match:

```text
nodes     node_id, evidence_grade, source_id, locator ...   (the selected node table)
annual    node_id, year, drought_events, famine_events, crop_events, pest_events
edges     a candidate table and an accepted table per graph; accepted carries evidence_grade
          and source_id, because only the accepted links enter the core
```

A frame with no rows is a graph or a core with nothing in it, so the columns it would have carried
are not required; a frame with rows is checked for every column read from it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator

from late_ming_lab.evidence.grades import SOURCE_ID_PATTERN, SOURCED_GRADES, EvidenceGrade
from late_ming_lab.historical.provenance import (
    CORE_DATASET_ID,
    CORE_SCHEMA_VERSION,
    WINDOW_END,
    WINDOW_START,
)

#: The event categories the caller's annual aggregate carries and the coverage table reports, in
#: the order they are summed in. A builder that names them differently is refused, not guessed at.
CATEGORY_COLUMNS: Final[tuple[str, ...]] = (
    "drought_events",
    "famine_events",
    "crop_events",
    "pest_events",
)

#: The window total, derived from the categories rather than carried separately by the caller.
TOTAL_COLUMN: Final[str] = "total_events"

#: Grades from strongest to weakest, which is the order a rendered grade count is printed in.
GRADES_IN_ORDER: Final[tuple[EvidenceGrade, ...]] = (
    EvidenceGrade.A,
    EvidenceGrade.B,
    EvidenceGrade.C,
    EvidenceGrade.D,
    EvidenceGrade.S,
)

#: The grade letters this project grades with; anything else in a caller's frame is still printed.
_GRADE_NAMES: Final[frozenset[str]] = frozenset(grade.value for grade in GRADES_IN_ORDER)

_NODE_COLUMNS: Final[tuple[str, ...]] = ("node_id", "evidence_grade", "source_id", "locator")
_ANNUAL_COLUMNS: Final[tuple[str, ...]] = ("node_id", "year", *CATEGORY_COLUMNS)
_EDGE_COLUMNS: Final[tuple[str, ...]] = ("evidence_grade", "source_id")

_COVERAGE_DTYPES: Final[dict[str, pl.DataType]] = {
    "node_id": pl.String(),
    "year": pl.Int32(),
    **{category: pl.Int64() for category in CATEGORY_COLUMNS},
    TOTAL_COLUMN: pl.Int64(),
    "covered": pl.Boolean(),
    "evidence_grade": pl.String(),
    "source_id": pl.String(),
    "locator": pl.String(),
}

_EDGE_DTYPES: Final[dict[str, pl.DataType]] = {
    "graph": pl.String(),
    "candidates": pl.Int64(),
    "accepted": pl.Int64(),
    "acceptance_share": pl.Float64(),
    "grades": pl.String(),
    "sources": pl.String(),
}

_FIELD_DTYPES: Final[dict[str, pl.DataType]] = {
    "table": pl.String(),
    "field": pl.String(),
    "grade": pl.String(),
    "source_id": pl.String(),
    "locator": pl.String(),
    "basis": pl.String(),
    "rows": pl.Int64(),
    "missing": pl.Int64(),
}


class FieldProvenance(BaseModel):
    """What one field of one derived table claims, and how much of it is missing.

    ``basis`` is how the field is derived — a rule, or the column it is counted from. ``rows`` is
    how many rows the table holds and ``missing`` how many of them carry nothing for this field, so
    a field that is present but empty is visible as exactly that. Grades ``A`` to ``D`` still need
    both a source and a locator, exactly as :class:`~late_ming_lab.evidence.grades.DataProvenance`
    demands, so a table cannot list a field as sourced without saying where from.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    table: str = Field(min_length=1, max_length=64)
    field: str = Field(min_length=1, max_length=64)
    grade: EvidenceGrade
    source_id: str | None = Field(default=None, pattern=SOURCE_ID_PATTERN, max_length=128)
    locator: str | None = Field(default=None, max_length=512)
    basis: str = Field(min_length=1, max_length=1000)
    rows: int = Field(ge=0)
    missing: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_grade_and_counts(self) -> FieldProvenance:
        if self.grade in SOURCED_GRADES and (self.source_id is None or self.locator is None):
            raise ValueError(
                f"{self.table}.{self.field}: grade {self.grade.value} requires both source_id "
                "and locator (a field with no source may only be graded S)"
            )
        if self.missing > self.rows:
            raise ValueError(
                f"{self.table}.{self.field}: {self.missing} missing of {self.rows} rows is not a "
                "share of anything"
            )
        return self


def node_year_coverage(
    nodes: pl.DataFrame,
    annual: pl.DataFrame,
    *,
    start: int = WINDOW_START,
    end: int = WINDOW_END,
) -> pl.DataFrame:
    """One row per node and year in the window, with zeros and ``covered = False`` where absent.

    ``nodes`` supplies the grid and the grade of every node-year in it: the climate count is
    derived from the same seat selection, so the node's own provenance is the node-year's.
    ``annual`` is the caller's per-node-year aggregate; a row there means the record was read for
    that node-year, and a row of zeros therefore means "no event recorded" rather than "not read".

    Rows of ``annual`` that name a node outside the grid, or a year outside the window, are not
    part of the grid and are left out. A repeated ``(node_id, year)`` is refused, because it would
    silently hold one node-year twice.
    """
    if end < start:
        raise ValueError(
            f"the window {start}-{end} is empty, and coverage of no years would report as complete"
        )
    if nodes.height == 0:
        return pl.DataFrame(schema=dict(_COVERAGE_DTYPES))
    _require_columns(nodes, _NODE_COLUMNS, "nodes")
    _require_columns(annual, _ANNUAL_COLUMNS, "annual")

    grid = nodes.select(
        pl.col("node_id").cast(pl.String),
        pl.col("evidence_grade").cast(pl.String),
        pl.col("source_id").cast(pl.String),
        pl.col("locator").cast(pl.String),
    ).join(
        pl.DataFrame({"year": pl.Series(range(start, end + 1), dtype=pl.Int32())}),
        how="cross",
    )

    if annual.height:
        counted = annual.select(
            pl.col("node_id").cast(pl.String),
            pl.col("year").cast(pl.Int32),
            *(pl.col(category).cast(pl.Int64) for category in CATEGORY_COLUMNS),
            pl.lit(True).alias("_read"),
        )
        grid = grid.join(counted, on=["node_id", "year"], how="left")
        if grid.height != nodes.height * (end - start + 1):
            raise ValueError(
                "annual holds more than one row for a node-year in the window: the grid would "
                "count that node-year twice"
            )
    else:
        grid = grid.with_columns(
            *(pl.lit(0, dtype=pl.Int64).alias(category) for category in CATEGORY_COLUMNS),
            pl.lit(False).alias("_read"),
        )

    return (
        grid.with_columns(
            *(pl.col(category).fill_null(0) for category in CATEGORY_COLUMNS),
            pl.col("_read").fill_null(False).alias("covered"),
        )
        .with_columns(pl.sum_horizontal(CATEGORY_COLUMNS).alias(TOTAL_COLUMN))
        .select(*_COVERAGE_DTYPES)
        .sort("node_id", "year")
    )


def edge_type_coverage(
    candidates: pl.DataFrame,
    accepted: pl.DataFrame,
    *,
    kind: str,
) -> pl.DataFrame:
    """One row for one graph: proposed against accepted links, with how they are evidenced.

    ``kind`` is the graph the two tables belong to (``trade``, ``migration`` or ``military``) and
    becomes the ``graph`` column, because a candidate table is one graph's proposal list rather
    than a mixed frame. ``grades`` and ``sources`` are read from the accepted links: they are the
    ones that enter the core. A graph with no candidates accepts nothing, and its acceptance share
    is zero rather than undefined.
    """
    _require_columns(accepted, _EDGE_COLUMNS, "accepted")

    if accepted.height:
        grades = _grade_counts(accepted.get_column("evidence_grade").cast(pl.String).to_list())
        named = {source for source in accepted.get_column("source_id").to_list() if source}
        sources = ", ".join(sorted(named)) or "-"
    else:
        grades = "-"
        sources = "-"

    return pl.DataFrame(
        {
            "graph": [kind],
            "candidates": [candidates.height],
            "accepted": [accepted.height],
            "acceptance_share": [accepted.height / candidates.height if candidates.height else 0.0],
            "grades": [grades],
            "sources": [sources],
        },
        schema=dict(_EDGE_DTYPES),
    )


def field_coverage(rows: Sequence[FieldProvenance]) -> pl.DataFrame:
    """One row per listed field, with the share of the table's rows that carry nothing.

    A field over an empty table has no share to report, so ``missing_share`` is zero there: the
    count of missing rows is the honest number, and the share exists only to compare tables.
    """
    listed = list(rows)
    frame = pl.DataFrame(
        {
            "table": [row.table for row in listed],
            "field": [row.field for row in listed],
            "grade": [row.grade.value for row in listed],
            "source_id": [row.source_id for row in listed],
            "locator": [row.locator for row in listed],
            "basis": [row.basis for row in listed],
            "rows": [row.rows for row in listed],
            "missing": [row.missing for row in listed],
        },
        schema=dict(_FIELD_DTYPES),
    )
    return frame.with_columns(
        pl.when(pl.col("rows") > 0)
        .then(pl.col("missing") / pl.col("rows"))
        .otherwise(0.0)
        .alias("missing_share")
    ).sort("table", "field")


def uncovered_periods(coverage: pl.DataFrame) -> tuple[tuple[str, int], ...]:
    """The uncovered node-periods as ``(node_id, first year)``, one per unbroken run.

    A caller that must fail closed can name what it is short of from this alone: which node, and
    from which year its record stops. The run ends where the node's next covered year begins.
    """
    return tuple((node_id, first) for node_id, first, _ in _uncovered_runs(coverage))


def render_coverage_report(
    *,
    nodes: pl.DataFrame,
    annual: pl.DataFrame,
    edges: Mapping[str, tuple[pl.DataFrame, pl.DataFrame]],
    fields: Sequence[FieldProvenance],
    start: int = WINDOW_START,
    end: int = WINDOW_END,
) -> str:
    """The three coverages as one document: the window, the node-years, the edges, the fields.

    ``edges`` maps each graph kind to its ``(candidates, accepted)`` tables. The first paragraph
    says the document is generated, names every input it was computed from, and gives the exact
    number of uncovered node-years; the node-year section then lists each uncovered period by
    node, so nothing is hidden behind a count.
    """
    coverage = node_year_coverage(nodes, annual, start=start, end=end)
    fields_frame = field_coverage(fields)
    edge_rows = (
        pl.concat(
            [
                edge_type_coverage(candidates, accepted, kind=kind)
                for kind, (candidates, accepted) in edges.items()
            ]
        )
        if edges
        else pl.DataFrame(schema=dict(_EDGE_DTYPES))
    )
    runs = _uncovered_runs(coverage)
    uncovered = sum(last - first + 1 for _, first, last in runs)
    nodes_covered = coverage.get_column("node_id").n_unique()
    grades, sources = _node_evidence(coverage)

    years = end - start + 1
    headings = {
        "window": "## Window and completeness",
        "node_years": "## Node-year coverage",
        "uncovered": "### Uncovered node-periods",
        "edges": "## Edge-type coverage",
        "fields": "## Field-level provenance",
    }
    lines: list[str] = [
        f"Generated by `late_ming_lab.historical.coverage` from the node table "
        f"({_counted(nodes.height, 'row')}), the caller's annual event aggregate "
        f"({_counted(annual.height, 'row')}), the candidate and accepted edge tables of "
        f"{_counted(len(edges), 'graph')} "
        f"({_counted(int(edge_rows.get_column('candidates').sum()), 'candidate link')}, "
        f"{_counted(int(edge_rows.get_column('accepted').sum()), 'accepted link')}) and the field "
        f"provenance records ({len(fields_frame)}). Every count in this document is counted from "
        f"those inputs, not estimated. The window {start}-{end} of `{CORE_DATASET_ID}` holds "
        f"{coverage.height} node-years over {_counted(nodes_covered, 'node')}, of which "
        f"{uncovered} node-years are uncovered.",
        "",
        headings["window"],
        "",
        f"- core: `{CORE_DATASET_ID}`, schema `{CORE_SCHEMA_VERSION}`",
        f"- window: {start} to {end} inclusive, {years} years ({years * 12} monthly ticks)",
        f"- nodes in the grid: {nodes_covered}",
        f"- node-years expected: {coverage.height}",
        f"- node-years covered: {coverage.height - uncovered}"
        f"{_share_suffix(coverage.height - uncovered, coverage.height)}",
        f"- node-years uncovered: {uncovered}{_share_suffix(uncovered, coverage.height)}",
        f"- node grades: {grades}",
        f"- sources named by the node table: {sources}",
        f"- uncovered periods: {len(runs)}",
        "",
        headings["node_years"],
        "",
    ]
    per_node = (
        coverage.group_by("node_id")
        .agg(
            pl.col("year").len().alias("years"),
            pl.col("covered").sum().alias("covered"),
            (~pl.col("covered")).sum().alias("uncovered"),
            pl.col(TOTAL_COLUMN).sum().alias(TOTAL_COLUMN),
            pl.col("evidence_grade").first().alias("grade"),
            pl.col("source_id").first().alias("source"),
        )
        .sort("node_id")
    )
    lines += _table(
        ("node", "years", "covered", "uncovered", TOTAL_COLUMN, "grade", "source"),
        (
            (
                str(row["node_id"]),
                str(row["years"]),
                str(row["covered"]),
                str(row["uncovered"]),
                str(row[TOTAL_COLUMN]),
                str(row["grade"]),
                str(row["source"]) if row["source"] is not None else "-",
            )
            for row in per_node.iter_rows(named=True)
        ),
    )
    lines += ["", headings["uncovered"], ""]
    if runs:
        lines.append(
            f"{uncovered} node-years carry no record, in {_counted(len(runs), 'period')}, listed "
            "here in full:"
        )
        lines.append("")
        lines += [
            f"- {node_id}: {first}" if first == last else f"- {node_id}: {first}-{last}"
            for node_id, first, last in runs
        ]
    else:
        lines.append(f"none: all {coverage.height} node-years in the window carry a record.")
    lines += ["", headings["edges"], ""]
    lines += _table(
        ("graph", "candidates", "accepted", "acceptance share", "grades", "sources"),
        (
            (
                str(row["graph"]),
                str(row["candidates"]),
                str(row["accepted"]),
                f"{row['acceptance_share']:.1%}",
                str(row["grades"]),
                str(row["sources"]),
            )
            for row in edge_rows.iter_rows(named=True)
        ),
    )
    lines += ["", headings["fields"], ""]
    lines += _table(
        ("table", "field", "grade", "source", "locator", "rows", "missing", "missing share"),
        (
            (
                str(row["table"]),
                str(row["field"]),
                str(row["grade"]),
                str(row["source_id"]) if row["source_id"] is not None else "-",
                str(row["locator"]) if row["locator"] is not None else "-",
                str(row["rows"]),
                str(row["missing"]),
                f"{row['missing_share']:.1%}",
            )
            for row in fields_frame.iter_rows(named=True)
        ),
    )
    lines.append("")
    return "\n".join(lines)


def _uncovered_runs(coverage: pl.DataFrame) -> tuple[tuple[str, int, int], ...]:
    """Each maximal run of consecutive uncovered years as ``(node_id, first year, last year)``."""
    _require_columns(coverage, ("node_id", "year", "covered"), "coverage")
    if coverage.height == 0:
        return ()
    gaps = coverage.filter(~pl.col("covered")).select("node_id", "year").sort("node_id", "year")
    runs: list[tuple[str, int, int]] = []
    current: str | None = None
    first = 0
    last = 0
    for node_id, year in gaps.iter_rows():
        if node_id == current and year == last + 1:
            last = year
        else:
            if current is not None:
                runs.append((current, first, last))
            current, first, last = node_id, year, year
    if current is not None:
        runs.append((current, first, last))
    return tuple(runs)


def _node_evidence(coverage: pl.DataFrame) -> tuple[str, str]:
    """The grades and the sources of the grid's nodes, each named once."""
    if coverage.height == 0:
        return "-", "-"
    distinct = coverage.unique(subset=["node_id"], keep="first")
    grades = _grade_counts(distinct.get_column("evidence_grade").to_list())
    named = {source for source in distinct.get_column("source_id").to_list() if source}
    return grades, ", ".join(sorted(named)) or "-"


def _grade_counts(grades: Sequence[str]) -> str:
    """A rendered grade count in grade order, e.g. ``B:12, S:5``; ``-`` when nothing is graded."""
    counts = Counter(grades)
    known = [(grade.value, counts.get(grade.value, 0)) for grade in GRADES_IN_ORDER]
    unknown = sorted((name, count) for name, count in counts.items() if name not in _GRADE_NAMES)
    rendered = ", ".join(f"{name}:{count}" for name, count in (*known, *unknown) if count)
    return rendered or "-"


def _share_suffix(part: int, whole: int) -> str:
    return f" ({part / whole:.1%})" if whole else ""


def _counted(count: int, noun: str) -> str:
    """``3 rows`` or ``1 row``: a generated document should not pluralise a count of one."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _require_columns(frame: pl.DataFrame, columns: Sequence[str], what: str) -> None:
    """Refuse a frame that carries rows but not the columns they are read through."""
    if frame.height == 0:
        return
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(
            f"{what} is missing {', '.join(missing)}; it carries {', '.join(frame.columns)}"
        )


def _table(header: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    """A markdown table, the way every other report in this package renders one."""
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines
