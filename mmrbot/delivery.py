"""Надёжная отправка фоновых сообщений в Telegram: повтор при лимите (retry_after) и сетевых сбоях.

Повторяем только то, что проходит само: `TelegramRetryAfter` (ждём, сколько просит Telegram), сетевые ошибки и 5xx.
Всё остальное — «бот выгнан», «чат перенесён», «чат не найден», неверный запрос — повторять бессмысленно: исключение
уходит наверх, и вызывающий код (`scheduler.chat_gone`) решает, что делать с чатом.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError

log = logging.getLogger(__name__)

T = TypeVar("T")
ATTEMPTS = 3
MAX_WAIT = 30.0  # дольше просит подождать Telegram — не висим: задача повторится в следующем тике планировщика


async def send_with_retry(
    call: Callable[[], Awaitable[T]], *, attempts: int = ATTEMPTS, max_wait: float = MAX_WAIT, sleep=None,
) -> T:
    """Выполнить отправку `call()`; при лимите/сети/5xx — повторить (до `attempts` раз), иначе поднять исключение."""
    sleep = sleep or asyncio.sleep  # ищем в момент вызова: тесты подменяют asyncio.sleep
    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except TelegramRetryAfter as exc:
            wait = float(getattr(exc, "retry_after", 1) or 1)
            if attempt == attempts or wait > max_wait:
                raise
            log.info("Telegram просит подождать %.0f с — повтор %d из %d", wait, attempt + 1, attempts)
            await sleep(wait + 0.5)
        except (TelegramNetworkError, TelegramServerError, asyncio.TimeoutError) as exc:
            if attempt == attempts:
                raise
            log.info("Сбой отправки в Telegram (%s) — повтор %d из %d", type(exc).__name__, attempt + 1, attempts)
            await sleep(1.5 * attempt)
    raise RuntimeError("unreachable")  # pragma: no cover — цикл всегда возвращает результат или поднимает исключение
