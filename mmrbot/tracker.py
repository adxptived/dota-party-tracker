"""Оркестровка: обновление игрока из OpenDota и сборка сводок/лидерборда.

Зависит от storage (данные), opendota-клиента (сеть) и stats (чистые расчёты).
Клиент передаётся аргументом — в тестах подставляется фейковый (без сети).
"""
from __future__ import annotations

import json
import logging
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional, Protocol

from mmrbot import party, stats
from mmrbot.ranks import rank_emoji, rank_label
from mmrbot.storage import Chat, Player, Storage

TODAY_WINDOW_SEC = 86_400

log = logging.getLogger(__name__)


ENRICH_CAP = 12  # сколько матчей обогащать деталями за один refresh (лимит запросов)
REFRESH_COOLDOWN = 180  # сек: не ходить в OpenDota, если игрок обновлён недавно (скорость /stats)
INSIGHTS_TTL = 6 * 3600  # сек: totals/линии/GPM-гистограмма — «медленные» агрегаты, не тянем на каждый refresh
REFRESH_WORKERS = 4  # игроков обновляем параллельно (частоту запросов всё равно держит троттлинг клиента)


class OpenDotaClient(Protocol):
    def refresh(self, account_id: int) -> bool: ...
    def get_profile(self, account_id: int) -> dict: ...
    def get_matches(self, account_id: int, limit: int = 200) -> list[dict]: ...
    def get_totals(self, account_id: int) -> dict: ...
    def get_lanes(self, account_id: int) -> dict: ...
    def get_gpm_distribution(self, account_id: int) -> dict: ...
    def get_match_player_stats(self, match_id: int, account_id: int) -> Optional[dict]: ...


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
    rank_emoji: str = ""
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
    lanes: dict = field(default_factory=dict)
    recent_form: list = field(default_factory=list)
    best_game: Optional[dict] = None
    longest_win_streak: int = 0
    gpm_median: Optional[float] = None
    gpm_best: Optional[float] = None
    avg_perf: Optional[float] = None
    enriched_games: int = 0
    avg_gpm_window: Optional[float] = None
    avg_hero_damage_window: Optional[float] = None
    avg_net_worth_window: Optional[float] = None
    avg_last_hits_window: Optional[float] = None
    avg_hero_healing_window: Optional[float] = None
    skill: dict = field(default_factory=dict)
    role_style: str = ""
    lobby_rank: Optional[int] = None
    hero_pool: int = 0
    wins_losses: dict = field(default_factory=dict)


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
        "average_rank": raw.get("average_rank"),
    }


def refresh_player(storage: Storage, client: OpenDotaClient, player: Player, now: int) -> int:
    """Подтянуть новые ранкед-матчи (с created_ts) и текущий ранг. Вернуть число новых матчей."""
    # Пнуть OpenDota перечитать историю — свежие игры доедут быстрее (best-effort).
    try:
        client.refresh(player.account_id)
    except Exception:
        pass

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

    # Тяжёлые агрегаты (3 запроса) меняются медленно: тянем при новых матчах, первом заходе
    # или по TTL — иначе каждое обновление стоит лишних ~3 секунд на игрока.
    insights_stale = (
        inserted > 0
        or player.insights_ts is None
        or (now - player.insights_ts) >= INSIGHTS_TTL
    )
    if insights_stale:
        # Средние GPM/XPM/last hits (пакет D) — необязательный доп. запрос.
        try:
            totals = client.get_totals(player.account_id)
            storage.update_player_totals(
                player.id, totals.get("gpm"), totals.get("xpm"), totals.get("last_hits")
            )
        except Exception:
            log.debug("Не удалось получить totals игрока %s", player.account_id, exc_info=True)

        # Линии + распределение GPM — тоже необязательные доп. запросы.
        try:
            lanes = client.get_lanes(player.account_id)
            lanes_json = json.dumps({str(lane): list(gw) for lane, gw in lanes.items()})
            dist = client.get_gpm_distribution(player.account_id)
            storage.update_player_insights(
                player.id, lanes_json, dist.get("median"), dist.get("best"), insights_ts=now
            )
        except Exception:
            log.debug("Не удалось получить lanes/gpm игрока %s", player.account_id, exc_info=True)

    # Обогащение матчей: пер-матч поля + role-normalized perf из benchmarks (по 1 GET на матч).
    for match_id in storage.get_unenriched_match_ids(player.id, player.created_ts, ENRICH_CAP):
        try:
            details = client.get_match_player_stats(match_id, player.account_id)
            if details:
                ps = stats.perf_score(details.get("benchmarks") or {})
                storage.update_match_details(player.id, match_id, details, ps)
        except Exception:
            log.debug("Не удалось обогатить матч %s", match_id, exc_info=True)

    return inserted


