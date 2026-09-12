# late-ming-mechanism-lab

晚明陕西—河南危机多层历史机制模拟 — a historical mechanism laboratory for the 1625–1644
Shaanxi–Henan crisis.

> Simulation is an argument, not evidence.

Not a game, not LLM role-play of historical figures, and not a machine for producing a
"probability the Ming collapsed". The product is a set of conditional, falsifiable mechanism
cards with explicit assumptions, parameter regions, ablation and sensitivity evidence.

## Status

P00 (Bootstrap / Constitution) complete. No simulation code exists yet. Phase plan:
`docs/OMP_ENGINEERING_PLAN.md`; current phase report: `docs/phase-reports/P00.md`.

## Setup

```bash
uv sync                 # Python 3.12 environment
cp .env.example .env    # runtime LLM stays disabled (USTC_LLM_ENABLED=0)
chmod 600 .env          # never committed; add the USTC key only when P11 requires it
```

## Checks

```bash
uv run late-ming-lab --version
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
