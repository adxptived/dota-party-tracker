"""Аккаунт Steam хранится и опрашивается один раз, сколько бы чатов его ни отслеживало."""
import sqlite3

import pytest

from mmrbot.storage import Storage
from mmrbot.tracker import (
    backfill_opendota,
    build_player_summary,
    detect_new_games,
    detect_steam_changes,
    refresh_chat,
)
from tests.legacy_db import add_match, add_player, make_v2
from tests.test_tracker import FakeOpenDota, od_match

NOW = 1_780_000_000
ACCOUNT = 42


@pytest.fixture
def store(tmp_path):
    return Storage(str(tmp_path / "a.db"))


def _two_chats(store, mmr_a=5000, mmr_b=4000):
    store.get_or_create_chat(1)
    store.get_or_create_chat(2)
    return (store.add_player(1, ACCOUNT, "Вася", mmr_a, NOW - 1000, NOW - 1000),
            store.add_player(2, ACCOUNT, "Василий", mmr_b, NOW - 1000, NOW - 1000))


def _row_count(store, table) -> int:
    with store._conn() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --- хранение ---------------------------------------------------------------

def test_matches_are_stored_once_and_seen_from_every_chat(store):
    first, second = _two_chats(store)
    assert store.add_matches(first.id, [od_match(1, NOW - 500), od_match(2, NOW - 300)]) == 2
    assert store.add_matches(second.id, [od_match(2, NOW - 300), od_match(3, NOW - 100)]) == 1  # матч 2 уже есть
    assert _row_count(store, "matches") == 3
    assert [m["match_id"] for m in store.get_matches(first.id)] == [1, 2, 3]
    assert [m["match_id"] for m in store.get_matches(second.id)] == [1, 2, 3]


def test_account_state_is_shared_but_chat_data_is_not(store):
    first, second = _two_chats(store)
    store.set_player_rank(first.id, 63, None, NOW)
    store.touch_player(first.id, NOW, deep=True)
    store.update_player_steam(first.id, "vasya", "https://avatars.steamstatic.com/a.jpg")
    store.link_user(1, first.id, 777)
    seen = store.get_player(2, "Василий")
    assert (seen.last_rank_tier, seen.updated_ts, seen.history_ts, seen.steam_name) == (63, NOW, NOW, "vasya")
    assert (seen.display_name, seen.anchor_mmr, seen.tg_user_id) == ("Василий", 4000, None)  # своё у каждого чата


def test_mmr_estimate_is_per_chat_over_shared_history(store):
    first, second = _two_chats(store, 5000, 4000)
    store.set_chat_step(2, 30)
    store.add_matches(first.id, [od_match(1, NOW - 500, radiant_win=True), od_match(2, NOW - 300, radiant_win=True)])
    in_first = build_player_summary(store, store.get_or_create_chat(1), store.get_player(1, "Вася"), NOW)
    in_second = build_player_summary(store, store.get_or_create_chat(2), store.get_player(2, "Василий"), NOW)
    assert (in_first.current_mmr, in_second.current_mmr) == (5050, 4060)


def test_removing_from_one_chat_keeps_history_for_the_other(store):
    first, second = _two_chats(store)
    store.add_matches(first.id, [od_match(1, NOW - 500)])
    assert store.remove_player(1, "Вася")
    assert store.get_matches(first.id) == []  # удалённый игрок истории не видит
    assert [m["match_id"] for m in store.get_matches(second.id)] == [1]
    assert store.remove_player(2, "Василий")  # последний — история и аккаунт уходят
    assert _row_count(store, "matches") == _row_count(store, "accounts") == _row_count(store, "pending_notices") == 0


def test_readded_account_starts_clean(store):
    store.get_or_create_chat(1)
    player = store.add_player(1, ACCOUNT, "Вася", None, 0, 0)
    store.add_matches(player.id, [od_match(1, NOW - 500)])
    store.set_player_rank(player.id, 63, None, NOW)
    store.remove_player(1, "Вася")
    again = store.add_player(1, ACCOUNT, "Вася", None, 0, 0)
    assert again.last_rank_tier is None and again.updated_ts is None and store.get_matches(again.id) == []


def test_supergroup_migration_clash_keeps_shared_history(store):
    store.get_or_create_chat(-5)
    old = store.add_player(-5, ACCOUNT, "Вася", 5000, 0, 0)
    store.add_matches(old.id, [od_match(1, NOW - 500)])
    store.get_or_create_chat(-1005)
    store.add_player(-1005, ACCOUNT, "Дубль", None, 0, 0)  # под новым id успели добавить тот же аккаунт
    assert store.migrate_chat(-5, -1005)
    players = store.list_players(-1005)
    assert [(p.id, p.display_name) for p in players] == [(old.id, "Вася")]
    assert [m["match_id"] for m in store.get_matches(old.id)] == [1]


