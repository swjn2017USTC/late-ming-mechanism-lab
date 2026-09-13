# P09 objective: what was frozen before anything was fitted

Generated from the registry, the cards and the ensemble's manifest. Every bound below is
the range a P08 parameter card already declared; nothing here widened or narrowed one.

## Windows

| role | ticks | calendar | months | note |
| --- | --- | --- | --- | --- |
| `calibration` | 0-119 | 1625-01 to 1634-12 | 120 | The warm-up plus the first shock decade. This is the only window an objective may read: it contains the onset of the crisis and enough years for the slow state (arrears, land, depletion) to move. |
| `hold-out` | 120-215 | 1635-01 to 1642-12 | 96 | Reserved. Nothing may be fitted to it; it exists to test whether a calibrated ensemble predicts the middle of the crisis, where the drought, the fiscal shortfall and the armed groups are all in play together. |
| `extrapolation` | 216-239 | 1643-01 to 1644-12 | 24 | Reserved, and the hard case: the last two years, beyond the decade the ensemble was shaped on, where the sources describe the collapse of the fiscal-military system. |
| `whole-run` | 0-239 | 1625-01 to 1644-12 | 240 | The whole run, used only by the hold-out prediction path. A pattern recording 1627-1644 cannot be scored inside a single third of the window, and scoring it is not fitting: the calibration objective is bound to the calibration window and refuses this one. |

## The frozen registry

Ensemble batch: `p09-cards87a14e9d-32p-ch1-s20260913`  
Evidence digest: `87a14e9d12e69f3c8bf227632a0f51a95818135457c8510f42643d1f2d45a334`  
Pattern schema: `historical-patterns-v1`  
Prior digest: `3ad980d7d2b58b9c6ba9bc89b135cc16c4b0820bb16b4b6fd01fcd28cc8bd0fd`  
Objective digest: `060b6546cf03cb324bbb213c849b50e088250fd6d123aa05dbfdcb6bf9e40b3c`  
Configuration hash: `f8b70130a3c6d74736a99452d0fd5c2d6b09b1848ea80e02a00981651ecab29c`  
Root seed: `20260912`  

| file | digest |
| --- | --- |
| `sources/registry/clusters-01-05.yaml` | `580471f91498983f` |
| `sources/registry/clusters-06-10.yaml` | `5a1e83207be7cae3` |
| `data/parameters/band.yaml` | `21d2ce35b23fd54e` |
| `data/parameters/crop.yaml` | `bc3ee4819ec23ccb` |
| `data/parameters/elite.yaml` | `1c49c3106e17c288` |
| `data/parameters/fiscal.yaml` | `c5c2c8574398673a` |
| `data/parameters/governance.yaml` | `76b16a4b66aacf5e` |
| `data/parameters/household.yaml` | `0b0338368eb8fea4` |
| `data/parameters/market.yaml` | `51fce66a6a966450` |
| `data/parameters/migration.yaml` | `e2c0551676018938` |
| `data/parameters/military.yaml` | `bcaf098b4bbda2ac` |
| `data/normalized/evidence_ledger-01-05.yaml` | `ea9242e7160033ea` |
| `data/normalized/evidence_ledger-06-10.yaml` | `3fe12938f381401d` |
| `data/normalized/rule_claims.yaml` | `d2e28ee06ee46c44` |
| `data/historical_patterns/01-drought-climate.yaml` | `1f45840987f8621f` |
| `data/historical_patterns/02-famine.yaml` | `02ef9e04a0cfc46c` |
| `data/historical_patterns/03-agriculture.yaml` | `3ba2fb77913902d0` |
| `data/historical_patterns/04-population-migration.yaml` | `45f586697c25b55e` |
| `data/historical_patterns/05-grain-market-prices.yaml` | `d42119585639dd09` |
| `data/historical_patterns/06-land-debt-elites.yaml` | `a80df344eaa5e04e` |
| `data/historical_patterns/07-taxation-levies.yaml` | `42a6ed214558aab3` |
| `data/historical_patterns/08-relief.yaml` | `23ed8d94cfbb104f` |
| `data/historical_patterns/09-military-finance.yaml` | `2ba254087ffd4521` |
| `data/historical_patterns/10-rebellion-armed-groups.yaml` | `ff5eaf64d87394df` |

## The calibrated parameters

A parameter is calibrated when its card declares a numeric range, the field is a scalar
the sandbox accepts, the card marks it a sensitivity priority, and at least one target
check reaches its mechanism. The support is the card range, unadjusted.

