"""Асинхронные помощники, общие для хендлеров и планировщика.

Сетевые/CPU-операции (build_leaderboard дергает синхронный OpenDota-клиент)
выносятся в поток через asyncio.to_thread, чтобы не блокировать event loop aiogram.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time
import weakref
from typing import Optional

from mmrbot import avatars, hero_icons, item_icons, perf
from mmrbot.alert_image import alert_caption, render_alert_image
from mmrbot.boards import CAPTION_LIMIT, HeroBoard, ImageBoard, MatchBoard, build_png, fit_caption
from mmrbot.contest_image import MAX_TABLE as CONTEST_TABLE_LIMIT, render_contest_image
from mmrbot.daily_image import render_daily_image
from mmrbot.card_data import (
    award_items, contest_caption, daily_caption, daily_card, contest_view, compare_caption, compare_rows, hero_caption, together_caption, together_card, weekly_awards, weekly_caption, weekly_records, weekly_tiles, record_tiles, records_caption, hero_detail_rows, hero_rows, heroes_caption, leader_caption, party_hero_rows,
    party_tiles, period_caption, period_rows, player_caption, player_card, record_items, role_rows, roles_caption,
    summary_rows,
)
from mmrbot.cards import ACCENT
from mmrbot.compare_image import render_compare_image
from mmrbot.together_image import render_together_image
from mmrbot.health import log_network_error, provider_down
from mmrbot.formatting import (
    outage_note,
    PERIOD_LABELS,
    render_contest,
    render_awards,
    render_daily,
    render_party_pulse,
    render_compare_table,
    render_full_match,
    render_game_alert,
    render_hero_detail,
    render_heroes,
    render_weekly,
    render_leaderboard,
    render_match_caption,
    render_match_card,
    render_player_card,
    render_period_leaderboard,
    render_player_heroes,
    render_records,
    render_roles,
    render_together,
    stale_note,
    standing_line,
)
from mmrbot.texts import HIDDEN_HINT, NO_PLAYERS, NOT_FOUND, STRATZ_OFF
from mmrbot.charts import _games_word as games_word, render_mmr_chart, series_stats
from mmrbot.heroes import find_hero, hero_name
from mmrbot.heroes_image import LIMIT as HEROES_LIMIT
from mmrbot.heroes_image import render_hero_image, render_party_heroes_image, render_player_heroes_image
from mmrbot.match_image import render_match_image
from mmrbot.opendota import OpenDota
from mmrbot.ranks import rank_label
from mmrbot import stats
from mmrbot.player_image import render_player_image
from mmrbot.records_image import render_records_image
from mmrbot.stats import period_since
from mmrbot.stats_image import render_stats_image
from mmrbot.storage import Storage
from mmrbot.tracker import (
    FRESH_ENOUGH,
    enrich_alert_items,
    BUILD_FIELDS, enrich_match_builds,
    finish_refresh,
    build_chat_comparison,
    build_daily_report,
    build_hero_view,
    build_weekly_report,
    build_leaderboard,
    refresh_chat,
    build_match_view,
    build_period_leaderboard,
    build_player_heroes,
    build_player_roles,
    build_together,
    build_mmr_series,
    build_period_awards,
    build_records,
    build_contest,
)

log = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096
PERIOD_BADGES = {"day": "ЗА СУТКИ", "week": "ЗА НЕДЕЛЮ", "month": "ЗА МЕСЯЦ", "year": "ЗА ГОД", "all": "ВСЁ ВРЕМЯ"}


def want_image(storage: Storage, chat_id: int, image: Optional[bool] = None) -> bool:
    """Рисовать ли картинку: явное True/False главнее, иначе — настройка чата «🖼 Отчёты» (prefer_text)."""
    return image if image is not None else not storage.get_or_create_chat(chat_id).prefer_text


async def _build(fn, *args):
    """Сборка данных из БД в потоке; время идёт в фазу build строки perf."""
    with perf.phase("build"):
        return await asyncio.to_thread(fn, *args)


async def _render(fn, *args):
    """Рисование картинки в потоке; время идёт в фазу render строки perf."""
    with perf.phase("render"):
        return await asyncio.to_thread(fn, *args)


# Блокировки по чату (на каждый event loop): одновременные команды в одном чате не обновляют
# игроков дважды — второй вызов ждёт первый и видит свежий кулдаун вместо повторных запросов.
_chat_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[int, asyncio.Lock]]" = (
    weakref.WeakKeyDictionary()
)


def _chat_lock(chat_id: int) -> asyncio.Lock:
    per_loop = _chat_locks.setdefault(asyncio.get_running_loop(), {})
    return per_loop.setdefault(chat_id, asyncio.Lock())


# Фоновая «вторая половина» обновления после ответа на команду: не больше одной задачи на чат.
_finish_running: set[tuple] = set()
_finish_tasks: set = set()


def _kick_finish(storage: Storage, od: OpenDota, chat_id: int) -> None:
    """Догнать всё, чего команда не ждала (детали матчей, средние/линии), уже после ответа."""
    if od is None or storage is None:
        return
    key = (storage.db_path, chat_id)
    if key in _finish_running:
        return
    _finish_running.add(key)

    async def run() -> None:
        try:
            await asyncio.to_thread(finish_refresh, storage, od, chat_id)
        except Exception as exc:
            log_network_error(log, f"Фоновое дообновление чата {chat_id} не удалось", exc, health=getattr(od, "health", None))
        finally:
            _finish_running.discard(key)

    task = asyncio.get_running_loop().create_task(run())
    _finish_tasks.add(task)  # держим ссылку, пока задача не завершится
    task.add_done_callback(_finish_tasks.discard)


COMMAND_REFRESH_WAIT = 4.0  # сек: ожидание обновления по умолчанию; настройка COMMAND_REFRESH_WAIT живёт в od.command_wait
_background_refreshes: set = set()

# Какие команды ждут обновление (в пределах бюджета), а какие отвечают сразу из БД, а обновление идёт фоном.
# Ждут отчёты, где свежая игра меняет картину (рейтинг, ±MMR, график, рекорды, матч). Не ждут разрезы по героям/ролям:
# новые 1–2 игры за месяц их почти не меняют. Игроки, которых ещё ни разу не загружали, ждут всегда: пустой экран хуже.
WAITS_FOR_REFRESH = {
    "stats": True, "player": True, "compare": True, "together": True, "records": True, "graph": True,
    "period": True, "match": True,
    "heroes": False, "player_heroes": False, "roles": False, "hero": False,
}


async def refresh_for(command: str, storage: Storage, od: OpenDota, chat_id: int, stratz=None) -> bool:
    """Обновление под команду по таблице WAITS_FOR_REFRESH: ждать (в бюджете) или запустить фоном и ответить из БД."""
    never_loaded = any(p.updated_ts is None for p in storage.list_players(chat_id))
    budget = None if WAITS_FOR_REFRESH[command] or never_loaded else 0.0
    return await refresh_with_budget(storage, od, chat_id, stratz, budget=budget)


async def refresh_with_budget(
    storage: Storage, od: OpenDota, chat_id: int, stratz=None, budget: Optional[float] = None
) -> bool:
    """Обновить игроков чата, но ждать не дольше budget (по умолчанию od.command_wait).

    Уложились — True. Нет (OpenDota тормозит) — False: вызывающий отвечает из БД, а обновление, не
    отменяясь, доходит фоном. Ошибка обновления в пределах бюджета поднимается наверх, как раньше.
    """
    wait = getattr(od, "command_wait", COMMAND_REFRESH_WAIT) if budget is None else budget
    task = asyncio.ensure_future(refresh_only(storage, od, chat_id, stratz))
    with perf.phase("refresh"):  # то, сколько команда реально прождала обновление
        done, _ = await asyncio.wait({task}, timeout=wait)
    if task in done:
        task.result()
        return True
    log.info("Обновление чата %s дольше %.1f с — отвечаем из БД, обновление идёт фоном", chat_id, wait)
    _background_refreshes.add(task)  # держим ссылку: иначе задачу может собрать GC
    task.add_done_callback(_background_refreshes.discard)
    task.add_done_callback(lambda t: t.cancelled() or t.exception())  # без «exception was never retrieved»
    return False


async def gather_summaries(
    storage: Storage, od: OpenDota, chat_id: int, refresh: bool = True, stratz=None, complete: bool = False,
    command: str = "stats",
):
    """Обновить игроков и собрать сводки.

    complete=False (команды): сначала обновление в пределах бюджета (refresh_with_budget: матчи, ранг и
    позиции Stratz; детали матчей и средние/линии догоняются фоном), затем сводки — всегда из БД, без лока
    чата (не ждут медленное обновление). True (ежедневная сводка): ждём всё, без бюджета.
    """
    if not complete:
        if refresh:
            await refresh_for(command, storage, od, chat_id, stratz)
        # Сводки — из БД: обновление уже сделано или доходит фоном (лок чата им не нужен).
        return await _build(build_leaderboard, storage, od, chat_id, int(time.time()), False, stratz, True)
    async with _chat_lock(chat_id):
        now = int(time.time())  # момент берём уже под локом — кулдаун считается от актуального времени
        return await _build(build_leaderboard, storage, od, chat_id, now, refresh, stratz, not complete)


async def refresh_only(storage: Storage, od: OpenDota, chat_id: int, stratz=None) -> None:
    """Только обновить матчи игроков (под локом чата) — без сборки сводок, когда они не нужны."""
    async with _chat_lock(chat_id):
        await asyncio.to_thread(
            refresh_chat, storage, od, chat_id, int(time.time()), stratz, None, True, FRESH_ENOUGH
        )
    _kick_finish(storage, od, chat_id)


def _with_stale(storage: Storage, chat_id: int, text: str, od=None) -> str:
    """Дописать, почему данные устарели: «OpenDota недоступен с … — показаны данные на …».

    Пока OpenDota недоступен (od.health), причина названа явно; иначе — прежнее предупреждение о тех игроках,
    которых не удалось обновить. Одна строка, а не две. Когда всё свежо и OpenDota жив — ничего не добавляется.
    """
    players = storage.list_players(chat_id)
    now = int(time.time())
    health = getattr(od, "health", None)
    note = outage_note(health.status() if health is not None else None, players, now, storage.get_or_create_chat(chat_id).tz)
    note = note or stale_note(players, now, FRESH_ENOUGH)
    return f"{text}\n\n{note}" if note else text


async def _stats_parts(
    storage: Storage, od: OpenDota, chat_id: int, today_only: bool, refresh: bool, stratz, awards_period: str,
) -> dict:
    """Данные рейтинга: сводки игроков, неделя, рекорды и отличия + собранный из них текст (без пометки об устаревании)."""
    summaries = await gather_summaries(storage, od, chat_id, refresh, stratz, complete=awards_period == "day")
    text = render_leaderboard(summaries, today_only=today_only)
    parts = {"summaries": summaries, "week_rows": [], "week_records": {}, "awards": []}
    if not today_only:
        since = int(time.time()) - 7 * 86_400
        week_rows = await _build(build_period_leaderboard, storage, chat_id, since)
        week_records = await _build(build_records, storage, chat_id, since)
        day_rows = None
        if awards_period == "day":
            day_rows = await _build(build_period_leaderboard, storage, chat_id, int(time.time()) - 86_400)
        text += "\n\n" + render_party_pulse(summaries, week_rows, week_records, day_rows)
        awards = []
        if len(summaries) >= 2:  # «отличия» — соревнование между игроками: с одним участником смысла нет
            day = awards_period == "day"
            awards_since = int(time.time()) - (86_400 if day else 7 * 86_400)
            awards = await _build(build_period_awards, storage, chat_id, awards_since, 2 if day else 3)
            if not day:  # «Лидер недели» в «Пульсе» уже называет того, кто поднялся больше всех
                awards = [a for a in awards if a["key"] != "climb"]
            block = render_awards(awards, "за сутки" if day else "за неделю")
            if block:
                text += "\n\n" + block
        parts.update(week_rows=week_rows, week_records=week_records, awards=awards)
    parts["text"] = text
    return parts


async def render_board(
    storage: Storage,
    od: OpenDota,
    chat_id: int,
    today_only: bool = False,
    refresh: bool = True,
    stratz=None,
    awards_period: str = "week",
) -> str:
    """Рейтинг + «Пульс пати» + отличия за awards_period (week — для /stats, day — для ежедневной сводки)."""
    text = (await _stats_parts(storage, od, chat_id, today_only, refresh, stratz, awards_period))["text"]
    return _with_stale(storage, chat_id, text, od) if refresh else text


def _stale_line(storage: Storage, chat_id: int, od) -> str:
    """Только строка-пометка («OpenDota недоступен с … — показаны данные на …») — для подписи к картинке."""
    text = _with_stale(storage, chat_id, "", od)
    return text.strip()


def _stats_png(title, subtitle, badge, rows, tiles, records, awards, note, big_label="MMR") -> bytes:
    """В потоке: иконки героев и аватары (кэш/CDN) + рендер таблицы рейтинга."""
    icon_loader, avatar_loader = hero_icons.shared(), avatars.shared()
    hero_ids = [r.get("hero_id") for r in rows] + [r.get("hero_id") for r in records]
    icons = icon_loader.get_many(hero_ids) if icon_loader is not None else {}
    found = avatar_loader.get_many(r.get("avatar") for r in rows) if avatar_loader is not None else {}
    return render_stats_image(title, subtitle, badge, rows, tiles, records, awards, note, icons, found, big_label)


STATS_MODES = {"stats": ("Рейтинг", "игры — с начала отслеживания, ±MMR — оценка от стартового MMR", ("ВСЁ ВРЕМЯ", ACCENT)),
               "today": ("Сегодня", "оценка MMR: старт ± шаг за игру", ("СЕГОДНЯ", ACCENT)),
               "week": ("Неделя", "оценка ±MMR за 7 дней", ("НЕДЕЛЯ", ACCENT)),
               "month": ("Месяц", "оценка ±MMR за 30 дней", ("МЕСЯЦ", ACCENT))}



async def stats_board(
    storage: Storage, od: OpenDota, chat_id: int, mode: str = "stats", stratz=None, image: Optional[bool] = None,
) -> ImageBoard:
    """Рейтинг пати (mode: stats | today | week | month): текст всегда, картинка с короткой подписью — если нарисовалась.

    Тот же отчёт, что и текстовые render_board / render_period_board: данные собираются один раз.
    mode="digest" — ежедневная сводка: собственный отчёт за последние 24 часа (daily_board), без недельных данных.
    """
    if mode == "digest":
        return await daily_board(storage, od, chat_id, stratz, image)
    title, subtitle, badge = STATS_MODES[mode]
    if mode in ("stats", "today"):
        parts = await _stats_parts(storage, od, chat_id, mode == "today", True, stratz, "week")
        summaries = parts["summaries"]
        board = ImageBoard(_with_stale(storage, chat_id, parts["text"], od))
        rows = summary_rows(summaries, today=mode == "today")
        full = mode != "today"
        tiles = party_tiles(summaries, parts["week_rows"]) if full else []
        records = record_items(parts["week_records"]) if full else []
        awards = award_items(parts["awards"]) if full else []
        caption = leader_caption(summaries, parts["week_rows"], mode)
    else:
        await refresh_for("period", storage, od, chat_id, stratz)
        since = period_since(mode, int(time.time()))
        period = await _build(build_period_leaderboard, storage, chat_id, since)
        board = ImageBoard(_with_stale(storage, chat_id, render_period_leaderboard(period, mode), od))
        info = {p.display_name: {"avatar": p.steam_avatar, "rank_tier": p.last_rank_tier,
                                 "rank_text": rank_label(p.last_rank_tier, p.last_leaderboard_rank)}
                for p in storage.list_players(chat_id)}
        rows, tiles, records, awards = period_rows(period, info), [], [], []
        caption = period_caption(period, mode)
    if want_image(storage, chat_id, image) and rows:
        note = _stale_line(storage, chat_id, od)
        plain_note = re.sub(r"<[^>]+>", "", html.unescape(note)) if note else None
        board.png = await asyncio.to_thread(
            build_png, "рейтинг", lambda: _stats_png(title, subtitle, badge, rows, tiles, records, awards, plain_note,
                               "MMR" if mode in ("stats", "today") else "±MMR"))
        if board.png is not None:
            board.caption = fit_caption(caption + (f"\n{note}" if note else ""))
    return board


async def _attach_best_build(od, report: dict) -> None:
    """Дописать лучшей игре суток билд из OpenDota (предметы, времена, шард, скипетр). Best-effort: сбой — без билда."""
    best = report.get("best_game")
    if not best or od is None or provider_down(od):
        return
    try:
        builds = await asyncio.to_thread(od.get_match_builds, best["match"]["match_id"])
    except Exception:
        log.debug("Билд лучшей игры суток не получен", exc_info=True)
        return
    build = (builds or {}).get(best["match"].get("hero_id"))
    if build:
        best["build"] = {key: build[key] for key in BUILD_FIELDS if key in build}


def _daily_png(view: dict) -> bytes:
    """В потоке: иконки героев, предметов и аватары (кэш/CDN) + рендер сводки суток."""
    icon_loader, avatar_loader = hero_icons.shared(), avatars.shared()
    hero_ids = [r.get("hero_id") for r in view["rows"]] + [r.get("hero_id") for r in view["records"]]
    hero_ids.append((view.get("best_game") or {}).get("hero_id"))
    urls = [r.get("avatar") for r in view["rows"]] + [lane.get("avatar") for lane in view["timeline"]["lanes"]]
    icons = icon_loader.get_many(hero_ids) if icon_loader is not None else {}
    found = avatar_loader.get_many(urls) if avatar_loader is not None else {}
    build = (view.get("best_game") or {}).get("build") or {}
    gear = item_icons.shared()
    item_ids = [i for i in (build.get("items") or []) + [build.get("neutral_item")] if i]
    found_items = gear.get_many(item_ids) if gear is not None and item_ids else {}
    return render_daily_image(view, icons, found, found_items)


async def daily_board(
    storage: Storage, od: OpenDota, chat_id: int, stratz=None, image: Optional[bool] = None, now: Optional[int] = None,
) -> ImageBoard:
    """Ежедневная сводка: итоги последних 24 часов до момента отправки — не календарный день и не неделя.

    Игроков обновляем без бюджета ожидания (сводка уходит по расписанию, торопиться некуда), затем всё берём из БД:
    текст всегда, картинка с короткой подписью — если в окне были игры и она нарисовалась.
    """
    summaries = await gather_summaries(storage, od, chat_id, True, stratz, complete=True)
    report = await _build(build_daily_report, storage, chat_id, int(time.time()) if now is None else now)
    await _attach_best_build(od, report)
    info = {s.display_name: {"avatar": s.avatar, "rank_tier": s.rank_tier, "rank_text": s.rank, "mmr": s.current_mmr}
            for s in summaries}
    board = ImageBoard(_with_stale(storage, chat_id, render_daily(report, info), od))
    if want_image(storage, chat_id, image) and report["totals"]["games"]:
        note = _stale_line(storage, chat_id, od)
        view = daily_card(report, info)
        view["note"] = _plain(note)
        board.png = await _render_png("сводку суток", _daily_png, view)
        if board.png is not None:
            board.caption = fit_caption(daily_caption(report) + (f"\n{note}" if note else ""))
    return board


async def warm_chat(storage: Storage, od: OpenDota, chat_id: int, stratz=None, timeout: float = 20.0) -> None:
    """Прогрев после новых игр (B4): собрать и нарисовать рейтинг чата заранее, ничего не отправляя.

    Кэш истории (B3) уже тёплый, а аватары и иконки героев подтягиваются на диск — следующий /stats
    не ждёт загрузок. Любая ошибка глушится: прогрев не должен ломать оповещения.
    """
    try:
        await asyncio.wait_for(stats_board(storage, od, chat_id, "stats", stratz, image=True), timeout)
    except Exception:
        log.debug("Прогрев чата %s не удался", chat_id, exc_info=True)


async def render_period_board(
    storage: Storage, od: OpenDota, chat_id: int, period: str, stratz=None
) -> str:
    await refresh_for("period", storage, od, chat_id, stratz)
    since = period_since(period, int(time.time()))
    rows = await _build(build_period_leaderboard, storage, chat_id, since)
    return _with_stale(storage, chat_id, render_period_leaderboard(rows, period), od)


GRAPH_CACHE_TTL = 60  # сек: повторный график того же периода (переключение кнопок туда-обратно) — мгновенно
_graph_cache: dict[tuple, tuple[float, Optional[tuple[bytes, str]]]] = {}


async def render_graph_board(
    storage: Storage, od: OpenDota, chat_id: int, period: str, stratz=None, refresh: bool = True,
    by_games: bool = False,
) -> Optional[tuple[bytes, str]]:
    """PNG-график ±MMR за период и подпись; None — за период игр не было.

    refresh=False — без запроса в OpenDota (смена периода под уже показанным графиком: данные только что обновлены).
    """
    if refresh:  # для графика нужны только свежие матчи — сводки игроков не собираем (кулдаун внутри)
        await refresh_for("graph", storage, od, chat_id, stratz)
    chat = storage.get_or_create_chat(chat_id)
    # В ключе — отпечаток данных: пришла новая игра — старая картинка не отдаётся (как и при смене шага/пояса).
    version = await asyncio.to_thread(storage.data_version, chat_id)
    cache_key = (storage.db_path, chat_id, period, chat.mmr_step, chat.tz, by_games, version)
    cached = _graph_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < GRAPH_CACHE_TTL:
        return cached[1]
    for key in [k for k, v in _graph_cache.items() if time.monotonic() - v[0] >= GRAPH_CACHE_TTL]:
        _graph_cache.pop(key, None)  # просроченные картинки не копим в памяти
    now = int(time.time())
    since = period_since(period, now)
    series = await _build(build_mmr_series, storage, chat_id, since)
    if not series:
        _graph_cache[cache_key] = (time.monotonic(), None)
        return None
    label = {"day": "за сутки", "week": "за неделю", "month": "за месяц", "year": "за год",
             "all": "за всё время"}[period]
    roster = [p.display_name for p in storage.list_players(chat_id)]  # цвет закреплён за игроком, а не за местом
    png = await _render(
        render_mmr_chart, series, f"Динамика MMR {label}", chat.tz, since, now, by_games, roster
    )
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (name, pts) in enumerate(sorted(series.items(), key=lambda kv: kv[1][-1][1], reverse=True)[:10]):  # лимит подписи фото — 1024
        games, wins, total = series_stats(pts)
        lines.append(f"{medals[i] if i < 3 else '▫️'} <b>{html.escape(name)}</b> {total:+d} · {games_word(games)} · {round(wins * 100 / games)}%")
    caption = f"📈 <b>Динамика MMR {label}</b> · <i>оценка: ±{chat.mmr_step} за игру</i>\n" + "\n".join(lines)
    if refresh:
        caption = _with_stale(storage, chat_id, caption, od)
    result = (png, caption)
    _graph_cache[cache_key] = (time.monotonic(), result)
    return result


def _weekly_png(rows, tiles, records, awards, note) -> bytes:
    """В потоке: иконка героя недели и аватары (кэш/CDN) + рендер итогов недели той же таблицей, что и рейтинг."""
    return _stats_png("Итоги недели", "оценка ±MMR за 7 дней", ("НЕДЕЛЯ", ACCENT), rows, tiles, records, awards, note, "±MMR")


async def weekly_board(storage: Storage, chat_id: int, now: int, image: Optional[bool] = None) -> ImageBoard:
    """Итоги недели (из кэша БД, сети нет): текст всегда, картинка с короткой подписью — если нарисовалась."""
    report = await _build(build_weekly_report, storage, chat_id, now)
    board = ImageBoard(render_weekly(report))
    played = [r for r in report["rows"] if r["games"] > 0]
    if want_image(storage, chat_id, image) and played:
        info = {p.display_name: {"avatar": p.steam_avatar, "rank_tier": p.last_rank_tier,
                                 "rank_text": rank_label(p.last_rank_tier, p.last_leaderboard_rank)}
                for p in storage.list_players(chat_id)}
        rows = period_rows(played, info)
        board.png = await _render_png("итоги недели", _weekly_png, rows, weekly_tiles(report), weekly_records(report),
                                      weekly_awards(report), None)
        if board.png is not None:
            board.caption = fit_caption(weekly_caption(report))
    return board


def _records_png(period: str, tiles: list, streak, note) -> bytes:
    """В потоке: иконки героев (кэш/CDN) + рендер рекордов."""
    icon_loader = hero_icons.shared()
    icons = icon_loader.get_many(t["hero_id"] for t in tiles) if icon_loader is not None else {}
    return render_records_image(PERIOD_BADGES.get(period, ""), tiles, streak, icons, note)


async def records_board(
    storage: Storage, od: OpenDota, chat_id: int, period: str, stratz=None, image: Optional[bool] = None,
) -> ImageBoard:
    """Рекорды пати: текст всегда, картинка с короткой подписью — если нарисовалась."""
    await refresh_for("records", storage, od, chat_id, stratz)
    since = period_since(period, int(time.time()))
    data = await _build(build_records, storage, chat_id, since)
    tz = storage.get_or_create_chat(chat_id).tz
    board = ImageBoard(_with_stale(storage, chat_id, render_records(data, period, tz), od))
    if want_image(storage, chat_id, image):
        note = _stale_line(storage, chat_id, od)
        tiles = record_tiles(data, tz)
        board.png = await _render_png("рекорды", _records_png, period, tiles, data.get("streak"), _plain(note))
        if board.png is not None:
            board.caption = fit_caption(records_caption(data, period) + (f"\n{note}" if note else ""))
    return board


def _contest_png(period: str, table: list, noms: list, note) -> bytes:
    """В потоке: аватары (кэш/CDN) + рендер соревнования."""
    avatar_loader = avatars.shared()
    found = avatar_loader.get_many({r.get("avatar") for r in table[:CONTEST_TABLE_LIMIT]}
                                   | {e.get("avatar") for n in noms for e in n["entries"]}) if avatar_loader is not None else {}
    return render_contest_image(period, table, noms, found, note)


async def contest_board(
    storage: Storage, od: OpenDota, chat_id: int, period: str, stratz=None, image: Optional[bool] = None,
) -> ImageBoard:
    """Соревнование чата за период: текст всегда, картинка с короткой подписью — если нарисовалась."""
    await refresh_for("records", storage, od, chat_id, stratz)
    data = await _build(build_contest, storage, chat_id, period_since(period, int(time.time())),
                        2 if period == "day" else 3)
    label = PERIOD_LABELS.get(period, "")
    board = ImageBoard(_with_stale(storage, chat_id, render_contest(label, data["standings"], data["points"]), od))
    if want_image(storage, chat_id, image):
        avatar_of = {p.display_name: p.steam_avatar for p in storage.list_players(chat_id)}
        table, noms = contest_view(data["standings"], data["points"], avatar_of)
        note = _stale_line(storage, chat_id, od)
        badge = PERIOD_BADGES.get(period, "")
        board.png = await _render_png("соревнование", _contest_png, badge, table, noms, _plain(note))
        if board.png is not None:
            board.caption = fit_caption(contest_caption(label, table, noms) + (f"\n{note}" if note else ""))
    return board


async def render_contest_text(storage: Storage, od: OpenDota, chat_id: int, period: str, stratz=None) -> str:
    return (await contest_board(storage, od, chat_id, period, stratz, image=False)).text


async def render_records_board(storage: Storage, od: OpenDota, chat_id: int, period: str, stratz=None) -> str:
    return (await records_board(storage, od, chat_id, period, stratz, image=False)).text


def _party_heroes_png(rows: list) -> bytes:
    """В потоке: иконки героев и аватары (кэш/CDN) + рендер «Любимых героев пати»."""
    icon_loader, avatar_loader = hero_icons.shared(), avatars.shared()
    hero_ids = [h["hero_id"] for r in rows for h in r["heroes"]]
    icons = icon_loader.get_many(hero_ids) if icon_loader is not None else {}
    found = avatar_loader.get_many(r.get("avatar") for r in rows) if avatar_loader is not None else {}
    return render_party_heroes_image(rows, icons, found)


async def heroes_board(storage: Storage, od: OpenDota, chat_id: int, stratz=None, image: Optional[bool] = None) -> ImageBoard:
    """Любимые герои пати: текст всегда, картинка с короткой подписью — если нарисовалась."""
    summaries = await gather_summaries(storage, od, chat_id, refresh=True, stratz=stratz, command="heroes")
    board = ImageBoard(_with_stale(storage, chat_id, render_heroes(summaries), od))
    if want_image(storage, chat_id, image) and summaries:
        rows = party_hero_rows(summaries)
        board.png = await _render_png("любимых героев", _party_heroes_png, rows)
        if board.png is not None:
            note = _stale_line(storage, chat_id, od)
            board.caption = fit_caption("🦸 <b>Любимые герои</b> · топ-3 каждого игрока" + (f"\n{note}" if note else ""))
    return board


async def render_heroes_board(storage: Storage, od: OpenDota, chat_id: int, stratz=None) -> str:
    return (await heroes_board(storage, od, chat_id, stratz, image=False)).text


def _together_png(summary, duo, players, pairs, note) -> bytes:
    """В потоке: аватары игроков (кэш/CDN) + рендер совместных игр."""
    loader = avatars.shared()
    found = loader.get_many(p.get("avatar") for p in players) if loader is not None else {}
    return render_together_image(summary, duo, players, pairs, found, note)


async def together_board(storage: Storage, od: OpenDota, chat_id: int, stratz=None, image: Optional[bool] = None) -> ImageBoard:
    """Совместные игры: текст всегда, картинка (плитки и матрица пар) — если нарисовалась."""
    # Сначала обновляем матчи всех игроков, затем считаем совместную статистику.
    await refresh_for("together", storage, od, chat_id, stratz)
    result = await _build(build_together, storage, chat_id)
    board = ImageBoard(_with_stale(storage, chat_id, render_together(result), od))
    if want_image(storage, chat_id, image):
        note = _stale_line(storage, chat_id, od)
        board.png = await _render_png("совместные игры", _together_png, *together_card(result), _plain(note))
        if board.png is not None:
            board.caption = fit_caption(together_caption(result) + (f"\n{note}" if note else ""))
    return board


async def render_together_board(storage: Storage, od: OpenDota, chat_id: int, stratz=None) -> str:
    return (await together_board(storage, od, chat_id, stratz, image=False)).text


def _player_png(card: dict) -> bytes:
    """В потоке: иконки героев и аватар (кэш/CDN) + рендер карточки игрока."""
    icon_loader, avatar_loader = hero_icons.shared(), avatars.shared()
    hero_ids = [h["hero_id"] for h in card.get("heroes") or []] + ([card["last_game"]["hero_id"]] if card.get("last_game") else [])
    icons = icon_loader.get_many(hero_ids) if icon_loader is not None else {}
    found = avatar_loader.get_many([card.get("avatar")]) if avatar_loader is not None else {}
    return render_player_image(card, icons, found)


def _mmr_values(storage: Storage, chat_id: int, player_id: int) -> list[int]:
    """Накопленное ±MMR по последним играм игрока — для линии на карточке."""
    step = storage.get_or_create_chat(chat_id).mmr_step
    return [value for _, value in stats.mmr_series(storage.get_outcomes(player_id), step)[-60:]]


async def player_board(
    storage: Storage, od: OpenDota, chat_id: int, name: str, stratz=None, image: Optional[bool] = None
) -> Optional[ImageBoard]:
    """Карточка игрока: текст всегда, картинка с короткой подписью — если нарисовалась; None — игрока нет."""
    summaries = await gather_summaries(storage, od, chat_id, refresh=True, stratz=stratz, command="player")
    comparison = build_chat_comparison(summaries)
    name_lower = name.strip().lower()
    for summary in summaries:
        if summary.display_name.lower() == name_lower or str(summary.account_id) == name.strip():
            break
    else:
        return None
    standing = standing_line(comparison, summary.display_name)
    board = ImageBoard(_with_stale(storage, chat_id, render_player_card(summary, standing=standing), od))
    if want_image(storage, chat_id, image):
        note = _stale_line(storage, chat_id, od)
        plain = re.sub(r"<[^>]+>", "", html.unescape(note)) if note else None
        player = storage.get_player_by_account_id(chat_id, summary.account_id)
        series = await _build(_mmr_values, storage, chat_id, player.id) if player is not None else []
        position = dict(comparison["players"].get(summary.display_name) or {}, size=comparison["size"])
        card = player_card(summary, position, series, plain)
        board.png = await asyncio.to_thread(build_png, "карточку игрока", lambda: _player_png(card))
        if board.png is not None:
            board.caption = fit_caption(player_caption(summary) + (f"\n{note}" if note else ""))
    return board


async def render_player_board(storage: Storage, od: OpenDota, chat_id: int, name: str, stratz=None) -> Optional[str]:
    """Карточка игрока текстом (см. player_board)."""
    board = await player_board(storage, od, chat_id, name, stratz, image=False)
    return board.text if board is not None else None


def _compare_png(rows: list, note) -> bytes:
    """В потоке: аватары игроков (кэш/CDN) + рендер сравнения."""
    loader = avatars.shared()
    found = loader.get_many(r.get("avatar") for r in rows) if loader is not None else {}
    return render_compare_image(rows, found, note)


async def compare_board(storage: Storage, od: OpenDota, chat_id: int, stratz=None, image: Optional[bool] = None) -> ImageBoard:
    """Сравнение игроков: текст всегда, картинка-таблица с местами — если нарисовалась."""
    summaries = await gather_summaries(storage, od, chat_id, refresh=True, stratz=stratz, command="compare")
    if not summaries:
        return ImageBoard(NO_PLAYERS)
    comparison = build_chat_comparison(summaries)
    board = ImageBoard(_with_stale(storage, chat_id, render_compare_table(comparison, summaries), od))
    if want_image(storage, chat_id, image):
        note = _stale_line(storage, chat_id, od)
        board.png = await _render_png("сравнение", _compare_png, compare_rows(comparison, summaries), _plain(note))
        if board.png is not None:
            board.caption = fit_caption(compare_caption(comparison, summaries) + (f"\n{note}" if note else ""))
    return board


async def render_compare_board(storage: Storage, od: OpenDota, chat_id: int, stratz=None) -> str:
    return (await compare_board(storage, od, chat_id, stratz, image=False)).text


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Разбить длинное сообщение по границам блоков (двойной перевод строки).

    Блок, который сам по себе длиннее лимита, режется жёстко на куски по `limit`,
    чтобы ни один кусок не превысил лимит Telegram.
    """
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = block if not current else current + "\n\n" + block
        if len(candidate) <= limit:
            current = candidate
            continue
        # candidate не помещается: сначала сбрасываем накопленное.
        if current:
            chunks.append(current)
            current = ""
        if len(block) <= limit:
            current = block
        else:
            # Один блок длиннее лимита — режем жёстко.
            for i in range(0, len(block), limit):
                piece = block[i : i + limit]
                if len(piece) == limit:
                    chunks.append(piece)
                else:
                    current = piece  # хвост копим дальше
    if current:
        chunks.append(current)
    return chunks


