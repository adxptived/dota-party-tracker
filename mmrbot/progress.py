"""Отложенный статус «⏳ Считаю…»: показываем, только когда ответ реально долгий.

Быстрый ответ обходится без лишних запросов к Telegram (статус + его удаление — это ~0.2–0.4 с на команду).
Через action_after секунд — индикатор sendChatAction («печатает…» / «отправляет фото»), через text_after —
само сообщение. delete() отменяет ещё не показанное и убирает показанное.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

log = logging.getLogger(__name__)


class DeferredStatus:
    def __init__(
        self,
        send_action: Callable[[], Awaitable],
        send_text: Callable[[], Awaitable],
        action_after: float = 0.7,
        text_after: float = 2.0,
        delete_sent: bool = True,
    ) -> None:
        """send_action/send_text — корутины-фабрики; send_text возвращает сообщение (с .delete()) или None.

        delete_sent=False — статус правит само сообщение-отчёт (кнопка): удалять его нельзя.
        """
        self._send_action = send_action
        self._send_text = send_text
        self._action_after = action_after
        self._text_after = text_after
        self._delete_sent = delete_sent
        self._sent = None
        self._sending = False
        self._closed = False
        self._task: Optional[asyncio.Task] = asyncio.ensure_future(self._run())

    async def _run(self) -> None:
        await asyncio.sleep(self._action_after)
        try:
            await self._send_action()
        except Exception:
            log.debug("sendChatAction не отправился", exc_info=True)
        await asyncio.sleep(max(self._text_after - self._action_after, 0.0))
        self._sending = True
        try:
            self._sent = await self._send_text()
        except Exception:
            log.debug("Статус «Считаю…» не отправился", exc_info=True)

    async def delete(self) -> None:
        """Отменить ещё не показанный статус; показанный — убрать. Повторный вызов безопасен."""
        if self._closed:
            return
        self._closed = True
        task = self._task
        if task is not None and not task.done():
            if self._sending:
                await asyncio.wait({task})  # отправка уже идёт — дождёмся и уберём сообщение, а не оставим висеть
            else:
                task.cancel()
                await asyncio.wait({task})
        if self._delete_sent and self._sent is not None:
            try:
                await self._sent.delete()
            except Exception:
                log.debug("Не удалось убрать статус", exc_info=True)
