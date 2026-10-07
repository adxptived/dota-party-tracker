import logging
import threading

import pytest
import requests

from mmrbot.health import ProviderHealth, ProviderUnavailable, log_network_error


class Clock:
    """Фейковые часы: monotonic и «настенное» время идут синхронно."""

    def __init__(self):
        self.now = 1000.0

    def mono(self):
        return self.now

    def wall(self):
        return 1_700_000_000.0 + (self.now - 1000.0)

    def advance(self, seconds):
        self.now += seconds


def make(clock=None, **kw):
    clock = clock or Clock()
    return ProviderHealth("OpenDota", clock=clock.mono, wall=clock.wall, **kw), clock


def test_starts_up_and_allows():
    health, _ = make()
    assert health.allow() is True
    assert health.status()["state"] == "up"


def test_failure_pauses_then_single_probe_after_pause():
    health, clock = make()
    health.failure(requests.ConnectTimeout("x"))
    assert health.status()["state"] == "down"
    assert health.allow() is False
    clock.advance(59)
    assert health.allow() is False          # пауза ещё идёт
    clock.advance(2)
    assert health.allow() is True           # одна пробная попытка
    assert health.status()["state"] == "probing"
    assert health.allow() is False          # остальным — отказ, пока проба в полёте


def test_probe_success_restores_up_and_resets_pause():
    health, clock = make()
    health.failure(RuntimeError("x"))
    clock.advance(61)
    assert health.allow()
    health.success()
    status = health.status()
    assert status["state"] == "up" and status["fails"] == 0 and status["next_try"] is None
    assert health.allow() is True


def test_probe_failure_doubles_pause_up_to_cap():
    health, clock = make()
    pauses = []
    health.failure(RuntimeError("x"))
    pauses.append(round(health.status()["next_try"] - clock.wall()))
    for _ in range(7):
        clock.advance(health.remaining() + 0.1)
        assert health.allow()
        health.failure(RuntimeError("x"))
        pauses.append(round(health.status()["next_try"] - clock.wall()))
    assert pauses == [60, 120, 240, 480, 900, 900, 900, 900]


def test_straggler_failures_do_not_escalate_pause():
    """Пять параллельных запросов упали разом — это один сбой, а не пять."""
    health, clock = make()
    for _ in range(5):
        health.failure(requests.ConnectTimeout("x"))
    assert round(health.status()["next_try"] - clock.wall()) == 60
    assert health.status()["fails"] == 1


def test_only_one_probe_with_parallel_callers():
    health, clock = make()
    health.failure(RuntimeError("x"))
    clock.advance(61)
    results = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        results.append(health.allow())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1


def test_stuck_probe_is_released_after_timeout():
    health, clock = make()
    health.failure(RuntimeError("x"))
    clock.advance(61)
    assert health.allow()
    clock.advance(health.PROBE_TIMEOUT + 1)  # проба зависла и не отчиталась
    assert health.allow() is True


def test_available_does_not_consume_probe():
    health, clock = make()
    health.failure(RuntimeError("x"))
    assert health.available() is False
    clock.advance(61)
    assert health.available() is True
    assert health.available() is True        # просмотр не занимает пробу
    assert health.allow() is True


def test_release_gives_probe_back_without_state_change():
    health, clock = make()
    health.failure(RuntimeError("x"))
    clock.advance(61)
    assert health.allow()
    health.release()
    assert health.allow() is True


def test_limited_state_blocks_until_retry_after_then_allows_everyone():
    health, clock = make()
    health.limit(30)
    assert health.status()["state"] == "limited"
    assert health.allow() is False
    clock.advance(31)
    assert health.allow() is True and health.allow() is True   # после лимита — без пробного режима
    assert health.status()["state"] == "up"


