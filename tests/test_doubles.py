"""Дабл-дауны: пометка «×2» у матча и её влияние на оценку MMR."""
import asyncio

import pytest
from aiogram.filters import CommandObject

from mmrbot import doubles, service, stats
from mmrbot.awards import compute_standings
from mmrbot.formatting import render_game_alert
from mmrbot.keyboards import alert_buttons
from mmrbot.storage import Storage
from mmrbot.tracker import (
    build_daily_report,
    build_mmr_series,
    build_period_leaderboard,
    build_player_summary,
    detect_new_games,
)
from tests.legacy_db import add_match, add_player, make_v2
from tests.test_tracker import FakeOpenDota, od_match

T0 = 1_780_000_000
HOUR = 3600


def game(match_id, start, win=True):
    return {"match_id": match_id, "start_time": start, "player_slot": 0, "radiant_win": win, "lobby_type": 7,
            "kills": 9, "deaths": 2, "assists": 11, "hero_id": 2, "duration": 1800}


@pytest.fixture
def store(tmp_path):
    storage = Storage(str(tmp_path / "d.db"))
    storage.get_or_create_chat(1)
    return storage


def _player(store, matches):
    player = store.add_player(1, 42, "Вася", 5000, T0, T0)
    store.add_matches(player.id, matches)
    return player


def _mmr(store, now=T0 + 50 * HOUR):
    return build_player_summary(store, store.get_or_create_chat(1), store.get_player(1, "Вася"), now)


class Message:
    def __init__(self, user_id=None, markup=None):
        self.chat = type("Chat", (), {"id": 1, "type": "group"})()
        self.from_user = type("User", (), {"id": user_id})() if user_id else None
        self.reply_markup = markup
        self.sent, self.markups = [], []

    async def answer(self, text, **kwargs):
        self.sent.append(text)

    async def edit_reply_markup(self, reply_markup=None):
        self.markups.append(reply_markup)


class Query:
    def __init__(self, data, message):
        self.data, self.message, self.toasts = data, message, []

    async def answer(self, text=None, **kwargs):
        self.toasts.append(text)


def test_double_down_counts_two_steps():
    assert stats.match_mmr_delta(game(1, T0), 25) == 25
    assert stats.match_mmr_delta({**game(1, T0), "double_down": 1}, 25) == 50
    assert stats.match_mmr_delta({**game(1, T0, win=False), "double_down": 1}, 30) == -60
    assert stats.mmr_series([game(1, T0), {**game(2, T0 + 1, win=False), "double_down": 1}], 25) == [(T0, 25), (T0 + 1, -25)]


def test_mark_changes_estimate_everywhere(store):
    player = _player(store, [game(1, T0 + HOUR), game(2, T0 + 2 * HOUR, win=False)])
    assert _mmr(store).current_mmr == 5000
    assert store.set_double_down(player.id, 1) is True
    summary = _mmr(store)
    assert (summary.current_mmr, summary.mmr_delta) == (5025, 25)  # +50 −25
    now = T0 + 3 * HOUR
    assert build_period_leaderboard(store, 1, T0)[0]["delta"] == 25
    assert build_daily_report(store, 1, now)["rows"][0]["delta"] == 25
    assert build_mmr_series(store, 1, T0)["Вася"] == [(T0 + HOUR, 50), (T0 + 2 * HOUR, 25)]
    assert service._mmr_values(store, 1, player.id) == [5050, 5025]
    assert store.set_double_down(player.id, 1) is False  # повтор снимает
    assert _mmr(store).current_mmr == 5000


def test_contest_climb_uses_doubles():
    named = [("Вася", [{**game(1, T0), "double_down": 1}]), ("Петя", [game(2, T0)])]
    climb = next(s for s in compute_standings(named, 25) if s["key"] == "climb")
    assert [(e["player"], e["value"]) for e in climb["entries"]] == [("Вася", 50), ("Петя", 25)]


def test_unknown_match_is_reported(store):
    player = _player(store, [game(1, T0 + HOUR)])
    assert store.set_double_down(player.id, 999) is None
    assert doubles.toggle(store, 1, player, 999, T0) is None
    empty = store.add_player(1, 43, "Петя", None, T0, T0)
    assert doubles.toggle(store, 1, empty, None, T0) is None  # матчей нет вовсе


def test_mark_is_shared_between_chats_of_one_account(store):
    player = _player(store, [game(1, T0 + HOUR)])
    store.get_or_create_chat(2)
    other = store.add_player(2, 42, "Василий", 4000, T0, T0)
    store.set_double_down(player.id, 1, True)
    summary = build_player_summary(store, store.get_or_create_chat(2), store.get_player(2, "Василий"), T0 + 5 * HOUR)
    assert summary.current_mmr == 4050 and store.get_match(other.id, 1)["double_down"] == 1


