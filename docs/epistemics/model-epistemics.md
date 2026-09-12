# Model Epistemics

Binding rules: `.omp/RULES.md` rules 1–6 and 21. Evidence grades:
`docs/epistemics/evidence-grades.md`. Scope and phasing: `docs/OMP_ENGINEERING_PLAN.md`.

## The governing sentence

```text
Simulation is an argument, not evidence.
```

A simulation output is a consequence of stated assumptions. It cannot corroborate the
historical record, and it cannot establish that a mechanism operated in 1625–1644. What it can
do is make an argument precise enough to be attacked: which conditions are necessary, which
facilitate, what the time lag is, what would falsify it, and where the outcome is insensitive
to the parameters we cannot measure.

## The loop the project runs

```text
historical evidence
→ explicit assumptions
→ formal mechanism
→ simulation
→ emergent pattern
→ intervention / ablation
→ sensitivity
→ counterfactual
→ return to historical evidence
```

Leaving the loop early — producing a run and calling it a finding — is a failure mode, not a
shortcut.

## Claims the model may make

- Conditional statements: under assumptions A and parameter region P, mechanism M produces
  pattern Q, with uncertainty.
- Necessity and sufficiency claims about model-internal conditions (ablation-supported).
- Sensitivity structure: which parameters matter, which are unidentified.
- Falsifiable predictions that could be checked against evidence not used in fitting.

## Claims the model may not make

- Point probabilities of historical events, presented without conditions or ensembles.
- "The Ming fell because …" from a single dramatic timeline.
- Causal historical truth from simulation alone.
- Any statement that merges historical evidence, model assumption, and generated output into
  one undifferentiated claim.

## Prohibitions in model construction

1. **No outcome encoding.** No rule, parameter, or initial condition may exist solely so that
   the simulation reproduces a known historical outcome.
2. **No single-scalar state capacity.** Fiscal/governance capacity is a vector (collection,
   information, relief, coercion, logistics); a scalar hides the mechanism being studied.
3. **No anger-threshold rebellion.** Violence/recruitment arises from the coping ladder,
   eligibility pools, organization, and opportunity — not `anger > 0.7 → rebel`.
4. **No fake precision.** Weighted cohorts, not invented household inventories.
5. **No LLM-owned physics.** The runtime institutional LLM selects among bounded policy
   actions; it never determines physical or economic state.
6. **No ledger leaks.** A claim cannot move from a paper into code without passing the evidence
   ledger (see `docs/epistemics/evidence-grades.md`).

## Identifiability and equifinality

The model has more parameters than the historical record can constrain. Two consequences are
treated as first-class results, not embarrassments:

- **Non-identifiability** must be reported: a parameter that cannot be recovered from available
  evidence is flagged, not assigned a confident value.
- **Equifinality** must be tested: if several parameter settings reproduce the same patterns,
  the mechanism claim weakens, and the sensitivity analysis must say so.

Calibration therefore targets `P(theta | historical patterns)`, never a "best parameter set".

## Calibration and validation discipline

- Pattern-oriented: many patterns simultaneously (drought spatial pattern, famine timing, grain
  price volatility, migration proxy, tax arrears, rebel-event spatial spread, armed-group
  concentration, military arrears). A mechanism that explains one pattern is not established.
- Hold-out: 1625–1634 training/calibration, 1635–1642 hold-out, 1643–1644 hard extrapolation.
  Tuning after seeing the hold-out period voids the claim.
- Sensitivity: Morris screening to reduce dozens of parameters to ~10–15 influential ones, then
  Sobol for first-order, interaction, and total effects.
- Ablation at minimum: `NO_DROUGHT`, `NO_EXTRACTION_ESCALATION`, `FULL_MILITARY_PAY`,
  `HIGH_RELIEF`, `NO_ELITE_CREDIT`, `NO_TRADE_DISRUPTION`, `NO_BAND_MERGER`, `LOW_REPRESSION`,
  `OPEN_MIGRATION_EXIT`.
- Counterfactuals run an ensemble per scenario × policy, with common random numbers, and report
  distributions, intervals, and tipping probabilities — never one dramatized timeline.
- Policy robustness: if a mechanism appears only under one decision policy, it is
  `model-dependent`; if it survives rule-based, utility-based, random, and LLM policies, its
  robustness claim is stronger.

## Mechanism cards

The project's product is a set of conditional mechanism cards, not a collapse probability.

```yaml
mechanism_id:            # stable identifier
name:
status:                  # candidate | supported | contested | rejected
micro_conditions:        # cohort-level conditions
meso_conditions:         # organization/government/market conditions
trigger:
causal_chain:
macro_outcome:
necessary_conditions:
facilitating_conditions:
counterexamples:
time_lag:
parameter_region:
ablation_evidence:
sensitivity_evidence:
historical_evidence:
holdout_performance:
novel_prediction:
falsification_test:
uncertainty:
```

Candidate mechanisms to test (not to assume): Fiscal Extraction Inversion, Crisis Gating,
Fiscal-Military Ratchet, Elite Mediation Bifurcation, Insurgent Consolidation.

## Falsifiability requirement

Every mechanism card names the observation that would count against it. Examples of admissible
falsification tests: the pattern persists when the proposed necessary condition is ablated; the
effect disappears under a parameter region the evidence permits; the hold-out period fails
where the mechanism predicts it should hold. A card without a falsification test is not a
result.

## Uncertainty reporting

Outputs are distributions with intervals and the parameter region that produced them. The
provenance record (git SHA, config hash, parameter hash, seeds, policy id, LLM enablement and
model id) is part of the claim: a result that cannot be reproduced from its manifest is not
reportable.
