# M002 - Crisis Gating

**Status: SUPPORTED**

*Question.* Is it the shock that produces breakdown, or the condition that lets the shock reach the base?

## 1. Micro conditions

- Households can leave: departure is a state a cohort enters when distress crosses a declared line, and it takes its labour and its consumption with it.
- Departure needs to be affordable - a move cost and a transit loss are charged - so a household below the line may still be unable to go.

## 2. Meso conditions

- The county's tax base is the labour and land that stayed, so an outflow is an outflow of assessable value.
- Military pay is claimed against the same receipts, so a smaller base shows up as arrears rather than as a smaller claim.

## 3. Causal chain

- The gate opens: move costs, transit loss and the distress lines that qualify a household to leave are removed.
- Households exit in numbers the baseline never reaches.
- The tax base contracts roughly seven times as far as in the next largest arm, and about seventeen times median to median.
- Receipts cannot cover the pay claim, arrears rise, and the county crosses the declared breakdown line in every replicate.

## 4. Trigger

The institutional gate, not the weather: with the gate open the crisis appears where the baseline has none, and removing the climate shocks leaves breakdown unchanged.

## 5. Macro outcome

Systemic breakdown of the county's finances and its coercive reach, reached at the same tick in every replicate.

## 6. Necessary versus facilitating conditions

- A gate on household movement that can be open or shut. (*meso*, necessary)
- A tax base that is the households still present. (*meso*, necessary)
- A climate shock severe enough to push households toward the line. (*micro*, facilitating)
- An army whose claim on the receipts does not shrink with them. (*meso*, facilitating)

## 7. Time lag

Twenty-four ticks, in every replicate: the open-gate arm crosses the declared breakdown line at tick 48 of 240, after the 24-tick warm-up. It is the only arm of the ablation batch whose replicates cross at all; the Morris and Sobol designs cross at ticks 24, 48 and 216.

## 8. Sensitivity evidence

The largest elementary effects on indicators_crossed_end are temporary_share_of_adults_per_month, reference_price_tael_per_shi, land_per_adult_capacity_mu (p10-morris): a migration share, a market price and a land constraint, with the land constraint tied with the assessed value rather than ranked behind it. The controls that lead sit on the movement and market side, not on the climate axis.

## 9. Ablation evidence

Opening the gate does it: breakdown +1.00 [+1.00, +1.00] up, tax_base_change_mu -162,553.28 [-170,826.34, -161,632.75] down, households_exited +8,514.95 [+3,896.31, +9,732.58] up, against a baseline in which no replicate breaks down. Removing the climate shocks does not: breakdown +0.00 [+0.00, +0.00] unresolved, with the tax base unresolved (tax_base_change_mu +2,718.02 [-4,560.20, +3,078.74] unresolved) and departures down (households_departed -534.23 [-580.57, -20.96] down).

## 10. Hold-out evidence

shaanxi-net-outflow scores 0.16 over the held-out years against 1.00 over the run as a whole, and 0.00 over the extrapolation; chongzhen-drought-sequence scores 0.00 over the held-out years. The direction of the outflow is matched; its timing is not.

## 11. Policy robustness

The gated region moves with the decision policy: 7 of 9 grid cells break down under the rule policy, 6 under random and 5 under utility, and only the rule policy's cell set is the reference's - so which cells break down is policy-dependent. That the *gate* is what carries the breakdown was tested in the P10 ablation, under one policy rather than three.

## 12. Historical support

shaanxi-net-outflow (grade C, hold-out, window 1628-1644): held-out years 0.16, whole run 1.00; chongzhen-drought-sequence (grade B, hold-out, window 1627-1644): held-out years 0.00

## 13. Historical challenge

The record's outflow is concentrated in the years the famine bites, and the model matches the run-long direction while missing those years: the held-out score is 0.16 against 1.00 for the run as a whole. A gate that leaks continuously is not the same as one that opens in a crisis.

## 14. Counterexample

The drought ablation: removing the climate shock keeps the baseline outcome - no breakdown in any replicate - so the shock is not the gate. Of the twelve arms in the ablation batch only the gate arm breaks down. Elsewhere in P10 breakdown does occur without it - 7 of the 40 Sobol runs and one tipping cell cross the line under extreme parameter draws - so the claim is about the declared arms, not the only route.

## 15. Falsifiable prediction

Shut the gate under the worst climate setting and breakdown should not occur: an arm that refuses permanent departure at severity floor 0.9 and nominal pressure 0.04 produces zero breakdowns in every replicate. Force the gate open under the mildest setting and at least one replicate should break down. Either result falsifies this card.

## 16. Uncertainty

One gate was intervened on. The relief and trade channels have arms whose effects on the crossed-line count are unresolved at four replicates, so the card does not claim they are not gates. Three counties, thirty-two cohorts, and a movement rule whose distress lines are declared rather than observed.

## Evidence cited

| kind | source | reading |
|---|---|---|
| ablation | `outputs/experiments/p10-ablations/runs.parquet` | OPEN_MIGRATION_EXIT breakdown +1.00 [+1.00, +1.00] up; NO_DROUGHT breakdown +0.00 [+0.00, +0.00] unresolved |
| counterfactual | `outputs/experiments/p10-ablations/runs.parquet` | NO_DROUGHT x FULL_MILITARY_PAY on indicators_crossed_end: joint +0.00 against -0.50 additive [+0.00, +1.00], additive |
| sensitivity | `outputs/experiments/p10-morris/runs.parquet` | strongest parameters on indicators_crossed_end: temporary_share_of_adults_per_month, reference_price_tael_per_shi, land_per_adult_capacity_mu |
| policy-robustness | `outputs/experiments/p12-robustness/tipping_grid.parquet` | cells with breakdown: rule 7, random 6, utility 5 |
| hold-out | `outputs/calibration/p09-*/predictive_checks.parquet` | shaanxi-net-outflow: held-out 0.16, extrapolation 0.00, whole run 1.00 |
| historical-challenge | `data/historical_patterns/01-drought-climate.yaml` | chongzhen-drought-sequence (grade B, hold-out): held-out years 0.00 - a refuted check, cited here as a challenge rather than as support |

Statuses across the book: 1 CONDITIONAL, 1 REJECTED, 2 SUPPORTED, 1 UNIDENTIFIED, 1 WEAK.
