"""Отчёты об ошибках владельцу: что уходит, что глушится, что вырезается."""
import asyncio
import logging
import sys
import threading

import pytest

from mmrbot import errors
from mmrbot.config import load_config
from mmrbot.errors import ErrorReporter, format_report, scrub

TOKEN = "8997261910:AAH_fake_token_fake_token_fake_tok1"


def _record(message="Сбой", exc=None, name="mmrbot.tracker", level=logging.ERROR, args=()):
    exc_info = None
    if exc is not None:
        try:
            raise exc
        except Exception:
            exc_info = sys.exc_info()
    return logging.LogRecord(name, level, __file__, 10, message, args, exc_info)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _run(reporter_factory, action):
    """Выполнить action(reporter) внутри цикла событий и дождаться отправок."""
    sent = []

    async def go():
        async def send(chat_id, text):
            sent.append((chat_id, text))

        reporter = reporter_factory(send).attach(asyncio.get_running_loop())
        result = action(reporter)
        if asyncio.iscoroutine(result):
            await result
        for _ in range(5):
            await asyncio.sleep(0)
        return reporter

    asyncio.run(go())
    return sent


def test_error_with_traceback_reaches_owner():
    sent = _run(lambda send: ErrorReporter(send, 77), lambda r: r.handle(_record("Чат 5 сломался", KeyError("hero"))))
    assert len(sent) == 1 and sent[0][0] == 77
    text = sent[0][1]
    assert "Ошибка бота" in text and "mmrbot.tracker" in text and "Чат 5 сломался" in text
    assert "KeyError" in text and "<pre>" in text


def test_warnings_and_expected_network_errors_are_not_reported():
    def act(reporter):
        logger = logging.getLogger("mmrbot.test_quiet")
        logger.addHandler(reporter)
        logger.propagate = False
        try:
            logger.warning("OpenDota недоступен: ConnectTimeout")
            logger.info("обычная работа")
        finally:
            logger.removeHandler(reporter)

    assert _run(lambda send: ErrorReporter(send, 77), act) == []


def test_same_error_is_sent_once_per_cooldown_with_repeat_count():
    clock = Clock()

    def boom():
        return _record("Задача упала", ValueError("x"))

    def act(reporter):
        reporter.handle(boom())
        reporter.handle(boom())
        reporter.handle(boom())
        clock.now += 601
        reporter.handle(boom())

    sent = _run(lambda send: ErrorReporter(send, 77, cooldown=600, clock=clock), act)
    assert len(sent) == 2
    assert "повторилась" not in sent[0][1]
    assert "повторилась ещё 2 раз" in sent[1][1]


def test_different_errors_are_not_merged():
    def act(reporter):
        reporter.handle(_record("А", ValueError("x")))
        reporter.handle(_record("Б", KeyError("y")))
        reporter.handle(_record("без исключения"))

    assert len(_run(lambda send: ErrorReporter(send, 77), act)) == 3


def test_hourly_limit_stops_a_flood():
    clock = Clock()

    def act(reporter):
        for i in range(10):
            reporter.handle(_record(f"Ошибка {i}", type(f"E{i}", (Exception,), {})("x")))
        clock.now += 3601
        reporter.handle(_record("после паузы", RuntimeError("z")))

    sent = _run(lambda send: ErrorReporter(send, 77, hourly_limit=3, clock=clock), act)
    assert len(sent) == 4 and "после паузы" in sent[-1][1]


def test_secrets_never_leave_the_process():
    leaked = f"https://api.telegram.org/bot{TOKEN}/sendMessage via socks5h://user:hunter2@proxy:1080 key=STRATZKEY123"
    record = _record(f"Не удалось: {leaked}", RuntimeError(leaked))
    text = format_report(record, secrets=("STRATZKEY123",))
    for secret in (TOKEN, "hunter2", "STRATZKEY123"):
        assert secret not in text
    assert "proxy:1080" in text  # адрес без пароля остаётся — по нему видно, что сломалось
    assert scrub("ключ ab", ("ab",)) == "ключ ab"  # слишком короткие «секреты» не вырезаем — заденут обычный текст