# --- герои / позиции / матч (данные из кэша БД после обновления) ---------

def _empty_players(storage: Storage, chat_id: int, name: Optional[str]) -> list[str]:
    """Имена игроков (одного или всех в чате), у которых в БД нет ни одного матча."""
    players = [storage.get_player(chat_id, name)] if name else storage.list_players(chat_id)
    return [p.display_name for p in players if p is not None and not storage.has_matches(p.id)]


def _plain(note: str) -> Optional[str]:
    return re.sub(r"<[^>]+>", "", html.unescape(note)) if note else None


def _player_heroes_png(title: str, badge, rows: list, roles: list, hidden: Optional[str], extra: int, note) -> bytes:
    """В потоке: иконки героев (кэш/CDN) + рендер «Героев игрока» (и позиций под ними)."""
    icon_loader = hero_icons.shared()
    icons = icon_loader.get_many(r["hero_id"] for r in rows[:HEROES_LIMIT]) if icon_loader is not None else {}
    return render_player_heroes_image(title, None, badge, rows, roles, icons, hidden, extra, note)


async def _render_png(what: str, fn, *args) -> Optional[bytes]:
    """Рисование в потоке с перехватом ошибок (build_png): None — картинки не будет, останется текст."""
    with perf.phase("render"):
        return await asyncio.to_thread(build_png, what, lambda: fn(*args))


