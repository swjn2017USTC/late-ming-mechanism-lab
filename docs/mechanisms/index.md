# Mechanism cards

P13 read the calibration ensemble, the hold-out pass, the sensitivity screens, the ablations, the counterfactual arms and the policy-robustness matrix, and wrote one card per candidate mechanism. This report holds what the six cards say together, where they contradict the project's own earlier documents, and what a fitted surface can and cannot add.

A status is computed from the evidence and checked against the schema's rules - a SUPPORTED card must cite an intervention as well as the quantities that were watched - and every number in a card is read from the batch it names. The machine-readable form is `cards.yaml`.

| id | mechanism | status | one line |
|---|---|---|---|
| M001 | [Fiscal Extraction Inversion](M001-fiscal-extraction-inversion.md) | CONDITIONAL | Three declared policies, three counties, thirty-two cohorts. |
| M002 | [Crisis Gating](M002-crisis-gating.md) | SUPPORTED | The gated region moves with the decision policy: 7 of 9 grid cells break down under the rule policy, 6 under random and 5 under utility, and only the rule policy's cell set is the reference's - so which cells break down is policy-dependent. |
| M003 | [Fiscal-Military Ratchet](M003-fiscal-military-ratchet.md) | REJECTED | arrears 254 to 26,849 tael with 37 month(s) of decline, against 287,355 assessed: the rule arm's largest end stock belongs to a replicate that still records dozens of months in which the stock falls, and the arm's largest decline count is 53. |
| M004 | [Elite Mediation Bifurcation](M004-elite-mediation-bifurcation.md) | WEAK | The card is named for a bifurcation and the evidence resolves one branch of it, which is why the status is WEAK rather than CONDITIONAL: credit is load-bearing, and the claim that elites divide into mediators and accumulators with different consequences is neither measured nor consistent with the runs, where both sides appear together. |
| M005 | [Insurgent Consolidation](M005-insurgent-consolidation.md) | SUPPORTED | Robust: present in rule 0.83, utility 0.83, random 0.83 of replicates (P12 verdict 'robust' at 3 of 3 arms). |
| M006 | [Famine Mortality](M006-famine-mortality.md) | UNIDENTIFIED | The gap is structural rather than empirical: no mortality event, no mortality parameter, no mortality output, so nothing in the project could have measured this mechanism even in principle. |

Counts: 1 CONDITIONAL, 1 REJECTED, 2 SUPPORTED, 1 UNIDENTIFIED, 1 WEAK.

## What the statuses mean

| status | means |
|---|---|
| SUPPORTED | an intervention moved it and at least one other evidence kind agrees |
| CONDITIONAL | it holds under a declared condition and not outside it |
| WEAK | the evidence exists but leaves the claim unresolved |
| REJECTED | a measurement contradicts the claim as stated |
| UNIDENTIFIED | nothing in the project could have measured it |

## What a card is not

A card is a claim with its falsifier, not a summary of everything that could matter. A card that said its factors interacted would be refused by the schema before it was written: the fields exist to force a condition, a trigger and a chain to be named, so that a reader can check each against the artifact the card cites.
