"""Билды из матча сохраняются в БД и подставляются, когда API времён не дал."""
import pytest

from mmrbot.storage import Storage
from mmrbot.tracker import persist_builds, restore_builds


@pytest.fixture
def store(tmp_path):
    return Storage(str(tmp_path / "p.db"))


def test_rows_with_builds_are_saved_and_restored(store):
    rows = [{"account_id": 42, "items": [1, 2], "item_times": [300, 400], "shard": True, "shard_time": 900},
            {"account_id": 43}, {"items": [1]}]
    persist_builds(store, 7, rows)
    assert store.get_build(42, 7)["item_times"] == [300, 400] and store.get_build(43, 7) is None

    later = [{"account_id": 42, "items": [1, 2], "item_times": [None, 450], "shard": True, "shard_time": None}]
    restore_builds(store, 7, later)
    assert later[0]["item_times"] == [300, 450] and later[0]["shard_time"] == 900  # своё не затираем, пустое — берём


def test_restore_ignores_other_items_and_fills_bare_rows(store):
    persist_builds(store, 7, [{"account_id": 42, "items": [1, 2], "item_times": [300, 400], "neutral_item": 9}])
    other = [{"account_id": 42, "items": [5], "item_times": [None]}]
    restore_builds(store, 7, other)
    assert other[0]["item_times"] == [None]  # другой билд — времена от прежнего чужие
    bare = [{"account_id": 42}]
    restore_builds(store, 7, bare)
    assert bare[0]["items"] == [1, 2] and bare[0]["neutral_item"] == 9


def test_storage_failure_never_breaks_the_flow():
    class Broken:
        def save_build(self, *a):
            raise RuntimeError("db")

        def get_builds(self, *a):
            raise RuntimeError("db")

    rows = [{"account_id": 1, "items": [1], "item_times": [1]}]
    persist_builds(Broken(), 7, rows)
    restore_builds(Broken(), 7, rows)
    persist_builds(None, 7, rows)
    restore_builds(None, 7, rows)


def test_contest_gets_fast_shard_from_stored_builds(store):
    from mmrbot.tracker import build_contest
    now = 1_780_000_000
    for acc, name, shard in ((1, "Вася", 900), (2, "Петя", 1500)):
        store.add_player(5, acc, name, None, now - 10_000, now)
        player = store.get_player(5, name)
        matches = [{"match_id": acc * 100 + i, "start_time": now - 5000 + i, "player_slot": 0, "radiant_win": True,
                    "lobby_type": 7, "kills": 1, "deaths": 1, "assists": 1} for i in range(3)]
        store.add_matches(player.id, matches)
        for m in matches:
            store.save_build(acc, m["match_id"], {"items": [1], "item_times": [100], "shard": True, "shard_time": shard})
    keys = {n["key"]: n for n in build_contest(store, 5, None)["standings"]}
    assert keys["fast_shard"]["entries"][0]["player"] == "Вася"
