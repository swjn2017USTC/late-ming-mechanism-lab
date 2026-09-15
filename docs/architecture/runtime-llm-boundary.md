# Runtime LLM Boundary

Status: P11. The runtime policy layer exists now: `policies/base.py` (the interface, the bounded
action space, the anonymized observation, the trace schema), `policies/ustc_v41.py` (the confirmed
model gate, the OpenAI-compatible transport, the retry and 429 policy, the prompt and response
hashes), `policies/recording.py` (record → sanitize → fixture → replay), `policies/rules.py`,
`policies/utility.py` and `policies/random_policy.py` (the declared fallbacks), and
`policies/institutional.py` (the event-triggered seats and the levers a decision may reach). The
live model is still off by default and the phase's smoke run reports that its configured id was not
confirmed. This document remains the contract; where it and the code disagree, the code is wrong.

Binding rules: `.omp/RULES.md` rules 7–13 and 22–23.

## Two separated roles

| | Development-time | Runtime institutional policy |
| --- | --- | --- |
| Purpose | Write, review, and analyze code and documents | Choose among bounded policy actions inside a simulation run |
| Allowed models | OpenCode Go (`deepseek-v4.1-flash`, `mimo-v2.5`, `qwen3.8-flash`, `glm-5.3-flash`) | exactly one id, declared in `docs/adr/0003-runtime-model-amendment.md` (`deepseek-flash`) |
| Routing | `.omp/config.yml` (`modelRoles`, `task.agentModelOverrides`) | `src/late_ming_lab/policies/ustc_v41.py` (P11), never via OMP model roles |
| Default state | enabled | **disabled** (`USTC_LLM_ENABLED=0`) |
| Tools | OMP tool surface | none |

OpenCode Go is a coding provider. It is never runtime simulation intelligence, and it is never
a fallback target for the runtime policy.

## What the runtime LLM may not determine

The LLM does not own world physics. It MUST NOT produce harvest, grain price, tax revenue,
death, migration, battle outcome, or rebel recruitment counts. Those are computed by the
simulation. The LLM only selects among a bounded action space for institutional actors:

```text
central fiscal authority
Shaanxi provincial authority
Henan provincial authority
selected county authorities
selected rebel/armed-group leadership
```

Calls are event-triggered decisions, never per-agent-per-tick polling.

## Input: anonymized, no hindsight

Prompts MUST NOT contain dynastic names, reign titles, personal names, or dates that reveal
the historical outcome. Actor and region identities are opaque codes.

```text
Actor: GOV-P3

Region:
R17

Observed harvest:
-0.28

Observed tax arrears:
0.37

Military arrears:
4 months

Known armed groups:
3

Refugee inflow:
high

Available policy actions:
A. maintain extraction
B. partial remission
C. relief transfer
D. military reinforcement
E. request central aid
```

The model does not know `Ming`, `Chongzhen`, `Li Zicheng`, or `1644`.

## Output: constrained

```json
{
  "action": "PARTIAL_REMISSION",
  "intensity": 0.35,
  "priority": "STABILIZE_TAX_BASE",
  "rationale": "..."
}
```

`action`, `intensity`, and `priority` MUST pass a Pydantic schema and a bounded action space.
`rationale` is stored for explanation only and MUST NOT modify simulation state directly.
Only the simulation engine changes the world.

## No tools, no ambient access

The runtime LLM gets: structured state → API → structured action. It gets no shell, no browser,
no filesystem, no Python execution, no network tools, no MCP, no retrieval. It never receives
API credentials beyond the transport layer that calls it.

## Failure policy

- USTC V4.1 unavailable → **fail closed**, or switch to an explicitly declared rule-based
  policy. Never silently fall back.
- Forbidden fallbacks: DeepSeek V4 Pro, legacy V4 Flash, Qwen, GLM, OpenCode Go, OpenAI.
- Retry only on retryable transport errors; handle 429 explicitly; enforce timeouts.
- Model identity is validated: `USTC_LLM_MODEL` must resolve to the single declared id (ADR 0003,
  `deepseek-flash`). The declaration is an operator decision, **not** a reading taken from the
  account's `/v1/models`; reports must say "declared by ADR 0003" and may not say "confirmed". If the
  configured id is anything else — including a near miss — the policy fails closed before reading the
  credential.

## Recording and replay

Each decision trace records model id, prompt version/hash, response hash, action, intensity,
priority, and timestamps. Live responses are sanitized into fixtures so that a recorded
decision can be replayed deterministically. Decision traces are an input to provenance, not a
hidden source of state.

## Credentials

Environment surface (`.env`, gitignored; `.env.example` tracked with an empty key):

```text
USTC_LLM_BASE_URL=https://api.llm.ustc.edu.cn/v1
USTC_LLM_API_KEY=
USTC_LLM_MODEL=
USTC_LLM_ENABLED=0
```

- The API key MUST NOT be read, printed, echoed, logged, or committed.
- Only `.env.example` with an empty key is tracked.
- Tests MUST NOT require live access. Live tests carry `@pytest.mark.live_ustc` and are opt-in;
  the default suite is offline.

These two properties are enforced by `tests/invariants/test_runtime_llm_boundary.py`.

## Phase gating

P11 implements the layer. What the code does with this contract, in one paragraph: the model gate
runs *before* the credential is read; the request payload carries no `tools` key; the observation is
anonymized and audited for place, dynasty, person and date tokens; the answer is validated against
the seat's action space; every decision records the model id, the prompt hash and the response hash;
a decision's rationale is stored and never parsed; every action has a declared lever; and a failure
of any kind is recorded as a refusal and changes nothing.

The live suite is opt-in through the marker, and `pyproject.toml` now excludes it by default — which
it claimed to do before P11 and did not.
