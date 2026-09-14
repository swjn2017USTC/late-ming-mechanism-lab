# M006 - Famine Mortality

**Status: UNIDENTIFIED**

*Question.* Does excess death from hunger carry a harvest failure into population loss, and from there into labour scarcity and abandoned land?

## 1. Micro conditions

- A cohort whose consumption falls below subsistence loses members, in proportion to how far below it falls and for how long.
- The dead leave the labour pool, so the next season's cultivation is smaller.

## 2. Meso conditions

- Relief and credit determine who reaches subsistence and who does not, so the mortality rate is a function of institutions as well as of the harvest.
- Land is abandoned when the households that worked it are gone, not only when they flee.

## 3. Causal chain

- Precipitation deficit, then harvest failure, then price spike, then consumption below subsistence.
- Members of the cohort die; the model records no such event and cannot.
- Labour per mu falls and cultivation is abandoned.

## 4. Trigger

A consumption shortfall persisting past the point where assets are exhausted - a state the model reaches, since it records consumption events below the subsistence line, but which it resolves by distress sales and departure rather than by death.

## 5. Macro outcome

Population decline beyond what migration explains, and a labour shortage in the seasons after a famine - neither of which any artifact in this project reports.

## 6. Necessary versus facilitating conditions

- A household cohort with a member count that death can reduce. (*micro*, necessary)
- A subsistence threshold below which consumption costs lives. (*micro*, necessary)
- Relief that arrives too late to change the outcome. (*meso*, facilitating)

## 7. Time lag

Not measurable in this model. The record puts deaths within the famine year and its aftermath; the model has no mortality clock at all, and the abandonment it does show is produced by departure, which is monthly.

## 8. Sensitivity evidence

None exists. The P09 prior table carries thirteen parameters and none of them is a mortality or survival rate; no Morris trajectory and no Sobol index can bear on a quantity the model does not compute.

## 9. Ablation evidence

No arm can be built. Removing mortality would be a no-op because there is nothing to remove, which is exactly the situation the NO_BAND_MERGER arm demonstrates for a different rule: an arm whose intervention cannot bind measures the rule's absence, not its effect.

## 10. Hold-out evidence

land-abandonment-in-famine - the pattern mortality is supposed to help produce - is satisfied in 1.00 of draws without any mortality rule, through departure. The pattern scores therefore cannot distinguish a world with deaths from one without.

## 11. Policy robustness

Not applicable: P12 reads three mechanisms and none of them is a population quantity, so no policy arm produces evidence about mortality.

## 12. Historical support

famine-lags-harvest-failure (grade B, constraint, window 1628-1635): sequence, not a level not scored; land-abandonment-in-famine (grade C, target, window 1630-1644): calibration window 1.00

## 13. Historical challenge

The record's causal sequence is precipitation, harvest, price, hunger, death - and the mortality is the part of it the project has never implemented. The model reaches the abandonment outcome through a different mechanism, so the historical case for mortality cannot be tested here at all.

## 14. Counterexample

The model satisfies land-abandonment-in-famine at 1.00 with zero deaths, so any claim that mortality is necessary for abandonment is contradicted inside the model - and any claim that the model's abandonment is historical evidence for a mortality mechanism is contradicted by the model's own structure.

## 15. Falsifiable prediction

Add a mortality rule that removes members on a sustained subsistence shortfall and the held-out scores should move only if the pattern's timing depends on labour scarcity: if famine-worst-years-1639-43 stays at 1.00 and the population statistics shift, mortality changes levels rather than timing in this model. That test cannot be run today, which is why the status is UNIDENTIFIED rather than WEAK.

## 16. Uncertainty

The gap is structural rather than empirical: no mortality event, no mortality parameter, no mortality output, so nothing in the project could have measured this mechanism even in principle. P08 recorded it as a coverage gap; this card records it as the largest single mismatch between the model's mechanism set and the record's causal chain.

## Evidence cited

| kind | source | reading |
|---|---|---|
| historical-support | `chen-2024-chongzhen` | famine-lags-harvest-failure (grade B, constraint, window 1628-1635): sequence, not a level not scored |
| historical-support | `shaanxi-famine-gazetteers` | land-abandonment-in-famine (grade C, target, window 1630-1644): calibration window 1.00 |

Statuses across the book: 1 CONDITIONAL, 1 REJECTED, 2 SUPPORTED, 1 UNIDENTIFIED, 1 WEAK.
