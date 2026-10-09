"""Замер скорости команд на синтетической БД — без сети и без Telegram.

    python scripts/bench.py [--players 8] [--matches 400] [--repeats 7]

Строит во временной папке чат с N игроками и историей матчей, отключает обновление из OpenDota
(как при «данные свежие») и гоняет сборку основных отчётов: считается время сборки из БД + рисования
картинок. Выводит p50/p95 по каждой команде — до/после оптимизаций сравниваем эти цифры.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mmrbot import service  # noqa: E402
from mmrbot.storage import Storage  # noqa: E402

CHAT_ID = 1
HEROES = (1, 2, 8, 11, 14, 19, 26, 35, 44, 74, 86, 93, 106, 114)


class OfflineOpenDota:
    """Любое обращение к сети — ошибка: бенч меряет только сборку из БД."""

    def __getattr__(self, name):
        # необязательные атрибуты и настройки, которые код читает через getattr (у бенча — умолчания)
        if name in ("health", "command_wait", "enrich_days") or name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"бенч не должен ходить в OpenDota ({name})")


def seed(storage: Storage, players: int, matches: int, seed_value: int = 1) -> None:
    rng = random.Random(seed_value)
    now = int(time.time())
    storage.get_or_create_chat(CHAT_ID)
    for n in range(players):
        player = storage.add_player(CHAT_ID, 1000 + n, f"Игрок{n + 1}", 4000 + 200 * n, now - 90 * 86_400, now - 90 * 86_400)
        storage.add_matches(player.id, [
            {
                "match_id": 7_000_000_000 + n * 100_000 + i,
                "start_time": now - int(i * 90 * 86_400 / matches) - 600,
                "player_slot": rng.choice((0, 128)),
                "radiant_win": rng.random() < 0.5,
                "lobby_type": 7,
                "kills": rng.randint(0, 20), "deaths": rng.randint(0, 14), "assists": rng.randint(0, 25),
                "hero_id": rng.choice(HEROES), "duration": rng.randint(1500, 3300),
                "gpm": rng.randint(300, 700), "xpm": rng.randint(350, 750), "party_size": rng.choice((1, 2, 3, 5)),
            }
            for i in range(matches)
        ])
        storage.touch_player(player.id, now, deep=True)


def scenarios(storage: Storage, od) -> dict:
    return {
        "/stats": lambda: service.render_board(storage, od, CHAT_ID, refresh=True),
        "/today": lambda: service.render_board(storage, od, CHAT_ID, today_only=True, refresh=True),
        "/week": lambda: service.render_period_board(storage, od, CHAT_ID, "week"),
        "/records": lambda: service.render_records_board(storage, od, CHAT_ID, "week"),
        "/compare": lambda: service.render_compare_board(storage, od, CHAT_ID),
        "/together": lambda: service.render_together_board(storage, od, CHAT_ID),
        "/heroes": lambda: service.render_heroes_board(storage, od, CHAT_ID),
        "/player": lambda: service.render_player_board(storage, od, CHAT_ID, "Игрок1"),
        "/graph": lambda: service.render_graph_board(storage, od, CHAT_ID, "week"),
    }


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


async def _noop(*args, **kwargs) -> None:
    return None


async def run_bench(players: int = 8, matches: int = 400, repeats: int = 7) -> list[tuple[str, float, float]]:
    """[(команда, p50 с, p95 с)] по порядку сценариев; первый прогон каждого — прогрев, в статистику не идёт."""
    results = []
    saved = service.refresh_only
    service.refresh_only = _noop
    try:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(str(Path(tmp) / "bench.db"))
            seed(storage, players, matches)
            for name, make in scenarios(storage, OfflineOpenDota()).items():
                await make()
                times = []
                for _ in range(repeats):
                    service._graph_cache.clear()  # меряем сборку, а не попадание в кэш картинок
                    started = time.perf_counter()
                    await make()
                    times.append(time.perf_counter() - started)
                results.append((name, statistics.median(times), percentile(times, 0.95)))
    finally:
        service.refresh_only = saved
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--players", type=int, default=8)
    parser.add_argument("--matches", type=int, default=400)
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    rows = asyncio.run(run_bench(args.players, args.matches, args.repeats))
    print(f"игроков: {args.players}, матчей на игрока: {args.matches}, прогонов: {args.repeats}")
    print(f"{'команда':<12}{'p50':>9}{'p95':>9}")
    for name, p50, p95 in rows:
        print(f"{name:<12}{p50 * 1000:>7.0f}мс{p95 * 1000:>7.0f}мс")


if __name__ == "__main__":
    main()