def test_state_changes_are_logged_once_each(caplog):
    health, clock = make()
    with caplog.at_level(logging.INFO, logger="mmrbot.health"):
        health.failure(requests.ConnectTimeout("x"))
        health.failure(requests.ConnectTimeout("x"))           # дубль без смены состояния
        clock.advance(61)
        health.allow()
        health.failure(RuntimeError("x"))                      # проба упала — пауза растёт, но это не новая «смена»
        clock.advance(health.remaining() + 1)
        health.allow()
        clock.advance(14 * 60)
        health.success()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(warnings) == 1
    assert "OpenDota недоступен (ConnectTimeout), пауза 60 с" in warnings[0].getMessage()
    assert len(infos) == 1 and "снова доступен" in infos[0].getMessage()
    assert all(r.exc_info is None for r in caplog.records)


def test_status_reports_since_last_ok_and_fails():
    health, clock = make()
    health.success()
    ok_at = clock.wall()
    clock.advance(10)
    health.failure(RuntimeError("x"))
    status = health.status()
    assert status["state"] == "down"
    assert status["since"] == clock.wall()
    assert status["last_ok"] == ok_at
    assert status["fails"] == 1


def test_claim_log_once_per_pause():
    health, clock = make()
    assert health.claim_log() is True        # пока всё хорошо — не гасим
    health.failure(RuntimeError("x"))
    assert health.claim_log() is True
    assert health.claim_log() is False       # повтор в ту же паузу — гасим
    clock.advance(61)
    health.allow()
    health.failure(RuntimeError("x"))
    assert health.claim_log() is True        # новая пауза — снова можно


def test_log_network_error_one_line_for_network_failures(caplog):
    log = logging.getLogger("test.netlog")
    with caplog.at_level(logging.DEBUG, logger="test.netlog"):
        log_network_error(log, "Не обновился игрок 1", requests.ConnectTimeout("boom"))
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert record.exc_info is None
    assert "ConnectTimeout" in record.getMessage() and "Traceback" not in caplog.text


def test_log_network_error_keeps_traceback_for_unexpected(caplog):
    log = logging.getLogger("test.netlog")
    with caplog.at_level(logging.DEBUG, logger="test.netlog"):
        try:
            {}["x"]
        except KeyError as exc:
            log_network_error(log, "Не обновился игрок 1", exc)
    record = caplog.records[0]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None


def test_log_network_error_refusal_is_debug_only(caplog):
    log = logging.getLogger("test.netlog")
    with caplog.at_level(logging.DEBUG, logger="test.netlog"):
        log_network_error(log, "Не обновился игрок 1", ProviderUnavailable("пауза"))
    assert [r.levelno for r in caplog.records] == [logging.DEBUG]


def test_log_network_error_dedupes_within_one_pause(caplog):
    health, _ = make()
    health.failure(RuntimeError("x"))
    log = logging.getLogger("test.netlog")
    with caplog.at_level(logging.DEBUG, logger="test.netlog"):
        for n in range(3):
            log_network_error(log, f"Не обновился игрок {n}", requests.ConnectTimeout("boom"), health=health)
    levels = [r.levelno for r in caplog.records if r.name == "test.netlog"]  # строка о смене состояния — отдельный логгер
    assert levels.count(logging.WARNING) == 1 and levels.count(logging.DEBUG) == 2


@pytest.mark.parametrize("exc", [requests.ReadTimeout("x"), requests.ConnectionError("x")])
def test_log_network_error_covers_requests_family(exc, caplog):
    log = logging.getLogger("test.netlog")
    with caplog.at_level(logging.DEBUG, logger="test.netlog"):
        log_network_error(log, "msg", exc)
    assert caplog.records[0].levelno == logging.WARNING


def test_provider_down_helper_tolerates_clients_without_health():
    from mmrbot.health import provider_down

    class Plain:
        pass

    class WithHealth:
        def __init__(self, health):
            self.health = health

    assert provider_down(Plain()) is False and provider_down(None) is False
    health, clock = make()
    client = WithHealth(health)
    assert provider_down(client) is False
    health.failure(RuntimeError("x"))
    assert provider_down(client) is True
    clock.advance(61)
    assert provider_down(client) is False   # пауза кончилась — пробную попытку пропустим
    health.allow()
    assert provider_down(client) is True    # проба в полёте — остальным лучше не соваться