async def player_heroes_board(
    storage: Storage, od: OpenDota, chat_id: int, name: str, period: str, stratz=None, image: Optional[bool] = None,
    kind: str = "heroes",
) -> Optional[ImageBoard]:
    """Герои игрока (kind="heroes": герои + позиции) или только позиции (kind="roles"); None — игрока нет."""
    await refresh_for("player_heroes" if kind == "heroes" else "roles", storage, od, chat_id, stratz)
    since = period_since(period, int(time.time()))
    result = await _build(build_player_heroes, storage, chat_id, name, since)
    if result is None:
        return None
    player, heroes = result
    roles_result = await _build(build_player_roles, storage, chat_id, name, since)
    roles = roles_result[1] if roles_result is not None else []
    if kind == "roles":
        text = render_roles(player.display_name, roles, period)
    else:
        text = render_player_heroes(player.display_name, period, heroes)
        if not heroes and not storage.has_matches(player.id):
            text += "\n" + HIDDEN_HINT
        if roles:
            text += "\n\n" + render_roles(player.display_name, roles, period)
    board = ImageBoard(_with_stale(storage, chat_id, text, od))
    if want_image(storage, chat_id, image):
        note = _stale_line(storage, chat_id, od)
        shown = hero_rows(heroes) if kind == "heroes" else []
        title = (f"Герои · {player.display_name}" if kind == "heroes" else f"Позиции · {player.display_name}")
        hidden = HIDDEN_NOTE if kind == "heroes" and not heroes and not storage.has_matches(player.id) else None
        extra = max(len(heroes) - HEROES_LIMIT, 0)
        badge = (PERIOD_BADGES.get(period, ""), ACCENT)
        rr = role_rows(roles)
        board.png = await _render_png("героев игрока", _player_heroes_png, title, badge, shown, rr, hidden, extra, _plain(note))
        if board.png is not None:
            caption = heroes_caption(player.display_name, period, shown) if kind == "heroes" else roles_caption(player.display_name, period, rr)
            board.caption = fit_caption(caption + (f"\n{note}" if note else ""))
    return board


