"""Кнопки меню для команд, у которых их не было: /last, /go, /double, /status."""
import asyncio
from types import SimpleNamespace

import pytest

from mmrbot import bot as botmod
from mmrbot import gather
from mmrbot.keyboards import CATEGORIES, category_menu
from mmrbot.storage import Storage

T0 = 1_780_000_000


class Msg:
    def __init__(self):
        self.chat = SimpleNamespace(id=1, type="supergroup")
        self.sent = []

    async def answer(self, text, **kw):
        self.sent.append(text)

    async def edit_text(self, text, **kw):
        self.sent.append(text)


class Query:
    def __init__(self, data, user_id=7):
        self.data = data
        self.message = Msg()
        self.from_user = SimpleNamespace(id=user_id, full_name="Вася")
        self.bot = object()

    async def answer(self, *a, **k):
        pass


@pytest.fixture
def store(tmp_path):
    storage = Storage(str(tmp_path / "m.db"))
    storage.get_or_create_chat(1)
    vasya = storage.add_player(1, 10, "Вася", None, T0, T0)
    storage.add_player(1, 20, "Петя", None, T0, T0)
    storage.link_user(1, vasya.id, 7)
    return storage


def _press(data, store, **kw):
    q = Query(data, **kw)
    asyncio.run(botmod.on_callback(q, store, object(), None))
    return q


def _actions(key):
    return {b.callback_data for row in category_menu(key).inline_keyboard for b in row}


def test_menu_has_buttons_for_last_go_double_status():
    all_actions = set().union(*(_actions(k) for k in CATEGORIES))
    assert {"m:last", "m:go", "m:double", "m:status"} <= all_actions


def test_last_button_shows_match_of_presser(store, monkeypatch):
    seen = {}

    async def fake(message, storage, od, name, match_id, stratz=None):
        seen["name"] = name

    monkeypatch.setattr(botmod, "do_match", fake)
    _press("m:last", store, user_id=7)
    assert seen["name"] == "Вася"
    _press("m:last", store, user_id=999)          # не привязан — последний матч пати
    assert seen["name"] is None


def test_go_button_starts_gather_from_presser(store):
    q = _press("m:go", store, user_id=7)
    call = store.current_gather(1)
    assert call is not None and call.by_user == 7 and q.message.sent
    assert [(v["user_id"], v["choice"]) for v in store.gather_votes(call.id)] == [(7, "go")]


def test_double_button_asks_player_then_toggles(store):
    q = _press("m:double", store)
    assert q.message.sent and "дабл" in q.message.sent[0].lower()
    q = _press("pp:double:10", store)             # у игрока нет матчей
    assert q.message.sent and "матч" in q.message.sent[0].lower()


def test_status_button_checks_admin(store, monkeypatch):
    calls = []

    async def fake(message, storage, od, stratz, bot, actor):
        calls.append(actor.id)

    monkeypatch.setattr(botmod, "do_status", fake)
    _press("m:status", store, user_id=5)
    assert calls == [5]


def test_start_requires_user(store):
    msg = Msg()
    asyncio.run(gather.start(msg, store, None))
    assert "не анонимного" in msg.sent[0]
