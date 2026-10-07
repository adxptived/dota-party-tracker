import io

from PIL import Image

from mmrbot.cards import WIDTH
from mmrbot.stats_image import render_stats_image


def _row(name="Вася", **extra):
    row = {"name": name, "avatar": None, "rank_tier": 55, "rank_text": "Legend 5", "big": "≈5420",
           "big_color": "#e8eef5", "sub": "+75 за 56 игр", "sub_color": "#3ddc84", "wins": 35, "losses": 21,
           "form": [True, False, True, True], "hero_id": 12, "hero_note": "×12"}
    row.update(extra)
    return row


def _open(png: bytes) -> Image.Image:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(png))


def test_width_and_height_grow_with_rows():
    one = _open(render_stats_image("Рейтинг", None, None, [_row()]))
    five = _open(render_stats_image("Рейтинг", None, None, [_row(f"P{i}") for i in range(5)]))
    assert one.width == five.width == WIDTH
    assert five.height > one.height + 4 * 90


def test_sections_add_height_and_empty_rows_still_render():
    base = _open(render_stats_image("Рейтинг", "под", ("СЕЗОН", "#3987e5"), [_row()]))
    tiles = [{"label": "Сегодня", "value": "4 игры", "sub": "3–1", "color": "#3ddc84"}]
    records = [{"label": "Макс. GPM", "value": "812 GPM", "player": "Вася", "hero_id": 12}]
    awards = [{"title": "Лидер недели", "player": "Вася", "detail": "+75"}]
    full = _open(render_stats_image("Рейтинг", "под", ("СЕЗОН", "#3987e5"), [_row()], tiles, records, awards, "заметка"))
    assert full.height > base.height + 200
    assert _open(render_stats_image("Рейтинг", None, None, [])).width == WIDTH


def test_missing_and_strange_data_do_not_break():
    rows = [
        _row("😀" * 3 + "x" * 90 + "\x00", wins=0, losses=0, form=[], hero_id=None, rank_tier=None, sub=None),
        _row("Без героя", hero_id=9999, rank_text=None, big=None, form=[True] * 40),
        _row(None, avatar="https://avatars.steamstatic.com/x.jpg"),
    ]
    png = render_stats_image("Рейтинг", None, None, rows, [{}], [{}], [{}], icons={12: b"junk"}, avatars={"u": b"junk"})
    assert _open(png).width == WIDTH


def test_more_than_limits_are_truncated_not_crashing():
    tiles = [{"label": f"T{i}", "value": str(i)} for i in range(9)]
    records = [{"label": f"R{i}", "value": "1", "player": "x", "hero_id": 1} for i in range(12)]
    awards = [{"title": f"A{i}", "player": "x", "detail": "d"} for i in range(12)]
    assert _open(render_stats_image("Рейтинг", None, None, [_row()], tiles, records, awards)).width == WIDTH
