"""Оповещение ушло без таймингов покупок — позже картинку обновляем, когда тайминги появились."""
import asyncio

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from mmrbot.boards import ImageBoard
from mmrbot.scheduler import PendingRetime, retime_alerts, send_board
from mmrbot.tracker import alert_untimed


def _event(times):
    return {"match_id": 5, "rows": [{"account_id": 1, "items": [1, 2], "item_times": times}]}


class Bot:
    def __init__(self, fail=None):
        self.edits, self.fail = [], fail

    async def edit_message_media(self, chat_id, message_id, media, reply_markup=None):
        if self.fail:
            raise self.fail
        self.edits.append((chat_id, message_id, media.caption))


def test_alert_untimed():
    assert alert_untimed(_event([None, None])) and alert_untimed(_event(None))
    assert not alert_untimed(_event([300, None]))
    assert not alert_untimed({"rows": [{"account_id": 1}]})  # билда нет вовсе — ждать нечего


def _pending():
    return PendingRetime(chat_id=7, message_id=70, event=_event([None, None]), since=1000, tz="UTC")


def _boards(times_after):
    async def fn(event, tz):
        for row in event["rows"]:
            row["item_times"] = times_after
        return ImageBoard("текст", png=b"\x89PNG", caption="подпись")
    return fn


def test_alert_photo_is_replaced_once_times_arrive():
    bot, pending = Bot(), [_pending()]
    asyncio.run(retime_alerts(bot, pending, _boards([None, None]), now=1100))
    assert bot.edits == [] and len(pending) == 1 and pending[0].tries == 1  # ещё нет — ждём дальше
    asyncio.run(retime_alerts(bot, pending, _boards([300, 600]), now=1200))
    assert bot.edits == [(7, 70, "подпись")] and pending == []


def test_gives_up_when_too_old_or_message_is_gone():
    bot, pending = Bot(), [_pending()]
    asyncio.run(retime_alerts(bot, pending, _boards([300, 600]), now=1000 + 10 ** 5))
    assert bot.edits == [] and pending == []  # старое не трогаем

    error = TelegramBadRequest(method=SendMessage(chat_id=1, text="x"),
                               message="message to edit not found")
    pending = [_pending()]
    asyncio.run(retime_alerts(Bot(fail=error), pending, _boards([300, 600]), now=1100))
    assert pending == []


def test_gives_up_after_max_tries():
    pending = [_pending()]
    for i in range(20):
        asyncio.run(retime_alerts(Bot(), pending, _boards([None, None]), now=1100 + i))
    assert pending == []


def test_send_board_returns_the_sent_photo_message():
    class Msg:
        message_id = 5

    class B:
        async def send_photo(self, *a, **k):
            return Msg()

    assert asyncio.run(send_board(B(), 1, ImageBoard("t", png=b"x", caption="c"))).message_id == 5


def test_background_allowed_follows_the_client_budget():
    from mmrbot.tracker import background_allowed

    class Low:
        def background_allowed(self):
            return False

    assert background_allowed(Low()) is False and background_allowed(object()) is True
