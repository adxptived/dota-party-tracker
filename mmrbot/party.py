"""Совместная игра пати: общие матчи участников и статистика вместе.

Игроки передаются как список (имя, матчи). Матч: match_id, player_slot, radiant_win.
«Совместная игра» = один match_id есть у >=2 участников И они на одной стороне
(иначе исход у них разный — не засчитываем как совместную).
"""
from __future__ import annotations

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


RECENT_LIMIT = 5


def together_report(
    players: list[tuple[str, list[dict]]], since_ts: Optional[int] = None, recent_limit: int = RECENT_LIMIT
) -> dict:
    """Совместные игры по составам: кто с кем, сколько, на каких героях и последние матчи.

    Совместная игра = в одном матче 2+ участника на одной стороне (Radiant/Dire). Состав — точный
    набор участников на стороне, поэтому каждый матч попадает ровно в один состав. Участники
    различаются по позиции в списке, а не по имени (имена могут совпадать).
    """
    # (match_id, сторона) -> [(индекс игрока, матч)]
    sides: dict[tuple[int, bool], list[tuple[int, dict]]] = {}
    for index, (_, matches) in enumerate(players):
        for match in matches:
            if since_ts is not None and match["start_time"] < since_ts:
                continue
            is_radiant = match["player_slot"] < 128
            sides.setdefault((match["match_id"], is_radiant), []).append((index, match))

    games = wins = solo_games = solo_wins = 0
    by_lineup: dict[tuple[int, ...], dict] = {}
    recent: list[dict] = []
    for (match_id, _), members in sides.items():
        won = is_win(members[0][1]["player_slot"], members[0][1]["radiant_win"])
        if len(members) < 2:
            solo_games += 1
            solo_wins += won
            continue
        members.sort(key=lambda x: x[0])
        games += 1
        wins += won
        start = members[0][1]["start_time"]
        lineup = by_lineup.setdefault(
            tuple(i for i, _ in members),
            {"games": 0, "wins": 0, "last_ts": 0, "hero_counts": [dict() for _ in members]},
        )
        lineup["games"] += 1
        lineup["wins"] += won
        lineup["last_ts"] = max(lineup["last_ts"], start)
        for counts, (_, match) in zip(lineup["hero_counts"], members):
            if match.get("hero_id"):
                counts[match["hero_id"]] = counts.get(match["hero_id"], 0) + 1
        recent.append({
            "match_id": match_id, "start_time": start, "win": won,
            "players": [
                {"name": players[i][0], "hero_id": match.get("hero_id"), "kills": match.get("kills") or 0,
                 "deaths": match.get("deaths") or 0, "assists": match.get("assists") or 0}
                for i, match in members
            ],
        })

    lineups = []
    for indexes, data in by_lineup.items():
        heroes = []
        for counts in data["hero_counts"]:  # любимый герой каждого в этом составе
            if counts:
                hero_id = max(counts, key=lambda h: (counts[h], -h))
                heroes.append({"hero_id": hero_id, "games": counts[hero_id]})
            else:
                heroes.append(None)
        lineups.append({
            "names": [players[i][0] for i in indexes],
            "games": data["games"], "wins": data["wins"], "losses": data["games"] - data["wins"],
            "winrate": data["wins"] / data["games"], "last_ts": data["last_ts"], "heroes": heroes,
        })
    lineups.sort(key=lambda x: (x["games"], x["winrate"], x["last_ts"]), reverse=True)
    recent.sort(key=lambda g: g["start_time"], reverse=True)
    return {
        "games": games, "wins": wins, "losses": games - wins,
        "solo_games": solo_games, "solo_wins": solo_wins,
        "lineups": lineups, "recent": recent[:recent_limit],
    }
