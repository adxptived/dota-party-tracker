"""Соперники и союзники: составы команд, расчёт списков героев, отчёт и команда."""
import asyncio
import io
import time

import pytest
from aiogram.filters import CommandObject
from PIL import Image

import mmrbot.bot as botmod
from mmrbot import matchups, service
from mmrbot.matchups import party_matchups, player_matchups, render_matchups
from mmrbot.matchups_image import render_matchups_image
from mmrbot.opendota import OpenDota, lineup_of
from mmrbot.storage import Storage
from mmrbot.stratz import Stratz
from mmrbot.tracker import backfill_opendota, build_matchups, refresh_player
from tests.legacy_db import add_match, add_player, make_v2
from tests.test_opendota import FakeResp, FakeSession

T0 = 1_780_000_000
AXE, BANE, CM, DROW, ES, JUGG, LINA, LION, MIRANA, PUDGE = 2, 3, 5, 6, 7, 8, 25, 26, 9, 14


def match(match_id, hero=JUGG, win=True, radiant=True, start=None):
    return {"match_id": match_id, "start_time": start or T0 + match_id, "player_slot": 0 if radiant else 128,
            "radiant_win": win if radiant else not win, "lobby_type": 7, "hero_id": hero, "kills": 5, "deaths": 3,
            "assists": 7, "duration": 1800}


def lineup(mine, theirs, radiant=True):
    return (tuple(mine), tuple(theirs)) if radiant else (tuple(theirs), tuple(mine))


# --- расчёт -------------------------------------------------------------------------

def _history():
    """10 игр: против Axe 1–4, против Lina 4–1; с Lion в команде 4–1, с Pudge 1–4."""
    matches, lineups = [], {}
    for i in range(10):
        hard = i < 5
        won = (i == 0) if hard else (i != 9)
        matches.append(match(i + 1, win=won))
        lineups[i + 1] = lineup([JUGG, PUDGE if hard else LION, CM, DROW, ES], [AXE if hard else LINA, BANE, MIRANA, 30 + i, 50 + i])
    return matches, lineups


def test_player_lists_split_by_usual_winrate():
    matches, lineups = _history()
    report = player_matchups(matches, lineups, min_games=3)
    assert (report["total"], report["games"], report["wins"], report["winrate"]) == (10, 10, 5, 0.5)
    assert [r["hero_id"] for r in report["hard"]] == [AXE]
    assert [r["hero_id"] for r in report["easy"]] == [LINA]
    assert [(r["hero_id"], r["wins"], r["losses"]) for r in report["good_allies"]] == [(LION, 4, 1)]
    assert [(r["hero_id"], r["wins"], r["losses"]) for r in report["bad_allies"]] == [(PUDGE, 1, 4)]
    # герои, встреченные в каждой игре (Bane, CM…), на винрейт не влияют — их в списках нет
    listed = {r["hero_id"] for key in ("hard", "easy", "good_allies", "bad_allies") for r in report[key]}
    assert listed == {AXE, LINA, LION, PUDGE}


def test_own_hero_is_not_an_ally_but_a_teammate_on_same_hero_is():
    matches = [match(i, hero=JUGG, win=True) for i in range(1, 5)] + [match(5, hero=JUGG, win=False)]
    lineups = {i: lineup([JUGG, CM, DROW, ES, LION], [AXE, BANE, LINA, MIRANA, PUDGE]) for i in range(1, 6)}
    report = player_matchups(matches, lineups, min_games=1)
    assert JUGG not in {r["hero_id"] for r in report["good_allies"] + report["bad_allies"]}


def test_side_is_respected_for_dire_games():
    matches = [match(i, radiant=False, win=False) for i in range(1, 4)] + [match(i, radiant=False, win=True) for i in range(4, 7)]
    lineups = {i: lineup([JUGG, CM, DROW, ES, LION], [AXE if i < 4 else LINA, BANE, MIRANA, 40, 41], radiant=False)
               for i in range(1, 7)}
    report = player_matchups(matches, lineups, min_games=3)
    assert [r["hero_id"] for r in report["hard"]] == [AXE] and [r["hero_id"] for r in report["easy"]] == [LINA]


