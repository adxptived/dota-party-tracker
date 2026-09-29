"""Асинхронные помощники, общие для хендлеров и планировщика.

Сетевые/CPU-операции (build_leaderboard дергает синхронный OpenDota-клиент)
выносятся в поток через asyncio.to_thread, чтобы не блокировать event loop aiogram.
"""
from __future__ import annotations

import asyncio
import time

from mmrbot.formatting import render_leaderboard
from mmrbot.opendota import OpenDota
from mmrbot.storage import Storage
from mmrbot.tracker import build_leaderboard

TELEGRAM_LIMIT = 4096


async def render_board(
    storage: Storage,
    od: OpenDota,
    chat_id: int,
    today_only: bool = False,
    refresh: bool = True,
) -> str:
    now = int(time.time())
    summaries = await asyncio.to_thread(build_leaderboard, storage, od, chat_id, now, refresh)
    return render_leaderboard(summaries, today_only=today_only)


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