HIDDEN_NOTE = "История матчей закрыта у OpenDota — игры могли не загрузиться."


async def render_player_heroes_board(
    storage: Storage, od: OpenDota, chat_id: int, name: str, period: str, stratz=None
) -> str:
    board = await player_heroes_board(storage, od, chat_id, name, period, stratz, image=False)
    return NOT_FOUND if board is None else board.text


async def render_roles_board(
    storage: Storage, od: OpenDota, chat_id: int, name: str, period: str = "all", stratz=None
) -> str:
    board = await player_heroes_board(storage, od, chat_id, name, period, stratz, image=False, kind="roles")
    return NOT_FOUND if board is None else board.text


def _alert_png(event: dict, tz: str) -> bytes:
    """В потоке: иконки героев и аватары (кэш/CDN) + рендер картинки оповещения."""
    icons, loader, gear = hero_icons.shared(), avatars.shared(), item_icons.shared()
    rows = event.get("rows") or []
    found_icons = icons.get_many(r.get("hero_id") for r in rows) if icons is not None else {}
    found_avatars = loader.get_many(r.get("avatar") for r in rows) if loader is not None else {}
    item_ids = [i for r in rows for i in (r.get("items") or []) + [r.get("neutral_item")]]
    found_items = gear.get_many(item_ids) if gear is not None else {}
    return render_alert_image(event, tz, found_icons, found_avatars, found_items)


