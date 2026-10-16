# Models and measurements

## Choosing the engineer model (2026-10-13)

A synthetic scenario sent to OpenRouter from Australia. The script that ran it is gone; its results stayed local.

21 models × 5 prompts, then 8 finalists × 4 engineer prompts × 5. First-word p50 / p90, $ per answer at ~1.3k prompt tokens:

| model | p50 | p90 | $/ans | notes |
|---|---|---|---|---|
| openai/gpt-6-luna | 1.05 | 3.1 | 0.00005 | right calls, terse/generic; reasons on strategy (2.8s) |
| anthropic/claude-haiku-5.5 | 1.10 | 3.1 | 0.0002 | right calls; one small slip (RR "pressure point") |
| z-ai/glm-5.3 | 1.27 | 2.3 | 0.0006 | most natural radio voice; occasionally invents a reason |
| moonshotai/kimi-k3 | 1.32 | 1.9 | 0.0023 | most consistent latency, adds useful context (Alonso catchable) |
| openai/gpt-6-sol | 1.41 | 3.2 | 0.0009 | solid, plain |
| anthropic/claude-sonnet-5.5 | 1.59 | 4.7 | 0.004 | best answers; best strategist note (conditional triggers, projected FR 77% by L21) |
| google/gemini-3.8-flash | 1.80 | 2.9 | 0.001 | correct, computed the FR projection |
| deepseek/deepseek-v4.1-flash | 1.20 | 11.0 | 0.0005 | flipped to "box now" 1/5, slow when it reasons — out |

Said "box now" on the strategy question (wrong given rain in ~10 laps): qwen3.8-flash, mimo-v2.6-flash, mercury-2.5, mistral-large-4. Unusably slow at low effort: mistral-large-4, nemotron-3.5-lightning, qwen3.8-flash. muse-spark needs an 18+ attestation on the OpenRouter account. Every model untangled "Sonoda" → Tsunoda from the field list. **Lesson: wrong strategy calls came from models doing their own arithmetic on raw numbers — the brief must pre-compute projections (wear at rain lap, laps to cliff, undercut delta, rejoin position).** Cost is a non-issue at these sizes (Sonnet strategist every 2 laps + Kimi engineer ≈ $0.50 a race); latency and judgement are what matter.

**On real Montreal briefs** (offline, `lat.py`-style: replay to a moment, build the brief, ask; 3 runs each): Kimi K3 1–2 s first word (provider varies: Parasail ~1 s, Wafer up to 5.7 s), grounded, one misquoted number. GLM-5.3 0.4–0.8 s and natural, but invented threats (Piastri/Alonso), brought up boxing unprompted at the SC restart, misread a trend. **Kimi stays default**; revisit GLM if latency bites.

## Radio (M3 MacBook Air, laptop mic, TV audio in the room)

Release → text on screen ~430–450 ms (STT itself 140–180 ms warm). Real speech transcribes cleanly even spoken casually with engine revs and a fish-tank pump in the background ("How are my tires looking?"). Radio edge logic (hold/toggle, post-roll re-tap, auto-close, reopen) is covered by `tests/test_radio.py`. Driver names are the expected weak spot (synthetic test: "Leclerc" → "look like", "Tsunoda" → "Sonoda") — plan: fuzzy-match against session participant names before the LLM sees it.
