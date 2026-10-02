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
        # Лок защищает только резервирование «слота» запроса (троттлинг): сами HTTP-запросы
        # идут параллельно, поэтому латентность сети перекрывается, а частота остаётся в лимите.
        self._lock = threading.Lock()

    def _throttle(self) -> None:
        """Зарезервировать слот под лок, а спать — вне лока, чтобы потоки не стояли в очереди."""
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._last_call + self.min_interval)
            self._last_call = slot
        wait = slot - now
        if wait > 0:
            time.sleep(wait)

    def _get(self, path: str, params: Optional[dict] = None):
        params = dict(params or {})
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"{BASE_URL}{path}"

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

    def refresh(self, account_id: int) -> bool:
        """Попросить OpenDota перечитать историю матчей игрока (POST /refresh).

        Обновление у OpenDota асинхронное: свежие матчи появятся не мгновенно, а
        через некоторое время — зато следующий опрос будет актуальнее. Best-effort.
        """
        self._throttle()
        try:
            self._session.post(f"{BASE_URL}/players/{account_id}/refresh", timeout=self.timeout)
            return True
        except Exception:
            return False

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

    def get_lanes(self, account_id: int) -> dict:
        """Игры/победы по линиям из /players/{id}/counts → {lane_int: (games, wins)}.

        lane_role: 0 — линия неизвестна (нераспарсенные матчи), 1 safe, 2 mid, 3 off, 4 jungle.
        """
        data = self._get(f"/players/{account_id}/counts") or {}
        lane_role = data.get("lane_role") or {}
        result: dict[int, tuple[int, int]] = {}
        for key, stat in lane_role.items():
            try:
                lane = int(key)
            except (TypeError, ValueError):
                continue
            result[lane] = (stat.get("games", 0), stat.get("win", 0))
        return result

    def get_gpm_distribution(self, account_id: int) -> dict:
        """Медиана и пик GPM из гистограммы /players/{id}/histograms/gold_per_min."""
        data = self._get(f"/players/{account_id}/histograms/gold_per_min")
        buckets = [(b["x"], b.get("games", 0)) for b in data if b.get("games")] if isinstance(data, list) else []
        if not buckets:
            return {"median": None, "best": None}
        total = sum(games for _, games in buckets)
        half = total / 2
        cumulative = 0
        median = None
        for x, games in sorted(buckets):
            cumulative += games
            if cumulative >= half:
                median = x
                break
        best = max(x for x, _ in buckets)
        return {"median": median, "best": best}

    _MATCH_FIELDS = {
        "gold_per_min": "gpm", "xp_per_min": "xpm", "last_hits": "last_hits", "denies": "denies",
        "hero_damage": "hero_damage", "tower_damage": "tower_damage", "hero_healing": "hero_healing",
        "net_worth": "net_worth", "level": "level",
    }

    def get_match_player_stats(self, match_id: int, account_id: int) -> Optional[dict]:
        """Пер-матч статистика игрока из /matches/{id} + benchmarks (перцентиль vs тот же герой).

        GPM/урон/хил/нетворт и benchmarks приходят БЕЗ парса (из сводки Valve).
        """
        match = self._get(f"/matches/{match_id}") or {}
        player = next(
            (p for p in match.get("players", []) if p.get("account_id") == account_id), None
        )
        if player is None:
            return None
        result = {out: player.get(src) for src, out in self._MATCH_FIELDS.items()}
        benchmarks = {}
        for metric, value in (player.get("benchmarks") or {}).items():
            benchmarks[metric] = value.get("pct") if isinstance(value, dict) else value
        result["benchmarks"] = benchmarks
        return result

    def get_totals(self, account_id: int) -> dict:
        """Средние GPM/XPM/last hits из /players/{id}/totals (sum/n по полям)."""
        data = self._get(f"/players/{account_id}/totals")
        wanted = {"gold_per_min": "gpm", "xp_per_min": "xpm", "last_hits": "last_hits"}
        result: dict = {"gpm": None, "xpm": None, "last_hits": None}
        if isinstance(data, list):
            for row in data:
                key = wanted.get(row.get("field"))
                if key and row.get("n"):
                    result[key] = row["sum"] / row["n"]
        return result
