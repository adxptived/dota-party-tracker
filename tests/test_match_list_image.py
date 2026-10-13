

def test_hero_level_is_drawn_in_match_list():
    import io
    from PIL import Image
    from mmrbot.match_list_image import render_match_list_image
    row = {"n": 1, "hero_id": 1, "name": "Axe", "won": True, "kills": 1, "deaths": 2, "assists": 3}
    plain = Image.open(io.BytesIO(render_match_list_image("t", None, [row]))).convert("RGB")
    leveled = Image.open(io.BytesIO(render_match_list_image("t", None, [dict(row, level=30)]))).convert("RGB")
    assert plain.tobytes() != leveled.tobytes()


def test_dota_plus_tier_is_drawn_in_match_list():
    import io
    from PIL import Image
    from mmrbot.match_list_image import render_match_list_image
    row = {"n": 1, "hero_id": 1, "name": "Axe", "won": True, "kills": 1, "deaths": 2, "assists": 3}
    plain = Image.open(io.BytesIO(render_match_list_image("t", None, [row]))).convert("RGB")
    plus = Image.open(io.BytesIO(render_match_list_image("t", None, [dict(row, plus_xp=72050)]))).convert("RGB")
    zero = Image.open(io.BytesIO(render_match_list_image("t", None, [dict(row, plus_xp=0)]))).convert("RGB")
    assert plain.tobytes() != plus.tobytes()
    assert plain.tobytes() == zero.tobytes()  # героя не качали — значка нет
