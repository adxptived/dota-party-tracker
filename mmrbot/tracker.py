"""Оркестровка: обновление игрока из OpenDota и сборка сводок/лидерборда.

Зависит от storage (данные), opendota-клиента (сеть) и stats (чистые расчёты).
Клиент передаётся аргументом — в тестах подставляется фейковый (без сети).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Protocol

from mmrbot import stats
from mmrbot.ranks import rank_label
from mmrbot.storage import Chat, Player, Storage

TODAY_WINDOW_SEC = 86_400

log = logging.getLogger(__name__)


class OpenDotaClient(Protocol):
    def get_profile(self, account_id: int) -> dict: ...
    def get_matches(self, account_id: int, limit: int = 200) -> list[dict]: ...


@dataclass
class PlayerSummary:
    display_name: str
    account_id: int
    rank: str
    anchor_mmr: Optional[int]
    current_mmr: Optional[int]
    mmr_delta: int
    games_total: int
    wins_total: int
    losses_total: int
    winrate: float
    kda_ratio: float
    avg_kills: float
    avg_deaths: float
    avg_assists: float
    games_today: int
    wins_today: int
    losses_today: int
    delta_today: int


def _normalize(raw: dict) -> dict:
    return {
        "match_id": raw["match_id"],
        "start_time": raw["start_time"],
        "player_slot": raw["player_slot"],
        "radiant_win": raw["radiant_win"],
        "lobby_type": raw.get("lobby_type"),
        "kills": raw.get("kills", 0) or 0,
        "deaths": raw.get("deaths", 0) or 0,
        "assists": raw.get("assists", 0) or 0,
        "hero_id": raw.get("hero_id"),
    }


def refresh_player(storage: Storage, client: OpenDotaClient, player: Player, now: int) -> int:
    """Подтянуть новые ранкед-матчи (с created_ts) и текущий ранг. Вернуть число новых матчей."""
    profile = client.get_profile(player.account_id)
    if profile is not None:
        storage.update_player_rank(
            player.id,
            rank_tier=profile.get("rank_tier"),
            leaderboard_rank=profile.get("leaderboard_rank"),
            updated_ts=now,
        )

    raw_matches = client.get_matches(player.account_id)
    fresh = [
        _normalize(m)
        for m in raw_matches
        if stats.is_ranked_lobby(m.get("lobby_type"))
        and m["start_time"] >= player.created_ts
        and m.get("radiant_win") is not None  # исход неизвестен → не считаем матч
    ]
    return storage.add_matches(player.id, fresh)


def build_player_summary(storage: Storage, chat: Chat, player: Player, now: int) -> PlayerSummary:
    step = chat.mmr_step

    all_matches = storage.get_matches(player.id, since_ts=player.created_ts)
    anchor_matches = storage.get_matches(player.id, since_ts=player.anchor_ts)
    today_matches = storage.get_matches(player.id, since_ts=now - TODAY_WINDOW_SEC)

    agg_all = stats.aggregate(all_matches)
    agg_anchor = stats.aggregate(anchor_matches)
    agg_today = stats.aggregate(today_matches)

    mmr_delta = stats.estimate_mmr_delta(agg_anchor.wins, agg_anchor.losses, step)
    current_mmr = player.anchor_mmr + mmr_delta if player.anchor_mmr is not None else None
    delta_today = stats.estimate_mmr_delta(agg_today.wins, agg_today.losses, step)

    return PlayerSummary(
        display_name=player.display_name,
        account_id=player.account_id,
        rank=rank_label(player.last_rank_tier, player.last_leaderboard_rank),
        anchor_mmr=player.anchor_mmr,
        current_mmr=current_mmr,
        mmr_delta=mmr_delta,
        games_total=agg_all.games,
        wins_total=agg_all.wins,
        losses_total=agg_all.losses,
        winrate=agg_all.winrate,
        kda_ratio=agg_all.kda_ratio,
        avg_kills=agg_all.avg_kills,
        avg_deaths=agg_all.avg_deaths,
        avg_assists=agg_all.avg_assists,
        games_today=agg_today.games,
        wins_today=agg_today.wins,
        losses_today=agg_today.losses,
        delta_today=delta_today,
    )


def build_leaderboard(
    storage: Storage,
    client: OpenDotaClient,
    chat_id: int,
    now: int,
    refresh: bool = True,
) -> list[PlayerSummary]:
    chat = storage.get_or_create_chat(chat_id)
    players = storage.list_players(chat_id)

    summaries: list[PlayerSummary] = []
    for player in players:
        if refresh:
            try:
                refresh_player(storage, client, player, now)
            except Exception:  # ошибка по одному игроку не должна рушить весь лидерборд
                log.warning("Не удалось обновить игрока %s (id %s), беру кэш",
                            player.display_name, player.account_id, exc_info=True)
            # точная перечитка по account_id (без неоднозначности имён)
            player = storage.get_player_by_account_id(chat_id, player.account_id) or player
        summaries.append(build_player_summary(storage, chat, player, now))

    # По убыванию текущего MMR; игроки без оценки MMR — в конце.
    summaries.sort(key=lambda s: (s.current_mmr is not None, s.current_mmr or 0), reverse=True)
    return summaries
