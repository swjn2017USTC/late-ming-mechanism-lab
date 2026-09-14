# M003 - Fiscal-Military Ratchet

**Status: REJECTED**

*Question.* Does the army's unpaid claim accumulate without ever clearing, so the fiscal burden only ever rises?

## 1. Micro conditions

- Soldiers are owed a monthly silver pay whose level is a declared rate rather than a negotiated outcome.
- The pay claim is made against the same receipts the civil administration collects, so a shortfall appears as an unpaid stock.

## 2. Meso conditions

- The treasury pays the claim from receipts in the same tick, so it cannot borrow against a future receipt.
- Desertion removes soldiers from the roster, so a pay failure is also a manpower loss.

## 3. Causal chain

- Assessed receipts fall short of the assessed quota.
- The pay claim is met only in part, and the unpaid remainder is carried forward as a stock.
- If the stock could only ever rise, the fiscal burden would ratchet; the stock is instead drawn down whenever receipts exceed the month's claim.

## 4. Trigger

A month in which receipts exceed that month's pay claim, which is what clears part of the stock and what the strong form of the mechanism says cannot happen.

## 5. Macro outcome

A large but fluctuating arrears stock - not a monotone ratchet. The stock ends the run at 14,355 to 26,849 tael against 287,355 to 311,429 tael assessed in the six rule replicates.

## 6. Necessary versus facilitating conditions

- A pay claim fixed in silver while receipts are a residual. (*meso*, necessary)
- No borrowing against future receipts, so the stock cannot be smoothed away. (*meso*, necessary)
- The claim rising with the number of soldiers the county must support. (*meso*, facilitating)

## 7. Time lag

Not resolved within the run: the reading is computed from a monthly series, but the artifact records only how many months declined, so when the declines fall is not in the evidence. The series' endpoints run from 254 tael to 14,355-26,849 tael over the six rule replicates.

## 8. Sensitivity evidence

pay_tael_per_soldier_month is identified in P09 - posterior median 0.508 tael against a prior of 0.10-1.00, contraction 0.271 - so the stock's level is constrained by the data. No sensitivity statistic distinguishes a ratchet from a fluctuating stock, because the Morris outputs are end-of-run levels and maxima.

## 9. Ablation evidence

Two resolved arms raise the stock and neither removes its declines: doubling the pay claim's call on the treasury (military_pay_arrears_end_tael +2,299.70 [+1,554.58, +4,753.25] up) and opening the mobility gate (military_pay_arrears_max_tael +10,287.79 [+7,289.76, +14,415.10] up). A shortfall that remains when the claim is doubled is a fiscal result rather than a policy choice, and the declines survive both arms because no arm was built to remove them.

## 10. Hold-out evidence

pay-monetised-and-arrears is satisfied in 1.00 of posterior draws over the held-out years, 1.00 over the run as a whole, on the question 'does the garrison arrears stock accumulate over the run?'. Accumulation is matched. Accumulation *without clearing* was never a scored pattern, which is why the strong form survived this long in the project's own reporting.

## 11. Policy robustness

Absent in all three declared policies: 0 of 3 arms show it, verdict 'absent'. Decline months per rule replicate are [11, 35, 37, 43, 45, 53] of 240 ticks, and over all 18 replicates the range is 4 to 69. The rule arm's largest end stock, 26,849 tael, is a replicate with 37 decline months - more than the arm's median, not fewer.

## 12. Historical support

pay-monetised-and-arrears (grade A, hold-out, window 1580-1644): held-out years 1.00, whole run 1.00

## 13. Historical challenge

The record supports chronic arrears at a level, which the model reproduces, and it does not report a monotone stock: garrisons were paid in bursts when silver arrived. The strong form was an inference the project made from 'arrears are chronic' to 'arrears never clear', and the model rejects the inference, not the evidence.

## 14. Counterexample

arrears 254 to 26,849 tael with 37 month(s) of decline, against 287,355 assessed: the rule arm's largest end stock belongs to a replicate that still records dozens of months in which the stock falls, and the arm's largest decline count is 53. Any reading that needs the stock to be monotone is false in this model.

## 15. Falsifiable prediction

An arm that removes the clearing - one that refuses to pay arrears in any month - would make the stock monotone. If the stock still declines under that arm, the declines come from something other than the payment rule, and this rejection is wrong. The surviving claim keeps its own prediction: the stock ends between 4.8% and 9.3% of the assessed value, and an arm that doubles the pay rate should raise that share rather than lower it.

## 16. Uncertainty

The rejection is of the strong claim only, at three counties and 240 ticks. The mechanism behind the declines is not identified: nothing measures whether they come from the payment rule, from re-assessment, or from the extraction arm's own response to the stock. The level claim rests on a single held-out pattern at grade A.

## Evidence cited

| kind | source | reading |
|---|---|---|
| policy-robustness | `outputs/experiments/p12-robustness/mechanism_readings.parquet` | ratchet present in 0 of 3 declared policies; decline months per replicate [11, 35, 37, 43, 45, 53] |
| ablation | `outputs/experiments/p10-ablations/runs.parquet` | FULL_MILITARY_PAY military_pay_arrears_end_tael +2,299.70 [+1,554.58, +4,753.25] up |
| ablation | `outputs/experiments/p10-ablations/runs.parquet` | OPEN_MIGRATION_EXIT military_pay_arrears_max_tael +10,287.79 [+7,289.76, +14,415.10] up |
| calibration | `outputs/calibration/p09-*/ensemble.parquet` | pay_tael_per_soldier_month median 0.508, contraction 0.271 |
| historical-support | `ray-huang-1974` | pay-monetised-and-arrears (grade A, hold-out, window 1580-1644): held-out years 1.00 |

Statuses across the book: 1 CONDITIONAL, 1 REJECTED, 2 SUPPORTED, 1 UNIDENTIFIED, 1 WEAK.
