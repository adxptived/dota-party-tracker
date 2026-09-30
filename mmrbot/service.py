"""Асинхронные помощники, общие для хендлеров и планировщика.

Сетевые/CPU-операции (build_leaderboard дергает синхронный OpenDota-клиент)
выносятся в поток через asyncio.to_thread, чтобы не блокировать event loop aiogram.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from mmrbot.formatting import (
    render_awards,
    render_compare_table,
    render_heroes,
    render_leaderboard,
    render_player_card,
    render_together,
    standing_line,
)
from mmrbot.opendota import OpenDota
from mmrbot.storage import Storage
from mmrbot.tracker import build_chat_comparison, build_leaderboard, build_together

TELEGRAM_LIMIT = 4096


async def gather_summaries(storage: Storage, od: OpenDota, chat_id: int, refresh: bool = True):
    now = int(time.time())
    return await asyncio.to_thread(build_leaderboard, storage, od, chat_id, now, refresh)


async def render_board(
    storage: Storage,
    od: OpenDota,
    chat_id: int,
    today_only: bool = False,
    refresh: bool = True,
) -> str:
    summaries = await gather_summaries(storage, od, chat_id, refresh)
    text = render_leaderboard(summaries, today_only=today_only)
    if not today_only:
        awards = render_awards(summaries)
        if awards:
            text += "\n\n" + awards
    return text


async def render_heroes_board(storage: Storage, od: OpenDota, chat_id: int) -> str:
    summaries = await gather_summaries(storage, od, chat_id, refresh=True)
    return render_heroes(summaries)


async def render_together_board(storage: Storage, od: OpenDota, chat_id: int) -> str:
    # Сначала обновляем матчи всех игроков, затем считаем совместную статистику.
    await gather_summaries(storage, od, chat_id, refresh=True)
    result = await asyncio.to_thread(build_together, storage, chat_id)
    return render_together(result)


async def render_player_board(storage: Storage, od: OpenDota, chat_id: int, name: str) -> Optional[str]:
    summaries = await gather_summaries(storage, od, chat_id, refresh=True)
    comparison = build_chat_comparison(summaries)
    name_lower = name.strip().lower()
    for summary in summaries:
        if summary.display_name.lower() == name_lower or str(summary.account_id) == name.strip():
            standing = standing_line(comparison, summary.display_name)
            return render_player_card(summary, standing=standing)
    return None


async def render_compare_board(storage: Storage, od: OpenDota, chat_id: int) -> str:
    summaries = await gather_summaries(storage, od, chat_id, refresh=True)
    if not summaries:
        return "В этом чате пока нет игроков. Добавь: /add «ссылка или ID» Имя [MMR]"
    comparison = build_chat_comparison(summaries)
    return render_compare_table(comparison, summaries)


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
