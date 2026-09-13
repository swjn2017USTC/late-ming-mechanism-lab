# P10 ablation: which mechanisms the crisis needs

Batch `p10-ablations`: 52 runs, 13 arms at 4 replicates, 240 ticks, base seed 20260914.

Every arm runs under common random numbers: replicate *r* of every arm starts from the
same root seed, so a paired difference is the declared intervention rather than a fresh
weather sequence. The table reports medians and quartiles per arm, the paired median
difference with a bootstrap interval, the share of replicates that move the same way, and
Cliff's delta. A direction is claimed only when the interval excludes zero.

## The arms and what each one changes

| arm | question | what it changes |
| --- | --- | --- |
| `BASELINE` | the declared reference condition: escalation and disruption on, everything else the P07 sandbox's own defaults | nothing (the reference arm) |
| `NO_DROUGHT` | does the crisis need the climate shocks at all? | scenario.monthly_event_probability: 0.4 to 0.0; scenario.severity_floor: 0.6 to 0.0 |
| `NO_EXTRACTION_ESCALATION` | does the fiscal apparatus need to escalate against arrears? | extraction_policy: ArrearsEscalation(name='arrears-escalation', base_effort=0.5, arrears_weight=0.5, effort_ceiling=1.0) to FixedExtraction(name='fixed', effort=0.5) |
| `FULL_MILITARY_PAY` | is the army's crisis fiscal or military? | scenario.pay_share_of_treasury: 0.5 to 1.0 |
| `HIGH_RELIEF` | does relief capacity change the trajectory? | capacity.relief: 0.5 to 1.0; elite.relief_eligibility_unmet_ratio: 0.05 to 0.1; elite.relief_share_of_grain_stock: 0.05 to 0.2; fiscal.relief_eligibility_unmet_ratio: 0.05 to 0.1; fiscal.relief_share_of_need: 0.5 to 1.0 |
| `NO_ELITE_CREDIT` | does household survival depend on borrowed silver? | elite.loan_to_value: 0.5 to 0.0 |
| `NO_TRADE_DISRUPTION` | does the market need the transport regime to be harsh? | disruption: ScaledDisruption(name='p10-baseline', risk_scale=1.5, capacity_scale=0.5, blocked_links=()) to CalmTrade(name='calm') |
| `NO_BAND_MERGER` | is consolidation, rather than band numbers, what concentrates armed force? | band.merge_cohesion_above: 0.6 to 1.0 |
| `LOW_REPRESSION` | is suppression load-bearing, and in which direction? | military.suppression_effectiveness: 0.02 to 0.0 |
| `OPEN_MIGRATION_EXIT` | is the mobility gate, rather than distress itself, what decides who leaves? | household.temporary_migration_unmet_ratio: 0.05 to 0.0; household.permanent_migration_unmet_ratio: 0.2 to 0.0; migration.cost_tael_per_household: 0.5 to 0.0; migration.cost_tael_per_adult: 0.2 to 0.0; migration.transit_loss_share: 0.5 to 0.0; migration.minimum_households_to_move: 5.0 to 1.0 |
| `JOINT_NO_DROUGHT+FULL_MILITARY_PAY` | is fiscal capacity for the army worth anything without the climate shocks? | scenario.monthly_event_probability: 0.4 to 0.0; scenario.severity_floor: 0.6 to 0.0; scenario.pay_share_of_treasury: 0.5 to 1.0 |
| `JOINT_NO_DROUGHT+HIGH_RELIEF` | does relief matter in a year with no harvest failure? | scenario.monthly_event_probability: 0.4 to 0.0; scenario.severity_floor: 0.6 to 0.0; capacity.relief: 0.5 to 1.0; elite.relief_eligibility_unmet_ratio: 0.05 to 0.1; elite.relief_share_of_grain_stock: 0.05 to 0.2; fiscal.relief_eligibility_unmet_ratio: 0.05 to 0.1; fiscal.relief_share_of_need: 0.5 to 1.0 |
| `JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT` | do extraction pressure and credit access substitute for one another? | extraction_policy: ArrearsEscalation(name='arrears-escalation', base_effort=0.5, arrears_weight=0.5, effort_ceiling=1.0) to FixedExtraction(name='fixed', effort=0.5); elite.loan_to_value: 0.5 to 0.0 |

The baseline is the declared reference: the escalating extraction policy and the declared
disruption regime are **on**, which the P07 sandbox leaves off, so the two ablations that
remove them have something to remove. The disruption regime is a scenario declaration,
not a measurement: the model has no endogenous link from armed activity to transport yet.

## Paired comparisons, per metric and arm

