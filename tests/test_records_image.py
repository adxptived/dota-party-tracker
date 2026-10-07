import io

from PIL import Image

from mmrbot import card_data as cd
from mmrbot.cards import WIDTH
from mmrbot.records import compute_records
from mmrbot.records_image import LIMIT, render_records_image


def _open(png: bytes) -> Image.Image:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(png))


def _tile(**extra):
    tile = {"label": "Макс. GPM", "value": "812 GPM", "player": "Вася", "hero_id": 12, "date": "11.09.25", "anti": False}
    tile.update(extra)
    return tile


def test_height_grows_with_rows_and_streak_adds_block():
    two = _open(render_records_image("за неделю", [_tile()] * 2))
    eight = _open(render_records_image("за неделю", [_tile()] * 8))
    streak = _open(render_records_image("за неделю", [_tile()] * 2, ("Вася", 7)))
    assert two.width == eight.width == streak.width == WIDTH
    assert eight.height > two.height + 2 * 120  # 8 плиток — 4 ряда против 1
    assert streak.height > two.height + 80
    short = _open(render_records_image("за неделю", [_tile()] * 2, ("Вася", 1)))
    assert short.height == two.height  # серия из одной победы — не серия


def test_empty_and_strange_data_render():
    assert _open(render_records_image("за сутки", [])).width == WIDTH
    tiles = [_tile(label="я" * 90, value="9" * 60, player="😀" * 3 + "x" * 90, date=None, hero_id=9999, anti=True), {}]
    png = render_records_image("за год", tiles, ("Ооо" * 40, 99), icons={12: b"junk"}, note="заметка")
    assert _open(png).width == WIDTH


def test_more_than_limit_is_truncated():
    many = _open(render_records_image("всё время", [_tile()] * 40))
    cap = _open(render_records_image("всё время", [_tile()] * LIMIT))
    assert many.height == cap.height


def test_record_tiles_from_compute_records():
    match = {"match_id": 1, "start_time": 1_760_000_000, "hero_id": 5, "gpm": 812, "deaths": 19, "kills": 3, "assists": 4,
             "duration": 2400, "player_slot": 0, "radiant_win": True}
    data = compute_records([("Вася", [match])])
    tiles = cd.record_tiles(data, "UTC")
    gpm = next(t for t in tiles if t["label"] == "Макс. GPM")
    assert gpm["value"] == "812 GPM" and gpm["player"] == "Вася" and gpm["hero_id"] == 5 and gpm["date"] == "09.10.25"
    assert next(t for t in tiles if t["label"] == "Больше всего смертей")["anti"] is True
    assert not next(t for t in tiles if t["label"] == "Макс. GPM")["anti"]


def test_records_caption_handles_empty_and_filled():
    assert "данных нет" in cd.records_caption({"records": []}, "week")
    data = compute_records([("Вася", [{"match_id": 1, "start_time": 1, "hero_id": 5, "kills": 12, "gpm": 600, "player_slot": 0, "radiant_win": True}])])
    caption = cd.records_caption(data, "month")
    assert "за месяц" in caption and "Вася" in caption and "12 убийств" in caption
