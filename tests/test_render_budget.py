"""Карточки рисуются на каждую команду: рендер не должен незаметно стать медленным.

Потолок — с большим запасом (обычная карточка — 25–60 мс), чтобы тест не мигал на медленном CI,
но ловил грубый регресс: суперсэмплинг во весь холст, потерянный кэш, optimize=True у PNG.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import render_samples as samples  # noqa: E402

from mmrbot import cards  # noqa: E402
from mmrbot.alert_image import render_alert_image  # noqa: E402
from mmrbot.daily_image import render_daily_image  # noqa: E402
from mmrbot.match_image import render_match_image  # noqa: E402
from mmrbot.player_image import render_player_image  # noqa: E402
from mmrbot.stats_image import render_stats_image  # noqa: E402

BUDGET_S = 0.3

CARDS = {
    "alert": lambda: render_alert_image(samples.sample_alert("win"), "UTC"),
    "match": lambda: render_match_image(samples.sample_match(), {1: "Вася"}, focus=1),
    "stats": lambda: render_stats_image("Рейтинг", None, None, samples.sample_stats_rows()),
    "player": lambda: render_player_image(samples.sample_player()),
    "daily": lambda: render_daily_image(samples.sample_daily()),
    "contest": lambda: samples.sample_contest({}),
}


def _timed(fn) -> float:
    started = time.perf_counter()
    fn()
    return time.perf_counter() - started


@pytest.mark.parametrize("name", sorted(CARDS))
def test_card_renders_within_budget(name):
    cards.warmup()
    render = CARDS[name]
    render()  # первый проход греет кэши масок и текста — как в живом боте после старта
    best = min(_timed(render) for _ in range(3))
    assert best < BUDGET_S, f"{name}: {best * 1000:.0f} мс"
