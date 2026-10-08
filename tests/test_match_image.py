import io

from PIL import Image

from mmrbot.cards import WIDTH as WIDTH_PX
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
