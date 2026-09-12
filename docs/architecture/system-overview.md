# System Overview

Status: P02 (space, time and climate skeleton). No households, markets, armies, rebels or
runtime-LLM decisions exist yet; the only spatial dataset in the repository is the toy
fixture, which is not history.
Binding rules: `.omp/RULES.md`. Source of truth for scope and phasing:
`docs/OMP_ENGINEERING_PLAN.md`.

## Purpose

A historical mechanism laboratory for the 1625–1644 Shaanxi–Henan crisis. It asks how
household survival, land and debt, grain markets, local elites, fiscal extraction, relief,
military pay, migration, desertion, and armed organization interact across scales, and under
what conditions local governance crosses from "difficult but sustainable" into
self-reinforcing systemic instability.

It is not a game, not LLM role-play of historical figures, and not a machine for producing
"probability the Ming collapsed = 83.7%".

## Simulation domain

| Dimension | Decision |
| --- | --- |
| Time | `1625-01 → 1644-12`, 240 monthly ticks; 1625–1626 warm-up, 1627+ shock period |
| Space | Shaanxi + Henan core; Shanxi, Huguang, Sichuan, Beizhili only as exits/links/external conditions |
| Population unit | Weighted household cohort, not individual households |
| Development scale | 3–5 counties, 200–500 cohorts, 5–20 elites, 5–10 merchants, 1–3 armies, 0–10 armed bands |
| Regional baseline | 50–100 county nodes, 2,000–5,000 cohorts, 100–300 elites, 100–300 merchants |

A cohort carries weight, land, labour, grain, silver, debt, rent, tax burden, social ties,
coping state, and migration state. It never represents a named household.

## Four layers

```text
MACRO           climate / central fiscal-military pressure
MESO            county government, army, market, elite, armed bands
LOCAL SOCIAL    county / market / credit / grain stock
MICRO           household cohorts, merchants, soldiers
```

Feedback crosses layers in both directions; a mechanism claim that only crosses one layer
direction is incomplete.

## Mechanism modules

| Module | Scope | Key requirement |
| --- | --- | --- |
| M1 Household survival | land, labour, grain, silver, debt, credit, ties | Explicit coping ladder (stored grain → discretionary cuts → borrowing → asset sale → land sale → temporary migration → household migration → army/band recruitment). No anger threshold. |
| M2 Market / credit / elite | county grain inventory, price, market access, transport cost, violence risk, credit supply; elite land, grain, silver, credit network, tax mediation, relief capacity, protection | Elite actions: lend, buy land, relieve, hide taxable resources, mediate tax, organize defense. |
| M3 Fiscal / governance | `TaxCollectionCapacity`, `InformationCapacity`, `ReliefCapacity`, `CoercionCapacity`, `LogisticsCapacity` | Tax decomposed into quota, collection effort, collection cost, actual receipts, arrears. Never one scalar `state_capacity`. |
| M4 Fiscal-military | army strength, food, pay due/received, arrears, morale, cohesion, desertion | Both loops: unrest → military demand → fiscal demand → extraction → household stress; and fiscal shortage → arrears → desertion → recruitment pool → armed groups. |
| M5 Armed organization | size, food, arms, mobility, cohesion, local support, ties, territorial access, actions | Starts as generic `ArmedBand`; consolidation into organizations is observed, never pre-named. |

## Networks

Three separate NetworkX graphs, because the same pair of places has different costs:
`G_trade` (trade cost), `G_migration` (migration cost), `G_military` (military movement cost).
A single county-adjacency graph is prohibited.

## Tick order

One tick = one month. Order is explicit, versioned, and tested — never Mesa's incidental
default ordering.

```text
01 climate update                    10 military finance
02 agricultural state                11 desertion
03 grain production / harvest        12 armed-group recruitment
04 household consumption             13 armed-group movement / actions
05 market clearing                   14 violence consequences
06 credit / debt                     15 institutional decisions
07 taxation                          16 bookkeeping
08 relief                            17 data collection
09 migration
```

## Randomness

One root `SeedSequence` splits into independent subsystem streams: `climate_rng`,
`household_rng`, `market_rng`, `migration_rng`, `military_rng`, `rebel_rng`, `decision_rng`.
This supports common random numbers for counterfactual comparison. A single global
`random.seed(...)` is prohibited.

## Provenance and outputs

Every run records `run_id`, `git_sha`, `engine_version`, `config_hash`, `parameter_hash`,
`root_seed`, `subsystem_seeds`, `scenario_id`, `policy_id`, `llm_enabled`, `llm_model_id`,
`llm_prompt_version`, `start_timestamp`.

```text
outputs/runs/<run_id>/
├── manifest.json              ├── county_timeseries.parquet
├── config.snapshot.yaml       ├── macro_timeseries.parquet
├── parameters.snapshot.parquet├── agent_events.parquet
├── decision_trace.jsonl       └── summary.json
```