| parameter | set | range | central | class | grade | why this parameter |
| --- | --- | --- | --- | --- | --- | --- |
| `yield_loss_scale` | CropParameters | [0.5, 2] | 0.5 | exploratory | S | famine-local-price-extremes / land-abandonment-in-famine: climate damage scales the yield loss that drives both. |
| `subsistence_grain_per_adult_month_shi` | HouseholdParameters | [0.2, 0.6] | 0.25 | theoretically-assumed | S | absorption-of-deserters-and-refugees / debt-transfers-land: the subsistence floor sets distress. |
| `permanent_migration_unmet_ratio` | HouseholdParameters | [0.1, 0.5] | 0.2 | theoretically-assumed | S | land-abandonment-in-famine: the distress line that lets a household leave. |
| `temporary_migration_unmet_ratio` | HouseholdParameters | [0.05, 0.4] | 0.05 | theoretically-assumed | S | land-abandonment-in-famine: the same line for a season's absence. |
| `interest_rate_monthly` | EliteParameters | [0.01, 0.1] | 0.005 | theoretically-assumed | S | debt-transfers-land: the credit price that moves land to creditors. |
| `assessed_value_tael_per_mu` | FiscalParameters | [0.05, 0.4] | 0.35 | theoretically-assumed | C | receipts-shortfall-chronic: the assessed value sets the quota receipts fall short of. |
| `elite_hidden_land_share` | FiscalParameters | [0, 0.6] | 0.6 | theoretically-assumed | S | receipts-shortfall-chronic / land-abandonment-in-famine: hidden land shrinks the visible base. |
| `reference_price_tael_per_shi` | MarketParameters | [0.2, 2] | 0.6 | theoretically-assumed | C | famine-local-price-extremes: the external price that the local posted price is dispersed around. |
| `permanent_share_of_households_per_month` | MigrationParameters | [0.005, 0.1] | 0.02 | theoretically-assumed | S | land-abandonment-in-famine: the departure rate that abandons land. |
| `temporary_share_of_adults_per_month` | MigrationParameters | [0.05, 0.4] | 0.15 | theoretically-assumed | S | land-abandonment-in-famine: the seasonal rate that removes labour. |
| `pay_tael_per_soldier_month` | MilitaryParameters | [0.1, 1] | 0.25 | theoretically-assumed | C | absorption-of-deserters-and-refugees: pay arrears drive desertion, the bands' intake. |
| `food_shi_per_soldier_month` | MilitaryParameters | [0.2, 0.5] | 0.3 | theoretically-assumed | C | absorption-of-deserters-and-refugees: garrison rations are the other route to desertion. |
| `food_shi_per_member_month` | BandParameters | [0.2, 0.5] | 0.3 | theoretically-assumed | S | absorption-of-deserters-and-refugees: a band that cannot feed members cannot absorb them. |

### Range-carrying cards deliberately not calibrated

| parameter | why not |
| --- | --- |
| `yield_shi_per_mu` | the card is dict-valued, one baseline per agrarian zone, so no single draw can set it. |
| `rent_share_of_harvest` | the card declares one range but the field in use is dict-valued, one share per cohort class: a scalar draw would not be the value the model runs, so the card's band documents the shares rather than bounds a draw. |
| `land_per_adult_capacity_mu` | the card's sensitivity_priority is medium and no target pattern's checks reach the labour market. |
| `wage_grain_shi_per_adult_month` | the card's sensitivity_priority is medium and no target check reaches the wage. |

### Recorded inconsistencies found in the registry

- Parameters whose card records a value in use outside its own range: 1.
  - `interest_rate_monthly`: the card records 0.005, below its own range [0.01, 0.1]. The prior is the range, so this default lies outside the calibration support; the report says so instead of widening the band.
- Cards with no range at all (not calibratable here): 85.

## The target checks

Each check reads a statistic or a pair of series and quotes the P08 signature whose
wording fixes the comparison. A pattern's score is the share of its checks that failed.

| pattern | check | kind | reads | question |
| --- | --- | --- | --- | --- |
| `absorption-of-deserters-and-refugees` | `intake-tracks-desertion` | co-moves-positive | `band_intake_adults vs deserted_troops` | does band in-take rise in the years when more soldiers desert? |
| `absorption-of-deserters-and-refugees` | `intake-tracks-distress` | co-moves-positive | `band_intake_adults vs unmet_ratio` | does band in-take rise in the years when households are in greater distress? |
| `absorption-of-deserters-and-refugees` | `bands-grow` | rises | `band_troops` | does total band strength grow across the window? |
| `debt-transfers-land` | `elite-share-rises` | rises | `elite_land_share` | does the elite's share of land rise across the window? |
| `debt-transfers-land` | `household-inequality-rises` | rises | `cohort_land_gini` | does inequality in land per household rise across the window? |
| `debt-transfers-land` | `transfer-tracks-distress` | co-moves-positive | `elite_land_share vs unmet_ratio` | does the elite's land share rise as distress rises? |
| `famine-local-price-extremes` | `dispersion-tracks-distress` | co-moves-positive | `price_cv vs unmet_ratio` | does cross-node price dispersion widen as distress rises? |
| `famine-local-price-extremes` | `dispersion-widens` | rises | `price_cv` | is the worst year's dispersion above the first year's? |
| `land-abandonment-in-famine` | `abandonment-present-in-crisis-years` | present-in-crisis-years | `land_abandoned_mu` | is any land abandoned in the years whose distress is above the window median? |
| `land-abandonment-in-famine` | `abandonment-tracks-distress` | co-moves-positive | `land_abandoned_mu vs unmet_ratio` | does abandonment appear in the worse years rather than the better ones? |
| `land-abandonment-in-famine` | `visible-base-contracts` | falls | `taxable_land_mu` | does the visible tax base contract across the window? |
| `receipts-shortfall-chronic` | `receipts-below-quota-persistent` | mostly-below | `receipts_over_quota` | do receipts stay below the assessed quota in most months of the window? |
| `receipts-shortfall-chronic` | `arrears-accumulate` | rises | `arrears_tael` | does the arrears stock accumulate across the window? |

