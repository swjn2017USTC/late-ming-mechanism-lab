# System Overview

Status: P07 (integrated crisis engine). The whole chain is wired — climate, agriculture,
households, market and credit, taxation and relief, migration, military finance, armed bands,
violence — under an explicit, validated monthly scheduler, and runs for the full 1625–1644 window on
a five-county and a twelve-county fixture. Inter-county military movement, trade disruption driven
by band activity, births and deaths, and runtime-LLM decisions do not exist. There are no tactics,
battles or named leaders, by decision — see `docs/adr/0002-military-abstractions.md`; the tick order
and its dependency rule are enforced and drawn in `docs/architecture/system-dependency.md`. Every
dataset and rate is an assumption: none of it is history.
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
| M4 Fiscal-military | army strength, food, pay due/received, arrears, morale, cohesion, desertion | Both loops: unrest → military demand → fiscal demand → extraction → household stress; and fiscal shortage → arrears → desertion → recruitment pool → armed groups. Implemented in P06: `actors/military.py`, `systems/military.py` (phases 10–14, 16). |
| M5 Armed organization | size, food, arms, mobility, cohesion, local support, ties, territorial access, actions | Starts as generic `ArmedBand`; consolidation into organizations is observed, never pre-named. Implemented in P06 as raids, movement, formation, recruitment, suppression, dissolution, split and merge — no tactics. |

## Networks

Three separate NetworkX graphs, because the same pair of places has different costs:
`G_trade` (trade cost), `G_migration` (migration cost), `G_military` (military movement cost).
A single county-adjacency graph is prohibited.

## Tick order

One tick = one month. Order is explicit, versioned, tested, and *drawable*: every system declares
the shared resources it reads and writes, `core.scheduler` refuses a registration that reads a
resource before the phase that writes it, and the diagram in `docs/architecture/system-dependency.md`
is generated from those declarations rather than maintained by hand.

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

## Household survival (P03)

### Cohorts, not families

`HouseholdCohortAgent` represents ``households`` households of one endowment archetype in one
county node. Five archetypes exist (landless labourer, tenant, poor/middle smallholder, wealthy
farmer); the cohort weight is a count of households, never a named family, and no
household-level inventory is invented.

Units, fixed once and used everywhere: grain in ``shi`` (石), silver in ``tael`` (两), land in
``mu`` (畝), time in months.

| Concern | Module | Contract |
| --- | --- | --- |
| Balance sheet | `actors/households.py` | weight, adults, land, grain, silver, debt, movable assets, season impact, coping stage, three eligibility flags |
| Cohort fixture | `actors/fixtures.py` | five archetypes per county node, every value graded `S`, marked as not social history |
| Production | `systems/agriculture.py` | `cultivated = min(land, adults × capacity)`, `yield_fraction = max(0, 1 − scale × Σ(severity × sensitivity))`, `harvest = cultivated × yield × yield_fraction` |
| Consumption and ladder | `systems/household_survival.py` | the ladder below, run once per cohort per month |
| Debt | `systems/household_survival.py` | interest accrues monthly; repayment only from silver above a reserve, or from grain above a year's need at harvest |
| Eligibility | `systems/household_survival.py` | trailing 12-month unmet share of the subsistence floor against declared thresholds |

### The coping ladder

```text
1 stored grain and in-kind wages — silver on hand belongs here too: it is stored wealth
2 discretionary consumption cut down to the floor
3 borrow: the request is recorded even when no capacity exists
4 sell movable assets
5 sell land
6 eligibility flags: temporary migration, permanent migration, recruitment
```

Silver is spent on food after the consumption cut and before borrowing, because a household that
cannot reach the floor first accepts eating less and only then pays for the rest. Grain bought on
the ladder is credited to the granary when it is bought and debited when it is eaten, so a
purchase feeds one month.

