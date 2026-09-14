# Mechanism synthesis

P13 read the calibration ensemble, the hold-out pass, the sensitivity screens, the ablations, the counterfactual arms and the policy-robustness matrix, and wrote one card per candidate mechanism. This report holds what the six cards say together, where they contradict the project's own earlier documents, and what a fitted surface can and cannot add.

The cards themselves are `docs/mechanisms/index.md`, with `cards.yaml` beside it for the machine-readable form. Every number below comes from an artifact the cards name.

## 1. The six candidates

| id | mechanism | status | evidence kinds cited |
|---|---|---|---|
| M001 | Fiscal Extraction Inversion | CONDITIONAL | ablation, calibration, historical-support, hold-out, policy-robustness, sensitivity |
| M002 | Crisis Gating | SUPPORTED | ablation, counterfactual, historical-challenge, hold-out, policy-robustness, sensitivity |
| M003 | Fiscal-Military Ratchet | REJECTED | ablation, calibration, historical-support, policy-robustness |
| M004 | Elite Mediation Bifurcation | WEAK | ablation, calibration, counterfactual, historical-support, hold-out |
| M005 | Insurgent Consolidation | SUPPORTED | ablation, historical-support, hold-out, policy-robustness, sensitivity |
| M006 | Famine Mortality | UNIDENTIFIED | historical-support |

Counts: 1 CONDITIONAL, 1 REJECTED, 2 SUPPORTED, 1 UNIDENTIFIED, 1 WEAK. No card can be SUPPORTED by the runtime arm, because no runtime arm ran: the P11 gate refused it and P12 recorded the refusal rather than imputing a result.

## 2. What each card found

### 2.1 M001 Fiscal Extraction Inversion - CONDITIONAL

- **Chain.** Pressure rises: the assessed value per mu, or the share of the quota demanded, increases. ... Receipts over the assessed quota fall while effort stays at the ceiling.
- **Macro outcome.** Chronic shortfall: receipts below quota, a contracting registered base, and a military pay claim met from a shrinking receipt.
- **Ablation evidence.** NO_EXTRACTION_ESCALATION removes the response of the assessment rate and the collection effort to the arrears stock and lowers receipts over quota (receipts_over_quota_total -0.06 [-0.10, -0.01] down), the opposite direction from an inversion story. Its effect on the tax base is unresolved (tax_base_change_mu -2,417.48 [-5,239.52, +4,228.41] unresolved), so the arm moves what is collected without showing that pressing harder destroys the base.
- **Counterexample.** The rule policy: 0 of 6 replicates, at the same parameter draws and the same world as the arm that shows it. A structural inversion would not depend on which declared policy is deciding.
- **Prediction.** Ablate the effort response - fix collection effort at its warm-up value - and the inversion disappears: receipts over quota stops falling as nominal pressure rises. If it still falls, the inversion is not the response rule's doing and this card is wrong.

### 2.2 M002 Crisis Gating - SUPPORTED

- **Chain.** The gate opens: move costs, transit loss and the distress lines that qualify a household to leave are removed. ... Receipts cannot cover the pay claim, arrears rise, and the county crosses the declared breakdown line in every replicate.
- **Macro outcome.** Systemic breakdown of the county's finances and its coercive reach, reached at the same tick in every replicate.
- **Ablation evidence.** Opening the gate does it: breakdown +1.00 [+1.00, +1.00] up, tax_base_change_mu -162,553.28 [-170,826.34, -161,632.75] down, households_exited +8,514.95 [+3,896.31, +9,732.58] up, against a baseline in which no replicate breaks down. Removing the climate shocks does not: breakdown +0.00 [+0.00, +0.00] unresolved, with the tax base unresolved (tax_base_change_mu +2,718.02 [-4,560.20, +3,078.74] unresolved) and departures down (households_departed -534.23 [-580.57, -20.96] down).
- **Counterexample.** The drought ablation: removing the climate shock keeps the baseline outcome - no breakdown in any replicate - so the shock is not the gate. Of the twelve arms in the ablation batch only the gate arm breaks down. Elsewhere in P10 breakdown does occur without it - 7 of the 40 Sobol runs and one tipping cell cross the line under extreme parameter draws - so the claim is about the declared arms, not the only route.
- **Prediction.** Shut the gate under the worst climate setting and breakdown should not occur: an arm that refuses permanent departure at severity floor 0.9 and nominal pressure 0.04 produces zero breakdowns in every replicate. Force the gate open under the mildest setting and at least one replicate should break down. Either result falsifies this card.

