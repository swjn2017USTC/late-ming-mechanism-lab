# P09 prediction: the reserved windows, scored after the ensemble was frozen

The 8 patterns P08 marked `hold-out` were never part of the
objective. The objective refuses any window but the calibration window and the predictive
checks refuse the calibration window, so the two surfaces are disjoint by construction
and a test asserts it both ways. Everything below is read from runs made afterwards.

| window | ticks | role in the split |
| --- | --- | --- |
| `whole-run` | 0-239 | The whole run, used only by the hold-out prediction path. A pattern recording 1627-1644 cannot be scored inside a single third of the window, and scoring it is not fitting: the calibration objective is bound to the calibration window and refuses this one. |
| `calibration` | 0-119 | The warm-up plus the first shock decade. This is the only window an objective may read: it contains the onset of the crisis and enough years for the slow state (arrears, land, depletion) to move. |
| `hold-out` | 120-215 | Reserved. Nothing may be fitted to it; it exists to test whether a calibrated ensemble predicts the middle of the crisis, where the drought, the fiscal shortfall and the armed groups are all in play together. |
| `extrapolation` | 216-239 | Reserved, and the hard case: the last two years, beyond the decade the ensemble was shaped on, where the sources describe the collapse of the fiscal-military system. |

## Reserved patterns, by window

| window | pattern | check | satisfied share | median value |
| --- | --- | --- | --- | --- |
| `extrapolation` | `chongzhen-drought-sequence` | `shock-peak-in-late-years` | 1.00 | 1643.0000 |
| `extrapolation` | `famine-worst-years-1639-43` | `famine-events-concentrated-late` | 1.00 | 1.0000 |
| `extrapolation` | `many-bands-then-consolidation` | `largest-band-share-rises` | 0.66 | 0.0050 |
| `extrapolation` | `pay-monetised-and-arrears` | `pay-arrears-accumulate` | 1.00 | 1554.5192 |
| `extrapolation` | `pay-monetised-and-arrears` | `pay-shortfall-structural` | 1.00 | 1.0000 |
| `extrapolation` | `price-spike-concentration` | `price-spike-peak-late` | 1.00 | 1643.0000 |
| `extrapolation` | `quota-erosion-and-surcharge` | `receipts-short-of-quota` | 1.00 | 1.0000 |
| `extrapolation` | `relief-overwhelmed-in-worst-years` | `relief-coverage-falls-as-need-peaks` | 0.00 | 0.0000 |
| `extrapolation` | `shaanxi-net-outflow` | `exits-in-crisis-years` | 0.00 | 0.0000 |
| `hold-out` | `chongzhen-drought-sequence` | `shock-peak-in-late-years` | 0.00 | 1635.0000 |
| `hold-out` | `famine-worst-years-1639-43` | `famine-events-concentrated-late` | 1.00 | 0.6166 |
| `hold-out` | `many-bands-then-consolidation` | `largest-band-share-rises` | 0.62 | 0.0107 |
| `hold-out` | `pay-monetised-and-arrears` | `pay-arrears-accumulate` | 1.00 | 11433.6470 |
| `hold-out` | `pay-monetised-and-arrears` | `pay-shortfall-structural` | 1.00 | 1.0000 |
| `hold-out` | `price-spike-concentration` | `price-spike-peak-late` | 0.44 | 1635.0000 |
| `hold-out` | `quota-erosion-and-surcharge` | `receipts-short-of-quota` | 1.00 | 1.0000 |
| `hold-out` | `relief-overwhelmed-in-worst-years` | `relief-coverage-falls-as-need-peaks` | 0.25 | 0.0000 |
| `hold-out` | `shaanxi-net-outflow` | `exits-in-crisis-years` | 0.16 | 0.0000 |
| `whole-run` | `chongzhen-drought-sequence` | `shock-peak-in-late-years` | 0.00 | 1625.0000 |
| `whole-run` | `famine-worst-years-1639-43` | `famine-events-concentrated-late` | 0.00 | 0.2683 |
| `whole-run` | `many-bands-then-consolidation` | `largest-band-share-rises` | 0.94 | 0.2975 |
| `whole-run` | `pay-monetised-and-arrears` | `pay-arrears-accumulate` | 1.00 | 25850.2585 |
| `whole-run` | `pay-monetised-and-arrears` | `pay-shortfall-structural` | 1.00 | 1.0000 |
| `whole-run` | `price-spike-concentration` | `price-spike-peak-late` | 0.44 | 1625.0000 |
| `whole-run` | `quota-erosion-and-surcharge` | `receipts-short-of-quota` | 1.00 | 1.0000 |
| `whole-run` | `relief-overwhelmed-in-worst-years` | `relief-coverage-falls-as-need-peaks` | 0.84 | -0.2134 |
| `whole-run` | `shaanxi-net-outflow` | `exits-in-crisis-years` | 1.00 | 0.9119 |

