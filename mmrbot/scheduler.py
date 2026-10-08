"""Ежедневный дайджест: раз в час проверяем чаты и шлём тем, у кого настал их день.

Момент прогона снимается один раз (now_utc), поэтому долгий цикл не «сползает» по часу.
Идемпотентность на день — через last_digest_date: дайджест уходит один раз в локальные
сутки, а при простое, накрывшем нужный час, досылается при первом же прогоне после часа.
"""
from __future__ import annotations

import asyncio
import logging
import time
from functools import partial
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytz
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramMigrateToChat
from aiogram.types import BufferedInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from mmrbot.boards import ImageBoard
from mmrbot.delivery import send_with_retry
from mmrbot.health import log_network_error, provider_down
from mmrbot.keyboards import alert_buttons
from mmrbot.opendota import OpenDota
from mmrbot.backup import backup_db
from mmrbot.formatting import (
    render_achievement_alert,
    render_start_alert,
    render_steam_change,
)
from mmrbot.status import write_heartbeat
from mmrbot.service import _chat_lock, alert_board, refresh_only, split_message, stats_board, warm_chat, weekly_board
from mmrbot.storage import Chat, Storage
from mmrbot.tags import sync_member_tags
from mmrbot.tracker import (
    backfill_opendota,
    backfill_stratz,
    detect_new_games,
    detect_presence,
    detect_steam_changes,
    refresh_heroes,
)

log = logging.getLogger(__name__)


async def send_board(bot: Bot, chat_id: int, board: ImageBoard, markup=None) -> None:
    """Отчёт в чат: фото с подписью; нет картинки или Telegram её не принял — тот же отчёт текстом.

    Ошибки доступа к чату и сети летят наверх — решает вызывающий код (повтор в следующем опросе и т. п.).
    """
    if board.png is not None:
        try:
            photo = BufferedInputFile(board.png, filename="card.png")
            await send_with_retry(partial(bot.send_photo, chat_id, photo, caption=board.caption, parse_mode="HTML",
                                          reply_markup=markup))
            return
        except TelegramBadRequest:  # фото не принято (формат, размер, подпись) — текстом; «чат не найден» повторится и уйдёт наверх
            log.warning("Telegram не принял картинку для чата %s — шлём текстом", chat_id, exc_info=True)
    chunks = split_message(board.text)
    for i, chunk in enumerate(chunks):  # без картинки длинный отчёт (много игроков) идёт несколькими сообщениями
        last = markup if i == len(chunks) - 1 else None
        await send_with_retry(partial(bot.send_message, chat_id, chunk, parse_mode="HTML", reply_markup=last))


def due_local_date(chat: Chat, now_utc: datetime) -> Optional[str]:
    """Вернуть ISO-дату локальных суток чата, если дайджест сейчас нужен, иначе None.

    Нужен, если по локальному времени час >= digest_hour и за эти локальные сутки
    дайджест ещё не отправляли.
    """
    try:
        tz = pytz.timezone(chat.tz)
    except Exception:
        tz = pytz.timezone("Europe/Moscow")
    local = now_utc.astimezone(tz)
    today = local.date().isoformat()
    if chat.last_digest_date == today:
        return None
    if local.hour < chat.digest_hour:
        return None
    return today


def due_weekly_key(chat: Chat, now_utc: datetime) -> Optional[str]:
    """Ключ ISO-недели (ГГГГ-Wнн), если недельную сводку пора слать (понедельник после часа сводки)."""
    try:
        tz = pytz.timezone(chat.tz)
    except Exception:
        tz = pytz.timezone("Europe/Moscow")
    local = now_utc.astimezone(tz)
    if local.weekday() != 0 or local.hour < chat.digest_hour:
        return None
    iso = local.isocalendar()
    key = f"{iso[0]}-W{iso[1]:02d}"
    return None if chat.last_weekly == key else key


IDLE_DIGEST_SEC = 86_400  # за столько секунд без единой игры сводку не шлём — в ней нечего читать


