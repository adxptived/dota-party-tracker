"""Кто может пользоваться ботом и управлять чатом.

- ChatGateMiddleware — белый список чатов (ALLOWED_CHATS): у бота общий на всех лимит запросов OpenDota,
  посторонний чат с десятком игроков оставил бы своих без свежих данных.
- may_manage — настройки чата и удаление игроков в группе доступны админам (если чат это не отключил).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError

log = logging.getLogger(__name__)

ADMIN_STATUSES = {"creator", "administrator"}
ADMIN_CACHE_TTL = 60  # сек: серия нажатий в настройках не превращается в серию запросов к Telegram
DENIED = "🔒 Это может сделать только админ чата."
NOT_ALLOWED = "🔒 Это приватный бот: он работает только в чатах своего владельца."

_admin_cache: dict[tuple[int, int], tuple[float, bool]] = {}


def _is_private(chat) -> bool:
    return getattr(chat, "type", "private") == "private"


async def is_chat_admin(bot, chat, user, sender_chat=None) -> bool:
    """Админ ли пользователь в этом чате. В личке управлять может её владелец — то есть всегда да.

    Анонимный админ пишет от имени самого чата (sender_chat == chat). Не удалось спросить Telegram —
    считаем, что не админ: лучше отказать в настройке, чем дать стереть историю кому попало.
    """
    if _is_private(chat):
        return True
    if sender_chat is not None and getattr(sender_chat, "id", None) == chat.id:
        return True
    if user is None or bot is None:
        return False
    key = (chat.id, user.id)
    cached = _admin_cache.get(key)
    if cached and time.monotonic() - cached[0] < ADMIN_CACHE_TTL:
        return cached[1]
    try:
        member = await bot.get_chat_member(chat.id, user.id)
    except TelegramAPIError:
        log.warning("Не удалось проверить права пользователя %s в чате %s", user.id, chat.id, exc_info=True)
        return False
    result = str(getattr(getattr(member, "status", None), "value", getattr(member, "status", ""))) in ADMIN_STATUSES
    _admin_cache[key] = (time.monotonic(), result)
    return result


async def may_manage(bot, storage, chat, user, sender_chat=None) -> bool:
    """Можно ли пользователю менять настройки чата и удалять чужих игроков."""
    if _is_private(chat) or not storage.get_or_create_chat(chat.id).admin_only:
        return True
    return await is_chat_admin(bot, chat, user, sender_chat)


class ChatGateMiddleware(BaseMiddleware):
    """Внешний фильтр сообщений и нажатий: чужие чаты отсекает, свой «спящий» чат будит.

    allowed пуст — бот открыт всем. Чат, откуда бота убирали (active=0), снова становится активным,
    как только из него пришло сообщение: значит, бота вернули.
    """

    def __init__(self, allowed=frozenset(), storage=None) -> None:
        self.allowed = frozenset(allowed)
        self.storage = storage

    async def __call__(self, handler, event, data):
        chat = getattr(event, "chat", None) or getattr(getattr(event, "message", None), "chat", None)
        if chat is None:
            return await handler(event, data)
        if self.allowed and chat.id not in self.allowed:
            await self._refuse(event, chat)
            return None
        if self.storage is not None:
            try:
                self.storage.set_chat_active(chat.id, True)
            except Exception:
                log.warning("Не удалось отметить чат %s активным", chat.id, exc_info=True)
        return await handler(event, data)

    @staticmethod
    async def _refuse(event, chat) -> None:
        """В личке на команду отвечаем один раз понятным отказом; в группах молчим (не шумим в чужом чате)."""
        try:
            if hasattr(event, "data"):  # CallbackQuery
                await event.answer(NOT_ALLOWED, show_alert=True)
            elif _is_private(chat) and (getattr(event, "text", None) or "").startswith("/"):
                await event.answer(NOT_ALLOWED)
        except Exception:
            pass
