# P12 robustness: the same world under four decision policies

Artifacts: `p12-robustness`. 3 arms ran with 6 replicates each over 240 ticks, and a 3 by 3 grid of fiscal pressure against climate severity with 2 replicates per cell.

Every arm runs the same configuration, the same parameter values and the same random
numbers: replicate *r* of every policy starts from root seed `base_seed + r`. A
difference between arms at the same replicate is the decision policy and nothing else.

## The arms

| policy | status | decisions | replicates | reason if refused |
| --- | --- | --- | --- | --- |
| `rule` | ran | 68 | 6 | — |
| `utility` | ran | 59 | 6 | — |
| `random` | ran | 63 | 6 | — |
| `ustc` | refused | 0 | 0 | USTC_LLM_MODEL='' is not a confirmed runtime model. Confirmed: ustc-deepseek-v4.1. There is no fallback from here: this layer never calls a model whose id carries pro, flash, qwen, glm, gpt, claude, opencode, legacy. |

## The robustness matrix

A cell is the share of that arm's replicates in which the mechanism is present. An
em dash means the arm did not run: nothing is imputed for it.

| mechanism | rule | utility | random | ustc |
| --- | --- | --- | --- | --- |
| fiscal-extraction-inversion | 0 | 1 | 0.3333 | — |
| fiscal-military-ratchet | 0 | 0 | 0 | — |
| armed-band-consolidation | 0.8333 | 0.8333 | 0.8333 | — |

Verdict rules, declared before the runs: a policy *shows* a mechanism when half its
replicates or more have it; *robust* when three or more arms show it, *mixed* at two,
*model-dependent* when the runtime arm is the only one that shows it, *policy-dependent*
when a single declared policy is, and *absent* when none does. The verdicts cover the
arms that ran; where the runtime arm did not, nothing is imputed for it.

| mechanism | arms_showing | arms_ran | showing_policies | verdict |
| --- | --- | --- | --- | --- |
| fiscal-extraction-inversion | 1 | 3 | utility | policy-dependent |
| fiscal-military-ratchet | 0 | 3 |  | absent |
| armed-band-consolidation | 3 | 3 | rule,utility,random | robust |

## The five questions

### 1 and 2. Extraction inversion and the fiscal-military ratchet

Both are read off the same arms as everything else. What the matrix says, in words:

| mechanism | policy | status | present_share | median_strength |
| --- | --- | --- | --- | --- |
| fiscal-extraction-inversion | rule | ran | 0 | 0 |
| fiscal-military-ratchet | rule | ran | 0 | 0.07802 |
| armed-band-consolidation | rule | ran | 0.8333 | 0.1185 |
| fiscal-extraction-inversion | utility | ran | 1 | 0.1804 |
| fiscal-military-ratchet | utility | ran | 0 | 0.04341 |
| armed-band-consolidation | utility | ran | 0.8333 | 0.1464 |
| fiscal-extraction-inversion | random | ran | 0.3333 | 0 |
| fiscal-military-ratchet | random | ran | 0 | 0.07566 |
| armed-band-consolidation | random | ran | 0.8333 | 0.123 |
| fiscal-extraction-inversion | ustc | refused | — | — |
| fiscal-military-ratchet | ustc | refused | — | — |
| armed-band-consolidation | ustc | refused | — | — |

### 3. Does the crisis tipping region move?

The grid varies fiscal pressure and climate severity and reads the crisis off the
governance line count and the breakdown indicator, per cell and per policy.

