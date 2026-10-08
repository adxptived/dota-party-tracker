import asyncio
from datetime import datetime, timezone

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import SendMessage

from mmrbot import scheduler as sched
from mmrbot.boards import ImageBoard
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
        return ImageBoard("доска")

    async def refreshed(*a, **kw):
        return None

    monkeypatch.setattr(sched, "stats_board", fake_board)
    monkeypatch.setattr(sched, "refresh_only", refreshed)
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


# --- C1: оповещение о матче картинкой --------------------------------------------------------

class _AlertBot:
    """Фейковый бот: что и как отправили; photo_exc/text_exc — чем падать."""

    def __init__(self, photo_exc=None, text_exc=None):
        self.photos, self.texts = [], []
        self.photo_exc, self.text_exc = photo_exc, text_exc

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        if self.photo_exc:
            raise self.photo_exc
        assert photo.data[:8] == b"\x89PNG\r\n\x1a\n"
        self.photos.append((chat_id, caption, kw))

    async def send_message(self, chat_id, text, **kw):
        if self.text_exc:
            raise self.text_exc
        self.texts.append((chat_id, text, kw))


def _alert_event(match_id=777):
    return {"kind": "match", "chat_id": 5, "match_id": match_id, "start_time": 1_700_000_000, "duration": 2280,
            "rows": [{"name": "Вася", "account_id": 1, "avatar": None, "hero_id": 12, "kills": 5, "deaths": 2,
                      "assists": 9, "won": True, "step": 25, "current_mmr": 5000, "streak_type": "W",
                      "streak_len": 1}],
            "shared": None, "average_rank": None, "pending": [(1, match_id)]}


def _run_game_watch(tmp_path, monkeypatch, bot, event=None):
    storage = Storage(str(tmp_path / "g.db"))
    storage.get_or_create_chat(5)
    storage.add_player(5, 1, "Вася", None, 0, 0)
    marked = []
    monkeypatch.setattr(sched, "detect_new_games", lambda *a, **kw: [event or _alert_event()])
    monkeypatch.setattr(storage, "mark_notified_matches", lambda pending: marked.append(list(pending)))
    scheduler = sched.setup_scheduler(bot, storage, _Provider())
    jobs = {job.func.__name__: job.func for job in scheduler.get_jobs()}
    asyncio.run(jobs["game_watch"]())
    return marked


def test_match_alert_goes_as_photo_with_caption_and_buttons(tmp_path, monkeypatch):
    bot = _AlertBot()
    marked = _run_game_watch(tmp_path, monkeypatch, bot)
    (chat_id, caption, kw), = bot.photos
    assert chat_id == 5 and "Матч завершён" in caption and "Вася" in caption and kw["parse_mode"] == "HTML"
    data = [b.callback_data for row in kw["reply_markup"].inline_keyboard for b in row]
    assert "mx:777" in data
    assert not bot.texts and marked == [[(1, 777)]]  # помечено оповещённым после успешной отправки


def test_match_alert_falls_back_to_text_when_telegram_rejects_photo(tmp_path, monkeypatch):
    exc = TelegramBadRequest(method=SendMessage(chat_id=5, text="x"), message="PHOTO_INVALID_DIMENSIONS")
    bot = _AlertBot(photo_exc=exc)
    marked = _run_game_watch(tmp_path, monkeypatch, bot)
    assert not bot.photos and len(bot.texts) == 1 and "Матч завершён" in bot.texts[0][1]
    assert marked == [[(1, 777)]]


