"""Клиент OpenDota API (без ключа работает; ключ повышает лимиты).

Синхронный (requests) с троттлингом и ретраями. В async-коде вызывается через
asyncio.to_thread, чтобы не блокировать event loop. Сессию можно подставить (тесты).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Optional

import requests

from .health import ProviderHealth, ProviderUnavailable
from .items import item_slug
from .ranks import average_rank_tier

BASE_URL = "https://api.opendota.com/api"
_RETRY_STATUSES = {429, 500, 502, 503, 504}
RANKED_LOBBY = 7

log = logging.getLogger(__name__)


_ITEM_SLOTS = tuple(f"item_{i}" for i in range(6))  # основные слоты; рюкзак и нейтралка — отдельно
_MAX_RETRY_AFTER = 30.0
_INLINE_WAIT = 10.0  # дольше этого лимит не пережидаем в запросе — сразу отдаём кэш из БД
_MAX_BLOCK = 900.0  # потолок паузы после 429 (сек): дальше пробуем снова
_BLOCK_NO_HEADER = 30.0  # 429 без Retry-After и после всех попыток — короткая пауза


class RateLimited(ProviderUnavailable):
    """OpenDota ответил 429: до конца паузы запросы не отправляются (вызывающий код берёт кэш)."""


def _retry_after_raw(resp) -> Optional[float]:
    """Значение заголовка Retry-After в секундах; None — заголовка нет или он нечисловой."""
    try:
        return max(float((getattr(resp, "headers", None) or {}).get("Retry-After")), 0.0)
    except (TypeError, ValueError):
        return None


def _retry_after(resp, default: float) -> float:
    """Пауза из заголовка Retry-After (секунды), ограниченная сверху; иначе default."""
    value = _retry_after_raw(resp)
    return default if value is None else min(value, _MAX_RETRY_AFTER)


def _purchase_times(player: dict) -> dict:
    """Ключ предмета → время (сек) его последней покупки по purchase_log. Матч без разбора (лога нет) → пусто."""
    bought: dict = {}
    for entry in player.get("purchase_log") or []:
        if isinstance(entry, dict) and isinstance(entry.get("key"), str) and isinstance(entry.get("time"), (int, float)):
            bought[entry["key"]] = max(bought.get(entry["key"], entry["time"]), entry["time"])
    return bought


def _player_build(player: dict) -> dict:
    """Билд игрока из матча OpenDota: предметы, время их покупки, нейтралка, шард и скипетр (с временем)."""
    bought = _purchase_times(player)
    items = [player[slot] for slot in _ITEM_SLOTS if player.get(slot)]
    return {
        "items": items,
        "item_times": [bought.get(item_slug(item_id)) for item_id in items],  # None — время неизвестно
        "neutral_item": player.get("item_neutral") or None,
        "shard": bool(player.get("aghanims_shard")) or "aghanims_shard" in bought,
        "shard_time": bought.get("aghanims_shard"),
        "scepter": bool(player.get("aghanims_scepter")) or "ultimate_scepter" in bought,
        "scepter_time": bought.get("ultimate_scepter"),
        "bought": bought,  # {предмет: время последней покупки} — для предметов медведя Лон Друида
    }


def lineup_of(players) -> Optional[tuple[list, list]]:
    """Составы команд (герои света, герои тьмы) из игроков матча; игроки — список или {слот: игрок} из списка матчей.

    None — состава нет (героев не прислали). Сторона — по player_slot (0–4 свет, 128–132 тьма) или isRadiant.
    """
    if isinstance(players, dict):
        players = [dict(value or {}, player_slot=int(slot)) for slot, value in players.items() if str(slot).isdigit()]
    radiant, dire = [], []
    for player in players or []:
        hero = player.get("hero_id")
        slot = player.get("player_slot")
        if not hero or (slot is None and "isRadiant" not in player):
            continue
        (radiant if (slot < 128 if slot is not None else player["isRadiant"]) else dire).append(hero)
    return (radiant, dire) if radiant and dire else None


def _party_size(players: list, me: dict) -> Optional[int]:
    """Размер пати игрока из состава матча: party_size от OpenDota, иначе союзники с тем же party_id."""
    size = me.get("party_size")
    if size:
        return size
    party_id = me.get("party_id")
    if not party_id or me.get("player_slot") is None:  # 0 — «нет пати» у одиночек: по нему группу не собрать
        return None
    side = me["player_slot"] < 128
    same = sum(
        1 for p in players
        if p.get("party_id") == party_id and p.get("player_slot") is not None and (p["player_slot"] < 128) == side
    )
    return same or None


class OpenDota:
    HISTORY_PAGE = 1000  # размер страницы при полной загрузке истории
    MATCH_CACHE_SIZE = 64  # сколько последних матчей держим в памяти
    MATCH_CACHE_TTL = 600  # сек: свежий матч может дополниться — долго не держим
    REFRESH_GAP = 600  # сек: POST /refresh одного игрока не чаще (обновление у OpenDota всё равно асинхронное)
    REFRESH_GAP_NO_KEY = 1800  # без ключа каждый запрос на счету — пинаем реже
    BACKGROUND_RESERVE = 800  # столько запросов из суточного лимита оставляем опросу игр и командам

    def __init__(
        self,
        api_key: Optional[str] = None,
        min_interval: float = 1.1,
        timeout=(5, 25),  # (соединение, чтение): недоступный сервер отваливается за 5 с, а не за 30
        max_retries: int = 3,
        session=None,
        burst: int = 1,
        background_reserve: Optional[int] = None,
        health: Optional[ProviderHealth] = None,
        proxy: Optional[str] = None,
        enrich_days: int = 90,
        command_wait: float = 4.0,
    ):
        self.api_key = api_key
        # Политика расхода запросов (из .env): за сколько дней догружать детали матчей (0 — вся история)
        # и сколько секунд команда пользователя ждёт обновление, прежде чем ответить из БД.
        self.enrich_days = enrich_days
        self.command_wait = command_wait
        # Прокси только для OpenDota (в нём может быть пароль — нигде не логируем и не выводим в repr).
        self._proxies = {"http": proxy, "https": proxy} if proxy else None
        # Предохранитель: недоступность по сети и 429 — одна логика «не ходить в сеть» (команды берут кэш БД).
        self.health = health or ProviderHealth("OpenDota")
        self.refresh_gap = self.REFRESH_GAP if api_key else self.REFRESH_GAP_NO_KEY
        self.background_reserve = self.BACKGROUND_RESERVE if background_reserve is None else background_reserve
        # Остаток бесплатного суточного лимита — из заголовка ответа OpenDota (без ключа); None — ещё неизвестен.
        self.remaining_day: Optional[int] = None
        self.min_interval = min_interval
        # Сколько запросов можно отправить подряд без паузы (дальше — по одному в min_interval).
        # Лимит OpenDota считается за минуту, поэтому короткая пачка в него укладывается, а
        # /stats на несколько игроков не ждёт по секунде на каждого.
        self.burst = max(1, int(burst))
        self.timeout = timeout
        self.max_retries = max_retries
        if session is None:
            session = requests.Session()
            # Игроки обновляются параллельно: пул по умолчанию (10) рвал бы лишние соединения.
            adapter = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=16)
            session.mount("https://", adapter)
        self._session = session
        self._last_call = 0.0
        self._match_cache: "OrderedDict[int, tuple[float, dict]]" = OrderedDict()
        self._match_locks: dict[int, threading.Lock] = {}
        self._refresh_at: dict[int, float] = {}
        self._parse_requested: set[int] = set()  # матчи, на разбор которых уже просили OpenDota
        self._project_matches = True  # просить список матчей с выбором колонок (составы команд); см. get_matches
        # Лок защищает только резервирование «слота» запроса (троттлинг): сами HTTP-запросы идут
        # параллельно — ожидание сети перекрывается между потоками, частота остаётся в лимите.
        self._lock = threading.Lock()

    def _throttle(self) -> None:
        """Резервируем слот под локом, спим вне лока — потоки не стоят в очереди целиком.

        Ведро с жетонами (GCRA): средняя частота — один запрос в min_interval, но первые burst
        запросов после простоя уходят сразу. _last_call — «теоретическое время» следующего слота.
        """
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._last_call)
            wait = slot - (self.burst - 1) * self.min_interval - now
            self._last_call = slot + self.min_interval
        if wait > 0:
            time.sleep(wait)

    def _net(self) -> dict:
        """Аргументы запроса про сеть: proxies — только если задан OPENDOTA_PROXY. Явный аргумент, а не session.proxies:
        переменные окружения (HTTPS_PROXY) в requests перебивают прокси сессии."""
        return {"proxies": self._proxies} if self._proxies else {}

    def _auth(self) -> dict:
        """Ключ — только в заголовке: URL (а с ним и query-параметры) попадает в тексты ошибок requests и в логи."""
        return {"headers": {"Authorization": f"Bearer {self.api_key}"}} if self.api_key else {}

    def _note_quota(self, resp) -> None:
        """Запомнить остаток суточного лимита из заголовка X-Rate-Limit-Remaining-Day (его шлют запросам без ключа)."""
        try:
            self.remaining_day = int((getattr(resp, "headers", None) or {}).get("X-Rate-Limit-Remaining-Day"))
        except (TypeError, ValueError):
            pass

    def background_allowed(self) -> bool:
        """Можно ли тратить запросы на необязательную фоновую работу (детали старых матчей).

        С ключом суточного потолка нет. Без ключа останавливаемся, когда до конца лимита осталось меньше
        резерва: иначе бэкфилл выбирал бы квоту целиком, и до полуночи UTC бот показывал бы старые данные.
        """
        if self.api_key or self.remaining_day is None:
            return True
        return self.remaining_day > self.background_reserve

    def _refusal(self) -> ProviderUnavailable:
        """Исключение для отказа предохранителя: лимит (429) или недоступность — по состоянию."""
        if self.health.status()["state"] == "limited":
            return RateLimited("OpenDota: пауза после лимита ещё не истекла")
        return ProviderUnavailable("OpenDota недоступен: пауза ещё не истекла")

    def _get(self, path: str, params: Optional[dict] = None):
        if not self.health.allow():
            raise self._refusal()
        try:
            return self._get_with_retries(path, params)
        finally:
            self.health.release()  # проба не должна «зависнуть», если запрос ушёл нестандартным исключением

    def _get_with_retries(self, path: str, params: Optional[dict] = None):
        params = dict(params or {})
        url = f"{BASE_URL}{path}"

        last_exc: Optional[Exception] = None
        limited = False
        for attempt in range(self.max_retries):
            if attempt and self.health.paused():  # пока ретраили, другой поток уже объявил паузу
                raise self._refusal()
            self._throttle()
            delay = 1.5 * (attempt + 1)
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout, **self._auth(), **self._net())
                self._note_quota(resp)
                if resp.status_code in _RETRY_STATUSES:
                    last_exc = RuntimeError(f"OpenDota HTTP {resp.status_code}")
                    limited = resp.status_code == 429
                    asked = _retry_after_raw(resp) if limited else None
                    if asked is not None and asked > _INLINE_WAIT:
                        # Долгая пауза (дневной лимит и т.п.): не висим и не шлём запросы впустую.
                        self.health.limit(min(asked, _MAX_BLOCK))
                        raise RateLimited(f"OpenDota HTTP 429, повтор через {asked:.0f} с")
                    delay = _retry_after(resp, delay)
                else:
                    try:
                        resp.raise_for_status()  # 4xx — не ретраим, сразу наверх
                    except requests.HTTPError:
                        self.health.success()  # сервер ответил — он жив
                        raise
                    data = resp.json()
                    self.health.success()
                    return data
            except requests.HTTPError:
                raise
            except requests.ConnectionError as exc:  # не достучались (connect timeout, DNS): ретраи — только лишнее ожидание
                self.health.failure(exc)
                raise
            except (requests.RequestException, ValueError) as exc:  # сеть / битый JSON
                last_exc = exc
            if attempt < self.max_retries - 1:  # после последней попытки не спим зря
                time.sleep(delay)
        if limited:  # лимит не отпустил за все попытки — остальные запросы этой волны не тратим
            self.health.limit(_BLOCK_NO_HEADER)
        elif last_exc is not None:  # 5xx / read timeout / битый ответ на всех попытках
            self.health.failure(last_exc)
        raise last_exc or RuntimeError("OpenDota: не удалось получить ответ")

    def refresh(self, account_id: int) -> bool:
        """Попросить OpenDota перечитать историю матчей игрока (POST /refresh).

        Обновление у OpenDota асинхронное: свежие матчи появятся не мгновенно, а
        через некоторое время — зато следующий опрос будет актуальнее. Best-effort.
        Повторный вызов раньше refresh_gap ничего не шлёт (False): пинок уже в очереди,
        а слот троттлинга и лимит запросов нужнее самим данным.
        """
        now = time.monotonic()
        with self._lock:
            last = self._refresh_at.get(account_id)
            if last is not None and now - last < self.refresh_gap:
                return False
            self._refresh_at[account_id] = now
        if not self.health.allow():  # пауза: пинок не ушёл — слот «не чаще раза в refresh_gap» не расходуем
            with self._lock:
                self._refresh_at.pop(account_id, None)
            return False
        self._throttle()
        try:
            resp = self._session.post(
                f"{BASE_URL}/players/{account_id}/refresh", timeout=self.timeout, **self._auth(), **self._net()
            )
            self._note_quota(resp)
            if getattr(resp, "status_code", 200) < 500:
                self.health.success()
            else:
                self.health.release()
            return True
        except Exception as exc:
            with self._lock:
                self._refresh_at.pop(account_id, None)  # не дошло — в следующий раз попробуем снова
            if isinstance(exc, requests.ConnectionError):
                self.health.failure(exc)
            else:
                self.health.release()
            return False

    def request_parse(self, match_id: int) -> bool:
        """Попросить OpenDota разобрать реплей матча (POST /request/{id}): без разбора нет таймингов покупок.

        Разбор идёт у OpenDota несколько минут. На один матч просим один раз; best-effort, ошибок не бросает.
        """
        with self._lock:
            if match_id in self._parse_requested:
                return False
            self._parse_requested.add(match_id)
        if not self.health.allow():
            with self._lock:
                self._parse_requested.discard(match_id)
            return False
        self._throttle()
        try:
            resp = self._session.post(f"{BASE_URL}/request/{match_id}", timeout=self.timeout, **self._auth(), **self._net())
            self._note_quota(resp)
            if getattr(resp, "status_code", 200) < 500:
                self.health.success()
            else:
                self.health.release()
            return True
        except Exception as exc:
            with self._lock:
                self._parse_requested.discard(match_id)  # не дошло — в следующий раз попробуем снова
            if isinstance(exc, requests.ConnectionError):
                self.health.failure(exc)
            else:
                self.health.release()
            return False

    def get_heroes(self) -> list[dict]:
        """Справочник героев /heroes: [{id, localized_name, ...}] (пусто при сбое формата)."""
        data = self._get("/heroes")
        return data if isinstance(data, list) else []

    def get_item_ids(self) -> dict:
        """Справочник предметов /constants/item_ids: {"1": "blink", ...} (пусто при сбое формата)."""
        data = self._get("/constants/item_ids")
        return data if isinstance(data, dict) else {}

    def get_profile(self, account_id: int) -> dict:
        data = self._get(f"/players/{account_id}") or {}
        profile = data.get("profile") or {}
        return {
            "rank_tier": data.get("rank_tier"),
            "leaderboard_rank": data.get("leaderboard_rank"),
            "personaname": profile.get("personaname"),
            "avatarfull": profile.get("avatarfull"),
            "profileurl": profile.get("profileurl"),
            "steamid": profile.get("steamid"),
            "loccountrycode": profile.get("loccountrycode"),
            "plus": bool(profile.get("plus")),
            "last_login": profile.get("last_login"),
            "fh_unavailable": profile.get("fh_unavailable"),  # None — признака нет в ответе
        }

    # Колонки списка матчей. С параметром project OpenDota отдаёт только перечисленное (плюс match_id, player_slot,
    # radiant_win), поэтому свой набор по умолчанию перечисляем сами и добавляем heroes — героев всех десяти
    # игроков ({слот: {hero_id, account_id}}): составы команд без отдельного запроса на каждый матч.
    MATCH_LIST_COLUMNS = (
        "hero_id", "start_time", "duration", "lobby_type", "kills", "deaths", "assists",
        "average_rank", "leaver_status", "party_size", "heroes",
    )

    def get_matches(self, account_id: int, limit: Optional[int] = 200, lobby_type: Optional[int] = 7) -> list[dict]:
        """Матчи игрока. По умолчанию только ранкед (lobby_type=7) — фильтр на стороне OpenDota,
        иначе лимит забивается обычными играми. limit=None — вся история."""
        base: dict = {"significant": 0}
        if self._project_matches:
            base["project"] = list(self.MATCH_LIST_COLUMNS)
        if lobby_type is not None:
            base["lobby_type"] = lobby_type
        path = f"/players/{account_id}/matches"
        # Вся история — постранично: один огромный ответ OpenDota иногда рвёт (HTTP 500).
        page_size = limit if limit is not None else self.HISTORY_PAGE
        result: list[dict] = []
        offset = 0
        while True:
            params = dict(base, limit=page_size)
            if limit is None:
                params["offset"] = offset
            page = self._get(path, params=params)
            if not isinstance(page, list):
                break
            if self._project_matches and page and "start_time" not in page[0]:
                # Выбор колонок сработал не так, как ожидалось (в ответе нет обязательного поля): дальше просим
                # список без project — составов не будет, зато обновление игроков не ломается.
                log.warning("OpenDota вернул список матчей без start_time при выборе колонок — отключаю project")
                self._project_matches = False
                return self.get_matches(account_id, limit, lobby_type)
            result.extend(page)
            if limit is not None or len(page) < self.HISTORY_PAGE:
                break
            offset += self.HISTORY_PAGE
        return result

    def get_recent_matches(self, account_id: int) -> list[dict]:
        """Последние ~20 матчей игрока (все лобби) сразу с GPM/XPM/уроном/лечением/добиваниями.

        Один лёгкий запрос вместо списка на 200 матчей + отдельного запроса на каждый матч.
        Ранкед отбирает вызывающий код; порядок — от новых к старым.
        """
        data = self._get(f"/players/{account_id}/recentMatches")
        return data if isinstance(data, list) else []

    _MATCH_FIELDS = {
        "gold_per_min": "gpm", "xp_per_min": "xpm", "last_hits": "last_hits", "denies": "denies",
        "hero_damage": "hero_damage", "tower_damage": "tower_damage", "hero_healing": "hero_healing",
        "net_worth": "net_worth", "level": "level", "leaver_status": "leaver_status",
    }

    def get_match(self, match_id: int) -> dict:
        """Полный матч /matches/{id} с короткоживущим кэшем в памяти.

        Одновременные запросы одного матча (участники пати обновляются параллельно) ждут
        первый ответ, а не идут в сеть каждый сам.
        """
        with self._lock:
            hit = self._match_cache.get(match_id)
            if hit and time.monotonic() - hit[0] < self.MATCH_CACHE_TTL:
                return hit[1]
            gate = self._match_locks.setdefault(match_id, threading.Lock())
        with gate:
            with self._lock:
                hit = self._match_cache.get(match_id)
                if hit and time.monotonic() - hit[0] < self.MATCH_CACHE_TTL:
                    return hit[1]
            try:
                match = self._get(f"/matches/{match_id}") or {}
            finally:
                with self._lock:
                    self._match_locks.pop(match_id, None)
            if match.get("players"):  # пустой ответ не кэшируем — матч мог ещё не доехать
                with self._lock:
                    self._match_cache[match_id] = (time.monotonic(), match)
                    self._match_cache.move_to_end(match_id)
                    while len(self._match_cache) > self.MATCH_CACHE_SIZE:
                        self._match_cache.popitem(last=False)
            return match

    def get_match_builds(self, match_id: int) -> dict:
        """Билды всех игроков матча {hero_id: билд} из того же (кэшируемого) /matches/{id}.

        Игроков сопоставляем по герою: он уникален в матче, а у скрытых профилей account_id обнулён.
        """
        players = self.get_match(match_id).get("players") or []
        return {p["hero_id"]: _player_build(p) for p in players if p.get("hero_id")}

    def get_match_player_stats(
        self, match_id: int, account_id: int, player_slot: Optional[int] = None
    ) -> Optional[dict]:
        """Пер-матч статистика игрока из /matches/{id} + benchmarks (перцентиль vs тот же герой).

        GPM/урон/хил/нетворт и benchmarks приходят БЕЗ парса (из сводки Valve).
        Матч берётся из кэша: совместная игра пати — один запрос на всех её участников.
        """
        match = self.get_match(match_id)
        players = match.get("players") or []
        player = next((p for p in players if p.get("account_id") == account_id), None)
        if player is None and player_slot is not None:  # скрытый профиль: account_id в матче обнулён — ищем по слоту
            player = next((p for p in players if p.get("player_slot") == player_slot), None)
        if player is None:
            return None
        result = {out: player.get(src) for src, out in self._MATCH_FIELDS.items()}
        result.update(_player_build(player))
        result["party_size"] = _party_size(players, player)
        result["lineup"] = lineup_of(players)
        # Стаки есть только в разобранном матче (version): в неразобранном OpenDota отдаёт пустой счётчик, и нулём
        # его считать нельзя — «0 стаков» вытеснило бы настоящее значение.
        result["stacks"] = player.get("camps_stacked") if match.get("version") else None
        # average_rank из OpenDota врёт на высоких лобби (Immortal-лобби → Divine 5), считаем сами по игрокам.
        result["average_rank"] = average_rank_tier([p.get("rank_tier") for p in players])
        benchmarks = {}
        for metric, value in (player.get("benchmarks") or {}).items():
            benchmarks[metric] = value.get("pct") if isinstance(value, dict) else value
        result["benchmarks"] = benchmarks
        return result