## Reserved claims the ensemble contradicts over the whole run

**`chongzhen-drought-sequence`** — The Chongzhen drought sequence. Checks failing in most draws: `shock-peak-in-late-years`.

- the record: Documentary reconstructions place a multi-year drought across North China from the late 1620s into the early 1640s, with the greatest severity in the late 1630s and early 1640s; different reconstructions date the onset to 1627 or 1628, and the dry-wet index identifies the episode as the most severe in eastern China of the past 1,500 years.
- the record shows: severe shocks concentrated in the late 1630s and early 1640s rather than evenly spread
- the record shows: a rising share through the 1630s, with the worst years near the end of the window
- the record's own falsifier: severe shocks distributed evenly across the window, with no late concentration
- the record's own falsifier: the model's worst simulated years falling in the warm-up period rather than the 1630s-40s

**`famine-worst-years-1639-43`** — The worst famine years are at the end of the window. Checks failing in most draws: `famine-events-concentrated-late`.

- the record: Famine-price observations and famine records concentrate extraordinarily in the last five years of the period, when deficit, harvest failure and famine converged; one corpus places a large share of all its famine-price reports inside that window.
- the record shows: concentrated in the final five years of the run rather than spread through it
- the record's own falsifier: famine events spread evenly across the two decades
- the record's own falsifier: the model's worst distress in the first half of the window

**`price-spike-concentration`** — The worst price years are the last five. Checks failing in most draws: `price-spike-peak-late`.

- the record: Famine-price observations concentrate extraordinarily in 1639-1643; one gazetteer corpus places a large share of all its famine-price reports inside that five-year window, while a border series shows a twentyfold rise from a normal mid-fifteenth-century price to the 1631 peak.
- the record shows: concentrated peaks in the late 1630s and early 1640s
- the record's own falsifier: price dispersion flat across the run
- the record's own falsifier: the worst dispersion before the first severe shock

## Where the ensemble lands, in the hold-out window

| statistic | hold-out median | hold-out q1 | hold-out q3 | calibration median |
| --- | --- | --- | --- | --- |
| `mean_unmet_ratio` | 0.3415 | 0.2937 | 0.4193 | 0.3312 |
| `share_cohorts_destitute` | 0.7600 | 0.7200 | 0.8800 | 0.7200 |
| `households_departed` | 0.0000 | 0.0000 | 566.5203 | 4339.9341 |
| `households_exited` | 0.0000 | 0.0000 | 0.0000 | 2431.3589 |
| `temporary_adults_sent` | 2063.0439 | 1237.9597 | 4244.2001 | 20541.9600 |
| `land_abandoned_mu` | 0.0000 | 0.0000 | 7340.4595 | 50066.4064 |
| `mean_price_dispersion` | 0.0000 | 0.0000 | 0.1599 | 0.0062 |
| `peak_price_dispersion` | 1.0000 | 1.0000 | 1.5428 | 1.2022 |
| `receipts_over_quota` | 0.1384 | 0.1088 | 0.1968 | 0.2997 |
| `tax_arrears_growth` | 12335.0449 | 5731.6073 | 16358.9114 | 6087.1195 |
| `tax_base_change` | -448.8133 | -8001.0481 | 0.0000 | -61390.8849 |
| `pay_arrears_growth` | 12852.1194 | 10983.8162 | 14169.9886 | 11643.1023 |
| `mean_pay_shortfall` | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| `mean_desertion_rate` | 0.6347 | 0.5643 | 0.7847 | 0.4614 |
| `bands_at_end` | 10.0000 | 7.0000 | 11.0000 | 5.0000 |
| `peak_largest_band_share` | 0.3919 | 0.3165 | 0.4867 | 0.6480 |
| `cohort_grain_seized` | 99676.4554 | 59336.9576 | 138859.9287 | 44728.0053 |
| `relief_released` | 562.7911 | 0.0000 | 1033.7763 | 1513.2332 |
| `elite_land_share` | 0.3334 | 0.2972 | 0.4651 | 0.3249 |
| `cohort_land_gini` | 0.5448 | 0.5273 | 0.6174 | 0.5423 |
| `band_intake_adults` | 1244.8264 | 1095.0738 | 1480.7387 | 1537.8456 |
| `band_troops_change` | 1596.7105 | 1219.1678 | 1809.8509 | 2441.7204 |
| `deserted_troops` | 9189.0941 | 8165.3855 | 10398.2836 | 11248.3451 |

## Patterns this scale cannot check

None: every reserved pattern has at least one check that reads a quantity this model reports. Where a check's quantity is only available per node or per band, the check reads the run-level aggregate and the report says so in the check's question.
