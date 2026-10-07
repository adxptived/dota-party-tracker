"""Совместная игра пати: общие матчи участников и статистика вместе.

Игроки передаются как список (имя, матчи). Матч: match_id, player_slot, radiant_win.
«Совместная игра» = один match_id есть у >=2 участников, они на одной стороне и не были соло в лобби
(иначе исход у них разный — не засчитываем как совместную).
"""
from __future__ import annotations

from itertools import combinations
from typing import Optional

from mmrbot.stats import is_win


def _win_map(matches: list[dict]) -> dict[int, bool]:
    """match_id -> победа. Игра, где игрок точно был один в лобби (party_size == 1), в совместные не идёт:
    двое из чата оказались на одной стороне случайно. Размер пати неизвестен — даём игре шанс."""
    return {
        m["match_id"]: is_win(m["player_slot"], m["radiant_win"])
        for m in matches
        if m.get("party_size") != 1
    }


def together_summary(players: list[tuple[str, list[dict]]]) -> dict:
    """Сводка по матчам, где участвовали >=2 игрока пати на одной стороне."""
    win_maps = [(_win_map(matches)) for _, matches in players]

    # match_id -> список исходов (bool) среди присутствовавших игроков
    by_match: dict[int, list[bool]] = {}
    for wm in win_maps:
        for match_id, won in wm.items():
            by_match.setdefault(match_id, []).append(won)

    games = wins = 0
    for outcomes in by_match.values():
        won = sum(1 for o in outcomes if o)
        lost = len(outcomes) - won
        if max(won, lost) < 2:  # нет как минимум 2 игроков на одной стороне
            continue
        if won == lost:  # 2 на 2 и т.п. — неоднозначно, пропускаем
            continue
        games += 1
        if won > lost:
            wins += 1
    return {"games": games, "wins": wins, "losses": games - wins}


def pair_stats(players: list[tuple[str, list[dict]]]) -> list[dict]:
    """Все пары с совместными играми на одной стороне: [{a, b, games, wins}] — a < b, индексы в `players`.

    Индексы, а не имена: имена не уникальны, и два аккаунта с одинаковым именем не должны схлопываться
    (иначе теряем матчи одного из них).
    """
    win_maps = [_win_map(matches) for _, matches in players]
    result = []
    for (a, wm_a), (b, wm_b) in combinations(enumerate(win_maps), 2):
        games = wins = 0
        for match_id in set(wm_a) & set(wm_b):
            if wm_a[match_id] != wm_b[match_id]:  # разные команды
                continue
            games += 1
            if wm_a[match_id]:
                wins += 1
        if games:
            result.append({"a": a, "b": b, "games": games, "wins": wins})
    return result


def best_duo(players: list[tuple[str, list[dict]]]) -> Optional[dict]:
    """Пара с наибольшим числом совместных матчей (на одной стороне); при равенстве — с лучшим винрейтом."""
    best: Optional[dict] = None
    for pair in pair_stats(players):
        candidate = {
            "pair": (players[pair["a"]][0], players[pair["b"]][0]),
            "games": pair["games"],
            "wins": pair["wins"],
            "winrate": pair["wins"] / pair["games"],
        }
        if best is None or (candidate["games"], candidate["winrate"]) > (best["games"], best["winrate"]):
            best = candidate
    return best
