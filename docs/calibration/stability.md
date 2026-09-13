# P09 stability: the same experiment, two sampler seeds

Batch A `p09-cards87a14e9d-32p-ch1-s20260913` (32 particles, seed 20260913, 32 distinct parameter vectors) against batch B `p09-cards87a14e9d-32p-ch1-s991753` (32 particles, seed 991753, 32 distinct parameter vectors).

Both batches run the same priors, the same objective, the same scenario and the same
root seed for the sandbox — they differ only in the sampler's random seed. The declared
rule: a parameter is *reproducible* when the two medians differ by less than a quarter of
its prior range. A parameter that fails that test is reported as unpinned regardless of
how narrow its marginal is in either batch.

| parameter | prior | A median | B median | shift (share of range) | verdict |
| --- | --- | --- | --- | --- | --- |
| `yield_loss_scale` | [0.5, 2] | 0.675974 | 0.838232 | 0.108 | reproducible |
| `subsistence_grain_per_adult_month_shi` | [0.2, 0.6] | 0.349891 | 0.347317 | 0.006 | reproducible |
| `permanent_migration_unmet_ratio` | [0.1, 0.5] | 0.29857 | 0.1965 | 0.255 | unpinned |
| `temporary_migration_unmet_ratio` | [0.05, 0.4] | 0.161553 | 0.153859 | 0.022 | reproducible |
| `interest_rate_monthly` | [0.01, 0.1] | 0.069944 | 0.0279818 | 0.466 | unpinned |
| `assessed_value_tael_per_mu` | [0.05, 0.4] | 0.240188 | 0.198735 | 0.118 | reproducible |
| `elite_hidden_land_share` | [0, 0.6] | 0.358733 | 0.22666 | 0.220 | reproducible |
| `reference_price_tael_per_shi` | [0.2, 2] | 0.612457 | 1.05653 | 0.247 | reproducible |
| `permanent_share_of_households_per_month` | [0.005, 0.1] | 0.0510376 | 0.0356055 | 0.162 | reproducible |
| `temporary_share_of_adults_per_month` | [0.05, 0.4] | 0.20881 | 0.173214 | 0.102 | reproducible |
| `pay_tael_per_soldier_month` | [0.1, 1] | 0.507748 | 0.589401 | 0.091 | reproducible |
| `food_shi_per_soldier_month` | [0.2, 0.5] | 0.3252 | 0.281582 | 0.145 | reproducible |
| `food_shi_per_member_month` | [0.2, 0.5] | 0.367587 | 0.332234 | 0.118 | reproducible |

Reproducible in 11 of 13 parameters.

Unpinned parameters, with the two batches' locations for a reader to judge:

- `interest_rate_monthly`: 0.069944 against 0.0279818, a shift of 0.466 of the range [0.01, 0.1].
- `permanent_migration_unmet_ratio`: 0.29857 against 0.1965, a shift of 0.255 of the range [0.1, 0.5].

## What this does and does not establish

- It does establish that the ensemble's *location* is a property of the objective and the
  prior rather than of one sampling run.
- It does not establish that the calibration window identifies these parameters
  individually: the equifinality table in `posterior.md` shows which pairs trade off, and
  a reproducible ridge is still a ridge.
- Two seeds are the cheapest version of this check, not a convergence study. A third seed
  would strengthen it, and a regional-scale batch would test whether it holds beyond the
  toy fixture.
