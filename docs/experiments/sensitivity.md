# P10 sensitivity: which parameters the model's behaviour depends on

Morris batch `p10-morris` (32 runs, 2 trajectories over 15 parameters), then Sobol batch `p10-sobol` (40 runs, base 4, second-order indices on).

Every swept parameter has a P08 card range; the design moves it inside that range and
nothing else changes between rows, so a difference across the design is the parameter.
Because a mean would hide everything interesting, the tables carry the elementary-effect
dispersion, the Sobol indices with their confidence intervals, and the binned response
curves that show where a response bends.

## Morris elementary effects

`mu_star` is the mean absolute elementary effect (influence), `sigma` its spread
(non-linearity or interaction), `mu` the signed mean (direction).

| output | parameter | mu | mu_star | sigma |
| --- | --- | --- | --- | --- |
| households_departed | subsistence_grain_per_adult_month_shi | 2.259e+04 | 2.259e+04 | 1.203e+04 |
| households_departed | permanent_share_of_households_per_month | 2.107e+04 | 2.107e+04 | 1381 |
| households_departed | permanent_migration_unmet_ratio | -8561 | 8561 | 7314 |
| households_departed | yield_loss_scale | 8526 | 8526 | 1.153e+04 |
| households_departed | reference_price_tael_per_shi | -7633 | 7633 | 9072 |
| households_departed | wage_grain_shi_per_adult_month | -4179 | 4179 | 2183 |
| households_departed | food_shi_per_soldier_month | 3813 | 3813 | 3530 |
| households_departed | temporary_share_of_adults_per_month | -2800 | 2800 | 3027 |
| households_departed | assessed_value_tael_per_mu | -2705 | 2705 | 2371 |
| households_departed | interest_rate_monthly | -2323 | 2323 | 3210 |
| households_departed | land_per_adult_capacity_mu | -1420 | 1420 | 2009 |
| households_departed | pay_tael_per_soldier_month | -28.84 | 1170 | 1655 |
| households_departed | temporary_migration_unmet_ratio | 975.5 | 975.5 | 1380 |
| households_departed | food_shi_per_member_month | -103.8 | 103.8 | 146.7 |
| households_departed | elite_hidden_land_share | 0 | 0 | 0 |
| indicators_crossed_end | temporary_share_of_adults_per_month | 0.75 | 2.25 | 3.182 |
| indicators_crossed_end | reference_price_tael_per_shi | 0 | 1.5 | 2.121 |
| indicators_crossed_end | pay_tael_per_soldier_month | -0.75 | 0.75 | 1.061 |
| indicators_crossed_end | food_shi_per_soldier_month | -0.75 | 0.75 | 1.061 |
| indicators_crossed_end | subsistence_grain_per_adult_month_shi | -0.75 | 0.75 | 1.061 |
| indicators_crossed_end | assessed_value_tael_per_mu | -0.75 | 0.75 | 1.061 |
| indicators_crossed_end | land_per_adult_capacity_mu | -0.75 | 0.75 | 1.061 |
| indicators_crossed_end | food_shi_per_member_month | 0 | 0 | 0 |
| indicators_crossed_end | yield_loss_scale | 0 | 0 | 0 |
| indicators_crossed_end | permanent_share_of_households_per_month | 0 | 0 | 0 |
| indicators_crossed_end | wage_grain_shi_per_adult_month | 0 | 0 | 0 |
| indicators_crossed_end | temporary_migration_unmet_ratio | 0 | 0 | 0 |
| indicators_crossed_end | permanent_migration_unmet_ratio | 0 | 0 | 0 |
| indicators_crossed_end | elite_hidden_land_share | 0 | 0 | 0 |
| indicators_crossed_end | interest_rate_monthly | 0 | 0 | 0 |
| largest_band_share_max | reference_price_tael_per_shi | 0.562 | 0.562 | 0.2655 |
| largest_band_share_max | food_shi_per_soldier_month | -0.5512 | 0.5512 | 0.7017 |
| largest_band_share_max | assessed_value_tael_per_mu | -0.4845 | 0.5382 | 0.7611 |
| largest_band_share_max | permanent_migration_unmet_ratio | -0.4148 | 0.4148 | 0.4737 |
| largest_band_share_max | pay_tael_per_soldier_month | -0.317 | 0.317 | 0.4104 |
| largest_band_share_max | yield_loss_scale | -0.2719 | 0.2719 | 0.2417 |
| largest_band_share_max | wage_grain_shi_per_adult_month | -0.1994 | 0.1994 | 0.2612 |
| largest_band_share_max | temporary_share_of_adults_per_month | -0.09816 | 0.09816 | 0.1289 |
| largest_band_share_max | subsistence_grain_per_adult_month_shi | 0.0818 | 0.0818 | 0.1157 |
| largest_band_share_max | food_shi_per_member_month | -0.06839 | 0.06839 | 0.09671 |
| largest_band_share_max | land_per_adult_capacity_mu | -0.03567 | 0.03702 | 0.05235 |
| largest_band_share_max | permanent_share_of_households_per_month | 0.03608 | 0.03608 | 0.05103 |
| largest_band_share_max | interest_rate_monthly | -0.0001029 | 0.0001029 | 0.0001456 |
| largest_band_share_max | temporary_migration_unmet_ratio | 0 | 0 | 0 |
| largest_band_share_max | elite_hidden_land_share | 0 | 0 | 0 |
| tax_base_change_mu | permanent_share_of_households_per_month | -1.104e+05 | 1.104e+05 | 1.039e+05 |
| tax_base_change_mu | subsistence_grain_per_adult_month_shi | -5.719e+04 | 5.719e+04 | 6.573e+04 |
| tax_base_change_mu | reference_price_tael_per_shi | 4.739e+04 | 4.739e+04 | 3.396e+04 |
| tax_base_change_mu | wage_grain_shi_per_adult_month | 4.706e+04 | 4.706e+04 | 1.126e+04 |
| tax_base_change_mu | yield_loss_scale | -2.606e+04 | 2.606e+04 | 2.606e+04 |
| tax_base_change_mu | permanent_migration_unmet_ratio | 1.196e+04 | 1.196e+04 | 8620 |
| tax_base_change_mu | temporary_share_of_adults_per_month | 7939 | 7939 | 5780 |
| tax_base_change_mu | pay_tael_per_soldier_month | 1574 | 7818 | 1.106e+04 |
| tax_base_change_mu | interest_rate_monthly | 5923 | 6174 | 8732 |
| tax_base_change_mu | food_shi_per_soldier_month | -4811 | 4811 | 1814 |
| tax_base_change_mu | assessed_value_tael_per_mu | 3930 | 3930 | 3524 |
| tax_base_change_mu | land_per_adult_capacity_mu | 1075 | 1259 | 1780 |
| tax_base_change_mu | food_shi_per_member_month | 258.4 | 258.7 | 365.9 |
| tax_base_change_mu | temporary_migration_unmet_ratio | -110.9 | 111.5 | 157.7 |
| tax_base_change_mu | elite_hidden_land_share | 0 | 0 | 0 |

