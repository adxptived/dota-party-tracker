"""Иконки предметов со Steam CDN: тот же загрузчик, что у героев (диск + память, предохранитель CDN)."""
from __future__ import annotations

from typing import Optional

from mmrbot.hero_icons import HeroIcons
from mmrbot.items import item_slug

ICON_URL = "https://cdn.steamstatic.com/apps/dota2/images/dota_react/items/{slug}.png"


class ItemIcons(HeroIcons):
    ICON_URL = ICON_URL

    def _slug(self, key) -> Optional[str]:
        return item_slug(key)


_shared: Optional[ItemIcons] = None


def setup(folder: Optional[str], health=None) -> ItemIcons:
    """Общий загрузчик иконок предметов (при старте). health — предохранитель CDN, общий с иконками героев."""
    global _shared
    _shared = ItemIcons(folder, health=health)
    return _shared


def shared() -> Optional[ItemIcons]:
    return _shared