The event log is a first-class artifact: tick, event, agent, region, trigger values, rule
version, RNG draw, and outcome. Any state change that matters must be explainable from it.

## Invariants

- grain cannot become negative; silver cannot appear without an explicit source;
- population_previous = population_current + deaths + net_outmigration ± explicit external flows;
- deserters leave the army population; recruits come from an eligible population pool;
- actual receipts ≤ collectible base under the defined rule;
- same code + config + seed + policy → same output, except live LLM decisions, whose traces
  must be recordable and replayable.

## Space, time and climate (P02)

### Nodes, not polygons

Space is a set of administrative seats with approximate catchments: no county polygons, no
area, no border geometry. The reasoning, the rejected alternatives and the costs are in
`docs/adr/0001-node-and-catchment-geography.md`.

| Concern | Module | Contract |
| --- | --- | --- |
| Nodes | `networks/nodes.py` | `CountyNode` (county or boundary), province, agrarian zone for counties, external roles for boundary nodes, optional **sourced** point with precision and uncertainty |
| Edges | `networks/edges.py` | `EdgeMetrics` (`distance_km > 0`, `cost > 0`, `capacity > 0`, `risk ∈ [0,1]`, all finite) plus per-graph `EdgeSemantics` |
| Graphs | `networks/trade.py`, `migration.py`, `military.py`, `graphs.py` | Three separate graphs; counties in every graph; each graph connected; boundary nodes only where their role allows; graph node sets differ |
| Dataset | `networks/dataset.py` | Versioned `spatial-dataset-v1`; node ids unique; endpoints exist; no duplicate edge; distance is pair-level and must agree across graphs while costs may differ |
| Real data | `networks/adapter.py` | One node table plus three edge tables, every row graded; a row without provenance is rejected, not defaulted |
| Toy fixture | `networks/fixtures.py` | Five county nodes (three loess dryland, two north China plain) and three boundary nodes, every value graded `S`; **not** geography |
| Calendar | `systems/calendar.py` | Per zone and month: crop phase and anomaly sensitivity; Gregorian months only; every entry grade `S` |
| Climate | `systems/climate.py` | `BaselineClimate`, `ObservedHistoricalClimate`, `SyntheticClimate`, and `ClimateSystem` (tick phase 01) |

### Climate forcing

A shock is a severity in `[0, 1]` for one node and month — a forcing, not a yield and not a
price. The production function (P03) turns it into crop outcomes, weighted by the calendar; the
climate layer does not contain a crop model.

| Mode | Behaviour | Rule version |
| --- | --- | --- |
| `baseline` | Always zero severity; consumes no randomness | `climate-baseline-v1` |
| `observed-historical` | Replays a sourced series; no randomness; fails closed on a gap; a series graded `S` is refused | `climate-observed-v1` |
| `synthetic` | Draws from `climate_rng` with declared parameters | `climate-synthetic-v1` |

Synthetic draws are taken **unconditionally** — occurrence first, magnitude second, for every
node and month in canonical node-id order — so changing a parameter changes what the draws
mean without shifting them. That is what makes common random numbers usable in the P10
counterfactuals, and `tests/regression/test_regression_seed.py` pins the draw sequence.

Each tick emits one `CLIMATE_SHOCK` event per county node, carrying `severity`, the calendar
`sensitivity`, their product as `impact`, the month, the two named draws (synthetic only), the
mode as `outcome` and the mode-specific `rule_version`. Boundary nodes receive no climate.

### Space and climate invariants

- a county node always has an agrarian zone, and a boundary node never does;
- assumed coordinates are impossible: a `NodeLocation` graded `S` is refused by the model;
- an edge endpoint must exist, and a boundary endpoint must declare the role its graph needs;
- a pair of places states one distance, whatever graph it appears in;
- every graph is connected and contains every county node;
- every zone used by a dataset has a calendar entry, or the run refuses to start;
- an observed series must be graded `A`–`D` and must cover every node-month it is asked for.

## Deterministic kernel (P01)

The kernel is history-free by design: it owns time, randomness, event recording, provenance
and output, and nothing else. Domain mechanisms attach to it as systems in later phases.

