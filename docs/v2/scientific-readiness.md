# Scientific readiness: what `v0.1.0-rc1` is, and what it is not

This document draws the boundary the V2 upgrade plan asks for (§1, §10) between three different
things that a reader could otherwise conflate: an **engineering release candidate**, a set of
**synthetic mechanism experiments**, and a **regional historical mechanism model**. Only the first
two exist today. The evidence behind every sentence here is in
`docs/v2/v1-acceptance-matrix.md`, and the content behind it is frozen in
`docs/v2/baseline-v1.json`.

```text
tier 1  engineering RC            exists   v0.1.0-rc1            reproducible software
tier 2  synthetic mechanism lab   exists   six cards, one ensemble, one ablation set
tier 3  regional historical model does not exist                  V2-P01 … V2-P09
```

## Tier 1 — Engineering release candidate (exists)

What the release actually guarantees:

- the kernel is deterministic: same code, configuration and seed give the same artifacts byte for
  byte, and `data/scenarios/demo.yaml` records a digest a regression test reproduces;
- every run records its code revision, configuration hash, root seed and subsystem seeds; every
  batch records its arms, design, seeds and statistics settings;
- the mechanical invariants hold and are enforced (grain never negative, population balance,
  deserters leave the army, receipts never exceed the collectible base);
- the surfaces work: nine CLI commands, an artifact browser that never runs the model, a batch and
  Slurm layer whose tasks carry their own seeds, and a benchmark with declared thresholds;
- the runtime LLM layer is closed by configuration and fails closed with no fallback.

`docs/v2/v1-acceptance-matrix.md` §2 marks the plan's two milestones `partial`, and no criterion
`met` rests on a tier-3 claim. The engineering tier is the only one this release licenses outright.

## Tier 2 — Synthetic mechanism laboratory (exists, and is where the six cards live)

Every mechanism result V1 publishes is a statement about **this model under declared fixtures**. The
fixtures are the point: the sandbox the P09, P10 and P12 batches ran on is five county nodes plus
three external nodes, twenty-five weighted household cohorts, twenty-one thousand households, and a
**synthetic stationary** climate (a shock month drawn independently with probability 0.4 and severity
floor 0.6 — no observed series, no trend). Every fixture value is graded `S`: a declared assumption.

What a tier-2 result can say, and what it cannot:

| V1 result | what it licenses | what it does not |
| --- | --- | --- |
| `M002 Crisis Gating` SUPPORTED | in this model, opening the mobility gate breaks the county's finances in 4 of 4 replicates, through the fiscal channel | that the 1630s crisis was gated by mobility; the gate's parameters are declared, and the migration network is synthetic |
| `M005 Insurgent Consolidation` SUPPORTED | fewer, larger bands under all three declared offline policies | the chain the card narrates: the merger rule it names produced zero merges anywhere in the batch |
| `M001 Fiscal Extraction Inversion` CONDITIONAL | a policy that presses harder collects less of the quota; absent under the rule policy | a property of the fiscal apparatus: the effect follows the decision rule |
| `M003 Fiscal-Military Ratchet` REJECTED | the strong form (arrears never decline) is false here: every replicate declines in 11 to 53 months | that arrears were not structural: the level claim survives, at grade A historical support |
| `M004 Elite Mediation Bifurcation` WEAK | credit is load-bearing for the tax base | a bifurcation: the accumulating branch was never built |
| `M006 Famine Mortality` UNIDENTIFIED | nothing: the model has no mortality rule, parameter or output | that mortality did not matter historically |

Four limits bound all of it, and each is measured in the audit rather than asserted:

1. **Sample size.** The largest single design is 52 runs (13 arms × 4 replicates); the calibration
   is 32 particles per seed over two seeds; the Morris screen is 2 trajectories; the Sobol design at
   N=4 returns four undefined first-order indices and nine of its twelve finite ones outside
   [0, 1], and is reported as a failed attempt.
   Nothing here is a converged estimate.
2. **Synthetic inputs.** Space, climate, cohort endowments and every edge property are assumptions.
   The drought-timing patterns fail because the climate is stationary — a property of the declared
   scenario, not a mechanism result.
3. **Reading thresholds.** "Breakdown" is six of eight governance reading lines, chosen above the
   five that cross in calm runs. The reports print the distribution and recompute the share at every
   candidate line, so no conclusion rests on the sixth line alone; but the lines themselves are
   declared, not observed.
4. **Unmeasured intermediates.** The cards record which links have no artifact: no mortality, no
   accumulation branch, no effort series, no band-merger event, no price series at county
   resolution, no relief coverage measured against need.

## Tier 3 — Regional historical mechanism model (does not exist)

A tier-3 claim would be: *on a sourced Shaanxi–Henan core, under observed climate forcing, with
pre-registered outcomes, mechanism X holds in such-and-such a parameter region and fails outside it.*
Nothing in `v0.1.0-rc1` supports a sentence of that form, because every clause of it is missing:

| what tier 3 needs | state at `v0.1.0-rc1` | the phase that would build it |
| --- | --- | --- |
| sourced nodes, edges and catchments | five synthetic counties, plus three synthetic external nodes | V2-P01 (rights and locators), V2-P02 (`historical-core-v1`) |
| observed climate forcing at its own resolution | a stationary synthetic draw | V2-P02 (allocation model, uncertainty carried) |
| outcomes and thresholds frozen before results | eight governance lines, all grade S | V2-P03 (continuous outcomes, threshold ensemble) |
| explanations for the failed hold-out patterns | three reserved patterns contradicted; failure traced to the scenario | V2-P04 |
| the missing mechanism variants | no mortality, no accumulation branch, an unexercised merger rule | V2-P05 |
| stable posterior and converged sensitivity | 32 particles; Morris 2 trajectories; Sobol undefined | V2-P06, V2-P07 |
| a runtime policy arm | refused at the model gate; zero live decisions | V2-P08, human gate |
| cards recomputed from V2 artifacts | six cards over the toy sandbox | V2-P09 |

## What would falsify this framing

The framing above is itself falsifiable, and V2 should be read as testing it:

- If a sourced Shaanxi–Henan core cannot be assembled to at least eight evidence-graded nodes from
  accessible rights-cleared material, the regional claim is dropped and the project stays a
  mechanism laboratory with a documented gap packet (V2-P02's declared fallback).
- If the V1 cards do not survive the transplanted inputs (V2-P09), then tier 2 was a statement about
  the fixtures rather than about the mechanisms, and the cards should say so in their status.
- If the threshold ensemble flips a core conclusion, then the V1 statuses were reading-line
  artefacts and V2 must report the flip rather than choose a favourable line (V2-P03).

## What does not change with the tier

Two commitments hold at every tier and are not contingent on V2 succeeding: an LLM never determines
physical or economic state (`.omp/RULES.md` 7–13), and historical evidence, model assumptions and
generated results are never silently merged (rules 2–3). The audit's own discrepancies section is
where that discipline is applied to this project's own prose: five statements in V1's mechanism
documents quote a sandbox size the artifacts do not support, and they are recorded rather than
edited, because V1 is frozen.
