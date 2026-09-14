# late-ming-mechanism-lab

晚明陕西—河南危机多层历史机制模拟 — a historical mechanism laboratory for the 1625–1644
Shaanxi–Henan crisis.

> **Simulation is an argument, not evidence.**
>
> Nothing in this repository is a finding about the past. Every number the model produces is a
> statement about *this model under a declared configuration*: the spatial fixtures are synthetic,
> the cohort endowments are graded `S` (assumption) throughout, the climate severity is a scenario
> knob rather than a reconstruction, the governance indicators are declared reading lines, and the
> priority weights are declared, not estimated. The model's job is to make assumptions explicit
> enough to argue with — mechanism cards with conditions, counterexamples and falsifiable
> predictions — and then to say which of them the evidence actually supports, which is what
> `docs/mechanisms/` does. Any sentence that reports a simulation outcome as a historical fact is a
> misuse of this repository.

Not a game, not LLM role-play of historical figures, and not a machine for producing a
"probability the Ming collapsed". The product is a set of conditional, falsifiable mechanism cards
with explicit assumptions, parameter regions, ablation and sensitivity evidence.

## Quick start

```bash
uv sync                                   # Python 3.12 environment
uv run late-ming-lab doctor               # python, uv.lock, artifacts, secret rules
uv run late-ming-lab run --ticks 24 --warmup 6    # the kernel, into outputs/runs/
uv run late-ming-lab run --scenario data/scenarios/demo.yaml   # the declared demo
uv run late-ming-lab analyze outputs/runs/<run_id>            # headline numbers of a run
uv run late-ming-lab bench                # measure the model, write outputs/reports/benchmark.md
uv run late-ming-lab ui                   # serve the artifact browser on 127.0.0.1:8876
uv run pytest                             # the offline suite
```

The declared demo is the whole thing in one command: the medium sandbox over the full 240-tick
window, with the seed and the digest recorded in `data/scenarios/demo.yaml`. If the run no longer
reproduces the recorded digest, `run --scenario` fails rather than printing a different number
nobody notices.

## Architecture

```text
MACRO          climate / central fiscal-military pressure
MESO           county government, army, market, elite, armed bands
LOCAL SOCIAL   county / market / credit / grain stock
MICRO          household cohorts, merchants, soldiers
```

- **Kernel** (`core/`): a deterministic monthly clock, RNG streams split by subsystem from one root
  `SeedSequence`, an append-only event log, and an explicit, validated tick order
  (`docs/architecture/system-dependency.md`). Same code, configuration and seed reproduce the same
  artifacts byte for byte.
- **Systems** (`systems/`, `actors/`, `networks/`): household survival and the coping ladder; the
  grain market, credit and elites; the county fiscal apparatus with state capacity kept as five
  separate capacities; the garrison and armed bands; migration over three separate networks
  (`G_trade`, `G_migration`, `G_military`).
- **Artifacts**: a run writes an immutable directory under `outputs/runs/<run_id>/` (manifest,
  config snapshot, event log, macro index, summary); an experiment batch writes its tables and
  manifest under `outputs/experiments/<batch>/`; a calibration batch under
  `outputs/calibration/<batch>/`. Documents under `docs/` are generated from those artifacts, never
  hand-written beside them.
- **Surfaces** (`cli.py`, `ui/`): nine commands — `run`, `replay`, `experiment`, `calibrate`,
  `analyze`, `doctor`, `bench`, `batch`, `ui` — and a Solara browser over the artifacts (county
  nodes, migration, trade, armed groups, time series, run comparison, mechanism cards). The UI reads
  artifacts and **never runs the model**.
- **Runtime decision layer** (`policies/`): one bounded interface, an audited anonymized observation,
  a validated decision and a trace; the live model is USTC DeepSeek V4.1 only, disabled by default,
  with no fallback and a replay path that runs offline (`docs/architecture/runtime-llm-boundary.md`).

## Reproduction

```bash
uv run late-ming-lab run --scenario data/scenarios/demo.yaml --output-root /tmp/demo
uv run late-ming-lab analyze /tmp/demo/<run_id>
```

