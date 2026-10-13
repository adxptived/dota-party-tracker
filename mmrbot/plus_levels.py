"""Уровень и тир героя в Dota Plus по опыту героя (Stratz отдаёт `dotaPlusHeroXp`).

Чистые функции. Таблица — Liquipedia, «Dota Plus»: накопленный опыт для каждого уровня 1–30 и тиры по уровням.
"""
from __future__ import annotations

from bisect import bisect_right
from typing import Optional

# Накопленный опыт, с которого герой на уровне 1, 2, … 30.
_TOTAL_XP = (
    50, 350, 750, 1250, 1850, 2750, 3750, 4850, 6050, 7350, 8750, 10450, 12250, 14150, 16150, 18250, 20450, 22950,
    25550, 28250, 31050, 33950, 36950, 40050, 46850, 50850, 55050, 59450, 64050, 72050,
)
# (первый уровень тира, название) — по возрастанию.
_TIERS = ((1, "Bronze"), (6, "Silver"), (12, "Gold"), (18, "Platinum"), (25, "Master"), (30, "Grandmaster"))
MAX_LEVEL = len(_TOTAL_XP)


def plus_level(xp) -> Optional[int]:
    """Уровень героя 0–30 по накопленному опыту; опыт неизвестен или не число — None."""
    if isinstance(xp, bool) or not isinstance(xp, (int, float)) or xp != xp or xp < 0:
        return None
    return bisect_right(_TOTAL_XP, xp)


def plus_tier(level) -> Optional[str]:
    """Тир по уровню героя (Bronze … Grandmaster); уровня нет или 0 — None."""
    if isinstance(level, bool) or not isinstance(level, int) or level < 1:
        return None
    name = None
    for first, tier in _TIERS:
        if level >= first:
            name = tier
    return name
