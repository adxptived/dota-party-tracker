"""Иконки героев со Steam CDN: качаем один раз, держим в памяти и на диске (папка рядом с БД).

Синхронный (requests), вызывается из потока рендера. Сбой сети — не ошибка: иконки нет (None), картинка
матча рисует заглушку. Промах запоминаем на MISS_TTL, чтобы каждая картинка не ждала один и тот же таймаут.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import requests

from mmrbot.heroes import hero_slug

ICON_URL = "https://cdn.steamstatic.com/apps/dota2/images/dota_react/heroes/{slug}.png"
MISS_TTL = 600  # сек: после неудачной загрузки не пробуем эту иконку снова
FETCH_THREADS = 5  # первая картинка матча качает до 10 иконок — параллельно

log = logging.getLogger(__name__)


class HeroIcons:
    def __init__(self, folder: Optional[str], session=None, timeout=(8, 15)):  # TLS-рукопожатие идёт в первый таймаут
        self.folder = folder
        self.timeout = timeout
        self._session = session or requests.Session()
        self._memory: dict[str, bytes] = {}
        self._misses: dict[str, float] = {}
        self._lock = threading.Lock()

    def get(self, hero_id) -> Optional[bytes]:
        """PNG-байты иконки героя | None (неизвестный герой, нет сети)."""
        slug = hero_slug(hero_id)
        if slug is None:
            return None
        with self._lock:
            if slug in self._memory:
                return self._memory[slug]
            if time.monotonic() - self._misses.get(slug, -MISS_TTL) < MISS_TTL:
                return None
        data = self._from_disk(slug) or self._download(slug)
        with self._lock:
            if data is None:
                self._misses[slug] = time.monotonic()
            else:
                self._memory[slug] = data
        return data

    def get_many(self, hero_ids) -> dict[int, bytes]:
        """{hero_id: PNG} для найденных иконок (не найденные пропускаются)."""
        ids = list(dict.fromkeys(hid for hid in hero_ids if hero_slug(hid)))
        if not ids:
            return {}
        with ThreadPoolExecutor(min(FETCH_THREADS, len(ids))) as pool:
            found = dict(zip(ids, pool.map(self.get, ids)))
        return {hid: data for hid, data in found.items() if data}

    def _path(self, slug: str) -> Optional[str]:
        return os.path.join(self.folder, f"{slug}.png") if self.folder else None

    def _from_disk(self, slug: str) -> Optional[bytes]:
        path = self._path(slug)
        if path is None or not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as fh:
                return fh.read() or None
        except OSError:
            return None

    def _download(self, slug: str) -> Optional[bytes]:
        try:
            resp = self._session.get(ICON_URL.format(slug=slug), timeout=self.timeout)
        except Exception as exc:
            log.warning("Иконка героя %s не скачалась: %s", slug, exc)  # без трейсбека: 10 иконок — 10 простыней
            return None
        content_type = (resp.headers or {}).get("Content-Type", "")
        if resp.status_code != 200 or not content_type.startswith("image/") or not resp.content:
            log.warning("Иконка героя %s: HTTP %s %s", slug, resp.status_code, content_type)
            return None
        path = self._path(slug)
        if path is not None:
            try:
                os.makedirs(self.folder, exist_ok=True)
                tmp = f"{path}.tmp"
                with open(tmp, "wb") as fh:
                    fh.write(resp.content)
                os.replace(tmp, path)  # атомарно: параллельный рендер не прочитает недописанный файл
            except OSError:
                log.warning("Не удалось сохранить иконку %s", path, exc_info=True)
        return resp.content


_shared: Optional[HeroIcons] = None


def setup(folder: Optional[str]) -> HeroIcons:
    """Общий загрузчик иконок бота (вызывается при старте). Без setup картинки рисуются с заглушками."""
    global _shared
    _shared = HeroIcons(folder)
    return _shared


def shared() -> Optional[HeroIcons]:
    return _shared
