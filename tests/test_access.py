"""Права и жизненный цикл чата: админ-проверка, белый список, уход бота, миграция в супергруппу."""
import asyncio
import sqlite3
import time
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramMigrateToChat
from aiogram.filters import CommandObject
from aiogram.methods import SendMessage

import mmrbot.access as access
import mmrbot.bot as botmod
import mmrbot.scheduler as sched
from mmrbot.boards import ImageBoard
from mmrbot.access import DENIED, ChatGateMiddleware, is_chat_admin
from mmrbot.config import _chat_ids
from mmrbot.ids import parse_account_id
from mmrbot.lifecycle import on_migrate, on_my_chat_member
from mmrbot.storage import SCHEMA_VERSION, Storage

GROUP = SimpleNamespace(id=-100, type="supergroup")
PRIVATE = SimpleNamespace(id=7, type="private")


class Bot:
    def __init__(self, admins=(1,), fail=False):
        self.admins, self.fail, self.asked = set(admins), fail, 0

    async def get_chat_member(self, chat_id, user_id):
        self.asked += 1
        if self.fail:
            raise TelegramBadRequest(method=None, message="Bad Request: user not found")
        return SimpleNamespace(status="administrator" if user_id in self.admins else "member")


class Msg:
    def __init__(self, chat=GROUP, user_id=2, bot=None, text="/x"):
        self.chat, self.bot, self.text = chat, bot, text
        self.from_user = SimpleNamespace(id=user_id, is_bot=False)
        self.sender_chat = None
        self.sent = []

    async def answer(self, text, **kw):
        self.sent.append(text)
        return self

    async def edit_text(self, text, **kw):
        self.sent.append(text)

    async def delete(self):
        pass


class CB:
    def __init__(self, data, user_id, bot, chat=GROUP):
        self.data, self.bot = data, bot
        self.message = Msg(chat, bot=bot)
        self.from_user = SimpleNamespace(id=user_id, is_bot=False)

    async def answer(self, *a, **k):
        pass


@pytest.fixture(autouse=True)
def _fresh_admin_cache():
    access._admin_cache.clear()


@pytest.fixture
def store(tmp_path):
    return Storage(str(tmp_path / "a.db"))


def run(coro):
    return asyncio.run(coro)


# --- проверка админа -----------------------------------------------------

def test_admin_check_private_anonymous_and_cache():
    bot = Bot(admins={1})
    assert run(is_chat_admin(bot, PRIVATE, SimpleNamespace(id=5)))  # в личке хозяин — сам пользователь
    assert run(is_chat_admin(bot, GROUP, SimpleNamespace(id=1)))
    assert not run(is_chat_admin(bot, GROUP, SimpleNamespace(id=2)))
    assert run(is_chat_admin(bot, GROUP, SimpleNamespace(id=99), sender_chat=GROUP))  # анонимный админ
    asked = bot.asked
    run(is_chat_admin(bot, GROUP, SimpleNamespace(id=1)))
    assert bot.asked == asked  # повтор — из кэша


def test_admin_check_fails_closed_when_telegram_does_not_answer():
    assert not run(is_chat_admin(Bot(fail=True), GROUP, SimpleNamespace(id=1)))
    assert not run(is_chat_admin(None, GROUP, SimpleNamespace(id=1)))


# --- настройки и удаление в группе ---------------------------------------

def test_non_admin_cannot_change_settings_but_admin_can(store):
    bot = Bot(admins={1})
    denied = CB("s:step:50", 2, bot)
    run(botmod.on_callback(denied, store, object()))
    assert store.get_or_create_chat(-100).mmr_step == 25 and DENIED in denied.message.sent
    run(botmod.on_callback(CB("s:step:50", 1, bot), store, object()))
    assert store.get_or_create_chat(-100).mmr_step == 50


def test_setstep_command_requires_admin_in_group(store):
    msg = Msg(user_id=2, bot=Bot(admins={1}))
    run(botmod.cmd_setstep(msg, CommandObject(command="setstep", args="30"), store))
    assert store.get_or_create_chat(-100).mmr_step == 25 and msg.sent == [DENIED]


def test_chat_can_open_management_to_everyone(store):
    store.set_chat_admin_only(-100, False)
    run(botmod.on_callback(CB("s:step:50", 2, Bot(admins={1})), store, object()))
    assert store.get_or_create_chat(-100).mmr_step == 50


