# Benchmark

Workload: the `bench-medium` integrated sandbox, 240 ticks (24 warm-up), seed 20260915.
Machine: Darwin arm64, Python 3.12.14.

| metric | measured |
|---|---|
| seconds | 10.64 |
| ticks per second | 22.6 |
| peak resident memory | 985 MiB |
| events | 263619 |
| simulation digest | `3930c3de0c63bfc3c13e1cd2a0aacb0fd53c5252fba8244aa67b4fc08cf19036` |

## Development thresholds (enforced by `late-ming-lab bench --enforce`)

| name | metric | bound | measured | cleared | protects |
|---|---|---|---|---|---|
| `dev-throughput` | ticks_per_second | at_least 5 | 22.57 | yes | a developer's edit-run loop: a full window in under a minute |
| `dev-window` | seconds | at_most 120 | 10.64 | yes | a single full-window run inside a short interactive session |
| `dev-memory` | peak_mib | at_most 2048 | 985.22 | yes | a laptop running the model beside an editor and a browser |

## Cluster budget (declared; sizes the Slurm array, grades no machine)

| name | metric | bound | measured | cleared | protects |
|---|---|---|---|---|---|
| `hpc-per-task` | seconds | at_most 600 | 10.64 | yes | one array task inside a ten-minute walltime with a 1.5 safety factor |
| `hpc-memory` | peak_mib | at_most 4096 | 985.22 | yes | the per-task memory ceiling a shared cluster node enforces |

A task measured at 10.6 s is given a walltime of 00:01:00 (safety factor 1.5) by the Slurm template.

## Profile of the same workload

| function | cumulative seconds | calls |
|---|---|---|
| `run_integrated_scenario (integrated.py:291)` | 23.56 | 1 |
| `run (kernel.py:80)` | 23.47 | 1 |
| `_apply (ledger.py:119)` | 16.44 | 192600 |
| `balance_fields (ledger.py:102)` | 15.53 | 2378672 |
| `<genexpr> (ledger.py:105)` | 14.29 | 16937468 |
| `__get__ (_utils.py:431)` | 9.68 | 28544064 |
| `step (household_survival.py:116)` | 4.55 | 240 |
| `monthly_budget (households.py:1053)` | 4.35 | 14400 |
| `model_fields (main.py:275)` | 4.13 | 28544064 |
| `step (fiscal.py:184)` | 2.75 | 240 |
| `_assess_and_collect (fiscal.py:195)` | 2.70 | 2880 |
| `eat_from_storage (households.py:269)` | 2.43 | 28800 |
| `_collect_from (fiscal.py:266)` | 2.31 | 14400 |
| `step (military.py:597)` | 2.17 | 240 |
| `step (military.py:283)` | 2.16 | 240 |