async def alert_board(event: dict, tz: str, image: bool = True, od=None) -> ImageBoard:
    """Оповещение о конце матча: текст всегда, картинка с короткой подписью — если нарисовалась.

    od — клиент OpenDota: для картинки подтягивает билд и фарм из матча (best-effort, без сети — картинка без билда).
    """
    board = ImageBoard(render_game_alert(event))
    if image:
        if od is not None:
            await asyncio.to_thread(enrich_alert_items, od, event)
        board.png = await asyncio.to_thread(build_png, "оповещение о матче", lambda: _alert_png(event, tz))
        if board.png is not None:
            board.caption = alert_caption(event)
    return board


def _cached_as_match(view: dict) -> dict:
    """Матч из кэша БД (одна строка игрока) → формат Stratz.get_match с одним игроком — для картинки."""
    player, row = view["player"], view["match"]
    me = {key: row.get(key) for key in (
        "hero_id", "kills", "deaths", "assists", "position", "lane", "imp", "gpm", "xpm", "net_worth",
        "hero_damage", "tower_damage", "hero_healing", "last_hits", "denies", "level",
    )}
    me.update(account_id=player.account_id, name=player.display_name, is_radiant=row["player_slot"] < 128)
    return {"match_id": row["match_id"], "start_time": row.get("start_time"), "duration": row.get("duration"),
            "radiant_win": bool(row["radiant_win"]), "players": [me]}