def chat_gone(storage: Storage, chat_id: int, exc: Exception) -> bool:
    """Разобрать отказ Telegram при отправке в чат; True — чат больше недоступен под этим id.

    Бота выгнали/заблокировали → чат приостанавливается (его игроков перестаём опрашивать).
    Группа стала супергруппой → данные переезжают на новый id.
    """
    if isinstance(exc, TelegramMigrateToChat):
        storage.migrate_chat(chat_id, exc.migrate_to_chat_id)
        log.info("Чат %s стал супергруппой %s — данные перенесены", chat_id, exc.migrate_to_chat_id)
        return True
    if isinstance(exc, TelegramForbiddenError):
        storage.set_chat_active(chat_id, False)
        log.info("Бот потерял доступ к чату %s — чат приостановлен", chat_id)
        return True
    return False


async def send_digest(bot: Bot, storage: Storage, od: OpenDota, chat: Chat, due_date: str, stratz=None) -> None:
    """Собрать и отправить дайджест в один чат; отметить сутки отправленными.

    Если бота выгнали из чата/заблокировали (Forbidden / чат не найден), отмечаем сутки
    сделанными: иначе каждый час повторялось бы полное обновление игроков впустую.
    """
    try:
        await refresh_only(storage, od, chat.chat_id, stratz)  # сначала данные: тихий день не стоит рисования картинки
        last = storage.last_activity(chat.chat_id)
        if last is None or time.time() - last > IDLE_DIGEST_SEC:
            storage.set_last_digest_date(chat.chat_id, due_date)  # никто не играл — не шумим
            return
        board = await stats_board(storage, od, chat.chat_id, "digest", stratz)
        await send_board(bot, chat.chat_id, board)
        storage.set_last_digest_date(chat.chat_id, due_date)
    except (TelegramForbiddenError, TelegramMigrateToChat) as exc:
        storage.set_last_digest_date(chat.chat_id, due_date)
        chat_gone(storage, chat.chat_id, exc)
    except TelegramBadRequest as exc:
        if "chat not found" in str(exc).lower():
            log.warning("Чат %s не найден — дайджест пропущен на сегодня", chat.chat_id)
            storage.set_last_digest_date(chat.chat_id, due_date)
        else:
            log.exception("Не удалось отправить дайджест в чат %s", chat.chat_id)
    except Exception:  # один битый чат не должен рушить остальные
        log.exception("Не удалось отправить дайджест в чат %s", chat.chat_id)


