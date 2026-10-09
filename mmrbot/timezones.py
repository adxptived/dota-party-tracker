"""Часовые пояса чатов: стандартный zoneinfo вместо pytz.

База поясов берётся у системы, а где её нет (Windows, урезанные образы) — из пакета tzdata.
"""
from __future__ import annotations

from datetime import datetime, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo

DEFAULT_ZONE = "Europe/Moscow"
# Переименованные пояса: в свежих базах IANA старое имя — ссылка, в урезанных его может не быть вовсе.
RENAMED = {"Europe/Kiev": "Europe/Kyiv"}


@lru_cache(maxsize=64)
def _load(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def is_valid(name: str) -> bool:
    """Известен ли пояс с таким именем (после учёта переименований)."""
    try:
        _load(RENAMED.get(name, name))
    except Exception:  # ZoneInfoNotFoundError, ValueError (мусор в имени), отсутствие базы поясов
        return False
    return True


def zone(name: str, default: str = DEFAULT_ZONE) -> tzinfo:
    """Пояс по имени IANA; неизвестное имя — `default`, а если нет и его (нет базы поясов) — UTC."""
    for candidate in (RENAMED.get(name, name), default):
        try:
            return _load(candidate)
        except Exception:
            continue
    return timezone.utc


def to_local(ts: float, name: str, default: str = DEFAULT_ZONE) -> datetime:
    """Unix-время → момент в поясе чата."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(zone(name, default))