Whatever remains of the floor after the whole ladder is **unmet need** — a physical ledger
quantity, not a sentiment. The coping stage records the furthest *distress* step reached
(reduction, borrowing, assets, land, destitute); spending silver on hand is provisioning, not
distress, so it has no stage of its own. The stage is sticky within a crop year and resets after
a harvest reaching ``harvest_recovery_grain_ratio`` × the household's annual need (0.5 in the
default parameter set, not a full year), so an analysis column named ``ended_*`` means "ended the
window at or beyond this step", while ``unmet_ratio`` is the continuous measure of the month.
There is no anger, grievance or rebellion scalar in any of this, and P03 moves nobody: it records
who *could* move.

### Enforcement, not documentation

- every balance field is validated on assignment, so a negative grain, silver, land, assets or
  debt balance raises immediately;
- balances change only through accounting primitives that record their delta, and each delta is
  written into the event that explains it — the event log *is* the ledger;
- `check_balances` reconciles every balance against its recorded deltas, and the bookkeeping
  system runs it for every cohort every month, so a change made outside the ledger surfaces as
  an error rather than a gift;
- `tests/invariants/test_household_mass_balance.py` rebuilds every cohort's balances from the
  event log of a real run and compares them with the reported state, and replays the log to show
  that no balance ever went negative;
- silver may only enter a cohort from a recorded source: borrowing, movable-asset sale or land
  sale (the invariant test asserts exactly that set).

### Placeholders that P04 and P05 replace

The ladder needs prices and a lender to be exercisable, so P03 declares fixed, assumption-graded
substitutes: a reference grain price, a distress grain price, land collateral and distress
values, a loan-to-value cap, an interest rate, an in-kind wage that follows the local harvest,
and rent as a share of the harvest paid to an unmodelled landlord. None of it is a market: no
price responds to anything, no counterparty exists, and every one of these is a sensitivity
target until the evidence ledger replaces it.

### What the toy experiment shows

Five scenarios over the full 1625–1644 window differ only in the synthetic forcing. Mean unmet
share of the subsistence floor, by archetype:

| severity floor | landless | tenant | poor smallholder | middle smallholder | wealthy farmer |
| --- | --- | --- | --- | --- | --- |
| 0.0 (baseline) | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 0.2 (mild) | 0.004 | 0.000 | 0.000 | 0.000 | 0.000 |
| 0.4 (moderate) | 0.126 | 0.076 | 0.000 | 0.000 | 0.000 |
| 0.6 (severe) | 0.396 | 0.330 | 0.145 | 0.000 | 0.000 |
| 0.8 (extreme) | 0.618 | 0.564 | 0.319 | 0.136 | 0.000 |

The ordering is emergent, not encoded: no rule mentions a cohort class, and the gradient comes
from endowment, collateral and the ladder's order. The severity axis is a scenario parameter,
not an estimate of any historical drought — no calibration exists yet, and none is claimed.

Flow conservation is asserted separately from balance reconciliation, because a flow missing on
both sides of the ledger cancels out: `tests/invariants/test_household_mass_balance.py` checks
that everything reported as eaten was debited from a granary in the same event. That test fails
against the pre-fix code, where grain bought on the ladder was eaten but never debited.

## Market, credit and local elites (P04)

### What exists now

| Concern | Module | Contract |
| --- | --- | --- |
| County inventory and price | `systems/markets.py` | `MarketClearingSystem` posts one price per priced node each month; `price = reference × (target cover / inventory)^elasticity`, clamped to declared bounds; a node with no modelled demand posts the reference price |
| Intercounty trade | `systems/markets.py` | merchants arbitrage along `G_trade`: margin = destination − origin − transport cost; capacity, risk loss and exporter stock all bind; the loss is a separate `TRADE_LOSS` event |
| Unit mappings | `evidence/parameters.py` | P02 left `cost` and `capacity` dimensionless; P04 declares one cost unit = silver per shi moved and one capacity unit = shi per month, with zero capacity meaning autarky |
| Violence hook | `networks/disruption.py` | `TradeDisruption` scales a link's risk and capacity and can block it outright. Not yet driven by armed-band activity: P06 raids do not touch the trade graph, and an experiment has to supply the disruption explicitly (open item in the P06 report) |
| Merchant layer | `actors/merchants.py` | one house per node the trade graph reaches, with silver, grain and goods; every purchase and sale is logged from both sides |
| Elite layer | `actors/elites.py` | rent, lending, land purchase, relief, tax mediation; **claims are derived** from household debt, so borrower and lender records cannot drift |
| Migration | `systems/migration.py` | phase 09: eligible households leave for good (people, food, silver and movable property; their fields are abandoned), adults leave for a declared term and eat where they arrive, and movers to a boundary node leave the modelled population. Destination = the cheapest reachable county, the exit a last resort |
| Credit | `systems/elites.py` | `LocalCredit` lends against collateral, bounded by both the borrower's limit and the lender's silver |
| Relief and mediation | `systems/elites.py` | `EliteActionSystem` (phase 08) releases grain to cohorts whose measured distress exceeds a threshold, and asks a `TaxMediationPolicy` how much of a tax demand it would advance |
| Analysis | `analysis/concentration.py` | price dispersion, land distribution, land concentration, debt distribution, trade summary, first-distress ticks |

