"""Лейнинг и вижн: исход линии игрока, варды и стаки — расчёт, разбор Stratz/OpenDota, хранение, номинации."""
import pytest

from mmrbot.awards import compute_period_awards, compute_standings
from mmrbot.lanes import lane_result, ward_count
from mmrbot.opendota import OpenDota
from mmrbot.storage import Storage
from mmrbot.stratz import Stratz
from tests.test_opendota import FakeSession as OpenDotaSession
from tests.test_stratz import FakeSession as StratzSession

T0 = 1_780_000_000
OUT = {"top": "RADIANT_VICTORY", "mid": "DIRE_STOMP", "bottom": "TIE"}


# --- исход линии с точки зрения игрока --------------------------------------------------

@pytest.mark.parametrize("lane,radiant,expected", [
    ("OFF_LANE", True, 1),       # свет, оффлейн = верх: победа света
    ("SAFE_LANE", False, -1),    # тьма, лёгкая линия = верх: тот же исход, но для тьмы это поражение
    ("MID_LANE", True, -2),      # центр: тьма раздавила свет
    ("MID_LANE", False, 2),
    ("SAFE_LANE", True, 0),      # свет, лёгкая линия = низ: ничья
    ("OFF_LANE", False, 0),      # тьма, оффлейн = низ
])
def test_lane_result_follows_side_and_lane(lane, radiant, expected):
    assert lane_result(lane, radiant, OUT) == expected


def test_lane_result_unknown_when_no_lane_or_no_outcome():
    assert lane_result("ROAMING", True, OUT) is None and lane_result("JUNGLE", False, OUT) is None
    assert lane_result("UNKNOWN", True, OUT) is None and lane_result(None, True, OUT) is None
    assert lane_result("MID_LANE", True, {}) is None
    assert lane_result("MID_LANE", True, {"mid": "NOT_A_RESULT"}) is None
    assert lane_result("MID_LANE", None, OUT) is None


def test_ward_count_is_none_without_data():
    assert ward_count({"wards": [{"time": 1}, {"time": 70}]}) == 2
    assert ward_count({"wards": []}) == 0
    assert ward_count({}) is None and ward_count(None) is None and ward_count({"wards": None}) is None


# --- Stratz ------------------------------------------------------------------------------

def _stratz_match(lane="SAFE_LANE", radiant=True, wards=3):
    return {
        "lobbyType": "RANKED", "topLaneOutcome": "DIRE_VICTORY", "midLaneOutcome": "TIE",
        "bottomLaneOutcome": "RADIANT_STOMP",
        "players": [{
            "steamAccountId": 42, "isRadiant": radiant, "heroId": 1, "position": "POSITION_5", "role": "SUPPORT",
            "lane": lane, "imp": 3, "stats": {"wards": [{"time": 30 * i} for i in range(wards)]},
        }],
    }


def test_stratz_returns_lane_result_and_wards():
    session = StratzSession([{"data": {"m0": _stratz_match(), "m1": _stratz_match("OFF_LANE", False, 0),
                                       "m2": _stratz_match("JUNGLE")}}])
    result = Stratz("key", session=session, min_interval=0).get_matches(42, [1, 2, 3])
    assert (result[1]["lane_result"], result[1]["wards"]) == (2, 3)    # свет, низ: сокрушительная победа
    assert (result[2]["lane_result"], result[2]["wards"]) == (-2, 0)   # тьма, оффлейн = низ: свет раздавил низ
    assert result[3]["lane_result"] is None and result[3]["wards"] == 3


def test_stratz_query_asks_for_lane_outcomes_and_wards():
    session = StratzSession([{"data": {"m0": None}}])
    Stratz("key", session=session, min_interval=0).get_matches(42, [1])
    query = session.calls[0]["json"]["query"]
    assert "topLaneOutcome" in query and "midLaneOutcome" in query and "bottomLaneOutcome" in query
    assert "wards" in query


# --- OpenDota: стаки только из разобранного матча ----------------------------------------

def _od_match(parsed, stacked):
    me = {"account_id": 42, "player_slot": 0, "hero_id": 1, "camps_stacked": stacked, "obs_placed": 5}
    body = {"players": [me] + [{"player_slot": s, "hero_id": 2 + s} for s in (1, 2, 3, 4, 128, 129, 130, 131, 132)]}
    if parsed:
        body["version"] = 21
    return OpenDota(session=OpenDotaSession(body), min_interval=0)


