"""Все карточки-картинки на фейковых данных — для проверки глазами (в т.ч. в тёмной и светлой теме Telegram).

    python scripts/render_samples.py [папка]      # по умолчанию ./samples (в .gitignore)

Сети нет: иконки героев и аватары рисуются заглушками, поэтому картинки получаются и без интернета.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mmrbot.alert_image import render_alert_image  # noqa: E402
from mmrbot.match_image import render_match_image  # noqa: E402
from mmrbot.player_image import render_player_image  # noqa: E402
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
                       imp=(i - 4) * 7, gpm=380 + i * 40, net_worth=11000 + i * 2100) for i in range(10)]
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
                "account_id": 1, "avatar": None}
        data.update(extra)
        return data
    won = kind != "loss"
    rows = [row("Вася", 12, won, 13, 3, 10, avatar="https://avatars.steamstatic.com/a.jpg"),
            row("Петя", 1, won if kind != "mixed" else False, 7, 6, 14, current_mmr=4975, streak_len=1, imp=3),
            row("Оооочень длинный ник игрока", 26, won, 2, 9, 21, current_mmr=6120, position=5, leaver_status=3)]
    return {"kind": "match", "chat_id": 1, "match_id": 7812345678, "start_time": NOW, "duration": 2280, "rows": rows,
            "shared": {"games": 5, "wins": 3, "losses": 2}, "average_rank": 55}


def sample_stats_rows() -> list[dict]:
    def row(name, mmr, delta, wins, losses, form, hero, rank_tier, rank_text, **extra):
        data = {"name": name, "avatar": None, "rank_tier": rank_tier, "rank_text": rank_text, "big": f"≈{mmr}",
                "big_color": "#e8eef5", "sub": f"{'+' if delta >= 0 else '−'}{abs(delta)} за {wins + losses} игр",
                "sub_color": "#3ddc84" if delta >= 0 else "#ff5c5c", "wins": wins, "losses": losses, "form": form,
                "hero_id": hero, "hero_note": "×12"}
        data.update(extra)
        return data
    win, lose = True, False
    return [
        row("Вася", 5420, 75, 35, 21, [win, win, lose, win, win, win, lose, win, win, win], 12, 55, "Legend 5"),
        row("Петя", 4975, -25, 20, 21, [lose, win, lose, lose, win, lose, win, lose, lose, win], 1, 43, "Archon 3"),
        row("Оооочень длинный ник игрока", 6120, 150, 60, 31, [win] * 4 + [lose], 26, 74, "Divine 4"),
        row("Макс", 3800, 0, 0, 0, [], None, None, "Без ранга", sub=None, big="≈3800"),
        row("Ира", 7210, 25, 12, 8, [win, lose, win], 35, 80, "Immortal #812", avatar="https://avatars.steamstatic.com/a.jpg"),
    ]


def build() -> dict[str, bytes]:
    match = sample_match()
    out = {
        "match.png": render_match_image(match, {1: "Вася", 7: "Петя"}, focus=1, tz="Europe/Moscow", icons={}),
    }
    for kind in ("win", "loss", "mixed"):
        out[f"alert_{kind}.png"] = render_alert_image(
            sample_alert(kind), "Europe/Moscow", icons={12: fake_photo(1, 256), 1: fake_photo(2, 256)},
            avatars={"https://avatars.steamstatic.com/a.jpg": fake_photo(7)})
    tiles = [
        {"label": "Сегодня", "value": "4 игры", "sub": "3–1 (75%) · +50", "color": "#3ddc84"},
        {"label": "За неделю", "value": "18 игр", "sub": "11–7 (61%) · +100", "color": "#e8eef5"},
        {"label": "Лидер недели", "value": "Вася", "sub": "+75 (9–3)", "color": "#f0b429"},
        {"label": "Лучшая серия", "value": "6 побед", "sub": "Вася", "color": "#e8eef5"},
    ]
    records = [
        {"label": "Макс. GPM", "value": "812 GPM", "player": "Вася", "hero_id": 12},
        {"label": "Больше всего убийств", "value": "21 убийство", "player": "Петя", "hero_id": 1},
        {"label": "Лучший IMP", "value": "IMP +64", "player": "Ира", "hero_id": 35},
    ]
    awards = [
        {"title": "Лидер недели", "player": "Вася", "detail": "+75 за неделю"},
        {"title": "Больше всех играл", "player": "Оооочень длинный ник игрока", "detail": "31 игра"},
        {"title": "Камбэк недели", "player": "Ира", "detail": "5 побед подряд"},
    ]
    icons = {12: fake_photo(1, 256), 1: fake_photo(2, 256), 26: fake_photo(5, 256)}
    avatars = {"https://avatars.steamstatic.com/a.jpg": fake_photo(7)}
    out["stats.png"] = render_stats_image(
        "Рейтинг", "оценка MMR: старт ± шаг за игру", ("СЕЗОН", "#3987e5"), sample_stats_rows(), tiles, records, awards,
        "данные обновлены 12:30", icons, avatars)
    out["stats_today.png"] = render_stats_image("Сегодня", None, None, sample_stats_rows()[:2], tiles[:2], icons=icons)
    out["stats_empty.png"] = render_stats_image("Рейтинг", None, None, [])
    out["player.png"] = render_player_image(sample_player(), icons, avatars)
    card = sample_player()
    card.update(warnings=[], steam_name=None, perf=None, streak=None, series=[], split=[], hours=None, skills=[],
                heroes=[], best_game=None, lobby_rank=None, standing=None)
    out["player_sparse.png"] = render_player_image(card)
    return out


def sample_player() -> dict:
    series = [5000, 5025, 5050, 5025, 5075, 5100, 5075, 5125, 5150, 5125, 5175, 5200, 5175, 5225, 5250, 5300, 5275, 5325, 5350, 5420]
    return {
        "name": "Вася", "steam_name": "shinoame_steam", "avatar": "https://avatars.steamstatic.com/a.jpg",
        "rank_tier": 55, "rank_text": "Legend 5", "mmr_text": "≈5420", "mmr_delta": 420, "delta_note": "за 56 игр",
        "perf": 73, "streak": ("W", 4),
        "warnings": ["Оценка MMR расходится с медалью Legend 5 — обновите стартовый: /setmmr",
                     "История матчей закрыта у OpenDota — игры могли не загрузиться, цифры неполные."],
        "tiles": [
            {"label": "Результат", "value": "35–21", "sub": "62% винрейт", "color": "#3ddc84"},
            {"label": "KDA", "value": "3.10", "sub": "8/5/11"},
            {"label": "GPM", "value": "540", "sub": "по 40 из 56"},
            {"label": "Нетворт", "value": "18.2k", "sub": "по 40 из 56"},
            {"label": "Урон по героям", "value": "21.0k", "sub": "по 40 из 56"},
            {"label": "Игр сыграно", "value": "56", "sub": "ср. 36 мин"},
        ],
        "series": series, "series_label": "Динамика ≈MMR · последние 20 игр",
        "form": [True, True, False, True, True, True, False, True, True, True],
        "split": [{"label": "Соло", "wins": 12, "losses": 8}, {"label": "В группе", "wins": 23, "losses": 13}],
        "hours": {"best": "21:00 · 70%", "worst": "03:00 · 30%"},
        "heroes": [{"hero_id": 12, "name": "Phantom Lancer", "games": 12, "wins": 8, "winrate": 8 / 12},
                   {"hero_id": 1, "name": "Anti-Mage", "games": 9, "wins": 4, "winrate": 4 / 9},
                   {"hero_id": 26, "name": "Lion", "games": 5, "wins": 1, "winrate": 0.2}],
        "best_game": {"hero_id": 12, "name": "Phantom Lancer", "kills": 20, "deaths": 2, "assists": 10, "kda": 15.0},
        "skills": [{"label": "Фарм", "pct": 0.78}, {"label": "Урон", "pct": 0.41}, {"label": "Участие в боях", "pct": 0.22},
                   {"label": "Поддержка", "pct": 0.55}],
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
