# Parameter uncertainty

One row per parameter card. `central` is the value the model currently uses; `range` is
what the evidence would allow instead, and is empty where nobody has established one.
Grade `S` means the value is a model assumption and nothing more. Grade `D` means the
evidence is weak but exists. Both are sensitivity candidates by the project's rule.

- cards: 111
- with a stated range: 25
- grade S: 101
- grade D: 0
- sensitivity candidates: 101
- cards whose sources are all identity-only: 10

## Cards

| parameter | set | grade | class | central | unit | range | range basis | sensitivity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| arms_per_asset_valuation | BandParameters | S | exploratory | 0.02 | arms per tael of seized property | — | — | low |
| arms_per_member_for_full_capability | BandParameters | S | exploratory | 0.05 | arms per member | — | — | medium |
| cohesion_decay_per_month | BandParameters | S | exploratory | 0.02 | index points per month (0-1) | — | — | medium |
| cohesion_gain_per_month | BandParameters | S | exploratory | 0.04 | index points per month (0-1) | — | — | medium |
| dissolve_troops_below | BandParameters | S | exploratory | 40 | members | — | — | medium |
| food_shi_per_member_month | BandParameters | S | theoretically-assumed | 0.3 | shi per member per month | 0.2-0.5 | above the civilian floor with a declared activity margin | high |
| formation_recruitment_months | BandParameters | S | exploratory | 6 | months | — | — | medium |
| formation_unmet_ratio | BandParameters | S | theoretically-assumed | 0.15 | ratio (0-1) | — | — | high |
| merge_cohesion_above | BandParameters | S | exploratory | 0.6 | index (0-1) | — | — | medium |
| minimum_formation_troops | BandParameters | S | theoretically-assumed | 40 | members | — | — | high |
| mobility_decay_per_month | BandParameters | S | exploratory | 0.02 | index points per month (0-1) | — | — | low |
| mobility_gain_from_move | BandParameters | S | exploratory | 0.05 | index points per move (0-1) | — | — | low |
| movement_avoidance_ratio | BandParameters | S | exploratory | 0.05 | share of own size (0-1) | — | — | high |
| movement_mobility_floor | BandParameters | S | exploratory | 0.3 | index (0-1) | — | — | medium |
| network_gain_per_month | BandParameters | S | exploratory | 0.03 | index points per month (0-1) | — | — | medium |
| network_loss_from_raid_per_month | BandParameters | S | exploratory | 0.1 | index points per month (0-1) | — | — | medium |
| raid_asset_share_per_month | BandParameters | S | exploratory | 0.05 | share of assets per month (0-1) | — | — | medium |
| raid_extraction_multiple | BandParameters | S | exploratory | 1.5 | multiple of the band's own monthly need | — | — | high |
| recruitment_rate_of_eligible_adults | BandParameters | S | exploratory | 0.01 | adults | — | — | high |
| split_cohesion_below | BandParameters | S | exploratory | 0.45 | index (0-1) | — | — | medium |
| split_troops_threshold | BandParameters | S | exploratory | 400 | members | — | — | medium |
| land_per_adult_capacity_mu | CropParameters | C | theoretically-assumed | 12 | mu per adult | 5.0-20.0 | family-farm labour ratios reported for north China | medium |
| yield_loss_scale | CropParameters | S | exploratory | 0.5 | multiple of the declared anomaly | 0.5-2.0 | declared prior width around the current value | high |
| yield_shi_per_mu | CropParameters | C | theoretically-assumed | loess-dryland=0.9; north-china-plain=1.1 | shi per mu, per agrarian zone | 0.4-1.1 | northern dryland reconstruction (poor to good land) | high |
| grain_sale_carry_over_ratio_of_local_need | EliteParameters | S | exploratory | 1 | months of local need | — | — | medium |
| interest_rate_monthly | EliteParameters | S | theoretically-assumed | 0.005 | share of principal per month | 0.01-0.1 | rates reported for pre-modern Chinese credit in the literature | high |
| land_purchase_price_tael_per_mu | EliteParameters | S | theoretically-assumed | 2.5 | tael per mu | — | — | high |
| loan_to_value | EliteParameters | S | theoretically-assumed | 0.5 | share of collateral value (0-1) | — | — | high |
| max_lending_share_of_silver | EliteParameters | S | exploratory | 0.8 | share of silver (0-1) | — | — | medium |
| relief_carry_over_ratio_of_local_need | EliteParameters | S | exploratory | 1 | months of local need | — | — | medium |
| relief_eligibility_unmet_ratio | EliteParameters | S | theoretically-assumed | 0.05 | ratio (0-1) | — | — | low |
| relief_share_of_grain_stock | EliteParameters | S | exploratory | 0.05 | share of grain stock (0-1) | — | — | medium |
| tax_mediation_advance_share | EliteParameters | S | theoretically-assumed | 0.5 | share (0-1) | — | — | medium |
| assessed_value_tael_per_mu | FiscalParameters | C | theoretically-assumed | 0.35 | tael per mu | 0.05-0.4 | declared band around the current value | high |
| collection_cost_logistics_floor | FiscalParameters | S | exploratory | 0.1 | tael per month | — | — | low |
| collection_cost_per_effort_tael | FiscalParameters | S | exploratory | 0.02 | tael per unit of collection effort | — | — | medium |
| elite_hidden_land_share | FiscalParameters | S | theoretically-assumed | 0.6 | share of land (0-1) | 0.0-0.6 | declared band; the sources describe the mechanism, not its size | high |
| granary_purchase_share_of_silver | FiscalParameters | S | exploratory | 0.5 | share of silver (0-1) | — | — | medium |
| granary_target_cover_months | FiscalParameters | S | theoretically-assumed | 1 | months | — | — | medium |
| relief_eligibility_unmet_ratio | FiscalParameters | S | theoretically-assumed | 0.05 | ratio (0-1) | — | — | low |
| relief_logistics_cost_per_shi_tael | FiscalParameters | S | exploratory | 0.02 | tael per shi relieved | — | — | medium |
| relief_share_of_need | FiscalParameters | S | exploratory | 0.5 | share of need (0-1) | — | — | medium |
| arrears_growth_tael_per_month | GovernanceIndicatorParameters | S | exploratory | 1 | tael per month | — | — | low |
| band_troops_share_of_adults | GovernanceIndicatorParameters | S | exploratory | 0.01 | share of adults (0-1) | — | — | low |
| largest_band_share | GovernanceIndicatorParameters | S | exploratory | 0.5 | share of armed men (0-1) | — | — | low |
| out_migration_share_of_households | GovernanceIndicatorParameters | S | exploratory | 0.01 | share of households (0-1) | — | — | low |
| pay_shortfall_share | GovernanceIndicatorParameters | S | exploratory | 0.5 | share of the pay obligation (0-1) | — | — | low |
| receipts_below_quota_share | GovernanceIndicatorParameters | S | exploratory | 0.5 | receipts over quota (0-1) | — | — | low |
| tax_base_contraction_share | GovernanceIndicatorParameters | S | exploratory | 0.02 | share of the opening base (0-1) | — | — | low |
| unmet_share_of_need | GovernanceIndicatorParameters | S | exploratory | 0.25 | share of need (0-1) | — | — | low |
| crop_saturation_events | HistoricalCoreParameters | S | theoretically-assumed | 4 | events per node-year | 2.0-8.0 | declared band around the current value | low |
| crop_weight | HistoricalCoreParameters | S | theoretically-assumed | 0.5 | index points per event | 0.2-0.8 | declared band around the current value | medium |
| drought_saturation_events | HistoricalCoreParameters | S | theoretically-assumed | 6 | events per node-year | 3.0-12.0 | declared band around the current value | high |
| drought_weight | HistoricalCoreParameters | S | theoretically-assumed | 1 | index points per event | 0.5-1.0 | declared band; the ordering drought >= famine >= crop >= pest is what is argued | high |
| famine_saturation_events | HistoricalCoreParameters | S | theoretically-assumed | 4 | events per node-year | 2.0-8.0 | declared band around the current value | medium |
| famine_weight | HistoricalCoreParameters | S | theoretically-assumed | 0.75 | index points per event | 0.4-1.0 | declared band around the current value | high |
| monthly_allocation_profile | HistoricalCoreParameters | C | evidence-backed | 1=0.0066, 2=0.1679, 3=0.0104, 4=0.0104, 5=0.2581, 6=0.0607, 7=0.1167, 8=0.2865, 9=0.0256, 10=0.0085, 11=0.0465, 12=0.0019 | share of the annual total, by month | — | — | high |
| pest_saturation_events | HistoricalCoreParameters | S | theoretically-assumed | 4 | events per node-year | 2.0-8.0 | declared band around the current value | low |
| pest_weight | HistoricalCoreParameters | S | theoretically-assumed | 0.4 | index points per event | 0.1-0.6 | declared band around the current value | medium |
| debt_repayment_grain_ratio_of_annual_need | HouseholdParameters | S | exploratory | 1 | multiple of annual need | — | — | low |
| debt_repayment_silver_reserve_tael_per_household | HouseholdParameters | S | exploratory | 0.5 | tael per household | — | — | low |
| harvest_recovery_grain_ratio | HouseholdParameters | S | exploratory | 0.5 | share of the harvest (0-1) | — | — | low |
| land_reference_value_tael_per_mu | HouseholdParameters | S | theoretically-assumed | 5 | tael per mu | — | — | medium |
| minimum_consumption_fraction | HouseholdParameters | S | exploratory | 0.75 | share of the floor (0-1) | — | — | high |
| permanent_migration_unmet_ratio | HouseholdParameters | S | theoretically-assumed | 0.2 | ratio (0-1) | 0.1-0.5 | declared band around the current line | high |
| recruitment_max_land_per_household_mu | HouseholdParameters | S | exploratory | 2 | mu per household | — | — | medium |
| recruitment_unmet_ratio | HouseholdParameters | S | theoretically-assumed | 0.2 | ratio (0-1) | — | — | high |
| rent_share_of_harvest | HouseholdParameters | S | theoretically-assumed | tenant-household=0.4 | share of harvest (0-1), per cohort class | 0.3-0.6 | customary share-rent fractions reported for north China | high |
| subsistence_grain_per_adult_month_shi | HouseholdParameters | S | theoretically-assumed | 0.25 | shi per adult per month | 0.2-0.6 | caloric requirement per adult converted to grain at declared values | high |
| surplus_keep_ratio_of_annual_need | HouseholdParameters | S | exploratory | 1 | multiple of annual need | — | — | medium |
| tax_grain_sale_floor_ratio_of_annual_need | HouseholdParameters | S | exploratory | 0.5 | multiple of annual need | — | — | high |
| temporary_migration_unmet_ratio | HouseholdParameters | S | theoretically-assumed | 0.05 | ratio (0-1) | 0.05-0.4 | declared band around the current line | high |
| wage_grain_shi_per_adult_month | HouseholdParameters | S | theoretically-assumed | 0.3 | shi per adult per month | 0.3-1.0 | declared prior around the subsistence floor | medium |
| capacity_unit_shi_per_month | MarketParameters | S | exploratory | 1 | shi per month per capacity unit | — | — | medium |
| max_export_share_of_stock | MarketParameters | S | exploratory | 0.5 | share of stock (0-1) | — | — | medium |
| minimum_trade_margin_tael_per_shi | MarketParameters | S | exploratory | 0.1 | tael per shi | — | — | low |
| price_ceiling_ratio | MarketParameters | C | exploratory | 6 | multiple of the reference price | — | — | high |
| price_elasticity | MarketParameters | S | exploratory | 0.8 | elasticity exponent | — | — | high |
| price_floor_ratio | MarketParameters | S | exploratory | 0.5 | share of the reference price (0-1) | — | — | medium |
| reference_price_tael_per_shi | MarketParameters | C | theoretically-assumed | 0.6 | tael per shi | 0.2-2.0 | Yansui series and gazetteer famine prices; the famine peak is a spike, not a reference | high |
| risk_loss_fraction_scale | MarketParameters | S | exploratory | 1 | multiple of the declared edge risk | — | — | medium |
| target_cover_months | MarketParameters | S | theoretically-assumed | 6 | months | — | — | medium |
| transport_cost_tael_per_cost_unit_per_shi | MarketParameters | S | theoretically-assumed | 0.35 | tael per cost unit per shi | — | — | high |
| cost_tael_per_adult | MigrationParameters | S | exploratory | 0.2 | tael per adult | — | — | high |
| cost_tael_per_household | MigrationParameters | S | exploratory | 0.5 | tael per household | — | — | high |
| minimum_households_to_move | MigrationParameters | S | exploratory | 5 | households | — | — | low |
| permanent_share_of_households_per_month | MigrationParameters | S | theoretically-assumed | 0.02 | per month | 0.005-0.1 | declared band around the current value | high |
| temporary_share_of_adults_per_month | MigrationParameters | S | theoretically-assumed | 0.15 | per month | 0.05-0.4 | declared band around the current value | high |
| temporary_term_months | MigrationParameters | S | theoretically-assumed | 6 | months | — | — | medium |
| transit_loss_share | MigrationParameters | S | exploratory | 0.5 | multiple of the declared edge risk | — | — | medium |
| cohesion_food_weight | MilitaryParameters | S | exploratory | 0.1 | coefficient on the ration shortfall | — | — | medium |
| deserter_band_share | MilitaryParameters | S | exploratory | 0.3 | share (0-1) | — | — | high |
| deserter_home_share | MilitaryParameters | S | exploratory | 0.4 | share (0-1) | — | — | high |
| desertion_base_rate | MilitaryParameters | S | exploratory | 0.002 | share of the garrison per month | — | — | high |
| desertion_food_weight | MilitaryParameters | S | exploratory | 0.04 | coefficient on the monthly ration shortfall | — | — | high |
| desertion_max_rate | MilitaryParameters | S | exploratory | 0.08 | share of the garrison per month | — | — | medium |
| desertion_morale_weight | MilitaryParameters | S | exploratory | 0.02 | coefficient on fallen morale | — | — | medium |
| desertion_pay_weight | MilitaryParameters | S | exploratory | 0.05 | coefficient on the monthly pay shortfall | — | — | high |
| food_shi_per_soldier_month | MilitaryParameters | C | theoretically-assumed | 0.3 | shi per soldier per month | 0.2-0.5 | scaled from the subsistence floor with a declared margin | high |
| garrison_target_troops | MilitaryParameters | S | theoretically-assumed | 300 | soldiers per node | — | — | high |
| levy_rate_of_eligible_adults | MilitaryParameters | S | exploratory | 0.002 | adults | — | — | high |
| morale_food_weight | MilitaryParameters | S | exploratory | 0.1 | coefficient on the monthly ration shortfall | — | — | medium |
| morale_pay_weight | MilitaryParameters | S | exploratory | 0.08 | coefficient on the monthly pay shortfall | — | — | medium |
| morale_recovery | MilitaryParameters | S | exploratory | 0.1 | index points per paid month (0-1) | — | — | medium |
| pay_share_of_treasury | MilitaryParameters | C | exploratory | 0.5 | share of treasury (0-1) | — | — | high |
| pay_tael_per_soldier_month | MilitaryParameters | C | theoretically-assumed | 0.25 | tael per soldier per month | 0.1-1.0 | declared band around the current value | high |
| ration_purchase_share_of_silver | MilitaryParameters | C | exploratory | 0.3 | share of silver (0-1) | — | — | medium |
| suppression_arms_mitigation | MilitaryParameters | S | exploratory | 0.5 | share of losses avoided (0-1) | — | — | medium |
| suppression_cohesion_cost | MilitaryParameters | S | exploratory | 0.02 | index points per suppression (0-1) | — | — | low |
| suppression_effectiveness | MilitaryParameters | S | exploratory | 0.02 | members per soldier per month | — | — | high |
| suppression_food_cost_per_troop_shi | MilitaryParameters | S | exploratory | 0.02 | shi per soldier suppressing | — | — | low |

