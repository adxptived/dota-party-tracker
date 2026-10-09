"""График MMR: закрепление цветов за игроками, читаемость подписей, рендер разных сценариев."""
import logging

from mmrbot.charts import BG, PALETTE, _ink_on, color_slots, render_mmr_chart

NOW = 1_791_400_000


def _series(n, start=NOW - 6 * 86_400, gap=3600, pattern=(1, 1, -1)):
    total, points = 0, []
    for i in range(n):
        total += 25 * pattern[i % len(pattern)]
        points.append((start + i * gap, total))
    return points


def test_color_follows_player_not_rank():
    roster = ["Вася", "Петя", "Коля"]
    week = color_slots(["Коля", "Вася"], roster)  # Петя за неделю не играл
    month = color_slots(["Петя", "Коля", "Вася"], roster)
    assert week["Вася"] == month["Вася"] == 0
    assert week["Коля"] == month["Коля"] == 2  # выбывший из периода игрок чужой цвет не освобождает


def test_color_slots_without_roster_are_alphabetical_and_unknown_go_last():
    assert color_slots(["б", "а"]) == {"а": 0, "б": 1}
    assert color_slots(["новый", "а"], ["а"]) == {"а": 0, "новый": 1}


def test_ink_on_fill_picks_readable_text():
    assert _ink_on("#ffffff") != "#ffffff"
    assert _ink_on("#000000") == "#ffffff"
    for color in PALETTE:  # любой цвет палитры даёт читаемую подпись
        assert _ink_on(color) in {"#ffffff", BG}


def test_palette_is_eight_distinct_colors():
    assert len(PALETTE) == len(set(PALETTE)) == 8


def test_render_scenarios_produce_png_of_telegram_width():
    cases = [
        ({"Вася": _series(12)}, {}),  # один игрок: заливка, пик и просадка
        ({"Вася": _series(12), "Петя": _series(5, pattern=(-1,))}, {"since_ts": NOW - 7 * 86_400, "until_ts": NOW}),
        ({f"Игрок{i}": _series(20 + i) for i in range(10)}, {"by_games": True}),  # больше восьми — пунктир
        ({"Очень длинный ник игрока из чата": [(NOW, 0 + 25)]}, {"order": ["Очень длинный ник игрока из чата"]}),
    ]
    for series, kwargs in cases:
        png = render_mmr_chart(series, "Динамика MMR", "Europe/Moscow", **kwargs)
        assert png.startswith(b"\x89PNG")
        assert int.from_bytes(png[16:20], "big") == 1280  # ширина из заголовка PNG


def test_render_does_not_spam_font_warnings(caplog):
    with caplog.at_level(logging.WARNING, logger="matplotlib.font_manager"):
        render_mmr_chart({"Вася": _series(3)}, "t", "UTC")
    assert not [r for r in caplog.records if "not found" in r.getMessage()]


def test_render_is_safe_in_parallel_threads():
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: render_mmr_chart({"Вася": _series(8 + i)}, "t", "UTC"), range(4)))
    assert all(png.startswith(b"\x89PNG") for png in results)


def test_date_num_matches_matplotlib_for_aware_datetimes():
    """Быстрая to_x не расходится с date2num(aware-datetime) — ни до, ни после перевода часов."""
    from datetime import datetime, timezone

    import matplotlib.dates as mdates
    import pytz

    from mmrbot.charts import date_num
    for name in ("Europe/Moscow", "America/New_York", "Asia/Kolkata"):
        tz = pytz.timezone(name)
        for ts in (0, 1_700_000_000, 1_711_846_800, 1_730_000_000, 1_760_000_123.5):
            expected = mdates.date2num(datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(tz))
            assert abs(date_num(ts) - expected) < 1e-9, (name, ts)
