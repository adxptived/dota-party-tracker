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

# Эмодзи-медаль по номеру медали (1 Herald … 8 Immortal) — «градиент» рангов.
MEDAL_EMOJI = {
    1: "⚪",
    2: "🟠",
    3: "🟡",
    4: "🟢",
    5: "🔵",
    6: "🟣",
    7: "💎",
    8: "🔱",
}


def rank_emoji(rank_tier: Optional[int]) -> str:
    if not rank_tier:
        return ""
    return MEDAL_EMOJI.get(rank_tier // 10, "")


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


def average_rank_tier(tiers) -> Optional[int]:
    """Средний `rank_tier` по игрокам лобби (без ранга игнорируем); Immortal — верхняя ступень шкалы."""
    ordinals = []
    for tier in tiers:
        if not tier:
            continue
        medal, star = tier // 10, tier % 10
        if medal >= 8:
            ordinals.append(35)
        elif 1 <= medal <= 7:
            ordinals.append((medal - 1) * 5 + max(star, 1) - 1)
    if not ordinals:
        return None
    mean = round(sum(ordinals) / len(ordinals))
    if mean >= 35:
        return 80
    return (mean // 5 + 1) * 10 + mean % 5 + 1


MEDAL_STEP = 770   # MMR-ширина одной медали (Herald..Divine)
STAR_STEP = 154    # и одной звезды внутри медали
MMR_DRIFT_TOLERANCE = 350  # на сколько оценка может разойтись с медалью, прежде чем это считаем расхождением


def rank_mmr_range(rank_tier: Optional[int]) -> Optional[tuple[int, Optional[int]]]:
    """Примерный диапазон MMR для медали со звёздами: (от, до); у Immortal верхней границы нет (None)."""
    if not rank_tier:
        return None
    medal, star = rank_tier // 10, rank_tier % 10
    if medal == 8:
        return (5620, None)
    if not 1 <= medal <= 7:
        return None
    low = (medal - 1) * MEDAL_STEP + max(star - 1, 0) * STAR_STEP
    return (low, low + STAR_STEP)


def mmr_rank_mismatch(current_mmr: Optional[int], rank_tier: Optional[int]) -> bool:
    """Оценка MMR заметно расходится с медалью — шаг ±MMR накопил ошибку, пора обновить /setmmr."""
    span = rank_mmr_range(rank_tier)
    if current_mmr is None or span is None:
        return False
    low, high = span
    if current_mmr < low - MMR_DRIFT_TOLERANCE:
        return True
    return high is not None and current_mmr > high + MMR_DRIFT_TOLERANCE


STEP_MIN, STEP_MAX = 10, 60  # разумные шаги ±MMR за игру; вне их подсказка была бы шумом
STEP_MIN_NET = 10  # подсказываем шаг, только если баланс побед и поражений набрался хотя бы такой


def suggest_step(start_mmr: Optional[int], corrections: int, earned: int, step: int,
                 rank_tier: Optional[int]) -> Optional[int]:
    """Шаг ±MMR за игру, при котором оценка совпала бы с серединой медали (кратно 5). None — подсказывать нечего:
    MMR не задан, медали нет, игр мало или шаг вышел бы за STEP_MIN…STEP_MAX, или совпадает с текущим.

    earned — заработанное игрой при текущем шаге step (дабл-дауны уже учтены), corrections — правки /setmmr.
    """
    span = rank_mmr_range(rank_tier)
    if start_mmr is None or span is None or not step:
        return None
    net = earned / step  # баланс побед и поражений в «шагах»
    if abs(net) < STEP_MIN_NET:
        return None
    low, high = span
    target = (low + high) / 2 if high is not None else low
    raw = (target - start_mmr - corrections) / net
    fit = int(round(raw / 5) * 5)
    if not STEP_MIN <= fit <= STEP_MAX or fit == step:
        return None
    return fit
