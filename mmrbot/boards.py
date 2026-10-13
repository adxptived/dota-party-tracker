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
class LookupBoard(ImageBoard):
    """Результат поиска по ID: найденный матч (match_id, focus) или игрок (account_id; tracked — он есть в пати)."""
    kind: Optional[str] = None  # "match" | "player" | None — ничего не найдено
    match_id: Optional[int] = None
    focus: Optional[int] = None
    account_id: Optional[int] = None
    tracked: bool = False


@dataclass
class HeroBoard(ImageBoard):
    """Герой и пати на нём: hero_id нужен кнопкам («Текстом»); None — героя с таким именем нет."""
    hero_id: Optional[int] = None


@dataclass
class MatchupsBoard(ImageBoard):
    """Соперники и союзники: account_id нужен кнопкам периода и «Текстом» (0 — вся пати)."""
    account_id: int = 0


HEAVY_PNG = 150 * 1024  # PNG тяжелее — отправляем JPEG: грузится быстрее, а Telegram всё равно пережимает фото


def lighten(data: bytes) -> bytes:
    """Тяжёлый PNG → JPEG того же вида (качество как у картинки матча); лёгкий или не PNG — как есть."""
    if len(data) <= HEAVY_PNG or data[:8] != b"\x89PNG\r\n\x1a\n":
        return data
    try:
        import io

        from PIL import Image

        from mmrbot.cards import to_jpeg
        return to_jpeg(Image.open(io.BytesIO(data)).convert("RGB"))
    except Exception:
        log.warning("Не удалось облегчить картинку — отправляем PNG", exc_info=True)
        return data


def build_png(label: str, render: Callable[[], bytes]) -> Optional[bytes]:
    """Нарисовать картинку; любая ошибка рендера → None (отчёт уйдёт текстом), а не падение команды.

    Тяжёлый PNG (больше HEAVY_PNG) уходит JPEG-ом — см. lighten.
    """
    try:
        return lighten(render())
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
