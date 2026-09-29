"""Клиент OpenDota API (без ключа работает; ключ повышает лимиты).

Синхронный (requests) с троттлингом и ретраями. В async-коде вызывается через
asyncio.to_thread, чтобы не блокировать event loop. Сессию можно подставить (тесты).
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import requests

BASE_URL = "https://api.opendota.com/api"
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class OpenDota:
    def __init__(
        self,
        api_key: Optional[str] = None,
        min_interval: float = 1.1,
        timeout: int = 30,
        max_retries: int = 3,
        session=None,
    ):
        self.api_key = api_key
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = session or requests.Session()
        self._last_call = 0.0
        # Один клиент шарится между to_thread-воркерами: сериализуем запросы,
        # чтобы не ломать троттлинг и не делить requests.Session между потоками гонкой.
        self._lock = threading.Lock()

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _get(self, path: str, params: Optional[dict] = None):
        params = dict(params or {})
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"{BASE_URL}{path}"

        with self._lock:  # сериализация запросов между потоками (троттлинг + общая Session)
            last_exc: Optional[Exception] = None
            for attempt in range(self.max_retries):
                self._throttle()
                try:
                    resp = self._session.get(url, params=params, timeout=self.timeout)
                except requests.RequestException as exc:  # сетевые сбои
                    last_exc = exc
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if resp.status_code in _RETRY_STATUSES:
                    last_exc = RuntimeError(f"OpenDota HTTP {resp.status_code}")
                    time.sleep(1.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp.json()
            raise last_exc or RuntimeError("OpenDota: не удалось получить ответ")

    def get_profile(self, account_id: int) -> dict:
        data = self._get(f"/players/{account_id}") or {}
        return {
            "rank_tier": data.get("rank_tier"),
            "leaderboard_rank": data.get("leaderboard_rank"),
            "personaname": (data.get("profile") or {}).get("personaname"),
        }

    def get_matches(self, account_id: int, limit: int = 200) -> list[dict]:
        # significant=0 включает все типы лобби; ранкед-фильтр делаем сами по lobby_type.
        data = self._get(f"/players/{account_id}/matches", params={"limit": limit, "significant": 0})
        return data if isinstance(data, list) else []
