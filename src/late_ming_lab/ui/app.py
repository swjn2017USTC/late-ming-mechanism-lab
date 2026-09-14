"""The artifact browser: a read-only Solara page over the runs, the batches and the mechanism cards.

```bash
uv run solara run src/late_ming_lab/ui/app.py --port 8876
```

Seven tabs, each reading one of the artifacts :mod:`late_ming_lab.ui.data` knows how to load:

```text
Map           the nodes of the source and their movement at one tick
Migration     households departed and exited, and the per-node net movement
Trade         the share of trade links still carrying grain, and the largest group's share
Armed groups  how many bands there are and how much of the armed men the largest holds
Time series   any two of the source's per-tick series, with the units they are measured in
Compare       two declared sources on the ticks they share, with their provenance differences
Mechanisms    docs/mechanisms/cards.yaml: every card's status, and one card's sixteen fields
```

The page never runs the model, never writes an artifact and never carries a credential. It reads
what the phases already wrote, and where a measurement needs something a run directory does not
record — the scenario's declared trade graph, the county-node roles, the governance reading
thresholds — it says which measurement is missing rather than substituting one.

The sources the Compare tab offers come from ``LATE_MING_UI_RUNS``, colon-separated; unset, they are
this repository's own P10 ablation and P12 robustness batches. A relative entry is read from the
repository root.
"""

# mypy: disable-error-code="no-untyped-call"
from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import polars as pl
from matplotlib.figure import Figure
from solara.components.alert import Info
from solara.components.datatable import DataFrame
from solara.components.markdown import Markdown
from solara.components.matplotlib import FigureMatplotlib
from solara.components.select import Select
from solara.components.slider import SliderInt
from solara.components.title import Title
from solara.core import component
from solara.hooks.use_reactive import use_reactive
from solara.lab.components.tabs import Tab, Tabs

from late_ming_lab.synthesis.report import BRIEF_FIELDS
from late_ming_lab.synthesis.schema import Condition, MechanismBook
from late_ming_lab.ui.data import (
    ComparisonResult,
    RunView,
    SeriesSpec,
    UiDataError,
    compare_runs,
    load_cards,
    load_run_view,
    series_catalog,
)

# The components are imported from the modules that define them rather than through ``solara.X``:
# the package re-exports them dynamically, which the type checker cannot follow, and a page whose
# attribute accesses it cannot check is a page where a misspelt component reaches the browser.

#: The repository this page reads: the cards from it, and any relative source under it.
REPOSITORY: Final[Path] = Path(__file__).resolve().parents[3]

#: The declared list of sources: colon-separated paths in this variable, or the two batches this
#: repository wrote, so the page opens on something that exists.
SOURCES_ENV: Final[str] = "LATE_MING_UI_RUNS"
DEFAULT_SOURCES: Final[tuple[str, ...]] = (
    "outputs/experiments/p10-ablations",
    "outputs/experiments/p12-robustness",
)

#: The label selector's "no label selected" entry. A batch is then combined over every arm it holds.
ALL_LABELS: Final[str] = "(every label combined)"

#: How wide the drawn figures are; the charts are read at desktop width beside their tables.
_FIGURE: Final[tuple[float, float]] = (9.0, 3.8)


def declared_sources() -> tuple[str, ...]:
    """The sources the selector offers: whatever the environment declares, else the repository's."""
    declared = tuple(
        entry.strip()
        for entry in os.environ.get(SOURCES_ENV, "").split(os.pathsep)
        if entry.strip()
    )
    return declared or DEFAULT_SOURCES


def _resolved(source: str) -> Path:
    """A declared source as a path, with a relative entry read from the repository root."""
    candidate = Path(source)
    return candidate if candidate.is_absolute() else REPOSITORY / candidate


@lru_cache(maxsize=8)
def _view(source: str, label: str | None) -> tuple[RunView | None, str | None]:
    """One source read, with a refusal kept as a message rather than raised into the page.

    The read is cached per source and label: run and batch outputs are immutable once written, and
    a page re-renders on every widget interaction, so re-reading a directory per slider step would
    be work with no effect. A source rewritten while the page is running needs a restart.
    """
    try:
        return load_run_view(_resolved(source), label=label), None
    except UiDataError as error:
        return None, str(error)


@lru_cache(maxsize=4)
def _comparison(left: str, right: str) -> tuple[ComparisonResult | None, str | None]:
    try:
        return compare_runs(_resolved(left), _resolved(right)), None
    except UiDataError as error:
        return None, str(error)


@lru_cache(maxsize=1)
def _book() -> tuple[MechanismBook | None, str | None]:
    try:
        return load_cards(REPOSITORY), None
    except UiDataError as error:
        return None, str(error)


