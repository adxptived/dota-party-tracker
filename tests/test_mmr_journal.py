"""Журнал правок MMR: история не теряется после /setmmr."""
import asyncio

import pytest
from aiogram.filters import CommandObject

import mmrbot.bot as botmod
from mmrbot import service, stats
from mmrbot.formatting import mmr_log_line, render_mmr_set, render_player_card, render_player_list
from mmrbot.storage import Storage
from mmrbot.tracker import build_player_summary, set_player_mmr
from tests.legacy_db import add_player, make_v2

T0 = 1_780_000_000
HOUR = 3600


def game(match_id, start, win=True, duration=1800):
    return {"match_id": match_id, "start_time": start, "player_slot": 0, "radiant_win": win, "lobby_type": 7,
            "kills": 5, "deaths": 3, "assists": 7, "hero_id": 1, "duration": duration}


@pytest.fixture
def store(tmp_path):
    storage = Storage(str(tmp_path / "j.db"))
    storage.get_or_create_chat(1)
    return storage


def _summary(store, name="Вася", now=T0 + 100 * HOUR):
    return build_player_summary(store, store.get_or_create_chat(1), store.get_player(1, name), now)


# --- чистые расчёты -------------------------------------------------------------

def test_ledger_without_corrections_matches_old_formula():
    matches = [game(1, T0 + HOUR), game(2, T0 + 2 * HOUR), game(3, T0 + 3 * HOUR, win=False)]
    ledger = stats.mmr_ledger(matches, [(T0, 5000)], 25)
    assert (ledger["start"], ledger["earned"], ledger["games"], ledger["corrections"], ledger["current"]) == (
        5000, 25, 3, 0, 5025)


def test_correction_keeps_earned_and_reports_drift():
    matches = [game(1, T0 + HOUR), game(2, T0 + 2 * HOUR), game(3, T0 + 10 * HOUR), game(4, T0 + 11 * HOUR, win=False)]
    anchors = [(T0, 5000), (T0 + 5 * HOUR, 5080)]  # после двух побед оценка 5050, в игре оказалось 5080
    ledger = stats.mmr_ledger(matches, anchors, 25)
    assert ledger["earned"] == 50 and ledger["games"] == 4  # заработанное игрой правка не обнуляет
    assert ledger["corrections"] == 30 and ledger["current"] == 5080
    assert ledger["start"] + ledger["earned"] + ledger["corrections"] == ledger["current"]
    assert ledger["entries"][1] == {"ts": T0 + 5 * HOUR, "mmr": 5080, "drift": 30, "games": 2}


def test_value_fixed_before_any_game_replaces_instead_of_correcting():
    matches = [game(1, T0 + 2 * HOUR)]
    ledger = stats.mmr_ledger(matches, [(T0, 5400), (T0 + 60, 4500)], 25)  # опечатка в /add, тут же исправлена
    assert (ledger["start"], ledger["corrections"], ledger["current"]) == (4500, 0, 4525)
    assert len(ledger["entries"]) == 1


def test_game_in_progress_at_correction_counts_after_it():
    running = game(1, T0 + HOUR, duration=3600)  # идёт с T0+1ч до T0+2ч
    ledger = stats.mmr_ledger([game(0, T0 + 10), running], [(T0, 5000), (T0 + HOUR + 600, 5100)], 25)
    assert ledger["entries"][1]["games"] == 1 and ledger["entries"][1]["drift"] == 75  # до правки завершилась одна игра
    assert ledger["current"] == 5125  # идущая игра ещё не входила во введённое число — прибавляется


def test_no_anchor_counts_from_tracking_start_and_has_no_mmr():
    ledger = stats.mmr_ledger([game(1, T0 - HOUR), game(2, T0 + HOUR)], [], 25, since_ts=T0)
    assert (ledger["start"], ledger["current"], ledger["earned"], ledger["games"]) == (None, None, 25, 1)


def test_timeline_is_continuous_through_corrections_and_before_first_anchor():
    matches = [game(1, T0 - 3 * HOUR), game(2, T0 - 2 * HOUR, win=False), game(3, T0 + HOUR), game(4, T0 + 2 * HOUR),
               game(5, T0 + 10 * HOUR, win=False)]
    points = stats.mmr_timeline(matches, [(T0, 5000), (T0 + 5 * HOUR, 5080)], 25)
    assert [value for _, value in points] == [5025, 5000, 5025, 5050, 5055]
    # до первой записи значения восстановлены назад: последняя игра перед ней заканчивается на стартовом MMR
    assert points[1][1] == 5000
    assert stats.mmr_timeline(matches, [], 25) == stats.mmr_series(matches, 25)  # MMR не задан — накопленное от нуля


# --- хранилище ------------------------------------------------------------------

