"""A8: повтор отправки в Telegram при лимите и сетевых сбоях; сводки не теряются до следующего дня."""
import asyncio

import pytest
from aiogram.exceptions import (
    TelegramBadRequest, TelegramForbiddenError, TelegramMigrateToChat, TelegramNetworkError, TelegramRetryAfter,
    TelegramServerError,
)

from mmrbot import scheduler as sched
from mmrbot.boards import ImageBoard
from mmrbot.delivery import send_with_retry
from mmrbot.storage import Storage


def run(coro):
    return asyncio.run(coro)


class Flaky:
    """Вызываемый объект: первые n раз кидает исключения из списка, потом возвращает «ok»."""

    def __init__(self, *errors):
        self.errors, self.calls = list(errors), 0

    async def __call__(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


async def _no_sleep(_):
    return None


def _retry_after(seconds):
    return TelegramRetryAfter(method=None, message="Flood", retry_after=seconds)


def test_success_is_not_retried():
    call = Flaky()
    assert run(send_with_retry(call, sleep=_no_sleep)) == "ok" and call.calls == 1


def test_retry_after_waits_the_requested_time_then_succeeds():
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    call = Flaky(_retry_after(7))
    assert run(send_with_retry(call, sleep=sleep)) == "ok" and call.calls == 2
    assert 7 <= waits[0] < 9


@pytest.mark.parametrize("error", [TelegramNetworkError(method=None, message="net"),
                                   TelegramServerError(method=None, message="502"), asyncio.TimeoutError()])
def test_network_and_server_errors_are_retried(error):
    call = Flaky(error)
    assert run(send_with_retry(call, sleep=_no_sleep)) == "ok" and call.calls == 2


@pytest.mark.parametrize("error", [TelegramForbiddenError(method=None, message="kicked"),
                                   TelegramBadRequest(method=None, message="chat not found"),
                                   TelegramMigrateToChat(method=None, message="moved", migrate_to_chat_id=-100)])
def test_chat_errors_are_not_retried(error):
    call = Flaky(error)
    with pytest.raises(type(error)):
        run(send_with_retry(call, sleep=_no_sleep))
    assert call.calls == 1


def test_persistent_failure_gives_up_after_attempts():
    call = Flaky(*[TelegramNetworkError(method=None, message="net")] * 5)
    with pytest.raises(TelegramNetworkError):
        run(send_with_retry(call, attempts=3, sleep=_no_sleep))
    assert call.calls == 3


def test_too_long_retry_after_is_not_awaited():
    call = Flaky(_retry_after(3600))
    with pytest.raises(TelegramRetryAfter):
        run(send_with_retry(call, sleep=_no_sleep))
    assert call.calls == 1  # час ждать не будем — задача повторится в следующем тике


# --- сводки: дата ставится только после доставки ----------------------------------------------------

class ScriptedBot:
    def __init__(self, *errors):
        self.errors, self.sent = list(errors), []

    async def send_message(self, chat_id, text, **kw):
        if self.errors:
            raise self.errors.pop(0)
        self.sent.append(text)

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        if self.errors:
            raise self.errors.pop(0)
        self.sent.append(caption)


@pytest.fixture
def digest_env(tmp_path, monkeypatch):
    import time

    async def board(*a, **k):
        return ImageBoard("сводка")

    async def refreshed(*a, **k):
        return None

    async def no_sleep(_):
        return None

    monkeypatch.setattr(sched, "stats_board", board)
    monkeypatch.setattr(sched, "refresh_only", refreshed)
    monkeypatch.setattr("mmrbot.delivery.asyncio.sleep", no_sleep)
    storage = Storage(str(tmp_path / "t.db"))
    chat = storage.get_or_create_chat(5)
    player = storage.add_player(5, 1, "Вася", None, 0, 0)
    storage.add_matches(player.id, [{"match_id": 1, "start_time": int(time.time()) - 600, "player_slot": 0,
                                     "radiant_win": True, "lobby_type": 7}])
    return storage, chat


def test_digest_survives_one_flood_wait(digest_env):
    storage, chat = digest_env
    bot = ScriptedBot(_retry_after(1))
    run(sched.send_digest(bot, storage, None, chat, "2026-10-07"))
    assert bot.sent == ["сводка"] and storage.get_or_create_chat(5).last_digest_date == "2026-10-07"


def test_digest_with_persistent_failure_keeps_date_unset_and_does_not_raise(digest_env):
    storage, chat = digest_env
    bot = ScriptedBot(*[TelegramNetworkError(method=None, message="net")] * 10)
    run(sched.send_digest(bot, storage, None, chat, "2026-10-07"))
    assert bot.sent == [] and storage.get_or_create_chat(5).last_digest_date is None  # завтра/через час — снова


def test_weekly_summary_survives_one_flood_wait(digest_env, monkeypatch):
    storage, _ = digest_env

    async def weekly(*a, **k):
        return ImageBoard("итоги недели")

    monkeypatch.setattr(sched, "weekly_board", weekly)
    monkeypatch.setattr(sched, "due_weekly_key", lambda c, now: "2026-W41")
    bot = ScriptedBot(_retry_after(1))
    jobs = {j.func.__name__: j.func for j in sched.setup_scheduler(bot, storage, None).get_jobs()}
    run(jobs["weekly_summary"]())
    assert bot.sent == ["итоги недели"] and storage.get_or_create_chat(5).last_weekly == "2026-W41"


def test_weekly_summary_with_persistent_failure_is_retried_later(digest_env, monkeypatch):
    storage, _ = digest_env

    async def weekly(*a, **k):
        return ImageBoard("итоги недели")

    monkeypatch.setattr(sched, "weekly_board", weekly)
    monkeypatch.setattr(sched, "due_weekly_key", lambda c, now: "2026-W41")
    bot = ScriptedBot(*[TelegramServerError(method=None, message="502")] * 10)
    jobs = {j.func.__name__: j.func for j in sched.setup_scheduler(bot, storage, None).get_jobs()}
    run(jobs["weekly_summary"]())
    assert storage.get_or_create_chat(5).last_weekly is None
