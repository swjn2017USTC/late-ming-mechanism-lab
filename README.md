# late-ming-mechanism-lab

晚明陕西—河南危机多层历史机制模拟 — a historical mechanism laboratory for the 1625–1644
Shaanxi–Henan crisis.

> Simulation is an argument, not evidence.

Not a game, not LLM role-play of historical figures, and not a machine for producing a
"probability the Ming collapsed". The product is a set of conditional, falsifiable mechanism
cards with explicit assumptions, parameter regions, ablation and sensitivity evidence.

## Status

P10 (Ablation / Sensitivity / Counterfactual) complete, on top of P09 (Calibration / Hold-out), P08
(Historical Evidence / Parameter Registry) and P07 (Integrated Crisis Engine). The repository holds a history-free deterministic kernel
(P01), a spatial–temporal–environmental skeleton (P02), weighted household cohorts with an explicit
coping ladder (P03), a county grain market with merchant houses and elite lending, land purchase and
private relief (P04), a county fiscal apparatus (P05) with state capacity kept as five separate
capacities and never one number, a garrison and armed bands (P06) — pay, rations, arrears, morale,
desertion, a shared recruit pool, raids, movement, suppression, split and merge — and now the
sandbox that connects them (P07): an explicit, validated monthly scheduler with a derived dependency
diagram, real migration (permanent moves with land abandoned, seasonal absences, exits from the
region), and a metric set covering distress, land concentration, migration, price dispersion,
receipts, the tax base, military arrears, desertion, armed groups and governance warning indicators.
Two spatial fixtures ship: the five-county toy and a twelve-county Shaanxi–Henan fixture; the
integrated experiment runs both for the full 1625–1644 window.
Mass-balance, double-entry, fiscal-accounting, people/food/war-material and migration invariants are
enforced in code and rebuilt from the event log in tests, and the whole sandbox is pinned by a
fixed-seed regression suite. There are still no tactics, no named leaders and no LLM decisions.

P08 built the chain from a simulation claim to the evidence behind it: 25 registered sources across
ten evidence clusters, 29 ledger claims, 102 parameter cards and 22 historical patterns, with the
referential chain enforced in both directions by tests (`docs/evidence/`). P09 then calibrated
against it without adding a number of its own: a prior exists only where a card declares a range and
its support **is** that range; the objective is a set of checks read off the event log in the
calibration window (1625–1634) and it refuses the other two thirds of the run; SMC over a PyMC
`Simulator` returns a particle set, never a best fit; and the eight patterns P08 reserved as
`hold-out` are scored afterwards from posterior predictive runs, with the results — including the
reserved claims the model contradicts — written into `docs/calibration/`. No mechanism, rule or
parameter value was changed to make a historical pattern come out.

P10 turned the model on itself: an experiment runner runs one declared baseline and nine named
mechanisms removed from it (drought, extraction escalation, military pay, relief, elite credit, trade
disruption, band merger, suppression, the migration gate) plus three two-way arms, all under common
random numbers; a Morris design screens every card-bounded parameter and a Sobol design then measures
the selected ones with second-order indices, so interactions are measured rather than assumed; and a
two-parameter grid shows the region rather than the curve. The reports under `docs/experiments/`
carry distributions rather than means — paired median differences with bootstrap intervals, Cliff's
deltas, collapse probabilities with Wilson intervals, the crossed-lines distribution behind the
breakdown line, and binned response curves with their curvature.

Everything shipped so far is an assumption, not history: both spatial fixtures and every cohort
endowment are graded `S` throughout, the shock experiment's severity axis is a scenario parameter,
never an estimate of a historical drought, and the governance indicators are declared reading
lines rather than evidence. Real geography enters only
through `networks/adapter.py` with provenance columns. Why space is nodes and catchments rather
than polygons: `docs/adr/0001-node-and-catchment-geography.md`.

