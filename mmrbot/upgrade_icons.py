"""Иконки Аганима из Доты (шард и скипетр) — лежат в репозитории (mmrbot/assets), сеть не нужна.

Вместо текстовых подписей «Ш»/«С» в билдах. Нет файла или он битый — None, и вызывающий код рисует
прежнюю таблетку.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

ASSETS = os.path.join(os.path.dirname(__file__), "assets")
FILES = {"shard": "shard.png", "scepter": "scepter.png"}


@lru_cache(maxsize=16)
def upgrade_icon(key: str, size: int, radius: int = 6):
    """RGBA-иконка «shard»/«scepter» size×size со скруглением или None."""
    name = FILES.get(key)
    if not name:
        return None
    try:
        from PIL import Image
        from mmrbot import cards
        icon = Image.open(os.path.join(ASSETS, name)).convert("RGBA").resize((size, size), Image.LANCZOS)
        icon.putalpha(cards._rr_mask(size, size, radius))
        return icon
    except Exception:
        return None


def paste_upgrade(img, key: str, x: float, cy: float, size: int) -> Optional[int]:
    """Нарисовать иконку с левым краем x и центром по вертикали cy. Вернуть ширину или None (иконки нет)."""
    from mmrbot import cards
    icon = upgrade_icon(key, size)
    if icon is None:
        return None
    cards.paste(img, icon, x, cy - size / 2)
    return size