def test_alert_has_button_per_player_and_reports_delta(store):
    store.add_player(1, 1, "Вася", 5000, T0 - 10, T0 - 10)
    store.add_player(1, 2, "Петя", 4000, T0 - 10, T0 - 10)
    client = FakeOpenDota(matches=[od_match(7812345678, T0 + 600, radiant_win=True)])
    event = detect_new_games(store, client, store.get_or_create_chat(1), T0 + 3000)[0]
    assert [(r["delta"], r["double"]) for r in event["rows"]] == [(25, False), (25, False)]
    markup = alert_buttons(event["match_id"], [(r["account_id"], r["name"], r["double"]) for r in event["rows"]])
    data = [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]
    assert data == ["mx:7812345678", "dd:7812345678:1", "dd:7812345678:2"]
    assert all(len(d.encode()) <= 64 for d in data)
    assert "+25" in render_game_alert(event)


def test_button_toggles_and_redraws_keyboard(store):
    store.add_player(1, 1, "Вася", 5000, T0 - 10, T0 - 10)
    store.add_player(1, 2, "Петя", 4000, T0 - 10, T0 - 10)
    for name in ("Вася", "Петя"):
        store.add_matches(store.get_player(1, name).id, [game(7812345678, T0 + 600)])
    message = Message(markup=alert_buttons(7812345678, [(1, "Вася", False), (2, "Петя", False)]))
    query = Query("dd:7812345678:2", message)
    asyncio.run(doubles.on_double_button(query, store))
    assert "Петя: дабл-даун, +50 вместо +25, ≈4050 MMR" == query.toasts[0]
    texts = [b.text for row in message.markups[0].inline_keyboard for b in row]
    assert texts == ["🎮 Весь матч", "🔗 Dotabuff", "×2 Вася", "✅ ×2 Петя"]

    message.reply_markup = message.markups[0]
    again = Query("dd:7812345678:2", message)
    asyncio.run(doubles.on_double_button(again, store))
    assert "снят" in again.toasts[0] and "≈4025" in again.toasts[0]
    assert [b.text for row in message.markups[1].inline_keyboard for b in row][-1] == "×2 Петя"


def test_button_for_removed_player_or_garbage_does_not_crash(store):
    message = Message(markup=alert_buttons(7812345678, [(1, "Вася", False)]))
    gone = Query("dd:7812345678:1", message)
    asyncio.run(doubles.on_double_button(gone, store))
    assert "удалён" in gone.toasts[0]
    garbage = Query("dd:abc", message)
    asyncio.run(doubles.on_double_button(garbage, store))
    assert garbage.toasts == [None] and message.markups == []


def test_command_marks_own_last_match_or_named_one(store):
    player = _player(store, [game(7812345671, T0 + HOUR), game(7812345672, T0 + 2 * HOUR, win=False)])
    store.link_user(1, player.id, 500)

    mine = Message(user_id=500)
    asyncio.run(doubles.cmd_double(mine, CommandObject(command="double", args=None), store))
    assert "7812345672" in mine.sent[0] and "-50 вместо -25" in mine.sent[0] and "≈4975" in mine.sent[0]

    named = Message(user_id=999)
    asyncio.run(doubles.cmd_double(named, CommandObject(command="double", args="Вася 7812345671"), store))
    assert "7812345671" in named.sent[0] and "+50 вместо +25" in named.sent[0] and "≈5000" in named.sent[0]

    undo = Message(user_id=500)
    asyncio.run(doubles.cmd_double(undo, CommandObject(command="double", args="7812345672"), store))
    assert "снят" in undo.sent[0] and _mmr(store).current_mmr == 5025

    stranger = Message(user_id=999)
    asyncio.run(doubles.cmd_double(stranger, CommandObject(command="double", args=None), store))
    assert stranger.sent == [doubles.WHO]
    missing = Message()
    asyncio.run(doubles.cmd_double(missing, CommandObject(command="double", args="Вася 7899999999"), store))
    assert missing.sent == [doubles.NO_MATCH]


def test_migration_adds_unmarked_column(tmp_path):
    path = str(tmp_path / "bot.db")
    conn = make_v2(path)
    player = add_player(conn, 1, 42, "Вася", 5000)
    add_match(conn, player, 1, 100)
    conn.commit()
    conn.close()
    store = Storage(path)
    assert store.get_matches(player)[0]["double_down"] == 0
    assert store.set_double_down(player, 1) is True
