"""Поиск по ID (/find): разбор запроса, карточка любого игрока из OpenDota, матч по ID и ссылке."""
import asyncio
import time

import pytest

from mmrbot import card_data as cd
from mmrbot.commands import looks_like_player_id, parse_lookup, parse_match_args
from mmrbot.service import lookup_board
from mmrbot.storage import Storage

NOW = int(time.time())
STRANGER = 123456789


def _raw(i, win=True, hero=11, lobby=7):
    return {"match_id": 9_000_000_000 + i, "start_time": NOW - i * 3600, "player_slot": 0, "radiant_win": win,
            "lobby_type": lobby, "kills": 10, "deaths": 5, "assists": 12, "hero_id": hero, "duration": 2400,
            "party_size": 1 if i % 2 else 3, "average_rank": 71}


class FakeOD:
    def __init__(self, players=None, matches=None):
        self.players = players or {}
        self.match_ids = matches or {}
        self.calls = []

    def get_profile(self, account_id):
        self.calls.append(("profile", account_id))
        return self.players.get(account_id, {})

    def get_matches(self, account_id, limit=200, lobby_type=7):
        self.calls.append(("matches", account_id))
        if account_id not in self.players:
            return []
        return [_raw(i, win=i % 3 != 0, hero=11 if i % 2 else 1) for i in range(12)] + [_raw(99, lobby=0)]

    def get_recent_matches(self, account_id):
        return [{"match_id": 9_000_000_000 + i, "gold_per_min": 500 + i, "hero_damage": 20000} for i in range(4)]

    def get_match(self, match_id):
        self.calls.append(("match", match_id))
        if match_id not in self.match_ids:
            raise RuntimeError("404")
        return self.match_ids[match_id]


def _od_match(match_id):
    return {"match_id": match_id, "start_time": NOW, "duration": 2400, "radiant_win": True,
            "players": [{"account_id": STRANGER, "player_slot": 0, "hero_id": 11, "kills": 10, "deaths": 5,
                         "assists": 12, "isRadiant": True, "personaname": "genocide in hell"}]}


@pytest.fixture
def store(tmp_path):
    from mmrbot import service
    service._LOOKUPS.clear()  # кэш поиска общий на процесс — каждый тест начинает с чистого
    storage = Storage(str(tmp_path / "l.db"))
    storage.get_or_create_chat(1)
    return storage


# --- разбор запроса -----------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("9042174049", ("match", 9042174049)),
    ("https://www.dotabuff.com/matches/9042174049", ("match", 9042174049)),
    ("stratz.com/matches/8000000000/", ("match", 8000000000)),
    ("https://www.opendota.com/players/123456789", ("player", 123456789)),
    ("76561198083722517", ("player", 123456789)),
    ("123456789", ("auto", 123456789)),
    ("матч 123456789", ("match", 123456789)),
    ("игрок 3000000000", ("player", 3000000000)),
    ("steamcommunity.com/id/foo", ("vanity", "steamcommunity.com/id/foo")),
])
def test_parse_lookup(text, expected):
    assert parse_lookup(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "abc", "Вася", "0"])
def test_parse_lookup_rejects_junk_with_hint(text):
    with pytest.raises(ValueError, match="ID матча"):
        parse_lookup(text)


def test_match_links_are_understood_by_match_command():
    assert parse_match_args("https://www.dotabuff.com/matches/9042174049 Вася") == (9042174049, "Вася")
    assert parse_match_args("9042174049") == (9042174049, None)


def test_player_id_detection_for_player_command():
    assert looks_like_player_id("123456789") and looks_like_player_id("dotabuff.com/players/1")
    assert not looks_like_player_id("Вася") and not looks_like_player_id("dotabuff.com/matches/9042174049")


# --- карточка игрока не из пати -----------------------------------------------------------------------

def test_lookup_matches_keep_ranked_sorted_and_merge_details():
    rows = cd.lookup_matches([_raw(2), _raw(1), _raw(3, lobby=0), {"junk": 1}],
                             [{"match_id": 9_000_000_001, "gold_per_min": 640, "hero_damage": 31000}])
    assert [r["match_id"] for r in rows] == [9_000_000_002, 9_000_000_001]
    assert rows[1]["gpm"] == 640 and rows[0]["gpm"] is None


def test_lookup_card_shows_winrate_not_mmr_and_honest_partial_counts():
    matches = cd.lookup_matches([_raw(i, win=i < 6) for i in range(10)],
                                [{"match_id": 9_000_000_000 + i, "gold_per_min": 600} for i in range(3)])
    card = cd.lookup_card(STRANGER, {"personaname": "genocide in hell", "rank_tier": 71}, matches, "UTC")
    assert card["name"] == "genocide in hell" and card["rank_text"] == "Divine 1 · ≈4620–4774"  # MMR по медали
    assert card["mmr_text"] == "60%" and "10 игр" in card["headline_note"] and card["mmr_delta"] is None
    assert "не в пати" in card["subtitle"] and str(STRANGER) in card["subtitle"]
    tiles = {t["label"]: t for t in card["tiles"]}
    assert tiles["Результат"]["value"] == "6–4" and tiles["GPM"]["value"] == "600" and tiles["GPM"]["sub"] == "по 3 игры"
    assert card["recent"] and card["recent_mmr"] is False and len(card["series"]) == 10
    assert card["lobby_text"] == "Divine 1" and "skills" not in card


