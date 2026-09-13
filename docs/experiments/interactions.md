# P10 interactions: whether two mechanisms add up

Batch `p10-ablations`: 52 runs.

Additivity is the null: the joint arm's paired difference is compared with the sum of its
two single-arm differences, and a bootstrap interval on that gap decides. *Additive*
means the interval covers zero — the two mechanisms do not visibly interact at this
sample size, which is not the same as proving them independent.

| verdict | len |
| --- | --- |
| additive | 45 |
| super-additive | 3 |

## Every triple, on every reported metric

| metric | single_a | single_b | effect_a | effect_b | effect_joint | interaction | low | high | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| indicators_crossed_end | NO_DROUGHT | FULL_MILITARY_PAY | 0 | -0.5 | 0 | 0.5 | 0 | 1 | additive |
| peak_crossed | NO_DROUGHT | FULL_MILITARY_PAY | 1 | 0 | 1 | 0 | -1 | 1 | additive |
| breakdown | NO_DROUGHT | FULL_MILITARY_PAY | 0 | 0 | 0 | 0 | 0 | 0 | additive |
| tax_base_end_mu | NO_DROUGHT | FULL_MILITARY_PAY | 2718 | 2086 | 2970 | -1834 | -2577 | 218.9 | additive |
| tax_base_change_mu | NO_DROUGHT | FULL_MILITARY_PAY | 2718 | 2086 | 2970 | -1834 | -2577 | 218.9 | additive |
| receipts_over_quota_total | NO_DROUGHT | FULL_MILITARY_PAY | -0.05662 | -0.02372 | -0.07336 | 0.00698 | -0.004309 | 0.0154 | additive |
| households_departed | NO_DROUGHT | FULL_MILITARY_PAY | -534.2 | -122.5 | -534.2 | 122.5 | -38.44 | 164.1 | additive |
| households_exited | NO_DROUGHT | FULL_MILITARY_PAY | 0 | 0 | 0 | 0 | 0 | 17.72 | additive |
| migration_net_node_min | NO_DROUGHT | FULL_MILITARY_PAY | 331.1 | 23.48 | 331.1 | -23.48 | -159.5 | 96.93 | additive |
| market_active_link_share | NO_DROUGHT | FULL_MILITARY_PAY | -0.5833 | 0 | -0.5833 | 0 | 0 | 0 | additive |
| market_largest_component_share | NO_DROUGHT | FULL_MILITARY_PAY | -0.6429 | 0 | -0.6429 | 0 | 0 | 0 | additive |
| military_pay_arrears_end_tael | NO_DROUGHT | FULL_MILITARY_PAY | 4650 | 2300 | 6887 | -62.46 | -2516 | 682.7 | additive |
| military_pay_arrears_max_tael | NO_DROUGHT | FULL_MILITARY_PAY | 4650 | 2021 | 6887 | 216.2 | -2516 | 665.6 | additive |
| largest_band_share_max | NO_DROUGHT | FULL_MILITARY_PAY | -0.1456 | 0.05324 | -0.1457 | -0.0533 | -0.638 | 0.1376 | additive |
| largest_band_share_end | NO_DROUGHT | FULL_MILITARY_PAY | -0.076 | 0.004711 | -0.07606 | -0.004771 | -0.1783 | 0.05378 | additive |
| bands_at_end | NO_DROUGHT | FULL_MILITARY_PAY | 0 | 0.5 | 0 | -0.5 | -1 | 2 | additive |
| indicators_crossed_end | NO_DROUGHT | HIGH_RELIEF | 0 | 0 | 0 | 0 | 0 | 0 | additive |
| peak_crossed | NO_DROUGHT | HIGH_RELIEF | 1 | 0 | 1 | 0 | -1 | 0 | additive |
| breakdown | NO_DROUGHT | HIGH_RELIEF | 0 | 0 | 0 | 0 | 0 | 0 | additive |
| tax_base_end_mu | NO_DROUGHT | HIGH_RELIEF | 2718 | -25.87 | 2718 | 25.87 | -50.23 | 402.8 | additive |
| tax_base_change_mu | NO_DROUGHT | HIGH_RELIEF | 2718 | -25.87 | 2718 | 25.87 | -50.23 | 402.8 | additive |
| receipts_over_quota_total | NO_DROUGHT | HIGH_RELIEF | -0.05662 | -6.249e-05 | -0.05662 | 6.249e-05 | -0.001279 | 0.004249 | additive |
| households_departed | NO_DROUGHT | HIGH_RELIEF | -534.2 | 20.07 | -534.2 | -20.07 | -40 | 0 | additive |
| households_exited | NO_DROUGHT | HIGH_RELIEF | 0 | 0 | 0 | 0 | -0.3437 | 0 | additive |
| migration_net_node_min | NO_DROUGHT | HIGH_RELIEF | 331.1 | -0.182 | 331.1 | 0.182 | -25.26 | 40 | additive |
| market_active_link_share | NO_DROUGHT | HIGH_RELIEF | -0.5833 | 0 | -0.5833 | 0 | 0 | 0 | additive |
| market_largest_component_share | NO_DROUGHT | HIGH_RELIEF | -0.6429 | 0 | -0.6429 | 0 | 0 | 0 | additive |
| military_pay_arrears_end_tael | NO_DROUGHT | HIGH_RELIEF | 4650 | 36.35 | 4650 | -36.35 | -509.1 | 241.2 | additive |
| military_pay_arrears_max_tael | NO_DROUGHT | HIGH_RELIEF | 4650 | 63.78 | 4650 | -63.78 | -509.1 | 241.2 | additive |
| largest_band_share_max | NO_DROUGHT | HIGH_RELIEF | -0.1456 | -2.413e-05 | -0.1456 | 2.413e-05 | -0.006249 | 0.01526 | additive |
| largest_band_share_end | NO_DROUGHT | HIGH_RELIEF | -0.076 | 0.00268 | -0.076 | -0.00268 | -0.006967 | 0.00282 | additive |
| bands_at_end | NO_DROUGHT | HIGH_RELIEF | 0 | 0 | 0 | 0 | 0 | 0 | additive |
| indicators_crossed_end | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | 0.5 | 0 | 0.5 | 0 | 0 | 1 | additive |
| peak_crossed | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | 1 | 0 | 1 | 0 | -1 | 0 | additive |
| breakdown | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | 0 | 0 | 0 | 0 | 0 | 0 | additive |
| tax_base_end_mu | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | -2417 | -9540 | -9294 | 440.9 | 7.048 | 6792 | super-additive |
| tax_base_change_mu | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | -2417 | -9540 | -9294 | 440.9 | 7.048 | 6792 | super-additive |
| receipts_over_quota_total | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | -0.06172 | 0.006921 | -0.04715 | 0.005461 | -0.02279 | 0.009743 | additive |
| households_departed | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | 136.2 | 121.2 | 169.7 | -31.09 | -488.1 | 11.47 | additive |
| households_exited | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | 37.57 | 0 | 31.01 | -4.795 | -108.5 | 0 | additive |
| migration_net_node_min | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | -79.27 | 14.47 | -28.63 | 1.002 | -30.34 | 425.6 | additive |
| market_active_link_share | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | 0 | 0 | 0 | 0 | 0 | 0 | additive |
| market_largest_component_share | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | 0 | 0 | 0 | 0 | 0 | 0 | additive |
| military_pay_arrears_end_tael | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | 1556 | -844.2 | 682.9 | -156.9 | -1227 | 935.1 | additive |
| military_pay_arrears_max_tael | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | 1556 | -834.5 | 682.9 | -166.6 | -1227 | 935.1 | additive |
| largest_band_share_max | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | -0.001321 | 0.0003199 | -0.004085 | 0.001248 | -0.1011 | 0.002567 | additive |
| largest_band_share_end | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | -0.01515 | -0.006923 | -0.01567 | 0.005454 | 0.004993 | 0.06824 | super-additive |
| bands_at_end | NO_EXTRACTION_ESCALATION | NO_ELITE_CREDIT | 0 | 0 | 0 | 0 | 0 | 0 | additive |
