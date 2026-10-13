"""Справочник талантов и выбранные в матче таланты."""
import pytest

from mmrbot import talents
from mmrbot.opendota import _player_build

ABILITY_IDS = {"5000": "special_bonus_unique_nevermore_7", "5001": "special_bonus_unique_nevermore_4",
               "5002": "special_bonus_hp_300", "5003": "special_bonus_unique_juggernaut_2", "5004": "nevermore_shadowraze1",
               "bad": "special_bonus_hp_300"}
ABILITIES = {"special_bonus_unique_nevermore_7": {"dname": "+30 Shadowraze Stack Damage"},
             "special_bonus_unique_nevermore_4": {"dname": "+30 Feast of Souls Attack Speed"},
             "special_bonus_hp_300": {"dname": "+300 Health"},
             "special_bonus_unique_juggernaut_2": {"dname": "+{s:bonus_healing_ward_bonus_health} Healing Ward Hits to Kill"},
             "nevermore_shadowraze1": {"dname": "Shadowraze"}}
HERO_ABILITIES = {
    "npc_dota_hero_nevermore": {"talents": [{"name": "special_bonus_unique_nevermore_7", "level": 1},
                                            {"name": "special_bonus_unique_nevermore_4", "level": 1},
                                            {"name": "special_bonus_hp_300", "level": 3}]},
    "npc_dota_hero_juggernaut": {"talents": [{"name": "special_bonus_unique_juggernaut_2", "level": 4}]},
    "junk": None,
}


@pytest.fixture
def table():
    saved = dict(talents.TALENTS)
    talents.TALENTS.clear()
    talents.update_talents(talents.build_talents(ABILITY_IDS, ABILITIES, HERO_ABILITIES))
    yield
    talents.TALENTS.clear()
    talents.TALENTS.update(saved)


def test_placeholders_are_dropped_from_names():
    assert talents.talent_name("+{s:bonus_healing_ward_heal_amount}% Healing Ward Heal") == "Healing Ward Heal"
    assert talents.talent_name("-{s:bonus_AbilityCooldown}s Blade Fury Cooldown") == "Blade Fury Cooldown"
    assert talents.talent_name("+300 Health") == "+300 Health" and talents.talent_name(None) == ""


def test_build_keeps_only_talents_with_tier(table):
    assert talents.TALENTS == {5000: (1, "+30 Shadowraze Stack Damage"), 5001: (1, "+30 Feast of Souls Attack Speed"),
                               5002: (3, "+300 Health"), 5003: (4, "Healing Ward Hits to Kill")}


def test_picks_are_ordered_by_level_one_per_tier(table):
    upgrades = [5004, 5004, 5002, 5000, 5001, 5004, 5003, True, "x", None, 999]
    assert talents.talent_picks(upgrades) == [[10, "+30 Shadowraze Stack Damage"], [20, "+300 Health"],
                                              [25, "Healing Ward Hits to Kill"]]
    assert talents.talent_picks(None) == []


def test_opendota_build_carries_talents(table):
    build = _player_build({"item_0": 1, "ability_upgrades_arr": [5004, 5000, 5002]})
    assert build["talents"] == [[10, "+30 Shadowraze Stack Damage"], [20, "+300 Health"]]


def test_save_and_load_roundtrip(table, tmp_path):
    path = str(tmp_path / "t" / "talents.json")
    talents.save_talents(path)
    before = dict(talents.TALENTS)
    talents.TALENTS.clear()
    assert talents.load_talents(path) == 4 and talents.TALENTS == before
    assert talents.load_talents(str(tmp_path / "nope.json")) == 0


def test_refresh_talents_uses_three_constants(table):
    from mmrbot.tracker import refresh_talents

    class OD:
        def get_talent_constants(self):
            return ABILITY_IDS, ABILITIES, dict(HERO_ABILITIES, npc_dota_hero_x={"talents": [
                {"name": "special_bonus_hp_300", "level": 3}]})

    talents.TALENTS.clear()
    assert refresh_talents(OD()) == 4


def test_storage_keeps_talents_and_upgrades_old_build(tmp_path):
    from mmrbot.storage import Storage
    store = Storage(str(tmp_path / "b.db"))
    build = {"items": [1, 2], "item_times": [60, None]}
    store.save_build(7, 100, build)
    store.save_build(7, 100, dict(build, talents=[[10, "+300 Health"]]))  # те же времена, но появились таланты
    assert store.get_build(7, 100)["talents"] == [[10, "+300 Health"]]