| metric | arm | baseline_median | arm_median | arm_q1 | arm_q3 | median_difference | difference_low | difference_high | share_increase | cliffs_delta | direction |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| indicators_crossed_end | FULL_MILITARY_PAY | 5 | 4 | 4 | 4.25 | -0.5 | -1 | 0 | 0 | -0.5 | unresolved |
| peak_crossed | FULL_MILITARY_PAY | 4 | 4 | 4 | 4.25 | 0 | -1 | 1 | 0.25 | 0 | unresolved |
| breakdown | FULL_MILITARY_PAY | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | unresolved |
| tax_base_end_mu | FULL_MILITARY_PAY | 1.653e+05 | 1.68e+05 | 1.673e+05 | 1.695e+05 | 2086 | 33.17 | 2829 | 1 | 0.625 | up |
| tax_base_change_mu | FULL_MILITARY_PAY | -1.548e+04 | -1.276e+04 | -1.347e+04 | -1.128e+04 | 2086 | 33.17 | 2829 | 1 | 0.625 | up |
| receipts_over_quota_total | FULL_MILITARY_PAY | 0.267 | 0.2522 | 0.2452 | 0.2624 | -0.02372 | -0.03215 | -0.01244 | 0 | -0.625 | down |
| households_departed | FULL_MILITARY_PAY | 534.2 | 386.7 | 279.2 | 432.4 | -122.5 | -164.1 | 38.44 | 0.25 | -0.5 | unresolved |
| households_exited | FULL_MILITARY_PAY | 0 | 0 | 0 | 77.82 | 0 | -17.72 | 0 | 0 | -0.0625 | unresolved |
| migration_net_node_min | FULL_MILITARY_PAY | -331.1 | -336.9 | -383.1 | -233.2 | 23.48 | -96.93 | 159.5 | 0.5 | 0.125 | unresolved |
| market_active_link_share | FULL_MILITARY_PAY | 0.9167 | 0.9167 | 0.8333 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| market_largest_component_share | FULL_MILITARY_PAY | 0.9286 | 0.9286 | 0.8571 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| military_pay_arrears_end_tael | FULL_MILITARY_PAY | 1.575e+04 | 1.904e+04 | 1.726e+04 | 2.015e+04 | 2300 | 1555 | 4753 | 1 | 0.5 | up |
| military_pay_arrears_max_tael | FULL_MILITARY_PAY | 1.575e+04 | 1.904e+04 | 1.726e+04 | 2.016e+04 | 2021 | 1572 | 4753 | 1 | 0.5 | up |
| largest_band_share_max | FULL_MILITARY_PAY | 0.404 | 0.4969 | 0.4737 | 0.6276 | 0.05324 | -0.1377 | 0.6379 | 0.75 | 0.625 | unresolved |
| largest_band_share_end | FULL_MILITARY_PAY | 0.3344 | 0.361 | 0.325 | 0.4091 | 0.004711 | -0.05384 | 0.1783 | 0.75 | 0.375 | unresolved |
| bands_at_end | FULL_MILITARY_PAY | 4 | 5 | 4.75 | 5.5 | 0.5 | -2 | 1 | 0.5 | 0.3125 | unresolved |
| indicators_crossed_end | HIGH_RELIEF | 5 | 5 | 4.75 | 5 | 0 | 0 | 0 | 0 | 0 | unresolved |
| peak_crossed | HIGH_RELIEF | 4 | 4.5 | 4 | 5 | 0 | 0 | 1 | 0.25 | 0.25 | unresolved |
| breakdown | HIGH_RELIEF | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | unresolved |
| tax_base_end_mu | HIGH_RELIEF | 1.653e+05 | 1.653e+05 | 1.65e+05 | 1.672e+05 | -25.87 | -402.8 | 50.23 | 0.5 | 0.125 | unresolved |
| tax_base_change_mu | HIGH_RELIEF | -1.548e+04 | -1.549e+04 | -1.579e+04 | -1.355e+04 | -25.87 | -402.8 | 50.23 | 0.5 | 0.125 | unresolved |
| receipts_over_quota_total | HIGH_RELIEF | 0.267 | 0.2645 | 0.2626 | 0.2795 | -6.249e-05 | -0.004249 | 0.001279 | 0.5 | -0.125 | unresolved |
| households_departed | HIGH_RELIEF | 534.2 | 551.4 | 428.4 | 560.5 | 20.07 | 0 | 40 | 0.75 | 0.1875 | unresolved |
| households_exited | HIGH_RELIEF | 0 | 0 | 0 | 82.33 | 0 | 0 | 0.3437 | 0.25 | 0.0625 | unresolved |
| migration_net_node_min | HIGH_RELIEF | -331.1 | -318.5 | -487.1 | -141.9 | -0.182 | -40 | 25.26 | 0.25 | -0.0625 | unresolved |
| market_active_link_share | HIGH_RELIEF | 0.9167 | 0.9167 | 0.8333 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| market_largest_component_share | HIGH_RELIEF | 0.9286 | 0.9286 | 0.8571 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| military_pay_arrears_end_tael | HIGH_RELIEF | 1.575e+04 | 1.588e+04 | 1.41e+04 | 1.751e+04 | 36.35 | -241.2 | 509.1 | 0.5 | 0 | unresolved |
| military_pay_arrears_max_tael | HIGH_RELIEF | 1.575e+04 | 1.588e+04 | 1.425e+04 | 1.751e+04 | 63.78 | -241.2 | 509.1 | 0.75 | 0.125 | unresolved |
| largest_band_share_max | HIGH_RELIEF | 0.404 | 0.3995 | 0.3802 | 0.4698 | -2.413e-05 | -0.01526 | 0.006249 | 0.5 | 0 | unresolved |
| largest_band_share_end | HIGH_RELIEF | 0.3344 | 0.3364 | 0.332 | 0.3464 | 0.00268 | -0.00282 | 0.006967 | 0.75 | 0.125 | unresolved |
| bands_at_end | HIGH_RELIEF | 4 | 4 | 4 | 5.25 | 0 | 0 | 0 | 0 | 0 | unresolved |
| indicators_crossed_end | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 5 | 5 | 5 | 5 | 0 | 0 | 1 | 0.25 | 0.25 | unresolved |
| peak_crossed | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 4 | 5 | 5 | 5 | 1 | 0 | 1 | 0.75 | 0.75 | unresolved |
| breakdown | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | unresolved |
| tax_base_end_mu | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 1.653e+05 | 1.682e+05 | 1.682e+05 | 1.682e+05 | 2970 | -4308 | 3331 | 0.75 | 0.5 | unresolved |
| tax_base_change_mu | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | -1.548e+04 | -1.251e+04 | -1.251e+04 | -1.251e+04 | 2970 | -4308 | 3331 | 0.75 | 0.5 | unresolved |
| receipts_over_quota_total | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 0.267 | 0.1937 | 0.1937 | 0.1937 | -0.07336 | -0.1248 | -0.06748 | 0 | -1 | down |
| households_departed | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 534.2 | 0 | 0 | 0 | -534.2 | -580.6 | -20.96 | 0 | -1 | down |
| households_exited | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 0 | 0 | 0 | 0 | 0 | -329 | 0 | 0 | -0.25 | unresolved |
| migration_net_node_min | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | -331.1 | 0 | 0 | 0 | 331.1 | 20.96 | 544.1 | 1 | 1 | up |
| market_active_link_share | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 0.9167 | 0.3333 | 0.3333 | 0.3333 | -0.5833 | -0.6667 | -0.5 | 0 | -1 | down |
| market_largest_component_share | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 0.9286 | 0.2857 | 0.2857 | 0.2857 | -0.6429 | -0.7143 | -0.5714 | 0 | -1 | down |
| military_pay_arrears_end_tael | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 1.575e+04 | 2.264e+04 | 2.264e+04 | 2.264e+04 | 6887 | 3289 | 1.091e+04 | 1 | 1 | up |
| military_pay_arrears_max_tael | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 1.575e+04 | 2.264e+04 | 2.264e+04 | 2.264e+04 | 6887 | 3289 | 1.035e+04 | 1 | 1 | up |
| largest_band_share_max | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 0.404 | 0.2583 | 0.2583 | 0.2583 | -0.1457 | -0.3829 | -0.1038 | 0 | -1 | down |
| largest_band_share_end | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 0.3344 | 0.2583 | 0.2583 | 0.2583 | -0.07606 | -0.1149 | -0.05825 | 0 | -1 | down |
| bands_at_end | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 4 | 4 | 4 | 4 | 0 | -5 | 0 | 0 | -0.25 | unresolved |
| indicators_crossed_end | JOINT_NO_DROUGHT+HIGH_RELIEF | 5 | 5 | 5 | 5 | 0 | 0 | 1 | 0.25 | 0.25 | unresolved |
| peak_crossed | JOINT_NO_DROUGHT+HIGH_RELIEF | 4 | 5 | 5 | 5 | 1 | 0 | 1 | 0.75 | 0.75 | unresolved |
| breakdown | JOINT_NO_DROUGHT+HIGH_RELIEF | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | unresolved |
| tax_base_end_mu | JOINT_NO_DROUGHT+HIGH_RELIEF | 1.653e+05 | 1.68e+05 | 1.68e+05 | 1.68e+05 | 2718 | -4560 | 3079 | 0.75 | 0.5 | unresolved |
| tax_base_change_mu | JOINT_NO_DROUGHT+HIGH_RELIEF | -1.548e+04 | -1.276e+04 | -1.276e+04 | -1.276e+04 | 2718 | -4560 | 3079 | 0.75 | 0.5 | unresolved |
| receipts_over_quota_total | JOINT_NO_DROUGHT+HIGH_RELIEF | 0.267 | 0.2104 | 0.2104 | 0.2104 | -0.05662 | -0.108 | -0.05073 | 0 | -1 | down |
| households_departed | JOINT_NO_DROUGHT+HIGH_RELIEF | 534.2 | 0 | 0 | 0 | -534.2 | -580.6 | -20.96 | 0 | -1 | down |
| households_exited | JOINT_NO_DROUGHT+HIGH_RELIEF | 0 | 0 | 0 | 0 | 0 | -329 | 0 | 0 | -0.25 | unresolved |
| migration_net_node_min | JOINT_NO_DROUGHT+HIGH_RELIEF | -331.1 | 0 | 0 | 0 | 331.1 | 20.96 | 544.1 | 1 | 1 | up |
| market_active_link_share | JOINT_NO_DROUGHT+HIGH_RELIEF | 0.9167 | 0.3333 | 0.3333 | 0.3333 | -0.5833 | -0.6667 | -0.5 | 0 | -1 | down |
| market_largest_component_share | JOINT_NO_DROUGHT+HIGH_RELIEF | 0.9286 | 0.2857 | 0.2857 | 0.2857 | -0.6429 | -0.7143 | -0.5714 | 0 | -1 | down |
| military_pay_arrears_end_tael | JOINT_NO_DROUGHT+HIGH_RELIEF | 1.575e+04 | 2.04e+04 | 2.04e+04 | 2.04e+04 | 4650 | 1052 | 8674 | 1 | 1 | up |
| military_pay_arrears_max_tael | JOINT_NO_DROUGHT+HIGH_RELIEF | 1.575e+04 | 2.04e+04 | 2.04e+04 | 2.04e+04 | 4650 | 1052 | 8116 | 1 | 1 | up |
| largest_band_share_max | JOINT_NO_DROUGHT+HIGH_RELIEF | 0.404 | 0.2584 | 0.2584 | 0.2584 | -0.1456 | -0.3828 | -0.1037 | 0 | -1 | down |
| largest_band_share_end | JOINT_NO_DROUGHT+HIGH_RELIEF | 0.3344 | 0.2584 | 0.2584 | 0.2584 | -0.076 | -0.1148 | -0.05819 | 0 | -1 | down |
| bands_at_end | JOINT_NO_DROUGHT+HIGH_RELIEF | 4 | 4 | 4 | 4 | 0 | -5 | 0 | 0 | -0.25 | unresolved |
| indicators_crossed_end | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 5 | 5 | 5 | 5.25 | 0.5 | 0 | 1 | 0.5 | 0.4375 | unresolved |
| peak_crossed | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 4 | 5 | 5 | 5 | 1 | 0 | 1 | 0.75 | 0.75 | unresolved |
| breakdown | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | unresolved |
| tax_base_end_mu | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 1.653e+05 | 1.591e+05 | 1.561e+05 | 1.606e+05 | -9294 | -1.433e+04 | -4697 | 0 | -1 | down |
| tax_base_change_mu | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | -1.548e+04 | -2.165e+04 | -2.461e+04 | -2.019e+04 | -9294 | -1.433e+04 | -4697 | 0 | -1 | down |
| receipts_over_quota_total | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 0.267 | 0.2292 | 0.2212 | 0.2409 | -0.04715 | -0.08553 | -0.001839 | 0 | -0.875 | down |
| households_departed | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 534.2 | 513.1 | 397.9 | 669.6 | 169.7 | -145.3 | 353.8 | 0.75 | 0.25 | unresolved |
| households_exited | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 0 | 71.18 | 46.51 | 142.2 | 31.01 | -1.2 | 80.36 | 0.5 | 0.3125 | unresolved |
| migration_net_node_min | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | -331.1 | -221.8 | -327.8 | -179.5 | -28.63 | -142.8 | 285.2 | 0.5 | 0.125 | unresolved |
| market_active_link_share | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 0.9167 | 0.9167 | 0.8333 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| market_largest_component_share | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 0.9286 | 0.9286 | 0.8571 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| military_pay_arrears_end_tael | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 1.575e+04 | 1.649e+04 | 1.531e+04 | 1.773e+04 | 682.9 | -2077 | 4325 | 0.75 | 0.25 | unresolved |
| military_pay_arrears_max_tael | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 1.575e+04 | 1.649e+04 | 1.531e+04 | 1.773e+04 | 682.9 | -2077 | 3767 | 0.75 | 0.25 | unresolved |
| largest_band_share_max | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 0.404 | 0.3846 | 0.3743 | 0.4553 | -0.004085 | -0.03061 | 0.007637 | 0.25 | -0.1875 | unresolved |
| largest_band_share_end | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 0.3344 | 0.3291 | 0.3172 | 0.3384 | -0.01567 | -0.02799 | 0.006797 | 0.25 | -0.25 | unresolved |
| bands_at_end | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 4 | 4 | 4 | 5.25 | 0 | 0 | 0 | 0 | 0 | unresolved |
| indicators_crossed_end | LOW_REPRESSION | 5 | 5 | 4.75 | 5 | 0 | 0 | 0 | 0 | 0 | unresolved |
| peak_crossed | LOW_REPRESSION | 4 | 5 | 4.75 | 5 | 0.5 | 0 | 1 | 0.5 | 0.5 | unresolved |
| breakdown | LOW_REPRESSION | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | unresolved |
| tax_base_end_mu | LOW_REPRESSION | 1.653e+05 | 1.646e+05 | 1.641e+05 | 1.666e+05 | -916.4 | -1367 | -592.4 | 0 | -0.375 | down |
| tax_base_change_mu | LOW_REPRESSION | -1.548e+04 | -1.619e+04 | -1.669e+04 | -1.419e+04 | -916.4 | -1367 | -592.4 | 0 | -0.375 | down |
| receipts_over_quota_total | LOW_REPRESSION | 0.267 | 0.2656 | 0.263 | 0.279 | -0.004098 | -0.006352 | 0.006883 | 0.25 | 0 | unresolved |
| households_departed | LOW_REPRESSION | 534.2 | 599.5 | 438.3 | 648.6 | 72.79 | 34.72 | 99.42 | 1 | 0.375 | up |
| households_exited | LOW_REPRESSION | 0 | 52.76 | 0 | 155.8 | 0 | -22.16 | 105.5 | 0.25 | 0.125 | unresolved |
| migration_net_node_min | LOW_REPRESSION | -331.1 | -316.1 | -508.2 | -144.9 | -38.27 | -78.41 | 34.03 | 0.25 | -0.125 | unresolved |
| market_active_link_share | LOW_REPRESSION | 0.9167 | 0.9167 | 0.8333 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| market_largest_component_share | LOW_REPRESSION | 0.9286 | 0.9286 | 0.8571 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| military_pay_arrears_end_tael | LOW_REPRESSION | 1.575e+04 | 1.536e+04 | 1.385e+04 | 1.676e+04 | -393 | -810.7 | 27.47 | 0.25 | -0.125 | unresolved |
| military_pay_arrears_max_tael | LOW_REPRESSION | 1.575e+04 | 1.536e+04 | 1.4e+04 | 1.676e+04 | -390.4 | -810.7 | 43.8 | 0.25 | -0.125 | unresolved |
| largest_band_share_max | LOW_REPRESSION | 0.404 | 0.3526 | 0.3526 | 0.3989 | -0.05138 | -0.1035 | -0.009464 | 0 | -0.625 | down |
| largest_band_share_end | LOW_REPRESSION | 0.3344 | 0.2846 | 0.2781 | 0.2932 | -0.05005 | -0.08232 | -0.02884 | 0 | -1 | down |
| bands_at_end | LOW_REPRESSION | 4 | 5 | 4.75 | 6.25 | 1 | 0 | 1 | 0.75 | 0.4375 | unresolved |
| indicators_crossed_end | NO_BAND_MERGER | 5 | 5 | 4.75 | 5 | 0 | 0 | 0 | 0 | 0 | unresolved |
| peak_crossed | NO_BAND_MERGER | 4 | 4 | 4 | 4.25 | 0 | 0 | 0 | 0 | 0 | unresolved |
| breakdown | NO_BAND_MERGER | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | unresolved |
| tax_base_end_mu | NO_BAND_MERGER | 1.653e+05 | 1.653e+05 | 1.649e+05 | 1.673e+05 | 0 | -1.655 | 0 | 0 | -0.0625 | unresolved |
| tax_base_change_mu | NO_BAND_MERGER | -1.548e+04 | -1.548e+04 | -1.582e+04 | -1.341e+04 | 0 | -1.655 | 0 | 0 | -0.0625 | unresolved |
| receipts_over_quota_total | NO_BAND_MERGER | 0.267 | 0.2671 | 0.2655 | 0.28 | 0 | 0 | 6.145e-05 | 0.25 | 0.0625 | unresolved |
| households_departed | NO_BAND_MERGER | 534.2 | 534.2 | 392.7 | 559.1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| households_exited | NO_BAND_MERGER | 0 | 0 | 0 | 82.25 | 0 | 0 | 0 | 0 | 0 | unresolved |
| migration_net_node_min | NO_BAND_MERGER | -331.1 | -331.1 | -487.1 | -150.8 | 0 | 0 | 0 | 0 | 0 | unresolved |
| market_active_link_share | NO_BAND_MERGER | 0.9167 | 0.9167 | 0.8333 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| market_largest_component_share | NO_BAND_MERGER | 0.9286 | 0.9286 | 0.8571 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| military_pay_arrears_end_tael | NO_BAND_MERGER | 1.575e+04 | 1.575e+04 | 1.429e+04 | 1.711e+04 | 0 | 0 | 8.61 | 0.25 | 0.0625 | unresolved |
| military_pay_arrears_max_tael | NO_BAND_MERGER | 1.575e+04 | 1.575e+04 | 1.443e+04 | 1.711e+04 | 0 | 0 | 8.61 | 0.25 | 0.0625 | unresolved |
| largest_band_share_max | NO_BAND_MERGER | 0.404 | 0.404 | 0.3917 | 0.4299 | 0 | -0.1409 | 0 | 0 | -0.0625 | unresolved |
| largest_band_share_end | NO_BAND_MERGER | 0.3344 | 0.3358 | 0.3283 | 0.3479 | 0 | 0 | 0.002877 | 0.25 | 0.0625 | unresolved |
| bands_at_end | NO_BAND_MERGER | 4 | 4 | 4 | 5.25 | 0 | 0 | 0 | 0 | 0 | unresolved |
| indicators_crossed_end | NO_DROUGHT | 5 | 5 | 5 | 5 | 0 | 0 | 1 | 0.25 | 0.25 | unresolved |
| peak_crossed | NO_DROUGHT | 4 | 5 | 5 | 5 | 1 | 0 | 1 | 0.75 | 0.75 | unresolved |
| breakdown | NO_DROUGHT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | unresolved |
| tax_base_end_mu | NO_DROUGHT | 1.653e+05 | 1.68e+05 | 1.68e+05 | 1.68e+05 | 2718 | -4560 | 3079 | 0.75 | 0.5 | unresolved |
| tax_base_change_mu | NO_DROUGHT | -1.548e+04 | -1.276e+04 | -1.276e+04 | -1.276e+04 | 2718 | -4560 | 3079 | 0.75 | 0.5 | unresolved |
| receipts_over_quota_total | NO_DROUGHT | 0.267 | 0.2104 | 0.2104 | 0.2104 | -0.05662 | -0.108 | -0.05073 | 0 | -1 | down |
| households_departed | NO_DROUGHT | 534.2 | 0 | 0 | 0 | -534.2 | -580.6 | -20.96 | 0 | -1 | down |
| households_exited | NO_DROUGHT | 0 | 0 | 0 | 0 | 0 | -329 | 0 | 0 | -0.25 | unresolved |
| migration_net_node_min | NO_DROUGHT | -331.1 | 0 | 0 | 0 | 331.1 | 20.96 | 544.1 | 1 | 1 | up |
| market_active_link_share | NO_DROUGHT | 0.9167 | 0.3333 | 0.3333 | 0.3333 | -0.5833 | -0.6667 | -0.5 | 0 | -1 | down |
| market_largest_component_share | NO_DROUGHT | 0.9286 | 0.2857 | 0.2857 | 0.2857 | -0.6429 | -0.7143 | -0.5714 | 0 | -1 | down |
| military_pay_arrears_end_tael | NO_DROUGHT | 1.575e+04 | 2.04e+04 | 2.04e+04 | 2.04e+04 | 4650 | 1052 | 8674 | 1 | 1 | up |
| military_pay_arrears_max_tael | NO_DROUGHT | 1.575e+04 | 2.04e+04 | 2.04e+04 | 2.04e+04 | 4650 | 1052 | 8116 | 1 | 1 | up |
| largest_band_share_max | NO_DROUGHT | 0.404 | 0.2584 | 0.2584 | 0.2584 | -0.1456 | -0.3828 | -0.1037 | 0 | -1 | down |
| largest_band_share_end | NO_DROUGHT | 0.3344 | 0.2584 | 0.2584 | 0.2584 | -0.076 | -0.1148 | -0.05819 | 0 | -1 | down |
| bands_at_end | NO_DROUGHT | 4 | 4 | 4 | 4 | 0 | -5 | 0 | 0 | -0.25 | unresolved |
| indicators_crossed_end | NO_ELITE_CREDIT | 5 | 4.5 | 4 | 5 | 0 | -1 | 0 | 0 | -0.25 | unresolved |
| peak_crossed | NO_ELITE_CREDIT | 4 | 4.5 | 4 | 5 | 0 | 0 | 1 | 0.25 | 0.25 | unresolved |
| breakdown | NO_ELITE_CREDIT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | unresolved |
| tax_base_end_mu | NO_ELITE_CREDIT | 1.653e+05 | 1.568e+05 | 1.556e+05 | 1.583e+05 | -9540 | -1.252e+04 | -7850 | 0 | -1 | down |
| tax_base_change_mu | NO_ELITE_CREDIT | -1.548e+04 | -2.396e+04 | -2.515e+04 | -2.242e+04 | -9540 | -1.252e+04 | -7850 | 0 | -1 | down |
| receipts_over_quota_total | NO_ELITE_CREDIT | 0.267 | 0.2862 | 0.2718 | 0.3057 | 0.006921 | 0.005341 | 0.03209 | 1 | 0.375 | up |
| households_departed | NO_ELITE_CREDIT | 534.2 | 630.7 | 561.6 | 670.2 | 121.2 | 91.79 | 400.5 | 1 | 0.625 | up |
| households_exited | NO_ELITE_CREDIT | 0 | 0 | 0 | 81.06 | 0 | -4.739 | 0 | 0 | -0.0625 | unresolved |
| migration_net_node_min | NO_ELITE_CREDIT | -331.1 | -382.7 | -452.5 | -299 | 14.47 | -400.5 | 124 | 0.5 | -0.125 | unresolved |
| market_active_link_share | NO_ELITE_CREDIT | 0.9167 | 0.9167 | 0.8333 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| market_largest_component_share | NO_ELITE_CREDIT | 0.9286 | 0.9286 | 0.8571 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| military_pay_arrears_end_tael | NO_ELITE_CREDIT | 1.575e+04 | 1.505e+04 | 1.396e+04 | 1.576e+04 | -844.2 | -1984 | -263.7 | 0 | -0.25 | down |
| military_pay_arrears_max_tael | NO_ELITE_CREDIT | 1.575e+04 | 1.505e+04 | 1.41e+04 | 1.576e+04 | -834.5 | -1984 | -263.7 | 0 | -0.25 | down |
| largest_band_share_max | NO_ELITE_CREDIT | 0.404 | 0.4 | 0.3857 | 0.4905 | 0.0003199 | -0.008095 | 0.1011 | 0.75 | 0.125 | unresolved |
| largest_band_share_end | NO_ELITE_CREDIT | 0.3344 | 0.3225 | 0.3033 | 0.3409 | -0.006923 | -0.05354 | -0.004019 | 0 | -0.375 | down |
| bands_at_end | NO_ELITE_CREDIT | 4 | 4 | 4 | 5.25 | 0 | 0 | 0 | 0 | 0 | unresolved |
| indicators_crossed_end | NO_EXTRACTION_ESCALATION | 5 | 5 | 5 | 5.25 | 0.5 | 0 | 1 | 0.5 | 0.4375 | unresolved |
| peak_crossed | NO_EXTRACTION_ESCALATION | 4 | 5 | 5 | 5 | 1 | 0 | 1 | 0.75 | 0.75 | unresolved |
| breakdown | NO_EXTRACTION_ESCALATION | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | unresolved |
| tax_base_end_mu | NO_EXTRACTION_ESCALATION | 1.653e+05 | 1.662e+05 | 1.64e+05 | 1.678e+05 | -2417 | -5240 | 4228 | 0.25 | 0 | unresolved |
| tax_base_change_mu | NO_EXTRACTION_ESCALATION | -1.548e+04 | -1.453e+04 | -1.676e+04 | -1.298e+04 | -2417 | -5240 | 4228 | 0.25 | 0 | unresolved |
| receipts_over_quota_total | NO_EXTRACTION_ESCALATION | 0.267 | 0.2163 | 0.2064 | 0.2306 | -0.06172 | -0.09624 | -0.01114 | 0 | -1 | down |
| households_departed | NO_EXTRACTION_ESCALATION | 534.2 | 460.7 | 357.1 | 609.2 | 136.2 | -273.1 | 352.7 | 0.75 | 0 | unresolved |
| households_exited | NO_EXTRACTION_ESCALATION | 0 | 125.4 | 46.51 | 227.2 | 37.57 | 0 | 188.9 | 0.75 | 0.4375 | unresolved |
| migration_net_node_min | NO_EXTRACTION_ESCALATION | -331.1 | -229.9 | -365 | -187.8 | -79.27 | -179.2 | 273.1 | 0.5 | 0 | unresolved |
| market_active_link_share | NO_EXTRACTION_ESCALATION | 0.9167 | 0.9167 | 0.8333 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| market_largest_component_share | NO_EXTRACTION_ESCALATION | 0.9286 | 0.9286 | 0.8571 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| military_pay_arrears_end_tael | NO_EXTRACTION_ESCALATION | 1.575e+04 | 1.724e+04 | 1.649e+04 | 1.844e+04 | 1556 | -586 | 5629 | 0.75 | 0.375 | unresolved |
| military_pay_arrears_max_tael | NO_EXTRACTION_ESCALATION | 1.575e+04 | 1.724e+04 | 1.649e+04 | 1.844e+04 | 1556 | -586 | 5071 | 0.75 | 0.375 | unresolved |
| largest_band_share_max | NO_EXTRACTION_ESCALATION | 0.404 | 0.3865 | 0.3727 | 0.4595 | -0.001321 | -0.03232 | 0.00621 | 0.25 | -0.1875 | unresolved |
| largest_band_share_end | NO_EXTRACTION_ESCALATION | 0.3344 | 0.3228 | 0.3164 | 0.3296 | -0.01515 | -0.02707 | -0.007907 | 0 | -0.375 | down |
| bands_at_end | NO_EXTRACTION_ESCALATION | 4 | 4 | 4 | 5.25 | 0 | 0 | 0 | 0 | 0 | unresolved |
| indicators_crossed_end | NO_TRADE_DISRUPTION | 5 | 5 | 4.75 | 5.25 | 0 | 0 | 1 | 0.25 | 0.1875 | unresolved |
| peak_crossed | NO_TRADE_DISRUPTION | 4 | 5 | 4.75 | 5 | 0.5 | 0 | 1 | 0.5 | 0.5 | unresolved |
| breakdown | NO_TRADE_DISRUPTION | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | unresolved |
| tax_base_end_mu | NO_TRADE_DISRUPTION | 1.653e+05 | 1.675e+05 | 1.663e+05 | 1.7e+05 | 1278 | 523.8 | 3799 | 1 | 0.625 | up |
| tax_base_change_mu | NO_TRADE_DISRUPTION | -1.548e+04 | -1.324e+04 | -1.448e+04 | -1.078e+04 | 1278 | 523.8 | 3799 | 1 | 0.625 | up |
| receipts_over_quota_total | NO_TRADE_DISRUPTION | 0.267 | 0.2406 | 0.2308 | 0.2433 | -0.04222 | -0.06978 | -0.02534 | 0 | -1 | down |
| households_departed | NO_TRADE_DISRUPTION | 534.2 | 459.9 | 297.2 | 525.1 | -24.71 | -184.2 | 13.41 | 0.25 | -0.375 | unresolved |
| households_exited | NO_TRADE_DISRUPTION | 0 | 0 | 0 | 86.3 | 0 | 0 | 16.22 | 0.25 | 0.0625 | unresolved |
| migration_net_node_min | NO_TRADE_DISRUPTION | -331.1 | -290.5 | -417.6 | -138.6 | 15.17 | -13.47 | 147.7 | 0.75 | 0.25 | unresolved |
| market_active_link_share | NO_TRADE_DISRUPTION | 0.9167 | 1 | 1 | 1 | 0.08333 | 0 | 0.1667 | 0.5 | 0.5 | unresolved |
| market_largest_component_share | NO_TRADE_DISRUPTION | 0.9286 | 1 | 1 | 1 | 0.07143 | 0 | 0.1429 | 0.5 | 0.5 | unresolved |
| military_pay_arrears_end_tael | NO_TRADE_DISRUPTION | 1.575e+04 | 2.066e+04 | 1.971e+04 | 2.161e+04 | 4918 | 1966 | 8270 | 1 | 0.875 | up |
| military_pay_arrears_max_tael | NO_TRADE_DISRUPTION | 1.575e+04 | 2.068e+04 | 1.971e+04 | 2.165e+04 | 4918 | 2016 | 7717 | 1 | 0.875 | up |
| largest_band_share_max | NO_TRADE_DISRUPTION | 0.404 | 0.3979 | 0.3878 | 0.46 | -0.001007 | -0.01018 | 0.0004466 | 0.25 | -0.1875 | unresolved |
| largest_band_share_end | NO_TRADE_DISRUPTION | 0.3344 | 0.3441 | 0.3382 | 0.3532 | 0.006302 | 0.001261 | 0.01681 | 1 | 0.375 | up |
| bands_at_end | NO_TRADE_DISRUPTION | 4 | 4 | 4 | 5.5 | 0 | 0 | 1 | 0.25 | 0.0625 | unresolved |
| indicators_crossed_end | OPEN_MIGRATION_EXIT | 5 | 6 | 6 | 6 | 1 | 1 | 2 | 1 | 1 | up |
| peak_crossed | OPEN_MIGRATION_EXIT | 4 | 6 | 6 | 6 | 2 | 1 | 2 | 1 | 1 | up |
| breakdown | OPEN_MIGRATION_EXIT | 0 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | up |
| tax_base_end_mu | OPEN_MIGRATION_EXIT | 1.653e+05 | 2707 | 2246 | 3073 | -1.626e+05 | -1.708e+05 | -1.616e+05 | 0 | -1 | down |
| tax_base_change_mu | OPEN_MIGRATION_EXIT | -1.548e+04 | -1.78e+05 | -1.785e+05 | -1.777e+05 | -1.626e+05 | -1.708e+05 | -1.616e+05 | 0 | -1 | down |
| receipts_over_quota_total | OPEN_MIGRATION_EXIT | 0.267 | 0.3537 | 0.3302 | 0.3757 | 0.07555 | 0.01872 | 0.1251 | 1 | 0.875 | up |
| households_departed | OPEN_MIGRATION_EXIT | 534.2 | 7.35e+04 | 7.277e+04 | 7.738e+04 | 7.295e+04 | 7.154e+04 | 8.751e+04 | 1 | 1 | up |
| households_exited | OPEN_MIGRATION_EXIT | 0 | 8679 | 7106 | 9321 | 8515 | 3896 | 9733 | 1 | 1 | up |
| migration_net_node_min | OPEN_MIGRATION_EXIT | -331.1 | -3949 | -3953 | -3886 | -3586 | -3751 | -3410 | 0 | -1 | down |
| market_active_link_share | OPEN_MIGRATION_EXIT | 0.9167 | 1 | 1 | 1 | 0.08333 | 0 | 0.1667 | 0.5 | 0.5 | unresolved |
| market_largest_component_share | OPEN_MIGRATION_EXIT | 0.9286 | 1 | 1 | 1 | 0.07143 | 0 | 0.1429 | 0.5 | 0.5 | unresolved |
| military_pay_arrears_end_tael | OPEN_MIGRATION_EXIT | 1.575e+04 | 2.574e+04 | 2.442e+04 | 2.767e+04 | 1.057e+04 | 7290 | 1.442e+04 | 1 | 1 | up |
| military_pay_arrears_max_tael | OPEN_MIGRATION_EXIT | 1.575e+04 | 2.574e+04 | 2.442e+04 | 2.767e+04 | 1.029e+04 | 7290 | 1.442e+04 | 1 | 1 | up |
| largest_band_share_max | OPEN_MIGRATION_EXIT | 0.404 | 0.4444 | 0.3752 | 0.5078 | -0.04168 | -0.1119 | 0.1385 | 0.25 | -0.125 | unresolved |
| largest_band_share_end | OPEN_MIGRATION_EXIT | 0.3344 | 0.3644 | 0.3149 | 0.4034 | 0.01315 | -0.08932 | 0.1204 | 0.5 | 0.25 | unresolved |
| bands_at_end | OPEN_MIGRATION_EXIT | 4 | 8 | 6.75 | 9.25 | 4 | -3 | 6 | 0.75 | 0.6875 | unresolved |

