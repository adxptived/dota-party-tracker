"""Отличия участников за период (чистые функции, без сети и БД).

compute_period_awards([(имя, матчи за период)], step) → список {key, emoji, title, player, detail}.
Считаем только по матчам выбранного периода (сутки/неделя), а не по всей истории: иначе «отличия»
в ежедневной сводке не отражали бы сам день. Отличие имеет смысл только как сравнение: нужны минимум
двое игроков с данными по метрике и различающиеся значения (при равенстве награду не выдаём).
"""
from __future__ import annotations

from typing import Callable, Optional

from mmrbot.stats import is_win, longest_win_streak, mmr_delta


def _games(n: int) -> str:
    """«1 игра», «2 игры», «21 игра», «11 игр»."""
    n10, n100 = n % 10, n % 100
    word = "игра" if n10 == 1 and n100 != 11 else "игры" if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else "игр"
    return f"{n} {word}"


def _mean(values: list) -> Optional[float]:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _longest_loss_streak(matches: list[dict]) -> int:
    longest = current = 0
    for match in matches:
        if is_win(match["player_slot"], match["radiant_win"]):
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def _kda(match: dict) -> Optional[float]:
    kills, deaths, assists = match.get("kills") or 0, match.get("deaths") or 0, match.get("assists") or 0
    if kills + assists < 10:  # без порога «0 смертей, 2 помощи» стало бы лучшей игрой
        return None
    return (kills + assists) / max(deaths, 1)


def compute_standings(
    named_matches: list[tuple[str, list[dict]]], step: int = 25, min_games: int = 3, top: int = 3
) -> list[dict]:
    """Соревнование за период: по каждой номинации топ-`top` участников.

    → [{key, emoji, title, anti, entries: [{player, place, value, text}]}], entries от лучшего к худшему
    (у антирекордов «лучший» — самый антигеройский). Места делят при равенстве значений (1, 2, 2, 4).
    min_games — порог игр у игрока для метрик-средних (винрейт, GPM, урон…); сравнивать нужно минимум двоих
    с разными значениями, иначе номинации нет.
    """
    players = {name: sorted(ms, key=lambda m: m["start_time"]) for name, ms in named_matches if ms}
    standings: list[dict] = []

    def add(key: str, emoji: str, title: str, values: dict[str, float], detail: Callable[[str], str],
            lowest: bool = False, floor: float = 0, anti: bool = False, keep: Callable[[float], bool] = None) -> None:
        if len(values) < 2:  # сравнивать не с кем
            return
        if max(values.values()) == min(values.values()):  # у всех одинаково — отличия нет
            return
        ordered = sorted(values.items(), key=lambda kv: kv[1] if lowest else -kv[1])
        shown = [(n, v) for n, v in ordered if (v >= floor or lowest) and (keep is None or keep(v))]  # порог значимости
        if not shown:
            return
        entries, place = [], 1
        for i, (name, value) in enumerate(shown[:top]):
            if i and value != shown[i - 1][1]:
                place = i + 1
            entries.append({"player": name, "place": place, "value": value, "text": detail(name)})
        standings.append({"key": key, "emoji": emoji, "title": title, "anti": anti, "entries": entries})

    played = {n: ms for n, ms in players.items() if len(ms) >= 1}
    regular = {n: ms for n, ms in played.items() if len(ms) >= min_games}

    deltas = {n: mmr_delta(ms, step) for n, ms in played.items()}
    add("climb", "🚀", "Больше всех поднялся", deltas, lambda n: f"{deltas[n]:+d} MMR", keep=lambda v: v > 0)
    add("drop", "📉", "Больше всех просел", deltas, lambda n: f"{deltas[n]:+d} MMR", lowest=True, anti=True,
        keep=lambda v: v < 0)

    add("games", "🕹️", "Больше всех играл", {n: len(ms) for n, ms in played.items()},
        lambda n: _games(len(played[n])))

    winrates = {n: sum(is_win(m["player_slot"], m["radiant_win"]) for m in ms) / len(ms) for n, ms in regular.items()}
    add("winrate", "👑", "Лучший винрейт", winrates,
        lambda n: f"{winrates[n] * 100:.0f}% за {_games(len(regular[n]))}")

    def averages(field: str) -> dict[str, float]:
        result = {}
        for n, ms in regular.items():
            mean = _mean([m.get(field) for m in ms])
            if mean is not None:
                result[n] = mean
        return result

    perf = averages("perf_score")
    add("perf", "⭐", "Лучший перф", perf, lambda n: f"{perf[n] * 100:.0f}/100")
    gpm = averages("gpm")
    add("gpm", "💰", "Наибольший GPM", gpm, lambda n: f"{gpm[n]:.0f} GPM в среднем")
    damage = averages("hero_damage")
    add("damage", "💥", "Наибольший урон по героям", damage, lambda n: f"{damage[n] / 1000:.1f}k урона/игра")
    assists = averages("assists")
    add("assists", "🤝", "Больше всего ассистов", assists, lambda n: f"{assists[n]:.1f} ассистов/игра")

    best_games: dict[str, tuple[float, dict]] = {}
    for n, ms in played.items():
        scored = [(k, m) for m in ms if (k := _kda(m)) is not None]
        if scored:
            best_games[n] = max(scored, key=lambda x: x[0])
    add("best_game", "🎯", "Лучшая игра", {n: v[0] for n, v in best_games.items()},
        lambda n: "{}/{}/{} (KDA {:.1f})".format(
            best_games[n][1].get("kills") or 0, best_games[n][1].get("deaths") or 0,
            best_games[n][1].get("assists") or 0, best_games[n][0]))

    streaks = {n: longest_win_streak(ms) for n, ms in played.items()}
    add("win_streak", "🔥", "Лучшая серия побед", streaks, lambda n: f"{streaks[n]} подряд", floor=2)

    deaths = averages("deaths")
    add("deaths", "💀", "Больше всего смертей", deaths, lambda n: f"{deaths[n]:.1f} смертей/игра", anti=True)

    loss = {n: _longest_loss_streak(ms) for n, ms in played.items()}
    add("loss_streak", "🧊", "Серия поражений", loss, lambda n: f"{loss[n]} подряд", floor=3, anti=True)
    return standings


