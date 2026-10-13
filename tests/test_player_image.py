import io

from PIL import Image

from mmrbot.cards import WIDTH
from mmrbot.player_image import render_player_image


def _full():
    return {
        "name": "Вася", "steam_name": "shinoame", "avatar": "https://avatars.steamstatic.com/a.jpg", "rank_tier": 55,
        "rank_text": "Legend 5", "mmr_text": "≈5420", "mmr_delta": 420, "delta_note": "за 56 игр", "perf": 73,
        "streak": ("W", 4), "warnings": ["Предупреждение"],
        "tiles": [{"label": f"T{i}", "value": str(i), "sub": "s"} for i in range(6)],
        "series": [5000, 5025, 5010, 5050], "series_label": "Динамика", "form": [True, False, True],
        "split": [{"label": "Соло", "wins": 3, "losses": 2}, {"label": "В группе", "wins": 0, "losses": 0}],
        "facts": [("Лучшая серия", "7 побед", "#3ddc84"), ("Пул героев", "23 героя", None)],
        "heroes": [{"hero_id": 12, "name": "Phantom Lancer", "games": 12, "wins": 8, "winrate": 0.66}] * 3,
        "last_game": {"hero_id": 12, "name": "Phantom Lancer", "kills": 20, "deaths": 2, "assists": 10, "kda": 15.0, "won": False},
        "recent": [{"hero_id": 12, "name": "PL", "won": i % 2 == 0, "kills": 9, "deaths": 1, "assists": 14, "delta": 25,
                    "minutes": 38, "when": "12.10"} for i in range(6)], "recent_mmr": True,
        "lobby_rank": 55, "lobby_text": "Legend 5", "standing": "#2 из 5", "note": "заметка",
    }


def _open(png: bytes) -> Image.Image:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(png))


def test_full_card_has_telegram_width_and_sensible_height():
    img = _open(render_player_image(_full(), {12: b"junk"}, {"https://avatars.steamstatic.com/a.jpg": b"junk"}))
    assert img.width == WIDTH and 1000 < img.height < 2000


def test_blocks_are_optional_and_card_shrinks():
    full = _open(render_player_image(_full()))
    sparse = _open(render_player_image({"name": "Вася", "rank_tier": None, "rank_text": None, "mmr_text": None}))
    assert sparse.width == WIDTH and sparse.height < full.height / 2


def test_strange_names_and_values_do_not_break():
    card = _full()
    card.update(name="😀" * 3 + "x" * 90 + "\x00", steam_name="y" * 90, series=[5], form=[], tiles=[{}],
                warnings=["z" * 300], heroes=[], last_game=None, split=[], facts=None, recent=[{}], mmr_delta=None,
                streak=("L", 6))
    assert _open(render_player_image(card)).width == WIDTH
    card["series"] = [7] * 30  # плоская линия
    assert _open(render_player_image(card)).width == WIDTH


def test_sections_add_height():
    base = _full()
    base.update(warnings=[])
    with_warnings = _full()
    with_warnings["warnings"] = ["a", "b"]
    assert _open(render_player_image(with_warnings)).height > _open(render_player_image(base)).height


def test_last_game_details_and_hero_kda_are_drawn(drawn):
    card = _full()
    card["last_game"].update(when="09.10 21:40", stats=[("Время", "38 мин"), ("GPM", "640"), ("Урон", "31.2k")])
    card["heroes"] = [dict(card["heroes"][0], kda=4.13)]
    render_player_image(card)
    texts = [t[0] for t in drawn]
    assert "09.10 21:40" in texts
    for label, value in (("ВРЕМЯ", "38 мин"), ("GPM", "640"), ("УРОН", "31.2k")):
        assert texts[texts.index(label) + 1] == value
    assert "12 игр · 8–4 · KDA 4.1" in texts


def test_long_name_and_rank_shrink_instead_of_truncating(drawn):
    card = _full()
    card.update(name="Оооочень длинный ник игрока из Steam", rank_text="Immortal #1234", mmr_text="≈12345")
    render_player_image(card)
    texts = [t[0] for t in drawn]
    assert "Оооочень длинный ник игрока из Steam" in texts and "Immortal #1234" in texts


def test_recent_games_and_facts_are_drawn(drawn):
    render_player_image(_full())
    texts = [t[0] for t in drawn]
    assert "ПОСЛЕДНИЕ ИГРЫ" in texts and texts.count("+25") == 6 and "38 мин  ·  12.10" in texts
    assert "Лучшая серия" in texts and "7 побед" in texts
    assert "ПРОФИЛЬ НАВЫКОВ · МИРОВОЙ ПЕРЦЕНТИЛЬ" not in texts
