# ADR 0002 — Military units and armed bands as declared abstractions

Status: accepted
Date: 2026-09-12
Phase: P06 (Military finance / armed organization)
Supersedes: —

## Context

The plan's M4 and M5 require the model to carry a garrison's finances and an armed band's
organization: army strength, food, pay due and received, arrears, morale, cohesion, desertion;
and for bands, size, food, arms, mobility, cohesion, local support and territorial access.

Everything that would make those two actors *decisive* rather than *modelled* is unavailable to
this phase and to the evidence base it rests on:

- **Tactics, orders of battle and command.** No source in the parameter ledger gives a monthly
  combat outcome, and no evidence in scope would survive being encoded as one. A rule that
  decided battles would be a historical claim disguised as a model rule.
- **Named leaders and named bands.** The plan forbids it, and for good reason: naming Li Zicheng
  would smuggle in an outcome — the organization that *did* consolidate — and make every
  counterfactual a rewrite of the biography.
- **Household-level military service.** Who served, for how long, and with what equipment is
  not measured at cohort resolution in the evidence the project intends to use.
- **Garrison rosters.** Actual strengths, pay rates and grain issues per county are, at best,
  documentary fragments; they are a job for the parameter registry (P08), not for this phase.

At the same time, a mechanism laboratory whose armies do nothing is useless: if desertion cannot
move a household, and a band cannot take grain, then M4 and M5 connect to nothing and the
integrated crisis engine of P07 would be built on sand.

## Decision

1. **Two actor types, no more.** `GovernmentMilitaryUnit` (strength, grain, pay arrears, morale,
   cohesion) and `ArmedBand` (size, food, arms, mobility, cohesion, network, territorial access).
   Both are `LedgerAgent`s: their balances move only through `_apply`, so every change is logged
   with the ledger delta that explains it.
2. **Every rule is a declared arithmetic relation over measured quantities**, in the spirit of
   "simulation is an argument, not evidence": pay due is strength times a monthly rate; desertion
   rises with *this month's* unpaid share, this month's ration shortfall and fallen morale;
   suppression reach is garrison strength times an effectiveness, discounted by the band's local
   support and by how well it is armed; a band takes grain up to a declared multiple of its own
   monthly need; a band moves when it is hungry or when the local garrison could remove a declared
   share of its people. No rule reads a map of forts, passes or armies, and none models a tactic.
3. **Consolidation is observed, never named.** Bands form from unorganized deserters or from
   distress-driven levies, grow by recruitment, fracture when they grow faster than they cohere,
   and merge when cohesive bands meet. The phase measures the *number* of bands and the *largest
   band's share* of all armed men; it does not label any of them an insurgency.
4. **People, food and war material are conserved, on both sides of every movement.** A recruit
   leaves a cohort's adult balance and appears in a unit or band; a deserter leaves a unit and goes
   home, to the unorganized pool, or out of the modelled population; a raid credits the band and
   debits the households, the elite house and the granary by exactly the same grain; a split or
   merge moves troops, grain and arms without creating any. The only sink is a logged dispersal.
5. **A band is created empty and filled by a logged inflow.** No constructor injects members
   off the books; formations, splits and merges all pass through `ArmedBand.adopt` or
   `gain_members`.
6. **The two recruiters read the same households differently, on purpose.** The garrison levies
   from all adults at its node — conscription in this model is an obligation — and a band levies
   only from the distress-eligible ones, because band recruitment is a response to hunger.
7. **Military finance is opt-in.** P03–P05 measurements were made without garrisons; the
   military systems ship off unless a run asks for them, so those recorded results stay exactly
   what they were.

## Consequences

- The model can show the *fiscal-military* loop closing — arrears to desertion, deserters to
  bands, bands to raids, raids to household grain loss, and taxation competing with pay and
  rations for the same treasury and granary — without asserting any historical outcome.
- The measured quantities this phase produces (desertion rate, band count, largest-band share,
  band size distribution, raid burden) are **inputs to later interpretation**, not findings. Any
  claim that unpaid soldiers became rebels in 1630s Shaanxi must come from the historical side of
  the project, with the counterfactuals and sensitivity evidence P10 and P13 require.
- The abstractions are visible and replaceable: parameter sets are versioned and provenance-graded
  (`S` throughout in P06), so P08 can substitute sourced pay rates, ration scales and band sizes
  without touching a rule.
- Every default value here is an assumption. The phase report states which ones the reported
  surface is sensitive to, and the experiment sweeps the three levers the mechanism actually has
  (the claim, the county's willingness to pay, and the climate) rather than presenting one
  calibration as *the* answer.
