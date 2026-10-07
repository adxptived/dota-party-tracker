import io
from types import SimpleNamespace

from PIL import Image

from mmrbot import card_data as cd
from mmrbot.cards import WIDTH
from mmrbot.heroes_image import LIMIT, render_hero_image, render_party_heroes_image, render_player_heroes_image


def _open(png: bytes) -> Image.Image:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(png))


def _hero(hero_id=1, **extra):
    row = {"hero_id": hero_id, "name": f"Hero {hero_id}", "games": 12, "wins": 8, "losses": 4, "winrate": 8 / 12,
           "kda": 3.4, "imp": 7.5, "gpm": 560}
    row.update(extra)
    return row


def _role(position=1, **extra):
    row = {"position": position, "label": "Керри", "games": 10, "wins": 6, "losses": 4, "winrate": 0.6, "kda": 3.1}
    row.update(extra)
    return row


def test_player_heroes_grows_with_rows_and_roles():
    one = _open(render_player_heroes_image("Герои · Вася", None, ("ВСЁ ВРЕМЯ", "#3987e5"), [_hero()]))
    five = _open(render_player_heroes_image("Герои · Вася", None, None, [_hero(i) for i in range(1, 6)]))
    with_roles = _open(render_player_heroes_image("Герои · Вася", None, None, [_hero()], [_role(1), _role(2)]))
    assert one.width == five.width == with_roles.width == WIDTH
    assert five.height > one.height + 4 * 80
    assert with_roles.height > one.height + 150


def test_player_heroes_shows_at_most_limit_rows():
    rows = [_hero(i) for i in range(1, 25)]
    capped = _open(render_player_heroes_image("Герои", None, None, rows, extra_heroes=len(rows) - LIMIT))
    ten = _open(render_player_heroes_image("Герои", None, None, rows[:LIMIT]))
    assert abs(capped.height - ten.height) < 80  # лишние строки не рисуются, только строка «и ещё N героев»


def test_empty_states_render():
    assert _open(render_player_heroes_image("Герои", None, ("ЗА СУТКИ", "#3987e5"), [])).width == WIDTH
    only_roles = _open(render_player_heroes_image("Позиции", None, None, [], [_role()]))
    assert only_roles.width == WIDTH
    hidden = render_player_heroes_image("Герои", None, None, [], hidden_note="История закрыта")
    assert _open(hidden).width == WIDTH
    assert _open(render_party_heroes_image([])).width == WIDTH
    assert _open(render_hero_image(1, "Anti-Mage", "за неделю", [])).width == WIDTH


def test_strange_data_does_not_break():
    rows = [_hero(1, name="😀" * 3 + "x" * 90, imp=None, gpm=None, games=0, wins=0, losses=0, winrate=0.0),
            _hero(9999, name=None)]
    png = render_player_heroes_image("Герои · " + "я" * 120, "под", None, rows, [_role(label="x" * 80, kda=0)],
                                     icons={1: b"junk"}, note="заметка")
    assert _open(png).width == WIDTH
    party = [{"name": "😀" * 40, "avatar": "u", "heroes": [{"hero_id": 1, "name": "x" * 90, "games": 1, "winrate": 1.0}] * 5},
             {"name": None, "avatar": None, "heroes": []}]
    assert _open(render_party_heroes_image(party, icons={1: b"junk"}, avatars={"u": b"junk"})).width == WIDTH
    hero = [{"name": None, "avatar": "u", "games": 1, "wins": 1, "losses": 0, "winrate": 1.0, "kda": 1.0, "imp": None, "gpm": None}]
    assert _open(render_hero_image(1, "x" * 200, "за год", hero, avatars={"u": b"junk"})).width == WIDTH


def test_party_and_hero_cards_grow_with_rows():
    party = [{"name": f"P{i}", "avatar": None, "heroes": [{"hero_id": 1, "name": "Axe", "games": 3, "winrate": 0.5}]}
             for i in range(4)]
    assert _open(render_party_heroes_image(party)).height > _open(render_party_heroes_image(party[:1])).height + 3 * 100
    entry = {"name": "Вася", "avatar": None, "games": 3, "wins": 2, "losses": 1, "winrate": 2 / 3, "kda": 2.5, "imp": 3, "gpm": 500}
    assert _open(render_hero_image(1, "Axe", "за месяц", [entry] * 4)).height > _open(render_hero_image(1, "Axe", "за месяц", [entry])).height + 3 * 80


# --- card_data -----------------------------------------------------------------------------------

def test_hero_rows_map_stats_keys():
    (row,) = cd.hero_rows([{"hero_id": 1, "games": 4, "wins": 3, "losses": 1, "winrate": 0.75, "kda": 3.0,
                            "avg_imp": 5.5, "avg_gpm": 600}])
    assert row["name"] == "Anti-Mage" and row["imp"] == 5.5 and row["gpm"] == 600 and row["games"] == 4


def test_role_rows_use_short_labels():
    rows = cd.role_rows([{"position": p, "games": 2, "wins": 1, "losses": 1, "winrate": 0.5, "kda": 2.0} for p in (1, 5)])
    assert [r["label"] for r in rows] == ["Керри", "Фулл-саппорт"] and rows[0]["position"] == 1


def test_party_hero_rows_keep_three_heroes():
    s = SimpleNamespace(display_name="Вася", avatar="a", top_heroes=[{"hero_id": i, "games": 5 - i, "winrate": 0.5} for i in range(1, 6)])
    (row,) = cd.party_hero_rows([s])
    assert row["name"] == "Вася" and row["avatar"] == "a" and [h["hero_id"] for h in row["heroes"]] == [1, 2, 3]


def test_hero_detail_rows_take_avatar_from_player():
    player = SimpleNamespace(display_name="Петя", account_id=7, steam_avatar="http://a")
    (row,) = cd.hero_detail_rows([(player, {"games": 3, "wins": 2, "losses": 1, "winrate": 2 / 3, "kda": 2.0, "avg_imp": 1, "avg_gpm": 400})])
    assert row["name"] == "Петя" and row["avatar"] == "http://a" and row["imp"] == 1 and row["gpm"] == 400


def test_captions_mention_top_entry_and_handle_empty():
    rows = cd.hero_rows([{"hero_id": 1, "games": 4, "wins": 3, "losses": 1, "winrate": 0.75, "kda": 3.0}])
    assert "Anti-Mage" in cd.heroes_caption("Вася", "week", rows) and "за неделю" in cd.heroes_caption("Вася", "week", rows)
    assert "игр нет" in cd.heroes_caption("Вася", "day", [])
    assert "данных нет" in cd.roles_caption("Вася", "all", [])
    assert "никто" in cd.hero_caption("Axe", "all", [])
