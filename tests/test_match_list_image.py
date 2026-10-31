

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


def _png(rows, **kw):
    import io
    from PIL import Image
    from mmrbot.match_list_image import render_match_list_image
    return Image.open(io.BytesIO(render_match_list_image("t", None, rows, **kw))).convert("RGB")


def test_saved_build_is_drawn_between_kda_and_mmr():
    row = {"n": 1, "hero_id": 1, "name": "Axe", "won": True, "kills": 1, "deaths": 2, "assists": 3, "delta": 25}
    built = dict(row, items=[1, 2, 3, 4, 5, 6], neutral_item=7, double_down=True)
    plain, with_items = _png([row]), _png([built], item_icons={i: None for i in range(1, 8)})
    assert plain.tobytes() != with_items.tobytes()
    box = (820, 150, 1080, 210)  # середина строки правее K/D/A: без билда там только фон
    assert plain.crop(box).tobytes() != with_items.crop(box).tobytes()
    assert plain.crop((1180, 150, 1230, 210)).tobytes() == _png([dict(row, double_down=True)]).crop(
        (1180, 150, 1230, 210)).tobytes()  # ±MMR на месте