## Collapse probability

A run is *in breakdown* when at least 6 of the eight declared governance lines are crossed at a sampled tick (every 24 ticks). The share carries a Wilson interval because twelve runs is not a probability until its uncertainty is stated.

| label | runs | runs_in_breakdown | collapse_probability | wilson_low | wilson_high |
| --- | --- | --- | --- | --- | --- |
| BASELINE | 4 | 0 | 0 | 0 | 0.4899 |
| FULL_MILITARY_PAY | 4 | 0 | 0 | 0 | 0.4899 |
| HIGH_RELIEF | 4 | 0 | 0 | 0 | 0.4899 |
| JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 4 | 0 | 0 | 0 | 0.4899 |
| JOINT_NO_DROUGHT+HIGH_RELIEF | 4 | 0 | 0 | 0 | 0.4899 |
| JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 4 | 0 | 0 | 0 | 0.4899 |
| LOW_REPRESSION | 4 | 0 | 0 | 0 | 0.4899 |
| NO_BAND_MERGER | 4 | 0 | 0 | 0 | 0.4899 |
| NO_DROUGHT | 4 | 0 | 0 | 0 | 0.4899 |
| NO_ELITE_CREDIT | 4 | 0 | 0 | 0 | 0.4899 |
| NO_EXTRACTION_ESCALATION | 4 | 0 | 0 | 0 | 0.4899 |
| NO_TRADE_DISRUPTION | 4 | 0 | 0 | 0 | 0.4899 |
| OPEN_MIGRATION_EXIT | 4 | 4 | 1 | 0.5101 | 1 |

