"""Calibration: windows, summary statistics, targets, priors, the simulator, SMC and the ensemble.

The phase's discipline is that calibration produces an **ensemble**, never a best fit: the objective
is a declared scalarisation used by the sampler, while everything reported keeps the per-target
distances, the accepted parameter draws and the failures visible.

The three windows are fixed before any fitting and are not negotiable afterwards:

```text
calibration    1625-01 to 1634-12   the only window any objective may see
hold-out       1635-01 to 1642-12   never used in an objective; used to predict and to check
extrapolation  1643-01 to 1644-12   the hard case: beyond the apparent regime
```

```text
windows.py        the three split windows, the prediction-only whole-run view, and their roles
summary_stats.py  what a run says about a window: a fixed statistic vector and a per-tick series
targets.py        the target patterns as checks, and the objective that refuses every other window
prediction.py     the reserved patterns as checks, and the posterior predictive runs
priors.py         the card range as the prior's support, and the refusal of anything else
simulator.py      one draw, one seeded sandbox run, one objective vector
smc.py            the objective as a PyMC Simulator, sampled with SMC
freeze.py         the digests that identify the frozen registry, bounds and checks
ensemble.py       the particle set, its provenance, and the identifiability reports
reports.py        the four generated documents under docs/calibration/
```
"""
