# late-ming-mechanism-lab

晚明陕西—河南危机多层历史机制模拟 — a historical mechanism laboratory for the 1625–1644
Shaanxi–Henan crisis.

> Simulation is an argument, not evidence.

Not a game, not LLM role-play of historical figures, and not a machine for producing a
"probability the Ming collapsed". The product is a set of conditional, falsifiable mechanism
cards with explicit assumptions, parameter regions, ablation and sensitivity evidence.

## Status

P02 (Historical Space / Time / Climate) complete. The repository holds a history-free
deterministic kernel (P01) and a spatial–temporal–environmental skeleton (P02): county and
boundary nodes with provenance, three separate movement graphs, a monthly agricultural
calendar, and a climate-forcing interface with baseline, observed-historical and synthetic
modes. There are still no households, markets, armies, rebels or LLM decisions.

The only spatial dataset in the repository is the five-county toy fixture, which is **not
history** — every value in it is graded `S` (an assumption). Real geography enters through
`networks/adapter.py`, with provenance columns, and nowhere else. Why space is nodes and
catchments rather than polygons: `docs/adr/0001-node-and-catchment-geography.md`.

Phase plan: `docs/OMP_ENGINEERING_PLAN.md`; current phase report: `docs/phase-reports/P02.md`.

```bash
uv run late-ming-lab smoke-run            # 240 ticks, 1625-01 → 1644-12, into outputs/runs/
uv run late-ming-lab smoke-run --ticks 24 --warmup 6 --seed 7
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
| `docs/phase-reports/` | One report per phase |

Each phase ends with a report, logical commits, a clean tree, and a stop. Never start the next
phase unasked.