### When each arm broke down, among the runs that did

A run that never reaches the line carries a sentinel of -1, kept out of every paired
statistic on purpose: a median of -1 is not a time, and subtracting it from a real tick
would make a run that broke down look like one that held out longer. Timing is answered
here instead, conditioned on the runs that reached the line.

| label | runs | runs_reaching_the_line | runs_never_reaching | median_tick | q1_tick | q3_tick |
| --- | --- | --- | --- | --- | --- | --- |
| BASELINE | 4 | 0 | 4 | None | None | None |
| FULL_MILITARY_PAY | 4 | 0 | 4 | None | None | None |
| HIGH_RELIEF | 4 | 0 | 4 | None | None | None |
| JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 4 | 0 | 4 | None | None | None |
| JOINT_NO_DROUGHT+HIGH_RELIEF | 4 | 0 | 4 | None | None | None |
| JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 4 | 0 | 4 | None | None | None |
| LOW_REPRESSION | 4 | 0 | 4 | None | None | None |
| NO_BAND_MERGER | 4 | 0 | 4 | None | None | None |
| NO_DROUGHT | 4 | 0 | 4 | None | None | None |
| NO_ELITE_CREDIT | 4 | 0 | 4 | None | None | None |
| NO_EXTRACTION_ESCALATION | 4 | 0 | 4 | None | None | None |
| NO_TRADE_DISRUPTION | 4 | 0 | 4 | None | None | None |
| OPEN_MIGRATION_EXIT | 4 | 4 | 0 | 48 | 48 | 48 |

