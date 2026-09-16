# Contributing

Contributions are welcome when they preserve the project's central rule: simulation results are
claims about a declared model, not evidence about the past.

## Before opening a pull request

1. Open an issue or clearly state the research question and the observable behavior being changed.
2. Keep one change scoped to one mechanism, data source, protocol rule, or engineering contract.
3. Add or update the smallest tests that defend the observable contract.
4. Run the relevant narrow tests, then `ruff check`, `ruff format --check`, and `mypy` when the change
   touches typed interfaces.
5. Record generated results from their artifact producer. Do not hand-edit a generated number.

## Historical claims and data

- A new claim must name its source, locator, read depth, evidence grade, and what parameter or rule it
  can support.
- Unknown is distinct from zero. Missing data must not silently become a negative observation.
- Do not commit restricted raw data, paywalled publications, API keys, credentials, or local `.env`
  files.
- State the licence and redistribution rule for every new data snapshot. The MIT licence does not
  cover third-party data.

## Model and experiment changes

- Keep physical and economic state transitions deterministic from their declared inputs and RNG
  streams; record every RNG draw that affects a transition.
- An intervention must have a configuration diff and a non-zero event or state path. A no-op is a
  result only when it was declared as a control.
- Do not tune against hold-out or extrapolation windows.
- Do not move a threshold, effect-size line, or convergence gate after reading the result.
- Runtime LLM access is optional, disabled by default, and never required by the offline test suite.

## Verification

```bash
uv sync --frozen
uv run late-ming-lab doctor
uv run pytest <tests related to your change>
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

If a change modifies a frozen V1/V2 artifact or generated release document, explain why and run the
corresponding release verification. Never rewrite an older result merely to make the current tree
look consistent.
