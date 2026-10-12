# Changes to existing tests (each with the reason; never to make a broken behaviour pass)

| date | test | change | why |
|---|---|---|---|
| 2026-10-12 | `tests/unit/test_tier1_engine.py::test_specs_are_valid_and_complete` | 109 → 111 specs | two new skills (`beat_edit`, `talking_head_reel`); the same test also caught that both lacked a "multi" example and had invalid param types — fixed in the specs, not in the test |
| 2026-10-12 | `tests/integration/test_e2e_api.py::run_prompt` | the director `review` is optional in the results row | Phase A rule (asked for by the user): a single clear change after an edit is made by the skills, which have the production verifier instead of the director's reviewer; every measured assertion of the test (silence gone, length, decodes, size) is unchanged |
| 2026-10-12 | `tests/integration/test_nondestructive.py::test_versions_undo_redo_restore_and_explain` | "black and white" checked on the redone VIDEO (saturation < 8) and in the answer as "colour …" OR "black and white", instead of `plan.color.preset == "bw"` | the skills make black and white as a grade, the director as a preset; the user-visible outcome is identical — the new check measures the picture, which is stricter |
| 2026-10-12 | `tests/integration/test_mcp.py` | the test media folder is allowed through `CUTMIND_MCP_ALLOW` | the MCP server now reads files only from allowed folders (security fix) |
| 2026-10-12 | `tests/integration/test_comment_and_replay.py` | the vignette edit accepts decision apply OR act | both run the skills; the test is about the replay, not the confidence label |
