"""Настройка чата «🖼 Отчёты: картинками / текстом» (chats.prefer_text): хранение, кнопка, все отчёты, планировщик."""
import asyncio
import sqlite3

import pytest

from mmrbot import scheduler as sched
from mmrbot import service
from mmrbot.formatting import render_settings
from mmrbot.keyboards import settings_menu
from mmrbot.storage import Storage


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def e2e():
    pytest.importorskip("aiogram.filters")
    from tests import test_e2e_commands as mod
    return mod


# --- хранение и меню ------------------------------------------------------------------------------

def test_prefer_text_defaults_to_images_and_toggles(tmp_path):
    storage = Storage(str(tmp_path / "t.db"))
    assert storage.get_or_create_chat(1).prefer_text is False
    storage.set_chat_prefer_text(1, True)
    assert storage.get_or_create_chat(1).prefer_text is True
    assert storage.get_or_create_chat(2).prefer_text is False  # настройка у каждого чата своя
    storage.set_chat_prefer_text(1, False)
    assert storage.get_or_create_chat(1).prefer_text is False


def test_old_database_gets_prefer_text_column(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE chats (chat_id INTEGER PRIMARY KEY, digest_hour INTEGER NOT NULL DEFAULT 10, "
                 "mmr_step INTEGER NOT NULL DEFAULT 25, tz TEXT NOT NULL DEFAULT 'Europe/Moscow')")
    conn.execute("INSERT INTO chats (chat_id) VALUES (7)")
    conn.commit()
    conn.close()
    storage = Storage(path)
    assert storage.get_or_create_chat(7).prefer_text is False  # миграция добавила колонку, чат остался на картинках
    storage.set_chat_prefer_text(7, True)
    assert Storage(path).get_or_create_chat(7).prefer_text is True


def test_settings_menu_and_text_show_current_mode(tmp_path):
    storage = Storage(str(tmp_path / "t.db"))
    chat = storage.get_or_create_chat(1)
    labels = [b.text for row in settings_menu(chat).inline_keyboard for b in row]
    assert "🖼 Отчёты: картинками" in labels and "Отчёты: <b>картинками</b>" in render_settings(chat)
    storage.set_chat_prefer_text(1, True)
    chat = storage.get_or_create_chat(1)
    assert "🖼 Отчёты: текстом" in [b.text for row in settings_menu(chat).inline_keyboard for b in row]
    assert "Отчёты: <b>текстом</b>" in render_settings(chat)
    data = [b.callback_data for row in settings_menu(chat).inline_keyboard for b in row]
    assert "s:images" in data


def test_settings_button_toggles_in_chat(e2e, tmp_path):
    import mmrbot.bot as botmod
    storage = Storage(str(tmp_path / "s.db"))
    storage.get_or_create_chat(100)
    cb = e2e.FakeCallback("s:images")
    run(botmod.on_callback(cb, storage, None, None))
    assert storage.get_or_create_chat(100).prefer_text is True
    assert "Отчёты: <b>текстом</b>" in cb.message.texts
    run(botmod.on_callback(e2e.FakeCallback("s:images"), storage, None, None))
    assert storage.get_or_create_chat(100).prefer_text is False


# --- сервис: все борды уважают настройку ----------------------------------------------------------

def test_want_image_explicit_flag_beats_chat_setting(tmp_path):
    storage = Storage(str(tmp_path / "t.db"))
    assert service.want_image(storage, 1) is True
    storage.set_chat_prefer_text(1, True)
    assert service.want_image(storage, 1) is False
    assert service.want_image(storage, 1, True) is True and service.want_image(storage, 1, False) is False


@pytest.fixture
def env(e2e, tmp_path):
    storage = Storage(str(tmp_path / "e2e.db"))
    storage.get_or_create_chat(100)
    storage.add_player(100, e2e.ACC, "shinoame", 5000, 0, 0)
    return storage, e2e.FakeOD(), e2e.FakeStratz()


COMMANDS = [("cmd_stats", "stats", None), ("cmd_stats", "stats", "сегодня"), ("cmd_stats", "stats", "неделя"),
            ("cmd_player", "player", "shinoame"), ("cmd_heroes", "heroes", None), ("cmd_heroes", "heroes", "shinoame"),
            ("cmd_heroes", "heroes", "kez"), ("cmd_roles", "roles", "shinoame"), ("cmd_records", "records", None),
            ("cmd_match", "match", None)]


@pytest.mark.parametrize("handler,name,args", COMMANDS)
def test_text_mode_answers_every_report_with_text_only(e2e, env, handler, name, args):
    import mmrbot.bot as botmod
    storage, od, sz = env
    storage.set_chat_prefer_text(100, True)
    msg = e2e.FakeMessage()
    run(getattr(botmod, handler)(msg, e2e.cmdobj(name, args), storage, od, sz))
    e2e.assert_ok(msg)
    assert not msg.photos and msg.sent
    assert not any((b.callback_data or "").startswith("tx:") for _, kw in msg.sent
                   for row in (kw.get("reply_markup").inline_keyboard if kw.get("reply_markup") else []) for b in row)  # кнопка «Текстом» не нужна


@pytest.mark.parametrize("handler", ["cmd_compare", "cmd_together"])
def test_text_mode_for_compare_and_together(e2e, env, handler):
    import mmrbot.bot as botmod
    storage, od, sz = env
    storage.set_chat_prefer_text(100, True)
    msg = e2e.FakeMessage()
    run(getattr(botmod, handler)(msg, storage, od, sz))
    e2e.assert_ok(msg)
    assert not msg.photos and msg.sent


def test_text_mode_keeps_period_buttons_and_edits_in_place(e2e, env):
    import mmrbot.bot as botmod
    storage, od, sz = env
    storage.set_chat_prefer_text(100, True)
    cb = e2e.FakeCallback("hp:%d:week" % e2e.ACC)
    run(botmod.on_callback(cb, storage, od, sz))
    (text, kw), = cb.message.sent  # одно сообщение, правится edit_text — без новых
    assert "за неделю" in text
    data = [b.callback_data for row in kw["reply_markup"].inline_keyboard for b in row]
    assert "hp:%d:month" % e2e.ACC in data and not any(d.startswith("tx:") for d in data)
    marked = [b.text for row in kw["reply_markup"].inline_keyboard for b in row if b.text.startswith("•")]
    assert marked == ["• Неделя"]


def test_text_mode_records_period_switch_edits_text(e2e, env):
    import mmrbot.bot as botmod
    storage, od, sz = env
    storage.set_chat_prefer_text(100, True)
    cb = e2e.FakeCallback("r:year")
    run(botmod.on_callback(cb, storage, od, sz))
    (text, kw), = cb.message.sent
    assert "за год" in text and any(b.callback_data == "r:month" for row in kw["reply_markup"].inline_keyboard for b in row)


def test_switching_to_text_replaces_photo_card(e2e, env):
    """Картинку показывали, потом выбрали «текстом»: нажатие периода присылает текст и убирает старое фото."""
    import mmrbot.bot as botmod
    storage, od, sz = env
    storage.set_chat_prefer_text(100, True)

    class PhotoMessage(e2e.FakeMessage):
        photo = [object()]
        deleted = False

        async def delete(self):
            self.deleted = True

    cb = e2e.FakeCallback("hp:%d:week" % e2e.ACC)
    cb.message = PhotoMessage()
    run(botmod.on_callback(cb, storage, od, sz))
    assert cb.message.deleted and cb.message.sent and "за неделю" in cb.message.texts


def test_default_chat_still_gets_images(e2e, env):
    import mmrbot.bot as botmod
    storage, od, sz = env
    msg = e2e.FakeMessage()
    run(botmod.cmd_stats(msg, e2e.cmdobj("stats", None), storage, od, sz))
    assert len(msg.photos) == 1


# --- планировщик ------------------------------------------------------------------------------------

class _Bot:
    def __init__(self):
        self.photos, self.messages = [], []

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        self.photos.append(caption)

    async def send_message(self, chat_id, text, **kw):
        self.messages.append(text)


def _chat_with_games(tmp_path, prefer_text):
    import time
    storage = Storage(str(tmp_path / "w.db"))
    chat = storage.get_or_create_chat(5)
    player = storage.add_player(5, 1, "Вася", 5000, 0, 0)
    now = int(time.time())
    storage.add_matches(player.id, [{"match_id": i, "start_time": now - 3600 * i, "player_slot": 0, "radiant_win": i != 2,
                                     "lobby_type": 7, "hero_id": 1, "kills": 5, "deaths": 2, "assists": 7} for i in range(1, 5)])
    storage.set_chat_prefer_text(5, prefer_text)
    return storage, storage.get_or_create_chat(5)


def test_weekly_and_digest_go_out_as_text_when_chat_prefers_text(tmp_path, monkeypatch):
    from mmrbot.health import ProviderHealth

    class Down:
        api_key = "K"

        def __init__(self):
            self.health = ProviderHealth("OpenDota")
            self.health.failure(RuntimeError("down"))

    async def refreshed(*a, **kw):
        return None

    monkeypatch.setattr(sched, "refresh_only", refreshed)
    monkeypatch.setattr(sched, "due_weekly_key", lambda c, now: "2026-W41")
    storage, chat = _chat_with_games(tmp_path, prefer_text=True)
    bot = _Bot()
    run(sched.send_digest(bot, storage, Down(), chat, "2026-10-07"))
    jobs = {j.func.__name__: j.func for j in sched.setup_scheduler(bot, storage, None).get_jobs()}
    run(jobs["weekly_summary"]())
    assert not bot.photos and len(bot.messages) >= 2
    assert any("Ежедневная сводка" in m for m in bot.messages) and any("Итоги недели" in m for m in bot.messages)


def test_match_alert_goes_out_as_text_when_chat_prefers_text(tmp_path):
    event = {"kind": "match", "chat_id": 5, "match_id": 7, "start_time": 1_760_000_000, "duration": 2400, "average_rank": 55,
             "rows": [{"name": "Вася", "won": True, "hero_id": 1, "kills": 5, "deaths": 2, "assists": 7, "step": 25,
                       "current_mmr": 5025, "avatar": None}], "shared": None}
    with_image = run(service.alert_board(event, "UTC"))
    text_only = run(service.alert_board(event, "UTC", image=False))
    assert with_image.png is not None and text_only.png is None and text_only.text == with_image.text
