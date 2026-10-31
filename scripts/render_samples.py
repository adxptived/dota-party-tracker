"""Все карточки-картинки на фейковых данных — для проверки глазами (в т.ч. в тёмной и светлой теме Telegram).

    python scripts/render_samples.py [папка]      # по умолчанию ./samples (в .gitignore)

Сети нет: иконки героев и аватары рисуются заглушками, поэтому картинки получаются и без интернета.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mmrbot.cards import ACCENT, FG, GOLD, LOSS, MUTED, WIN  # noqa: E402
from mmrbot.contest_image import render_contest_image  # noqa: E402
from mmrbot.alert_image import render_alert_image  # noqa: E402
from mmrbot.compare_image import render_compare_image  # noqa: E402
from mmrbot.together_image import render_together_image  # noqa: E402
from mmrbot.daily_image import render_daily_image  # noqa: E402
from mmrbot.heroes_image import render_hero_image, render_party_heroes_image, render_player_heroes_image  # noqa: E402
from mmrbot.match_image import render_match_image  # noqa: E402
from mmrbot.player_image import render_player_image  # noqa: E402
from mmrbot.records_image import render_records_image  # noqa: E402
from mmrbot.stats_image import render_stats_image  # noqa: E402

NOW = 1_760_000_000


def _player(acc, radiant, hero, pos, **extra):
    row = {"account_id": acc, "name": f"Player{acc}", "is_radiant": radiant, "hero_id": hero, "position": pos,
           "kills": 5, "deaths": 3, "assists": 7, "imp": 12, "gpm": 600, "xpm": 650, "net_worth": 18000,
           "hero_damage": 21000}
    row.update(extra)
    return row


def sample_match() -> dict:
    heroes = [1, 11, 14, 35, 44, 74, 86, 93, 106, 114]
    players = [_player(i + 1, i < 5, heroes[i], i % 5 + 1, kills=3 + i * 2, deaths=1 + (i * 3) % 9, assists=4 + i,
                       imp=(i - 4) * 7, gpm=380 + i * 40, net_worth=11000 + i * 2100,
                       hero_damage=14000 + (i * 7 % 10) * 2300) for i in range(10)]
    return {"match_id": 7812345678, "start_time": NOW, "duration": 2280, "radiant_win": True, "players": players}


def fake_photo(seed: int, size: int = 184) -> bytes:
    """Условная «фотография» для аватара/иконки: цветной градиент (в проде — настоящие картинки Steam)."""
    import io

    from PIL import Image
    img = Image.new("RGB", (size, size))
    px = img.load()
    for x in range(size):
        for y in range(size):
            px[x, y] = ((seed * 53 + x) % 256, (seed * 97 + y) % 256, (seed * 29 + (x + y) // 2) % 256)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def sample_alert(kind: str = "win") -> dict:
    def row(name, hero, won, k, d, a, **extra):
        data = {"name": name, "hero_id": hero, "kills": k, "deaths": d, "assists": a, "won": won, "step": 25,
                "current_mmr": 5420, "streak_type": "W" if won else "L", "streak_len": 4, "gpm": 640,
                "hero_damage": 31250, "position": 1, "imp": 21 if won else -14, "leaver_status": 0,
                "account_id": 1, "avatar": None, "is_radiant": won, "lane_result": 1 if won else -1}
        data.update(extra)
        return data
    won = kind != "loss"
    rows = [row("Вася", 12, won, 13, 3, 10, avatar="https://avatars.steamstatic.com/a.jpg"),
            row("Петя", 1, won if kind != "mixed" else False, 7, 6, 14, current_mmr=4975, streak_len=1, imp=3),
            row("Оооочень длинный ник игрока", 26, won, 2, 9, 21, current_mmr=6120, position=5, leaver_status=3,
                wards=18, stacks=4, hero_healing=5200, net_worth=9800)]
    return {"kind": "match", "chat_id": 1, "match_id": 7812345678, "start_time": NOW, "duration": 2280, "rows": rows,
            "score": {"radiant": 41, "dire": 27, "gold": (98400, 86000)},
            "shared": {"games": 5, "wins": 3, "losses": 2}, "average_rank": 55}


def sample_stats_rows() -> list[dict]:
    def row(name, mmr, delta, wins, losses, form, hero, rank_tier, rank_text, **extra):
        data = {"name": name, "avatar": None, "rank_tier": rank_tier, "rank_text": rank_text, "big": f"≈{mmr}",
                "big_color": FG, "sub": f"{'+' if delta >= 0 else '−'}{abs(delta)} за {wins + losses} игр",
                "sub_color": WIN if delta >= 0 else LOSS, "wins": wins, "losses": losses, "form": form,
                "hero_id": hero, "hero_note": "×12"}
        data.update(extra)
        return data
    win, lose = True, False
    return [
        row("Вася", 5420, 75, 35, 21, [win, win, lose, win, win, win, lose, win, win, win], 12, 55, "Legend 5",
            streak=("W", 3)),
        row("Петя", 4975, -25, 20, 21, [lose, win, lose, lose, win, lose, win, lose, lose, win], 1, 43, "Archon 3"),
        row("Оооочень длинный ник игрока", 6120, 150, 60, 31, [win] * 4 + [lose] * 4, 26, 74, "Divine 4",
            streak=("L", 4)),
        row("Макс", 3800, 0, 0, 0, [], None, None, "Без ранга", sub=None, big="≈3800"),
        row("Ира", 7210, 25, 12, 8, [win, lose, win], 35, 80, "Immortal #812", avatar="https://avatars.steamstatic.com/a.jpg"),
    ]


def build() -> dict[str, bytes]:
    match = sample_match()
    out = {
        "match.png": render_match_image(match, {1: "Вася", 7: "Петя"}, focus=1, tz="Europe/Moscow", icons={}),
    }
    items = {i: fake_photo(40 + i, 88) for i in range(1, 12)}
    built = sample_match()
    for i, p in enumerate(built["players"]):
        p.update(items=[1 + (i + k) % 9 for k in range(6)], item_times=[60 * (k * 6 + i) for k in range(6)],
                 neutral_item=10, shard=i % 2 == 0, scepter=i % 3 == 0, tower_damage=1200 * i)
    for p in built["players"][:6]:
        p.update(last_hits=120 + p["account_id"] * 31, denies=p["account_id"] * 2,
                 talents=[{"level": lv, "left": f"+{lv} Damage", "right": f"+{lv * 20} Health",
                           "pick": ("left", "right")[(lv // 5 + p["account_id"]) % 2] if lv < 25 else None}
                          for lv in (10, 15, 20, 25)])
    built["players"][2].update(bear_items=[1, 2, 3, 4], bear_item_times=[300, 900, 1500, 2000], bear_neutral=11)
    out["match_build.png"] = render_match_image(built, {1: "Вася", 7: "Петя"}, focus=7, tz="Europe/Moscow", icons={},
                                                item_icons=items)
    event = sample_alert("win")
    for i, row in enumerate(event["rows"]):
        row.update(items=[1 + (i + k) % 9 for k in range(6)], item_times=[60 * (k * 6 + i) for k in range(6)],
                   neutral_item=10, shard=True, shard_time=1500, scepter=i == 0, scepter_time=2100,
                   net_worth=18200 + i * 900, last_hits=312, denies=14, tower_damage=4200, rank_tier=55 - i * 10)
    out["alert_build.png"] = render_alert_image(event, "Europe/Moscow", icons={12: fake_photo(1, 256)}, item_icons=items)
    solo = {"kind": "match", "chat_id": 1, "match_id": 9042174049, "start_time": NOW, "duration": 2468,
            "average_rank": 71, "score": {"radiant": 33, "dire": 32, "gold": (60000, 76100)},
            "rows": [{"name": "genocide in hell", "hero_id": 11, "kills": 10, "deaths": 5, "assists": 12, "won": False,
                      "delta": -25, "current_mmr": 4244, "gpm": 536, "hero_damage": 21100, "net_worth": 20400,
                      "last_hits": 295, "denies": 4, "tower_damage": 1800, "rank_tier": 63, "is_radiant": True,
                      "position": 2, "imp": -6, "items": [1, 2, 3, 4, 5, 6], "neutral_item": 10,
                      "item_times": [457, 1948, 2380, 1509, 893, 1085],
                      "talents": [
                          {"level": 10, "right": "+30 Shadowraze Stack Damage", "left": "+30 Feast of Souls Attack Speed",
                           "pick": "left"},
                          {"level": 15, "right": "+1.5 Presence Armor Reduction",
                           "left": "+2 Feast of Souls Souls Collected Per Hero", "pick": "right"},
                          {"level": 20, "right": "+5 Necromastery Max Souls", "left": "+0.2s Requiem Fear per line",
                           "pick": "right"},
                          {"level": 25, "right": "Feast of Souls Grants +30% Cast Speed",
                           "left": "Shadowraze Applies Attack Damage", "pick": None}]}]}
    out["alert_solo.png"] = render_alert_image(solo, "Europe/Moscow", icons={11: fake_photo(3, 256)}, item_icons=items)
    druid = dict(solo, rows=[dict(solo["rows"][0], name="Cotara", hero_id=80, won=True, delta=25, current_mmr=3734,
                                  kills=4, deaths=9, assists=12, gpm=833, net_worth=57600, last_hits=1030, denies=4,
                                  hero_damage=33000, tower_damage=16600, position=1, rank_tier=71, level=28,
                                  items=[1, 2, 3], item_times=[620, 1340, 2400], neutral_item=10, shard=True,
                                  shard_time=1900, bear_items=[4, 5, 6, 7, 8, 9], bear_neutral=11,
                                  bear_item_times=[380, 900, 1500, 2100, 2900, 3600])])
    out["alert_bear.png"] = render_alert_image(druid, "Europe/Moscow", icons={80: fake_photo(5, 256)}, item_icons=items)
    for kind in ("win", "loss", "mixed"):
        out[f"alert_{kind}.png"] = render_alert_image(
            sample_alert(kind), "Europe/Moscow", icons={12: fake_photo(1, 256), 1: fake_photo(2, 256)},
            avatars={"https://avatars.steamstatic.com/a.jpg": fake_photo(7)})
    tiles = [
        {"label": "Сегодня", "value": "4 игры", "sub": "3–1 (75%) · +50", "color": WIN},
        {"label": "За неделю", "value": "18 игр", "sub": "11–7 (61%) · +100", "color": FG},
        {"label": "Лидер недели", "value": "Вася", "sub": "+75 (9–3)", "color": GOLD},
        {"label": "Лучшая серия", "value": "6 побед", "sub": "Вася", "color": FG},
    ]
    records = [
        {"label": "Макс. GPM", "value": "812 GPM", "player": "Вася", "hero_id": 12},
        {"label": "Больше всего убийств", "value": "21 убийство", "player": "Петя", "hero_id": 1},
        {"label": "Лучший IMP", "value": "IMP +64", "player": "Ира", "hero_id": 35},
    ]
    awards = [
        {"title": "Больше всех играл", "player": "Оооочень длинный ник игрока", "detail": "31 игра"},
        {"title": "Камбэк недели", "player": "Ира", "detail": "5 побед подряд"},
    ]
    icons = {12: fake_photo(1, 256), 1: fake_photo(2, 256), 26: fake_photo(5, 256)}
    avatars = {"https://avatars.steamstatic.com/a.jpg": fake_photo(7)}
    out["stats.png"] = render_stats_image(
        "Рейтинг", "оценка MMR: старт ± шаг за игру", ("СЕЗОН", ACCENT), sample_stats_rows(), tiles, records, awards,
        "данные обновлены 12:30", icons, avatars)
    out["stats_today.png"] = render_stats_image("Сегодня", None, None, sample_stats_rows()[:2], tiles[:2], icons=icons)
    weekly_rows = [dict(r, big="+75", sub="12 игр · KDA 3.10", sub_color=MUTED, big_color=WIN, form=[]) for r in sample_stats_rows()[:3]]
    out["weekly.png"] = render_stats_image(
        "Итоги недели", "оценка ±MMR за 7 дней", ("НЕДЕЛЯ", ACCENT), weekly_rows, tiles,
        [{"label": "Герой недели", "value": "Phantom Lancer", "player": "9 игр · 67%", "hero_id": 12}],
        awards[1:], None, icons, avatars, "±MMR")
    out["stats_empty.png"] = render_stats_image("Рейтинг", None, None, [])
    out["player.png"] = render_player_image(sample_player(), icons, avatars)
    from mmrbot.match_list_image import render_match_list_image
    page = [{"n": i + 1, "hero_id": [12, 1, 26, 35, 11][i % 5], "name": ["Phantom Lancer", "Anti-Mage", "Lion", "Sniper",
             "Shadow Fiend"][i % 5], "won": i % 3 != 1, "kills": 3 + i, "deaths": 2 + i % 4, "assists": 7 + i,
             "delta": 25 if i % 3 != 1 else -25, "double_down": i == 4, "minutes": 30 + i * 2, "when": f"{12 - i // 3:02d}.10 21:{10 + i}",
             "extra": "P1 · 612 GPM · 280 крипов", "current": i == 2} for i in range(10)]
    for i, row in enumerate(page):
        if i != 7:  # у одного матча билд не сохранён
            row.update(items=[1 + (i + k) % 9 for k in range(6 - i % 3)], neutral_item=10 if i % 4 else None)
    gear = {i: fake_photo(40 + i, 88) for i in range(1, 12)}
    out["match_list.png"] = render_match_list_image("Матчи · Вася", "матчи 1–10 из 56 · нажмите номер, чтобы открыть",
                                                    page, icons, ("СТР. 1/6", ACCENT), item_icons=gear)
    long_card = sample_player()
    long_card.update(name="Оооочень длинный ник игрока из Steam", steam_name="steam_" + "x" * 40, rank_tier=80,
                     rank_text="Immortal #1234", mmr_text="≈12345", delta_note="за 1234 игры", streak=("L", 12))
    out["player_long.png"] = render_player_image(long_card, icons, avatars)
    from mmrbot.card_data import lookup_card, lookup_matches
    raw = [{"match_id": 9_000_000_000 + i, "start_time": NOW - i * 7200, "player_slot": 0, "radiant_win": i % 3 != 1,
            "lobby_type": 7, "kills": 4 + i % 9, "deaths": 2 + i % 6, "assists": 6 + i % 11, "hero_id": [11, 1, 26][i % 3],
            "duration": 1800 + i * 60, "party_size": 1 + i % 2, "average_rank": 71} for i in range(40)]
    recent = [{"match_id": 9_000_000_000 + i, "gold_per_min": 520 + i * 7, "hero_damage": 19000 + i * 400} for i in range(20)]
    found = lookup_card(123456789, {"personaname": "genocide in hell", "rank_tier": 63,
                                     "avatarfull": "https://avatars.steamstatic.com/a.jpg"},
                        lookup_matches(raw, recent), "Europe/Moscow")
    out["player_lookup.png"] = render_player_image(found, icons, avatars)
    card = sample_player()
    card.update(warnings=[], steam_name=None, perf=None, streak=None, series=[], split=[], hours=None, skills=[],
                heroes=[], last_game=None, lobby_rank=None, standing=None)
    out["player_sparse.png"] = render_player_image(card)
    out["daily.png"] = render_daily_image(sample_daily(), icons, avatars, items)
    out.update(sample_heroes(icons, avatars))
    out.update(sample_records(icons))
    out.update(sample_charts())
    out.update(sample_party(avatars))
    out.update(sample_contest(avatars))
    return out


def sample_daily() -> dict:
    since, until = NOW - 86_400, NOW
    rows = sample_stats_rows()

    def row(base, games, wins, big, color, series, **extra):
        data = dict(base, games=games, wins=wins, losses=games - wins, big=big, big_color=color,
                    sub=f"≈{base['big'][1:]} · {games} игр" if games else "не играл", series=series)
        data.update(extra)
        return data

    def game(hours_ago, won, minutes=38):
        return {"start": until - hours_ago * 3600, "end": until - hours_ago * 3600 + minutes * 60, "won": won}
    return {
        "title": "Ежедневная сводка", "window": "Последние 24 часа · 08.10 12:00 — 09.10 12:00",
        "span": None, "badge": ("24 ЧАСА", ACCENT),
        "big": {"value": "+75", "color": WIN, "label": "оценка ±MMR пати за 24 часа", "sub": "11 игр · 64% побед"},
        "tiles": [{"label": "Игр за сутки", "value": "11", "sub": "7–4 (64%)", "color": FG},
                  {"label": "Лидер суток", "value": "Вася", "sub": "+75 (4–1)", "color": GOLD},
                  {"label": "Лучшая серия", "value": "4 победы", "sub": "Вася", "color": WIN},
                  {"label": "Вместе", "value": "4 игры", "sub": "3–1", "color": FG}],
        "rows": [row(rows[0], 5, 4, "+75", WIN, [0, 25, 50, 25, 50, 75]),
                 row(rows[2], 4, 2, "0", MUTED, [0, 25, 0, 25, 0]),
                 row(rows[1], 2, 1, "−25", LOSS, [0, -25, -50, -25]),
                 row(rows[3], 0, 0, "", MUTED, [], hero_id=None)],
        "timeline": {"since": since, "until": until,
                     "ticks": [(since + h * 3600, f"{(12 + h) % 24:02d}:00") for h in range(0, 25, 4)],
                     "lanes": [{"name": "Вася", "avatar": "https://avatars.steamstatic.com/a.jpg",
                                "games": [game(21, True), game(20, True), game(19, False), game(11, True), game(10, True, 52)]},
                               {"name": "Оооочень длинный ник игрока", "avatar": None,
                                "games": [game(21, True), game(20, True), game(13, False), game(12, False, 44)]},
                               {"name": "Петя", "avatar": None, "games": [game(19, False), game(11, True)]}]},
        "records": [{"label": "Макс. GPM", "value": "812 GPM", "player": "Вася", "hero_id": 12},
                    {"label": "Больше всего убийств", "value": "21 убийство", "player": "Петя", "hero_id": 1},
                    {"label": "Лучший IMP", "value": "IMP +64", "player": "Вася", "hero_id": 26}],
        "best_game": {"player": "Вася", "hero_id": 12, "won": True, "kills": 20, "deaths": 2, "assists": 10, "kda": "15.0",
                      "stats": [{"label": "GPM", "value": "812"}, {"label": "XPM", "value": "790"},
                                {"label": "Нетворс", "value": "31.4k"}, {"label": "Урон по героям", "value": "42.0k"},
                                {"label": "Урон по зданиям", "value": "9.8k"}, {"label": "IMP", "value": "+64"}],
                      "build": {"items": [1, 2, 3, 4, 5, 6], "item_times": [420, 900, 1260, 1620, 1980, 2200],
                                "neutral_item": 10, "shard": True, "shard_time": 1500, "scepter": True, "scepter_time": 2100}},
        "footer": "Оценка MMR: ±25 за игру · учтены игры за последние 24 часа до отправки", "note": None,
    }


def sample_charts() -> dict[str, bytes]:
    """График MMR (/graph): пати по времени и один игрок по номеру игры."""
    from mmrbot.charts import render_mmr_chart

    def walk(seed: int, games: int) -> list[tuple[int, int]]:
        total, points = 0, []
        for i in range(games):
            total += 25 if (seed * 7 + i * i * 3 + i) % 5 < 3 else -25
            points.append((NOW - 7 * 86_400 + i * 7 * 86_400 // games, total))
        return points
    series = {"Вася": walk(1, 22), "Петя": walk(2, 14), "Ира": walk(3, 18), "Макс": walk(5, 9)}
    return {"graph.png": render_mmr_chart(series, "Динамика MMR · неделя", "Europe/Moscow", NOW - 7 * 86_400, NOW,
                                          order=list(series)),
            "graph_solo.png": render_mmr_chart({"Вася": walk(1, 30)}, "Динамика MMR · Вася", "Europe/Moscow", by_games=True)}


def sample_party(avatars: dict) -> dict[str, bytes]:
    def cell(value, rank):
        return {"value": value, "rank": rank}
    rows = [
        {"name": "Вася", "avatar": "https://avatars.steamstatic.com/a.jpg", "rank_tier": 55, "rank_text": "Legend 5", "power": 0.83,
         "index_text": "83", "cells": [cell("74", 1), cell("62%", 1), cell("3.1", 2), cell("540", 1)]},
        {"name": "Петя", "avatar": None, "rank_tier": 43, "rank_text": "Archon 3", "power": 0.5, "index_text": "50",
         "cells": [cell("61", 2), cell("49%", 3), cell("3.4", 1), cell("510", 2)]},
        {"name": "Оооочень длинный ник игрока", "avatar": None, "rank_tier": 74, "rank_text": "Divine 4", "power": 0.17,
         "index_text": "17", "cells": [cell(None, None), cell("40%", 4), cell("2.0", 4), cell("390", 4)]},
        {"name": "Новичок", "avatar": None, "rank_tier": None, "rank_text": "Без ранга", "power": None, "index_text": None,
         "cells": [cell(None, None)] * 4},
    ]
    names = ["Вася", "Петя", "Оооочень длинный ник игрока", "Новичок", "Ира", "Макс"]
    players = [{"name": n, "avatar": "https://avatars.steamstatic.com/a.jpg" if i == 0 else None} for i, n in enumerate(names)]
    pairs = [{"a": 0, "b": 1, "games": 24, "wins": 15}, {"a": 0, "b": 2, "games": 9, "wins": 3}, {"a": 1, "b": 2, "games": 5, "wins": 3},
             {"a": 0, "b": 4, "games": 12, "wins": 6}, {"a": 3, "b": 5, "games": 2, "wins": 0}]
    summary = {"games": 33, "wins": 19, "losses": 14}
    duo = {"names": ("Вася", "Петя"), "games": 24, "wins": 15}
    many = [{"name": f"P{i}", "avatar": None} for i in range(11)]
    many_pairs = [{"a": i, "b": j, "games": 1 + (i * j) % 9, "wins": (i + j) % 3} for i in range(11) for j in range(i + 1, 11)]
    return {"compare.png": render_compare_image(rows, avatars, "данные обновлены 12:30"),
            "compare_empty.png": render_compare_image([]),
            "together.png": render_together_image(summary, duo, players, pairs, avatars, "данные обновлены 12:30"),
            "together_many.png": render_together_image(summary, duo, many, many_pairs),
            "together_empty.png": render_together_image({"games": 0}, None, players, [])}


def sample_records(icons: dict) -> dict[str, bytes]:
    items = [("Макс. GPM", "812 GPM", "Вася", 12, "11.09.25", False), ("Больше всего убийств", "24 убийства", "Петя", 1, "02.10.25", False),
             ("Больше всего ассистов", "31 ассист", "Оооочень длинный ник игрока", 26, "28.09.25", False),
             ("Лучший KDA", "KDA 18.5", "Вася", 35, "05.10.25", False), ("Макс. урон по героям", "58.2k урона", "Петя", 44, "01.10.25", False),
             ("Макс. урон по строениям", "21.4k урона", "Вася", 74, "30.09.25", False), ("Макс. лечение", "14.9k лечения", "Новичок", 26, "29.09.25", False),
             ("Больше всего добиваний", "612 добиваний", "Вася", 12, "03.10.25", False), ("Макс. нетворс", "41.0k золота", "Вася", 12, "03.10.25", False),
             ("Лучший IMP", "IMP +54", "Петя", 1, "06.10.25", False), ("Самая долгая игра", "74 мин", "Вася", 35, "20.09.25", False),
             ("Больше всего смертей", "19 смертей", "Новичок", 74, "07.10.25", True)]
    recs = [{"label": a, "value": b, "player": c, "hero_id": d, "date": e, "anti": f} for a, b, c, d, e, f in items]
    return {"records.png": render_records_image("за неделю", recs, ("Вася", 7), icons, "данные обновлены 12:30"),
            "records_few.png": render_records_image("за сутки", recs[:3], None, icons),
            "records_empty.png": render_records_image("за сутки", [], None)}


def sample_heroes(icons: dict, avatars: dict) -> dict[str, bytes]:
    names = {12: "Phantom Lancer", 1: "Anti-Mage", 26: "Lion", 35: "Sniper", 44: "Phantom Assassin", 74: "Invoker"}

    def hero(hid, games, wins, kda, imp, gpm):
        return {"hero_id": hid, "name": names[hid], "games": games, "wins": wins, "losses": games - wins,
                "winrate": wins / games, "kda": kda, "imp": imp, "gpm": gpm}
    rows = [hero(12, 12, 8, 4.1, 12, 610), hero(1, 9, 4, 2.8, -3, 540), hero(26, 5, 1, 2.1, -11, 380),
            hero(35, 4, 3, 3.9, 8, 520), hero(44, 3, 2, 3.3, None, None), hero(74, 2, 0, 1.4, -20, 410)]
    roles = [{"position": 1, "label": "Керри", "games": 20, "wins": 12, "losses": 8, "winrate": 0.6, "kda": 3.4},
             {"position": 2, "label": "Мид", "games": 9, "wins": 4, "losses": 5, "winrate": 4 / 9, "kda": 2.9},
             {"position": 5, "label": "Фулл-саппорт", "games": 3, "wins": 1, "losses": 2, "winrate": 1 / 3, "kda": 2.2}]
    party = [{"name": "Вася", "avatar": "https://avatars.steamstatic.com/a.jpg",
              "heroes": [{k: rows[i][k] for k in ("hero_id", "name", "games", "winrate")} for i in range(3)]},
             {"name": "Оооочень длинный ник игрока", "avatar": None,
              "heroes": [{k: rows[i][k] for k in ("hero_id", "name", "games", "winrate")} for i in range(2)]},
             {"name": "Новичок", "avatar": None, "heroes": []}]
    players = [dict(row, name=nm, avatar=av) for row, nm, av in zip(
        rows, ("Вася", "Петя", "Оооочень длинный ник игрока"), ("https://avatars.steamstatic.com/a.jpg", None, None))]
    return {
        "heroes_player.png": render_player_heroes_image("Герои · Вася", None, ("ЗА НЕДЕЛЮ", ACCENT), rows, roles, icons,
                                                         note="данные обновлены 12:30"),
        "heroes_player_empty.png": render_player_heroes_image("Герои · Вася", None, ("ЗА СУТКИ", ACCENT), []),
        "roles_player.png": render_player_heroes_image("Позиции · Вася", None, ("ВСЁ ВРЕМЯ", ACCENT), [], roles),
        "heroes_party.png": render_party_heroes_image(party, icons, avatars),
        "hero.png": render_hero_image(12, "Phantom Lancer", "за месяц", players, icons, avatars),
        "hero_empty.png": render_hero_image(12, "Phantom Lancer", "за сутки", [], icons),
    }


def sample_contest(avatars: dict) -> dict[str, bytes]:
    photo = {"https://avatars.steamstatic.com/a.jpg": fake_photo(7)}
    table = [{"name": n, "avatar": "https://avatars.steamstatic.com/a.jpg", "points": p, "golds": g}
             for n, p, g in (("Вася", 21, 5), ("Петя", 17, 3), ("Ира", 12, 2), ("Оля", 9, 1), ("Макс", 4, 0))]

    def nom(title, rows, anti=False):
        return {"title": title, "anti": anti, "entries": [
            {"name": n, "avatar": "https://avatars.steamstatic.com/a.jpg", "place": i + 1, "text": text}
            for i, (n, text) in enumerate(rows)]}

    noms = [
        nom("Больше всех поднялся", [("Вася", "+75 MMR"), ("Ира", "+50 MMR"), ("Оля", "+25 MMR")]),
        nom("Лучший винрейт", [("Вася", "71% за 14 игр"), ("Петя", "60% за 10 игр"), ("Ира", "55% за 9 игр")]),
        nom("Наибольший GPM", [("Петя", "612 GPM в среднем"), ("Вася", "590 GPM в среднем")]),
        nom("Лучшая игра", [("Ира", "16/2/18 (KDA 17.0)"), ("Вася", "12/1/9 (KDA 21.0)")]),
        nom("Больше всех просел", [("Макс", "-100 MMR"), ("Оля", "-50 MMR")], anti=True),
        nom("Больше всего смертей", [("Макс", "9.8 смертей/игра"), ("Петя", "8.0 смертей/игра")], anti=True),
    ]
    return {"contest.png": render_contest_image("ЗА НЕДЕЛЮ", table, noms, photo, "данные обновлены 12:30"),
            "contest_empty.png": render_contest_image("ЗА СУТКИ", [], [])}


def sample_player() -> dict:
    series = [5000, 5025, 5050, 5025, 5075, 5100, 5075, 5125, 5150, 5125, 5175, 5200, 5175, 5225, 5250, 5300, 5275, 5325, 5350, 5420]
    return {
        "name": "Вася", "steam_name": "shinoame_steam", "avatar": "https://avatars.steamstatic.com/a.jpg",
        "rank_tier": 55, "rank_text": "Legend 5", "mmr_text": "≈5420", "mmr_delta": 420, "delta_note": "за 56 игр",
        "perf": 73, "streak": ("W", 4),
        "warnings": ["Оценка MMR расходится с медалью Legend 5 — обновите стартовый: /setmmr",
                     "История матчей закрыта у OpenDota — игры могли не загрузиться, цифры неполные."],
        "tiles": [
            {"label": "Результат", "value": "35–21", "sub": "62% винрейт", "color": WIN},
            {"label": "KDA", "value": "3.10", "sub": "8/5/11"},
            {"label": "GPM", "value": "540", "sub": "по 40 из 56"},
            {"label": "Нетворс", "value": "18.2k", "sub": "по 40 из 56"},
            {"label": "Урон по героям", "value": "21.0k", "sub": "по 40 из 56"},
            {"label": "Позиция", "value": "Pos 3", "sub": "Оффлейн · 69% игр"},
        ],
        "series": series, "series_label": "Динамика ≈MMR · последние 20 игр",
        "form": [True, True, False, True, True, True, False, True, True, True],
        "split": [{"label": "Соло", "wins": 12, "losses": 8}, {"label": "В группе", "wins": 23, "losses": 13}],
        "facts": [("Лучшая серия", "7 побед", WIN), ("Пул героев", "23 героя", None), ("Средняя игра", "38 мин", None)],
        "heroes": [{"hero_id": 12, "name": "Phantom Lancer", "games": 12, "wins": 8, "winrate": 8 / 12, "kda": 4.1},
                   {"hero_id": 1, "name": "Anti-Mage", "games": 9, "wins": 4, "winrate": 4 / 9, "kda": 2.8},
                   {"hero_id": 26, "name": "Lion", "games": 5, "wins": 1, "winrate": 0.2, "kda": 2.1}],
        "last_game": {"hero_id": 12, "name": "Phantom Lancer", "kills": 20, "deaths": 2, "assists": 10, "kda": 15.0, "won": True,
                      "when": "09.10 11:53", "stats": [("Время", "38 мин"), ("GPM", "812"), ("Урон", "42.0k")]},
        "recent": [{"hero_id": h, "name": "", "won": w, "kills": k, "deaths": d, "assists": a, "delta": 25 if w else -25,
                    "double_down": i == 2, "minutes": 30 + i * 3, "when": f"{12 - i // 2:02d}.10"}
                   for i, (h, w, k, d, a) in enumerate([(12, True, 20, 2, 10), (1, False, 4, 9, 6), (26, True, 3, 5, 21),
                                                       (12, True, 11, 4, 9), (35, False, 6, 7, 8), (12, True, 9, 1, 14)])],
        "recent_mmr": True,
        "lobby_rank": 55, "lobby_text": "Legend 5", "standing": "#2 из 5 в чате по силе", "note": "данные обновлены 12:30",
    }


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "samples")
    out.mkdir(parents=True, exist_ok=True)
    for name, png in build().items():
        (out / name).write_bytes(png)
        print(f"{name}: {len(png) // 1024} КБ")
    print(f"Готово: {out.resolve()}")


if __name__ == "__main__":
    main()