def test_rare_hero_does_not_outrank_a_proven_one():
    matches = [match(i, win=False) for i in range(1, 4)]            # 0–3 против Axe
    matches += [match(i, win=i > 22) for i in range(10, 30)]        # 7–13 против Lina: 20 игр
    matches += [match(i, win=True) for i in range(40, 57)]          # 17 побед без них
    lineups = {m["match_id"]: lineup([JUGG, CM, DROW, ES, LION], [BANE, MIRANA, 40, 41, 42]) for m in matches}
    for i in range(1, 4):
        lineups[i] = lineup([JUGG, CM, DROW, ES, LION], [AXE, BANE, MIRANA, 40, 41])
    for i in range(10, 30):
        lineups[i] = lineup([JUGG, CM, DROW, ES, LION], [LINA, BANE, MIRANA, 40, 41])
    hard = [r["hero_id"] for r in player_matchups(matches, lineups, min_games=3)["hard"]]
    assert hard[:2] == [LINA, AXE]  # 7–13 за 20 игр весомее, чем 0–3


def test_matches_without_lineup_are_counted_as_missing():
    matches, lineups = _history()
    del lineups[1], lineups[2]
    report = player_matchups(matches, lineups)
    assert (report["total"], report["games"]) == (10, 8)
    assert matchups.coverage(report) == "по 8 из 10 игр"
    assert matchups.coverage({"games": 21, "total": 21}) == "по 21 игре"
    assert matchups.coverage({"games": 5, "total": 5}) == "по 5 играм"


def test_party_counts_shared_game_once_and_skips_own_heroes():
    vasya = [match(i, hero=JUGG, win=i != 1) for i in range(1, 6)]
    petya = [match(i, hero=CM, win=i != 1) for i in range(1, 6)]
    lineups = {i: lineup([JUGG, CM, LION, DROW, ES], [AXE, BANE, LINA, MIRANA, PUDGE]) for i in range(1, 6)}
    report = party_matchups([("Вася", vasya), ("Петя", petya)], lineups, min_games=1)
    assert (report["total"], report["games"], report["wins"]) == (5, 5, 4)  # пять игр, а не десять
    solo = player_matchups(vasya, lineups, min_games=1)
    assert solo["games"] == 5
    party_allies = {r["hero_id"] for r in report["good_allies"] + report["bad_allies"]}
    assert not {JUGG, CM} & party_allies  # герои своих игроков — не «союзники»


def test_thresholds_grow_with_period():
    assert [matchups.threshold(p) for p in ("day", "week", "month", "year", "all")] == [2, 2, 3, 4, 4]


# --- откуда берутся составы ----------------------------------------------------------

def test_lineup_from_match_list_and_match_players():
    heroes = {"0": {"hero_id": 1}, "1": {"hero_id": 2}, "2": {"hero_id": 3}, "3": {"hero_id": 4}, "4": {"hero_id": 5},
              "128": {"hero_id": 6}, "129": {"hero_id": 7}, "130": {"hero_id": 8}, "131": {"hero_id": 9}, "132": {"hero_id": 10}}
    assert lineup_of(heroes) == ([1, 2, 3, 4, 5], [6, 7, 8, 9, 10])
    players = [{"hero_id": 11, "player_slot": 0}, {"hero_id": 12, "player_slot": 130}, {"hero_id": 0, "player_slot": 1}]
    assert lineup_of(players) == ([11], [12])
    assert lineup_of(None) is None and lineup_of({}) is None and lineup_of([{"hero_id": 5, "player_slot": 0}]) is None


@pytest.fixture
def store(tmp_path):
    storage = Storage(str(tmp_path / "m.db"))
    storage.get_or_create_chat(1)
    return storage


