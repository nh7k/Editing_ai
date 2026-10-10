# Understanding engine v2 — review before building (2026-10-10)

Sources: a web search done in this session (links at the end) plus my own knowledge, said where it applies.
Starting point: the resolver built earlier today (docs/INTENT_FAILURE_REVIEW.md, docs/INTENT_EVAL.md): held-out
top-1 85.9 %, top-3 91.8 %, 3 silent wrong edits of 85, 0 dead ends after the "never empty" fix.

## 1. What the evidence says

| question | evidence | what it means for CutMind |
|---|---|---|
| Does accuracy drop as the catalog grows? | Yes. RAG-MCP: picking 1 tool among many schemas, 13.6 % → 43.1 % with retrieval first. ToolBench (2026 cloud paper): expose-all 92.4 % at 15 tools → 78.2 % at 640; a hybrid retriever holds up best at 3,616. "How many tools should an agent see?" (2026): shorter adaptive shortlists beat a fixed 5. | Retrieval of a shortlist is the proven fix. But those are LLMs reading tool schemas. CutMind's matcher is a scorer over synonyms, not an LLM — it degrades differently (more near-duplicate synonyms, not prompt bloat). **Measure it** (Phase 7 scaling test) instead of assuming the LLM curve. |
| Code-mixed Hinglish | Parikh & Solorio 2021 (normalization + back-transliteration); synthetic noisy forms by dropping non-initial vowels and swapping phonetically close consonants (arXiv 1804.05868); noisy-channel normalizers ~78 % for Hindi words. | Our phonetic key + variant table is the same family. A synthetic variant generator (Phase 2) is cheap and well supported. A seq2seq normalizer model is not needed at this size. |
| Ask or act? | Alexa study (arXiv 2109.12451): asking about every ambiguity hurts satisfaction; ask when the hypotheses compete AND a mistake costs. 2026 benchmarks: LLM agents mostly UNDER-ask and invent missing arguments. | Your "act, show, undo" is right for cheap reversible edits — with one caveat below. |

## 2. Where I disagree with the plan (with reasons)

1. **"Always act on the best guess" has a real cost here: render time.** A wrong guess is not free — a Tier 1
   render of a 15 s clip takes 5-20 s on this laptop, a 5-minute video ~12 minutes (eval/results/perf.json), and
   the phone is NOT TESTED. Acting on a coin-flip between "take the black and white off" and "add a white flash"
   wastes that time half the time. My rule: act directly when the best reading is clearly ahead OR all readings
   are cheap and the video is short; when two different meanings are close on a long video, show the chips first
   (one tap) — never a wall of text, never more than one question. The threshold comes from the calibration
   data, not from me.
2. **16,000 skills is not the retrieval problem we have.** The catalog's variants are parameter values of ~108
   executable skills (docs/SKILL_CATALOG.md). Retrieval runs over skills, parameters are read after. I will still
   run the scaling test with synthetic skills (100 → 10,000) to show where the flat scorer breaks and whether the
   category-first route fixes it.
3. **Embedding model: reuse, don't add.** The project already ships `paraphrase-multilingual-MiniLM-L12-v2`
   (Apache-2.0, in LICENSES.md) for the phrasebook. It takes ~32 s to load and ~20-50 ms per query on CPU, so it
   can only be an optional extra signal that never blocks a request. A new model needs evidence that the token
   scorer is the bottleneck.
4. **A tiny LLM as the tie-breaker: off by default.** Measured today: the local planner model takes ~21 s per
   reading on this CPU. A tie-breaker that slow cannot sit in the request path; it can run in the background and
   only re-rank the next time.
5. **"40-50 primitives" first is too wide.** Most needed primitives already exist inside the 108 skills (grade,
   overlays, keyframes, speed, crop, text, gain). I will expose a small, tested set where an unseen request needs
   one (solid/colour screen, overlay opacity, rotate, simple keyframe), not 50 untested ones.
6. **The corpus: generated prompts flatter the system.** Prompts generated from the synonym lists test spelling
   robustness only — the matcher has seen those phrases. I report them separately from hand-written prompts; the
   headline numbers are the hand-written held-out set. Your real failed prompts would be worth more than any of
   mine.

## 3. Plan (and order)

baseline + trace tool → corpus (generated noisy variants + hand-written, held-out kept apart) → normalisation
(synthetic variant generator, number words, time words) → partial execution of multi-instruction prompts (today a
prompt with one unknown part drops the known parts — checked below) → policy (act / chips / one question,
calibrated) → relative commands ("aur thoda", "kam karo", "dobara", "wahi yahan bhi", "isko hata do") → non-edit
turns → confusability lint + scaling test (category-first route) → learning loop extras (undo / rephrase as
negative signal, decay, reset) → failure injection → real renders → docs. Checkpoints in CHANGELOG.

## Sources (web search, 2026-10-10)

- [RAG-MCP review](https://www.themoonlight.io/en/review/rag-mcp-mitigating-prompt-bloat-in-llm-tool-selection-via-retrieval-augmented-generation), [alphaxiv 2505.03275](https://www.alphaxiv.org/overview/2505.03275v1)
- [Scalable LLM Agent Tool Access in the Cloud](https://arxiv.org/pdf/2607.15593)
- [How Many Tools Should an LLM Agent See?](https://www.alphaxiv.org/abs/2605.24660.md)
- [Normalization and Back-Transliteration for Code-Switched Data (CALCS 2021)](https://aclanthology.org/2021.calcs-1.15)
- [UD parsing for Hindi-English code-switching (synthetic noisy forms)](https://arxiv.org/pdf/1804.05868)
- [Shallow parsing pipeline for Hindi-English code-mixed text](https://arxiv.org/pdf/1604.03136)
- [Deciding whether to ask clarifying questions (Alexa)](https://arxiv.org/pdf/2109.12451)
- [AgentAbstain](https://arxiv.org/pdf/2607.10059)
- `dhvani` (PyPI) came up as a Hinglish phonetic library; it is a brand-new package already marked untrusted in
  this project — idea only, not installed.