def _specs(view: RunView, *, scope: str) -> tuple[SeriesSpec, ...]:
    """Every series of one scope. A tab draws the ones its own frame carries; see :func:`_Chart`."""
    return tuple(spec for spec in series_catalog(view) if spec.scope == scope)


def _ticks(view: RunView) -> list[int]:
    if "tick" not in view.series.columns:
        return []
    return [int(value) for value in view.series["tick"].to_list()]


def _nearest(ticks: Sequence[int], value: int) -> int:
    """The sampled tick a slider position falls on: the source reads on its own grid."""
    return min(ticks, key=lambda tick: abs(tick - value))


def _legend(spec: SeriesSpec) -> str:
    return f"{spec.label} [{spec.unit}]" if spec.unit else spec.label


def _unit_label(specs: Sequence[SeriesSpec]) -> str:
    units = sorted({spec.unit for spec in specs if spec.unit})
    return " / ".join(units) if units else "value"


def _frame_figure(frame: pl.DataFrame, specs: Sequence[SeriesSpec]) -> Figure:
    """A line per named column against the tick, with the legend carrying each unit."""
    figure = Figure(figsize=_FIGURE, layout="constrained")
    axes = figure.add_subplot(1, 1, 1)
    for spec in specs:
        if spec.key not in frame.columns:
            continue
        axes.plot(frame["tick"].to_list(), frame[spec.key].to_list(), label=_legend(spec))
    axes.set_xlabel("tick")
    axes.set_ylabel(_unit_label(specs))
    axes.grid(visible=True, alpha=0.3)
    if len(specs) > 1:
        axes.legend(loc="best", fontsize="small")
    return figure


def _node_figure(frame: pl.DataFrame, column: str, unit: str) -> Figure:
    """One line per node against the tick, or one bar per node when the frame carries no tick."""
    figure = Figure(figsize=_FIGURE, layout="constrained")
    axes = figure.add_subplot(1, 1, 1)
    nodes = [str(value) for value in sorted(set(frame["node_id"].to_list()))]
    if "tick" in frame.columns:
        for node in nodes:
            rows = frame.filter(pl.col("node_id") == node).sort("tick")
            axes.plot(rows["tick"].to_list(), rows[column].to_list(), label=node)
        axes.set_xlabel("tick")
        axes.legend(loc="best", fontsize="small")
    else:
        totals = [
            float(frame.filter(pl.col("node_id") == node)[column].sum() or 0.0) for node in nodes
        ]
        axes.bar(nodes, totals)
        axes.set_xlabel("node")
    axes.set_ylabel(f"{column} [{unit}]" if unit else column)
    axes.grid(visible=True, alpha=0.3)
    return figure


@component
def _Chart(frame: pl.DataFrame, specs: Sequence[SeriesSpec], *, missing: str) -> None:
    """A line per named series, drawn for the ones this frame actually carries.

    The candidate list is the view's catalog and the frame decides: a tab that draws the trade
    columns passes the per-tick series and the trade frame draws the two of them, so which columns
    belong to which tab is stated once, by the frame itself, rather than by a list here.
    """
    drawn = [spec for spec in specs if spec.key in frame.columns]
    if not drawn or frame.height == 0:
        Info(missing)
        return
    FigureMatplotlib(_frame_figure(frame, drawn))


def _has(frame: pl.DataFrame, *columns: str) -> bool:
    return all(name in frame.columns for name in columns)


@component
def _ReplicateTable(runs: pl.DataFrame, columns: Sequence[str], *, note: str) -> None:
    """A batch's per-replicate values for measurements it records once per run, not per tick."""
    present = [name for name in columns if name in runs.columns]
    if runs.height == 0 or not present:
        Info(note)
        return
    Markdown(note)
    keys = [name for name in ("label", "replicate") if name in runs.columns]
    DataFrame(runs.select([*keys, *present]))


@component
def _MapTab(view: RunView) -> None:
    nodes = view.county_nodes
    node = use_reactive(nodes[0] if nodes else "")
    ticks = _ticks(view)
    tick = use_reactive(ticks[-1] if ticks else 0)
    if not nodes:
        Info(
            "This source records no node-level migration, so there is nothing to place on the map."
        )
        return
    chosen = node.value if node.value in nodes else nodes[0]
    sampled = _nearest(ticks, tick.value) if ticks else None
    at_tick = (
        view.migration.filter(pl.col("tick") == sampled)
        if sampled is not None and "tick" in view.migration.columns
        else view.migration
    )
    Markdown(
        "The nodes are the ones this source's own migration frame attributes households to: a run "
        "directory does not record which of the model's nodes are counties, so the set is read "
        "from the frame rather than guessed from the node names."
    )
    Select("Node", values=list(nodes), value=node)
    if ticks:
        SliderInt(
            "Tick",
            value=sampled if sampled is not None else 0,
            min=ticks[0],
            max=ticks[-1],
            on_value=lambda value: tick.set(value),
        )
        if "tick" in view.migration.columns:
            Markdown(f"Reading the nearest sampled tick: **{sampled}**.")
        else:
            Markdown(
                "This source's node table is written once per run rather than per tick, so the "
                "figures below are the run's own totals; the slider moves the other tabs' series."
            )
    if _has(at_tick, "net_households") and at_tick.height:
        FigureMatplotlib(_node_figure(at_tick, "net_households", "households"))
    selected = at_tick.filter(pl.col("node_id") == chosen) if at_tick.height else at_tick
    if selected.height:
        DataFrame(selected)
    else:
        Info(f"This source records no movement for {chosen} at that tick.")