def setup_scheduler(
    bot: Bot, storage: Storage, od: OpenDota, stratz=None, backup_keep: int = 7, steam=None,
    heartbeat_path: Optional[str] = None,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    keyless = not getattr(od, "api_key", None)

    async def heartbeat() -> None:
        """Отметка «жив» для healthcheck контейнера (mtime файла) + JSON со снимком состояния — тот же, что в /status."""
        try:
            await asyncio.to_thread(write_heartbeat, heartbeat_path, storage, od, stratz)
        except OSError:
            log.debug("Не удалось записать heartbeat %s", heartbeat_path, exc_info=True)

    if heartbeat_path:
        scheduler.add_job(heartbeat, "interval", seconds=60, next_run_time=datetime.now(timezone.utc))

    async def hourly_digest() -> None:
        now_utc = datetime.now(timezone.utc)  # снимок момента прогона — один на все чаты
        for chat in storage.list_chats():
            due_date = due_local_date(chat, now_utc)
            if due_date is None or not chat.notify_digest:
                continue
            if not storage.list_players(chat.chat_id):
                continue
            await send_digest(bot, storage, od, chat, due_date, stratz)

    async def stratz_backfill() -> None:
        if stratz is None:
            return
        if provider_down(stratz):
            log.debug("Stratz недоступен — дозаполнение пропущено до следующего тика")
            return
        try:
            await asyncio.to_thread(backfill_stratz, storage, stratz)
        except Exception as exc:
            log_network_error(log, "Фоновое дозаполнение Stratz не удалось", exc, health=getattr(stratz, "health", None))

    async def opendota_backfill() -> None:
        if provider_down(od):
            log.debug("OpenDota недоступен — обогащение матчей пропущено до следующего тика")
            return
        try:
            await asyncio.to_thread(backfill_opendota, storage, od)
        except Exception as exc:
            log_network_error(log, "Фоновое обогащение матчей OpenDota не удалось", exc, health=getattr(od, "health", None))

    def retry_heroes_in_an_hour() -> None:
        """OpenDota недоступен — справочник героев догоним через час, а не ждём следующих суток."""
        scheduler.add_job(
            heroes_refresh, "date", run_date=datetime.now(timezone.utc) + timedelta(hours=1),
            id="heroes_retry", replace_existing=True,
        )

    async def heroes_refresh() -> None:
        """Справочник героев: раз в сутки и вскоре после старта; при недоступном OpenDota — повтор через час."""
        if provider_down(od):
            log.debug("OpenDota недоступен — обновление справочника героев перенесено на +1 ч")
            retry_heroes_in_an_hour()
            return
        try:
            added = await asyncio.to_thread(refresh_heroes, od)
            if added:
                log.info("Справочник героев пополнен: +%d", added)
        except Exception as exc:
            log_network_error(log, "Обновление справочника героев не удалось", exc, health=getattr(od, "health", None))
            retry_heroes_in_an_hour()

    async def steam_watch() -> None:
        """Оповещения о смене ника/аватарки Steam (профили берём из OpenDota)."""
        if provider_down(od):
            log.debug("OpenDota недоступен — проверка Steam-профилей пропущена до следующего тика")
            return
        try:
            events = await asyncio.to_thread(detect_steam_changes, storage, od)
        except Exception as exc:
            log_network_error(log, "Проверка смены Steam-профилей не удалась", exc, health=getattr(od, "health", None))
            return
        for event in events:
            text = render_steam_change(event["player"], event["changes"])
            avatar = event["profile"].get("avatarfull")
            try:
                if event["changes"].get("avatar") and avatar:
                    await send_with_retry(partial(bot.send_photo, event["chat_id"], avatar, caption=text, parse_mode="HTML"))
                else:
                    await send_with_retry(partial(bot.send_message, event["chat_id"], text, parse_mode="HTML"))
            except Exception as exc:
                if not chat_gone(storage, event["chat_id"], exc):
                    log.warning("Не удалось отправить оповещение Steam в чат %s", event["chat_id"], exc_info=True)

    async def tags_sync() -> None:
        """Теги участников с их MMR (чаты с /tags on); MMR берётся из кэша БД."""
        now = int(datetime.now(timezone.utc).timestamp())
        for chat in storage.list_chats():
            if not chat.tag_mmr:
                continue
            try:
                await sync_member_tags(bot, storage, chat.chat_id, now)
            except Exception:
                log.exception("Обновление тегов в чате %s не удалось", chat.chat_id)

    scheduler.add_job(tags_sync, "interval", minutes=30, misfire_grace_time=300, max_instances=1,
                      next_run_time=datetime.now(timezone.utc) + timedelta(seconds=120))
    scheduler.add_job(heroes_refresh, "cron", hour=5, minute=10, misfire_grace_time=3600)
    scheduler.add_job(heroes_refresh, "date", run_date=datetime.now(timezone.utc) + timedelta(seconds=45))

    # Каждые 30 минут сверяем ник/аватарку (без ключа OpenDota — раз в час: это запрос на каждого игрока);
    # первый прогон через минуту после старта (заполняет базу).
    scheduler.add_job(
        steam_watch, "interval", minutes=60 if keyless else 30, misfire_grace_time=300, max_instances=1,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=60),
    )

    async def game_watch() -> None:
        """Оповещения о новых играх и достижениях (по матчам не старше нескольких часов)."""
        now = int(datetime.now(timezone.utc).timestamp())
        for chat in storage.list_chats():
            if not chat.notify_games or not storage.list_players(chat.chat_id):
                continue
            try:
                async with _chat_lock(chat.chat_id):
                    events = await asyncio.to_thread(detect_new_games, storage, od, chat, now, stratz, False)
            except Exception as exc:
                log_network_error(log, f"Проверка новых игр в чате {chat.chat_id} не удалась", exc,
                                  health=getattr(od, "health", None))
                continue
            warm = False
            for event in events:
                if event["kind"] == "match":
                    board = await alert_board(event, chat.tz, image=not chat.prefer_text)
                    markup = alert_buttons(event["match_id"])
                else:
                    board, markup = ImageBoard(render_achievement_alert(event)), None
                delivered = True
                try:
                    await send_board(bot, chat.chat_id, board, markup)
                except (TelegramForbiddenError, TelegramBadRequest, TelegramMigrateToChat) as exc:
                    # Чат недоступен или сообщение не принято — повтор не поможет, не зацикливаемся.
                    if chat_gone(storage, chat.chat_id, exc):
                        break
                    log.warning("Оповещение в чат %s отклонено Telegram", chat.chat_id, exc_info=True)
                except Exception:  # сеть/лимит Telegram: матч остаётся неоповещённым и уйдёт в следующем опросе
                    delivered = False
                    log.warning("Не удалось отправить оповещение в чат %s", chat.chat_id, exc_info=True)
                if delivered:
                    storage.mark_notified_matches(event.get("pending") or [])
                    warm = warm or event["kind"] == "match"
            if warm:  # пользователь, открывший /stats после оповещения, получает готовое
                await warm_chat(storage, od, chat.chat_id, stratz)

    async def presence_watch() -> None:
        """Оповещения «зашёл в Dota 2» (Steam Web API); без ключа задача не регистрируется."""
        try:
            events = await asyncio.to_thread(detect_presence, storage, steam, int(datetime.now(timezone.utc).timestamp()))
        except Exception as exc:  # текст ошибки Steam-клиента ключа не содержит
            log.warning("Проверка статуса Steam не удалась: %s", exc)
            return
        for event in events:
            try:
                start_text = render_start_alert(event)
                await send_with_retry(partial(bot.send_message, event["chat_id"], start_text, parse_mode="HTML"))
            except Exception as exc:
                if not chat_gone(storage, event["chat_id"], exc):
                    log.warning("Не удалось отправить оповещение о заходе в Dota в чат %s", event["chat_id"], exc_info=True)

    async def weekly_summary() -> None:
        now_utc = datetime.now(timezone.utc)
        for chat in storage.list_chats():
            key = due_weekly_key(chat, now_utc)
            if key is None or not chat.notify_weekly or not storage.list_players(chat.chat_id):
                continue
            try:
                board = await weekly_board(storage, chat.chat_id, int(now_utc.timestamp()))
                await send_board(bot, chat.chat_id, board)
                storage.set_last_weekly(chat.chat_id, key)
            except (TelegramForbiddenError, TelegramBadRequest, TelegramMigrateToChat) as exc:
                log.warning("Недельная сводка в чат %s не доставлена — пропускаю неделю", chat.chat_id)
                storage.set_last_weekly(chat.chat_id, key)
                chat_gone(storage, chat.chat_id, exc)
            except Exception:
                log.exception("Недельная сводка в чат %s не удалась", chat.chat_id)

    async def daily_backup() -> None:
        try:
            await asyncio.to_thread(backup_db, storage.db_path, backup_keep)
        except Exception:
            log.exception("Бэкап БД не удался")

    # Новые игры: каждые 4 минуты (OpenDota-кулдаун внутри не даёт дёргать API чаще раза в 2 минуты на игрока;
    # без ключа и пока пати не играет — не чаще раза в 10 минут, см. tracker.GAME_IDLE_COOLDOWN).
    scheduler.add_job(game_watch, "interval", minutes=4, misfire_grace_time=120, max_instances=1,
                      next_run_time=datetime.now(timezone.utc) + timedelta(seconds=90))
    if steam is not None:
        scheduler.add_job(presence_watch, "interval", minutes=2, misfire_grace_time=120, max_instances=1,
                          next_run_time=datetime.now(timezone.utc) + timedelta(seconds=75))
    scheduler.add_job(weekly_summary, "cron", minute=5, misfire_grace_time=300)
    # Бэкап БД: раз в сутки ночью + один раз вскоре после старта (если за сегодня копии ещё нет).
    scheduler.add_job(daily_backup, "cron", hour=4, minute=30, misfire_grace_time=3600)
    scheduler.add_job(daily_backup, "date", run_date=datetime.now(timezone.utc) + timedelta(seconds=20))

    # Бэклог перф/бенчмарков (по 1 запросу на матч) разгребаем фоном, а не в /stats.
    scheduler.add_job(opendota_backfill, "interval", minutes=2, misfire_grace_time=120, max_instances=1)

    # Каждые 3 минуты дозаполняем позиции/IMP по истории (лимиты Stratz это выдерживают).
    scheduler.add_job(stratz_backfill, "interval", minutes=3, misfire_grace_time=120, max_instances=1)

    # Раз в час на :00; misfire_grace_time — переживаем короткие простои.
    scheduler.add_job(hourly_digest, "cron", minute=0, misfire_grace_time=300)
    return scheduler