Selection rule: for `indicators_crossed_end`, the parameters whose `mu_star` is at least a
tenth of the largest, capped at six. Selected: `land_per_adult_capacity_mu`, `assessed_value_tael_per_mu`, `reference_price_tael_per_shi`, `temporary_share_of_adults_per_month`.

The Sobol batch ran the selection recorded in its manifest: `land_per_adult_capacity_mu`, `assessed_value_tael_per_mu`, `reference_price_tael_per_shi`, `temporary_share_of_adults_per_month`.

## Sobol first-order and total indices

| parameter | output | value | confidence_low | confidence_high |
| --- | --- | --- | --- | --- |
| reference_price_tael_per_shi | households_departed | 1.135 | -2.305 | 4.576 |
| land_per_adult_capacity_mu | households_departed | 0.135 | -9.034 | 9.304 |
| temporary_share_of_adults_per_month | households_departed | -0.6182 | -1.536 | 0.2994 |
| assessed_value_tael_per_mu | households_departed | -2.941 | -8.709 | 2.827 |
| land_per_adult_capacity_mu | indicators_crossed_end | nan | nan | nan |
| assessed_value_tael_per_mu | indicators_crossed_end | nan | nan | nan |
| reference_price_tael_per_shi | indicators_crossed_end | nan | nan | nan |
| temporary_share_of_adults_per_month | indicators_crossed_end | nan | nan | nan |
| assessed_value_tael_per_mu | largest_band_share_max | 3.516 | -0.3881 | 7.421 |
| land_per_adult_capacity_mu | largest_band_share_max | 0.1337 | -0.01415 | 0.2816 |
| temporary_share_of_adults_per_month | largest_band_share_max | -0.03317 | -0.08369 | 0.01736 |
| reference_price_tael_per_shi | largest_band_share_max | -0.2971 | -0.4981 | -0.096 |
| reference_price_tael_per_shi | tax_base_change_mu | 1.19 | 0.6649 | 1.715 |
| land_per_adult_capacity_mu | tax_base_change_mu | 0.1677 | -4.053 | 4.388 |
| temporary_share_of_adults_per_month | tax_base_change_mu | -0.6202 | -1.31 | 0.07002 |
| assessed_value_tael_per_mu | tax_base_change_mu | -1.366 | -3.159 | 0.4261 |