def test_backlog_counts_shared_account_once(store):
    first, _ = _two_chats(store)
    store.add_matches(first.id, [od_match(1, NOW - 500), od_match(2, NOW - 300)])
    assert store.backlog_counts(0) == {"details": 2, "stratz": 2}
    store.set_chat_active(1, False)
    assert store.backlog_counts(0)["details"] == 2  # второй чат активен — очередь остаётся
    store.set_chat_active(2, False)
    assert store.backlog_counts(0)["details"] == 0


# --- опрос: один раз на аккаунт ------------------------------------------------

def test_second_chat_does_not_refetch_fresh_account(store):
    _two_chats(store)
    client = FakeOpenDota(matches=[od_match(1, NOW - 500)])
    refresh_chat(store, client, 1, NOW)
    calls = client.match_calls
    assert calls >= 1
    refresh_chat(store, client, 2, NOW + 10)  # аккаунт только что обновлён из первого чата
    assert client.match_calls == calls
    assert [m["match_id"] for m in store.get_matches(store.get_player(2, "Василий").id)] == [1]


def test_details_are_fetched_once_for_shared_account(store):
    first, _ = _two_chats(store)
    store.add_matches(first.id, [od_match(1, NOW - 500)])
    client = FakeOpenDota(match_stats={"gpm": 500, "benchmarks": {"gold_per_min": 0.5}})
    asked = []
    client.get_match_player_stats = lambda mid, acc, slot=None: asked.append(mid) or {"gpm": 500, "benchmarks": {}}
    backfill_opendota(store, client, now=NOW)
    assert asked == [1]


def test_new_game_is_announced_in_every_chat_with_one_fetch(store):
    _two_chats(store)
    client = FakeOpenDota(matches=[od_match(7, NOW - 600, radiant_win=True)])
    events_a = detect_new_games(store, client, store.get_or_create_chat(1), NOW)
    calls = client.match_calls
    events_b = detect_new_games(store, client, store.get_or_create_chat(2), NOW + 5)
    assert client.match_calls == calls  # второй чат взял матч из БД
    assert [e["match_id"] for e in events_a] == [e["match_id"] for e in events_b] == [7]
    assert events_a[0]["rows"][0]["name"] == "Вася" and events_b[0]["rows"][0]["name"] == "Василий"
    assert events_a[0]["rows"][0]["current_mmr"] == 5025 and events_b[0]["rows"][0]["current_mmr"] == 4025
    assert detect_new_games(store, client, store.get_or_create_chat(1), NOW + 10) == []  # повтора нет
    assert detect_new_games(store, client, store.get_or_create_chat(2), NOW + 10) == []


def test_unsent_alert_stays_pending_only_for_its_chat(store):
    first, second = _two_chats(store)
    client = FakeOpenDota(matches=[od_match(7, NOW - 600)])
    sent = detect_new_games(store, client, store.get_or_create_chat(1), NOW, mark=False)
    store.mark_notified_matches(sent[0]["pending"])  # первый чат отправил
    failed = detect_new_games(store, client, store.get_or_create_chat(2), NOW + 5, mark=False)  # второй — не смог
    assert failed[0]["pending"] == [(second.id, 7)]
    retry = detect_new_games(store, client, store.get_or_create_chat(2), NOW + 10, mark=False)
    assert [e["match_id"] for e in retry] == [7]
    assert detect_new_games(store, client, store.get_or_create_chat(1), NOW + 10, mark=False) == []


def test_steam_rename_is_reported_to_every_chat(store):
    first, _ = _two_chats(store)
    store.update_player_steam(first.id, "old", "https://avatars.steamstatic.com/a.jpg")
    client = FakeOpenDota(profile={"personaname": "new", "avatarfull": "https://avatars.steamstatic.com/a.jpg",
                                   "rank_tier": 55, "leaderboard_rank": None})
    events = detect_steam_changes(store, client, NOW)
    assert sorted(e["chat_id"] for e in events) == [1, 2]
    assert all(e["changes"]["name"] == ("old", "new") for e in events)
    assert client.profile_calls == 1
    assert detect_steam_changes(store, client, NOW + 10) == []


# --- миграция со схемы «матчи на игрока чата» ------------------------------------

