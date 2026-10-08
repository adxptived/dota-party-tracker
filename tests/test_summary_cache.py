"""B3 (сводки): PlayerSummary кэшируется по версии данных игрока, настройкам чата и дню."""

import pytest

import mmrbot.tracker as tracker
from mmrbot.storage import Storage

NOW = 1_760_000_000


def _m(mid, start, win=True):
    return {"match_id": mid, "start_time": start, "player_slot": 0, "radiant_win": win, "lobby_type": 7,
            "kills": 3, "deaths": 2, "assists": 5}


@pytest.fixture
def env(tmp_path):
    storage = Storage(str(tmp_path / "s.db"))
    storage.get_or_create_chat(1)
    player = storage.add_player(1, 100, "Вася", 4000, NOW - 99999, NOW - 99999)
    storage.add_matches(player.id, [_m(i, NOW - 5000 + i) for i in range(1, 8)])
    reads = []
    original = storage.get_matches
    storage.get_matches = lambda *a, **kw: (reads.append(1), original(*a, **kw))[1]
    tracker._SUMMARIES.clear()
    return storage, player, reads


def build(storage, player, now=NOW):
    return tracker.build_player_summary(storage, storage.get_or_create_chat(1), storage.get_player(1, str(player.account_id)), now)


def test_repeat_call_is_served_from_cache(env):
    storage, player, reads = env
    first = build(storage, player)
    second = build(storage, player, NOW + 60)  # та же локальная дата
    assert second is first and len(reads) == 1


def test_new_match_recomputes(env):
    storage, player, reads = env
    before = build(storage, player)
    storage.add_matches(player.id, [_m(99, NOW - 10)])
    after = build(storage, player)
    assert after is not before and after.games_total == before.games_total + 1 and len(reads) == 2


def test_chat_settings_and_player_fields_are_part_of_key(env):
    storage, player, reads = env
    first = build(storage, player)
    storage.set_chat_step(1, 30)
    assert build(storage, player) is not first
    storage.set_chat_tz(1, "Asia/Tokyo")
    build(storage, player)
    storage.set_player_anchor(player.id, 4500, NOW - 99999)
    assert build(storage, player).anchor_mmr == 4500
    storage.set_player_rank(player.id, 55, None, NOW)
    assert build(storage, player).rank != first.rank


def test_next_day_recomputes(env):
    storage, player, reads = env
    first = build(storage, player)
    assert build(storage, player, NOW + 2 * 86400) is not first


def test_cache_is_bounded(env):
    storage, player, reads = env
    for n in range(tracker.SUMMARY_CACHE_LIMIT + 20):
        build(storage, player, NOW + n * 86400)
    assert len(tracker._SUMMARIES) <= tracker.SUMMARY_CACHE_LIMIT
