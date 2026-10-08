"""Справочник предметов: id → внутреннее имя для URL иконки (blink, black_king_bar…).

Наполняется ответом OpenDota /constants/item_ids (см. tracker.refresh_items). Пока справочник пуст,
иконок предметов нет, и картинка рисуется без билда.
"""
from __future__ import annotations

import json
import os
import tempfile

ITEM_SLUGS: dict[int, str] = {}
CACHE_PATH: str = ""  # файл кэша справочника; задаётся при старте (см. __main__)


def update_items(data) -> int:
    """Обновить справочник из {"1": "blink", ...}. Вернуть число новых предметов; мусорные записи пропускаются."""
    added = 0
    for key, slug in data.items() if isinstance(data, dict) else []:
        try:
            item_id = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(slug, str) or not slug:
            continue
        added += item_id not in ITEM_SLUGS
        ITEM_SLUGS[item_id] = slug
    return added


def item_slug(item_id):
    """item_id → имя для URL иконки | None (пустой слот, неизвестный предмет)."""
    return ITEM_SLUGS.get(item_id) if item_id else None


def save_items(path: str) -> None:
    """Сохранить справочник на диск (атомарно), чтобы после перезапуска билды рисовались без сети."""
    if not ITEM_SLUGS:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({str(k): v for k, v in ITEM_SLUGS.items()}, fh)
    os.replace(tmp, path)


def load_items(path: str) -> int:
    """Прочитать справочник с диска. Вернуть число новых предметов (0 — файла нет или он битый)."""
    try:
        with open(path, encoding="utf-8") as fh:
            return update_items(json.load(fh))
    except (OSError, ValueError):
        return 0
