"""Лейнинг и вижн: исход линии игрока и число поставленных вардов (чистые функции, без сети и БД).

Stratz отдаёт исход каждой из трёх линий с точки зрения света: RADIANT_STOMP / RADIANT_VICTORY / TIE /
DIRE_VICTORY / DIRE_STOMP. Игроку нужен исход ЕГО линии и в ЕГО пользу: свет и тьма делят линии по-разному
(лёгкая линия света — нижняя, тьмы — верхняя), а для тьмы победа света — поражение.
"""
from __future__ import annotations

from typing import Optional

# какая из трёх линий поля соответствует линии игрока: (за свет, за тьму)
_LANE_ON_MAP = {"SAFE_LANE": ("bottom", "top"), "OFF_LANE": ("top", "bottom"), "MID_LANE": ("mid", "mid")}
# исход глазами света: +2 раздавил, +1 выиграл, 0 ничья
_RADIANT_VIEW = {"RADIANT_STOMP": 2, "RADIANT_VICTORY": 1, "TIE": 0, "DIRE_VICTORY": -1, "DIRE_STOMP": -2}


def lane_result(lane: Optional[str], is_radiant: Optional[bool], outcomes: dict) -> Optional[int]:
    """Исход линии для игрока: +2 раздавил, +1 выиграл, 0 ничья, −1 проиграл, −2 раздавили; None — неизвестно.

    lane — MatchPlayerType.lane (SAFE_LANE / OFF_LANE / MID_LANE; роуминг и лес — линии нет), outcomes —
    {"top", "mid", "bottom"} → значение LaneOutcomeEnums.
    """
    sides = _LANE_ON_MAP.get(lane or "")
    if sides is None or is_radiant is None:
        return None
    score = _RADIANT_VIEW.get(outcomes.get(sides[0] if is_radiant else sides[1]) or "")
    if score is None:
        return None
    return score if is_radiant else -score


def ward_count(stats: Optional[dict]) -> Optional[int]:
    """Сколько вардов поставил игрок (наблюдатели и сентри вместе); None — Stratz не прислал данных."""
    wards = (stats or {}).get("wards")
    return len(wards) if isinstance(wards, list) else None
