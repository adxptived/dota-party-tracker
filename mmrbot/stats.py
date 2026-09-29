"""Чистые функции статистики: победа/поражение, ранкед-фильтр, агрегаты, оценка MMR.

Никакого I/O — всё легко юнит-тестится. Окна по времени (с старта / за сутки /
с якоря) применяет вызывающий код (tracker) через выборки из хранилища.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

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