def _od_row(match_id, start, slot=0, win=True, hero=JUGG, heroes=None):
    row = {"match_id": match_id, "start_time": start, "player_slot": slot, "radiant_win": win, "lobby_type": 7,
           "hero_id": hero, "kills": 1, "deaths": 1, "assists": 1, "duration": 1800}
    if heroes is not None:
        row["heroes"] = heroes
    return row


def _heroes(radiant, dire):
    result = {str(i): {"hero_id": h} for i, h in enumerate(radiant)}
    result.update({str(128 + i): {"hero_id": h} for i, h in enumerate(dire)})
    return result


class ListClient:
    """Клиент, отдающий список матчей (с составами или без) и считающий полные выгрузки."""

    def __init__(self, rows):
        self.rows, self.limits = rows, []

    def refresh(self, account_id):
        return True

    def get_profile(self, account_id):
        return {"rank_tier": None, "leaderboard_rank": None, "personaname": "x"}

    def get_matches(self, account_id, limit=200):
        self.limits.append(limit)
        return list(self.rows)

    def get_match_player_stats(self, match_id, account_id, player_slot=None):
        return None


def test_lineups_arrive_with_match_list(store):
    player = store.add_player(1, 42, "Вася", None, T0, T0)
    client = ListClient([_od_row(1, T0 + 10, heroes=_heroes([JUGG, CM, DROW, ES, LION], [AXE, BANE, LINA, MIRANA, PUDGE]))])
    refresh_player(store, client, player, T0 + 100)
    assert store.get_lineups(player.id) == {1: ((JUGG, CM, DROW, ES, LION), (AXE, BANE, LINA, MIRANA, PUDGE))}
    assert store.get_player(1, "Вася").lineups_ts == T0 + 100


def test_existing_history_gets_lineups_by_one_full_reload_in_background(store):
    player = store.add_player(1, 42, "Вася", None, T0, T0)
    store.add_matches(player.id, [_od_row(1, T0 + 10)])  # история сохранена до появления составов
    store.touch_player(player.id, T0 + 20, deep=True)
    with_heroes = [_od_row(1, T0 + 10, heroes=_heroes([JUGG, CM, DROW, ES, LION], [AXE, BANE, LINA, MIRANA, PUDGE]))]
    client = ListClient(with_heroes)

    refresh_player(store, client, store.get_player(1, "Вася"), T0 + 30, fast=True)  # команда пользователя — не грузим всё
    assert client.limits == [200] and store.get_lineups(player.id) == {1: ((JUGG, CM, DROW, ES, LION), (AXE, BANE, LINA, MIRANA, PUDGE))}
    assert store.get_player(1, "Вася").lineups_ts is None

    refresh_player(store, client, store.get_player(1, "Вася"), T0 + 40)  # фон — вся история, один раз
    assert client.limits == [200, None] and store.get_player(1, "Вася").lineups_ts == T0 + 40
    refresh_player(store, client, store.get_player(1, "Вася"), T0 + 7 * 3600 + 50)
    assert client.limits[-1] == 200  # дальше — обычная сверка


