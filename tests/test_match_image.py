import io

from PIL import Image

from mmrbot.match_image import MATCH_WIDTH as WIDTH_PX
from mmrbot.match_image import render_match_image


def _icon(color=(200, 50, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (256, 144), color).save(buf, format="PNG")
    return buf.getvalue()


def _player(acc, radiant, hero, pos, **extra):
    row = {"account_id": acc, "name": f"p{acc}", "is_radiant": radiant, "hero_id": hero, "position": pos,
           "kills": 5, "deaths": 3, "assists": 7, "imp": 12, "gpm": 600, "xpm": 650, "net_worth": 18000,
           "hero_damage": 21000}
    row.update(extra)
    return row


def _full_match():
    players = [_player(i, i <= 5, i, (i - 1) % 5 + 1) for i in range(1, 11)]
    return {"match_id": 7812345678, "start_time": 1_700_000_000, "duration": 2280, "radiant_win": True,
            "players": players}


def _open(png: bytes) -> Image.Image:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(png))


def test_full_match_renders_png_of_telegram_width():
    match = _full_match()
    icons = {hid: _icon() for hid in range(1, 11)}
    img = _open(render_match_image(match, {1: "Вася"}, focus=1, tz="Europe/Moscow", icons=icons))
    assert img.width == WIDTH_PX
    assert 600 < img.height < 1400


def test_single_player_card_is_shorter():
    match = _full_match()
    full = _open(render_match_image(match, {}, None, "UTC", {}))
    match["players"] = match["players"][:1]
    single = _open(render_match_image(match, {1: "Вася"}, 1, "UTC", {}))
    assert single.width == WIDTH_PX and single.height < full.height / 2


def test_missing_icons_values_and_strange_names_do_not_break():
    match = _full_match()
    match["players"][0].update(name=None, account_id=None, imp=None, net_worth=None, gpm=None, position=None)
    match["players"][1].update(name="😀" * 3 + "x" * 80 + "\x00")  # эмодзи вне шрифта, длинный ник
    match["players"][2].update(hero_id=None)
    match["duration"] = None
    icons = {4: b"not a png"}  # битая иконка — заглушка
    img = _open(render_match_image(match, {}, None, "UTC", icons))
    assert img.width == WIDTH_PX


def test_tracked_row_is_highlighted():
    """Строка своего игрока подсвечена: пиксели фона строки отличаются от строки чужого."""
    match = _full_match()
    match["players"] = [_player(1, True, 1, 1), _player(2, True, 2, 2)]
    plain = _open(render_match_image(match, {}, None, "UTC", {})).convert("RGB")
    marked = _open(render_match_image(match, {1: "Вася"}, None, "UTC", {})).convert("RGB")
    assert plain.size == marked.size
    assert plain.tobytes() != marked.tobytes()


def test_every_players_build_is_drawn_in_the_row_without_growing_the_table():
    plain = render_match_image(_full_match(), {1: "Вася"}, focus=1)
    match = _full_match()
    for p in match["players"]:
        p.update(items=[1, 2, 3, 4, 5, 6], item_times=[300, 900, None, 120, 2000, 60], neutral_item=9,
                 shard=p["account_id"] % 2 == 0, shard_time=1450, scepter=p["account_id"] % 3 == 0)
    built = render_match_image(match, {1: "Вася"}, focus=1, item_icons={1: _icon(), 9: _icon((50, 200, 50))})
    assert _open(built).size == _open(plain).size  # билд лежит в строке, высота таблицы та же
    assert built != plain and built != render_match_image(match, {1: "Вася"}, focus=1)  # иконки предметов отрисованы
    match["players"][0].update(item_times=["x"], shard_time="bad", items=[1, "junk", None])
    assert _open(render_match_image(match, {1: "Вася"}, focus=1, item_icons={1: b"junk"})).width == WIDTH_PX


def test_players_without_build_keep_the_old_layout():
    match = _full_match()
    assert render_match_image(match, {}, focus=1) == render_match_image(match, {}, focus=1, item_icons={1: _icon()})


def test_tower_damage_is_shown_under_hero_damage():
    match = _full_match()
    plain = render_match_image(match, {}, focus=1)
    for p in match["players"]:
        p["tower_damage"] = 6589
    assert render_match_image(match, {}, focus=1) != plain


def test_match_image_is_wider_than_a_card_so_columns_do_not_overlap():
    from mmrbot.cards import WIDTH
    assert WIDTH_PX > WIDTH
    assert _open(render_match_image(_full_match(), {}, focus=1)).width == WIDTH_PX


def test_lone_druid_shows_both_inventories_in_a_taller_row():
    match = _full_match()
    for p in match["players"]:
        p.update(items=[1, 2, 3], item_times=[100, 200, 300])
    base = _open(render_match_image(match, {}, focus=1, item_icons={1: _icon()}))
    druid = match["players"][0]
    druid.update(hero_id=80, bear_items=[1, 2, 3, 4, 5, 6], bear_item_times=[600, 700, None, 900, 1000, 1100],
                 bear_neutral=9)
    two = _open(render_match_image(match, {}, focus=1, item_icons={1: _icon()}))
    assert two.height > base.height + 30  # у медведя своя строка предметов
    druid.update(bear_items=["x", None], bear_item_times=["bad"], bear_neutral="junk")
    assert _open(render_match_image(match, {}, focus=1, item_icons={1: b"junk"})).width == WIDTH_PX
    druid.update(bear_items=[])
    assert _open(render_match_image(match, {}, focus=1)).height == base.height  # пустой инвентарь медведя — обычная строка


def test_match_image_can_be_encoded_as_small_jpeg():
    match = _full_match()
    noisy = io.BytesIO()
    Image.effect_noise((256, 144), 80).convert("RGB").save(noisy, format="PNG")  # иконки героев — «фотографические»
    icons = {p["hero_id"]: noisy.getvalue() for p in match["players"]}
    png = render_match_image(match, {}, focus=1, icons=icons)
    jpeg = render_match_image(match, {}, focus=1, icons=icons, fmt="JPEG")
    assert jpeg[:3] == b"\xff\xd8\xff" and len(jpeg) < len(png)  # Telegram всё равно пережимает фото — шлём лёгкий файл
    img = Image.open(io.BytesIO(jpeg))
    assert img.size == _open(png).size and img.format == "JPEG"
