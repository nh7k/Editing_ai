# Lesson memory

* **Written** by the Director after every review round (`DirectorAgent.record`): each failed, fixable check →
  `lessons(agent, check_name, text, job_id)` with a hint (`LESSON_HINTS`) plus what happened last time.
* **Retrieved** per agent before it uses the LLM (`BaseAgent.lessons`): its newest lesson per check, filtered by
  `lesson_applies` to the checks that matter for THIS request (a duration lesson only when a length was asked,
  a captions lesson only when captions were asked, …), at most 5. Never the whole table.
* **Not written** for footage limits (nobody speaks, no person found) — they would teach the agents the wrong thing.
* Scores per check and per agent: `scores` / `agents` tables → Scoreboard screen.
* Long-term project memory (edit history, favourite look, "same as before", "in my style", conversation
  adjustments): `cutmind/memory.py`, see ../MEMORY.md.

Tested: `tests/unit/test_memory_fx.py::test_agents_only_get_lessons_relevant_to_the_request`,
`tests/integration/test_workflow.py::test_no_rerender_when_the_failure_cannot_be_fixed`.
