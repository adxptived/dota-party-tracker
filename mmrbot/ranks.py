"""Преобразование OpenDota `rank_tier` в человекочитаемую медаль.

`rank_tier` = медаль*10 + звёзды, где медаль:
1 Herald, 2 Guardian, 3 Crusader, 4 Archon, 5 Legend, 6 Ancient, 7 Divine, 8 Immortal.
У Immortal звёзд нет; при наличии `leaderboard_rank` показываем номер в топе.
"""
from __future__ import annotations

from typing import Optional

MEDALS = {
    1: "Herald",
    2: "Guardian",
    3: "Crusader",
    4: "Archon",
    5: "Legend",
    6: "Ancient",
    7: "Divine",
    8: "Immortal",
}

UNCALIBRATED = "Без ранга"


def rank_label(rank_tier: Optional[int], leaderboard_rank: Optional[int] = None) -> str:
    if not rank_tier:  # None или 0 — ранг не откалиброван
        return UNCALIBRATED

    medal = rank_tier // 10
    star = rank_tier % 10
    name = MEDALS.get(medal)
    if name is None:
        return UNCALIBRATED

    if medal == 8:  # Immortal — без звёзд
        if leaderboard_rank:
            return f"Immortal #{leaderboard_rank}"
        return "Immortal"

    if star:
        return f"{name} {star}"
    return name
