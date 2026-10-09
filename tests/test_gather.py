"""Сбор пати: /go с кнопками «иду / через 15 минут / пас», упоминания привязанных игроков, срок жизни."""
import asyncio
import sqlite3

import pytest
from aiogram.filters import CommandObject

from mmrbot import gather
from mmrbot.storage import Storage

T0 = 1_780_000_000
HOUR = 3600


@pytest.fixture
def store(tmp_path):
    storage = Storage(str(tmp_path / "g.db"))
    storage.get_or_create_chat(1)
    return storage


# --- хранилище ---------------------------------------------------------------------------

def test_vote_switches_and_repeat_withdraws(store):
    call = store.create_gather(1, T0, 7, "Вася", "в 21:00")
    assert (call.chat_id, call.by_user, call.note, call.closed, call.message_id) == (1, 7, "в 21:00", False, None)
    assert store.vote_gather(call.id, 7, "Вася", "go", T0) == "go"
    assert store.vote_gather(call.id, 8, "Петя", "late", T0 + 1) == "late"
    assert store.vote_gather(call.id, 8, "Петя", "no", T0 + 2) == "no"      # передумал
    assert store.vote_gather(call.id, 7, "Вася", "go", T0 + 3) is None      # тот же ответ повторно — снимает голос
    assert [(v["user_id"], v["choice"]) for v in store.gather_votes(call.id)] == [(8, "no")]


def test_new_call_closes_previous_one_in_chat(store):
    store.get_or_create_chat(2)
    first = store.create_gather(1, T0, 7, "Вася", None)
    store.set_gather_message(first.id, 555)
    other_chat = store.create_gather(2, T0, 7, "Вася", None)
    closed = store.close_gathers(1)
    assert [(g.id, g.message_id) for g in closed] == [(first.id, 555)]
    assert store.get_gather(first.id).closed and not store.get_gather(other_chat.id).closed
    assert store.current_gather(1) is None and store.current_gather(2).id == other_chat.id
    assert store.close_gathers(1) == []  # второй раз закрывать нечего


def test_old_calls_and_votes_are_purged(store):
    old = store.create_gather(1, T0, 7, "Вася", None)
    store.vote_gather(old.id, 7, "Вася", "go", T0)
    store.create_gather(1, T0 + 8 * 86_400, 7, "Вася", None)
    assert store.get_gather(old.id) is None and store.gather_votes(old.id) == []


def test_calls_move_with_group_to_supergroup(store):
    call = store.create_gather(1, T0, 7, "Вася", None)
    assert store.migrate_chat(1, -100500)
    assert store.get_gather(call.id).chat_id == -100500


def test_migration_adds_gather_tables(tmp_path):
    path = str(tmp_path / "bot.db")
    Storage(path)
    with sqlite3.connect(path) as raw:
        tables = {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"gather_calls", "gather_votes"} <= tables


# --- текст ----------------------------------------------------------------------------------

def _call(store, note=None, now=T0):
    return store.create_gather(1, now, 7, "Вася", note)


def test_render_lists_answers_counts_and_waiting_linked_players(store):
    call = _call(store, "в 21:00, ранкед")
    for uid, name, choice in ((7, "Вася", "go"), (8, "Tg Петя", "go"), (9, "Коля", "late"), (10, "Маша", "no")):
        store.vote_gather(call.id, uid, name, choice, T0 + uid)
    linked = {7: "Вася", 8: "Петя", 11: "Саша"}  # 8 назван ником игрока, 11 ещё молчит
    text = gather.render(store.get_gather(call.id), store.gather_votes(call.id), linked, T0 + 60)
    assert "Сбор пати" in text and "Вася" in text and "в 21:00, ранкед" in text
    assert "Собрано 2/5" in text
    assert "✅ Иду (2): Вася, Петя" in text and "Tg Петя" not in text
    assert "⏱ Через 15 мин (1): Коля" in text and "❌ Пас (1): Маша" in text
    assert '<a href="tg://user?id=11">Саша</a>' in text and "Ждём" in text


def test_render_escapes_html_and_hides_empty_sections(store):
    call = store.create_gather(1, T0, 7, "<b>Вася</b>", "<script>")
    store.vote_gather(call.id, 7, "<b>Вася</b>", "go", T0)
    text = gather.render(store.get_gather(call.id), store.gather_votes(call.id), {}, T0)
    assert "<script>" not in text and "&lt;script&gt;" in text and "&lt;b&gt;Вася&lt;/b&gt;" in text
    assert "Через 15" not in text and "Пас" not in text and "Ждём" not in text


def test_party_complete_and_expired_notes(store):
    call = _call(store)
    for uid in range(1, 6):
        store.vote_gather(call.id, uid, f"И{uid}", "go", T0 + uid)
    full = gather.render(store.get_gather(call.id), store.gather_votes(call.id), {}, T0 + 10)
    assert "Пати собрана" in full and "Собрано 5/5" in full
    late = gather.render(store.get_gather(call.id), store.gather_votes(call.id), {}, T0 + gather.TTL + 1)
    assert "Сбор закончился" in late
    assert not gather.is_expired(call, T0 + gather.TTL - 1) and gather.is_expired(call, T0 + gather.TTL)


def test_buttons_carry_call_id_and_fit_telegram_limit(store):
    call = _call(store)
    markup = gather.buttons(call.id)
    data = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert data == [f"go:{call.id}:go", f"go:{call.id}:late", f"go:{call.id}:no"]
    assert all(len(d.encode()) <= 64 for d in data)