### 2.3 M003 Fiscal-Military Ratchet - REJECTED

- **Chain.** Assessed receipts fall short of the assessed quota. ... If the stock could only ever rise, the fiscal burden would ratchet; the stock is instead drawn down whenever receipts exceed the month's claim.
- **Macro outcome.** A large but fluctuating arrears stock - not a monotone ratchet. The stock ends the run at 14,355 to 26,849 tael against 287,355 to 311,429 tael assessed in the six rule replicates.
- **Ablation evidence.** Two resolved arms raise the stock and neither removes its declines: doubling the pay claim's call on the treasury (military_pay_arrears_end_tael +2,299.70 [+1,554.58, +4,753.25] up) and opening the mobility gate (military_pay_arrears_max_tael +10,287.79 [+7,289.76, +14,415.10] up). A shortfall that remains when the claim is doubled is a fiscal result rather than a policy choice, and the declines survive both arms because no arm was built to remove them.
- **Counterexample.** arrears 254 to 26,849 tael with 37 month(s) of decline, against 287,355 assessed: the rule arm's largest end stock belongs to a replicate that still records dozens of months in which the stock falls, and the arm's largest decline count is 53. Any reading that needs the stock to be monotone is false in this model.
- **Prediction.** An arm that removes the clearing - one that refuses to pay arrears in any month - would make the stock monotone. If the stock still declines under that arm, the declines come from something other than the payment rule, and this rejection is wrong. The surviving claim keeps its own prediction: the stock ends between 4.8% and 9.3% of the assessed value, and an arm that doubles the pay rate should raise that share rather than lower it.

### 2.4 M004 Elite Mediation Bifurcation - WEAK

- **Chain.** Distress forces sales or loans, and the loan-to-value rule decides how much silver an elite will advance. ... Land moves toward the lender, and the county's assessable base contracts with it.
- **Macro outcome.** A contracting assessable base with land concentrated in elite hands. The mediation side of that is measured and load-bearing; the bifurcation - two branches with different trajectories - was never measured, and the runs show the two sides occurring together.
- **Ablation evidence.** Closing the credit channel deepens the base contraction and pushes households out: tax_base_change_mu -9,539.98 [-12,523.40, -7,849.88] down and households_departed +121.18 [+91.79, +400.50] up. Elite lending falls from 74.5 to 0.0 per run, while the effect on the armed population is unresolved (largest_band_share_max +0.00 [-0.01, +0.10] unresolved): the mediating branch is load-bearing here, and the accumulating branch has no arm to remove.
- **Counterexample.** The baseline runs satisfy debt-transfers-land at 0.94 while the tax base contracts by 15,476 mu, with land moving to creditors as the pattern describes. Removing the credit channel makes that contraction deeper, not shallower (tax_base_change_mu -9,539.98 [-12,523.40, -7,849.88] down): mediation and accumulation appear together rather than as alternatives, so the bifurcation as stated is not what the model shows.
- **Prediction.** Two tests, one per claim. Build the accumulating branch - elites lending at the maximum rate with land taken on default - and it should produce a larger base contraction than the closed-credit arm's -9,540 mu; if it does not, the bifurcation has no second branch and the card should say so in one sentence rather than carry a status. Then split the runs by which side dominates and compare their trajectories: if the two groups do not separate, mediation is one mechanism rather than a pair of branches.

### 2.5 M005 Insurgent Consolidation - SUPPORTED