def _warm_match(od, match_id: int) -> None:
    """В потоке: прогреть кэш матча OpenDota (билды игроков для картинки) — пока идёт запрос к Stratz."""
    if provider_down(od):
        return
    try:
        od.get_match(match_id)
    except Exception:
        log.debug("Прогрев матча %s в OpenDota не удался", match_id, exc_info=True)


MATCH_REFRESH_WAIT = 6.0  # сек: «последний матч» ждёт обновление дольше обычных команд — он про свежую игру


def _render_match_png(match: dict, tracked: dict, focus, tz: str, icons, od=None) -> bytes:
    """В потоке: билды игроков (OpenDota, best-effort) + иконки героев и предметов (кэш/CDN) + рендер картинки."""
    if od is not None:
        enrich_match_builds(od, match)
    source = icons if icons is not None else hero_icons.shared()
    found = source.get_many(p.get("hero_id") for p in match["players"]) if source is not None else {}
    gear = item_icons.shared()
    item_ids = [i for p in match["players"]
                for i in (p.get("items") or []) + [p.get("neutral_item")] + (p.get("bear_items") or []) + [p.get("bear_neutral")]]
    found_items = gear.get_many(item_ids) if gear is not None and item_ids else {}
    return render_match_image(match, tracked, focus, tz, found, found_items, fmt="JPEG")


