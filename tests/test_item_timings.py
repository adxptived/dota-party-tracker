"""Средние тайминги предметов героя по сохранённым билдам пати."""
import io

from PIL import Image

from mmrbot import stats
from mmrbot.heroes_image import render_hero_image


def _b(items, times):
    return {"items": items, "item_times": times}


def test_item_timings_average_by_item_and_skip_unknown_times():
    builds = [_b([1, 2], [600, 1200]), _b([1, 3], [800, None]), _b([1], [None]), _b([2], [1000])]
    rows = stats.item_timings(builds, min_n=2)
    assert [r["item_id"] for r in rows] == [1, 2]  # предмет 3 — одно время, мало
    assert rows[0] == {"item_id": 1, "n": 2, "avg": 700.0} and rows[1]["avg"] == 1100.0


def test_item_timings_limit_and_junk():
    builds = [_b(list(range(1, 9)), [100 * i for i in range(1, 9)])] * 3 + [{"items": "x"}, {}, None]
    assert len(stats.item_timings(builds, limit=5)) == 5
    assert stats.item_timings([], limit=5) == [] and stats.item_timings(None) == []


def test_hero_card_with_timings_is_taller_and_survives_junk_icons():
    row = {"name": "Вася", "avatar": None, "games": 3, "wins": 2, "losses": 1, "winrate": 2 / 3, "kda": 2.5, "imp": 3,
           "gpm": 500}
    plain = Image.open(io.BytesIO(render_hero_image(1, "Axe", "за месяц", [row])))
    timed = Image.open(io.BytesIO(render_hero_image(
        1, "Axe", "за месяц", [row], timings=[{"item_id": 1, "n": 3, "avg": 700.0}, {"item_id": 2, "n": 2, "avg": 1500.0}],
        item_icons={1: b"junk"})))
    assert timed.width == plain.width and timed.height > plain.height