| parameter | output | value | confidence_low | confidence_high |
| --- | --- | --- | --- | --- |
| assessed_value_tael_per_mu | households_departed | 5.289 | -7.547 | 18.13 |
| reference_price_tael_per_shi | households_departed | 0.8718 | -1.895 | 3.638 |
| land_per_adult_capacity_mu | households_departed | 0.7215 | -5.994 | 7.437 |
| temporary_share_of_adults_per_month | households_departed | 0.2834 | 0.04416 | 0.5226 |
| land_per_adult_capacity_mu | indicators_crossed_end | nan | nan | nan |
| assessed_value_tael_per_mu | indicators_crossed_end | nan | nan | nan |
| reference_price_tael_per_shi | indicators_crossed_end | nan | nan | nan |
| temporary_share_of_adults_per_month | indicators_crossed_end | nan | nan | nan |
| assessed_value_tael_per_mu | largest_band_share_max | 8.893 | -4.057 | 21.84 |
| reference_price_tael_per_shi | largest_band_share_max | 0.08802 | -0.08689 | 0.2629 |
| land_per_adult_capacity_mu | largest_band_share_max | 0.008646 | 0.002551 | 0.01474 |
| temporary_share_of_adults_per_month | largest_band_share_max | 0.0008374 | -0.0003984 | 0.002073 |
| assessed_value_tael_per_mu | tax_base_change_mu | 1.024 | -0.1968 | 2.244 |
| reference_price_tael_per_shi | tax_base_change_mu | 0.9291 | 0.4969 | 1.361 |
| land_per_adult_capacity_mu | tax_base_change_mu | 0.7473 | -2.907 | 4.401 |
| temporary_share_of_adults_per_month | tax_base_change_mu | 0.3275 | -0.001983 | 0.6569 |

## Sobol second-order indices: the interactions

A second-order index is the share of an output's variance attributable to two parameters
together beyond their separate effects. The five strongest pairs per output are shown;
the confidence interval is in the table for a reason, since this design is small.

