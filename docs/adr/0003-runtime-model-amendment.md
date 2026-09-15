# ADR 0003 — The runtime model id, amended by operator decision

Status: accepted, 2026-09-16. Amends `.omp/RULES.md` rules 8 and 12 and the model-identity clause of
`docs/architecture/runtime-llm-boundary.md`.

## Context

`.omp/RULES.md` rule 8 said the runtime institutional policy runs "USTC-confirmed DeepSeek V4.1
only", and the code carried that as an exact-match constant:

```text
src/late_ming_lab/core/config.py   RUNTIME_LLM_MODEL_ID = "ustc-deepseek-v4.1"
src/late_ming_lab/policies/ustc_v41.py   CONFIRMED_MODEL_IDS = (RUNTIME_LLM_MODEL_ID,)
src/late_ming_lab/policies/ustc_v41.py   FORBIDDEN_MODEL_MARKERS = (…, "flash", …)
```

Two things were true of that constant, and both matter:

1. **It was never a recorded confirmation.** No file in the repository holds an operator's reading of
   the account's `/v1/models`; the string appears first in P01's report and is repeated by P11. It was
   a declared placeholder, and the phases that read it (P11, V2-P08) correctly refused to call it a
   confirmation.
2. **The configured id has always been `deepseek-flash`.** P11's report and V2-P08's both record
   `USTC_LLM_MODEL=deepseek-flash` in the uncommitted `.env`, and both failed closed on it. The
   configured value and the accepted value have disagreed since P11.

On 2026-09-16 the operator instructed: keep the model id as `deepseek-flash`, treat the claim that
`ustc-deepseek-v4.1` is the only acceptable string as wrong, and open the gate. The operator chose the
option of a **constitutional amendment** over the option of reporting a `/v1/models` reading.

## Decision

The runtime institutional policy's model id is **`deepseek-flash`** at the declared USTC endpoint. It
is the operator's declaration about their own account, it is recorded here as a **decision**, and it
is **not** recorded as a verification against `/v1/models` — because no such reading was taken or
supplied.

Consequences, all implemented in the same commit:

- `RUNTIME_LLM_MODEL_ID` becomes `deepseek-flash`; `CONFIRMED_MODEL_IDS` follows it, so the
  exact-match fence still admits exactly one string and still refuses every near miss
  (`deepseek-flash-v2`, `ustc-deepseek-v4.1`, `deepseek-v4.1-pro`, …).
- `flash` leaves `FORBIDDEN_MODEL_MARKERS`. The other markers (`pro`, `qwen`, `glm`, `gpt`, `claude`,
  `opencode`, `legacy`) stay, so the named fallbacks are still refused by name. The marker fence was
  never the only fence: the exact-match confirmation check refuses anything that is not the one
  declared id.
- Rules 8 and 12 are re-worded: the runtime model is the one this ADR declares, and the ban on
  automatic fallback (rule 11) is untouched. The OpenCode Go ban on *runtime simulation intelligence*
  stays, and this ADR notes the name collision explicitly.
- The runtime settings read the repository's `.env` (process environment wins) so that the operator's
  switch is effective rather than decorative. Nothing loads `.env` today, which is why the previous
  two phases could change it with no effect.

## What this amendment does not do

- It does not claim the id was verified with the account. Every report that cites the runtime model
  must say "declared by ADR 0003" rather than "operator-confirmed", and
  `docs/architecture/runtime-llm-boundary.md` says so.
- It does not license any other model, any automatic fallback, any tool access, or any credential
  exposure. The fences the amendment does not touch are listed in the boundary document.
- It does not change any mechanism, parameter or historical claim. M2's status depends on the
  runtime arm's evidence, not on this decision.

## Reversal

Reversing this is one commit: restore the constant, restore the marker, set `USTC_LLM_ENABLED=0`, and
supersede this ADR with a new one. Nothing computed from a run depends on the id's spelling; the
decision traces record the id each decision actually came from.
