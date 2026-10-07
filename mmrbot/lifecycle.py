"""Жизненный цикл чата: бота добавили/убрали, группа стала супергруппой."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import ChatMemberUpdated, Message

from mmrbot.storage import Storage

log = logging.getLogger(__name__)
router = Router()

GONE = {"left", "kicked"}


def _status(member) -> str:
    status = getattr(member, "status", "")
    return str(getattr(status, "value", status))


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated, storage: Storage) -> None:
    """Бота убрали из чата (или заблокировали в личке) — перестаём опрашивать его игроков и слать сводки.

    Данные не удаляем: вернут бота — рейтинг и история на месте.
    """
    status = _status(event.new_chat_member)
    if status in GONE:
        storage.set_chat_active(event.chat.id, False)
        log.info("Бот убран из чата %s — чат приостановлен", event.chat.id)
    else:
        storage.set_chat_active(event.chat.id, True)


@router.message(F.migrate_to_chat_id)
async def on_migrate(message: Message, storage: Storage) -> None:
    """Группу превратили в супергруппу: у чата новый id, переносим на него игроков и настройки."""
    new_id = message.migrate_to_chat_id
    if storage.migrate_chat(message.chat.id, new_id):
        log.info("Чат %s стал супергруппой %s — данные перенесены", message.chat.id, new_id)
