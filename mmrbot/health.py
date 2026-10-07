"""Предохранитель внешних сервисов (circuit breaker) и аккуратный лог сетевых сбоев.

Один экземпляр ProviderHealth на сервис (OpenDota, Stratz, CDN иконок): после сетевого сбоя в сеть не ходим
всю паузу (команды берут кэш БД и отвечают сразу), пауза растёт 60 → 120 → … → 900 с. По окончании паузы
пропускается ОДНА пробная попытка (half-open), остальные запросы в это время получают отказ.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import requests

log = logging.getLogger(__name__)


class ProviderUnavailable(RuntimeError):
    """Сервис недоступен: идёт пауза предохранителя, в сеть не ходили (вызывающий код берёт кэш)."""


class ProviderHealth:
    """Состояние внешнего сервиса: up / down (пауза) / probing (одна пробная попытка) / limited (429)."""

    BASE_PAUSE = 60.0
    MAX_PAUSE = 900.0
    PROBE_TIMEOUT = 60.0  # пробная попытка, не отчитавшаяся за это время, считается потерянной

    def __init__(
        self,
        name: str,
        *,
        clock: Optional[Callable[[], float]] = None,
        wall: Optional[Callable[[], float]] = None,
        base_pause: Optional[float] = None,
        max_pause: Optional[float] = None,
    ):
        self.name = name
        # Часы берём лениво (time.monotonic на каждый вызов): тесты подменяют их через monkeypatch.
        self._clock = clock or (lambda: time.monotonic())
        self._wall = wall or (lambda: time.time())
        self.base_pause = self.BASE_PAUSE if base_pause is None else base_pause
        self.max_pause = self.MAX_PAUSE if max_pause is None else max_pause
        self._lock = threading.Lock()
        self._state = "up"
        self._blocked_until = 0.0  # monotonic: до этого момента в сеть не ходим
        self._fails = 0  # подряд идущие неудачи (определяют длину паузы)
        self._since: Optional[float] = None  # wall: когда сервис «лёг» (или упёрся в лимит)
        self._last_ok: Optional[float] = None  # wall: последний успешный ответ
        self._probe_started: Optional[float] = None  # monotonic: пробная попытка в полёте
        self._log_claimed = False

    # -- решение «идти ли в сеть» -------------------------------------------------------------

    def allow(self) -> bool:
        """Можно ли идти в сеть сейчас. После паузы пропускает одну пробную попытку (занимает её)."""
        with self._lock:
            now = self._clock()
            if self._state == "up":
                return True
            if now < self._blocked_until:
                return False
            if self._state == "limited":  # лимит кончился — без пробного режима, ходят все
                self._state = "up"
                self._since = None
                return True
            if self._probe_started is not None and now - self._probe_started < self.PROBE_TIMEOUT:
                return False  # проба уже в полёте
            self._state = "probing"
            self._probe_started = now
            return True

    def available(self) -> bool:
        """Как allow(), но ничего не занимает: годится для «стоит ли вообще начинать» (пул потоков, фоновая задача)."""
        with self._lock:
            now = self._clock()
            if self._state == "up":
                return True
            if now < self._blocked_until:
                return False
            if self._state == "limited":
                return True
            return self._probe_started is None or now - self._probe_started >= self.PROBE_TIMEOUT

    def paused(self) -> bool:
        """Идёт ли сейчас пауза (чисто по времени, пробу не трогает) — для проверки между попытками ретрая."""
        with self._lock:
            return self._state != "up" and self._clock() < self._blocked_until

    def remaining(self) -> float:
        """Сколько секунд осталось до следующей попытки (0 — можно сейчас)."""
        with self._lock:
            return max(0.0, self._blocked_until - self._clock()) if self._state != "up" else 0.0

    # -- результаты запросов ------------------------------------------------------------------

    def success(self) -> None:
        """Ответ получен: сервис жив, пауза сброшена."""
        with self._lock:
            was_down = self._state in ("down", "probing")
            since = self._since
            self._state = "up"
            self._fails = 0
            self._blocked_until = 0.0
            self._probe_started = None
            self._since = None
            self._log_claimed = False
            self._last_ok = self._wall()
            wall_now = self._last_ok
        if was_down:
            lasted = f"лежал {_duration(wall_now - since)}" if since is not None else "был недоступен"
            log.info("%s снова доступен (%s)", self.name, lasted)

    def failure(self, exc: Optional[BaseException] = None) -> None:
        """Сетевой сбой или 5xx: пауза (растёт с каждой неудачной пробой, потолок max_pause)."""
        with self._lock:
            now = self._clock()
            if self._state == "down" and now < self._blocked_until:
                return  # «запоздавший» параллельный запрос того же сбоя — не раздуваем паузу
            first = self._state not in ("down", "probing")
            self._fails += 1
            pause = min(self.base_pause * (2 ** (self._fails - 1)), self.max_pause)
            self._state = "down"
            self._blocked_until = now + pause
            self._probe_started = None
            self._log_claimed = False
            if first or self._since is None:
                self._since = self._wall()
        reason = type(exc).__name__ if exc is not None else "сбой"
        if first:
            log.warning("%s недоступен (%s), пауза %d с", self.name, reason, pause)
        else:
            log.debug("%s всё ещё недоступен (%s), пауза %d с", self.name, reason, pause)

    def limit(self, seconds: float) -> None:
        """Лимит запросов (429): не ходим seconds секунд; после паузы пробной попытки не нужно."""
        with self._lock:
            if self._state in ("down", "probing"):
                return  # недоступность важнее лимита
            now = self._clock()
            self._state = "limited"
            self._blocked_until = max(self._blocked_until, now + max(seconds, 0.0))
            if self._since is None:
                self._since = self._wall()

    def release(self) -> None:
        """Отдать пробную попытку, если запрос закончился ни успехом, ни сетевым сбоем."""
        with self._lock:
            self._probe_started = None

    # -- наблюдаемость ------------------------------------------------------------------------

    def status(self) -> dict:
        """Снимок для /status и heartbeat: state, since, next_try, last_ok, fails (время — unix, wall-clock)."""
        with self._lock:
            now = self._clock()
            paused = self._state != "up"
            return {
                "name": self.name,
                "state": self._state,
                "since": self._since,
                "next_try": self._wall() + max(0.0, self._blocked_until - now) if paused else None,
                "last_ok": self._last_ok,
                "fails": self._fails,
            }

    def is_down(self) -> bool:
        """Недоступен или упёрся в лимит прямо сейчас (для пометки «данные устарели»)."""
        with self._lock:
            return self._state in ("down", "probing") or (self._state == "limited" and self._clock() < self._blocked_until)

    def claim_log(self) -> bool:
        """True — можно написать в лог об ошибке (раз за паузу); пока сервис жив, не ограничивает."""
        with self._lock:
            if self._state == "up" or not self._log_claimed:
                self._log_claimed = self._state != "up"
                return True
            return False


def _duration(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    if seconds >= 3600:
        return f"{seconds // 3600} ч {seconds % 3600 // 60} мин"
    if seconds >= 60:
        return f"{seconds // 60} мин"
    return f"{seconds} с"


_NETWORK_ERRORS = (requests.RequestException,)


def is_network_error(exc: BaseException) -> bool:
    """Ожидаемый сбой внешнего сервиса (сеть, лимит, пауза предохранителя), а не баг в нашем коде."""
    return isinstance(exc, _NETWORK_ERRORS + (ProviderUnavailable,))


def log_network_error(logger: logging.Logger, msg: str, exc: BaseException, *, health: Optional[ProviderHealth] = None) -> None:
    """Одна строка вместо трейсбека для ожидаемых сетевых сбоев; полный трейсбек — только для неожиданных.

    Отказ предохранителя — debug (само падение уже залогировано при смене состояния). С health повторные
    сообщения в одну паузу гасятся до debug: при падении OpenDota лог не превращается в простыню по игрокам.
    """
    if isinstance(exc, ProviderUnavailable):
        logger.debug("%s: %s", msg, exc)
    elif is_network_error(exc):
        quiet = health is not None and not health.claim_log()
        (logger.debug if quiet else logger.warning)("%s: %s", msg, type(exc).__name__)
    else:
        logger.error(msg, exc_info=(type(exc), exc, exc.__traceback__))
