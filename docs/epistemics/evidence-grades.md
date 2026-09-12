# Evidence Grades and the Parameter Ledger

Binding rules: `.omp/RULES.md` rules 2, 3, 14. Interpretation of results:
`docs/epistemics/model-epistemics.md`.

## Grades

Every parameter, rule, and initial condition carries one grade. The grade states the quality of
the evidence behind the number, not how convenient the number is.

| Grade | Meaning | Typical use |
| --- | --- | --- |
| **A** | Direct, high-quality historical evidence: a primary source or a dataset that records the quantity itself | Anchor values; constraints that must be satisfied |
| **B** | Cross-supported: several reliable sources agree | Preferred central values, with stated range |
| **C** | Derived from historical data or mature scholarship by explicit inference | Estimates, with the derivation recorded |
| **D** | Weak evidence mechanism parameter, or a plausible prior | Sensitivity analysis is mandatory for these |
| **S** | Pure model assumption | Must be labelled as such everywhere it appears; first target for Morris screening |

Rules:

- A grade must be defensible from the recorded sources, not from memory.
- Grade `S` is legitimate. Grade `S` presented as `A` is a defect.
- If two sources conflict, record both and the disagreement; do not average silently.
- Anything graded `D` or `S` is flagged for sensitivity analysis; conclusions must not depend on
  a `D`/`S` value inside a region where the evidence does not exclude alternatives.

## Parameter card

```yaml
id:
name:
definition:
unit:
mechanism:            # which model mechanism consumes it
level:                # macro | meso | local | micro
evidence_grade:       # A | B | C | D | S
central:
range:
distribution:
sources:              # source registry ids, with locators
reasoning:            # how the value was derived, especially for C/D/S
uncertainty:
sensitivity_priority: # screened with Morris, then Sobol if influential
version:
```

A parameter without a card does not enter the model. A parameter card without `sources` and
`reasoning` is incomplete for grades A–D.

## Ledger flow

```text
raw source
→ normalized evidence
→ evidence ledger
→ parameter / rule claim
→ simulation rule
```

Prohibited:

```text
paper says X  →  agent.py hardcodes X
```

Modern scholarship may propose a mechanism; the leap from claim to code must pass through the
ledger so that a later reviewer can see which quantity came from which source under which
interpretation. Evidence, assumption, and generated output are never merged into one claim.

## Reusing the earlier Academic Literature Pipeline

The registry / digest / ledger / claim-delta / human-acquisition-gate structure may be reused.
The previous project's specific historical conclusions, private PDFs, and project-specific
claims must not be copied. Every item is classified **COPY / CONFIGURE / REBUILD / DO NOT COPY**
before it enters this repository.

## Data placement

| Path | Content |
| --- | --- |
| `sources/registry/` | Source registry entries (bibliographic identity, locator, access) |
| `sources/primary/` | Primary-source material and transcriptions |
| `sources/literature/` | Literature notes; private material stays in gitignored `private/` or `inbox/` |
| `data/raw/public/` | Downloaded public datasets, unmodified |
| `data/raw/private/` | Licensed/private data (gitignored) |
| `data/normalized/` | Cleaned, harmonized, unit-consistent evidence |
| `data/parameters/` | Parameter cards produced from the ledger |
| `data/historical_patterns/` | Patterns targeted by calibration and hold-out |
| `data/scenarios/` | Scenario definitions (initial conditions, shocks, policy sets) |
| `src/late_ming_lab/evidence/` | Code: `registry.py`, `parameters.py`, `provenance.py` |

Raw data is never edited in place. Normalization is a scripted, re-runnable transformation with
recorded provenance.

## Confidence and reporting

- Values are ranges or distributions where the evidence permits, not point estimates presented
  as knowledge.
- Non-identifiability is reported, not hidden behind a default.
- Grade composition of a result is reportable: a conclusion resting mainly on `S` parameters is
  labelled as such.
- Calibration must not silently convert a grade `D`/`S` prior into an `A`-looking posterior;
  the evidence grade and the fitted posterior are recorded separately.

## Review checklist

1. Does every parameter have a card with an explicit grade?
2. Are `sources` and `reasoning` present and checkable for grades A–D?
3. Is any historical outcome encoded directly to reproduce history (grade-inflated or
   outcome-driven values)? This is a blocker.
4. Are `D`/`S` parameters screened for sensitivity before conclusions?
5. Is conflicting evidence recorded rather than averaged away?
6. Does any code claim trace to a ledger entry, rather than to a remembered conclusion?
