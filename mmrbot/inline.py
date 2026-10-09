"""Inline-режим: `@бот Вася` в любом чате → карточка игрока.

Видны только игроки из чатов, где пользователь привязан к игроку командой /me, — чужие чаты не светятся.
Карточки берутся из БД (без обращений к OpenDota): inline-запрос нужно отвечать за секунды.
Картинкой карточка уходит, если задан INLINE_CACHE_CHAT: inline-результат с фото принимает только file_id,
поэтому PNG один раз заливается в этот чат (бот в нём должен быть). Иначе — текстовая карточка.
Включается у @BotFather: /setinline.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
from typing import Awaitable, Callable, Optional

from aiogram import Bot, Router
from aiogram.types import (
    BufferedInputFile, InlineQuery, InlineQueryResultArticle, InlineQueryResultCachedPhoto,
    InlineQueryResultsButton, InputTextMessageContent,
)

from mmrbot import service
from mmrbot.storage import Player, Storage

log = logging.getLogger(__name__)
router = Router()

MAX_RESULTS = 10
CACHE_TIME = 30  # сек: Telegram не переспрашивает бота об одном и том же запросе
HINT = "Привяжите себя к игроку: /me в чате"
Upload = Callable[[bytes, str], Awaitable[str]]  # (png, подпись) → file_id

_file_ids: dict[str, str] = {}  # sha1 картинки → file_id в чате-хранилище


def visible_players(storage: Storage, user_id: int, query: str) -> list[tuple[int, Player]]:
    """[(чат, игрок)] из чатов пользователя, по нику (подстрока, без @ и регистра); аккаунт — один раз."""
    needle = query.strip().lstrip("@").lower()
    seen: set[int] = set()
    found: list[tuple[int, Player]] = []
    for chat_id in storage.user_chats(user_id):
        for player in storage.list_players(chat_id):
            if player.account_id in seen or needle not in player.display_name.lower():
                continue
            seen.add(player.account_id)
            found.append((chat_id, player))
    return found[:MAX_RESULTS]


def _plain(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


async def build_results(storage: Storage, user_id: int, query: str, upload: Optional[Upload] = None) -> list:
    results = []
    for chat_id, player in visible_players(storage, user_id, query):
        board = await service.player_board(
            storage, None, chat_id, player.display_name, image=upload is not None, refresh=False
        )
        if board is None:
            continue
        key = f"{chat_id}:{player.account_id}"
        if upload is not None and board.png is not None:
            digest = hashlib.sha1(board.png).hexdigest()
            try:
                file_id = _file_ids.get(digest) or await upload(board.png, board.caption)
            except Exception:
                log.warning("Inline: не удалось залить карточку — отдаём текстом", exc_info=True)
            else:
                _file_ids[digest] = file_id
                results.append(InlineQueryResultCachedPhoto(
                    id=key, photo_file_id=file_id, caption=board.caption, parse_mode="HTML"
                ))
                continue
        results.append(InlineQueryResultArticle(
            id=key,
            title=player.display_name,
            description=_plain(board.text).split("\n", 1)[0][:100],
            input_message_content=InputTextMessageContent(message_text=board.text, parse_mode="HTML"),
        ))
    return results


@router.inline_query()
async def on_inline(query: InlineQuery, bot: Bot, storage: Storage, inline_cache_chat: Optional[int] = None) -> None:
    upload: Optional[Upload] = None
    if inline_cache_chat is not None:
        async def upload(png: bytes, caption: str) -> str:
            sent = await bot.send_photo(inline_cache_chat, BufferedInputFile(png, filename="card.png"),
                                        disable_notification=True)
            return sent.photo[-1].file_id

    results = await build_results(storage, query.from_user.id, query.query, upload)
    button = None
    if not results and not storage.user_chats(query.from_user.id):
        button = InlineQueryResultsButton(text=HINT, start_parameter="me")
    await query.answer(results, cache_time=CACHE_TIME, is_personal=True, button=button)