@component
def _MigrationTab(view: RunView) -> None:
    flow = _specs(view, scope="tick")
    departed = next((spec for spec in flow if spec.key == "households_departed"), None)
    exited = next((spec for spec in flow if spec.key == "households_exited"), None)
    totals = [
        (spec.label, float(view.series[spec.key].sum() or 0.0))
        for spec in (departed, exited)
        if spec is not None
    ]
    Markdown(
        "Departures and exits are read per tick from the run's log; a batch records the node table "
        "once per run, so a batch shows the run's own totals per node and no per-tick lines."
    )
    if totals:
        Markdown(
            "Over the whole window: "
            + "; ".join(f"**{label}** {value:,.0f}" for label, value in totals)
            + "."
        )
    _Chart(
        view.series,
        [spec for spec in (departed, exited) if spec is not None],
        missing="This source records no departure or exit column.",
    )
    if view.migration.height:
        FigureMatplotlib(_node_figure(view.migration, "net_households", "households"))
        DataFrame(view.migration)
    else:
        Info("This source records no node-level migration frame.")


@component
def _TradeTab(view: RunView) -> None:
    Markdown(
        "For a run these two are read from its own shipment log, by "
        "`analysis.outcomes.market_connectivity`'s rule: a link counts once it has carried grain, "
        "and a node with no active link is its own component. The denominators there are the "
        "scenario's declared trade graph, which a run directory does not record, so they are this "
        "run's own links and nodes (`links_observed`, `nodes_observed`, in the series tab). "
        "A batch records the declared measure once per run."
    )
    _Chart(
        view.trade,
        _specs(view, scope="tick"),
        missing="This source records no per-tick trade connectivity.",
    )
    _ReplicateTable(
        view.runs,
        ("market_active_link_share", "market_largest_component_share"),
        note=(
            "The same two measures as the batch's runs.parquet states them: one row per labelled "
            "replicate, on the scenario's declared trade graph."
        ),
    )


@component
def _ArmedGroupsTab(view: RunView) -> None:
    Markdown(
        "How many bands are standing and what share of all armed men the largest one holds. A run "
        "reads them from its own `BAND_STATE` log; a run that never recorded a band has no reading "
        "at all, which is not the same as a measured zero."
    )
    _Chart(
        view.bands,
        _specs(view, scope="tick"),
        missing="This source records no per-tick band columns.",
    )
    _ReplicateTable(
        view.runs,
        ("bands_at_end", "largest_band_share_end", "largest_band_share_max"),
        note=(
            "The batch's own end state per labelled replicate: bands standing, the largest band's "
            "share at the end and at its peak."
        ),
    )


@component
def _TimeSeriesTab(view: RunView) -> None:
    specs = _specs(view, scope="tick")
    keys = [spec.key for spec in specs]
    first = use_reactive(keys[0] if keys else "")
    second = use_reactive(keys[1] if len(keys) > 1 else "")
    if not keys:
        Info("This source records no per-tick series.")
        return
    left = first.value if first.value in keys else keys[0]
    right = second.value if second.value in keys else keys[0]
    Select("First series", values=keys, value=first)
    Select("Second series", values=keys, value=second)
    chosen = tuple(spec for spec in specs if spec.key in {left, right})
    if left == right:
        Info("Both selectors name the same column; change one to overlay two series.")
    FigureMatplotlib(_frame_figure(view.series, chosen))
    rows = "\n".join(
        f"| `{spec.key}` | {spec.label} | {spec.unit or '—'} | {spec.scope} |" for spec in specs
    )
    Markdown(f"| series | what it is | unit | scope |\n|---|---|---|---|\n{rows}")
    DataFrame(view.series)