def test_lineup_from_match_details_and_stratz(store):
    player = store.add_player(1, 42, "Вася", None, T0, T0)
    store.add_matches(player.id, [_od_row(1, T0 + 10), _od_row(2, T0 + 20)])
    players = [{"account_id": 42, "player_slot": 0, "hero_id": JUGG, "gold_per_min": 500}]
    players += [{"player_slot": i, "hero_id": h} for i, h in zip((1, 2, 3, 4), (CM, DROW, ES, LION))]
    players += [{"player_slot": 128 + i, "hero_id": h} for i, h in enumerate((AXE, BANE, LINA, MIRANA, PUDGE))]
    od = OpenDota(session=FakeSession({"players": players}), min_interval=0)
    backfill_opendota(store, od, now=T0 + 100)
    assert store.get_lineups(player.id)[2] == ((JUGG, CM, DROW, ES, LION), (AXE, BANE, LINA, MIRANA, PUDGE))

    rows = [{"steamAccountId": 42, "isRadiant": True, "heroId": JUGG, "position": "POSITION_1", "imp": 5}]
    rows += [{"steamAccountId": 100 + h, "isRadiant": True, "heroId": h} for h in (CM, DROW, ES, LION)]
    rows += [{"steamAccountId": 200 + h, "isRadiant": False, "heroId": h} for h in (AXE, BANE, LINA, MIRANA, PUDGE)]

    class Session:
        def post(self, url, json=None, headers=None, timeout=None):
            return FakeResp({"data": {"m0": {"players": rows}}})

    info = Stratz("key", session=Session(), min_interval=0).get_matches(42, [7])[7]
    assert info["lineup"] == ([JUGG, CM, DROW, ES, LION], [AXE, BANE, LINA, MIRANA, PUDGE])


def test_fuller_lineup_replaces_partial_and_orphans_are_removed(store):
    player = store.add_player(1, 42, "Вася", None, T0, T0)
    partial = {**_od_row(1, T0 + 10), "lineup": ([JUGG, CM], [AXE])}
    full = {**_od_row(1, T0 + 10), "lineup": ([JUGG, CM, DROW, ES, LION], [AXE, BANE, LINA, MIRANA, PUDGE])}
    store.add_matches(player.id, [partial])
    store.add_matches(player.id, [full])
    store.add_matches(player.id, [partial])  # неполный не затирает полный
    assert store.get_lineups(player.id)[1] == ((JUGG, CM, DROW, ES, LION), (AXE, BANE, LINA, MIRANA, PUDGE))
    assert store.get_lineups(player.id, since_ts=T0 + 11) == {}
    store.remove_player(1, "Вася")
    with store._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM match_lineups").fetchone()[0] == 0


def test_project_fallback_when_opendota_ignores_columns():
    """Если выбор колонок вернул строки без start_time, клиент один раз переспрашивает без project и запоминает это."""
    calls = []

    class Session:
        def get(self, url, params=None, timeout=None, headers=None):
            calls.append(dict(params or {}))
            if "project" in (params or {}):
                return FakeResp([{"match_id": 1, "player_slot": 0, "radiant_win": True}])
            return FakeResp([{"match_id": 1, "player_slot": 0, "radiant_win": True, "start_time": 5}])

    od = OpenDota(session=Session(), min_interval=0)
    assert od.get_matches(42)[0]["start_time"] == 5
    assert ["project" in c for c in calls] == [True, False]
    od.get_matches(42)
    assert "project" not in calls[-1]


def test_migrated_database_starts_without_lineups(tmp_path):
    path = str(tmp_path / "bot.db")
    conn = make_v2(path)
    player = add_player(conn, 1, 42, "Вася", 5000)
    add_match(conn, player, 1, 100)
    conn.commit()
    conn.close()
    store = Storage(path)
    assert store.get_lineups(player) == {} and store.get_player(1, "Вася").lineups_ts is None


# --- отчёт -----------------------------------------------------------------------------

def _seed(store, recent=False):
    """10 игр с составами; recent=True — недавние (попадают в окно «месяц»), иначе в окне только «всё»."""
    matches, lineups = _history()
    shift = int(time.time()) - 3 * 86400 - T0 if recent else 0
    player = store.add_player(1, 42, "Вася", 5000, T0, T0)
    store.add_matches(player.id, [dict(m, start_time=m["start_time"] + shift, lineup=lineups[m["match_id"]]) for m in matches])
    store.touch_player(player.id, 10**10)
    return player