def test_stacks_come_from_parsed_match_only():
    assert _od_match(True, 4).get_match_player_stats(7, 42)["stacks"] == 4
    assert _od_match(True, 0).get_match_player_stats(8, 42)["stacks"] == 0
    # в неразобранном матче OpenDota отдаёт пустые счётчики — нулём их считать нельзя
    assert _od_match(False, 0).get_match_player_stats(9, 42)["stacks"] is None
    assert _od_match(True, None).get_match_player_stats(10, 42)["stacks"] is None


# --- хранение -----------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    storage = Storage(str(tmp_path / "l.db"))
    storage.get_or_create_chat(1)
    return storage


def _game(match_id, **extra):
    return {"match_id": match_id, "start_time": T0 + match_id, "player_slot": 0, "radiant_win": True, "lobby_type": 7,
            "hero_id": 1, "kills": 1, "deaths": 1, "assists": 1, "duration": 1800, **extra}


def test_stratz_info_is_stored_and_not_overwritten_by_empty(store):
    player = store.add_player(1, 42, "Вася", None, T0, T0)
    store.add_matches(player.id, [_game(1)])
    store.update_match_stratz(player.id, 1, {"position": 5, "lane": "SAFE_LANE", "lane_result": 2, "wards": 7})
    row = store.get_matches(player.id)[0]
    assert (row["lane_result"], row["wards"], row["stacks"]) == (2, 7, None)
    store.update_match_stratz(player.id, 1, {"position": 5, "lane": "SAFE_LANE"})  # повторный ответ без новых полей
    row = store.get_matches(player.id)[0]
    assert (row["lane_result"], row["wards"]) == (2, 7)


def test_opendota_stacks_are_stored_and_do_not_erase_stratz_fields(store):
    player = store.add_player(1, 42, "Вася", None, T0, T0)
    store.add_matches(player.id, [_game(1)])
    store.update_match_stratz(player.id, 1, {"lane_result": -1, "wards": 4})
    store.update_match_details(player.id, 1, {"gpm": 400, "stacks": 3}, None)
    row = store.get_matches(player.id)[0]
    assert (row["stacks"], row["wards"], row["lane_result"]) == (3, 4, -1)


# --- номинации ------------------------------------------------------------------------------

def g(t, **extra):
    return {"start_time": t, "player_slot": 0, "radiant_win": True, "kills": 2, "deaths": 2, "assists": 8, **extra}


def standing(standings, key):
    return next((s for s in standings if s["key"] == key), None)


def test_ward_stack_and_lane_nominations():
    support = [g(i, wards=14, stacks=2, lane_result=-1) for i in range(1, 4)]
    carry = [g(i, wards=3, stacks=0, lane_result=2) for i in range(1, 4)]
    standings = compute_standings([("Саппорт", support), ("Кор", carry)])
    wards, stacks, lanes = standing(standings, "wards"), standing(standings, "stacks"), standing(standings, "lane")
    assert wards["entries"][0]["player"] == "Саппорт" and "14.0" in wards["entries"][0]["text"]
    assert stacks["entries"][0]["player"] == "Саппорт"
    assert lanes["entries"][0]["player"] == "Кор" and "100%" in lanes["entries"][0]["text"]


def test_nominations_need_data_from_two_players_and_enough_samples():
    with_data = [g(i, wards=10) for i in range(1, 4)]
    no_data = [g(i) for i in range(1, 4)]
    assert standing(compute_standings([("A", with_data), ("B", no_data)]), "wards") is None  # сравнивать не с кем
    thin = [g(1, wards=30), g(2), g(3)]  # один матч с данными из трёх — это не «в среднем 30», игрок в сравнение не идёт
    assert standing(compute_standings([("A", thin), ("B", with_data)]), "wards") is None


def test_zero_wards_do_not_make_a_nomination_winner():
    standings = compute_standings([("A", [g(i, wards=0) for i in range(1, 4)]), ("B", [g(i, wards=0) for i in range(1, 4)])])
    assert standing(standings, "wards") is None


def test_period_awards_include_new_keys():
    support = [g(i, wards=12, stacks=3, lane_result=1) for i in range(1, 4)]
    carry = [g(i, wards=2, stacks=0, lane_result=-2) for i in range(1, 4)]
    keys = {a["key"] for a in compute_period_awards([("С", support), ("К", carry)])}
    assert {"wards", "stacks", "lane"} <= keys
