"""Аватары Steam для карточек: качаем один раз, держим в памяти и на диске (папка avatars/ рядом с БД).

Адрес берём из профиля игрока (`players.steam_avatar` — avatarfull из OpenDota). Работает как hero_icons.HeroIcons:
синхронный (requests), вызывается из потока рендера; сбой сети — не ошибка (None → кружок с инициалом);
общий предохранитель Steam CDN с иконками героев — упал CDN, ждать таймауты на каждой картинке не нужно.
Качаем только с хостов Steam: адрес пришёл из чужого API, ходить по произвольным ссылкам нельзя.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Optional
from urllib.parse import urlparse

import requests

from mmrbot.health import ProviderHealth

MISS_TTL = 600  # сек: после неудачной загрузки не пробуем этот адрес снова
FETCH_THREADS = 5
MAX_BYTES = 512 * 1024  # аватар — десяток КБ; всё, что больше, — не аватар
ALLOWED_HOST_SUFFIXES = (".steamstatic.com", ".akamaihd.net", ".steamcdn-a.akamaihd.net")

log = logging.getLogger(__name__)


def allowed_url(url) -> bool:
    try:
        parsed = urlparse(str(url))
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == s.lstrip(".") or host.endswith(s) for s in ALLOWED_HOST_SUFFIXES)


class Avatars:
    def __init__(self, folder: Optional[str], session=None, timeout=(8, 15), health: Optional[ProviderHealth] = None):
        self.folder = folder
        self.health = health or ProviderHealth("Steam CDN")
        self.timeout = timeout
        self._session = session or requests.Session()
        self._memory: dict[str, bytes] = {}
        self._misses: dict[str, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(url: str) -> str:
        return hashlib.sha1(url.encode("utf-8")).hexdigest()[:24]

    def get(self, url) -> Optional[bytes]:
        """Байты аватара по адресу | None (нет адреса, чужой хост, нет сети)."""
        if not url or not allowed_url(url):
            return None
        key = self._key(url)
        with self._lock:
            if key in self._memory:
                return self._memory[key]
            if time.monotonic() - self._misses.get(key, -MISS_TTL) < MISS_TTL:
                return None
        data = self._from_disk(key)
        if data is None and self.health.allow():
            try:
                data = self._download(url, key)
            finally:
                self.health.release()
        elif data is None:
            return None
        with self._lock:
            if data is None:
                self._misses[key] = time.monotonic()
            else:
                self._memory[key] = data
        return data

    def get_many(self, urls: Iterable[Optional[str]]) -> dict[str, bytes]:
        """{url: байты} для найденных аватаров."""
        unique = list(dict.fromkeys(u for u in urls if u and allowed_url(u)))
        if not unique:
            return {}
        with ThreadPoolExecutor(min(FETCH_THREADS, len(unique))) as pool:
            found = dict(zip(unique, pool.map(self.get, unique)))
        return {url: data for url, data in found.items() if data}

    def _path(self, key: str) -> Optional[str]:
        return os.path.join(self.folder, f"{key}.img") if self.folder else None

    def _from_disk(self, key: str) -> Optional[bytes]:
        path = self._path(key)
        if path is None or not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as fh:
                return fh.read() or None
        except OSError:
            return None

    def _download(self, url: str, key: str) -> Optional[bytes]:
        try:
            resp = self._session.get(url, timeout=self.timeout)
        except Exception as exc:
            self.health.failure(exc)
            log.warning("Аватар не скачался: %s", type(exc).__name__)
            return None
        if resp.status_code >= 500:
            self.health.failure(RuntimeError(f"HTTP {resp.status_code}"))
        else:
            self.health.success()
        content_type = (resp.headers or {}).get("Content-Type", "")
        content = resp.content
        if resp.status_code != 200 or not content_type.startswith("image/") or not content or len(content) > MAX_BYTES:
            log.warning("Аватар: HTTP %s %s", resp.status_code, content_type)
            return None
        path = self._path(key)
        if path is not None:
            try:
                os.makedirs(self.folder, exist_ok=True)
                tmp = f"{path}.tmp"
                with open(tmp, "wb") as fh:
                    fh.write(content)
                os.replace(tmp, path)
            except OSError:
                log.warning("Не удалось сохранить аватар %s", path, exc_info=True)
        return content


_shared: Optional[Avatars] = None


def setup(folder: Optional[str], health: Optional[ProviderHealth] = None) -> Avatars:
    """Общий загрузчик аватаров бота (при старте); health — предохранитель Steam CDN, общий с иконками героев."""
    global _shared
    _shared = Avatars(folder, health=health)
    return _shared


def shared() -> Optional[Avatars]:
    return _shared
