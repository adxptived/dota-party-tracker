"""Все карточки-картинки на фейковых данных — для проверки глазами (в т.ч. в тёмной и светлой теме Telegram).

    python scripts/render_samples.py [папка]      # по умолчанию ./samples (в .gitignore)

Сети нет: иконки героев и аватары рисуются заглушками, поэтому картинки получаются и без интернета.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mmrbot.match_image import render_match_image  # noqa: E402

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


def build() -> dict[str, bytes]:
    match = sample_match()
    return {
        "match.png": render_match_image(match, {1: "Вася", 7: "Петя"}, focus=1, tz="Europe/Moscow", icons={}),
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