| Concern | Module | Enforced contract |
| --- | --- | --- |
| Configuration | `core/config.py` | Frozen Pydantic model, `extra="forbid"`, cross-field validation; runtime LLM off by default and, when enabled, restricted to `ustc-deepseek-v4.1`; `content_hash()` over canonical JSON |
| Time | `core/clock.py` | Zero-based monthly ticks, pure integer month arithmetic, `warmup`/`shock` split, out-of-window access raises |
| Randomness | `core/rng.py` | One root `SeedSequence` spawned into seven independent streams; 128-bit per-stream seed recorded in the manifest; a global `random.seed(...)` is prohibited |
| Events | `core/events.py` | Frozen events ordered by `(tick, seq)`; trigger values stored as a read-only mapping and canonical JSON; Parquet round-trip is lossless |
| Tick order | `core/tick.py` | `TickPhase` (17 phases) and `TICK_ORDER_VERSION = "tick-order-v1"`; the kernel refuses systems registered out of phase order |
| Driver | `core/kernel.py` | Registration order within the versioned phase order, per-tick clock marker event, macro index frame, simulation digest |
| Provenance | `core/manifest.py`, `evidence/provenance.py` | `RunManifest` (git SHA, dirty flag, engine version, config hash, root seed, subsystem seeds, scenario, policy, tick order version, LLM switch) and `RunSummary` (event count, simulation digest, wall-clock diagnostics) |
| Storage | `storage/tables.py`, `storage/run_store.py`, `storage/warehouse.py` | Atomically written Parquet/JSON/YAML artifacts; run directories keyed by run id; read access plus DuckDB SQL over the written files |

### What "reproducible" means here

- Same code + same config + same seed → byte-identical Parquet and YAML artifacts, and an
  identical `simulation_digest` (SHA-256 over the canonical form of every produced row).
- `RunManifest.created_at` and `RunSummary.duration_seconds` are wall-clock diagnostics and
  are excluded from `RunManifest.deterministic_digest()`; everything else in the manifest is
  provenance and is included.
- `run_id = <scenario>-<root_seed>-<config_hash[:12]>`, so repeating a configuration and
  seed targets the same directory and reproduces it instead of accumulating duplicates.
  Writing over a directory whose manifest has a different deterministic digest is refused
  (`RunConflictError`); pass a run label for a deliberate second run of the same config.
- With no systems registered, the kernel draws nothing: the seed changes run identity, not
  event content. Seeded determinism of *drawn* values is exercised by kernel tests that
  register a system bound to a stream.

### Run directory

```text
outputs/runs/<run_id>/
├── manifest.json             replay key
├── config.snapshot.yaml      the exact configuration that was hashed
├── macro_timeseries.parquet  per-tick index frame (clock columns in P01)
├── agent_events.parquet      the event log, ordered by (tick, seq)
└── summary.json              event count, simulation digest, wall-clock diagnostics
```

`parameters.snapshot.parquet`, `county_timeseries.parquet` and `decision_trace.jsonl` are
absent because no phase produces them yet; each arrives with the phase that produces it.

## Stack

Mesa 3 stable (not Mesa 4 alpha) · NetworkX · Polars + Arrow · DuckDB · Parquet · SALib
(Morris screening → Sobol) · PyMC (`Simulator` ABC/SMC) · scikit-learn · Mesa Solara ·
Python 3.12 · `uv`. Dependencies are added when a phase needs them, not in advance.

## Package layout

```text
src/late_ming_lab/
├── core/        config.py, clock.py, rng.py, events.py, tick.py, kernel.py, manifest.py,
│                hashing.py                       (implemented in P01)
├── actors/      households, elites, merchants, government, military, armed_groups
├── systems/     calendar.py, climate.py          (implemented in P02)
│                agriculture, households, markets, credit, taxation, relief,
│                migration, military_finance, insurgency, violence
├── networks/    nodes.py, edges.py, trade.py, migration.py, military.py, graphs.py,
│                dataset.py, adapter.py, fixtures.py   (implemented in P02)
├── policies/    base, rules, utility, random_policy, ustc_v41
├── evidence/    provenance.py (P01), grades.py (P02); registry, parameters (P08)
├── storage/     tables.py, run_store.py, warehouse.py  (implemented in P01)
├── calibration/ experiments/ analysis/ cli/ ui/
```

Implemented so far: `late_ming_lab/__init__.py`, `cli.py` (`--version`, `smoke-run`),
`core/`, `evidence/`, `networks/`, `systems/`, `storage/`. Everything else is created by the
phase that needs it.

## Phase roadmap

```text
P00 constitution   P05 fiscal/governance/relief   P10 ablation/sensitivity/counterfactual
P01 kernel         P06 military finance/bands     P11 USTC V4.1 decision layer
P02 space/time     P07 integrated crisis engine   P12 decision-policy robustness
P03 households     P08 historical evidence        P13 mechanism cards
P04 market/elite   P09 calibration/hold-out       P14 visualization/HPC/release
```

Each phase ends with a phase report, logical commits, a clean tree, and a stop.

## Boundaries

- The development LLM (OpenCode Go) and the runtime institutional-policy LLM (USTC DeepSeek
  V4.1) are strictly separate; see `docs/architecture/runtime-llm-boundary.md`.
- Evidence grading and the parameter ledger: `docs/epistemics/evidence-grades.md`.
- What simulation may and may not claim: `docs/epistemics/model-epistemics.md`.
- No geographic, UI, calibration, or framework expansion ahead of its phase.
