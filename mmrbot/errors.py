"""Отчёты об ошибках владельцу бота: личное сообщение в Telegram и, по желанию, Sentry.

Всё, что бот пишет в лог уровнем ERROR и выше (неотловленный сбой хендлера, упавшая задача планировщика,
неожиданное исключение при обновлении игрока), уходит в чат `ERROR_CHAT_ID`. Ожидаемые сетевые сбои пишутся
уровнем WARNING (см. health.log_network_error) и сюда не попадают.

Защита от спама: одна и та же ошибка (тип исключения + место в коде) повторно шлётся не чаще, чем раз
в `cooldown` секунд — следующее сообщение скажет, сколько раз она случилась за это время; всего в час
уходит не больше `hourly_limit` сообщений. Секреты (токен бота, ключи API, пароль прокси) вырезаются из текста.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time
import traceback
from typing import Callable, Iterable, Optional

log = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096
TRACE_LIMIT = 2800  # символов трейсбека в сообщении (хвост: место сбоя — в конце)
MESSAGE_LIMIT = 700  # символов самой записи лога
# Токен бота в чужом тексте (адрес запроса к Bot API в сообщении исключения): 123456:AA…
_TOKEN_RE = re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{30,}")  # перед цифрами бывает «bot» — границу слова не требуем
# Логин и пароль в адресе (прокси): scheme://user:pass@host
_URL_AUTH_RE = re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)")


def scrub(text: str, secrets: Iterable[str] = ()) -> str:
    """Вырезать из текста секреты: перечисленные значения, токены Bot API и пароли в адресах."""
    for secret in secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, "***")
    return _URL_AUTH_RE.sub("***", _TOKEN_RE.sub("***", text))


def signature(record: logging.LogRecord) -> tuple:
    """Что считается «той же ошибкой»: тип исключения и строка, где оно возникло (без текста — в нём бывают id)."""
    if record.exc_info and record.exc_info[1] is not None:
        exc = record.exc_info[1]
        frames = traceback.extract_tb(exc.__traceback__)
        where = (frames[-1].filename, frames[-1].lineno) if frames else (record.pathname, record.lineno)
        return (type(exc).__name__, *where)
    return (record.name, record.pathname, record.lineno)


def format_report(record: logging.LogRecord, repeats: int = 0, secrets: Iterable[str] = ()) -> str:
    """Сообщение владельцу (Telegram HTML): где, что и хвост трейсбека."""
    try:
        message = record.getMessage()
    except Exception:  # кривые аргументы форматирования не должны глушить сам отчёт
        message = str(record.msg)
    message = scrub(message, secrets)
    if len(message) > MESSAGE_LIMIT:
        message = message[:MESSAGE_LIMIT] + "…"
    lines = [f"🚨 <b>Ошибка бота</b> · <code>{html.escape(record.name)}</code>", html.escape(message)]
    if repeats:
        lines.append(f"<i>С прошлого сообщения повторилась ещё {repeats} раз(а).</i>")
    head = "\n".join(lines)
    if not (record.exc_info and record.exc_info[1] is not None):
        return head
    # Последняя строка трейсбека («Тип: текст») может быть огромной — укорачиваем её отдельно, чтобы она
    # не вытеснила стек: в отчёте нужны и место сбоя, и тип исключения.
    full = "".join(traceback.format_exception(*record.exc_info)).rstrip()
    last = "".join(traceback.format_exception_only(record.exc_info[0], record.exc_info[1])).rstrip()
    stack = full[: -len(last)] if last and full.endswith(last) else full + "\n"
    last = scrub(last, secrets)
    if len(last) > MESSAGE_LIMIT:
        last = last[:MESSAGE_LIMIT] + "…"
    stack = scrub(stack, secrets)
    limit = TRACE_LIMIT
    while True:  # режем до экранирования: обрезка готового HTML могла бы разорвать тег или &-последовательность
        shown = stack if len(stack) <= limit else "…" + stack[-limit:]
        text = f"{head}\n<pre>{html.escape(shown + last)}</pre>"
        if len(text) <= TELEGRAM_LIMIT:
            return text
        if limit <= 0:  # не помещается даже без стека (текст из одних спецсимволов) — самый короткий вариант
            return (f"🚨 <b>Ошибка бота</b> · <code>{html.escape(record.name)}</code>\n{html.escape(message[:200])}\n"
                    f"<pre>{html.escape(last[:200])}</pre>")
        limit = max(0, limit - (len(text) - TELEGRAM_LIMIT) - 50)


class ErrorReporter(logging.Handler):
    """Обработчик логов: записи ERROR+ отправляет владельцу бота в Telegram.

    send — корутина `(chat_id, text) -> None` (обёртка над bot.send_message). Записи могут приходить из любых
    потоков (клиенты OpenDota/Stratz работают в пуле): отправка планируется в цикл событий, заданный в attach().
    """

    def __init__(
        self, send: Callable, chat_id: int, *, secrets: Iterable[str] = (), cooldown: float = 600.0,
        hourly_limit: int = 20, clock: Optional[Callable[[], float]] = None,
    ):
        super().__init__(level=logging.ERROR)
        self._send = send
        self.chat_id = chat_id
        self.secrets = tuple(s for s in secrets if s)
        self.cooldown = cooldown
        self.hourly_limit = hourly_limit
        self._clock = clock or time.monotonic
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._last: dict[tuple, float] = {}  # подпись ошибки → когда о ней сообщали
        self._muted: dict[tuple, int] = {}  # подпись → сколько повторов проглочено с тех пор
        self._sent_at: list[float] = []  # моменты отправок за последний час
        self._tasks: set = set()

    def attach(self, loop: asyncio.AbstractEventLoop) -> "ErrorReporter":
        self._loop = loop
        return self

    # -- решение «слать ли» ------------------------------------------------------------------------

    def _admit(self, key: tuple) -> Optional[int]:
        """Число проглоченных повторов, если сообщение пора слать; None — промолчать."""
        now = self._clock()
        last = self._last.get(key)
        if last is not None and now - last < self.cooldown:
            self._muted[key] = self._muted.get(key, 0) + 1
            return None
        self._sent_at = [t for t in self._sent_at if now - t < 3600]
        if len(self._sent_at) >= self.hourly_limit:
            self._muted[key] = self._muted.get(key, 0) + 1
            return None
        self._sent_at.append(now)
        self._last[key] = now
        if len(self._last) > 500:  # подписи старых ошибок не копим
            for stale in [k for k, t in self._last.items() if now - t >= self.cooldown]:
                self._last.pop(stale, None)
                self._muted.pop(stale, None)
        return self._muted.pop(key, 0)

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == __name__:  # собственные сообщения о сбое отправки — иначе петля
            return
        try:
            repeats = self._admit(signature(record))  # под блокировкой обработчика: её берёт Handler.handle
            if repeats is None:
                return
            text = format_report(record, repeats, self.secrets)
            loop = self._loop
            if loop is None or loop.is_closed():
                return
            loop.call_soon_threadsafe(self._schedule, text)
        except Exception:  # отчёт об ошибке не должен ломать то, что её залогировало
            self.handleError(record)

    def _schedule(self, text: str) -> None:
        task = asyncio.ensure_future(self._deliver(text))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _deliver(self, text: str) -> None:
        try:
            await self._send(self.chat_id, text)
        except Exception as exc:
            # WARNING, не ERROR: сбой отправки отчёта сам отчётом не становится.
            log.warning("Не удалось отправить отчёт об ошибке в чат %s: %s", self.chat_id, type(exc).__name__)


def setup_sentry(dsn: Optional[str], secrets: Iterable[str] = ()) -> bool:
    """Включить Sentry, если задан SENTRY_DSN и установлен пакет sentry-sdk. Вернуть, включён ли."""
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        log.warning("SENTRY_DSN задан, но пакет sentry-sdk не установлен (pip install sentry-sdk) — Sentry выключен")
        return False
    secrets = tuple(s for s in secrets if s)

    def clean(value):
        if isinstance(value, str):
            return scrub(value, secrets)
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        return value

    sentry_sdk.init(dsn=dsn, send_default_pii=False, before_send=lambda event, hint: clean(event))
    log.info("Sentry включён")
    return True


def install(bot, chat_id: Optional[int], secrets: Iterable[str] = (), logger: Optional[logging.Logger] = None,
            ) -> Optional[ErrorReporter]:
    """Подключить отчёты в Telegram к корневому логгеру (вызывать внутри работающего цикла событий)."""
    if not chat_id:
        return None

    async def send(target: int, text: str) -> None:
        try:
            await bot.send_message(target, text, parse_mode="HTML")
        except Exception as exc:
            if type(exc).__name__ != "TelegramBadRequest":
                raise
            # Telegram не принял разметку — тот же отчёт простым текстом: лучше некрасиво, чем никак.
            await bot.send_message(target, html.unescape(re.sub(r"</?(?:b|i|code|pre)>", "", text)))

    reporter = ErrorReporter(send, chat_id, secrets=secrets).attach(asyncio.get_running_loop())
    (logger or logging.getLogger()).addHandler(reporter)
    log.info("Отчёты об ошибках будут приходить в чат %s", chat_id)
    return reporter
