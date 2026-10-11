"""Билды игроков (предметы и времена покупок) хранятся в БД: /last и сводки не зависят от кэша и API."""
import pytest

from mmrbot.storage import Storage

T0 = 1_780_000_000
BUILD = {"items": [1, 2], "item_times": [300, None], "neutral_item": 9, "shard": True, "shard_time": 1450,
         "scepter": False, "scepter_time": None}


@pytest.fixture
def store(tmp_path):
    return Storage(str(tmp_path / "b.db"))


def test_build_roundtrip(store):
    assert store.get_build(42, 7) is None
    store.save_build(42, 7, BUILD)
    assert store.get_build(42, 7) == BUILD
    assert store.get_builds(42, [7, 8]) == {7: BUILD}


def test_build_with_more_known_times_wins(store):
    store.save_build(42, 7, BUILD)
    poorer = dict(BUILD, item_times=[None, None], shard_time=None)
    store.save_build(42, 7, poorer)
    assert store.get_build(42, 7) == BUILD  # без времён лучший билд не затираем
    richer = dict(BUILD, item_times=[300, 800])
    store.save_build(42, 7, richer)
    assert store.get_build(42, 7) == richer


def test_bad_build_is_ignored(store):
    store.save_build(42, 7, {})
    store.save_build(42, 8, {"items": []})
    assert store.get_builds(42, [7, 8]) == {}


def test_builds_are_removed_with_the_last_tracker_of_the_account(store):
    player = store.add_player(1, 42, "Вася", None, T0, T0)
    store.save_build(42, 7, BUILD)
    store.remove_player(1, "Вася")
    assert store.get_build(42, 7) is None
