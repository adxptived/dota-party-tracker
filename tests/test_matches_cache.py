"""B3: история матчей игрока кэшируется по «версии данных» players.data_ver — повторное чтение не ходит в БД за строками."""
import time

import pytest

from mmrbot.storage import Storage

NOW = int(time.time())


def _m(mid, start, **extra):
    row = {"match_id": mid, "start_time": start, "player_slot": 0, "radiant_win": True, "lobby_type": 7,
           "kills": 1, "deaths": 1, "assists": 1}
    row.update(extra)
    return row


class Spy:
    """Считает SELECT'ы строк матчей: именно они — цена отчёта у игрока с большой историей."""

    def __init__(self, storage):
        self.statements = []
        original = storage._conn

        def conn():
            c = original()
            c.set_trace_callback(self.statements.append)
            return c

        storage._conn = conn

    def row_reads(self):
        return sum(1 for s in self.statements if "FROM matches" in s and s.lstrip().upper().startswith("SELECT *"))

    def reset(self):
        self.statements.clear()


@pytest.fixture
def env(tmp_path):
    storage = Storage(str(tmp_path / "c.db"))
    storage.get_or_create_chat(1)
    player = storage.add_player(1, 100, "Вася", 4000, NOW - 9999, NOW - 9999)
    storage.add_matches(player.id, [_m(i, NOW - 1000 + i) for i in range(1, 6)])
    return storage, player, Spy(storage)


def test_second_read_does_not_touch_match_rows(env):
    storage, player, spy = env
    first = storage.get_matches(player.id)
    spy.reset()
    again = storage.get_matches(player.id)
    assert again == first and len(first) == 5
    assert spy.row_reads() == 0


def test_since_ts_is_sliced_from_cache_and_equals_db(env):
    storage, player, spy = env
    storage.get_matches(player.id)
    spy.reset()
    cut = NOW - 1000 + 3
    got = storage.get_matches(player.id, since_ts=cut)
    assert [m["match_id"] for m in got] == [3, 4, 5]
    assert spy.row_reads() == 0


def test_new_match_invalidates(env):
    storage, player, spy = env
    storage.get_matches(player.id)
    storage.add_matches(player.id, [_m(9, NOW - 100)])
    assert [m["match_id"] for m in storage.get_matches(player.id)][-1] == 9


def test_readding_same_matches_keeps_cache(env):
    storage, player, spy = env
    storage.get_matches(player.id)
    storage.add_matches(player.id, [_m(i, NOW - 1000 + i) for i in range(1, 6)])
    spy.reset()
    storage.get_matches(player.id)
    assert spy.row_reads() == 0


def test_fill_of_empty_field_invalidates(env):
    storage, player, spy = env
    assert storage.get_matches(player.id)[0]["duration"] is None
    storage.add_matches(player.id, [_m(1, NOW - 999, duration=2400)])
    assert storage.get_matches(player.id)[0]["duration"] == 2400


def test_details_and_stratz_updates_invalidate(env):
    storage, player, spy = env
    storage.get_matches(player.id)
    storage.update_match_stratz(player.id, 2, {"position": 3, "role": "core", "lane": "mid", "imp": 12})
    row = next(m for m in storage.get_matches(player.id) if m["match_id"] == 2)
    assert row["position"] == 3 and row["imp"] == 12
    storage.update_match_details(player.id, 3, {"gpm": 555}, 1.5)
    row = next(m for m in storage.get_matches(player.id) if m["match_id"] == 3)
    assert row["gpm"] == 555 and row["perf_score"] == 1.5


def test_bookkeeping_updates_keep_cache(env):
    storage, player, spy = env
    storage.get_matches(player.id)
    storage.mark_enrich_miss(player.id, 1)
    storage.mark_notified(player.id)
    spy.reset()
    storage.get_matches(player.id)
    assert spy.row_reads() == 0


def test_returned_list_is_a_copy(env):
    storage, player, spy = env
    rows = storage.get_matches(player.id)
    rows.clear()
    assert len(storage.get_matches(player.id)) == 5


def test_remove_player_drops_history(env):
    storage, player, spy = env
    storage.get_matches(player.id)
    storage.remove_player(1, "Вася")
    assert storage.get_matches(player.id) == []


def test_old_database_gets_data_ver_column(tmp_path):
    from tests.legacy_db import make_v0
    path = str(tmp_path / "old.db")
    make_v0(path).close()  # база до «версии данных»: ни колонки, ни триггеров
    storage = Storage(path)
    storage.get_or_create_chat(1)
    player = storage.add_player(1, 1, "A", None, NOW, NOW)
    storage.add_matches(player.id, [_m(1, NOW)])
    assert len(storage.get_matches(player.id)) == 1


def test_cache_is_bounded(tmp_path):
    storage = Storage(str(tmp_path / "b.db"))
    storage.get_or_create_chat(1)
    storage.MATCH_CACHE_ROWS = 10
    ids = []
    for n in range(4):
        p = storage.add_player(1, 100 + n, f"P{n}", None, NOW, NOW)
        storage.add_matches(p.id, [_m(i, NOW - 500 + i) for i in range(1, 5)])
        ids.append(p.id)
        storage.get_matches(p.id)
    assert sum(len(v[1]) for v in storage._matches_cache.values()) <= 10


def test_unnotified_query_does_not_scan_history(env):
    """B9: поиск кандидатов на оповещение идёт от очереди pending_notices, а не сканирует историю матчей."""
    storage, player, _ = env
    with storage._conn() as conn:
        plan = " ".join(r[3] for r in conn.execute(
            "EXPLAIN QUERY PLAN SELECT m.* FROM pending_notices n JOIN players p ON p.id = n.player_id "
            "JOIN matches m ON m.account_id = p.account_id AND m.match_id = n.match_id "
            "WHERE n.player_id = ? AND m.start_time + COALESCE(m.duration, 0) >= ? ORDER BY m.start_time",
            (player.id, 0)))
    assert "SCAN m" not in plan and "SCAN matches" not in plan
    assert "SEARCH n" in plan


def test_light_selects_use_warm_cache_and_stay_correct(env):
    storage, player, spy = env
    cold = storage.get_outcomes(player.id)
    assert spy.row_reads() == 0 and len(cold) == 5  # холодный кэш: узкий запрос, историю целиком не грузим
    storage.get_matches(player.id)
    spy.reset()
    warm = storage.get_outcomes(player.id)
    sides = storage.get_match_sides(player.id, since_ts=NOW - 1000 + 3)
    assert not any("FROM matches" in s for s in spy.statements)
    assert warm == cold and set(warm[0]) == {"start_time", "player_slot", "radiant_win"}
    assert [m["match_id"] for m in sides] == [3, 4, 5] and "kills" not in sides[0]
    storage.add_matches(player.id, [_m(9, NOW - 100)])
    assert len(storage.get_outcomes(player.id)) == 6  # новая игра — кэш не отдаёт устаревшее
