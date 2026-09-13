# P10 tipping: the region, not the curve

Grid batch `p10-tipping`: 9 runs over ['temporary_share_of_adults_per_month', 'reference_price_tael_per_shi'] at 3 values per axis and 1 replicates per cell.

The two axes are the parameters with the largest Morris elementary effect on
`indicators_crossed_end`, sampled inside their card ranges. Every cell is the same run under
the same random numbers apart from the two parameters, so the surface is the model's
response to them rather than to a fresh sample.

The axes recorded in the batch manifest are `temporary_share_of_adults_per_month`, `reference_price_tael_per_shi`.

Collapse share: rows `temporary_share_of_adults_per_month`, columns `reference_price_tael_per_shi`.

| temporary_share_of_adults_per_month | 0.2 | 1.1 | 2.0 |
| --- | --- | --- | --- |
| 0.05 | 1 | 0 | 0 |
| 0.225 | 0 | 0 | 0 |
| 0.4 | 0 | 0 | 0 |

Mean peak crossed lines: rows `temporary_share_of_adults_per_month`, columns `reference_price_tael_per_shi`.

| temporary_share_of_adults_per_month | 0.2 | 1.1 | 2.0 |
| --- | --- | --- | --- |
| 0.05 | 6 | 5 | 5 |
| 0.225 | 5 | 5 | 5 |
| 0.4 | 5 | 5 | 5 |

The response to `temporary_share_of_adults_per_month` at the grid's own values (medians of `indicators_crossed_end`):

| value | runs | median | q1 | q3 | curvature |
| --- | --- | --- | --- | --- | --- |
| 0.05 | 3 | 5 | 5 | 5 | 0 |
| 0.225 | 3 | 5 | 5 | 5 | 0 |
| 0.4 | 3 | 5 | 5 | 5 | 0 |

The response to `reference_price_tael_per_shi`, measured the same way:

| value | runs | median | q1 | q3 | curvature |
| --- | --- | --- | --- | --- | --- |
| 0.2 | 3 | 5 | 5 | 5 | 0 |
| 1.1 | 3 | 5 | 5 | 5 | 0 |
| 2 | 3 | 5 | 5 | 5 | 0 |

## The Morris ranking behind the axes

| parameter | mu | mu_star | sigma |
| --- | --- | --- | --- |
| temporary_share_of_adults_per_month | 0.75 | 2.25 | 3.182 |
| reference_price_tael_per_shi | 0 | 1.5 | 2.121 |
| land_per_adult_capacity_mu | -0.75 | 0.75 | 1.061 |
| assessed_value_tael_per_mu | -0.75 | 0.75 | 1.061 |
| subsistence_grain_per_adult_month_shi | -0.75 | 0.75 | 1.061 |
| food_shi_per_soldier_month | -0.75 | 0.75 | 1.061 |
| pay_tael_per_soldier_month | -0.75 | 0.75 | 1.061 |
| food_shi_per_member_month | 0 | 0 | 0 |
| yield_loss_scale | 0 | 0 | 0 |
| interest_rate_monthly | 0 | 0 | 0 |
| elite_hidden_land_share | 0 | 0 | 0 |
| permanent_migration_unmet_ratio | 0 | 0 | 0 |
| temporary_migration_unmet_ratio | 0 | 0 | 0 |
| wage_grain_shi_per_adult_month | 0 | 0 | 0 |
| permanent_share_of_households_per_month | 0 | 0 | 0 |
