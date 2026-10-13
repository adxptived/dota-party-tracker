"""Справочник талантов и выбранные в матче таланты."""
import pytest

from mmrbot import talents
from mmrbot.opendota import _player_build

ABILITY_IDS = {str(5000 + i): f"special_bonus_sf_{i}" for i in range(8)}
ABILITY_IDS.update({"6000": "special_bonus_jugg_x", "bad": "special_bonus_sf_0", "7000": "nevermore_shadowraze1"})
ABILITIES = {f"special_bonus_sf_{i}": {"dname": f"SF talent {i}"} for i in range(8)}
ABILITIES["special_bonus_sf_7"] = {"dname": "+{s:bonus_healing_ward_bonus_health} Healing Ward Hits to Kill"}
HERO_ABILITIES = {
    "npc_dota_hero_nevermore": {"talents": [{"name": f"special_bonus_sf_{i}", "level": i // 2 + 1} for i in range(8)]},
    "npc_dota_hero_juggernaut": {"talents": [{"name": "special_bonus_jugg_x", "level": 4}]},  # неполное дерево
    "junk": None,
}


@pytest.fixture
def table():
    saved = dict(talents.TALENTS), dict(talents.TREES)
    talents.TALENTS.clear()
    talents.TREES.clear()
    talents.update_talents(talents.build_talents(ABILITY_IDS, ABILITIES, HERO_ABILITIES))
    yield
    talents.TALENTS.clear()
    talents.TREES.clear()
    talents.TALENTS.update(saved[0])
    talents.TREES.update(saved[1])


def test_placeholders_are_dropped_from_names():
    assert talents.talent_name("+{s:bonus_healing_ward_heal_amount}% Healing Ward Heal") == "Healing Ward Heal"
    assert talents.talent_name("-{s:bonus_AbilityCooldown}s Blade Fury Cooldown") == "Blade Fury Cooldown"
    assert talents.talent_name("+300 Health") == "+300 Health" and talents.talent_name(None) == ""


def test_build_keeps_full_trees_with_sides(table):
    assert set(talents.TREES) == {"npc_dota_hero_nevermore"}  # у Джаггернаута в данных неполное дерево
    assert talents.TREES["npc_dota_hero_nevermore"][0] == ["SF talent 0", "SF talent 1"]  # [правый, левый]
    assert talents.TREES["npc_dota_hero_nevermore"][3][1] == "Healing Ward Hits to Kill"
    assert talents.TALENTS[5000] == ("npc_dota_hero_nevermore", 1, "right")
    assert talents.TALENTS[5003] == ("npc_dota_hero_nevermore", 2, "left") and 6000 not in talents.TALENTS


def test_tree_from_upgrades_has_both_options_and_picked_side(table):
    tree = talents.talent_tree([7000, 5001, 7000, 5002, 5005, 5004, True, "x", None, 999])
    assert [r["level"] for r in tree] == [10, 15, 20, 25]
    assert tree[0] == {"level": 10, "right": "SF talent 0", "left": "SF talent 1", "pick": "left"}
    assert tree[1]["pick"] == "right" and tree[2]["pick"] == "left" and tree[3]["pick"] is None  # 25 не взят
    assert talents.talent_tree([7000]) == [] and talents.talent_tree(None) == []


def test_tree_rows_cleans_junk_and_reads_old_format():
    tree = [{"level": 10, "left": "a", "right": "b", "pick": "left"}, {"level": 99}, "junk", None]
    rows = talents.tree_rows(tree)
    assert [r["level"] for r in rows] == [10, 15, 20, 25] and rows[0]["pick"] == "left" and rows[1]["pick"] is None
    assert talents.tree_rows([{"level": 10, "left": "a", "right": "b", "pick": None}]) == []  # ничего не выбрано
    old = talents.tree_rows([[10, "+20 Damage"], [25, "x"]])
    assert old[0] == {"level": 10, "left": "+20 Damage", "right": "", "pick": "left"} and old[3]["pick"] == "left"


def test_opendota_build_carries_tree(table):
    build = _player_build({"item_0": 1, "ability_upgrades_arr": [7000, 5000, 5004]})
    assert build["talents"][0]["pick"] == "right" and build["talents"][2]["pick"] == "right"


def test_save_and_load_roundtrip(table, tmp_path):
    path = str(tmp_path / "t" / "talents.json")
    talents.save_talents(path)
    before = dict(talents.TALENTS), dict(talents.TREES)
    talents.TALENTS.clear()
    talents.TREES.clear()
    assert talents.load_talents(path) == 8 and (talents.TALENTS, talents.TREES) == before
    assert talents.load_talents(str(tmp_path / "nope.json")) == 0


def test_refresh_talents_uses_three_constants(table):
    from mmrbot.tracker import refresh_talents

    class OD:
        def get_talent_constants(self):
            return ABILITY_IDS, ABILITIES, HERO_ABILITIES

    talents.TALENTS.clear()
    assert refresh_talents(OD()) == 8


def test_storage_keeps_talents_and_upgrades_old_build(tmp_path):
    from mmrbot.storage import Storage
    store = Storage(str(tmp_path / "b.db"))
    build = {"items": [1, 2], "item_times": [60, None]}
    tree = [{"level": 10, "left": "a", "right": "b", "pick": "left"}]
    store.save_build(7, 100, build)
    store.save_build(7, 100, dict(build, talents=tree))  # те же времена, но появились таланты
    assert store.get_build(7, 100)["talents"] == tree


def test_sides_match_the_game_for_shadow_fiend():
    """Сверено с таблицей талантов Liquipedia: на 10 уровне слева «+30 Feast of Souls attack speed»,
    справа «+30 Shadowraze stack damage»; в константах OpenDota ступень начинается с правого."""
    ids = {"1": "special_bonus_unique_nevermore_7", "2": "special_bonus_unique_nevermore_4"}
    names = {"special_bonus_unique_nevermore_7": {"dname": "+30 Shadowraze Stack Damage"},
             "special_bonus_unique_nevermore_4": {"dname": "+30 Feast of Souls Attack Speed"}}
    hero = {"npc_dota_hero_nevermore": {"talents": [
        {"name": "special_bonus_unique_nevermore_7", "level": 1}, {"name": "special_bonus_unique_nevermore_4", "level": 1},
        *({"name": f"x{i}", "level": i // 2 + 2} for i in range(6))]}}
    built = talents.build_talents(ids, names, hero)
    assert built["trees"]["npc_dota_hero_nevermore"][0] == ["+30 Shadowraze Stack Damage", "+30 Feast of Souls Attack Speed"]
    assert built["talents"][2] == ["npc_dota_hero_nevermore", 1, "left"]
