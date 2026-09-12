# late-ming-mechanism-lab — project context

## What this repository is

A **historical mechanism laboratory**, not a game and not a stage for LLM role-play.
It builds an explainable, reproducible, calibratable agent-based model of the
1625–1644 Shaanxi–Henan crisis: how household survival, land and debt, grain markets,
local elites, fiscal extraction, relief, military pay, migration, desertion, and armed
organization interact across scales, and under what conditions local governance crosses
from "difficult but sustainable" to self-reinforcing systemic instability.

Central epistemological commitment:

```text
Simulation is an argument, not evidence.
```

Non-negotiable constraints are in `.omp/RULES.md` (sticky). This file supplies background,
layout, and conventions.

## Non-goals

- Reproducing "the fall of the Ming" as a target to be fitted.
- "One agent per real household" fake precision.
- 100,000 LLM peasants; LLM-driven physics.
- A national-scale model, a UI, or a calibrated crisis narrative before the core
  mechanisms are validated.
- Geographic, UI, or framework expansion ahead of the current phase's scope.

## Model shape

Four layers, top to bottom:

```text
MACRO           climate / central fiscal-military pressure
MESO            county government, army, market, elite, armed bands
LOCAL SOCIAL    county / market / credit / grain stock
MICRO           household cohorts, merchants, soldiers
```

- Window: `1625-01 → 1644-12`, **240 monthly ticks**; 1625–1626 warm-up, 1627+ shock period.
- Core space: Shaanxi + Henan. Neighbour nodes (Shanxi, Huguang, Sichuan, Beizhili) only as
  migration exits, grain-trade links, military movement links, and external conditions.
- Population unit: **weighted household cohort** (weight, land, labour, grain, silver, debt,
  rent, tax burden, social ties, coping state, migration state) — not individual households.
- Development scale: 3–5 counties, 200–500 cohorts, 5–20 elites, 5–10 merchants, 1–3 armies,
  0–10 armed bands. Regional baseline: 50–100 counties, 2,000–5,000 cohorts.
- Five mechanism modules: M1 household survival, M2 market/credit/elite, M3 fiscal/governance,
  M4 fiscal-military, M5 armed organization. See `docs/architecture/system-overview.md`.
- Three separate networks — `G_trade`, `G_migration`, `G_military` — never one adjacency graph.
- Tick order is explicit, versioned, and tested; never Mesa's incidental default order.
- RNG is split by subsystem (climate, household, market, migration, military, rebel, decision)
  from a root `SeedSequence`, so common random numbers support counterfactuals.

## Stack

Mesa 3 stable (not Mesa 4 alpha) · NetworkX · Polars + Arrow · DuckDB · Parquet · SALib
(Morris, Sobol) · PyMC (ABC / SMC) · scikit-learn · Mesa Solara · Python 3.12 · `uv`.

Do not add a framework because it might be useful later. Add it when a phase needs it.

## Layout

```text
.omp/            OMP constitution: AGENTS.md, RULES.md, config.yml, agents/
docs/            OMP_ENGINEERING_PLAN.md, architecture/, epistemics/, adr/,
                 mechanisms/, exec-plans/, phase-reports/
src/late_ming_lab/   Python package (core/, actors/, systems/, networks/, policies/,
                     evidence/, calibration/, experiments/, analysis/, storage/, cli/, ui/)
data/            raw/{public,private} → normalized/ → parameters/, historical_patterns/, scenarios/
sources/         registry/, primary/, literature/
experiments/     ablations/, sensitivity/, counterfactuals/, calibration/
outputs/         runs/ (immutable Parquet + manifest), analysis/, reports/
tests/           unit/, integration/, invariants/, regression/, policies/, fixtures/
```

## Commands

```bash
uv sync                       # environment (Python 3.12)
uv run pytest                 # default suite; never requires network or live LLM
uv run pytest -m live_ustc    # opt-in only; requires USTC credentials (P11+)
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run late-ming-lab --version
```

Run the narrow test that covers your change. Do not run the whole suite repeatedly mid-task.

## Engineering standards

- Correctness first, then maintainability six months out. Delete weightless code; refuse
  needless abstraction and speculative configuration.
- Every state change that matters must be explainable from the event log
  (tick, event, agent, region, trigger, rule version, rng draw, outcome).
- Invariants are enforced, not documented only: grain ≥ 0, silver only from explicit sources,
  population balance, deserters leave army population, recruits come from an eligible pool,
  receipts ≤ collectible base.
- Tests defend observable contracts. No tests that assert source text, wiring, or defaults.
- Provenance: every run records git SHA, config hash, parameter hash, root seed, subsystem
  seeds, scenario id, policy id, and LLM enablement/model id.

## LLM boundary (summary)

- Development-time coding/analysis: **OpenCode Go only** (`opencode-go/deepseek-v4.1-flash`,
  `mimo-v2.5`, `qwen3.8-flash`, `glm-5.3-flash`). Routing: `.omp/config.yml`.
- Runtime institutional policy: **USTC DeepSeek V4.1 only**, disabled by default, no tools,
  anonymized inputs, Pydantic-constrained outputs, fail-closed, no fallback, record/replay.
- Full contract: `docs/architecture/runtime-llm-boundary.md`.

## Agent routing

| Agent | Use for | Mode |
| --- | --- | --- |
| `repo-scout` | Locate files, existing interfaces, narrow context | read-only |
| `architect` | Cross-module interfaces, state transitions, RNG/event/storage/policy architecture | read-only |
| `implementer` | Scoped implementation + its tests | writes |
| `plan-critic` | Challenge assumptions, scope creep, missing failure modes, identifiability | read-only |
| `reviewer` | Independent review of diff/tests/invariants/acceptance criteria | read-only |

Route ordinary work to at most one agent; complex work to two. Do not chain
architect → reviewer → plan-critic → advisor for one change.

## Phase discipline

Work phase by phase from `docs/OMP_ENGINEERING_PLAN.md`: read the plan and the previous phase
report, write a ≤1-page scope with explicit non-goals and acceptance criteria, implement the
smallest valid version, test, document, write `docs/phase-reports/PXX.md`, inspect `git diff`,
commit, stop.
