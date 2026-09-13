# P09 mismatch: the checks the model does not satisfy

Read from the posterior predictive runs, in the calibration window — the window the
objective scored. A check whose failure share is at or above 0.5 is called systematically unsatisfied: the ensemble's own
runs contradict it more often than not, at every draw inside the declared bounds.

| pattern | check | satisfied share | median value |
| --- | --- | --- | --- |
| `absorption-of-deserters-and-refugees` | `bands-grow` | 1.00 | 2499.6312 |
| `absorption-of-deserters-and-refugees` | `intake-tracks-desertion` | 0.25 | -0.1912 |
| `absorption-of-deserters-and-refugees` | `intake-tracks-distress` | 1.00 | 0.5212 |
| `debt-transfers-land` | `elite-share-rises` | 1.00 | 0.1451 |
| `debt-transfers-land` | `household-inequality-rises` | 1.00 | 0.0685 |
| `debt-transfers-land` | `transfer-tracks-distress` | 0.81 | 0.4058 |
| `famine-local-price-extremes` | `dispersion-tracks-distress` | 0.38 | 0.0000 |
| `famine-local-price-extremes` | `dispersion-widens` | 0.44 | 0.0000 |
| `land-abandonment-in-famine` | `abandonment-present-in-crisis-years` | 1.00 | 32339.2027 |
| `land-abandonment-in-famine` | `abandonment-tracks-distress` | 1.00 | 0.5154 |
| `land-abandonment-in-famine` | `visible-base-contracts` | 1.00 | -13936.7138 |
| `receipts-shortfall-chronic` | `arrears-accumulate` | 1.00 | 1665.4256 |
| `receipts-shortfall-chronic` | `receipts-below-quota-persistent` | 1.00 | 1.0000 |

## Patterns the model cannot match, and what would count against it

**`absorption-of-deserters-and-refugees`** — checks systematically unsatisfied: `intake-tracks-desertion`.

> Rebel forces expanded by absorbing other bands, surrendered Ming soldiers and famine refugees, which made their composition fluid and their growth closely tied to the state's own failures.

- the record's own falsifier: band growth uncorrelated with desertion or distress
- the record's own falsifier: bands growing while both garrisons and households are well off

**`famine-local-price-extremes`** — checks systematically unsatisfied: `dispersion-tracks-distress`, `dispersion-widens`.

> Gazetteers record extreme local prices in the famine years: 4 taels of silver per dou of rice at Shangzhou in 1631, with escalating prices at Shenmu in 1640-41 — an acute local peak, not a provincial average.

- the record's own falsifier: uniform prices across nodes in famine years
- the record's own falsifier: dispersion falling as the crisis deepens

## The one place a historical magnitude is printed

P08 recorded a local famine price that the model's ceiling does not reach. That gap is a
known limitation of the mechanism, recorded here rather than closed by calibration:

- recorded: the 1631 Shangzhou price, 4 tael per dou, i.e. 40 tael per shi (`famine-local-price-extremes`).
- the card `reference_price_tael_per_shi` declares a band up to 2 tael per shi, and the model cannot post more than its ceiling allows.
- consequence: a famine-price comparison can test direction and timing, never magnitude, until the mechanism is revisited on evidence.
