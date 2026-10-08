import io

from PIL import Image

from mmrbot import card_data as cd
from mmrbot.achievements import CATALOG
from mmrbot.achievements_image import MAX_PLAYERS, collapse, render_achievements_image
from mmrbot.cards import WIDTH


def _open(png: bytes) -> Image.Image:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(png))


def _player(name="Вася", codes=("win_streak_5", "games_100"), **extra):
    return {"name": name, "avatar": None, "items": [{"code": c, "detail": None} for c in codes], **extra}


def test_collapse_keeps_highest_of_each_series():
    got = collapse([{"code": c} for c in ("win_streak_5", "win_streak_15", "win_streak_10", "games_50", "games_250", "kills_20")])
    assert [i["code"] for i in got] == ["win_streak_15", "games_250", "kills_20"]


def test_every_catalog_code_has_a_badge():
    from mmrbot.achievements_image import badge_of
    for code, ach in CATALOG.items():
        b = badge_of({"code": code, "detail": "Pudge · 12"})
        assert b["big"] and b["label"] and b["anti"] == ach.anti, code


def test_height_grows_with_players_and_anti_row():
    one = _open(render_achievements_image([_player()]))
    three = _open(render_achievements_image([_player(), _player("Петя"), _player("Оля")]))
    anti = _open(render_achievements_image([_player(codes=("win_streak_5", "lose_streak_5"))]))
    assert one.width == three.width == anti.width == WIDTH
    assert three.height > one.height + 2 * 150
    assert anti.height > one.height + 100  # антирекорды — отдельный ряд


def test_many_tiles_wrap_to_second_row():
    codes = ("win_streak_15", "games_1000", "hero_500", "kills_20", "deathless", "marathon")
    seven = _open(render_achievements_image([_player(codes=codes)]))
    two = _open(render_achievements_image([_player(codes=codes[:2])]))
    assert seven.height == two.height  # 6 значков помещаются в один ряд


def test_empty_and_strange_data_render():
    assert _open(render_achievements_image([])).width == WIDTH
    weird = _player("😀" * 3 + "я" * 90, codes=("nope", "hero_50", "deaths_20"), note=None)
    weird["items"][1]["detail"] = "X" * 80
    png = render_achievements_image([weird, _player(codes=())], note="заметка", avatars={})
    assert _open(png).width == WIDTH


def test_player_limit_and_hidden_note():
    many = [_player(f"П{i}") for i in range(MAX_PLAYERS + 3)]
    capped = _open(render_achievements_image(many))
    exact = _open(render_achievements_image(many[:MAX_PLAYERS]))
    assert capped.height > exact.height  # строка «и ещё 3 игрока»
    assert capped.height < exact.height + 80


def test_card_data_builds_players_from_storage_rows():
    rows = [("Вася", {"games_50": (1_700_000_000, "50"), "lose_streak_5": (1_700_000_100, "5"), "junk": (1, None)}),
            ("Петя", {})]
    players = cd.achievements_players(rows, {"Вася": "http://a"}, "UTC")
    assert players[0]["name"] == "Вася" and players[0]["avatar"] == "http://a"
    assert [i["code"] for i in players[0]["items"]] == ["games_50", "lose_streak_5"]  # неизвестный код отброшен
    assert players[1]["items"] == []
    caption = cd.achievements_caption(players)
    assert "Вася" in caption and "1" in caption