def test_match_alert_falls_back_to_text_when_render_fails(tmp_path, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("нет шрифта")

    monkeypatch.setattr("mmrbot.service.render_alert_image", boom)
    bot = _AlertBot()
    marked = _run_game_watch(tmp_path, monkeypatch, bot)
    assert not bot.photos and len(bot.texts) == 1 and marked == [[(1, 777)]]


def test_alert_stays_pending_when_telegram_is_down(tmp_path, monkeypatch):
    bot = _AlertBot(photo_exc=RuntimeError("сеть"))
    marked = _run_game_watch(tmp_path, monkeypatch, bot)
    assert marked == []  # не отправлено — уйдёт в следующем опросе


# --- недельная сводка и дайджест уходят картинкой ----------------------------------------------

class _PhotoBot:
    def __init__(self):
        self.photos, self.messages = [], []

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        assert photo.data[:8] == b"\x89PNG\r\n\x1a\n"
        self.photos.append((chat_id, caption))

    async def send_message(self, chat_id, text, **kw):
        self.messages.append((chat_id, text))


def _played_chat(tmp_path):
    import time
    storage = Storage(str(tmp_path / "w.db"))
    chat = storage.get_or_create_chat(5)
    player = storage.add_player(5, 1, "Вася", 5000, 0, 0)
    now = int(time.time())
    storage.add_matches(player.id, [{"match_id": i, "start_time": now - 3600 * i, "player_slot": 0, "radiant_win": i != 2,
                                     "lobby_type": 7, "hero_id": 1, "kills": 5, "deaths": 2, "assists": 7}
                                    for i in range(1, 5)])
    return storage, chat


def test_weekly_summary_job_sends_card_photo(tmp_path, monkeypatch):
    storage, chat = _played_chat(tmp_path)
    monkeypatch.setattr(sched, "due_weekly_key", lambda c, now: "2026-W41")
    bot = _PhotoBot()
    jobs = {j.func.__name__: j.func for j in sched.setup_scheduler(bot, storage, None).get_jobs()}
    asyncio.run(jobs["weekly_summary"]())
    assert bot.photos and "Итоги недели" in bot.photos[0][1] and not bot.messages
    assert storage.get_or_create_chat(5).last_weekly == "2026-W41"


def test_digest_sends_card_photo_and_idle_day_skips_rendering(tmp_path, monkeypatch):
    storage, chat = _played_chat(tmp_path)

    async def refreshed(*a, **kw):
        return None

    monkeypatch.setattr(sched, "refresh_only", refreshed)
    bot = _PhotoBot()
    asyncio.run(sched.send_digest(bot, storage, _Provider(down=True), chat, "2026-10-07"))
    assert bot.photos and "Ежедневная сводка" in bot.photos[0][1]

    async def forbidden(*a, **kw):
        raise AssertionError("в тихий день картинку не рисуем")

    idle_storage = Storage(str(tmp_path / "idle.db"))
    idle_chat = idle_storage.get_or_create_chat(6)
    idle_storage.add_player(6, 2, "Петя", None, 0, 0)
    monkeypatch.setattr(sched, "stats_board", forbidden)
    asyncio.run(sched.send_digest(_PhotoBot(), idle_storage, _Provider(down=True), idle_chat, "2026-10-07"))
    assert idle_storage.get_or_create_chat(6).last_digest_date == "2026-10-07"


# --- B4: прогрев после новых игр -------------------------------------------------------------------

def test_game_watch_warms_chat_after_delivered_match(tmp_path, monkeypatch):
    warmed = []

    async def spy(storage, od, chat_id, stratz=None, **kw):
        warmed.append(chat_id)

    monkeypatch.setattr(sched, "warm_chat", spy)
    _run_game_watch(tmp_path, monkeypatch, _AlertBot())
    assert warmed == [5]


def test_game_watch_does_not_warm_when_nothing_delivered(tmp_path, monkeypatch):
    warmed = []

    async def spy(*a, **kw):
        warmed.append(1)

    monkeypatch.setattr(sched, "warm_chat", spy)
    _run_game_watch(tmp_path, monkeypatch, _AlertBot(photo_exc=RuntimeError("сеть")))
    assert warmed == []


def test_warm_chat_swallows_errors(tmp_path, monkeypatch):
    import mmrbot.service as service

    async def boom(*a, **kw):
        raise RuntimeError("упало")

    monkeypatch.setattr(service, "stats_board", boom)
    asyncio.run(service.warm_chat(Storage(str(tmp_path / "w.db")), _Provider(), 5))  # не бросает


def test_contest_leader_change_is_announced_after_new_games(tmp_path, monkeypatch):
    import time
    bot = _AlertBot()
    storage = Storage(str(tmp_path / "c.db"))
    storage.get_or_create_chat(5)
    a, b = storage.add_player(5, 1, "Вася", None, 0, 0), storage.add_player(5, 2, "Петя", None, 0, 0)
    now = int(time.time())

    def games(player, base, gpm, start):
        storage.add_matches(player.id, [{"match_id": base + i, "start_time": start - 3600 * i, "player_slot": 0,
                                         "radiant_win": True, "lobby_type": 7, "kills": 5, "deaths": 3, "assists": 7,
                                         "hero_id": 1, "duration": 2400, "gpm": gpm} for i in range(1, 4)])
    games(a, 100, 700, now)
    games(b, 200, 400, now)
    monkeypatch.setattr(sched, "detect_new_games", lambda *a, **kw: [_alert_event()])
    monkeypatch.setattr(storage, "mark_notified_matches", lambda pending: None)
    scheduler = sched.setup_scheduler(bot, storage, _Provider())
    jobs = {job.func.__name__: job.func for job in scheduler.get_jobs()}
    asyncio.run(jobs["game_watch"]())                       # первый проход: лидеры только запоминаются
    assert not any("Смена лидера" in t for _, t, *_ in bot.texts)
    games(b, 300, 1500, now - 10)                           # Петя перехватил GPM
    asyncio.run(jobs["game_watch"]())
    assert any("Смена лидера" in t and "Петя" in t and "Вася" in t for _, t, *_ in bot.texts)
