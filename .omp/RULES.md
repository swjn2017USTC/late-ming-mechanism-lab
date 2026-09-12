# RULES — late-ming-mechanism-lab

Hard requirements. Always in force, regardless of conversation length.
Background and rationale live in `.omp/AGENTS.md` and `docs/`.

## Epistemics

1. Simulation is an argument, not evidence.
2. Historical evidence, model assumptions, and generated results MUST NOT be silently merged.
3. No historical outcome may be encoded directly in order to reproduce history.
4. State capacity is multidimensional (tax collection, information, relief, coercion, logistics).
5. Rebellion MUST NOT be represented as a simple anger threshold.
6. Weighted household cohorts are preferred over fake household-level precision.

## Runtime LLM boundary

7. An LLM MUST NEVER determine physical or economic state directly (harvest, price, tax
   revenue, death, migration, battle outcome, recruitment counts).
8. Runtime LLM = USTC-confirmed DeepSeek V4.1 only.
9. The runtime LLM has no tools.
10. The runtime LLM never receives API credentials, filesystem, or shell access.
11. No automatic fallback from USTC V4.1 to another model. Fail closed, or switch to an
    explicitly declared rule-based policy.
12. OpenCode Go is development-only; it is never runtime simulation intelligence.
13. Tests MUST NOT require live LLM access; `@pytest.mark.live_ustc` is opt-in only.

## Provenance and reproducibility

14. Every run MUST record code/config/seed provenance.
15. Same code + same config + same seed + same policy implies the same output, except for
    live LLM decisions, whose traces MUST be recordable and replayable.

## Process and cost

16. Advisor is off by default.
17. Ordinary tasks use <= 1 subagent; complex tasks <= 2; phase gates <= 3 with
    non-overlapping roles. Never fan out agents that each read the whole repository.
18. Every phase stops after phase report + commit; never start the next phase unasked.
19. Do not expand geographical scope before the Shaanxi–Henan model is scientifically useful.
20. Do not optimize UI before mechanism validation.
21. Do not claim causal historical truth from simulation alone.

## Secrets

22. The USTC API key MUST NOT be read, printed, echoed, logged, or committed. `.env` stays
    gitignored; only `.env.example` with an empty key is tracked.
23. Runtime LLM calls are disabled by default (`USTC_LLM_ENABLED=0`) and stay disabled
    until P11.

## Engineering

24. NEVER suppress a symptom, skip a test, or special-case an input to make a check pass.
25. Prefer deleting code over adding configuration for a need that does not exist yet.
