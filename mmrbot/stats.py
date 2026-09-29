"""Чистые функции статистики: победа/поражение, ранкед-фильтр, агрегаты, оценка MMR.

Никакого I/O — всё легко юнит-тестится. Окна по времени (с старта / за сутки /
с якоря) применяет вызывающий код (tracker) через выборки из хранилища.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pytz

RANKED_LOBBY_TYPE = 7


def is_win(player_slot: int, radiant_win: bool) -> bool:
    """player_slot < 128 — игрок за Radiant. Победа = сторона игрока победила."""
    is_radiant = player_slot < 128
    return is_radiant == bool(radiant_win)


def is_ranked_lobby(lobby_type: Optional[int]) -> bool:
    return lobby_type == RANKED_LOBBY_TYPE


@dataclass
class Aggregate:
    games: int
    wins: int
    losses: int
    sum_kills: int
    sum_deaths: int
    sum_assists: int

    @property
    def winrate(self) -> float:
        return self.wins / self.games if self.games else 0.0

    @property
    def avg_kills(self) -> float:
        return self.sum_kills / self.games if self.games else 0.0

    @property
    def avg_deaths(self) -> float:
        return self.sum_deaths / self.games if self.games else 0.0

    @property
    def avg_assists(self) -> float:
        return self.sum_assists / self.games if self.games else 0.0

    @property
    def kda_ratio(self) -> float:
        """(K+A)/max(D,1) по сумме — стандартный агрегатный KDA."""
        if self.games == 0:
            return 0.0
        return (self.sum_kills + self.sum_assists) / max(self.sum_deaths, 1)


def aggregate(matches: list[dict]) -> Aggregate:
    """Свести список матчей в агрегат. Каждый матч: player_slot, radiant_win, kills, deaths, assists."""
    wins = 0
    sum_k = sum_d = sum_a = 0
    for match in matches:
        if is_win(match["player_slot"], match["radiant_win"]):
            wins += 1
        sum_k += match.get("kills", 0) or 0
        sum_d += match.get("deaths", 0) or 0
        sum_a += match.get("assists", 0) or 0
    games = len(matches)
    return Aggregate(
        games=games,
        wins=wins,
        losses=games - wins,
        sum_kills=sum_k,
        sum_deaths=sum_d,
        sum_assists=sum_a,
    )


def estimate_mmr_delta(wins: int, losses: int, step: int) -> int:
    """Оценка изменения MMR: (победы - поражения) * шаг."""
    return (wins - losses) * step


def current_streak(matches: list[dict]) -> tuple[str, int]:
    """Текущая серия по хвосту (матчи должны быть по возрастанию времени).

    Возвращает ('W'|'L', длина) или ('', 0), если матчей нет.
    """
    if not matches:
        return ("", 0)
    last_win = is_win(matches[-1]["player_slot"], matches[-1]["radiant_win"])
    length = 0
    for match in reversed(matches):
        if is_win(match["player_slot"], match["radiant_win"]) == last_win:
            length += 1
        else:
            break
    return ("W" if last_win else "L", length)


def top_heroes(matches: list[dict], k: int = 3) -> list[dict]:
    """Топ-k героев по числу игр (тай-брейк: винрейт, затем hero_id)."""
    by_hero: dict[int, list[int]] = {}  # hero_id -> [games, wins]
    for match in matches:
        hero_id = match.get("hero_id")
        if not hero_id:
            continue
        stat = by_hero.setdefault(hero_id, [0, 0])
        stat[0] += 1
        if is_win(match["player_slot"], match["radiant_win"]):
            stat[1] += 1
    result = [
        {"hero_id": hid, "games": games, "wins": wins, "winrate": wins / games}
        for hid, (games, wins) in by_hero.items()
    ]
    result.sort(key=lambda h: (h["games"], h["winrate"], -h["hero_id"]), reverse=True)
    return result[:k]


def winrate_by_hour(matches: list[dict], tz_name: str) -> dict[int, tuple[int, int]]:
    """Разбивка по локальному часу старта: hour -> (игр, побед)."""
    try:
        tz = pytz.timezone(tz_name)
    except Exception:
        tz = pytz.timezone("Europe/Moscow")
    by_hour: dict[int, list[int]] = {}
    for match in matches:
        start_time = match.get("start_time")
        if start_time is None:
            continue
        hour = datetime.fromtimestamp(start_time, tz=timezone.utc).astimezone(tz).hour
        stat = by_hour.setdefault(hour, [0, 0])
        stat[0] += 1
        if is_win(match["player_slot"], match["radiant_win"]):
            stat[1] += 1
    return {hour: (games, wins) for hour, (games, wins) in by_hour.items()}


def solo_party_split(matches: list[dict]) -> dict[str, tuple[int, int]]:
    """Соло (party_size<=1 или отсутствует) vs пати: bucket -> (игр, побед)."""
    buckets = {"solo": [0, 0], "party": [0, 0]}
    for match in matches:
        party_size = match.get("party_size") or 1
        key = "party" if party_size > 1 else "solo"
        buckets[key][0] += 1
        if is_win(match["player_slot"], match["radiant_win"]):
            buckets[key][1] += 1
    return {key: (games, wins) for key, (games, wins) in buckets.items()}


def recent_form(matches: list[dict], n: int = 5) -> list[bool]:
    """Последние n матчей как список исходов (True=победа), в хронологическом порядке."""
    tail = matches[-n:]
    return [is_win(m["player_slot"], m["radiant_win"]) for m in tail]


def best_game(matches: list[dict]) -> Optional[dict]:
    """Матч с максимальным KDA. Возвращает kills/deaths/assists/hero_id/kda или None."""
    best = None
    best_kda = -1.0
    for match in matches:
        kills = match.get("kills", 0) or 0
        deaths = match.get("deaths", 0) or 0
        assists = match.get("assists", 0) or 0
        kda = (kills + assists) / max(deaths, 1)
        if kda > best_kda:
            best_kda = kda
            best = {
                "kills": kills,
                "deaths": deaths,
                "assists": assists,
                "hero_id": match.get("hero_id"),
                "kda": kda,
            }
    return best


def longest_win_streak(matches: list[dict]) -> int:
    """Самая длинная серия побед подряд за весь набор матчей."""
    longest = current = 0
    for match in matches:
        if is_win(match["player_slot"], match["radiant_win"]):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def duration_stats(matches: list[dict]) -> dict[str, float]:
    """Средняя и максимальная длительность (в минутах) по полю duration (секунды)."""
    durations = [m["duration"] for m in matches if m.get("duration")]
    if not durations:
        return {"avg_minutes": 0, "max_minutes": 0}
    return {
        "avg_minutes": sum(durations) / len(durations) / 60,
        "max_minutes": max(durations) / 60,
    }
