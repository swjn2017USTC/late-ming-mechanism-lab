# Benchmark

Workload: the `bench-medium` integrated sandbox, 240 ticks (24 warm-up), seed 20260915.
Machine: Darwin arm64, Python 3.12.14.

| metric | measured |
|---|---|
| seconds | 11.14 |
| ticks per second | 21.6 |
| peak resident memory | 901 MiB |
| events | 242979 |
| simulation digest | `71115de61171596eb6621400d518ad306bd0510c165bccc3badf59702f219b7f` |

## Development thresholds (enforced by `late-ming-lab bench --enforce`)

| name | metric | bound | measured | cleared | protects |
|---|---|---|---|---|---|
| `dev-throughput` | ticks_per_second | at_least 5 | 21.55 | yes | a developer's edit-run loop: a full window in under a minute |
| `dev-window` | seconds | at_most 120 | 11.14 | yes | a single full-window run inside a short interactive session |
| `dev-memory` | peak_mib | at_most 2048 | 900.62 | yes | a laptop running the model beside an editor and a browser |

## Cluster budget (declared; sizes the Slurm array, grades no machine)

| name | metric | bound | measured | cleared | protects |
|---|---|---|---|---|---|
| `hpc-per-task` | seconds | at_most 600 | 11.14 | yes | one array task inside a ten-minute walltime with a 1.5 safety factor |
| `hpc-memory` | peak_mib | at_most 4096 | 900.62 | yes | the per-task memory ceiling a shared cluster node enforces |

A task measured at 11.1 s is given a walltime of 00:01:00 (safety factor 1.5) by the Slurm template.
