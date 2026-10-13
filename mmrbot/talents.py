"""Справочник талантов и дерево талантов игрока в матче.

Справочник собирается из констант OpenDota (/constants/ability_ids, /constants/abilities, /constants/hero_abilities;
см. tracker.refresh_talents) и хранится на диске, как справочник предметов: после перезапуска таланты видны без сети.
TALENTS: id способности → (герой, ступень 1–4, сторона); TREES: герой → 4 ступени по [правый, левый] — названия.
Сторона — как в игре: в константах у каждой ступени сначала правый талант (Ability10, 12…), затем левый.

Дерево игрока — 4 ступени снизу вверх (10, 15, 20, 25): {"level", "left", "right", "pick": "left"|"right"|None};
выбор берётся из ability_upgrades_arr матча. Названия — английские, как в константах OpenDota. Сети здесь нет.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from typing import Optional

TALENTS: dict[int, tuple[str, int, str]] = {}
TREES: dict[str, list[list[str]]] = {}
CACHE_PATH: str = ""  # файл кэша справочника; задаётся при старте (см. __main__)
TIER_LEVELS = {1: 10, 2: 15, 3: 20, 4: 25}
SIDES = ("right", "left")  # порядок талантов ступени в константах

_PLACEHOLDER = re.compile(r"[+\-]?\{s:[^}]*\}\s*(%|s\b)?\s*")


def talent_name(raw) -> str:
    """Название таланта без подстановок «{s:value}» (их значения в константах не приходят): «+{s:x}% Heal» → «Heal»."""
    text = _PLACEHOLDER.sub("", str(raw or "")).strip()
    return re.sub(r"\s{2,}", " ", text)


def build_talents(ability_ids, abilities, hero_abilities) -> dict:
    """Константы OpenDota → {"talents": {id: [герой, ступень, сторона]}, "trees": {герой: [[правый, левый] × 4]}}.

    Герой попадает в справочник, только если у него ровно по два таланта на каждой из четырёх ступеней.
    """
    names = {}
    for key, name in (ability_ids or {}).items() if isinstance(ability_ids, dict) else []:
        try:
            names[name] = int(key)
        except (TypeError, ValueError):
            continue
    abilities = abilities if isinstance(abilities, dict) else {}
    talents, trees = {}, {}
    for hero, info in (hero_abilities or {}).items() if isinstance(hero_abilities, dict) else []:
        rows: dict[int, list] = {}
        for talent in (info or {}).get("talents") or [] if isinstance(info, dict) else []:
            if isinstance(talent, dict) and isinstance(talent.get("name"), str) and talent.get("level") in TIER_LEVELS:
                rows.setdefault(talent["level"], []).append(talent["name"])
        if sorted(rows) != [1, 2, 3, 4] or any(len(pair) != 2 for pair in rows.values()):
            continue
        tree = []
        for tier in (1, 2, 3, 4):
            pair = []
            for side, name in zip(SIDES, rows[tier]):
                info = abilities.get(name)
                pair.append(talent_name(info.get("dname")) if isinstance(info, dict) else "")
                if name in names:
                    talents[names[name]] = [hero, tier, side]
            tree.append(pair)
        trees[hero] = tree
    return {"talents": talents, "trees": trees}


def update_talents(data) -> int:
    """Пополнить справочник из build_talents (или файла кэша); вернуть число новых талантов."""
    if not isinstance(data, dict):
        return 0
    for hero, tree in (data.get("trees") or {}).items():
        if (isinstance(tree, list) and len(tree) == 4
                and all(isinstance(p, list) and len(p) == 2 and all(isinstance(n, str) for n in p) for p in tree)):
            TREES[hero] = [list(p) for p in tree]
    added = 0
    for key, value in (data.get("talents") or {}).items():
        try:
            ability_id, (hero, tier, side) = int(key), value
        except (TypeError, ValueError):
            continue
        if hero not in TREES or tier not in TIER_LEVELS or side not in SIDES:
            continue
        added += ability_id not in TALENTS
        TALENTS[ability_id] = (hero, int(tier), side)
    return added


def talent_tree(upgrades) -> list[dict]:
    """Дерево талантов по ability_upgrades_arr: 4 ступени (10, 15, 20, 25) с обоими вариантами и выбранной стороной.

    Пусто — ни одного известного таланта (обычные способности, новые таланты до обновления справочника).
    """
    picks: dict[int, str] = {}
    hero: Optional[str] = None
    for ability_id in upgrades or []:
        known = TALENTS.get(ability_id) if isinstance(ability_id, int) and not isinstance(ability_id, bool) else None
        if not known or (hero is not None and known[0] != hero):
            continue
        hero = known[0]
        picks.setdefault(known[1], known[2])
    if hero is None:
        return []
    tree = TREES[hero]
    return [{"level": TIER_LEVELS[tier], "right": tree[tier - 1][0], "left": tree[tier - 1][1], "pick": picks.get(tier)}
            for tier in (1, 2, 3, 4)]


def tree_rows(value) -> list[dict]:
    """Дерево из билда в виде, пригодном для рисования: мусор отбрасывается; без единого выбора — пусто.

    Понимает и прежний формат [[уровень, название]] (только выбранные): выбор рисуется слева, вторая сторона пуста.
    """
    rows = []
    for row in value or []:
        if isinstance(row, dict) and row.get("level") in TIER_LEVELS.values():
            pick = row.get("pick") if row.get("pick") in SIDES else None
            rows.append({"level": row["level"], "left": str(row.get("left") or ""), "right": str(row.get("right") or ""),
                         "pick": pick})
        elif isinstance(row, (list, tuple)) and len(row) == 2 and row[0] in TIER_LEVELS.values() and row[1]:
            rows.append({"level": row[0], "left": str(row[1]), "right": "", "pick": "left"})
    if not any(r["pick"] for r in rows):
        return []
    by_level = {r["level"]: r for r in rows}
    return [by_level.get(level, {"level": level, "left": "", "right": "", "pick": None})
            for level in TIER_LEVELS.values()]


def save_talents(path: str) -> None:
    """Сохранить справочник на диск (атомарно)."""
    if not TALENTS:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = {"talents": {str(k): list(v) for k, v in TALENTS.items()}, "trees": TREES}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, path)


def load_talents(path: str) -> int:
    """Прочитать справочник с диска; 0 — файла нет, он битый или старого формата."""
    try:
        with open(path, encoding="utf-8") as fh:
            return update_talents(json.load(fh))
    except (OSError, ValueError):
        return 0
