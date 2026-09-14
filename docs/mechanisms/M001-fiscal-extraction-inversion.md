# M001 - Fiscal Extraction Inversion

**Status: CONDITIONAL**

*Question.* Does pressing the fiscal apparatus harder collect less of what it is owed?

## 1. Micro conditions

- The assessment is a rate applied to a registered base that households can leave, conceal or default on.
- Land can change hands or fall out of cultivation, so the base the rate is applied to is not fixed within a run.

## 2. Meso conditions

- Collection effort is a decision: the county can press harder after it observes a shortfall, rather than applying a constant effort.
- The quota is assessed against a register that is not the same as the land actually worked, so the two can diverge.

## 3. Causal chain

- Pressure rises: the assessed value per mu, or the share of the quota demanded, increases.
- Effort rises in response; under the utility policy it moves to the declared ceiling of 5.0 from 3.34-4.25.
- Households leave, conceal or default, and the assessable base contracts.
- Receipts over the assessed quota fall while effort stays at the ceiling.

## 4. Trigger

A decision rule that raises collection effort after observing a receipt shortfall. No P10 ablation contains one: the P12 utility policy is the only arm in the project that presses to the ceiling.

## 5. Macro outcome

Chronic shortfall: receipts below quota, a contracting registered base, and a military pay claim met from a shrinking receipt.

## 6. Necessary versus facilitating conditions

- A base that can respond to the rate by moving, hiding or defaulting. (*micro*, necessary)
- An authority whose effort is a choice rather than a constant. (*meso*, necessary)
- Distress lines that make departure legal and affordable. (*micro*, facilitating)
- An assessed register that lags the cultivated area. (*meso*, facilitating)

## 7. Time lag

Unresolved: the P12 reading compares the endpoints of a 240-tick run, no artifact records an effort series, and none records the month at which effort and the receipt share would cross. Monthly resolution exists only for the crossed-line count, in the P10 governance timelines.

## 8. Sensitivity evidence

assessed_value_tael_per_mu has mu* = 0.75 (sigma = 1.06) on indicators_crossed_end in the Morris screen of the p10-morris batch: third equal with the land constraint behind the temporary-migration share and the reference price, so the tie is a tie rather than a rank. P09 identifies it: posterior median 0.240 tael per mu against a prior of 0.05-0.40, contraction 0.401, verdict identified.

## 9. Ablation evidence

NO_EXTRACTION_ESCALATION removes the response of the assessment rate and the collection effort to the arrears stock and lowers receipts over quota (receipts_over_quota_total -0.06 [-0.10, -0.01] down), the opposite direction from an inversion story. Its effect on the tax base is unresolved (tax_base_change_mu -2,417.48 [-5,239.52, +4,228.41] unresolved), so the arm moves what is collected without showing that pressing harder destroys the base.

## 10. Hold-out evidence

quota-erosion-and-surcharge is satisfied in 1.00 of posterior draws over the held-out years and 1.00 over the run as a whole; receipts-shortfall-chronic is satisfied in 1.00 of draws on the calibration window. The shortfall the mechanism is about is present; the pressing that is supposed to cause it is not in any held-out quantity.

## 11. Policy robustness

Present in 1.00 of the utility replicates with strengths 0.10-0.31, in 0.33 of the random replicates, and in none of the rule replicates: P12's verdict is 'policy-dependent'. It appears when the decision rule reacts to a shortfall by pressing, and it is absent when the rule holds.

## 12. Historical support

receipts-shortfall-chronic (grade B, target, window 1600-1644): calibration window 1.00; quota-erosion-and-surcharge (grade B, hold-out, window 1522-1644): held-out years 1.00, whole run 1.00

## 13. Historical challenge

The record attaches the shortfall to what collection could reach - flight, harvest and evasion - not to a feedback rule in which the authority presses harder as receipts fall, and neither pattern carries a measured collection effort. The model produces its inversion through exactly the rule the sources do not describe, and the extraction-escalation arm collects more, not less, of the quota.

## 14. Counterexample

The rule policy: 0 of 6 replicates, at the same parameter draws and the same world as the arm that shows it. A structural inversion would not depend on which declared policy is deciding.

## 15. Falsifiable prediction

Ablate the effort response - fix collection effort at its warm-up value - and the inversion disappears: receipts over quota stops falling as nominal pressure rises. If it still falls, the inversion is not the response rule's doing and this card is wrong.

## 16. Uncertainty

Three declared policies, three counties, thirty-two cohorts. The utility policy's ceiling of 5.0 is a declared bound, not an observed one, and the inversion's dependence on that ceiling is untested. The one arm that varies extraction runs the other way, so the card rests on a within-run co-movement under a single policy.

## Evidence cited

| kind | source | reading |
|---|---|---|
| sensitivity | `outputs/experiments/p10-morris/runs.parquet` | assessed_value_tael_per_mu mu*=0.75 sigma=1.06 on indicators_crossed_end |
| calibration | `outputs/calibration/p09-*/ensemble.parquet` | assessed_value_tael_per_mu median 0.240, contraction 0.401, identified |
| ablation | `outputs/experiments/p10-ablations/runs.parquet` | receipts_over_quota_total -0.06 [-0.10, -0.01] down |
| hold-out | `outputs/calibration/p09-*/predictive_checks.parquet` | quota-erosion-and-surcharge held-out 1.00, whole run 1.00 |
| policy-robustness | `outputs/experiments/p12-robustness/mechanism_readings.parquet` | inversion present in 1.00/utility, 0.33/random, 0.00/rule; verdict policy-dependent |
| historical-support | `ray-huang-1974` | receipts-shortfall-chronic (grade B, target, window 1600-1644): calibration window 1.00 |

Statuses across the book: 1 CONDITIONAL, 1 REJECTED, 2 SUPPORTED, 1 UNIDENTIFIED, 1 WEAK.