## Sources behind each card, and how far they were read

`identity` means the bibliographic record was confirmed and the text was not read;
`abstract` means an abstract was read; `full-text` means the passage was read. A sourced
card whose sources are all identity-only is a value resting on a title.

| card | grade | sources | verification and read depth |
| --- | --- | --- | --- |
| arms_per_asset_valuation | S | — | — |
| arms_per_member_for_full_capability | S | — | — |
| cohesion_decay_per_month | S | — | — |
| cohesion_gain_per_month | S | — | — |
| dissolve_troops_below | S | — | — |
| food_shi_per_member_month | S | — | — |
| formation_recruitment_months | S | — | — |
| formation_unmet_ratio | S | — | — |
| merge_cohesion_above | S | — | — |
| minimum_formation_troops | S | — | — |
| mobility_decay_per_month | S | — | — |
| mobility_gain_from_move | S | — | — |
| movement_avoidance_ratio | S | — | — |
| movement_mobility_floor | S | — | — |
| network_gain_per_month | S | — | — |
| network_loss_from_raid_per_month | S | — | — |
| raid_asset_share_per_month | S | — | — |
| raid_extraction_multiple | S | — | — |
| recruitment_rate_of_eligible_adults | S | — | — |
| split_cohesion_below | S | — | — |
| split_troops_threshold | S | — | — |
| land_per_adult_capacity_mu | C | 1 | `guo-2001-grain-yields` unverified/identity-only |
| yield_loss_scale | S | — | — |
| yield_shi_per_mu | C | 2 | `guo-2001-grain-yields` unverified/identity-only; `broadberry-gupta-wang-2024-ming` unverified/identity-only |
| grain_sale_carry_over_ratio_of_local_need | S | — | — |
| interest_rate_monthly | S | — | — |
| land_purchase_price_tael_per_mu | S | — | — |
| loan_to_value | S | — | — |
| max_lending_share_of_silver | S | — | — |
| relief_carry_over_ratio_of_local_need | S | — | — |
| relief_eligibility_unmet_ratio | S | — | — |
| relief_share_of_grain_stock | S | — | — |
| tax_mediation_advance_share | S | — | — |
| assessed_value_tael_per_mu | C | 3 | `mingshi` verified/identity-only; `liang-fangzhong-1980` verified/identity-only; `ray-huang-1974` verified/identity-only |
| collection_cost_logistics_floor | S | — | — |
| collection_cost_per_effort_tael | S | — | — |
| elite_hidden_land_share | S | — | — |
| granary_purchase_share_of_silver | S | — | — |
| granary_target_cover_months | S | — | — |
| relief_eligibility_unmet_ratio | S | — | — |
| relief_logistics_cost_per_shi_tael | S | — | — |
| relief_share_of_need | S | — | — |
| arrears_growth_tael_per_month | S | — | — |
| band_troops_share_of_adults | S | — | — |
| largest_band_share | S | — | — |
| out_migration_share_of_households | S | — | — |
| pay_shortfall_share | S | — | — |
| receipts_below_quota_share | S | — | — |
| tax_base_contraction_share | S | — | — |
| unmet_share_of_need | S | — | — |
| crop_saturation_events | S | — | — |
| crop_weight | S | — | — |
| drought_saturation_events | S | — | — |
| drought_weight | S | — | — |
| famine_saturation_events | S | — | — |
| famine_weight | S | — | — |
| monthly_allocation_profile | C | 1 | `reaches-noaa` verified/identity-only |
| pest_saturation_events | S | — | — |
| pest_weight | S | — | — |
| debt_repayment_grain_ratio_of_annual_need | S | — | — |
| debt_repayment_silver_reserve_tael_per_household | S | — | — |
| harvest_recovery_grain_ratio | S | — | — |
| land_reference_value_tael_per_mu | S | — | — |
| minimum_consumption_fraction | S | — | — |
| permanent_migration_unmet_ratio | S | — | — |
| recruitment_max_land_per_household_mu | S | — | — |
| recruitment_unmet_ratio | S | — | — |
| rent_share_of_harvest | S | — | — |
| subsistence_grain_per_adult_month_shi | S | — | — |
| surplus_keep_ratio_of_annual_need | S | — | — |
| tax_grain_sale_floor_ratio_of_annual_need | S | — | — |
| temporary_migration_unmet_ratio | S | — | — |
| wage_grain_shi_per_adult_month | S | — | — |
| capacity_unit_shi_per_month | S | — | — |
| max_export_share_of_stock | S | — | — |
| minimum_trade_margin_tael_per_shi | S | — | — |
| price_ceiling_ratio | C | 2 | `shaanxi-famine-gazetteers` verified/identity-only; `quan-1991-northern-prices` unverified/identity-only |
| price_elasticity | S | — | — |
| price_floor_ratio | S | — | — |
| reference_price_tael_per_shi | C | 2 | `quan-1991-northern-prices` unverified/identity-only; `shaanxi-famine-gazetteers` verified/identity-only |
| risk_loss_fraction_scale | S | — | — |
| target_cover_months | S | — | — |
| transport_cost_tael_per_cost_unit_per_shi | S | — | — |
| cost_tael_per_adult | S | — | — |
| cost_tael_per_household | S | — | — |
| minimum_households_to_move | S | — | — |
| permanent_share_of_households_per_month | S | — | — |
| temporary_share_of_adults_per_month | S | — | — |
| temporary_term_months | S | — | — |
| transit_loss_share | S | — | — |
| cohesion_food_weight | S | — | — |
| deserter_band_share | S | — | — |
| deserter_home_share | S | — | — |
| desertion_base_rate | S | — | — |
| desertion_food_weight | S | — | — |
| desertion_max_rate | S | — | — |
| desertion_morale_weight | S | — | — |
| desertion_pay_weight | S | — | — |
| food_shi_per_soldier_month | C | 2 | `ray-huang-1974` verified/identity-only; `ray-huang-chc8` verified/identity-only |
| garrison_target_troops | S | — | — |
| levy_rate_of_eligible_adults | S | — | — |
| morale_food_weight | S | — | — |
| morale_pay_weight | S | — | — |
| morale_recovery | S | — | — |
| pay_share_of_treasury | C | 2 | `ray-huang-chc8` verified/identity-only; `ray-huang-1970` verified/identity-only |
| pay_tael_per_soldier_month | C | 3 | `ray-huang-1974` verified/identity-only; `ray-huang-chc8` verified/identity-only; `ray-huang-1970` verified/identity-only |
| ration_purchase_share_of_silver | C | 2 | `ray-huang-1974` verified/identity-only; `ray-huang-chc8` verified/identity-only |
| suppression_arms_mitigation | S | — | — |
| suppression_cohesion_cost | S | — | — |
| suppression_effectiveness | S | — | — |
| suppression_food_cost_per_troop_shi | S | — | — |


## Recorded conflicts

- none: no card currently records two sources that disagree.