@component
def _CompareTab() -> None:
    sources = declared_sources()
    left = use_reactive(sources[0])
    right = use_reactive(sources[1] if len(sources) > 1 else sources[0])
    comparison, error = _comparison(left.value, right.value)
    Markdown(
        f"The two sources come from `{SOURCES_ENV}` (colon-separated); unset, from this "
        "repository's own P10 and P12 batches. A relative entry is read from the repository root."
    )
    Select("Left", values=list(sources), value=left)
    Select("Right", values=list(sources), value=right)
    if comparison is None:
        Markdown(f"**Refused:** {error}")
        return
    Markdown(
        f"**{comparison.left.label}** and **{comparison.right.label}**, on the "
        f"{len(comparison.series)} series they share."
    )
    if comparison.series:
        DataFrame(comparison.aligned)
    else:
        Info("The two sources share no per-tick series, so there is nothing to align.")
    if comparison.manifest_differences:
        Markdown("### Provenance differences")
        Markdown(
            "Every manifest field the two sources state differently, so a comparison of two arms "
            "is never read as a comparison of the same code."
        )
        DataFrame(
            pl.DataFrame(
                [
                    {"field": field, "left": left_value, "right": right_value}
                    for field, left_value, right_value in comparison.manifest_differences
                ]
            )
        )
    else:
        Markdown("The two manifests agree on every field they state.")


def _field_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (tuple, list)):
        return "\n".join(f"- {_entry(entry)}" for entry in value)
    return str(value)


def _entry(value: object) -> str:
    if isinstance(value, Condition):
        return f"{value.statement} — {value.level}, {value.role}"
    return str(value)


@component
def _MechanismsTab() -> None:
    book, error = _book()
    first = book.cards[0].id if book is not None else ""
    selected = use_reactive(first)
    if book is None:
        Markdown(f"**No cards:** {error}")
        return
    Markdown(
        "The cards are the phase's claims, each with its status and the evidence behind it. A card "
        "marked SUPPORTED cites an intervention — an ablation or a counterfactual arm — not only "
        "quantities that were watched."
    )
    DataFrame(
        pl.DataFrame(
            [{"id": card.id, "name": card.name, "status": card.status.value} for card in book.cards]
        )
    )
    ids = [card.id for card in book.cards]
    chosen = selected.value if selected.value in ids else ids[0]
    Select("Card", values=ids, value=selected)
    card = book.by_id(chosen)
    Markdown(
        f"### {card.id} — {card.name}\n\n**Status:** {card.status.value}\n\n**Question:** "
        f"{card.question}"
    )
    for heading, attribute in BRIEF_FIELDS:
        Markdown(f"**{heading}**\n\n{_field_text(getattr(card, attribute))}")


@component
def _SourceTab(view: RunView | None, error: str | None, tab: Callable[[RunView], Any]) -> None:
    """A tab that needs a source: the refusal that came back, or the tab itself."""
    if view is None:
        Markdown(f"**Cannot read the source:** {error}")
        return
    tab(view)


@component
def Page() -> None:
    """The browser: pick a source, then a tab. Nothing on this page writes or runs anything."""
    Title("late-ming-mechanism-lab — artifact browser")
    sources = declared_sources()
    path = use_reactive(sources[0])
    label = use_reactive(ALL_LABELS)
    view, error = _view(path.value, None if label.value == ALL_LABELS else label.value)
    Markdown(
        "# late-ming-mechanism-lab — artifact browser\n\n"
        "Every tab reads an artifact this project already wrote: a run directory, a batch "
        "directory, or the mechanism cards. The page never runs the model, never writes "
        "anything and never reaches the network."
    )
    Select("Source", values=list(sources), value=path)
    labels = view.summary.get("labels", ()) if view is not None else ()
    if labels:
        options = [ALL_LABELS, *labels]
        label_value = label.value if label.value in options else ALL_LABELS
        Select("Label", values=options, value=label)
        Markdown(
            "A labelled arm is shown as its own view; every label combined is the batch's "
            "aggregate, and the summary below states which combination was applied."
        )
        if label_value == ALL_LABELS and view is not None:
            Markdown(f"Aggregation: {view.summary['aggregation']}.")
    if view is None:
        Markdown(f"**Cannot read `{path.value}`:** {error}")
    else:
        Markdown(
            f"**{view.label}** — {view.kind}, {view.series.height} ticks, "
            f"{len(view.county_nodes)} nodes, {view.runs.height} replicated runs."
        )
    with Tabs(lazy=True):
        with Tab("Map"):
            _SourceTab(view, error, _MapTab)
        with Tab("Migration"):
            _SourceTab(view, error, _MigrationTab)
        with Tab("Trade"):
            _SourceTab(view, error, _TradeTab)
        with Tab("Armed groups"):
            _SourceTab(view, error, _ArmedGroupsTab)
        with Tab("Time series"):
            _SourceTab(view, error, _TimeSeriesTab)
        with Tab("Compare"):
            _CompareTab()
        with Tab("Mechanisms"):
            _MechanismsTab()