### Did each arm actually remove its mechanism?

Each ablatable mechanism leaves a counter in the log. An arm whose counter still moves
as often as the baseline's removed nothing; `baseline_replicates_active` says how many
baseline runs had something to remove at all, so a structural no-op is visible rather
than read as a null result.

| metric | arm | baseline_replicates_active | baseline_median | arm_median | median_difference | direction |
| --- | --- | --- | --- | --- | --- | --- |
| band_merges | NO_DROUGHT | 0 | 0 | 0 | 0 | removed |
| band_merges | NO_EXTRACTION_ESCALATION | 0 | 0 | 0 | 0 | removed |
| band_merges | FULL_MILITARY_PAY | 0 | 0 | 0 | 0 | removed |
| band_merges | HIGH_RELIEF | 0 | 0 | 0 | 0 | removed |
| band_merges | NO_ELITE_CREDIT | 0 | 0 | 0 | 0 | removed |
| band_merges | NO_TRADE_DISRUPTION | 0 | 0 | 0 | 0 | removed |
| band_merges | NO_BAND_MERGER | 0 | 0 | 0 | 0 | removed |
| band_merges | LOW_REPRESSION | 0 | 0 | 0 | 0 | removed |
| band_merges | OPEN_MIGRATION_EXIT | 0 | 0 | 0 | 0 | removed |
| band_merges | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 0 | 0 | 0 | 0 | removed |
| band_merges | JOINT_NO_DROUGHT+HIGH_RELIEF | 0 | 0 | 0 | 0 | removed |
| band_merges | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 0 | 0 | 0 | 0 | removed |
| elite_loans | NO_DROUGHT | 4 | 74 | 110 | 36 | still active |
| elite_loans | NO_EXTRACTION_ESCALATION | 4 | 74 | 76.5 | 2 | still active |
| elite_loans | FULL_MILITARY_PAY | 4 | 74 | 74 | 3 | still active |
| elite_loans | HIGH_RELIEF | 4 | 74 | 68.5 | 0.5 | still active |
| elite_loans | NO_ELITE_CREDIT | 4 | 74 | 0 | -74 | removed |
| elite_loans | NO_TRADE_DISRUPTION | 4 | 74 | 77 | 6 | still active |
| elite_loans | NO_BAND_MERGER | 4 | 74 | 67.5 | 0 | still active |
| elite_loans | LOW_REPRESSION | 4 | 74 | 75.5 | 1 | still active |
| elite_loans | OPEN_MIGRATION_EXIT | 4 | 74 | 115 | 43 | still active |
| elite_loans | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 4 | 74 | 102 | 28 | still active |
| elite_loans | JOINT_NO_DROUGHT+HIGH_RELIEF | 4 | 74 | 110 | 36 | still active |
| elite_loans | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 4 | 74 | 0 | -74 | removed |
| suppressions | NO_DROUGHT | 4 | 936.5 | 938 | 1.5 | still active |
| suppressions | NO_EXTRACTION_ESCALATION | 4 | 936.5 | 935.5 | 0 | still active |
| suppressions | FULL_MILITARY_PAY | 4 | 936.5 | 907 | -29.5 | still active |
| suppressions | HIGH_RELIEF | 4 | 936.5 | 936 | -0.5 | still active |
| suppressions | NO_ELITE_CREDIT | 4 | 936.5 | 931 | -5.5 | still active |
| suppressions | NO_TRADE_DISRUPTION | 4 | 936.5 | 940.5 | 4 | still active |
| suppressions | NO_BAND_MERGER | 4 | 936.5 | 936.5 | 0 | still active |
| suppressions | LOW_REPRESSION | 4 | 936.5 | 0 | -936.5 | removed |
| suppressions | OPEN_MIGRATION_EXIT | 4 | 936.5 | 1038 | 127 | still active |
| suppressions | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 4 | 936.5 | 920 | -16.5 | still active |
| suppressions | JOINT_NO_DROUGHT+HIGH_RELIEF | 4 | 936.5 | 938 | 1.5 | still active |
| suppressions | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 4 | 936.5 | 939 | 2.5 | still active |
| trade_shipments | NO_DROUGHT | 4 | 318.5 | 280 | -38.5 | still active |
| trade_shipments | NO_EXTRACTION_ESCALATION | 4 | 318.5 | 354.5 | 51.5 | still active |
| trade_shipments | FULL_MILITARY_PAY | 4 | 318.5 | 341 | -10.5 | still active |
| trade_shipments | HIGH_RELIEF | 4 | 318.5 | 327 | 0.5 | still active |
| trade_shipments | NO_ELITE_CREDIT | 4 | 318.5 | 333 | 4.5 | still active |
| trade_shipments | NO_TRADE_DISRUPTION | 4 | 318.5 | 249.5 | -68.5 | still active |
| trade_shipments | NO_BAND_MERGER | 4 | 318.5 | 318.5 | 0 | still active |
| trade_shipments | LOW_REPRESSION | 4 | 318.5 | 261.5 | -28 | still active |
| trade_shipments | OPEN_MIGRATION_EXIT | 4 | 318.5 | 405.5 | 86 | still active |
| trade_shipments | JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 4 | 318.5 | 263 | -55.5 | still active |
| trade_shipments | JOINT_NO_DROUGHT+HIGH_RELIEF | 4 | 318.5 | 280 | -38.5 | still active |
| trade_shipments | JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 4 | 318.5 | 368 | 65 | still active |

