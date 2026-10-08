"""Состояние бота для /status (админам) и heartbeat-файла: внешние сервисы, обновления, очереди, кэши.

`collect_status` возвращает только простые типы (JSON), `render_status` — человекочитаемый HTML для Telegram.
Сети нет: всё берётся из предохранителей клиентов и БД.
"""
from __future__ import annotations

import html
import json
import logging
import os
import time
from typing import Optional

from mmrbot import avatars, hero_icons, tracker

log = logging.getLogger(__name__)


def _files(folder: Optional[str]) -> int:
    """Сколько файлов в папке кэша (нет папки — 0)."""
    try:
        return sum(1 for entry in os.scandir(folder) if entry.is_file()) if folder else 0
    except OSError:
        return 0


def _provider(health) -> Optional[dict]:
    return health.status() if health is not None else None


def collect_status(storage, od=None, stratz=None, now: Optional[int] = None) -> dict:
    """Снимок состояния бота (JSON-совместимый словарь)."""
    now = int(time.time()) if now is None else now
    chats = storage.list_chats()
    updates = storage.player_update_times()
    known = [t for t in updates if t is not None]
    icons, avatar_loader = hero_icons.shared(), avatars.shared()
    healths = [getattr(od, "health", None), getattr(stratz, "health", None), getattr(icons, "health", None)]
    return {
        "ts": now,
        "chats": len(chats),
        "providers": [p for p in map(_provider, healths) if p is not None],
        "opendota": {"remaining_day": getattr(od, "remaining_day", None), "has_key": bool(getattr(od, "api_key", None))},
        "players": {
            "count": len(updates), "never_updated": len(updates) - len(known),
            "newest_update": max(known) if known else None, "oldest_update": min(known) if known else None,
        },
        "backlog": storage.backlog_counts(tracker._enrich_since(now)),
        "caches": {
            "hero_icons": _files(getattr(icons, "folder", None)),
            "avatars": _files(getattr(avatar_loader, "folder", None)),
            "opendota_matches": len(getattr(od, "_match_cache", ()) or ()),
        },
    }


def _ago(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    if seconds >= 3600:
        return f"{seconds // 3600} ч {seconds % 3600 // 60} мин"
    if seconds >= 60:
        return f"{seconds // 60} мин"
    return f"{seconds} с"


STATE_TEXT = {"up": ("🟢", "работает"), "down": ("🔴", "недоступен"), "probing": ("🟡", "проверяю доступность"),
              "limited": ("🟠", "лимит запросов")}


def _provider_line(p: dict, now: float) -> str:
    icon, word = STATE_TEXT.get(p["state"], ("⚪", p["state"]))
    line = f"{icon} <b>{html.escape(p['name'])}</b>: {word}"
    if p["state"] != "up":
        if p.get("since"):
            line += f" уже {_ago(now - p['since'])}"
        if p.get("next_try"):
            line += f", следующая попытка через {_ago(p['next_try'] - now)}"
    elif p.get("last_ok"):
        line += f" (ответ {_ago(now - p['last_ok'])} назад)"
    return line


def render_status(data: dict, now: Optional[float] = None) -> str:
    """Человекочитаемый статус (HTML для Telegram)."""
    now = data["ts"] if now is None else now
    lines = ["🩺 <b>Состояние бота</b>", ""]
    lines += [_provider_line(p, now) for p in data["providers"]] or ["Внешние сервисы: данных нет"]
    od = data["opendota"]
    quota = f"{od['remaining_day']}" if od.get("remaining_day") is not None else "не известен"
    mode = "с ключом (суточного потолка нет)" if od.get("has_key") else f"без ключа, остаток суточного лимита: {quota}"
    lines.append(f"🔑 OpenDota {mode}")
    players = data["players"]
    lines.append("")
    freshness = ""
    if players["newest_update"] is not None:
        freshness = (f" · последнее обновление {_ago(now - players['newest_update'])} назад,"
                     f" самое старое — {_ago(now - players['oldest_update'])} назад")
    never = f" · ещё не обновлялись: {players['never_updated']}" if players["never_updated"] else ""
    lines.append(f"👥 Игроки: {players['count']} в {data['chats']} чатах{freshness}{never}")
    backlog = data["backlog"]
    lines.append(f"📥 Очередь догрузки — деталей матчей: {backlog['details']} · Stratz: {backlog['stratz']}")
    caches = data["caches"]
    lines.append(f"🗂 Кэши — иконки героев: {caches['hero_icons']} · аватары: {caches['avatars']} · "
                 f"матчи в памяти: {caches['opendota_matches']}")
    return "\n".join(lines)


def write_heartbeat(path: str, storage, od=None, stratz=None) -> None:
    """Записать heartbeat: JSON со снимком состояния (mtime файла по-прежнему смотрит Docker healthcheck).

    Сбор состояния не должен мешать heartbeat: при ошибке в файл пишется хотя бы ts и причина.
    Запись атомарная (временный файл + replace) — читающий не увидит обрезанный JSON.
    """
    try:
        payload = collect_status(storage, od, stratz)
    except Exception as exc:
        log.debug("Не удалось собрать состояние для heartbeat", exc_info=True)
        payload = {"ts": int(time.time()), "error": type(exc).__name__}
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, path)
