"""Оркестровка: обновление игрока из OpenDota и сборка сводок/лидерборда.

Зависит от storage (данные), opendota-клиента (сеть) и stats (чистые расчёты).
Клиент передаётся аргументом — в тестах подставляется фейковый (без сети).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Protocol

from mmrbot import party, stats
from mmrbot.ranks import rank_label
from mmrbot.storage import Chat, Player, Storage

TODAY_WINDOW_SEC = 86_400

log = logging.getLogger(__name__)


class OpenDotaClient(Protocol):
    def get_profile(self, account_id: int) -> dict: ...
    def get_matches(self, account_id: int, limit: int = 200) -> list[dict]: ...
    def get_totals(self, account_id: int) -> dict: ...


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
    # расширенная статистика (пакеты A/C/D)
    sum_kills: int = 0
    sum_deaths: int = 0
    sum_assists: int = 0
    streak_type: str = ""
    streak_len: int = 0
    top_heroes: list = field(default_factory=list)
    gpm: Optional[float] = None
    xpm: Optional[float] = None
    last_hits: Optional[float] = None
    avg_duration_min: float = 0.0
    max_duration_min: float = 0.0
    solo: tuple = (0, 0)
    party: tuple = (0, 0)
    best_hour: Optional[tuple] = None
    worst_hour: Optional[tuple] = None


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
        "duration": raw.get("duration"),
        "party_size": raw.get("party_size"),
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
    inserted = storage.add_matches(player.id, fresh)

    # Средние GPM/XPM/last hits (пакет D) — необязательный доп. запрос.
    try:
        totals = client.get_totals(player.account_id)
        storage.update_player_totals(
            player.id, totals.get("gpm"), totals.get("xpm"), totals.get("last_hits")
        )
    except Exception:
        log.debug("Не удалось получить totals игрока %s", player.account_id, exc_info=True)

    return inserted


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

    streak_type, streak_len = stats.current_streak(all_matches)
    top = stats.top_heroes(all_matches, k=3)
    duration = stats.duration_stats(all_matches)
    split = stats.solo_party_split(all_matches)
    best_hour, worst_hour = _best_worst_hour(stats.winrate_by_hour(all_matches, chat.tz))

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
        sum_kills=agg_all.sum_kills,
        sum_deaths=agg_all.sum_deaths,
        sum_assists=agg_all.sum_assists,
        streak_type=streak_type,
        streak_len=streak_len,
        top_heroes=top,
        gpm=player.last_gpm,
        xpm=player.last_xpm,
        last_hits=player.last_last_hits,
        avg_duration_min=duration["avg_minutes"],
        max_duration_min=duration["max_minutes"],
        solo=split["solo"],
        party=split["party"],
        best_hour=best_hour,
        worst_hour=worst_hour,
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


def _best_worst_hour(by_hour: dict, min_games: int = 3):
    """Из {час: (игр, побед)} выбрать лучший/худший час (по винрейту, порог по играм)."""
    qualified = [(hour, wins / games, games) for hour, (games, wins) in by_hour.items() if games >= min_games]
    if not qualified:
        return (None, None)
    best = max(qualified, key=lambda x: x[1])
    worst = min(qualified, key=lambda x: x[1])
    return ((best[0], best[1]), (worst[0], worst[1]))


def compute_awards(summaries: list[PlayerSummary], min_games: int = 3) -> list[dict]:
    """Награды пати по сводкам игроков. Каждая: {title, player, detail}."""
    eligible = [s for s in summaries if s.games_total >= min_games]
    awards: list[dict] = []
    if not eligible:
        return awards

    king = max(eligible, key=lambda s: s.winrate)
    awards.append({"title": "👑 Король винрейта", "player": king.display_name,
                   "detail": f"{king.winrate * 100:.0f}% ({king.wins_total}–{king.losses_total})"})

    grinder = max(eligible, key=lambda s: s.games_total)
    awards.append({"title": "🛠 Работяга", "player": grinder.display_name,
                   "detail": f"{grinder.games_total} игр"})

    carry = max(eligible, key=lambda s: s.kda_ratio)
    awards.append({"title": "🗡 Керри (KDA)", "player": carry.display_name,
                   "detail": f"KDA {carry.kda_ratio:.2f}"})

    feeder = max(eligible, key=lambda s: s.sum_deaths)
    awards.append({"title": "💀 Фидер", "player": feeder.display_name,
                   "detail": f"{feeder.sum_deaths} смертей всего"})

    return awards


def build_together(storage: Storage, chat_id: int) -> dict:
    """Статистика совместной игры пати (пакет B)."""
    players = storage.list_players(chat_id)
    named_matches = [
        (p.display_name, storage.get_matches(p.id, since_ts=p.created_ts)) for p in players
    ]
    return {
        "player_count": len(players),
        "summary": party.together_summary(named_matches),
        "duo": party.best_duo(named_matches),
    }
