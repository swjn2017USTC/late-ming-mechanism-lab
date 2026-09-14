# M004 - Elite Mediation Bifurcation

**Status: WEAK**

*Question.* Do elites either mediate household distress or accumulate the collateral, and does the branch taken decide the county's trajectory?

## 1. Micro conditions

- A household facing a consumption shortfall can borrow silver against its land at a monthly rate, if it has land to pledge.
- The loan is the household's way to stay fed without leaving, so the credit channel stands between distress and departure.

## 2. Meso conditions

- The elite's lending capacity is a share of the land pledged as collateral, so the same rule that lets the household survive transfers the land if it cannot repay.
- Elite holdings are assessed partly off the register: a declared hidden share of elite land is not taxed.

## 3. Causal chain

- Distress forces sales or loans, and the loan-to-value rule decides how much silver an elite will advance.
- The silver is consumed rather than invested, so the household's asset position weakens even when it survives the month.
- Land moves toward the lender, and the county's assessable base contracts with it.

## 4. Trigger

A consumption shortfall large enough that a household pledges land to close it; with the credit channel closed the same shortfall has to be met by departure instead.

## 5. Macro outcome

A contracting assessable base with land concentrated in elite hands. The mediation side of that is measured and load-bearing; the bifurcation - two branches with different trajectories - was never measured, and the runs show the two sides occurring together.

## 6. Necessary versus facilitating conditions

- A lender with capacity to advance silver against pledged land. (*meso*, necessary)
- A household with land to pledge and a shortfall it cannot cover. (*micro*, necessary)
- An unreformed register, so elite land can be hidden from assessment. (*meso*, facilitating)

## 7. Time lag

Not resolved: the credit arms are compared on end-of-run levels, and no artifact records the month in which a cohort first borrows or first loses land. The consumption events that precede borrowing are monthly, so the lag is at most the run.

## 8. Sensitivity evidence

elite_hidden_land_share is identified in P09 - median 0.359, contraction 0.277 - and interest_rate_monthly is identified too (median 0.070, contraction 0.368), so both terms of the credit relation are pinned by the evidence rather than left free. Neither appears among the three largest elementary effects on the crossed-line count, so the channel matters more to levels than to the breakdown boundary.

## 9. Ablation evidence

Closing the credit channel deepens the base contraction and pushes households out: tax_base_change_mu -9,539.98 [-12,523.40, -7,849.88] down and households_departed +121.18 [+91.79, +400.50] up. Elite lending falls from 74.5 to 0.0 per run, while the effect on the armed population is unresolved (largest_band_share_max +0.00 [-0.01, +0.10] unresolved): the mediating branch is load-bearing here, and the accumulating branch has no arm to remove.

## 10. Hold-out evidence

No reserved pattern scores the credit channel: debt-transfers-land is a calibration target satisfied in 0.94 of draws, and no held-out pattern asks anything about elite lending. The bifurcation's second branch is therefore outside the predictive check as well as outside the ablation set.

## 11. Policy robustness

Not measured: P12's mechanism readings are the extraction, ratchet and band consolidation readings, and none of them reads the credit channel. The policy arms do change the level comparison, but no reading tracks elite lending, so no verdict exists for this mechanism.

## 12. Historical support

debt-transfers-land (grade B, target, window 1600-1644): calibration window 0.94; land-abandonment-in-famine (grade C, target, window 1630-1644): calibration window 1.00; the model's interest and hidden-land parameters are identified against these targets

## 13. Historical challenge

The record describes mediation and accumulation as a choice made differently by different elites; the model has a single lending rule and no predatory variant, so it cannot distinguish the branches it is supposed to bifurcate between. The land-transfer pattern being matched at 0.94 says the credit relation works, not that elites diverge.

## 14. Counterexample

The baseline runs satisfy debt-transfers-land at 0.94 while the tax base contracts by 15,476 mu, with land moving to creditors as the pattern describes. Removing the credit channel makes that contraction deeper, not shallower (tax_base_change_mu -9,539.98 [-12,523.40, -7,849.88] down): mediation and accumulation appear together rather than as alternatives, so the bifurcation as stated is not what the model shows.

## 15. Falsifiable prediction

Two tests, one per claim. Build the accumulating branch - elites lending at the maximum rate with land taken on default - and it should produce a larger base contraction than the closed-credit arm's -9,540 mu; if it does not, the bifurcation has no second branch and the card should say so in one sentence rather than carry a status. Then split the runs by which side dominates and compare their trajectories: if the two groups do not separate, mediation is one mechanism rather than a pair of branches.

## 16. Uncertainty

The card is named for a bifurcation and the evidence resolves one branch of it, which is why the status is WEAK rather than CONDITIONAL: credit is load-bearing, and the claim that elites divide into mediators and accumulators with different consequences is neither measured nor consistent with the runs, where both sides appear together. The credit channel is also entangled with migration, so part of what looks like a credit effect on the base may be a movement effect, and the parameter that pins it is identified against the land-transfer target the mechanism itself implies.

## Evidence cited

| kind | source | reading |
|---|---|---|
| ablation | `outputs/experiments/p10-ablations/runs.parquet` | NO_ELITE_CREDIT tax_base_change_mu -9,539.98 [-12,523.40, -7,849.88] down; households_departed +121.18 [+91.79, +400.50] up |
| calibration | `outputs/calibration/p09-*/ensemble.parquet` | elite_hidden_land_share median 0.359 contraction 0.277; interest_rate_monthly median 0.070 contraction 0.368 |
| counterfactual | `outputs/experiments/p10-ablations/runs.parquet` | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT closes both channels at once |
| hold-out | `outputs/calibration/p09-*/predictive_statistics.parquet` | no reserved pattern scores the credit channel |
| historical-support | `ray-huang-1974` | debt-transfers-land (grade B, target, window 1600-1644): calibration window 0.94 |

Statuses across the book: 1 CONDITIONAL, 1 REJECTED, 2 SUPPORTED, 1 UNIDENTIFIED, 1 WEAK.
