# V2 phase conventions

Where V2 work is written down, and what each document is for. V1's convention (`docs/phase-reports/P00.md`
… `P14.md`, `docs/exec-plans/P09.md` … `P14.md`) is kept unchanged and is not extended: V2 gets its
own names so a reader can never mistake a V2 document for a V1 one, and so no V1 file is edited to
make room.

## Layout

```text
docs/exec-plans/V2-P00.md … V2-P09.md      the scope of one V2 phase, written before it starts
docs/phase-reports/V2-P00.md … V2-P09.md   what the phase did, with its real verification output
docs/v2/                                   V2 documents that are not a phase report
docs/v2/baseline-v1.json                   generated: the frozen V1 release candidate, by hash
docs/v2/v1-acceptance-matrix.md            generated: milestone and success-criterion audit
docs/v2/v1-acceptance-matrix.json          generated: the same matrix, machine-readable
docs/v2/scientific-readiness.md            the boundary between engineering RC and regional model
docs/v2/phase-conventions.md               this file
```

## Rules

1. **One phase, one name.** A phase is `V2-Pnn` in prose, `V2-Pnn.md` in both directories, and the
   phase report says which exec plan it was run against. `docs/phase-reports/V2-P00.md` belongs to
   `docs/exec-plans/V2-P00.md` and to no other.
2. **V1 documents are read-only.** No `P00.md`–`P14.md` file, no `docs/mechanisms/`, `docs/evidence/`,
   `docs/calibration/` or `docs/experiments/` document is edited by a V2 phase. A V1 statement the V2
   evidence contradicts is contradicted *in the V2 document that measured it*, with the V1 file
   named; `docs/v2/v1-acceptance-matrix.md` is where that starts.
3. **Generated documents are regenerable.** Anything under `docs/v2/` that a module writes carries
   its generator in the document header and is rewritten by its command, never hand-edited after
   generation: `late-ming-lab baseline build` writes `baseline-v1.json`, `late-ming-lab baseline
   audit` writes the two matrix files. Authored V2 documents (`scientific-readiness.md`,
   `phase-conventions.md`, every phase report) are not generated.
4. **Phase reports carry the real output.** Every command a phase claims to have run appears with its
   actual result, including a failure or an environment limitation. A report that says what should
   have happened is a report of nothing.
5. **Evidence is a path plus a locator.** A claim in a V2 document cites a file (`outputs/…`,
   `docs/…`, `src/…`) and what in it is being read; a citation that a reader cannot resolve is a bug.
   `docs/v2/v1-acceptance-matrix.json` is the machine-readable form of the same rule.
6. **New output directories.** V2 runs write under a new root (`outputs/v2/…` and a V2 batch label);
   nothing V2 executes rewrites a V1 artifact directory, and `late-ming-lab baseline verify` is what
   proves that.
7. **A phase ends the way V1 phases did.** Report, review, logical commit, clean tree, STOP. Never
   start `V2-Pnn+1` unasked (`.omp/RULES.md` rule 18).

## What each V2 phase writes

| phase | exec plan | report | generated documents it owns |
| --- | --- | --- | --- |
| V2-P00 | `docs/exec-plans/V2-P00.md` | `docs/phase-reports/V2-P00.md` | `docs/v2/baseline-v1.json`, `docs/v2/v1-acceptance-matrix.{md,json}` |
| V2-P01 | `docs/exec-plans/V2-P01.md` | `docs/phase-reports/V2-P01.md` | evidence registry and rights reports (paths declared by that phase) |
| V2-P02 | `docs/exec-plans/V2-P02.md` | `docs/phase-reports/V2-P02.md` | `historical-core-v1` coverage and gap reports |
| V2-P03 | `docs/exec-plans/V2-P03.md` | `docs/phase-reports/V2-P03.md` | `validation-protocol-v2.yaml`, `threshold-ensemble.yaml`, `model-comparison-register.yaml` |
| V2-P04 | `docs/exec-plans/V2-P04.md` | `docs/phase-reports/V2-P04.md` | the hold-out diagnosis reports |
| V2-P05 | `docs/exec-plans/V2-P05.md` | `docs/phase-reports/V2-P05.md` | the mechanism-variant reports |
| V2-P06 | `docs/exec-plans/V2-P06.md` | `docs/phase-reports/V2-P06.md` | the calibration V2 reports |
| V2-P07 | `docs/exec-plans/V2-P07.md` | `docs/phase-reports/V2-P07.md` | the sensitivity and counterfactual V2 reports |
| V2-P08 | `docs/exec-plans/V2-P08.md` | `docs/phase-reports/V2-P08.md` | the runtime policy reports |
| V2-P09 | `docs/exec-plans/V2-P09.md` | `docs/phase-reports/V2-P09.md` | the V2 mechanism cards, synthesis and release bundle |

This file declares the convention only. It starts no phase: P01–P09 remain unwritten until they are
asked for.
