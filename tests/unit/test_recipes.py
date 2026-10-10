"""Style recipes: schema-valid, enough of them, consistent with the editor's own vocabulary, picked by the request."""

from cutmind import recipes


def test_recipes_are_schema_valid_and_25_plus():
    assert recipes.validate_all() == []
    assert len(recipes.recipes()) >= 25


def test_recipes_point_at_real_genres():
    import yaml

    genres = {g["id"] for g in yaml.safe_load((recipes.KNOW / "genres.yaml").read_text(encoding="utf-8"))["genres"]}
    assert {r["genre"] for r in recipes.recipes().values()} <= genres


def test_pick_by_words_then_genre():
    assert recipes.pick("podcast clip bana do")["id"] == "podcast_clip"
    assert recipes.pick("goa trip ka reel")["id"] == "travel_reel"
    assert recipes.pick("kuch accha", genres=["wedding"])["id"] == "wedding_highlight"
    assert recipes.pick("kuch accha") is None
    assert "cuts on speech" in recipes.describe(recipes.recipes()["podcast_clip"])
