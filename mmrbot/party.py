"""Совместная игра пати: общие матчи участников и статистика вместе.

Игроки передаются как список (имя, матчи). Матч: match_id, player_slot, radiant_win.
«Совместная игра» = один match_id есть у >=2 участников И они на одной стороне
(иначе исход у них разный — не засчитываем как совместную).
"""
from __future__ import annotations

from itertools import combinations
from typing import Optional

from mmrbot.stats import is_win


def _win_map(matches: list[dict]) -> dict[int, bool]:
    return {m["match_id"]: is_win(m["player_slot"], m["radiant_win"]) for m in matches}


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
        if len(outcomes) < 2:
            continue
        if len(set(outcomes)) != 1:  # разные команды — пропускаем
            continue
        games += 1
        if outcomes[0]:
            wins += 1
    return {"games": games, "wins": wins, "losses": games - wins}


def best_duo(players: list[tuple[str, list[dict]]]) -> Optional[dict]:
    """Пара с наибольшим числом совместных матчей (на одной стороне)."""
    win_maps = {name: _win_map(matches) for name, matches in players}

    best: Optional[dict] = None
    for (name_a, wm_a), (name_b, wm_b) in combinations(win_maps.items(), 2):
        shared = set(wm_a) & set(wm_b)
        games = wins = 0
        for match_id in shared:
            if wm_a[match_id] != wm_b[match_id]:  # разные команды
                continue
            games += 1
            if wm_a[match_id]:
                wins += 1
        if games == 0:
            continue
        candidate = {
            "pair": (name_a, name_b),
            "games": games,
            "wins": wins,
            "winrate": wins / games,
        }
        if best is None or (candidate["games"], candidate["winrate"]) > (best["games"], best["winrate"]):
            best = candidate
    return best