| policy | nominal_pressure | severity_floor | mean_crossed | breakdown_share | median_band_share | runs |
| --- | --- | --- | --- | --- | --- | --- |
| random | 0.01 | 0.3 | 5.5 | 0.5 | 0.3859 | 2 |
| random | 0.01 | 0.6 | 5 | 0 | 0.3845 | 2 |
| random | 0.01 | 0.9 | 6 | 1 | 0.3936 | 2 |
| random | 0.02 | 0.3 | 5.5 | 0.5 | 0.3764 | 2 |
| random | 0.02 | 0.6 | 5 | 0 | 0.3892 | 2 |
| random | 0.02 | 0.9 | 6.5 | 1 | 0.3471 | 2 |
| random | 0.04 | 0.3 | 5.5 | 1 | 0.6301 | 2 |
| random | 0.04 | 0.6 | 5 | 0 | 0.5865 | 2 |
| random | 0.04 | 0.9 | 6 | 1 | 1 | 2 |
| rule | 0.01 | 0.3 | 5.5 | 0.5 | 0.3893 | 2 |
| rule | 0.01 | 0.6 | 5 | 0 | 0.3859 | 2 |
| rule | 0.01 | 0.9 | 6.5 | 1 | 0.3936 | 2 |
| rule | 0.02 | 0.3 | 5.5 | 0.5 | 0.3837 | 2 |
| rule | 0.02 | 0.6 | 5 | 0 | 0.3796 | 2 |
| rule | 0.02 | 0.9 | 6.5 | 1 | 0.3469 | 2 |
| rule | 0.04 | 0.3 | 6 | 0.5 | 0.621 | 2 |
| rule | 0.04 | 0.6 | 5.5 | 0.5 | 0.5671 | 2 |
| rule | 0.04 | 0.9 | 6 | 1 | 1 | 2 |
| utility | 0.01 | 0.3 | 5 | 0 | 0.402 | 2 |
| utility | 0.01 | 0.6 | 5 | 0 | 0.3955 | 2 |
| utility | 0.01 | 0.9 | 5.5 | 1 | 0.394 | 2 |
| utility | 0.02 | 0.3 | 4.5 | 0 | 0.4307 | 2 |
| utility | 0.02 | 0.6 | 4.5 | 0 | 0.4095 | 2 |
| utility | 0.02 | 0.9 | 5.5 | 0.5 | 0.3525 | 2 |
| utility | 0.04 | 0.3 | 6 | 0.5 | 0.6953 | 2 |
| utility | 0.04 | 0.6 | 5.5 | 0.5 | 0.5853 | 2 |
| utility | 0.04 | 0.9 | 6 | 0.5 | 1 | 2 |

Cells where any run breaks down, and whether they match the reference arm's cells:

| policy | cells_with_breakdown | same_as_reference | cells |
| --- | --- | --- | --- |
| utility | 5 | False | 0.01x0.9,0.02x0.9,0.04x0.3,0.04x0.6,0.04x0.9 |
| random | 6 | False | 0.01x0.3,0.01x0.9,0.02x0.3,0.02x0.9,0.04x0.3,0.04x0.9 |
| rule | 7 | True | 0.01x0.3,0.01x0.9,0.02x0.3,0.02x0.9,0.04x0.3,0.04x0.6,0.04x0.9 |

### 4. Does armed-band consolidation depend on the model?

The band mechanism's row in the matrix answers this directly. It is shown by the arms
that showed it, and the verdict is *model-dependent* only when the arm that showed it is
the runtime one; a mechanism a single declared policy shows is *policy-dependent*.

### 5. Levels or mechanisms?

Paired level differences against the reference arm, on the same replicates:

