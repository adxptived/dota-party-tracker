"""Замеры скорости команд: одна строка на команду/кнопку в логе.

    perf cmd=/stats chat=-100123 total=1.84s refresh=1.20s build=0.31s render=0.12s send=0.21s

Фазы отмечаются контекстным таймером `with perf.phase("refresh"):` в service.py (refresh — ожидание
обновления игроков, build — сборка данных из БД, render — рисование картинки). `send` — остаток:
отправка в Telegram и накладные расходы. Трассировка живёт в contextvars: asyncio.to_thread переносит её
в рабочий поток, а вне команды (фон, тесты) `phase` ничего не делает.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

log = logging.getLogger("mmrbot.perf")

PHASES = ("refresh", "build", "render")  # порядок в строке; send считается остатком


class Trace:
    def __init__(self) -> None:
        self.started = time.monotonic()
        self.phases: dict[str, float] = {}


_current: ContextVar[Optional[Trace]] = ContextVar("mmrbot_perf", default=None)


def begin() -> Trace:
    """Начать трассировку команды (вызывается middleware перед хендлером)."""
    trace = Trace()
    _current.set(trace)
    return trace


@contextmanager
def phase(name: str):
    """Учесть время блока в фазе name (суммируется); без активной трассировки — ничего не делает."""
    trace = _current.get()
    if trace is None:
        yield
        return
    started = time.monotonic()
    try:
        yield
    finally:
        trace.phases[name] = trace.phases.get(name, 0.0) + time.monotonic() - started


def format_line(cmd: str, chat_id, total: float, phases: dict) -> str:
    parts = [f"perf cmd={cmd} chat={chat_id} total={total:.2f}s"]
    known = 0.0
    for name in PHASES:
        if name in phases:
            parts.append(f"{name}={phases[name]:.2f}s")
            known += phases[name]
    parts.append(f"send={max(total - known, 0.0):.2f}s")
    return " ".join(parts)


def finish(trace: Trace, cmd: str, chat_id) -> str:
    """Закрыть трассировку и записать строку perf в лог (INFO). Возвращает строку."""
    _current.set(None)
    line = format_line(cmd, chat_id, time.monotonic() - trace.started, trace.phases)
    log.info("%s", line)
    return line


def label(event) -> str:
    """Подпись события для строки: команда («/stats»), «cb:<data>» для кнопки, «text» для прочего."""
    data = getattr(event, "data", None)
    if data is not None:
        return f"cb:{data}"
    text = (getattr(event, "text", None) or "").strip()
    if text.startswith("/"):
        return text.split()[0].split("@")[0]
    return "text"
