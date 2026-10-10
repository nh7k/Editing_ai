# Video editor benchmark

Same desi prompts, same clips, edited twice: **baseline** (prompt parser only) vs **editorial brain**
(Hinglish concepts → content type → skills → inferred professional choices). Each criterion is measured on
the real render/plan. Generated test clips; mock (rules) planner; CPU only. Reproduce: `python -m cutmind.benchmark`.

| Scenario | Prompt | Baseline | Editorial brain | Reviewer match (base → brain) | Time (base → brain) | Decisions logged |
|---|---|---|---|---|---|---|
| talking_mast | bhai isko mast bana de | 80% | **100%** | 92.9 → 100.0 | 23.9s → 11.6s | 12 |
| party_reel | party ka mast energetic reel insta ke liye | 71% | **100%** | 90.5 → 100.0 | 20.8s → 14.0s | 18 |
| travel_restrained | travel vlog jaisa bana, over mat kar | 50% | **100%** | 100.0 → 100.0 | 9.5s → 13.7s | 7 |
| podcast_premium | podcast clip, premium captions, ye banda jab important baat bole tab zoom kar | 20% | **100%** | 100.0 → 100.0 | 17.7s → 12.0s | 10 |
| boring_hata | boring hata de | 50% | **100%** | 94.4 → 100.0 | 8.8s → 7.0s | 9 |
| cinematic_restrained | thoda cinematic bana, over mat kar | 100% | **100%** | 100.0 → 100.0 | 7.1s → 9.0s | 6 |

**Average professional-criteria score: 62% → 100%**

## Criteria per scenario

**talking_mast** — “bhai isko mast bana de”

| Criterion | Baseline | Brain |
|---|---|---|
| pauses removed (shorter than the source) | ✓ | ✓ |
| captions for the speech | ✓ | ✓ |
| jump cuts covered or key words punched | ✗ | ✓ |
| speech not chopped to a beat (avg shot > 1.5 s) | ✓ | ✓ |
| no template transitions | ✓ | ✓ |

**party_reel** — “party ka mast energetic reel insta ke liye”

| Criterion | Baseline | Brain |
|---|---|---|
| vertical 9:16 for Instagram | ✓ | ✓ |
| music | ✓ | ✓ |
| fast pacing (avg shot ≤ 2.5 s) | ✓ | ✓ |
| cuts on the beat | ✓ | ✓ |
| hook: opening shot is energetic | ✗ | ✓ |
| ends on a strong moment | ✗ | ✓ |
| restraint: no template transitions, ≤ 2 flashes | ✓ | ✓ |

**travel_restrained** — “travel vlog jaisa bana, over mat kar”

| Criterion | Baseline | Brain |
|---|---|---|
| music | ✗ | ✓ |
| no template transitions | ✓ | ✓ |
| restraint: at most 2 video effects | ✓ | ✓ |
| a look (graded) | ✗ | ✓ |

**podcast_premium** — “podcast clip, premium captions, ye banda jab important baat bole tab zoom kar”

| Criterion | Baseline | Brain |
|---|---|---|
| captions | ✓ | ✓ |
| premium caption style | ✗ | ✓ |
| pauses removed | ✗ | ✓ |
| punch-ins on key words | ✗ | ✓ |
| cleaner voice | ✗ | ✓ |

**boring_hata** — “boring hata de”

| Criterion | Baseline | Brain |
|---|---|---|
| dead air removed | ✗ | ✓ |
| no word cut | ✓ | ✓ |

**cinematic_restrained** — “thoda cinematic bana, over mat kar”

| Criterion | Baseline | Brain |
|---|---|---|
| cinematic grade | ✓ | ✓ |
| no template transitions | ✓ | ✓ |
| restraint: at most 2 video effects | ✓ | ✓ |
| no flashes | ✓ | ✓ |

## Limits of this benchmark

* Criteria are rules a professional editor would follow; they are not a human taste rating.
* Synthetic clips (TTS speech, test patterns) — real footage behaves differently; the user's own footage
  runs are in TEST_REPORT.md.
* The local-LLM planner was not used here (rules planner), so this isolates the editorial brain.