| output | parameter_a | parameter_b | value | confidence_low | confidence_high |
| --- | --- | --- | --- | --- | --- |
| households_departed | assessed_value_tael_per_mu | temporary_share_of_adults_per_month | 3.946 | -1.085 | 8.978 |
| households_departed | reference_price_tael_per_shi | temporary_share_of_adults_per_month | 3.181 | -10.68 | 17.04 |
| households_departed | assessed_value_tael_per_mu | reference_price_tael_per_shi | 2.782 | -2.748 | 8.311 |
| households_departed | land_per_adult_capacity_mu | assessed_value_tael_per_mu | 2.687 | -19.47 | 24.85 |
| households_departed | land_per_adult_capacity_mu | temporary_share_of_adults_per_month | 0.4655 | -25.98 | 26.91 |
| indicators_crossed_end | land_per_adult_capacity_mu | assessed_value_tael_per_mu | nan | nan | nan |
| indicators_crossed_end | land_per_adult_capacity_mu | reference_price_tael_per_shi | nan | nan | nan |
| indicators_crossed_end | land_per_adult_capacity_mu | temporary_share_of_adults_per_month | nan | nan | nan |
| indicators_crossed_end | assessed_value_tael_per_mu | reference_price_tael_per_shi | nan | nan | nan |
| indicators_crossed_end | assessed_value_tael_per_mu | temporary_share_of_adults_per_month | nan | nan | nan |
| largest_band_share_max | land_per_adult_capacity_mu | reference_price_tael_per_shi | -0.1749 | -0.998 | 0.6482 |
| largest_band_share_max | land_per_adult_capacity_mu | temporary_share_of_adults_per_month | -0.2375 | -1.254 | 0.7785 |
| largest_band_share_max | land_per_adult_capacity_mu | assessed_value_tael_per_mu | -0.3333 | -1.394 | 0.7269 |
| largest_band_share_max | reference_price_tael_per_shi | temporary_share_of_adults_per_month | -0.5581 | -3.085 | 1.969 |
| largest_band_share_max | assessed_value_tael_per_mu | reference_price_tael_per_shi | -1.62 | -5.314 | 2.074 |
| tax_base_change_mu | reference_price_tael_per_shi | temporary_share_of_adults_per_month | 2.214 | -4.114 | 8.541 |
| tax_base_change_mu | assessed_value_tael_per_mu | temporary_share_of_adults_per_month | 2.068 | 0.6437 | 3.492 |
| tax_base_change_mu | land_per_adult_capacity_mu | assessed_value_tael_per_mu | 2.052 | -6.721 | 10.83 |
| tax_base_change_mu | assessed_value_tael_per_mu | reference_price_tael_per_shi | 1.19 | -0.5419 | 2.921 |
| tax_base_change_mu | land_per_adult_capacity_mu | temporary_share_of_adults_per_month | 1.036 | -4.035 | 6.106 |

## Response curves, and where they bend

Binned medians of `indicators_crossed_end` along the three strongest parameters, with the
second difference of those medians: a straight line reads as zero, a bend is a spike.

`land_per_adult_capacity_mu` against `indicators_crossed_end` (Sobol design):

| bin | bin_low | bin_high | runs | median | q1 | q3 | curvature |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 5.989 | 10.57 | 10 | 5 | 5 | 5 | 0 |
| 1 | 10.57 | 15.16 | 15 | 6 | 5 | 6 | 0 |
| 2 | 15.16 | 19.74 | 15 | 5 | 5 | 6 | -0.09516 |

`assessed_value_tael_per_mu` against `indicators_crossed_end` (Sobol design):

| bin | bin_low | bin_high | runs | median | q1 | q3 | curvature |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 0.06129 | 0.1609 | 15 | 6 | 5 | 6 | 0 |
| 1 | 0.1609 | 0.2604 | 5 | 6 | 5 | 6 | 0 |
| 2 | 0.2604 | 0.36 | 20 | 5 | 5 | 5 | -100.8 |

`reference_price_tael_per_shi` against `indicators_crossed_end` (Sobol design):

| bin | bin_low | bin_high | runs | median | q1 | q3 | curvature |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 0.3932 | 0.9037 | 15 | 6 | 5 | 6 | 0 |
| 1 | 0.9037 | 1.414 | 10 | 5 | 5 | 6 | 0 |
| 2 | 1.414 | 1.925 | 15 | 5 | 5 | 5 | 3.837 |

