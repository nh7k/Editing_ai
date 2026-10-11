# Goal loop — review and design decision (2026-10-11)

Sources: a web search (titles below) plus this project's own measurements. Where a statement is from my own
knowledge and not from a source I opened, it says so.

## What the evidence says

1. **Self-correction without outside feedback does not help, and can hurt.** Huang et al., "Large Language Models
   Cannot Self-Correct Reasoning Yet" (ICLR 2024, arXiv 2310.01798): models revising their own answer with no
   external signal did not improve, sometimes got worse; earlier positive results leaned on oracle labels.
   → The loop must be driven by **measurements of the rendered video**, never by the planner re-reading its own plan.
2. **Correction works when the feedback comes from tools.** Gou et al., "CRITIC" (ICLR 2024, arXiv 2305.11738):
   verify with external tools (search, code execution), then revise, until a stop condition. Gains shrink when the
   tool is removed. → Our "tool" is ffprobe + frame/audio measurement — deterministic and external to the planners.
3. **Optimising against a verifier finds its blind spots (Goodhart).** Reward-hacking literature (e.g. the ICLR 2026
   RLVR verifier-gaming study; a 2026 audit finding ~16 % of terminal-agent benchmark tasks hackable): an agent
   pushed against a checker satisfies the checker, not the intent; LLM judges reward length/confidence.
   → (a) no LLM judge decides "done"; (b) the checks are direction-and-tolerance measurements on the video, not
   plan fields the patcher writes; (c) a separate independent audit (the test200 judge — different code, it never
   reads the app's verifier) measures **false-done**; (d) the loop code cannot edit the verifier.
4. **Co-moving verifiers.** If the same code that writes a change also decides it worked, both drift together
   (my knowledge, standard testing practice). → `verify.py` / the loop checks import nothing from the skills; the
   test200 judge imports nothing from the app.
5. **Stopping rules / oscillation / best-so-far** (my knowledge: early stopping, hill-climbing with restarts,
   control loops with integrator wind-up): budgets must be set outside the agent; keep the best state, not the
   last; detect A→B→A flips.

## This project's real constraints (measured)

- A skill job (plan patch + render) on a 6-18 s clip: **10-25 s**; a director job **30-90 s**; 5-min video ~12 min
  (TEST_REPORT perf). Every loop round costs a render.
- Plans are non-destructive and versioned: a round = a new version; rollback = restore the best version (free).
- Skill fixes are **deterministic** (the same call on the same plan gives the same result): repeating the identical
  patch cannot help — only a **different** patch (a stronger amount, another owner skill) can.
- Phone render path: NOT TESTED; the loop runs on the server.

## Decisions (and where I disagree with the brief)

| item | brief | decision | why |
|---|---|---|---|
| controller | deterministic, no LLM | **same** | evidence 1-3 |
| what is looped on | objective checklist items | **same**; subjective words ("filmy", "viral") become chips after the loop | no honest measurement exists |
| per-round render | plan + low-res proxy, final once | **proxy only for checks that need pixels; the final render is the last round's render when it is already full size** | on 6-20 s clips a 720p render is 10-25 s and a 360p proxy saves only ~30-40 %; a separate final render would cost MORE than it saves for short clips. For clips > 60 s the proxy path is used (NOT TESTED at that length in this change). |
| stop: flat progress | two rounds without improvement | **one round without improvement** | patches are deterministic and escalate each round; a round that improved nothing means the next one would repeat a worse guess, and each round costs 10-25 s. Measured below (improvement per round). |
| stop: max rounds | 3 (4 background) | **3 interactive, 4 background** | same |
| stop: time | 90 s loop time | **90 s interactive (excluding the first render), 300 s background** | a 15 s clip round is ~15-25 s: 3 rounds fit |
| oscillation | detect | **an item that passed, failed after a later fix, and is targeted again → stop, explain** | evidence 5 |
| rollback | lower score or broken invariant | **same**; invariants: length must not change unless a length item asked it, audio present, decodes | |
| contradictions | detect | **before round 1**: two items on the same measure that cannot both pass (5 s and 60 s) → no loop, ask once | |
| "done" | all objective items pass | **same, measured by the loop verifier; the test200 judge audits it independently (false-done rate)** | evidence 3 |

## What the loop is NOT

- Not a new brain: it reuses the understanding engine to compile the checklist and the existing skills to fix items.
- Not an LLM judge. Not able to raise its own budgets. Not used on taste words.
