"""Чистый разбор аргументов команд (без aiogram) — легко тестируется."""
from __future__ import annotations

from typing import Optional

MMR_MIN = 0
MMR_MAX = 20000


def _is_int(token: str) -> bool:
    try:
        int(token)
        return True
    except (TypeError, ValueError):
        return False


def _validate_mmr(mmr: int) -> int:
    if mmr < MMR_MIN or mmr > MMR_MAX:
        raise ValueError(f"MMR должен быть в диапазоне {MMR_MIN}..{MMR_MAX}.")
    return mmr


def parse_add_args(args: str) -> tuple[str, Optional[str], Optional[int]]:
    """`/add <identifier> [Имя ...] [MMR]` → (identifier, name|None, mmr|None).

    Эвристика: первый токен — идентификатор; если последний токен — число, это MMR;
    всё между ними — имя (может быть из нескольких слов).
    """
    tokens = (args or "").split()
    if not tokens:
        raise ValueError("Укажи ссылку или ID: /add <ссылка или ID> [Имя] [стартовый_MMR]")

    identifier = tokens[0]
    rest = tokens[1:]

    mmr: Optional[int] = None
    if rest and _is_int(rest[-1]):
        mmr = _validate_mmr(int(rest[-1]))
        rest = rest[:-1]

    name = " ".join(rest) if rest else None
    return identifier, name, mmr


def parse_name_and_mmr(args: str) -> tuple[str, int]:
    """`/setmmr <Имя ...> <MMR>` → (name, mmr)."""
    tokens = (args or "").split()
    if len(tokens) < 2 or not _is_int(tokens[-1]):
        raise ValueError("Формат: /setmmr Имя MMR (например: /setmmr Вася 5300)")
    mmr = _validate_mmr(int(tokens[-1]))
    name = " ".join(tokens[:-1])
    return name, mmr


def parse_step(args: str) -> int:
    """`/setstep <шаг>` → положительный int."""
    token = (args or "").strip()
    if not _is_int(token):
        raise ValueError("Формат: /setstep <число> (например: /setstep 25)")
    step = int(token)
    if step <= 0 or step > 200:
        raise ValueError("Шаг MMR должен быть от 1 до 200.")
    return step


def parse_hour(args: str) -> int:
    """`/settime <час>` → 0..23."""
    token = (args or "").strip()
    if not _is_int(token):
        raise ValueError("Формат: /settime <час 0..23> (например: /settime 10)")
    hour = int(token)
    if hour < 0 or hour > 23:
        raise ValueError("Час должен быть от 0 до 23.")
    return hour