def test_build_and_render_report(store):
    _seed(store)
    who, report = build_matchups(store, 1, "Вася", None, min_games=3)
    assert who == "Вася" and [r["hero_id"] for r in report["hard"]] == [AXE]
    text = render_matchups(who, "all", report)
    assert "Соперники и союзники: Вася" in text and "по 10 играм" in text and "обычный винрейт 50%" in text
    assert "Axe — 1–4 (20%)" in text and "Lina — 4–1 (80%)" in text and "Lion — 4–1 (80%)" in text
    party_who, party = build_matchups(store, 1, None, None, min_games=3)
    assert party_who is None and party["games"] == 10
    assert build_matchups(store, 1, "Никто", None) is None


def test_empty_states_are_explained(store):
    player = store.add_player(1, 42, "Вася", 5000, T0, T0)
    assert "игр нет" in render_matchups("Вася", "week", build_matchups(store, 1, "Вася", None)[1])
    store.add_matches(player.id, [match(1)])
    assert matchups.NO_LINEUPS in render_matchups("Вася", "all", build_matchups(store, 1, "Вася", None)[1])
    store.add_matches(player.id, [dict(match(1), lineup=lineup([JUGG, CM, DROW, ES, LION], [AXE, BANE, LINA, MIRANA, PUDGE]))])
    assert "Пока мало повторов" in render_matchups("Вася", "all", build_matchups(store, 1, "Вася", None)[1])


def test_card_renders_with_and_without_rows():
    matches, lineups = _history()
    view = matchups.matchups_view("Вася", "all", player_matchups(matches, lineups, min_games=3))
    image = Image.open(io.BytesIO(render_matchups_image(view)))
    assert image.width == 1280 and image.height > 400
    empty = matchups.matchups_view(None, "week", player_matchups([], {}))
    assert Image.open(io.BytesIO(render_matchups_image(empty))).width == 1280
    assert set(matchups.hero_ids(view)) == {AXE, LINA, LION, PUDGE}


def test_board_gives_text_and_image(store):
    _seed(store)
    board = asyncio.run(service.matchups_board(store, None, 1, "Вася", "all", image=True))
    assert board.png and "Axe" in board.text and "Вася" in board.caption and board.account_id == 42
    text_only = asyncio.run(service.matchups_board(store, None, 1, None, "all", image=False))
    assert text_only.png is None and "пати" in text_only.text and text_only.account_id == 0
    assert asyncio.run(service.matchups_board(store, None, 1, "Никто", "all")) is None


class Message:
    def __init__(self):
        self.chat = type("Chat", (), {"id": 1, "type": "group"})()
        self.from_user = None
        self.photo = None
        self.bot = type("Bot", (), {"send_chat_action": staticmethod(lambda *a, **k: asyncio.sleep(0))})()
        self.texts, self.photos, self.markups = [], [], []

    async def answer(self, text, **kwargs):
        self.texts.append(text)
        self.markups.append(kwargs.get("reply_markup"))

    async def answer_photo(self, photo, caption=None, **kwargs):
        self.photos.append(caption)
        self.markups.append(kwargs.get("reply_markup"))


def test_command_sends_card_with_period_buttons(store):
    _seed(store, recent=True)
    message = Message()
    asyncio.run(botmod.cmd_matchups(message, CommandObject(command="matchups", args="Вася месяц"), store, None))
    assert len(message.photos) == 1 and "Вася" in message.photos[0]
    data = [b.callback_data for row in message.markups[-1].inline_keyboard for b in row if b.callback_data]
    assert "mu:42:week" in data and "tx:mu:42:month" in data and all(len(d.encode()) <= 64 for d in data)

    party = Message()
    asyncio.run(botmod.cmd_matchups(party, CommandObject(command="matchups", args=None), store, None))
    assert "mu:0:all" in [b.callback_data for row in party.markups[-1].inline_keyboard for b in row if b.callback_data]

    unknown = Message()
    asyncio.run(botmod.cmd_matchups(unknown, CommandObject(command="matchups", args="Никто"), store, None))
    assert unknown.photos == [] and "Не нашёл" in unknown.texts[0]