- **Chain.** Recruitment from distress and from the soldiery continues through the crisis years. ... The armed population becomes a smaller number of larger organisations, whose grain demands the record describes as exceeding what a county can collect - a quantity no artifact in this project measures.
- **Macro outcome.** Armed force concentrated in fewer, larger bands - present in every declared policy, at five of six replicates in each - alongside a county base that cannot meet both the pay claim and the relief demand.
- **Ablation evidence.** Suppression is load-bearing and the direction is measured: LOW_REPRESSION (largest_band_share_max -0.05 [-0.10, -0.01] down) lowers the largest band's share, while leaving the number of bands unresolved. The merger rule is not load-bearing: NO_BAND_MERGER produces the same merge count as the baseline (0 in both, bands at end 5.25 against 5.25), because no merge fires anywhere in the batch.
- **Counterexample.** The merger arm: raising the cohesion bar to its maximum changes nothing (0 merges against the baseline's 0), and consolidation still appears. Whatever produces it, it is not the merger rule the model's documentation names.
- **Prediction.** Lower the cohesion bar so that merges actually fire, and the largest band's share should exceed the 0.382 maximum the declared policies reach. If merges fire and the share does not rise, the merger link is decorative and the mechanism's chain should be rewritten around formation and dissolution.

### 2.6 M006 Famine Mortality - UNIDENTIFIED

- **Chain.** Precipitation deficit, then harvest failure, then price spike, then consumption below subsistence. ... Labour per mu falls and cultivation is abandoned.
- **Macro outcome.** Population decline beyond what migration explains, and a labour shortage in the seasons after a famine - neither of which any artifact in this project reports.
- **Ablation evidence.** No arm can be built. Removing mortality would be a no-op because there is nothing to remove, which is exactly the situation the NO_BAND_MERGER arm demonstrates for a different rule: an arm whose intervention cannot bind measures the rule's absence, not its effect.
- **Counterexample.** The model satisfies land-abandonment-in-famine at 1.00 with zero deaths, so any claim that mortality is necessary for abandonment is contradicted inside the model - and any claim that the model's abandonment is historical evidence for a mortality mechanism is contradicted by the model's own structure.
- **Prediction.** Add a mortality rule that removes members on a sustained subsistence shortfall and the held-out scores should move only if the pattern's timing depends on labour scarcity: if famine-worst-years-1639-43 stays at 1.00 and the population statistics shift, mortality changes levels rather than timing in this model. That test cannot be run today, which is why the status is UNIDENTIFIED rather than WEAK.

## 3. Where the evidence contradicts the project's earlier documents

1. **The fiscal-military ratchet was narrated before it was measured.** P07's report and the P12 scope both treated the arrears stock as a ratchet. Measured month by month over the 18 replicates of the three declared policies it declines somewhere between 4 and 69 times in a 240-tick run, so no replicate is monotone; the rule arm's largest end stock, 26,849 tael, belongs to a replicate with 37 decline months rather than to the arm's quietest one. The level claim survives; the monotone claim does not.
2. **The extraction inversion looked structural and is not.** It appears in six of six utility replicates and in none of the rule arm's. The one arm that varies extraction (NO_EXTRACTION_ESCALATION) collects *less* of the quota with the escalation rule removed, so the inversion is a property of a policy that responds to shortfall rather than of the fiscal apparatus.
3. **Consolidation's named link was never exercised.** The merger rule's cohesion bar was never met: zero merges in every arm of the P10 batch, including the arm built to stop them. Consolidation as an outcome is robust; the mechanism the model documents for it is not what produces it.
4. **One named mechanism has no second branch and another has no mechanism at all.** Elite accumulation was never built, so a bifurcation cannot be measured; famine mortality was never implemented, and the abandonment pattern it is supposed to help produce is satisfied at 1.00 without it. Pattern agreement is not mechanism evidence.
5. **The gate that decides breakdown is movement, not climate.** Opening the mobility gate produces breakdown in four of four replicates at tick 48; removing the climate shocks leaves breakdown at zero and the tax base unresolved. In this model the crisis is gated by an institution, and the drought's own effects are to move households and to raise the arrears stock.

## 4. The boundary analysis: what the fitted surfaces describe

A boundary, a partial dependence or a tipping surface describes these runs; it is not evidence about the past. What separates the runs that were made is a property of this model under this design, and no coefficient, importance or AUC here measures what an intervention would do. A historical claim needs an intervention this table cannot supply.

### 4.1 The scenario surface (P12's grid)

Fitted on the 54 runs of the P12 tipping grid: target `breakdown`, features `nominal_pressure`, `severity_floor`, logistic model. Cross-validated AUC 0.754 (sd 0.176) against an in-sample 0.723, so the separation is not an artefact of scoring the rows that were fitted.

| feature | standardized coefficient |
|---|---|
| `nominal_pressure` | +0.334 |
| `severity_floor` | +0.733 |

Partial dependence on `nominal_pressure`: 0.01 -> 0.404, 0.02 -> 0.462, 0.04 -> 0.579.

Observed breakdown share by cell, all three declared policies pooled:

| x_bin | y_bin | x_centre | y_centre | runs | observed_rate |
|---|---|---|---|---|---|
| 0 | 0 | 0.01 | 0.40 | 6 | 0.33 |
| 0 | 1 | 0.01 | 0.60 | 6 | 0.00 |
| 0 | 2 | 0.01 | 0.80 | 6 | 1.00 |
| 1 | 0 | 0.03 | 0.40 | 6 | 0.33 |
| 1 | 1 | 0.03 | 0.60 | 6 | 0.00 |
| 1 | 2 | 0.03 | 0.80 | 6 | 0.83 |
| 2 | 0 | 0.04 | 0.40 | 6 | 0.67 |
| 2 | 1 | 0.04 | 0.60 | 6 | 0.33 |
| 2 | 2 | 0.04 | 0.80 | 6 | 0.83 |

### 4.2 The same fit per policy

| policy | runs | cv AUC | sd | pressure | severity | breakdown share |
|---|---|---|---|---|---|---|
| rule | 18 | 0.725 | 0.229 | +0.27 | +0.72 | 0.56 |
| utility | 18 | 0.800 | 0.245 | +0.35 | +0.80 | 0.33 |
| random | 18 | 0.550 | 0.400 | +0.26 | +0.47 | 0.56 |

The three rows are fitted on the same two knobs in the same world, and only the decision policy differs between them. Their coefficients differ, and so does their cross-validated score - 0.550 with a spread of 0.400 on the random policy's 18 rows is a fit that separates almost nothing. Whether the differences are the policy acting or sampling noise at 18 rows is not something the fit decides; the region table in the cards' policy-robustness fields is the observation that carries the substantive claim, and it says the cells that break down move with the policy.


### 4.3 The parameter surface (P10's Morris design)

The Morris batch has 32 runs and 30 of them cross the declared breakdown line: two classes at a 0.94 positive rate across fifteen swept parameters. The declared five-fold split is what was attempted.

The fit is refused rather than forced: fold 2 of 5 carries one class in its 6 test rows, so it cannot be scored: the smaller outcome needs at least 5 rows. Dropping to a split the table could carry would produce a number that measures the fold split rather than the model, so no parameter-side boundary is published; the parameter-side statement is the Morris screen itself, whose leaders on `indicators_crossed_end` are `temporary_share_of_adults_per_month`, `reference_price_tael_per_shi`, `land_per_adult_capacity_mu`.


### 4.4 What the surfaces do not decide

A boundary fitted on the P12 grid says where the policy arms turned over, and the policy is not a feature of the table: it is which columns were collected. A boundary fitted on the Morris design would say which of the fifteen swept parameters co-vary with crossing the line, and at this sample size it cannot say it at all. Neither can replace the interventions the cards cite: the ablation arms are what say a gate is load-bearing, and the difference between *the runs separate here* and *this would change the outcome* is why the cards rest on arms rather than on fits.

## 5. What this phase cannot claim

- **Not causal historical truth.** Six cards over three counties and thirty-two cohorts, with the sandbox's declared parameters, are a statement about this model.
- **Not a ranking of the five named mechanisms.** Two are conditional, one is rejected, two are supported and one is unidentified, and the statuses rest on different amounts of evidence: the supported pair rests on a reading present in every declared policy plus a resolved intervention, while the conditional pair rests on a single arm each.
- **Not a search over mechanisms.** The candidates were the plan's list plus the one structural gap the evidence itself named. A mechanism nobody listed is not assessed here, and the fitted surfaces in section 4 describe the runs rather than search them.
- **Not a claim about the runtime layer.** Three declared policies ran; the runtime arm was refused, so nothing here constrains what an institutional decision layer would do.