### The P03 placeholders are gone

P03 resolved shortfalls with fixed prices and a synthetic lender, and paid rent to nobody. All of
that is deleted: households now buy at the posted market price, borrow from the local elite at
that elite's own terms, sell land to it, and pay rent into its granary. `HouseholdParameters` no
longer has any price or credit field, and a test asserts that those five fields cannot come back.

### Measured answers, and what they are not

Questions A to D are run by `experiments/market_credit.py` on the toy economy over the full
window. They are statements about these rules, this topology and these endowments, not about
markets or elites in general, and nothing here is calibrated.

| Question | Change | Measured result |
| --- | --- | --- |
| A integration and dispersion | tradable capacity 0x to 10x, merchant stock 1x to 100x | integration **raised** mean max/min price dispersion from 1.79 to 2.93; more capacity lowered it only to 2.31; thin stocks (10x) raised it further; abundant stock (100x) pinned every node to the price floor |
| B transport cost and trade | cost multiplier 0.5x to 4x | shipped grain fell 6,470 → 5,438 → 2,728 → 0 shi, monotonically |
| C credit and collapse | lending on vs off under a severe shock | first below-floor month 38.5 vs 33.4; unmet share 0.253 vs 0.260; forced land sales 4,481 vs 11,874 mu |
| D credit and land | no credit, cheap credit, dear credit | elite land share 0.252 → 0.219 → 0.221; cohort land Gini 0.526 → 0.496 → 0.499; total claims 31k → 87k → 2.60M tael |

The A result is negative and is explained rather than hidden: arbitrage drains the selling node,
and with merchant stock a tenth of the declared target cover a single consignment is a large
share of it, so trade widens the spread instead of narrowing it. The price rule's fixed target
cover is the likely culprit and is recorded as an open item for P08/P09, not patched here.

The D result is likewise measured, not assumed: in this configuration credit *substitutes* for
distress sales, so concentration is lower with credit than without it, and a dearer rate adds a
little back while multiplying the claims stock thirtyfold — a placeholder pathology, since P04
has no bankruptcy, write-off or rescheduling rule.

## Fiscal extraction, governance and relief (P05)

### The county

`CountyGovernment` owns a treasury, a relief granary and five capacities. The capacities are
kept apart on purpose (RULES 4): `StateCapacity` has exactly five fields, no mean, no index and
no total, and a test asserts that no aggregate can be added unnoticed.

| Capacity | What it bounds | How it shows up |
| --- | --- | --- |
| `TaxCollectionCapacity` | the share of an assessed obligation the apparatus can reach | `reach = min(1, tax_collection + coercion × effort)` |
| `InformationCapacity` | how much of the true base it can see | hidden elite land = `elite_hidden_share × (1 − information)` |
| `ReliefCapacity` | the share of assessed relief need it can deliver | caps release against local need |
| `CoercionCapacity` | the extra reach it can force | raises reach; also raises what households must sell |
| `LogisticsCapacity` | what a unit of collection or relief costs | divides the cost of both |

### The tax ledger

Taxation is decomposed the way M3 requires, and every part is separately logged and reported:

```text
tax base        the land the county can see; elite land escapes in proportion to weak information
nominal quota   assessment_rate x base x assessed value per mu
collection      effort from the extraction policy, then reach from the five capacities
collection cost effort x quota / logistics, paid from the treasury
actual receipts what reached the treasury, through mediation, silver or liquidation
arrears         everything pursued and not taken, owed by households to the county
```

Collection walks a fixed order, reusing the machinery households already have for food: elite tax
mediation → silver on hand → forced grain sale down to a subsistence reserve → movable goods →
land, bought by the local elite → a loan against remaining collateral → arrears. The county's
arrears stock *is* the sum of its households' arrears, and a test reconciles the two.

### Official relief

Official relief is funded from the treasury: the county buys grain into its granary at the posted
market price, then releases it to households whose measured distress crosses a threshold, in
proportion to that distress, capped by `ReliefCapacity` and the granary, with the logistics cost
recorded. It is a different fiscal fact from private elite relief and the log says which is which.

### Elite tax mediation

P04 shipped a mediation interface with no demand behind it. P05 supplies the demand: the assessed
obligation is what an elite may advance, the advance becomes a claim on the household, and both
sides log it. The P04 placeholder knob is deleted rather than left beside the real path.

### What the pressure experiment shows, and what it refuses to claim

`experiments/extraction.py` sweeps the nominal pressure from 0.005 to 0.16 (a 32-fold range)
under both a fixed and an arrears-escalating policy, and reports measurements only — the curve has
no verdict column, and a test asserts its columns are exactly the declared measures.

| pressure | quota | receipts | receipts/quota | arrears | arrears per household | visible land | migration-eligible |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.005 | 74,191 | 20,396 | 0.275 | 9,280 | 0.44 | 180,750 → 175,655 | 0.52 |
| 0.02 | 296,102 | 64,489 | 0.218 | 53,952 | 2.97 | 180,750 → 175,228 | 0.48 |
| 0.08 | 1,184,327 | 194,081 | 0.164 | 279,649 | 17.13 | 180,750 → 175,489 | 0.44 |
| 0.16 | 2,360,336 | 273,923 | 0.116 | 670,212 | 42.58 | 180,750 → 174,803 | 0.36 |

Receipts rise with pressure, but far less than the quota does, and the unpaid remainder piles up
as arrears. That is the *data* an extraction-inversion hypothesis would need. **P05 does not claim
the mechanism exists**, and the report says what would be required before anyone may: receipts do
not actually fall in this range, the base erodes only through the food channel (no land was sold
for tax at any pressure, because the only land buyer — the local elite — had lent its silver
away), and arrears in P05 carry no consequence at all: nothing is seized, no interest accrues and
no distress follows from owing the county. Until arrears bite, an "extraction does not cause
flight" reading of this curve is an artefact of the model, not a finding — migration eligibility
falls across the sweep because higher receipts fund more relief.

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
├── actors/      households.py, merchants.py, elites.py, government.py, exchange.py,
│                ledger.py, fixtures.py            (implemented in P03-P05)
│                military, armed_groups
├── systems/     calendar.py, climate.py          (implemented in P02)
│                agriculture, households, markets, credit, taxation, relief,
│                migration, military_finance, insurgency, violence
├── networks/    nodes.py, edges.py, trade.py, migration.py, military.py, graphs.py,
│                dataset.py, adapter.py, fixtures.py   (implemented in P02)
├── policies/    base, rules, utility, random_policy, ustc_v41
├── evidence/    provenance.py (P01), grades.py (P02); registry, parameters (P08)
├── storage/     tables.py, run_store.py, warehouse.py  (implemented in P01)
├── analysis/    distress.py, concentration.py, fiscal.py  (P03-P05)
├── policies/    fiscal.py                          (implemented in P05)
├── experiments/ assembly.py, household_shock.py, market_credit.py,
│                extraction.py                      (P03-P05)
├── calibration/ cli/ ui/
```

Implemented so far: `late_ming_lab/__init__.py`, `cli.py` (`--version`, `smoke-run`),
`analysis/`, `actors/`, `core/`, `evidence/`, `experiments/`, `networks/`, `systems/`,
`storage/`. Everything else is created by the phase that needs it.

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