def build_player_summary(storage: Storage, chat: Chat, player: Player, now: int) -> PlayerSummary:
    step = chat.mmr_step

    # Один запрос в БД вместо трёх: окна (с якоря / за сутки) режем в памяти.
    all_matches = storage.get_matches(player.id, since_ts=player.created_ts)
    anchor_matches = [m for m in all_matches if m["start_time"] >= player.anchor_ts]
    today_cutoff = now - TODAY_WINDOW_SEC
    today_matches = [m for m in all_matches if m["start_time"] >= today_cutoff]

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
    lanes = _parse_lanes(player.last_lanes)

    enriched = [m for m in all_matches if m.get("perf_score") is not None]
    avg_perf = sum(m["perf_score"] for m in enriched) / len(enriched) if enriched else None

    def _mean_field(field: str) -> Optional[float]:
        values = [m[field] for m in all_matches if m.get(field) is not None]
        return sum(values) / len(values) if values else None

    bench_list = []
    for match in all_matches:
        raw = match.get("bench_json")
        if raw:
            try:
                bench_list.append(json.loads(raw))
            except (ValueError, TypeError):
                pass
    skill = stats.aggregate_skill(bench_list)
    avg_last_hits_window = _mean_field("last_hits")
    avg_hero_healing_window = _mean_field("hero_healing")
    role_style = stats.infer_role_style(avg_last_hits_window, avg_hero_healing_window)

    lobby_ranks = [m["average_rank"] for m in all_matches if m.get("average_rank")]
    lobby_rank = round(statistics.median(lobby_ranks)) if lobby_ranks else None
    wins_losses = stats.wins_losses_split(all_matches)
    pool = stats.hero_pool(all_matches)

    return PlayerSummary(
        display_name=player.display_name,
        account_id=player.account_id,
        rank=rank_label(player.last_rank_tier, player.last_leaderboard_rank),
        rank_emoji=rank_emoji(player.last_rank_tier),
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
        lanes=lanes,
        recent_form=stats.recent_form(all_matches, 5),
        best_game=stats.best_game(all_matches),
        longest_win_streak=stats.longest_win_streak(all_matches),
        gpm_median=player.last_gpm_median,
        gpm_best=player.last_gpm_best,
        avg_perf=avg_perf,
        enriched_games=len(enriched),
        avg_gpm_window=_mean_field("gpm"),
        avg_hero_damage_window=_mean_field("hero_damage"),
        avg_net_worth_window=_mean_field("net_worth"),
        avg_last_hits_window=avg_last_hits_window,
        avg_hero_healing_window=avg_hero_healing_window,
        skill=skill,
        role_style=role_style,
        lobby_rank=lobby_rank,
        hero_pool=pool,
        wins_losses=wins_losses,
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

    def _refresh_safe(player: Player) -> None:
        try:
            refresh_player(storage, client, player, now)
        except Exception:  # ошибка по одному игроку не должна рушить весь лидерборд
            log.warning("Не удалось обновить игрока %s (id %s), беру кэш",
                        player.display_name, player.account_id, exc_info=True)

    # Кулдаун: если обновляли недавно — берём кэш из БД, не дёргаем OpenDota (скорость).
    stale_players = [
        p for p in players
        if refresh and (p.updated_ts is None or (now - p.updated_ts) >= REFRESH_COOLDOWN)
    ]
    if len(stale_players) > 1:
        # Игроки независимы: параллелим, чтобы сетевые ожидания перекрывались.
        with ThreadPoolExecutor(max_workers=min(REFRESH_WORKERS, len(stale_players))) as pool:
            list(pool.map(_refresh_safe, stale_players))
    elif stale_players:
        _refresh_safe(stale_players[0])

    summaries: list[PlayerSummary] = []
    if stale_players:
        # точная перечитка по account_id (без неоднозначности имён) — одним запросом списка
        fresh = {p.account_id: p for p in storage.list_players(chat_id)}
        players = [fresh.get(p.account_id, p) for p in players]
    for player in players:
        summaries.append(build_player_summary(storage, chat, player, now))

    # По убыванию текущего MMR; игроки без оценки MMR — в конце.
    summaries.sort(key=lambda s: (s.current_mmr is not None, s.current_mmr or 0), reverse=True)
    return summaries


def _parse_lanes(lanes_json: Optional[str]) -> dict:
    """JSON {'2':[games,wins]} → {2: (games, wins)}."""
    if not lanes_json:
        return {}
    try:
        raw = json.loads(lanes_json)
    except (ValueError, TypeError):
        return {}
    result = {}
    for key, value in raw.items():
        try:
            result[int(key)] = (value[0], value[1])
        except (ValueError, TypeError, IndexError):
            continue
    return result


def _best_worst_hour(by_hour: dict, min_games: int = 3):
    """Из {час: (игр, побед)} выбрать лучший/худший час (по винрейту, порог по играм)."""
    qualified = [(hour, wins / games, games) for hour, (games, wins) in by_hour.items() if games >= min_games]
    if not qualified:
        return (None, None)
    best = max(qualified, key=lambda x: x[1])
    worst = min(qualified, key=lambda x: x[1])
    return ((best[0], best[1]), (worst[0], worst[1]))


def compute_awards(summaries: list[PlayerSummary], min_games: int = 3) -> list[dict]:
    """Награды, рассказывающие историю пати (не липнут к одному игроку). {title, player, detail}.

    Позитивные — лучшему; «главный тилт» — тому, кто РЕАЛЬНО в просадке (серия поражений),
    а не самому активному. Метрики по ставкам/сериям, не по абсолютным суммам.
    """
    eligible = [s for s in summaries if s.games_total >= min_games]
    awards: list[dict] = []
    if not eligible:
        return awards

    # MVP по role-normalized перформансу (честнее KDA) — самый престижный.
    perf_eligible = [s for s in eligible if s.avg_perf is not None]
    if perf_eligible:
        mvp = max(perf_eligible, key=lambda s: s.avg_perf)
        awards.append({"title": "🎯 MVP (перформанс)", "player": mvp.display_name,
                       "detail": f"{mvp.avg_perf * 100:.0f}/100"})

    king = max(eligible, key=lambda s: s.winrate)
    awards.append({"title": "👑 Король винрейта", "player": king.display_name,
                   "detail": f"{king.winrate * 100:.0f}% ({king.wins_total}–{king.losses_total})"})

    # Стилевые награды (по ставкам/за игру) — разводят кор/саппорт/дамагера.
    def _best(getter, title, detail):
        pool = [s for s in eligible if getter(s) is not None]
        if pool:
            top = max(pool, key=getter)
            awards.append({"title": title, "player": top.display_name, "detail": detail(top)})

    _best(lambda s: s.avg_gpm_window, "🌾 Фармила", lambda s: f"{s.avg_gpm_window:.0f} GPM")
    _best(lambda s: s.avg_hero_damage_window, "🗡 Мясник",
          lambda s: f"{s.avg_hero_damage_window / 1000:.1f}k урона/игра")
    _best(lambda s: s.avg_assists or None, "✨ Опора", lambda s: f"{s.avg_assists:.0f} ассистов/игра")
    _best(lambda s: s.best_game["kda"] if s.best_game else None, "🌟 Имба игры",
          lambda s: f"{s.best_game['kills']}/{s.best_game['deaths']}/{s.best_game['assists']}")
    _best(lambda s: s.hero_pool or None, "🦸 Мастер на все руки", lambda s: f"{s.hero_pool} героев")

    # На кураже — самая длинная текущая серия ПОБЕД.
    hot = [s for s in eligible if s.streak_type == "W" and s.streak_len >= 2]
    if hot:
        top = max(hot, key=lambda s: s.streak_len)
        awards.append({"title": "🔥 На кураже", "player": top.display_name,
                       "detail": f"{top.streak_len} побед подряд"})

    # Камикадзе — больше всего смертей ЗА ИГРУ (не сумма! честно к активности).
    _best(lambda s: s.avg_deaths or None, "💀 Камикадзе", lambda s: f"{s.avg_deaths:.0f} смертей/игра")

    # Главный тилт — самая длинная серия ПОРАЖЕНИЙ (реальная просадка).
    cold = [s for s in eligible if s.streak_type == "L" and s.streak_len >= 2]
    if cold:
        bottom = max(cold, key=lambda s: (s.streak_len, -s.winrate))
        awards.append({"title": "📉 Главный тилт", "player": bottom.display_name,
                       "detail": f"{bottom.streak_len} поражений подряд, {bottom.winrate * 100:.0f}%"})

    return awards


# Метрики для сравнения игроков внутри чата (все — «выше = лучше»).
_COMPARE_METRICS = {
    "perf": lambda s: s.avg_perf,
    "winrate": lambda s: s.winrate if s.games_total else None,
    "kda": lambda s: s.kda_ratio if s.games_total else None,
    "gpm": lambda s: s.avg_gpm_window,
}


def build_chat_comparison(summaries: list[PlayerSummary]) -> dict:
    """Ранги игроков внутри чата по метрикам + композитная «сила в чате».

    Для каждой метрики ранжируем (1 = лучший). power = среднее нормированной позиции
    (1=лучший…0=худший) по метрикам, где значение есть. power_rank — итоговое место.
    """
    players: dict = {s.display_name: {"ranks": {}, "leads": [], "_pos": []} for s in summaries}
    averages: dict = {}

    for key, getter in _COMPARE_METRICS.items():
        valued = [(s.display_name, getter(s)) for s in summaries if getter(s) is not None]
        present = [value for _, value in valued]
        averages[key] = sum(present) / len(present) if present else None
        ordered = sorted(valued, key=lambda kv: kv[1], reverse=True)
        n = len(ordered)
        for rank, (name, _value) in enumerate(ordered, start=1):
            players[name]["ranks"][key] = rank
            if rank == 1 and n > 1:
                players[name]["leads"].append(key)
            players[name]["_pos"].append((n - rank) / (n - 1) if n > 1 else 1.0)

    ranking = []
    for name, data in players.items():
        positions = data.pop("_pos")
        data["power"] = sum(positions) / len(positions) if positions else None
        ranking.append((name, data["power"]))
    ranking.sort(key=lambda kv: (kv[1] is not None, kv[1] or 0), reverse=True)
    for rank, (name, _power) in enumerate(ranking, start=1):
        players[name]["power_rank"] = rank

    return {"size": len(summaries), "players": players, "averages": averages}


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