def test_journal_keeps_every_value(store):
    player = store.add_player(1, 42, "Вася", 5000, T0, T0)
    assert store.get_anchors(player.id) == [(T0, 5000)]
    store.set_player_anchor(player.id, 5080, T0 + 500)
    assert store.get_anchors(player.id) == [(T0, 5000), (T0 + 500, 5080)]
    fresh = store.get_player(1, "Вася")
    assert (fresh.anchor_mmr, fresh.anchor_ts) == (5080, T0 + 500)  # «текущее» — последняя запись
    nobody = store.add_player(1, 43, "Петя", None, T0, T0)
    assert store.get_anchors(nobody.id) == []
    store.set_player_anchor(999, 1, 1)  # несуществующий игрок — без записи-сироты
    with store._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM mmr_anchors").fetchone()[0] == 2


def test_journal_is_removed_with_player(store):
    player = store.add_player(1, 42, "Вася", 5000, T0, T0)
    store.set_player_anchor(player.id, 5080, T0 + 500)
    store.remove_player(1, "Вася")
    with store._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM mmr_anchors").fetchone()[0] == 0


def test_existing_anchor_is_seeded_into_journal_by_migration(tmp_path):
    path = str(tmp_path / "bot.db")
    conn = make_v2(path)
    with_mmr = add_player(conn, 1, 42, "Вася", 5300, 1000, 900)
    without = add_player(conn, 1, 43, "Петя", None, 1100, 1100)
    conn.commit()
    conn.close()
    store = Storage(path)
    assert store.get_anchors(with_mmr) == [(1000, 5300)]
    assert store.get_anchors(without) == []


# --- сводка и тексты ------------------------------------------------------------

def _played(store):
    player = store.add_player(1, 42, "Вася", 5000, T0, T0)
    store.add_matches(player.id, [game(1, T0 + HOUR), game(2, T0 + 2 * HOUR)])
    return player


def test_setmmr_does_not_reset_earned_mmr(store):
    player = _played(store)
    before, after = set_player_mmr(store, 1, player, 5080, T0 + 5 * HOUR)
    assert (before.current_mmr, before.mmr_delta, before.mmr_corrections) == (5050, 50, 0)
    assert (after.anchor_mmr, after.current_mmr, after.mmr_delta, after.anchor_games, after.mmr_corrections) == (
        5000, 5080, 50, 2, 30)
    store.add_matches(player.id, [game(3, T0 + 6 * HOUR, win=False)])
    later = _summary(store)
    assert (later.current_mmr, later.mmr_delta, later.anchor_games, later.mmr_corrections) == (5055, 25, 3, 30)


def test_setmmr_reply_explains_what_changed(store):
    player = _played(store)
    before, after = set_player_mmr(store, 1, player, 5080, T0 + 5 * HOUR)
    text = render_mmr_set("Вася", 5080, before, after)
    assert "≈5080" in text and "≈5050" in text and "+30 за 2 игры" in text and "(+50)" in text

    same_before, same_after = set_player_mmr(store, 1, store.get_player(1, "Вася"), 4980, T0 + 5 * HOUR + 60)
    replaced = render_mmr_set("Вася", 4980, same_before, same_after)
    assert "значение заменено" in replaced and "поправка" not in replaced

    store.add_matches(player.id, [game(3, T0 + 6 * HOUR)])
    hit_before, hit_after = set_player_mmr(store, 1, store.get_player(1, "Вася"), 5005, T0 + 8 * HOUR)
    assert "совпала" in render_mmr_set("Вася", 5005, hit_before, hit_after)


def test_first_mmr_reply_is_plain(store):
    player = store.add_player(1, 42, "Вася", None, T0, T0)
    before, after = set_player_mmr(store, 1, player, 5400, T0 + 10)
    assert render_mmr_set("Вася", 5400, before, after) == "✅ <b>Вася</b>: ≈5400 MMR"
    assert after.current_mmr == 5400 and after.mmr_log[0]["mmr"] == 5400


def test_cards_show_corrections(store):
    player = _played(store)
    set_player_mmr(store, 1, player, 5080, T0 + 5 * HOUR)
    summary = _summary(store)
    assert "правки +30" in render_player_list([summary]) and "старт 5000" in render_player_list([summary])
    line = mmr_log_line(summary, "Europe/Moscow")
    assert line.startswith("✏️ Правки MMR:") and "+30" in line
    assert line in render_player_card(summary, tz="Europe/Moscow")
    untouched = store.add_player(1, 43, "Петя", 4000, T0, T0)
    assert mmr_log_line(build_player_summary(store, store.get_or_create_chat(1), untouched, T0), "UTC") == ""


def test_card_line_shows_real_mmr_through_correction(store):
    player = _played(store)
    set_player_mmr(store, 1, player, 5080, T0 + 5 * HOUR)
    store.add_matches(player.id, [game(3, T0 + 6 * HOUR, win=False)])
    assert service._mmr_values(store, 1, player.id) == [5025, 5050, 5055]


def test_setmmr_command_writes_journal(store):
    player = _played(store)
    sent = []

    class Message:
        chat = type("Chat", (), {"id": 1, "type": "group"})()

        async def answer(self, text, **kwargs):
            sent.append(text)

    asyncio.run(botmod.cmd_setmmr(Message(), CommandObject(command="setmmr", args="Вася 5100"), store))
    assert len(store.get_anchors(player.id)) == 2 and "поправка +50" in sent[0]