def _legacy_shared_db(path):
    conn = make_v2(path)
    one = add_player(conn, 1, ACCOUNT, "Вася", 5000, 100, 50, last_rank_tier=54, updated_ts=900, profile_ts=900,
                     steam_name="vasya", tg_user_id=77, last_tag="5000 MMR")
    two = add_player(conn, 2, ACCOUNT, "Василий", 4000, 200, 60, last_rank_tier=55, updated_ts=1000, profile_ts=1000,
                     history_ts=1000, fh_unavailable=1)
    solo = add_player(conn, 2, 43, "Петя", None, 0, 0)
    # матч 11 есть у обоих: у первого обогащён OpenDota, у второго — Stratz
    add_match(conn, one, 11, 500, kills=7, gpm=612.0, perf_score=0.7, bench_json='{"gold_per_min": 0.7}', enriched=1,
              notified=1)
    add_match(conn, two, 11, 500, kills=7, position=1, imp=20, party_size=2, stratz_done=1, notified=0)
    add_match(conn, one, 12, 600, win=False, notified=0, enrich_tries=2)   # только в первом чате
    add_match(conn, two, 13, 700, notified=1, enrich_tries=3)              # только во втором
    add_match(conn, solo, 14, 800, notified=1)
    conn.execute("INSERT INTO matches (player_id, match_id, start_time, player_slot, radiant_win) VALUES (999, 15, 1, 0, 1)")
    conn.commit()
    conn.close()
    return one, two, solo


def test_legacy_database_is_merged_by_account(tmp_path):
    path = str(tmp_path / "bot.db")
    one, two, solo = _legacy_shared_db(path)
    store = Storage(path)

    first, second = store.get_player(1, "Вася"), store.get_player(2, "Василий")
    assert (first.id, second.id) == (one, two)  # id игроков чата не меняются
    assert (first.anchor_mmr, first.anchor_ts, first.created_ts, first.tg_user_id, first.last_tag) == (
        5000, 100, 50, 77, "5000 MMR")
    assert (second.anchor_mmr, second.anchor_ts, second.created_ts, second.tg_user_id) == (4000, 200, 60, None)
    # состояние аккаунта — от строки, которую обновляли последней; пустое у неё дополняется из другой
    for player in (first, second):
        assert (player.last_rank_tier, player.updated_ts, player.history_ts, player.fh_unavailable) == (55, 1000, 1000, True)
        assert player.steam_name == "vasya"

    history = store.get_matches(first.id)
    assert [m["match_id"] for m in history] == [11, 12, 13] == [m["match_id"] for m in store.get_matches(second.id)]
    merged = history[0]  # копии матча 11 слились: поля OpenDota и Stratz вместе
    assert (merged["gpm"], merged["perf_score"], merged["enriched"]) == (612.0, 0.7, 1)
    assert (merged["position"], merged["imp"], merged["party_size"], merged["stratz_done"]) == (1, 20, 2, 1)
    assert [m["match_id"] for m in store.get_matches(solo)] == [14]
    with store._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 4  # 11, 12, 13, 14; осиротевший 15 отброшен
        assert "notified" not in {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
        assert "last_rank_tier" not in {r[1] for r in conn.execute("PRAGMA table_info(players)")}


def test_legacy_unnotified_matches_stay_pending_per_chat(tmp_path):
    path = str(tmp_path / "bot.db")
    one, two, solo = _legacy_shared_db(path)
    store = Storage(path)
    assert [m["match_id"] for m in store.get_unnotified_matches(one, 0)] == [12]
    assert [m["match_id"] for m in store.get_unnotified_matches(two, 0)] == [11]
    assert store.get_unnotified_matches(solo, 0) == []
    assert store.announced_match_ids(1, [11, 12, 13]) == {11, 13}  # 13 пришёл уже «объявленным» из общей истории
    assert store.announced_match_ids(2, [11, 12, 13]) == {12, 13}


def test_migrated_database_keeps_working(tmp_path):
    path = str(tmp_path / "bot.db")
    one, two, _ = _legacy_shared_db(path)
    store = Storage(path)
    assert store.add_matches(one, [od_match(20, 2000)]) == 1
    assert [m["match_id"] for m in store.get_unnotified_matches(two, 1500)] == [20]
    before = store.player_data_ver(one)
    store.update_match_details(one, 20, {"gpm": 400, "benchmarks": {}}, 0.4)
    assert store.player_data_ver(one) > before and store.get_matches(two)[-1]["gpm"] == 400
    backup = sqlite3.connect(str(tmp_path / "backups" / "pre-migration-v2-bot.db"))
    assert backup.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 6  # копия до миграции цела
    backup.close()