POINTS_BY_PLACE = {1: 3, 2: 2, 3: 1}


def contest_points(standings: list[dict]) -> list[dict]:
    """Общий зачёт: 3/2/1 очка за 1/2/3 место в обычных номинациях (антирекорды очков не дают).

    → [{player, points, golds}] от лидера; при равенстве очков выше тот, у кого больше первых мест.
    """
    table: dict[str, dict] = {}
    for standing in standings:
        for entry in standing["entries"]:
            row = table.setdefault(entry["player"], {"player": entry["player"], "points": 0, "golds": 0})
            if standing["anti"]:
                continue
            row["points"] += POINTS_BY_PLACE.get(entry["place"], 0)
            row["golds"] += entry["place"] == 1
    return sorted(table.values(), key=lambda r: (-r["points"], -r["golds"], r["player"]))


def compute_period_awards(
    named_matches: list[tuple[str, list[dict]]], step: int = 25, min_games: int = 3
) -> list[dict]:
    """Награды за период — единственный лидер каждой номинации (при делёже первого места награды нет)."""
    awards = []
    for standing in compute_standings(named_matches, step, min_games, top=2):
        first, rest = standing["entries"][0], standing["entries"][1:]
        if rest and rest[0]["place"] == 1:
            continue
        awards.append({"key": standing["key"], "emoji": standing["emoji"], "title": standing["title"],
                       "player": first["player"], "detail": first["text"]})
    return awards


def current_leaders(standings: list[dict]) -> dict[str, str]:
    """{номинация: единственный лидер} — только обычные номинации и только без дележа первого места."""
    leaders = {}
    for standing in standings:
        if standing["anti"]:
            continue
        firsts = [e["player"] for e in standing["entries"] if e["place"] == 1]
        if len(firsts) == 1:
            leaders[standing["key"]] = firsts[0]
    return leaders


def leader_changes(standings: list[dict], previous: dict[str, str]) -> list[dict]:
    """Номинации, где лидера перехватили: [{key, emoji, title, old, new, text}].

    Новые номинации (раньше лидера не было) и антирекорды не считаются — объявляем только «обошёл».
    """
    now = current_leaders(standings)
    by_key = {s["key"]: s for s in standings}
    changes = []
    for key, leader in now.items():
        old = previous.get(key)
        if old is None or old == leader:
            continue
        standing = by_key[key]
        changes.append({"key": key, "emoji": standing["emoji"], "title": standing["title"], "old": old,
                        "new": leader, "text": standing["entries"][0]["text"]})
    return changes
