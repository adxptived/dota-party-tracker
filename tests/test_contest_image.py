import io

from PIL import Image

from mmrbot import card_data as cd
from mmrbot.cards import WIDTH
from mmrbot.contest_image import MAX_NOMS, MAX_TABLE, render_contest_image


def _open(png: bytes) -> Image.Image:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(png))


def _table(n=3):
    return [{"name": f"П{i}", "avatar": None, "points": 20 - i, "golds": 3 - min(i, 3)} for i in range(n)]


def _nom(title="Наибольший GPM", anti=False, n=3):
    return {"title": title, "anti": anti,
            "entries": [{"name": f"П{i}", "avatar": None, "place": i + 1, "text": f"{600 - i * 50} GPM в среднем"}
                        for i in range(n)]}


def test_renders_png_of_card_width():
    assert _open(render_contest_image("ЗА НЕДЕЛЮ", _table(), [_nom(), _nom("Лучший винрейт")])).width == WIDTH


def test_height_grows_with_nominations_two_per_row():
    two = _open(render_contest_image("ЗА НЕДЕЛЮ", _table(), [_nom(), _nom()]))
    four = _open(render_contest_image("ЗА НЕДЕЛЮ", _table(), [_nom()] * 4))
    five = _open(render_contest_image("ЗА НЕДЕЛЮ", _table(), [_nom()] * 5))
    assert four.height > two.height + 150
    assert five.height > four.height + 150  # пятая номинация — новый ряд


def test_table_beyond_podium_adds_rows_and_is_capped():
    podium = _open(render_contest_image("ЗА НЕДЕЛЮ", _table(3), [_nom()]))
    big = _open(render_contest_image("ЗА НЕДЕЛЮ", _table(MAX_TABLE), [_nom()]))
    huge = _open(render_contest_image("ЗА НЕДЕЛЮ", _table(MAX_TABLE + 5), [_nom()]))
    assert big.height > podium.height
    assert huge.height <= big.height + 60  # лишние — одной строкой «и ещё N»


def test_nominations_are_capped():
    exact = _open(render_contest_image("ЗА НЕДЕЛЮ", _table(), [_nom()] * MAX_NOMS))
    capped = _open(render_contest_image("ЗА НЕДЕЛЮ", _table(), [_nom()] * (MAX_NOMS + 6)))
    assert capped.height == exact.height


def test_one_and_two_player_podium_and_empty_states_render():
    assert _open(render_contest_image("ЗА СУТКИ", _table(1), [_nom(n=1)])).width == WIDTH
    assert _open(render_contest_image("ЗА СУТКИ", _table(2), [_nom(n=2)])).width == WIDTH
    assert _open(render_contest_image("ЗА СУТКИ", [], [])).width == WIDTH
    assert _open(render_contest_image("ЗА СУТКИ", _table(), [], note="заметка")).width == WIDTH


def test_weird_names_and_anti_cards_render():
    weird = _table(3)
    weird[0]["name"] = "😀" * 3 + "я" * 90
    nom = _nom("Н" * 120, anti=True)
    nom["entries"][0]["text"] = "X" * 90
    assert _open(render_contest_image("ЗА МЕСЯЦ", weird, [nom, _nom()])).width == WIDTH


def test_card_data_builds_contest_view():
    standings = [
        {"key": "gpm", "emoji": "💰", "title": "Наибольший GPM", "anti": False, "entries": [
            {"player": "Вася", "place": 1, "value": 650, "text": "650 GPM в среднем"},
            {"player": "Петя", "place": 2, "value": 500, "text": "500 GPM в среднем"}]},
        {"key": "loss_streak", "emoji": "🧊", "title": "Серия поражений", "anti": True, "entries": [
            {"player": "Петя", "place": 1, "value": 4, "text": "4 подряд"}]},
    ]
    points = [{"player": "Вася", "points": 3, "golds": 1}, {"player": "Петя", "points": 2, "golds": 0}]
    table, noms = cd.contest_view(standings, points, {"Вася": "http://a"})
    assert table[0] == {"name": "Вася", "avatar": "http://a", "points": 3, "golds": 1}
    assert table[1]["avatar"] is None
    assert [n["title"] for n in noms] == ["Наибольший GPM", "Серия поражений"]
    assert noms[1]["anti"] is True and noms[0]["entries"][0]["avatar"] == "http://a"
    caption = cd.contest_caption("ЗА НЕДЕЛЮ", table, noms)
    assert "Вася" in caption and "ЗА НЕДЕЛЮ".lower() in caption.lower()