def test_remove_needs_confirmation_and_admin_or_self(store):
    vasya = store.add_player(-100, 42, "Вася", None, 0, 0)
    store.add_player(-100, 43, "Петя", None, 0, 0)
    store.link_user(-100, vasya.id, 2)
    bot = Bot(admins={1})

    msg = Msg(user_id=3, bot=bot)
    run(botmod.cmd_remove(msg, CommandObject(command="remove", args="Вася"), store))
    assert "Удалить игрока Вася?" in msg.sent[0] and store.get_player(-100, "Вася")  # команда ничего не стирает

    stranger = CB("pp:rmyes:43", 3, bot)
    run(botmod.on_callback(stranger, store, object()))
    assert store.get_player(-100, "Петя") is not None and DENIED in stranger.message.sent

    run(botmod.on_callback(CB("pp:rmyes:42", 2, bot), store, object()))  # сам себя — можно
    assert store.get_player(-100, "Вася") is None
    run(botmod.on_callback(CB("pp:rmyes:43", 1, bot), store, object()))  # админ — можно
    assert store.get_player(-100, "Петя") is None


# --- /add: предел игроков и мусор на входе --------------------------------

def test_add_respects_player_limit(store):
    store.max_players = 1
    store.add_player(7, 42, "Вася", None, 0, 0)
    msg = Msg(PRIVATE)
    run(botmod.do_add(msg, store, object(), "123456 Петя"))
    assert "предел" in msg.sent[0] and store.count_players(7) == 1


@pytest.mark.parametrize("bad", ["9" * 30, "0", str(76561197960265728 + 2**32 + 5)])
def test_impossible_account_ids_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_account_id(bad)


def test_add_with_garbage_id_and_long_name_answers_instead_of_crashing(store):
    for args in ("9" * 30, "123456 " + "Я" * 200):
        msg = Msg(PRIVATE)
        run(botmod.do_add(msg, store, object(), args))
        assert msg.sent and msg.sent[0].startswith("⚠️")
    assert store.count_players(7) == 0


def test_unknown_hero_reply_is_html_safe(store):
    from mmrbot.service import render_hero_board
    text = run(render_hero_board(store, None, 7, "<3 pudge", "all"))
    assert "&lt;3 pudge" in text and "<3" not in text


# --- белый список чатов ---------------------------------------------------

def test_allowed_chats_parsing():
    assert _chat_ids("-100123, 456;7") == frozenset({-100123, 456, 7})
    assert _chat_ids("") == frozenset()
    with pytest.raises(RuntimeError):
        _chat_ids("-100123, мой_чат")


def test_gate_blocks_foreign_chats_and_passes_own(store):
    gate = ChatGateMiddleware({-100}, store)
    seen = []

    async def handler(event, data):
        seen.append(event.chat.id)

    foreign_group = Msg(SimpleNamespace(id=-200, type="group"))
    foreign_private = Msg(PRIVATE)
    own = Msg(GROUP)
    for event in (foreign_group, foreign_private, own):
        run(gate(handler, event, {}))
    assert seen == [-100]
    assert foreign_group.sent == [] and foreign_private.sent == [access.NOT_ALLOWED]


def test_gate_without_list_is_open_and_wakes_paused_chat(store):
    store.get_or_create_chat(-100)
    store.set_chat_active(-100, False)
    gate = ChatGateMiddleware(frozenset(), store)

    async def handler(event, data):
        return "ok"

    assert run(gate(handler, Msg(GROUP), {})) == "ok"
    assert store.get_or_create_chat(-100).active


# --- бот ушёл из чата / чат переехал --------------------------------------

def _member_event(status, chat_id=-100):
    return SimpleNamespace(chat=SimpleNamespace(id=chat_id), new_chat_member=SimpleNamespace(status=status))


def test_kicked_bot_pauses_chat_and_keeps_data(store):
    store.add_player(-100, 42, "Вася", None, 0, 0)
    store.get_or_create_chat(-100)
    run(on_my_chat_member(_member_event("kicked"), store))
    assert store.list_chats() == [] and [c.chat_id for c in store.list_chats(include_inactive=True)] == [-100]
    assert store.get_player(-100, "Вася") is not None  # вернут бота — история на месте
    run(on_my_chat_member(_member_event("member"), store))
    assert [c.chat_id for c in store.list_chats()] == [-100]


def test_paused_chat_is_not_polled(store):
    from mmrbot.tracker import backfill_opendota, detect_steam_changes
    store.get_or_create_chat(-100)
    store.add_player(-100, 42, "Вася", None, 0, 0)
    store.set_chat_active(-100, False)

    class Client:
        def __getattr__(self, name):
            raise AssertionError(f"запрос {name} в приостановленный чат")

    assert backfill_opendota(store, Client()) == 0
    assert detect_steam_changes(store, Client()) == []


