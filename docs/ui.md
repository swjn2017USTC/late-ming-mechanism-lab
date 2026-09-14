# Artifact browser

Status: P14. A read-only Solara page over the artifacts the earlier phases already wrote. It adds
no measurement and runs no model.

```bash
uv run solara run src/late_ming_lab/ui/app.py --port 8876
```

Then open <http://127.0.0.1:8876>. The page needs no credentials, opens no connection other than its
own local socket, and writes nothing. The loader it draws from is
`src/late_ming_lab/ui/data.py`, which imports no UI framework and is exercised headlessly by
`tests/unit/test_ui_data.py`; the page is `src/late_ming_lab/ui/app.py`.

## What it reads

| Source | Why it is the source |
| --- | --- |
| A **run directory** — `manifest.json`, `summary.json`, the event log and the macro frame | What the kernel wrote: `storage/run_store.py` writes `agent_events.parquet` and `macro_timeseries.parquet`, and the phase brief calls the same two artifacts `events.parquet` and `macro.parquet`. Both spellings are accepted. |
| A **batch directory** — `runs.parquet`, `governance_timeline.parquet`, `migration_nodes.parquet`, `tax_base.parquet` | What the experiment runner wrote: one row set per labelled replicate. |
| `docs/mechanisms/cards.yaml` | The phase's cards, read by `synthesis.report.load_book`. |

A directory is read as a run when it holds a manifest and an event log, and as a batch when it holds
`runs.parquet` and a manifest. Anything else is refused with the names of what the directory does
hold, rather than opening as an empty page.

## What each tab reads

| Tab | Reads | From |
| --- | --- | --- |
| **Map** | the nodes and their movement at one tick | the per-tick, per-node migration frame; a batch's node table is written once per run, so there it is the run's own totals and the slider moves the other tabs instead |
| **Migration** | households departed and exited, and the per-node net movement | `MIGRATION_DEPARTURE`, `MIGRATION_ARRIVAL` and `MIGRATION_EXIT` records of a run's log, by `analysis.migration`'s attribution rule: a departure and an exit belong to the origin, an arrival to the destination, and `net_households` counts arrivals minus departures |
| **Trade** | the share of trade links still carrying grain, and the largest group's share | a run's own `TRADE_SHIPMENT` log, by `analysis.outcomes.market_connectivity`'s rule; a batch records the declared measure once per run, so it is shown per replicate |
| **Armed groups** | bands standing, and the largest band's share of armed men | a run's `BAND_STATE` log through `analysis.military.band_series`; a batch's `runs.parquet` columns per replicate |
| **Time series** | any two per-tick series, with the unit each is measured in | the columns of the view, listed by `series_catalog` |
| **Compare** | two declared sources on the ticks they share, and every manifest field they state differently | `LATE_MING_UI_RUNS` |
| **Mechanisms** | each card's status, and one card's sixteen fields | `docs/mechanisms/cards.yaml` |

`LATE_MING_UI_RUNS` is a colon-separated list of paths; a relative entry is read from the repository
root. Unset, it is this repository's own `outputs/experiments/p10-ablations` and
`outputs/experiments/p12-robustness`.

## What the loader does with a batch

A batch holds replicated runs, so a tab has to say what it is showing:

- With a label selected, the view is that arm's own runs.
- With *every label combined*, the view is combined over the labels and their replicates, and the
  page states which combination was applied in `summary["aggregation"]`. The rule is the phase's:
  **a count adds up and a share does not** — households, mu, shi, tael and crossed reading lines are
  summed; shares, rates and indices are averaged.
- The governance sample and the tax base are read on different grids (one yearly, one yearly dated
  by its last tick), and the batch's node table carries no tick at all. The loader joins what exists
  on the tick and leaves the holes the source itself leaves rather than interpolating between two
  readings.

## What it deliberately does not do

- **It never runs the model.** No tab constructs a scenario, a config or a kernel; every number on
  screen is read from a file that already exists.
- **It never writes.** No artifact is created, moved or rewritten; the page reads, and that is all.
- **It carries no credentials and reaches no network.** Nothing here touches `.env`, an API key, the
  USTC client or the runtime decision layer; the only socket is the one `solara run` opens for the
  browser.
- **It does not draw a measurement the source does not hold.** A run directory records neither the
  scenario's declared trade graph, nor which of the model's nodes are counties, nor the declared
  governance reading thresholds. The Trade tab therefore computes connectivity from the run's own
  shipment log and names its denominators `links_observed` / `nodes_observed`; the Map tab takes its
  nodes from the migration frame rather than guessing them from node names; and no tab shows a
  crossed-line count for a single run.
- **It does not compare sources that are not comparable.** Two views whose tick counts differ are
  refused — a divergence is not a comparison — and every manifest field the two sources state
  differently is listed beside the aligned frame, so a comparison of two arms is never read as a
  comparison of the same code.
- **It draws no verdict.** Statuses come from the cards unchanged; the page does not score a run,
  rank the mechanisms, or turn a series into a cause.
- **It is not a calibration or editing surface.** There is no input that changes a parameter, a
  policy or a scenario, and no way to launch a run from the page.

## Operational notes

- Each source is read once per process (the artifacts are immutable once written), so a source
  regenerated while the page is running needs a restart to be re-read.
- A run whose log carries no migration, no garrison and no bands renders the tabs it can and says
  which measurement is missing; an empty chart is "this source never recorded it", not a zero.