# --- команда и кнопки -------------------------------------------------------------------------

class User:
    def __init__(self, uid, name):
        self.id, self.full_name = uid, name


class Sent:
    def __init__(self, message_id):
        self.message_id = message_id


class Message:
    def __init__(self, user=None, chat_type="group", message_id=100):
        self.chat = type("Chat", (), {"id": 1, "type": chat_type})()
        self.from_user = user
        self.message_id = message_id
        self.reply_markup = None
        self.sent, self.edits, self.markups = [], [], []
        self.bot = Bot()

    async def answer(self, text, **kwargs):
        self.sent.append((text, kwargs.get("reply_markup")))
        return Sent(200 + len(self.sent))

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))

    async def edit_reply_markup(self, reply_markup=None):
        self.markups.append(reply_markup)


class Bot:
    def __init__(self):
        self.cleared = []

    async def edit_message_reply_markup(self, chat_id=None, message_id=None, reply_markup=None, **kw):
        self.cleared.append((chat_id, message_id))


class Query:
    def __init__(self, data, message, user):
        self.data, self.message, self.from_user, self.toasts = data, message, user, []

    async def answer(self, text=None, **kwargs):
        self.toasts.append(text)


def run_go(store, user, args=None, **kw):
    message = Message(user, **kw)
    asyncio.run(gather.cmd_go(message, CommandObject(command="go", args=args), store))
    return message


def test_go_posts_call_with_buttons_marks_author_and_mentions_waiting_linked(store):
    vasya = store.add_player(1, 10, "Вася", None, T0, T0)
    petya = store.add_player(1, 20, "Петя", None, T0, T0)
    store.link_user(1, vasya.id, 7)
    store.link_user(1, petya.id, 8)
    message = run_go(store, User(7, "Vasya TG"), "в 21:00")
    text, markup = message.sent[0]
    assert "Сбор пати" in text and "в 21:00" in text and "✅ Иду (1): Вася" in text
    assert '<a href="tg://user?id=8">Петя</a>' in text and 'user?id=7' not in text  # автора не зовём — он уже «иду»
    call = store.current_gather(1)
    assert call.message_id == 201 and call.by_user == 7 and call.note == "в 21:00"
    assert [b.text for row in markup.inline_keyboard for b in row] == ["✅ Иду", "⏱ Через 15 мин", "❌ Пас"]


def test_go_long_note_is_cut_and_second_call_closes_first(store):
    run_go(store, User(7, "Вася"), "я" * 500)
    first = store.current_gather(1)
    assert len(first.note) <= gather.NOTE_LIMIT
    message = run_go(store, User(8, "Петя"))
    assert store.get_gather(first.id).closed and store.current_gather(1).id != first.id
    assert message.bot.cleared == [(1, 201)]  # у прошлого сообщения убрали кнопки


def test_go_needs_a_person_and_works_in_private_chat(store):
    assert "от имени" in run_go(store, None).sent[0][0]
    assert store.current_gather(1) is None
    assert "Сбор пати" in run_go(store, User(7, "Вася"), chat_type="private").sent[0][0]


def press(store, call, user, choice, message=None):
    message = message or Message(user)
    query = Query(f"go:{call.id}:{choice}", message, user)
    asyncio.run(gather.on_button(query, store))
    return query, message


def test_buttons_vote_change_and_withdraw_and_rerender(store):
    run_go(store, User(7, "Вася"))
    call = store.current_gather(1)
    query, message = press(store, call, User(8, "Петя"), "late")
    assert "⏱ Через 15 мин (1): Петя" in message.edits[0][0] and message.edits[0][1] is not None
    press(store, call, User(8, "Петя"), "go", message)
    assert "✅ Иду (2): Вася, Петя" in message.edits[1][0] and "Через 15" not in message.edits[1][0]
    press(store, call, User(8, "Петя"), "go", message)  # повтор — снять голос
    assert "Петя" not in message.edits[2][0]


def test_button_ignores_foreign_chat_closed_and_expired_calls(store):
    run_go(store, User(7, "Вася"))
    call = store.current_gather(1)
    foreign = Message(User(8, "Петя"))
    foreign.chat = type("Chat", (), {"id": 99, "type": "group"})()
    press(store, call, User(8, "Петя"), "go", foreign)
    assert foreign.edits == [] and len(store.gather_votes(call.id)) == 1

    old = store.create_gather(1, 1, 7, "Вася", None)   # создан «в 1970-м» — давно истёк
    query, message = press(store, old, User(8, "Петя"), "go")
    assert "закончился" in message.edits[0][0] and message.edits[0][1] is None  # текст дополнен, кнопок нет
    assert store.get_gather(old.id).closed and store.gather_votes(old.id) == []
    assert not store.get_gather(call.id).closed  # актуальный сбор не задет

    store.close_gathers(1)
    _, message = press(store, call, User(8, "Петя"), "go")
    assert message.markups == [None] and store.gather_votes(call.id)[0]["user_id"] == 7


def test_garbage_callback_data_is_ignored(store):
    message = Message(User(8, "Петя"))
    for data in ("go:", "go:abc:go", "go:1:maybe", "go:99999:go"):
        asyncio.run(gather.on_button(Query(data, message, User(8, "Петя")), store))
    assert message.edits == []
