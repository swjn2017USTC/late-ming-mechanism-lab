# M005 - Insurgent Consolidation

**Status: SUPPORTED**

*Question.* Do armed groups consolidate into fewer, larger organisations as the crisis proceeds?

## 1. Micro conditions

- Bands grow by taking in the households that the county can no longer feed - the intake track - and by levying grain from the population around them.
- Cohesion is a binding constraint: a band fed less than its members need loses cohesion and can lose members again.

## 2. Meso conditions

- Suppression is the state's coercive reach against the bands, and its removal changes which bands survive.
- Grain seized by a band is grain the county cannot assess or the army cannot buy, so band growth and fiscal capacity compete for the same harvest.

## 3. Causal chain

- Recruitment from distress and from the soldiery continues through the crisis years.
- Bands form faster than they dissolve, and the largest band's share of the armed population rises while the number of bands moves with suppression.
- The armed population becomes a smaller number of larger organisations, whose grain demands the record describes as exceeding what a county can collect - a quantity no artifact in this project measures.

## 4. Trigger

Suppression falling away: with the coercive reach removed the largest band's share falls, so it is suppression that concentrates the force rather than the crisis alone. What happens to the number of bands in that arm is unresolved.

## 5. Macro outcome

Armed force concentrated in fewer, larger bands - present in every declared policy, at five of six replicates in each - alongside a county base that cannot meet both the pay claim and the relief demand.

## 6. Necessary versus facilitating conditions

- A recruitment pool of distressed households and unpaid soldiers. (*micro*, necessary)
- Grain that can be seized from the surrounding population. (*micro*, necessary)
- Suppression weak enough that large bands survive their own expansion. (*meso*, facilitating)
- Trade disruption that raises the price of the food a band must buy. (*meso*, facilitating)

## 7. Time lag

Over the run rather than at a tick: the P12 reading compares the opening band count with the final one over 240 ticks. No artifact records the month in which the largest band's share peaks, so the consolidation's pace is unresolved.

## 8. Sensitivity evidence

The largest elementary effects on the largest band share are reference_price_tael_per_shi, food_shi_per_soldier_month, assessed_value_tael_per_mu - the reference price, the soldier's food ration and the assessed value - while the crossed-line count leads with temporary_share_of_adults_per_month, reference_price_tael_per_shi. The two rankings share one leader, not three, so the band share does not simply inherit the breakdown boundary's drivers, and no band-specific parameter leads either.

## 9. Ablation evidence

Suppression is load-bearing and the direction is measured: LOW_REPRESSION (largest_band_share_max -0.05 [-0.10, -0.01] down) lowers the largest band's share, while leaving the number of bands unresolved. The merger rule is not load-bearing: NO_BAND_MERGER produces the same merge count as the baseline (0 in both, bands at end 5.25 against 5.25), because no merge fires anywhere in the batch.

## 10. Hold-out evidence

many-bands-then-consolidation is satisfied in 0.62 of posterior draws over the held-out years and 0.94 over the run as a whole, and absorption-of-deserters-and-refugees in 0.75 of draws. The shape is matched over the run; the held-out years score lower than the run as a whole.

## 11. Policy robustness

Robust: present in rule 0.83, utility 0.83, random 0.83 of replicates (P12 verdict 'robust' at 3 of 3 arms). The only policy-dependent part is the intensity: the utility arm's median strength is the highest of the three.

## 12. Historical support

many-bands-then-consolidation (grade B, hold-out, window 1630-1644): held-out years 0.62, whole run 0.94; absorption-of-deserters-and-refugees (grade B, target, window 1628-1644): calibration window 0.75

## 13. Historical challenge

The record has thirty-odd bands in the early 1630s and one dominant organisation by 1644, an order of magnitude of consolidation; the model moves from five bands to three to nine with the largest share rising from 0.20 to about 0.38. The direction is matched and the magnitude is far smaller, so the card claims consolidation, not the scale the record describes.

## 14. Counterexample

The merger arm: raising the cohesion bar to its maximum changes nothing (0 merges against the baseline's 0), and consolidation still appears. Whatever produces it, it is not the merger rule the model's documentation names.

## 15. Falsifiable prediction

Lower the cohesion bar so that merges actually fire, and the largest band's share should exceed the 0.382 maximum the declared policies reach. If merges fire and the share does not rise, the merger link is decorative and the mechanism's chain should be rewritten around formation and dissolution.

## 16. Uncertainty

The causal link the model names - merging on cohesion - was never exercised: zero merges in every arm of the P10 batch, at every level. Consolidation as an outcome is robust; its attribution inside the model is not, and this card does not claim the outcome and the link together. Five or six replicates per policy is enough to show presence, not to estimate the strength.

## Evidence cited

| kind | source | reading |
|---|---|---|
| policy-robustness | `outputs/experiments/p12-robustness/mechanism_readings.parquet` | present in rule 0.83, utility 0.83, random 0.83 of replicates; verdict robust |
| ablation | `outputs/experiments/p10-ablations/runs.parquet` | LOW_REPRESSION largest_band_share_max -0.05 [-0.10, -0.01] down; NO_BAND_MERGER merges 0 against baseline 0 |
| hold-out | `outputs/calibration/p09-*/predictive_checks.parquet` | many-bands-then-consolidation held-out 0.62, whole run 0.94 |
| sensitivity | `outputs/experiments/p10-morris/runs.parquet` | largest band share leads with reference_price_tael_per_shi, food_shi_per_soldier_month, assessed_value_tael_per_mu |
| historical-support | `lorge-2005` | many-bands-then-consolidation (grade B, hold-out, window 1630-1644): held-out years 0.62 |

Statuses across the book: 1 CONDITIONAL, 1 REJECTED, 2 SUPPORTED, 1 UNIDENTIFIED, 1 WEAK.