A run records its git SHA, config hash, parameter hash, root seed, subsystem seeds, scenario id,
policy id, and LLM enablement in `manifest.json`, plus a `summary.json` carrying the simulation
digest. Re-running the same configuration and seed reproduces the same directory; a directory holding
a different run is refused rather than overwritten.

Every generated document is regenerable from its artifact:

```bash
uv run late-ming-lab experiment mechanisms      # regenerate the cards and the synthesis
uv run late-ming-lab analyze outputs/experiments --report   # regenerate the experiment reports
uv run late-ming-lab calibrate --predictive && uv run late-ming-lab analyze outputs/calibration --report
```

## HPC guide

The rules the batch layer is built to keep:

```text
compute nodes need no network       the batch module's import graph contains no transport
no API key is ever uploaded         doctor warns by name and never prints a value
no runtime LLM on a compute node    the Slurm template exports USTC_LLM_ENABLED=0
LLM decisions are recorded online   and replayed from fixtures on the cluster
every task has its own seed         seed = base_seed + array index, written into its manifest
a failed task can be re-run         tasks are idempotent and failure-isolated
```

```bash
# on the login node: plan, then render a Slurm array script from the plan
uv run late-ming-lab batch plan --family integrated --replicates 200 --base-seed 20260914 \
    --root outputs/batches
uv run python -c "from late_ming_lab.experiments.batch import load_plan; \
  from late_ming_lab.hpc.slurm_array import render_slurm_script; \
  plan = load_plan('outputs/batches/<batch_id>'); \
  print(render_slurm_script(plan, partition='normal', walltime='00:15:00', cpus=1, \
      concurrency=8, seconds_per_task=10.0))" > submit.sh
sbatch submit.sh

# one array task (the script does this), then merge what finished
uv run late-ming-lab batch run --plan outputs/batches/<batch_id> --task-index "$SLURM_ARRAY_TASK_ID"
uv run late-ming-lab batch merge --plan outputs/batches/<batch_id>
```

The array script is rendered from the plan rather than written by hand: its `--array` bound is the
task count, its per-task time limit is the measured cost times a declared safety factor (refused at
render time if it would not fit the walltime ceiling the operator declares), and each task writes its
own manifest, so a re-run of one index is a local operation. `merge` concatenates the
completed tasks, records the missing and failed indices in `merge.json`, and never imputes a row for a
task that did not run. Run `late-ming-lab doctor` on the node before submitting: it checks the
interpreter, the lock file against `pyproject.toml`, the artifact directories and the secret rules,
and fails closed.

A batch that needs model-backed decisions records them where the network is, and replays them here:

```bash
uv run late-ming-lab replay --fixtures tests/fixtures/llm --ticks 48   # offline, no credential
```

With no recorded fixtures the command fails closed and says so — the decision layer never answers a
prompt it has no recorded exchange for, and there is no fallback model.

## Performance

`uv run late-ming-lab bench` measures the declared workload (the medium sandbox, 240 ticks) and
compares it against declared thresholds, writing `outputs/reports/benchmark.md` with the profile of
the same run. On the development machine (Apple M4, Python 3.12) the measurement is about 10 seconds,
~24 ticks per second, and ~900 MiB peak resident memory; the enforced development bounds sit below
that with headroom (>= 5 ticks/s, <= 120 s, <= 2048 MiB), and the cluster budget (<= 600 s and
<= 4096 MiB per task) is what the Slurm template sizes its walltime from. The dev set is enforced by
`bench --enforce`; the cluster set is a declared budget, because no cluster was available to this
phase and it says so rather than implying otherwise.

## Setup

```bash
uv sync                 # Python 3.12 environment
cp .env.example .env    # runtime LLM stays disabled (USTC_LLM_ENABLED=0)
chmod 600 .env          # never committed; add the USTC key only for a live run
uv run late-ming-lab doctor
```

## Checks

