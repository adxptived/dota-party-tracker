"""Справочник талантов: id способности → (ступень 1–4 = уровни 10/15/20/25, название таланта).

Собирается из констант OpenDota (/constants/ability_ids, /constants/abilities, /constants/hero_abilities; см.
tracker.refresh_talents) и хранится на диске, как справочник предметов: после перезапуска таланты видны без сети.
Выбранные в матче таланты — это id способностей из ability_upgrades_arr игрока, которые есть в справочнике.
Названия — английские, как в константах OpenDota (русских там нет). Чистые функции, сети нет.
"""
from __future__ import annotations

import json
import os
import re
import tempfile

TALENTS: dict[int, tuple[int, str]] = {}
CACHE_PATH: str = ""  # файл кэша справочника; задаётся при старте (см. __main__)
TIER_LEVELS = {1: 10, 2: 15, 3: 20, 4: 25}

_PLACEHOLDER = re.compile(r"[+\-]?\{s:[^}]*\}\s*(%|s\b)?\s*")


def talent_name(raw) -> str:
    """Название таланта без подстановок «{s:value}» (их значения в константах не приходят): «+{s:x}% Heal» → «Heal»."""
    text = _PLACEHOLDER.sub("", str(raw or "")).strip()
    return re.sub(r"\s{2,}", " ", text)


def build_talents(ability_ids, abilities, hero_abilities) -> dict[int, tuple[int, str]]:
    """Константы OpenDota → {id: (ступень, название)}. Мусорные и неполные записи пропускаются."""
    tiers: dict[str, int] = {}
    for hero in (hero_abilities or {}).values() if isinstance(hero_abilities, dict) else []:
        for talent in (hero or {}).get("talents") or [] if isinstance(hero, dict) else []:
            if isinstance(talent, dict) and isinstance(talent.get("name"), str) and talent.get("level") in TIER_LEVELS:
                tiers[talent["name"]] = talent["level"]
    result: dict[int, tuple[int, str]] = {}
    for key, name in (ability_ids or {}).items() if isinstance(ability_ids, dict) else []:
        if name not in tiers:
            continue
        try:
            ability_id = int(key)
        except (TypeError, ValueError):
            continue
        info = (abilities or {}).get(name) if isinstance(abilities, dict) else None
        title = talent_name(info.get("dname")) if isinstance(info, dict) else ""
        if title:
            result[ability_id] = (tiers[name], title)
    return result


def update_talents(data: dict) -> int:
    """Пополнить справочник ({id: (ступень, название)}); вернуть число новых талантов."""
    added = 0
    for key, value in (data or {}).items():
        try:
            ability_id, tier, title = int(key), int(value[0]), str(value[1])
        except (TypeError, ValueError, IndexError):
            continue
        if tier not in TIER_LEVELS or not title:
            continue
        added += ability_id not in TALENTS
        TALENTS[ability_id] = (tier, title)
    return added


def talent_picks(upgrades) -> list[list]:
    """Выбранные таланты по ability_upgrades_arr: [[уровень 10/15/20/25, название], …] по возрастанию уровня.

    Неизвестные id (обычные способности, новые таланты до обновления справочника) пропускаются; на ступень — один.
    """
    picked: dict[int, str] = {}
    for ability_id in upgrades or []:
        talent = TALENTS.get(ability_id) if isinstance(ability_id, int) and not isinstance(ability_id, bool) else None
        if talent and talent[0] not in picked:
            picked[talent[0]] = talent[1]
    return [[TIER_LEVELS[tier], picked[tier]] for tier in sorted(picked)]


def save_talents(path: str) -> None:
    """Сохранить справочник на диск (атомарно)."""
    if not TALENTS:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({str(k): list(v) for k, v in TALENTS.items()}, fh, ensure_ascii=False)
    os.replace(tmp, path)


def load_talents(path: str) -> int:
    """Прочитать справочник с диска; 0 — файла нет или он битый."""
    try:
        with open(path, encoding="utf-8") as fh:
            return update_talents(json.load(fh))
    except (OSError, ValueError):
        return 0