### The record's wording, per target pattern

**`absorption-of-deserters-and-refugees`** — Armed groups grew by absorbing soldiers and refugees (B evidence, window 1628-1644, Shaanxi, Shanxi, Henan)

> Rebel forces expanded by absorbing other bands, surrendered Ming soldiers and famine refugees, which made their composition fluid and their growth closely tied to the state's own failures.

- quantity: band recruitment from the deserter pool and from distress-eligible households
  - the record shows: band membership growing when desertion and distress rise, i.e. the state's losses becoming the bands' recruits
  - how to score it: co-movement between desertion/distress and band in-take; no magnitude
- would count against the model: band growth uncorrelated with desertion or distress
- would count against the model: bands growing while both garrisons and households are well off

**`debt-transfers-land`** — Credit relations transfer land in distress (B evidence, window 1600-1644, Ming China)

> Loans secured on land, at high monthly rates, are described as the mechanism through which holdings moved to creditors during bad years; land prices in distress fell below normal values.

- quantity: elite land share and the cohort land gini
  - the record shows: both rise through the crisis as households sell and default
  - how to score it: direction and co-movement with distress; no magnitude
- would count against the model: elite land share flat while distress and land sales rise
- would count against the model: land gini falling through the crisis

**`famine-local-price-extremes`** — Local famine prices reach extreme levels (B evidence, window 1631-1641, Shangzhou and Shenmu, Shaanxi)

> Gazetteers record extreme local prices in the famine years: 4 taels of silver per dou of rice at Shangzhou in 1631, with escalating prices at Shenmu in 1640-41 — an acute local peak, not a provincial average.

- quantity: cross-node price dispersion (coefficient of variation, max/min ratio)
  - the record shows: dispersion rising sharply in famine years, with the worst local ratio far above normal
  - how to score it: compare the ordering of years by dispersion; the model's ceiling means the magnitude is expected to fall short, and that shortfall is reported
- would count against the model: uniform prices across nodes in famine years
- would count against the model: dispersion falling as the crisis deepens

**`land-abandonment-in-famine`** — Fields are abandoned in the worst years (C evidence, window 1630-1644, Shaanxi)

> The gazetteers and the transition literature describe fields going out of cultivation as households fled, and the registered tax base diverging from the land actually farmed.

- quantity: land abandoned by migration (land_abandoned_mu) and the visible tax base
  - the record shows: abandonment appears in the crisis years, and the visible base contracts
  - how to score it: direction and co-movement with distress; no magnitude
- would count against the model: no land abandoned despite sustained out-migration
- would count against the model: a tax base that grows through the crisis years

**`receipts-shortfall-chronic`** — Receipts fall short of assessment (B evidence, window 1600-1644, Ming China)

> Assessment and receipt were not the same thing: collection was incomplete, arrears accumulated, and the burden shifted as the registering system decayed; the state's fiscal problem in the period is described as a shortfall between what was assessed and what arrived.

- quantity: actual receipts against nominal quota, and the tax arrears stock
  - the record shows: receipts persistently below the assessed quota, with arrears accumulating
  - how to score it: direction and persistence: the shortfall should be structural, not episodic
- would count against the model: receipts meeting the quota in most years
- would count against the model: arrears falling to zero and staying there

## Sampler settings

- particles: 32, chains: 1, seed: 20260913
- Laplace tolerance per pattern: 0.25 (a score is the share of a pattern's checks that failed; the target patterns carry two or three checks each, so this allows about one failed check before the kernel discounts)
- hold-out patterns reserved and never scored here: 8 (`chongzhen-drought-sequence`, `famine-worst-years-1639-43`, `many-bands-then-consolidation`, `pay-monetised-and-arrears`, `price-spike-concentration`, `quota-erosion-and-surcharge`, `relief-overwhelmed-in-worst-years`, `shaanxi-net-outflow`)
- PyMC 6.3.2, ArviZ 1.3.0, engine 0.1.0
- stages: 3, accept rates: [0.40625, 0.3958333333333333, 0.4270833333333333], distinct draws simulated: 288