### How many lines each arm actually crosses

| label | indicators_crossed_end | runs | share |
| --- | --- | --- | --- |
| BASELINE | 4 | 1 | 0.25 |
| BASELINE | 5 | 3 | 0.75 |
| FULL_MILITARY_PAY | 4 | 3 | 0.75 |
| FULL_MILITARY_PAY | 5 | 1 | 0.25 |
| HIGH_RELIEF | 4 | 1 | 0.25 |
| HIGH_RELIEF | 5 | 3 | 0.75 |
| JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 5 | 4 | 1 |
| JOINT_NO_DROUGHT+HIGH_RELIEF | 5 | 4 | 1 |
| JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 5 | 3 | 0.75 |
| JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 6 | 1 | 0.25 |
| LOW_REPRESSION | 4 | 1 | 0.25 |
| LOW_REPRESSION | 5 | 3 | 0.75 |
| NO_BAND_MERGER | 4 | 1 | 0.25 |
| NO_BAND_MERGER | 5 | 3 | 0.75 |
| NO_DROUGHT | 5 | 4 | 1 |
| NO_ELITE_CREDIT | 4 | 2 | 0.5 |
| NO_ELITE_CREDIT | 5 | 2 | 0.5 |
| NO_EXTRACTION_ESCALATION | 5 | 3 | 0.75 |
| NO_EXTRACTION_ESCALATION | 6 | 1 | 0.25 |
| NO_TRADE_DISRUPTION | 4 | 1 | 0.25 |
| NO_TRADE_DISRUPTION | 5 | 2 | 0.5 |
| NO_TRADE_DISRUPTION | 6 | 1 | 0.25 |
| OPEN_MIGRATION_EXIT | 6 | 4 | 1 |