| metric | baseline | arm | replicates | baseline_median | baseline_q1 | baseline_q3 | arm_median | arm_q1 | arm_q3 | median_difference | difference_low | difference_high | share_increase | cliffs_delta | direction |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| indicators_crossed_end | rule | utility | 6 | 5 | 5 | 5 | 4.5 | 4 | 5 | -0.5 | -1 | 0 | 0 | -0.4167 | unresolved |
| breakdown | rule | utility | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | unresolved |
| receipts_over_quota_total | rule | utility | 6 | 0.2 | 0.1775 | 0.224 | 0.2808 | 0.2723 | 0.3159 | 0.07772 | 0.03701 | 0.1013 | 1 | 0.7222 | up |
| tax_base_change_mu | rule | utility | 6 | -1.359e+04 | -1.63e+04 | -1.122e+04 | -1.344e+04 | -1.579e+04 | -1.116e+04 | 942.2 | -1821 | 3513 | 0.6667 | 0.1111 | unresolved |
| military_pay_arrears_end_tael | rule | utility | 6 | 2.388e+04 | 1.872e+04 | 2.645e+04 | 1.771e+04 | 1.363e+04 | 2.132e+04 | -3109 | -9024 | -178.8 | 0 | -0.6111 | down |
| largest_band_share_max | rule | utility | 6 | 0.3829 | 0.3669 | 0.394 | 0.424 | 0.382 | 0.4442 | 0.0226 | 0.004793 | 0.052 | 0.8333 | 0.3056 | up |
| bands_at_end | rule | utility | 6 | 4 | 4 | 4 | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 0 | unresolved |
| households_exited | rule | utility | 6 | 0 | 0 | 138.6 | 0 | 0 | 0 | 0 | -166.1 | 0 | 0 | -0.1667 | unresolved |
| market_active_link_share | rule | utility | 6 | 1 | 0.875 | 1 | 1 | 0.875 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |
| indicators_crossed_end | rule | random | 6 | 5 | 5 | 5 | 5 | 5 | 5 | 0 | -0.5 | 0 | 0 | -0.1389 | unresolved |
| breakdown | rule | random | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | unresolved |
| receipts_over_quota_total | rule | random | 6 | 0.2 | 0.1775 | 0.224 | 0.2 | 0.1849 | 0.2152 | 0.007957 | -0.04744 | 0.04044 | 0.5 | 0 | unresolved |
| tax_base_change_mu | rule | random | 6 | -1.359e+04 | -1.63e+04 | -1.122e+04 | -1.583e+04 | -1.884e+04 | -1.11e+04 | -282.4 | -3302 | 2229 | 0.5 | 0 | unresolved |
| military_pay_arrears_end_tael | rule | random | 6 | 2.388e+04 | 1.872e+04 | 2.645e+04 | 2.568e+04 | 1.877e+04 | 2.748e+04 | -918.5 | -7224 | 9952 | 0.3333 | 0.1667 | unresolved |
| largest_band_share_max | rule | random | 6 | 0.3829 | 0.3669 | 0.394 | 0.389 | 0.3697 | 0.4086 | 0.005654 | 0.0008184 | 0.01198 | 0.8333 | 0.1944 | up |
| bands_at_end | rule | random | 6 | 4 | 4 | 4 | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 0 | unresolved |
| households_exited | rule | random | 6 | 0 | 0 | 138.6 | 0 | 0 | 46.51 | 0 | -161.5 | 31.01 | 0.1667 | -0.05556 | unresolved |
| market_active_link_share | rule | random | 6 | 1 | 0.875 | 1 | 1 | 0.875 | 1 | 0 | 0 | 0 | 0 | 0 | unresolved |

Reading the two tables together is the phase's answer. Where the mechanism rows agree
across arms while the level rows move, the policy changed *how much*. Where a mechanism
row itself changes across arms, the policy changed *what the model does* — and that is a
claim about the decision rule, not about history.

## What this cannot say

- **The runtime arm did not run.** 1 arm(s) were refused by the model gate: `ustc`: USTC_LLM_MODEL='' is not a confirmed runtime model. Confirmed: ustc-deepseek-v4.1. There is no fallback from here: this layer never calls a model whose id carries pro, flash, qwen, glm, gpt, claude, opencode, legacy.

  The configured runtime model id is not the operator-confirmed one, so no live call was
  made and no conclusion is drawn about a model-backed policy. A mechanism no arm
  showed is *not* evidence an LLM-backed policy would not show it: it is a statement
  about the three declared policies that ran.
- **190 decisions** across every arm: not a large decision experiment, and the seats are a handful.
- **The grid is 2 replicates per cell per arm**, so a breakdown share there is a coarse reading of where the region is, not a probability.
- **The mechanisms are the three P12 declared**: extraction inversion, the
  fiscal-military ratchet and band consolidation. Nothing else was looked for.