def test_long_report_fits_telegram_and_keeps_markup_whole():
    def deep(n):
        if n == 0:
            raise RuntimeError("<&>" * 400)
        deep(n - 1)

    try:
        deep(60)
    except RuntimeError:
        record = logging.LogRecord("mmrbot.x", logging.ERROR, __file__, 1, "x" * 3000, (), sys.exc_info())
    text = format_report(record)
    assert len(text) <= 4096
    assert text.count("<pre>") == text.count("</pre>") == 1 and text.endswith("</pre>")
    assert "RuntimeError" in text  # хвост трейсбека — место сбоя — сохранён


def test_report_of_pure_markup_characters_still_fits():
    record = _record("&" * 3000, RuntimeError("&" * 3000))
    text = format_report(record)
    assert len(text) <= 4096 and text.endswith("</pre>") and "RuntimeError" in text


def test_bad_format_arguments_do_not_hide_the_report():
    text = format_report(_record("значение %d", args=("не число",)))
    assert "значение %d" in text


def test_records_from_worker_threads_are_delivered():
    def act(reporter):
        thread = threading.Thread(target=lambda: reporter.handle(_record("из потока", OSError("disk"))))
        thread.start()
        thread.join()

    sent = _run(lambda send: ErrorReporter(send, 77), act)
    assert len(sent) == 1 and "из потока" in sent[0][1]


def test_send_failure_is_swallowed_and_not_reported_again(caplog):
    attempts = []

    async def go():
        async def send(chat_id, text):
            attempts.append(text)
            raise ConnectionError("telegram down")

        reporter = ErrorReporter(send, 77).attach(asyncio.get_running_loop())
        root = logging.getLogger()
        root.addHandler(reporter)
        try:
            logging.getLogger("mmrbot.any").error("первая")
            for _ in range(5):
                await asyncio.sleep(0)
        finally:
            root.removeHandler(reporter)

    with caplog.at_level(logging.WARNING):
        asyncio.run(go())
    assert len(attempts) == 1  # сбой отправки не породил второй отчёт
    assert any("Не удалось отправить отчёт" in r.getMessage() for r in caplog.records)


def test_install_wires_root_logger_and_falls_back_to_plain_text():
    calls = []

    class TelegramBadRequest(Exception):
        pass

    class Bot:
        async def send_message(self, chat_id, text, parse_mode=None):
            calls.append((chat_id, text, parse_mode))
            if parse_mode == "HTML":
                raise TelegramBadRequest("can't parse entities")

    async def go():
        assert errors.install(Bot(), None) is None  # без ERROR_CHAT_ID отчёты выключены
        logger = logging.getLogger("mmrbot.install_test")
        reporter = errors.install(Bot(), 77, logger=logger)
        try:
            logger.error("упало <здесь>")
            for _ in range(5):
                await asyncio.sleep(0)
        finally:
            logger.removeHandler(reporter)

    asyncio.run(go())
    assert [c[2] for c in calls] == ["HTML", None]
    assert "упало <здесь>" in calls[1][1] and "<b>" not in calls[1][1]


def test_sentry_is_optional(monkeypatch, caplog):
    assert errors.setup_sentry(None) is False
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)  # пакет не установлен
    with caplog.at_level(logging.WARNING):
        assert errors.setup_sentry("https://key@sentry.example/1") is False
    assert any("sentry-sdk не установлен" in r.getMessage() for r in caplog.records)


def test_sentry_events_are_scrubbed(monkeypatch):
    captured = {}

    class FakeSentry:
        @staticmethod
        def init(**kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "sentry_sdk", FakeSentry)
    assert errors.setup_sentry("https://key@sentry.example/1", (TOKEN,)) is True
    event = {"message": f"bot{TOKEN}", "exception": {"values": [{"value": f"url {TOKEN}"}]}, "level": "error", "n": 1}
    cleaned = captured["before_send"](event, {})
    assert TOKEN not in str(cleaned) and cleaned["n"] == 1 and captured["send_default_pii"] is False


def test_config_reads_error_chat_and_lists_secrets(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    monkeypatch.setenv("STRATZ_API_KEY", "stratz-secret")
    monkeypatch.delenv("ERROR_CHAT_ID", raising=False)
    assert load_config().error_chat_id is None
    monkeypatch.setenv("ERROR_CHAT_ID", " 123456789 ")
    config = load_config()
    assert config.error_chat_id == 123456789
    assert TOKEN in config.secrets() and "stratz-secret" in config.secrets()
    monkeypatch.setenv("ERROR_CHAT_ID", "@me")
    with pytest.raises(RuntimeError, match="ERROR_CHAT_ID"):
        load_config()
