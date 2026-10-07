import asyncio
from datetime import datetime, timezone

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import SendMessage

from mmrbot import scheduler as sched
from mmrbot.scheduler import due_local_date
from mmrbot.storage import Chat, Storage


def chat(digest_hour=10, tz="Europe/Moscow", last=None):
    return Chat(chat_id=1, digest_hour=digest_hour, mmr_step=25, tz=tz, last_digest_date=last)


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_due_at_digest_hour():
    # 07:00 UTC == 10:00 МСК
    assert due_local_date(chat(digest_hour=10), utc(2026, 9, 29, 7)) == "2026-09-29"


def test_not_due_before_hour():
    # 06:00 UTC == 09:00 МСК < 10
    assert due_local_date(chat(digest_hour=10), utc(2026, 9, 29, 6)) is None


def test_catch_up_after_hour_same_day():
    # 08:00 UTC == 11:00 МСК, дайджест ещё не слали → догоняем
    assert due_local_date(chat(digest_hour=10), utc(2026, 9, 29, 8)) == "2026-09-29"


def test_not_due_if_already_sent_today():
    c = chat(digest_hour=10, last="2026-09-29")
    assert due_local_date(c, utc(2026, 9, 29, 7)) is None


def test_due_next_day_after_previous_send():
    c = chat(digest_hour=10, last="2026-09-28")
    assert due_local_date(c, utc(2026, 9, 29, 7)) == "2026-09-29"


def test_respects_chat_timezone():
    # Asia/Yekaterinburg = UTC+5; 05:00 UTC == 10:00 YEKT
    c = chat(digest_hour=10, tz="Asia/Yekaterinburg")
    assert due_local_date(c, utc(2026, 9, 29, 5)) == "2026-09-29"


def test_bad_timezone_falls_back_to_moscow():
    c = chat(digest_hour=10, tz="Not/AZone")
    assert due_local_date(c, utc(2026, 9, 29, 7)) == "2026-09-29"


# --- send_digest: устойчивость к потере доступа к чату -----------------------


class _FailingBot:
    def __init__(self, exc):
        self.exc = exc
        self.sent = 0

    async def send_message(self, *a, **kw):
        self.sent += 1
        raise self.exc


def _run_digest(tmp_path, monkeypatch, exc):
    async def fake_board(*a, **kw):
        return "доска"

    monkeypatch.setattr(sched, "render_board", fake_board)
    import time
    storage = Storage(str(tmp_path / "t.db"))
    c = storage.get_or_create_chat(5)
    player = storage.add_player(5, 1, "Вася", None, 0, 0)  # вчера играли — сводка есть о чём
    storage.add_matches(player.id, [{"match_id": 1, "start_time": int(time.time()) - 3600, "player_slot": 0,
                                     "radiant_win": True, "lobby_type": 7}])
    bot = _FailingBot(exc)
    asyncio.run(sched.send_digest(bot, storage, None, c, "2026-09-29"))
    return storage.get_or_create_chat(5).last_digest_date


def test_digest_forbidden_marks_day_done(tmp_path, monkeypatch):
    exc = TelegramForbiddenError(method=SendMessage(chat_id=5, text="x"), message="bot was kicked")
    assert _run_digest(tmp_path, monkeypatch, exc) == "2026-09-29"


def test_digest_chat_not_found_marks_day_done(tmp_path, monkeypatch):
    exc = TelegramBadRequest(method=SendMessage(chat_id=5, text="x"), message="chat not found")
    assert _run_digest(tmp_path, monkeypatch, exc) == "2026-09-29"


def test_digest_other_error_is_retried_next_hour(tmp_path, monkeypatch):
    assert _run_digest(tmp_path, monkeypatch, RuntimeError("boom")) is None


# --- A2: фоновые задачи не ходят в сеть, пока провайдер лежит ---------------------------

class _Provider:
    """Фейковый клиент с предохранителем (health) и счётчиком обращений."""

    def __init__(self, down=False):
        from mmrbot.health import ProviderHealth
        self.health = ProviderHealth("OpenDota")
        if down:
            self.health.failure(RuntimeError("down"))
        self.api_key = "K"
        self.calls = []

    def get_heroes(self):
        self.calls.append("get_heroes")
        return []


