# P09 posterior: what the ensemble identifies, and what it cannot separate

Batch `p09-cards87a14e9d-32p-ch1-s20260913`: 32 draws, 32 particles, 1 chain(s).

The verdicts follow the declared rules: the posterior interquartile range is compared
with the prior's full range, at most half counts as *identified*, at least four fifths as
*unresolved*, and the band between as *weak*; two parameters correlating at least 0.7 in
absolute value are reported as a trade-off.

## Identifiability

| parameter | prior | posterior q1 | median | q3 | contraction | verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `yield_loss_scale` | [0.5, 2] | 0.613132 | 0.675974 | 0.816463 | 0.136 | identified |
| `subsistence_grain_per_adult_month_shi` | [0.2, 0.6] | 0.27635 | 0.349891 | 0.45877 | 0.456 | identified |
| `permanent_migration_unmet_ratio` | [0.1, 0.5] | 0.21573 | 0.29857 | 0.371233 | 0.389 | identified |
| `temporary_migration_unmet_ratio` | [0.05, 0.4] | 0.106782 | 0.161553 | 0.233773 | 0.363 | identified |
| `interest_rate_monthly` | [0.01, 0.1] | 0.0492985 | 0.069944 | 0.0824187 | 0.368 | identified |
| `assessed_value_tael_per_mu` | [0.05, 0.4] | 0.159923 | 0.240188 | 0.300296 | 0.401 | identified |
| `elite_hidden_land_share` | [0, 0.6] | 0.253353 | 0.358733 | 0.41962 | 0.277 | identified |
| `reference_price_tael_per_shi` | [0.2, 2] | 0.341536 | 0.612457 | 0.991558 | 0.361 | identified |
| `permanent_share_of_households_per_month` | [0.005, 0.1] | 0.0340876 | 0.0510376 | 0.0686369 | 0.364 | identified |
| `temporary_share_of_adults_per_month` | [0.05, 0.4] | 0.0990902 | 0.20881 | 0.283601 | 0.527 | weak |
| `pay_tael_per_soldier_month` | [0.1, 1] | 0.381312 | 0.507748 | 0.625068 | 0.271 | identified |
| `food_shi_per_soldier_month` | [0.2, 0.5] | 0.298439 | 0.3252 | 0.418021 | 0.399 | identified |
| `food_shi_per_member_month` | [0.2, 0.5] | 0.297831 | 0.367587 | 0.421526 | 0.412 | identified |

Counts: identified 12, weak 1.

## Equifinality

No pair reaches the declared 0.7 line at this batch size, so no trade-off is reported. That is a statement about this ensemble, not a claim that the parameters are separable in the model.

Distinct parameter vectors in the particle set: 32 of 32. Fewer distinct vectors than particles means the sampler resampled copies; the weighted distribution is unchanged by the copies, but a reader should not read a count of rows as a count of independent draws.

## The target patterns across the ensemble

| pattern | draws fully consistent | mean score | worst score |
| --- | --- | --- | --- |
| `absorption-of-deserters-and-refugees` | 0.25 | 0.250 | 0.333 |
| `debt-transfers-land` | 0.81 | 0.062 | 0.333 |
| `famine-local-price-extremes` | 0.38 | 0.594 | 1.000 |
| `land-abandonment-in-famine` | 1.00 | 0.000 | 0.000 |
| `receipts-shortfall-chronic` | 1.00 | 0.000 | 0.000 |