```bash
uv run late-ming-lab --version
uv run late-ming-lab doctor
uv run late-ming-lab bench --enforce
uv run pytest                   # offline; no live LLM access
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

`uv run pytest -m live_ustc` is the opt-in live USTC suite (P11+ only); it refuses rather than skips
when the gate is closed.

## Where the project is

P14 (Visualization / HPC / Release Candidate) complete, tagged `v0.1.0-rc1`, on top of P13
(Mechanism Discovery / Mechanism Cards), P12 (Decision-Policy Robustness, runtime arm refused by
P11's gate), P11 (the runtime decision layer, live model **closed**), P10 (Ablation / Sensitivity /
Counterfactual), P09 (Calibration / Hold-out), P08 (Historical Evidence / Parameter Registry) and
P07 (Integrated Crisis Engine). P01–P06 built the kernel, the space and time, household survival, the
market and elites, the fiscal apparatus, and the garrison and armed bands.

P08 built the chain from a simulation claim to the evidence behind it: 25 registered sources across
ten evidence clusters, 29 ledger claims, 102 parameter cards and 22 historical patterns, with the
referential chain enforced in both directions by tests (`docs/evidence/`). P09 calibrated against it
without adding a number of its own: a prior exists only where a card declares a range and its support
**is** that range; the objective reads the event log in the calibration window (1625–1634) and
refuses the other two thirds of the run; SMC over a PyMC `Simulator` returns a particle set, never a
best fit; and the eight patterns P08 reserved as `hold-out` are scored afterwards from posterior
predictive runs, with the results — including the reserved claims the model contradicts — written into
`docs/calibration/`.

P10 turned the model on itself: one declared baseline and nine named mechanisms removed from it plus
three two-way arms under common random numbers; a Morris screen over every card-bounded parameter and
a Sobol design with second-order indices; and a two-parameter grid that shows the region rather than
the curve. P11 built the runtime decision layer and then refused to use it: the configured model id is
not the operator-confirmed one, so no live call was made, the live suite refuses rather than skips, and
the replay path is proven offline. P12 compared three declared decision policies under common random
numbers: armed-band consolidation is robust across all three, extraction inversion is policy-dependent,
and the fiscal-military ratchet in its strong form is absent from every arm, with the runtime arm's
refusal recorded rather than imputed. P13 read that evidence back into six mechanism cards — two
SUPPORTED (crisis gating by the mobility valve; insurgent consolidation), one CONDITIONAL (extraction
inversion), one WEAK (elite mediation), one REJECTED (the ratchet's monotone form) and one
UNIDENTIFIED (famine mortality, which the model does not implement). P14 added the surfaces: the
command line, the artifact browser, the batch and Slurm layer, the environment checks, the benchmark,
the reproducible demo scenario, and a full review.

## Boundaries

- Development LLM (OpenCode Go) and runtime institutional-policy LLM (USTC DeepSeek V4.1) are
  strictly separate. The runtime path is off by default, has no fallback, and is never called from a
  compute node.
- `.env` is gitignored; the USTC API key is never read, printed, echoed, logged or committed.
- Parameter cards, evidence grades and the ledger are the register of what is sourced and what is
  assumed: `docs/epistemics/evidence-grades.md`.
- Binding rules: `.omp/RULES.md` (sticky). Project context: `.omp/AGENTS.md`.

## Documentation

| Document | Content |
| --- | --- |
| `docs/OMP_ENGINEERING_PLAN.md` | Phase plan P00–P14, mechanisms, stack, discipline |
| `docs/architecture/system-overview.md` | Layers, modules, tick order, RNG, provenance, invariants |
| `docs/architecture/system-dependency.md` | The tick order, its dependencies, and how both are enforced |
| `docs/architecture/runtime-llm-boundary.md` | Dev vs runtime LLM contract |
| `docs/epistemics/model-epistemics.md` | What simulation may and may not claim |
| `docs/epistemics/evidence-grades.md` | A/B/C/D/S grades, parameter cards, evidence ledger |
| `docs/evidence/` | Generated: coverage, uncertainty and the gaps in the evidence base |
| `docs/calibration/` | Generated: the frozen objective, the posterior, the mismatches, the held-out predictions |
| `docs/experiments/` | Generated: ablations, interactions, sensitivity indices, tipping grid, policy-robustness matrix |
| `docs/mechanisms/` | The mechanism cards: `cards.yaml`, one Markdown card each, and the index |
| `outputs/reports/mechanism-synthesis.md` | Generated: what the cards say together, and the boundary fits |
| `docs/ui.md` | The browser: what each tab reads, and what it deliberately does not do |
| `docs/phase-reports/` | One report per phase |

Each phase ends with a report, logical commits, a clean tree, and a stop. Never start the next phase
unasked.
