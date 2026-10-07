"""Отчёт, который может уйти картинкой: текст (запасной вариант и кнопка «📝 Текстом») + PNG и подпись.

Правило карточек: не собралась картинка или Telegram её не принял — отправляем текст. Поэтому текст собирается
всегда, а картинка — приложение к нему.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger(__name__)

CAPTION_LIMIT = 1024  # лимит подписи к фото в Telegram


@dataclass
class ImageBoard:
    text: str
    png: Optional[bytes] = None
    caption: Optional[str] = None


@dataclass
class MatchBoard(ImageBoard):
    """Матч для ответа: текстовая карточка всегда, картинка и подпись — если собрались."""
    match_id: Optional[int] = None
    focus: Optional[int] = None


@dataclass
class HeroBoard(ImageBoard):
    """Герой и пати на нём: hero_id нужен кнопкам («Текстом»); None — героя с таким именем нет."""
    hero_id: Optional[int] = None


def build_png(label: str, render: Callable[[], bytes]) -> Optional[bytes]:
    """Нарисовать картинку; любая ошибка рендера → None (отчёт уйдёт текстом), а не падение команды."""
    try:
        return render()
    except Exception:
        log.exception("Не удалось нарисовать %s — отвечаем текстом", label)
        return None


def fit_caption(caption: str, limit: int = CAPTION_LIMIT) -> str:
    """Подпись к фото не длиннее лимита Telegram (иначе фото не уйдёт): режем по строкам, не посреди HTML-тега."""
    if len(caption) <= limit:
        return caption
    lines = caption.split("\n")
    while lines and len("\n".join(lines)) > limit:
        lines.pop()
    return "\n".join(lines) if lines else caption[:limit].rsplit("<", 1)[0]
