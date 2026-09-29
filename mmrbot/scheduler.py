"""Ежедневный дайджест: раз в час проверяем чаты и шлём тем, у кого настал их день.

Момент прогона снимается один раз (now_utc), поэтому долгий цикл не «сползает» по часу.
Идемпотентность на день — через last_digest_date: дайджест уходит один раз в локальные
сутки, а при простое, накрывшем нужный час, досылается при первом же прогоне после часа.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import pytz
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from mmrbot.opendota import OpenDota
from mmrbot.service import render_board, split_message
from mmrbot.storage import Chat, Storage

log = logging.getLogger(__name__)


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


def setup_scheduler(bot: Bot, storage: Storage, od: OpenDota) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    async def hourly_digest() -> None:
        now_utc = datetime.now(timezone.utc)  # снимок момента прогона — один на все чаты
        for chat in storage.list_chats():
            due_date = due_local_date(chat, now_utc)
            if due_date is None:
                continue
            if not storage.list_players(chat.chat_id):
                continue
            try:
                text = await render_board(storage, od, chat.chat_id, today_only=False, refresh=True)
                for chunk in split_message("🌅 <b>Ежедневный дайджест</b>\n\n" + text):
                    await bot.send_message(chat.chat_id, chunk, parse_mode="HTML")
                storage.set_last_digest_date(chat.chat_id, due_date)
            except Exception:  # один битый чат не должен рушить остальные
                log.exception("Не удалось отправить дайджест в чат %s", chat.chat_id)

    # Раз в час на :00; misfire_grace_time — переживаем короткие простои.
    scheduler.add_job(hourly_digest, "cron", minute=0, misfire_grace_time=300)
    return scheduler