def _jobs(tmp_path, od, stratz=None):
    storage = Storage(str(tmp_path / "t.db"))
    scheduler = sched.setup_scheduler(None, storage, od, stratz=stratz)
    return scheduler, {job.func.__name__: job.func for job in scheduler.get_jobs()}


def test_heroes_refresh_reschedules_itself_in_an_hour_when_opendota_is_down(tmp_path):
    od = _Provider(down=True)
    scheduler, jobs = _jobs(tmp_path, od)
    asyncio.run(jobs["heroes_refresh"]())
    assert od.calls == []                                           # в сеть не ходили
    retry = next(j for j in scheduler.get_jobs() if j.id == "heroes_retry")
    delta = (retry.trigger.run_date - datetime.now(timezone.utc)).total_seconds()
    assert 3500 < delta <= 3600                                      # перенос на +1 ч


def test_heroes_refresh_retry_does_not_pile_up(tmp_path):
    od = _Provider(down=True)
    scheduler, jobs = _jobs(tmp_path, od)
    for _ in range(3):
        asyncio.run(jobs["heroes_refresh"]())
    assert [j.id for j in scheduler.get_jobs()].count("heroes_retry") == 1


def test_background_jobs_skip_the_tick_when_provider_is_down(tmp_path, monkeypatch):
    called = []
    for name in ("backfill_opendota", "backfill_stratz", "detect_steam_changes"):
        monkeypatch.setattr(sched, name, lambda *a, _n=name, **kw: called.append(_n) or [])
    _, jobs = _jobs(tmp_path, _Provider(down=True), stratz=_Provider(down=True))
    for name in ("opendota_backfill", "stratz_backfill", "steam_watch"):
        asyncio.run(jobs[name]())          # тик тихо пропущен, без исключений
    assert called == []                    # и без обращений к задачам, которые ходят в сеть


def test_background_jobs_run_when_provider_is_up(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(sched, "backfill_opendota", lambda storage, od: called.append("od") or 0)
    monkeypatch.setattr(sched, "backfill_stratz", lambda storage, st: called.append("stratz") or 0)
    _, jobs = _jobs(tmp_path, _Provider(), stratz=_Provider())
    asyncio.run(jobs["opendota_backfill"]())
    asyncio.run(jobs["stratz_backfill"]())
    assert called == ["od", "stratz"]


def test_heroes_refresh_network_failure_is_one_warning_and_retried_in_an_hour(tmp_path, caplog):
    import logging

    import requests

    class Flaky(_Provider):
        def get_heroes(self):
            raise requests.exceptions.ConnectTimeout("boom")

    scheduler, jobs = _jobs(tmp_path, Flaky())
    with caplog.at_level(logging.DEBUG, logger="mmrbot.scheduler"):
        asyncio.run(jobs["heroes_refresh"]())
    records = [r for r in caplog.records if r.name == "mmrbot.scheduler"]
    assert [r.levelno for r in records] == [logging.WARNING]
    assert records[0].exc_info is None and "Traceback" not in caplog.text
    assert any(j.id == "heroes_retry" for j in scheduler.get_jobs())


def test_background_job_unexpected_error_keeps_traceback(tmp_path, monkeypatch, caplog):
    import logging

    def bug(*a, **kw):
        raise KeyError("bug")

    monkeypatch.setattr(sched, "backfill_opendota", bug)
    _, jobs = _jobs(tmp_path, _Provider())
    with caplog.at_level(logging.DEBUG, logger="mmrbot.scheduler"):
        asyncio.run(jobs["opendota_backfill"]())
    record = next(r for r in caplog.records if r.name == "mmrbot.scheduler")
    assert record.levelno == logging.ERROR and record.exc_info is not None


def test_background_job_network_error_has_no_traceback(tmp_path, monkeypatch, caplog):
    import logging

    import requests

    def down(*a, **kw):
        raise requests.exceptions.ConnectTimeout("boom")

    monkeypatch.setattr(sched, "backfill_opendota", down)
    _, jobs = _jobs(tmp_path, _Provider())
    with caplog.at_level(logging.DEBUG, logger="mmrbot.scheduler"):
        asyncio.run(jobs["opendota_backfill"]())
    records = [r for r in caplog.records if r.name == "mmrbot.scheduler"]
    assert [r.levelno for r in records] == [logging.WARNING] and records[0].exc_info is None
