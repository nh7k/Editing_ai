# Agent architecture

```
USER (chat / voice / templates / manual clicks)
  ├─ manual click ──► POST /manual ── deterministic ops on the plan ── cached cut reused ── render ── quality gate
  └─ words ──► Coach (/understand) ──► LangGraph job
        understand ── Director: Intent (rules or local LLM + guard) · memory · AgentRouter (195 roles → ~17–35)
        analyze ───── Analyzer: per-clip cache (scenes, motion curve, silences, loudness, words, beats, filming time)
                      Editorial brain: concepts → genres → platform → skills → ProfessionalEditSpec → Intent
                      Autopilot (auto edit) fills what is still open
        audio ─► cutter      color (parallel)
        effects ───── captions, text looks, timed FX, beat/emphasis punches, jump-cut cover, flashes,
                      person tracking (YOLOX-nano / YuNet) → follow crop, spotlight, labels that follow a person
        render ────── parallel segments, cached cut, libass text, music/ducking/bass/loudness
        review ────── ~35 checks on the rendered file, per-agent scores, lessons (fixable failures only)
        fix ⟲ ─────── only failing agents, stops when a retry changes nothing
        finalize ──── styled versions if asked, decisions + plan stored
```

Agents (Director, Analyzer, Audio, Cutter, Color, Effects, Reviewer) own plan sections; the 195 "specialists" are the
operations they apply, chosen by the router (AGENTS.md). Live events: LANGGRAPH.md. Tools for other AI clients:
MCP_TOOLS.md.
