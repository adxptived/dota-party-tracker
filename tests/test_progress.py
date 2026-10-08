import asyncio

from mmrbot.progress import DeferredStatus


class Recorder:
    def __init__(self, fail_action=False):
        self.actions = 0
        self.texts = 0
        self.deleted = 0
        self.fail_action = fail_action

    async def action(self):
        self.actions += 1
        if self.fail_action:
            raise RuntimeError("нет прав на sendChatAction")

    async def send(self):
        self.texts += 1
        rec = self

        class Sent:
            async def delete(self_inner):
                rec.deleted += 1

        return Sent()


def _status(rec, **kw):
    return DeferredStatus(rec.action, rec.send, action_after=0.03, text_after=0.12, **kw)


def test_fast_answer_sends_neither_action_nor_status():
    rec = Recorder()

    async def go():
        status = _status(rec)
        await asyncio.sleep(0.01)
        await status.delete()
        await asyncio.sleep(0.2)  # отменённое не оживает

    asyncio.run(go())
    assert (rec.actions, rec.texts, rec.deleted) == (0, 0, 0)


def test_medium_answer_shows_only_chat_action():
    rec = Recorder()

    async def go():
        status = _status(rec)
        await asyncio.sleep(0.07)
        await status.delete()
        await asyncio.sleep(0.2)

    asyncio.run(go())
    assert (rec.actions, rec.texts, rec.deleted) == (1, 0, 0)


def test_slow_answer_sends_status_and_delete_removes_it():
    rec = Recorder()

    async def go():
        status = _status(rec)
        await asyncio.sleep(0.2)
        await status.delete()

    asyncio.run(go())
    assert (rec.actions, rec.texts, rec.deleted) == (1, 1, 1)


def test_in_place_status_is_not_deleted():
    """Кнопка: «Считаю…» — это правка самого сообщения-отчёта, удалять его нельзя."""
    rec = Recorder()

    async def go():
        status = _status(rec, delete_sent=False)
        await asyncio.sleep(0.2)
        await status.delete()

    asyncio.run(go())
    assert (rec.texts, rec.deleted) == (1, 0)


def test_delete_during_sending_waits_for_it_and_cleans_up():
    rec = Recorder()

    async def slow_send():
        await asyncio.sleep(0.1)
        return await rec.send()

    async def go():
        status = DeferredStatus(rec.action, slow_send, action_after=0.0, text_after=0.02)
        await asyncio.sleep(0.05)  # отправка статуса уже идёт
        await status.delete()

    asyncio.run(go())
    assert (rec.texts, rec.deleted) == (1, 1)  # не осталось «зависшего» сообщения


def test_action_failure_is_swallowed_and_status_still_sent():
    rec = Recorder(fail_action=True)

    async def go():
        status = _status(rec)
        await asyncio.sleep(0.2)
        await status.delete()

    asyncio.run(go())
    assert rec.actions == 1 and rec.texts == 1


def test_status_send_failure_is_swallowed():
    async def broken():
        raise RuntimeError("Telegram не принял")

    async def go():
        status = DeferredStatus(Recorder().action, broken, action_after=0.0, text_after=0.01)
        await asyncio.sleep(0.05)
        await status.delete()

    asyncio.run(go())  # не падает


def test_delete_is_idempotent():
    rec = Recorder()

    async def go():
        status = _status(rec)
        await asyncio.sleep(0.2)
        await status.delete()
        await status.delete()

    asyncio.run(go())
    assert rec.deleted == 1


def test_without_text_factory_only_the_action_is_shown():
    actions, texts = [], []

    async def go():
        status = DeferredStatus(lambda: _record(actions, "a"), None, action_after=0.01, text_after=0.03)
        await asyncio.sleep(0.1)
        await status.delete()

    asyncio.run(go())
    assert actions == ["a"] and texts == []


async def _record(bucket, item):
    bucket.append(item)