Phase plan: `docs/OMP_ENGINEERING_PLAN.md`; current phase report: `docs/phase-reports/P10.md`.
Why the military actors are declared abstractions rather than tactics:
`docs/adr/0002-military-abstractions.md`; how the tick order and its dependencies are enforced and
drawn: `docs/architecture/system-dependency.md`.

```bash
uv run late-ming-lab smoke-run            # 240 ticks, 1625-01 → 1644-12, into outputs/runs/
uv run late-ming-lab smoke-run --ticks 24 --warmup 6 --seed 7
```

The toy shock experiment (five modelled severity levels over the households of the toy fixture)
is a library entry point; it writes its two analysis tables to `outputs/analysis/`:

```python
from late_ming_lab.experiments.household_shock import run_shock_experiment

experiment = run_shock_experiment()
print(experiment.distribution)  # severity × cohort class → distress distribution
experiment.write("outputs/analysis")
```

The calibration batch is two steps, because a report that cannot be regenerated from the artifact is
a claim nobody can check. The batch writes `outputs/calibration/<batch_id>/` (the particle set, its
manifest, the SMC stage diagnostics and the posterior predictive tables); the second step regenerates
the four documents under `docs/calibration/` from that directory:

```bash
uv run python -c "from late_ming_lab.experiments.calibration import run_calibration_batch; \
    run_calibration_batch('.')"
uv run python -c "from late_ming_lab.experiments.calibration import write_calibration_reports; \
    write_calibration_reports('.')"
```

The P10 experiment runner is the same two-step shape: run the three experiments (ablation, Morris
then Sobol, and the two-parameter grid) into `outputs/experiments/`, then regenerate the four reports
from those artifacts.

```bash
uv run python -c "from late_ming_lab.experiments.ablation import run_p10; run_p10('.')"
```

A run writes an immutable directory under `outputs/runs/<run_id>/` (manifest, config
snapshot, event log, macro index, summary). Same configuration + same seed reproduces the
artifacts byte for byte; repeating a run reuses its directory, and a directory holding a
different run is refused rather than overwritten.

## Setup

```bash
uv sync                 # Python 3.12 environment
cp .env.example .env    # runtime LLM stays disabled (USTC_LLM_ENABLED=0)
chmod 600 .env          # never committed; add the USTC key only when P11 requires it
```

## Checks

```bash
uv run late-ming-lab --version
uv run late-ming-lab smoke-run --output-root /tmp/lml-check
uv run pytest                   # offline; no live LLM access
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

`uv run pytest -m live_ustc` is the opt-in live USTC suite (P11+ only).

## Boundaries

- Development LLM (OpenCode Go) and runtime institutional-policy LLM (USTC DeepSeek V4.1) are
  strictly separate. Runtime policy is off by default and unavailable until P11.
- `.env` is gitignored; the USTC API key is never read, printed, or committed.
- Binding rules: `.omp/RULES.md` (sticky). Project context: `.omp/AGENTS.md`.

## Documentation

| Document | Content |
| --- | --- |
| `docs/OMP_ENGINEERING_PLAN.md` | Phase plan P00–P14, mechanisms, stack, discipline |
| `docs/architecture/system-overview.md` | Layers, modules, tick order, RNG, provenance, invariants |
| `docs/architecture/runtime-llm-boundary.md` | Dev vs runtime LLM contract |
| `docs/epistemics/model-epistemics.md` | What simulation may and may not claim |
| `docs/epistemics/evidence-grades.md` | A/B/C/D/S grades, parameter cards, evidence ledger |
| `docs/evidence/` | Generated: what the evidence base covers, how uncertain it is, where the gaps are |
| `docs/calibration/` | Generated: the frozen objective, the posterior, the mismatches, the held-out predictions |
| `docs/experiments/` | Generated: the ablations, the interactions, the sensitivity indices and the tipping grid |
| `docs/phase-reports/` | One report per phase |

Each phase ends with a report, logical commits, a clean tree, and a stop. Never start the next
phase unasked.