async def match_board(
    storage: Storage, od: OpenDota, chat_id: int, name: Optional[str], match_id: Optional[int], stratz=None,
    image: Optional[bool] = None, icons=None,
) -> MatchBoard:
    """Карточка матча. С match_id — любой матч (не обязательно игроков пати), через Stratz.

    Без match_id — последний матч игрока (или самого свежего в чате). Если Stratz недоступен,
    для своих игроков показываем карточку из кэша БД. image=True — ещё и картинка (сбой рендера → только текст);
    None — по настройке чата («🖼 Отчёты»).
    """
    tracked = {p.account_id: p.display_name for p in storage.list_players(chat_id)}
    focus = None
    cached = None
    latest = match_id is None  # «последний матч» зависит от свежести данных — там уместна пометка об устаревании
    if match_id is None:
        await refresh_with_budget(storage, od, chat_id, stratz, budget=MATCH_REFRESH_WAIT)
        view = await _build(build_match_view, storage, chat_id, name, None)
        if view is None:
            empty = _empty_players(storage, chat_id, name)
            who = html.escape(", ".join(empty)) if empty else "участников пати"  # уйдёт с parse_mode=HTML
            return MatchBoard(f"Ранкед-матчей не видно ({who}). " + HIDDEN_HINT)
        cached = view
        match_id = view["match"]["match_id"]
        focus = view["player"].account_id
    elif name:
        target = storage.get_player(chat_id, name)
        if target is None:
            return MatchBoard(NOT_FOUND)
        focus = target.account_id

    full = None
    warm = None
    if stratz is not None:
        if want_image(storage, chat_id, image):  # билды для картинки берём у OpenDota параллельно со Stratz
            warm = asyncio.create_task(asyncio.to_thread(_warm_match, od, match_id))
        try:
            full = await asyncio.to_thread(stratz.get_match, match_id)
        except Exception as exc:
            log_network_error(log, f"Stratz: не удалось получить матч {match_id}", exc, health=getattr(stratz, "health", None))
        if warm is not None:
            await warm
    if full is None and cached is None and name:  # матч своего игрока по id — без Stratz из кэша БД
        cached = await _build(build_match_view, storage, chat_id, name, match_id)
    tz = storage.get_or_create_chat(chat_id).tz
    if full is not None:
        if focus is None:
            focus = next((p["account_id"] for p in full["players"] if p["account_id"] in tracked), None)
        board = MatchBoard(render_full_match(full, tracked, focus, tz), match_id=match_id, focus=focus)
        match = full
    elif cached is not None:
        board = MatchBoard(render_match_card(cached, tz), match_id=match_id, focus=focus)
        match = _cached_as_match(cached)
    elif stratz is None:
        return MatchBoard(STRATZ_OFF)
    else:
        return MatchBoard(f"Матч {match_id} не найден в Stratz (возможно, не ранкед или скрыт).")
    if want_image(storage, chat_id, image):
        try:
            board.png = await _render(_render_match_png, match, tracked, focus, tz, icons, od)
            board.caption = render_match_caption(match, tracked, focus, tz)
        except Exception:
            log.exception("Не удалось нарисовать матч %s — отвечаем текстом", match_id)
            board.png = board.caption = None
    if latest:
        health = getattr(od, "health", None)
        note = outage_note(health.status() if health is not None else None,
                           storage.list_players(chat_id), int(time.time()), tz)
        if note:
            board.text += "\n\n" + note
            if board.caption is not None and len(board.caption) + len(note) + 2 <= CAPTION_LIMIT:
                board.caption += "\n" + note
    return board


