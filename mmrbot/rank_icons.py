"""Настоящие значки рангов Dota 2 (медали и звёзды из репозитория odota/web): качаем один раз, кэш в памяти и на диске.

Синхронный (requests), вызывается из потока рендера. Сеть недоступна — значка нет (None), `cards.rank_badge`
рисует свою медаль. Промах запоминаем на MISS_TTL, как в hero_icons.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

import requests

from mmrbot.health import ProviderHealth

ICON_URL = "https://raw.githubusercontent.com/odota/web/master/public/assets/images/dota2/rank_icons/{name}.png"
MISS_TTL = 600  # сек: после неудачной загрузки не пробуем этот значок снова

log = logging.getLogger(__name__)


def medal_name(medal: int) -> str:
    return f"rank_icon_{medal}"


def star_name(stars: int) -> str:
    return f"rank_star_{stars}"


class RankIcons:
    def __init__(self, folder: Optional[str], session=None, timeout=(8, 15), health: Optional[ProviderHealth] = None):
        self.folder = folder
        self.health = health or ProviderHealth("Rank icons")
        self.timeout = timeout
        self._session = session or requests.Session()
        self._memory: dict[str, bytes] = {}
        self._misses: dict[str, float] = {}
        self._lock = threading.Lock()

    def get(self, name: str) -> Optional[bytes]:
        """PNG-байты значка (`rank_icon_5`, `rank_star_3`) | None (нет файла, нет сети)."""
        with self._lock:
            if name in self._memory:
                return self._memory[name]
            if time.monotonic() - self._misses.get(name, -MISS_TTL) < MISS_TTL:
                return None
        data = self._from_disk(name)
        if data is None and self.health.allow():
            try:
                data = self._download(name)
            finally:
                self.health.release()
        elif data is None:
            return None
        with self._lock:
            if data is None:
                self._misses[name] = time.monotonic()
            else:
                self._memory[name] = data
        return data

    def _path(self, name: str) -> Optional[str]:
        return os.path.join(self.folder, f"{name}.png") if self.folder else None

    def _from_disk(self, name: str) -> Optional[bytes]:
        path = self._path(name)
        if path is None or not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as fh:
                return fh.read() or None
        except OSError:
            return None

    def _download(self, name: str) -> Optional[bytes]:
        try:
            resp = self._session.get(ICON_URL.format(name=name), timeout=self.timeout)
        except Exception as exc:
            self.health.failure(exc)
            log.warning("Значок ранга %s не скачался: %s", name, exc)
            return None
        if resp.status_code >= 500:
            self.health.failure(RuntimeError(f"HTTP {resp.status_code}"))
        else:
            self.health.success()
        content_type = (resp.headers or {}).get("Content-Type", "")
        if resp.status_code != 200 or not content_type.startswith("image/") or not resp.content:
            log.warning("Значок ранга %s: HTTP %s %s", name, resp.status_code, content_type)
            return None
        path = self._path(name)
        if path is not None:
            try:
                os.makedirs(self.folder, exist_ok=True)
                tmp = f"{path}.tmp"
                with open(tmp, "wb") as fh:
                    fh.write(resp.content)
                os.replace(tmp, path)
            except OSError:
                log.warning("Не удалось сохранить значок %s", path, exc_info=True)
        return resp.content


_shared: Optional[RankIcons] = None


def setup(folder: Optional[str], health: Optional[ProviderHealth] = None) -> RankIcons:
    """Общий загрузчик значков бота (вызывается при старте). Без setup рисуется нарисованная медаль."""
    global _shared
    _shared = RankIcons(folder, health=health)
    return _shared


def shared() -> Optional[RankIcons]:
    return _shared