### Is the result the line or the model?

The breakdown line is a declared reading rule, so the share is recomputed at every
candidate line (3, 4, 5, 6, 7, 8). If the declared line sits where
nothing changes any more, the table says so.

| label | line | runs_in_breakdown | collapse_probability | wilson_low | wilson_high |
| --- | --- | --- | --- | --- | --- |
| BASELINE | 3 | 4 | 1 | 0.5101 | 1 |
| BASELINE | 4 | 4 | 1 | 0.5101 | 1 |
| BASELINE | 5 | 1 | 0.25 | 0.04559 | 0.6994 |
| BASELINE | 6 | 0 | 0 | 0 | 0.4899 |
| BASELINE | 7 | 0 | 0 | 0 | 0.4899 |
| BASELINE | 8 | 0 | 0 | 0 | 0.4899 |
| FULL_MILITARY_PAY | 3 | 4 | 1 | 0.5101 | 1 |
| FULL_MILITARY_PAY | 4 | 4 | 1 | 0.5101 | 1 |
| FULL_MILITARY_PAY | 5 | 1 | 0.25 | 0.04559 | 0.6994 |
| FULL_MILITARY_PAY | 6 | 0 | 0 | 0 | 0.4899 |
| FULL_MILITARY_PAY | 7 | 0 | 0 | 0 | 0.4899 |
| FULL_MILITARY_PAY | 8 | 0 | 0 | 0 | 0.4899 |
| HIGH_RELIEF | 3 | 4 | 1 | 0.5101 | 1 |
| HIGH_RELIEF | 4 | 4 | 1 | 0.5101 | 1 |
| HIGH_RELIEF | 5 | 2 | 0.5 | 0.15 | 0.85 |
| HIGH_RELIEF | 6 | 0 | 0 | 0 | 0.4899 |
| HIGH_RELIEF | 7 | 0 | 0 | 0 | 0.4899 |
| HIGH_RELIEF | 8 | 0 | 0 | 0 | 0.4899 |
| JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 3 | 4 | 1 | 0.5101 | 1 |
| JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 4 | 4 | 1 | 0.5101 | 1 |
| JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 5 | 4 | 1 | 0.5101 | 1 |
| JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 6 | 0 | 0 | 0 | 0.4899 |
| JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 7 | 0 | 0 | 0 | 0.4899 |
| JOINT_NO_DROUGHT+FULL_MILITARY_PAY | 8 | 0 | 0 | 0 | 0.4899 |
| JOINT_NO_DROUGHT+HIGH_RELIEF | 3 | 4 | 1 | 0.5101 | 1 |
| JOINT_NO_DROUGHT+HIGH_RELIEF | 4 | 4 | 1 | 0.5101 | 1 |
| JOINT_NO_DROUGHT+HIGH_RELIEF | 5 | 4 | 1 | 0.5101 | 1 |
| JOINT_NO_DROUGHT+HIGH_RELIEF | 6 | 0 | 0 | 0 | 0.4899 |
| JOINT_NO_DROUGHT+HIGH_RELIEF | 7 | 0 | 0 | 0 | 0.4899 |
| JOINT_NO_DROUGHT+HIGH_RELIEF | 8 | 0 | 0 | 0 | 0.4899 |
| JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 3 | 4 | 1 | 0.5101 | 1 |
| JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 4 | 4 | 1 | 0.5101 | 1 |
| JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 5 | 4 | 1 | 0.5101 | 1 |
| JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 6 | 0 | 0 | 0 | 0.4899 |
| JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 7 | 0 | 0 | 0 | 0.4899 |
| JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT | 8 | 0 | 0 | 0 | 0.4899 |
| LOW_REPRESSION | 3 | 4 | 1 | 0.5101 | 1 |
| LOW_REPRESSION | 4 | 4 | 1 | 0.5101 | 1 |
| LOW_REPRESSION | 5 | 3 | 0.75 | 0.3006 | 0.9544 |
| LOW_REPRESSION | 6 | 0 | 0 | 0 | 0.4899 |
| LOW_REPRESSION | 7 | 0 | 0 | 0 | 0.4899 |
| LOW_REPRESSION | 8 | 0 | 0 | 0 | 0.4899 |
| NO_BAND_MERGER | 3 | 4 | 1 | 0.5101 | 1 |
| NO_BAND_MERGER | 4 | 4 | 1 | 0.5101 | 1 |
| NO_BAND_MERGER | 5 | 1 | 0.25 | 0.04559 | 0.6994 |
| NO_BAND_MERGER | 6 | 0 | 0 | 0 | 0.4899 |
| NO_BAND_MERGER | 7 | 0 | 0 | 0 | 0.4899 |
| NO_BAND_MERGER | 8 | 0 | 0 | 0 | 0.4899 |
| NO_DROUGHT | 3 | 4 | 1 | 0.5101 | 1 |
| NO_DROUGHT | 4 | 4 | 1 | 0.5101 | 1 |
| NO_DROUGHT | 5 | 4 | 1 | 0.5101 | 1 |
| NO_DROUGHT | 6 | 0 | 0 | 0 | 0.4899 |
| NO_DROUGHT | 7 | 0 | 0 | 0 | 0.4899 |
| NO_DROUGHT | 8 | 0 | 0 | 0 | 0.4899 |
| NO_ELITE_CREDIT | 3 | 4 | 1 | 0.5101 | 1 |
| NO_ELITE_CREDIT | 4 | 4 | 1 | 0.5101 | 1 |
| NO_ELITE_CREDIT | 5 | 2 | 0.5 | 0.15 | 0.85 |
| NO_ELITE_CREDIT | 6 | 0 | 0 | 0 | 0.4899 |
| NO_ELITE_CREDIT | 7 | 0 | 0 | 0 | 0.4899 |
| NO_ELITE_CREDIT | 8 | 0 | 0 | 0 | 0.4899 |
| NO_EXTRACTION_ESCALATION | 3 | 4 | 1 | 0.5101 | 1 |
| NO_EXTRACTION_ESCALATION | 4 | 4 | 1 | 0.5101 | 1 |
| NO_EXTRACTION_ESCALATION | 5 | 4 | 1 | 0.5101 | 1 |
| NO_EXTRACTION_ESCALATION | 6 | 0 | 0 | 0 | 0.4899 |
| NO_EXTRACTION_ESCALATION | 7 | 0 | 0 | 0 | 0.4899 |
| NO_EXTRACTION_ESCALATION | 8 | 0 | 0 | 0 | 0.4899 |
| NO_TRADE_DISRUPTION | 3 | 4 | 1 | 0.5101 | 1 |
| NO_TRADE_DISRUPTION | 4 | 4 | 1 | 0.5101 | 1 |
| NO_TRADE_DISRUPTION | 5 | 3 | 0.75 | 0.3006 | 0.9544 |
| NO_TRADE_DISRUPTION | 6 | 0 | 0 | 0 | 0.4899 |
| NO_TRADE_DISRUPTION | 7 | 0 | 0 | 0 | 0.4899 |
| NO_TRADE_DISRUPTION | 8 | 0 | 0 | 0 | 0.4899 |
| OPEN_MIGRATION_EXIT | 3 | 4 | 1 | 0.5101 | 1 |
| OPEN_MIGRATION_EXIT | 4 | 4 | 1 | 0.5101 | 1 |
| OPEN_MIGRATION_EXIT | 5 | 4 | 1 | 0.5101 | 1 |
| OPEN_MIGRATION_EXIT | 6 | 4 | 1 | 0.5101 | 1 |
| OPEN_MIGRATION_EXIT | 7 | 0 | 0 | 0 | 0.4899 |
| OPEN_MIGRATION_EXIT | 8 | 0 | 0 | 0 | 0.4899 |