async def render_match_board(
    storage: Storage, od: OpenDota, chat_id: int, name: Optional[str], match_id: Optional[int], stratz=None
) -> str:
    """Карточка матча текстом (см. match_board)."""
    return (await match_board(storage, od, chat_id, name, match_id, stratz, image=False)).text


def _hero_png(hero_id: int, title: str, label: str, rows: list, note) -> bytes:
    """В потоке: иконка героя и аватары игроков (кэш/CDN) + рендер «Героя и пати на нём»."""
    icon_loader, avatar_loader = hero_icons.shared(), avatars.shared()
    icons = icon_loader.get_many([hero_id]) if icon_loader is not None else {}
    found = avatar_loader.get_many(r.get("avatar") for r in rows) if avatar_loader is not None else {}
    return render_hero_image(hero_id, title, label, rows, icons, found, note)


def hero_not_found(query: str) -> str:
    return f"Герой «{html.escape(query)}» не найден. Пишите по-английски, например: /heroes Axe"  # уйдёт как HTML


async def hero_board(
    storage: Storage, od: OpenDota, chat_id: int, query: str, period: str, stratz=None, image: Optional[bool] = None,
) -> HeroBoard:
    """Герой и кто из пати на нём играл: текст всегда, картинка — если нарисовалась. `board.hero_id` — для кнопок."""
    hero_id = find_hero(query)
    if hero_id is None:
        return HeroBoard(hero_not_found(query))
    await refresh_for("hero", storage, od, chat_id, stratz)
    since = period_since(period, int(time.time()))
    entries = await _build(build_hero_view, storage, chat_id, hero_id, since)
    board = HeroBoard(_with_stale(storage, chat_id, render_hero_detail(hero_id, period, entries), od), hero_id=hero_id)
    if want_image(storage, chat_id, image):
        note = _stale_line(storage, chat_id, od)
        rows = hero_detail_rows(entries)
        label = {"day": "за сутки", "week": "за неделю", "month": "за месяц", "year": "за год", "all": "всё время"}.get(period, "")
        board.png = await _render_png("героя", _hero_png, hero_id, hero_name(hero_id), label, rows, _plain(note))
        if board.png is not None:
            board.caption = fit_caption(hero_caption(hero_name(hero_id), period, entries) + (f"\n{note}" if note else ""))
    return board


async def render_hero_board(
    storage: Storage, od: OpenDota, chat_id: int, query: str, period: str, stratz=None
) -> str:
    return (await hero_board(storage, od, chat_id, query, period, stratz, image=False)).text