def test_supergroup_migration_moves_players_and_settings(store):
    store.get_or_create_chat(-5)
    store.set_chat_step(-5, 30)
    player = store.add_player(-5, 42, "Вася", 5000, 0, 0)
    store.add_matches(player.id, [{"match_id": 1, "start_time": 10, "player_slot": 0, "radiant_win": True}])
    store.get_or_create_chat(-1005)  # под новым id уже успели что-то нажать
    message = SimpleNamespace(chat=SimpleNamespace(id=-5), migrate_to_chat_id=-1005)
    run(on_migrate(message, store))
    assert store.list_players(-5) == []
    moved = store.get_player(-1005, "Вася")
    assert moved.id == player.id and len(store.get_matches(moved.id)) == 1
    assert store.get_or_create_chat(-1005).mmr_step == 30
    assert [c.chat_id for c in store.list_chats(include_inactive=True)] == [-1005]
    assert store.migrate_chat(-5, -1005) is False  # повторное событие ничего не ломает


def test_send_errors_pause_or_migrate_chat(store):
    store.get_or_create_chat(-5)
    store.add_player(-5, 42, "Вася", None, 0, 0)
    method = SendMessage(chat_id=-5, text="x")
    assert not sched.chat_gone(store, -5, RuntimeError("сеть"))
    assert sched.chat_gone(store, -5, TelegramMigrateToChat(method=method, message="m", migrate_to_chat_id=-1005))
    assert store.get_player(-1005, "Вася") is not None
    assert sched.chat_gone(store, -1005, TelegramForbiddenError(method=method, message="bot was kicked"))
    assert store.list_chats() == []


# --- ежедневная сводка ----------------------------------------------------

class SendBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(chat_id)


def _digest(store, monkeypatch, played_ago=None):
    async def board(*a, **kw):
        return ImageBoard("доска")

    async def refreshed(*a, **kw):
        return None

    monkeypatch.setattr(sched, "stats_board", board)
    monkeypatch.setattr(sched, "refresh_only", refreshed)
    chat = store.get_or_create_chat(5)
    player = store.add_player(5, 1, "Вася", None, 0, 0)
    if played_ago is not None:
        store.add_matches(player.id, [{"match_id": 1, "start_time": int(time.time()) - played_ago, "player_slot": 0,
                                       "radiant_win": True, "lobby_type": 7}])
    bot = SendBot()
    run(sched.send_digest(bot, store, None, chat, "2026-10-07"))
    return bot.sent, store.get_or_create_chat(5).last_digest_date


def test_digest_is_sent_after_a_day_with_games(store, monkeypatch):
    assert _digest(store, monkeypatch, played_ago=3600) == ([5], "2026-10-07")


def test_digest_is_skipped_when_nobody_played(store, monkeypatch):
    assert _digest(store, monkeypatch, played_ago=3 * 86_400) == ([], "2026-10-07")  # день закрыт, чат не тревожим


def test_digest_toggle_in_settings(store):
    run(botmod.on_callback(CB("s:digest", 1, Bot(admins={1})), store, object()))
    assert store.get_or_create_chat(-100).notify_digest is False


# --- схема -----------------------------------------------------------------

def test_schema_version_is_stamped_and_newer_db_is_refused(tmp_path):
    path = str(tmp_path / "v.db")
    Storage(path)
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError):
        Storage(path)


def test_old_database_gets_new_chat_columns(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE chats (chat_id INTEGER PRIMARY KEY, digest_hour INTEGER NOT NULL DEFAULT 10, "
                 "mmr_step INTEGER NOT NULL DEFAULT 25, tz TEXT NOT NULL DEFAULT 'Europe/Moscow')")
    conn.execute("INSERT INTO chats (chat_id) VALUES (100)")
    conn.commit()
    conn.close()
    chat = Storage(path).get_or_create_chat(100)
    assert chat.active and chat.notify_digest and chat.admin_only


def test_new_chat_defaults_come_from_config(tmp_path):
    store = Storage(str(tmp_path / "d.db"), default_digest_hour=21, default_mmr_step=30, default_tz="Asia/Almaty")
    chat = store.get_or_create_chat(1)
    assert (chat.digest_hour, chat.mmr_step, chat.tz) == (21, 30, "Asia/Almaty")
