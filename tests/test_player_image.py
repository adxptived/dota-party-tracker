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
        "hours": {"best": "21:00 · 70%", "worst": "03:00 · 30%"},
        "heroes": [{"hero_id": 12, "name": "Phantom Lancer", "games": 12, "wins": 8, "winrate": 0.66}] * 3,
        "best_game": {"hero_id": 12, "name": "Phantom Lancer", "kills": 20, "deaths": 2, "assists": 10, "kda": 15.0},
        "skills": [{"label": "Фарм", "pct": 0.78}, {"label": "Урон", "pct": 1.4}, {"label": "Бои", "pct": -1}],
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
                warnings=["z" * 300], heroes=[], best_game=None, split=[], hours=None, skills=[], mmr_delta=None,
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