def test_lookup_card_for_hidden_profile_is_header_and_warning():
    card = cd.lookup_card(STRANGER, {"personaname": "x"}, [], "UTC")
    assert "tiles" not in card and any("закрыт" in w for w in card["warnings"]) and card["mmr_text"] == "—"
    assert cd.lookup_text(card)  # текстом тоже собирается


# --- поиск целиком ------------------------------------------------------------------------------------

def test_find_player_not_in_party_builds_card(store):
    od = FakeOD(players={STRANGER: {"personaname": "genocide in hell", "rank_tier": 63}})
    board = asyncio.run(lookup_board(store, od, 1, str(STRANGER)))
    assert board.kind == "player" and board.account_id == STRANGER and not board.tracked
    assert board.png is not None and "genocide in hell" in board.caption and "genocide in hell" in board.text
    assert ("match", STRANGER) not in od.calls  # игрок нашёлся — как матч не ищем


def test_find_party_member_by_id_shows_his_usual_card(store, monkeypatch):
    store.add_player(1, STRANGER, "Вася", 5000, NOW - 86400, NOW - 86400)
    from mmrbot import service

    async def fake_player_board(storage, od, chat_id, name, stratz=None, image=None):
        return service.ImageBoard("карточка Васи", b"png", "Вася")

    monkeypatch.setattr(service, "player_board", fake_player_board)
    board = asyncio.run(lookup_board(store, FakeOD(), 1, f"dotabuff.com/players/{STRANGER}"))
    assert board.kind == "player" and board.tracked and board.text == "карточка Васи"


def test_bare_number_falls_back_to_match_when_no_such_player(store):
    od = FakeOD(matches={5_000_000: _od_match(5_000_000)})
    board = asyncio.run(lookup_board(store, od, 1, "5000000", image=False))
    assert board.kind == "match" and board.match_id == 5_000_000
    assert od.calls.index(("profile", 5_000_000)) < od.calls.index(("match", 5_000_000))


def test_match_link_goes_straight_to_match(store):
    od = FakeOD(matches={9042174049: _od_match(9042174049)})
    board = asyncio.run(lookup_board(store, od, 1, "https://www.dotabuff.com/matches/9042174049", image=False))
    assert board.kind == "match" and board.match_id == 9042174049 and ("profile", 9042174049) not in od.calls


def test_nothing_found_is_a_clear_message(store):
    board = asyncio.run(lookup_board(store, FakeOD(), 1, "5000000", image=False))
    assert board.kind is None and "ни игрока, ни матча" in board.text
    bad = asyncio.run(lookup_board(store, FakeOD(), 1, "привет"))
    assert bad.kind is None and "ID матча" in bad.text


def test_repeated_lookup_is_served_from_cache(store):
    od = FakeOD(players={STRANGER: {"personaname": "genocide in hell", "rank_tier": 63}})
    asyncio.run(lookup_board(store, od, 1, str(STRANGER), image=False))
    first = len(od.calls)
    again = asyncio.run(lookup_board(store, od, 1, f"dotabuff.com/players/{STRANGER}", image=False))
    assert again.kind == "player" and len(od.calls) == first  # второй поиск — без запросов к OpenDota


def test_find_cooldown_per_person(monkeypatch):
    pytest.importorskip("aiogram.filters")
    from types import SimpleNamespace

    import mmrbot.bot as botmod
    clock = [1000.0]
    monkeypatch.setattr(botmod.time, "monotonic", lambda: clock[0])
    botmod._last_find.clear()
    vasya, petya = SimpleNamespace(id=1), SimpleNamespace(id=2)
    assert botmod._find_wait(5, vasya) == 0 and botmod._find_wait(5, petya) == 0
    clock[0] += 3
    assert botmod._find_wait(5, vasya) == pytest.approx(botmod.FIND_COOLDOWN - 3)
    assert botmod._find_wait(6, vasya) == 0  # другой чат — свой счётчик
    clock[0] += botmod.FIND_COOLDOWN
    assert botmod._find_wait(5, vasya) == 0 and botmod._find_wait(5, None) == 0


def test_medal_mmr_text():
    assert cd.medal_mmr_text(71) == " · ≈4620–4774" and cd.medal_mmr_text(80) == " · ≈5620+"
    assert cd.medal_mmr_text(None) == "" and cd.medal_mmr_text(0) == ""


def test_lookup_card_numbers_recent_games_for_buttons(store):
    od = FakeOD(players={STRANGER: {"personaname": "x", "rank_tier": 63}})
    board = asyncio.run(lookup_board(store, od, 1, str(STRANGER)))
    assert board.match_ids == [9_000_000_000 + i for i in range(6)]  # новые первыми, как на картинке
