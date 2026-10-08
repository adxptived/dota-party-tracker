import io

import pytest
from PIL import Image

from mmrbot import cards
from mmrbot.cards import Canvas


def _open(png: bytes) -> Image.Image:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(png)).convert("RGB")


def _icon_bytes(color=(200, 50, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (256, 144), color).save(buf, format="PNG")
    return buf.getvalue()


def test_canvas_png_has_telegram_width_and_is_cropped_to_content():
    canvas = Canvas(1000)
    img = _open(canvas.png(bottom=300))
    assert img.width == cards.WIDTH == 1280
    assert img.height == 300 + cards.PAD
    assert _open(Canvas(500).png()).height == 500  # без bottom — как есть


def test_clean_drops_emoji_and_control_chars_and_fit_truncates():
    assert cards.clean("Вася 😀\x00") == "Вася"
    assert cards.clean(None) == ""
    fnt = cards.font(24)
    short = cards.fit("x" * 200, fnt, 100)
    assert short.endswith("…") and fnt.getlength(short) <= 100
    assert cards.fit("ok", fnt, 100) == "ok"


def test_signed_uses_real_minus_and_handles_none():
    assert cards.signed(75) == "+75" and cards.signed(-12) == "−12" and cards.signed(0) == "0"
    assert cards.signed(None) == "—" and cards.signed(0.4) == "0"
    assert cards.delta_color(5) == cards.WIN and cards.delta_color(-5) == cards.LOSS
    assert cards.delta_color(0) == cards.MUTED and cards.delta_color(None) == cards.MUTED


def test_panel_fills_center_and_rounds_corners_with_antialiasing():
    canvas = Canvas(200)
    cards.panel(canvas.img, (20, 20, 220, 120), "#ff0000", radius=30)
    img = canvas.img
    assert img.getpixel((120, 70)) == (255, 0, 0)
    assert img.getpixel((20, 20)) == _hex(cards.BG)  # угол скруглён — фон
    diagonal = {img.getpixel((20 + i, 20 + i)) for i in range(0, 20)}  # по диагонали через дугу
    assert any(px not in (_hex(cards.BG), (255, 0, 0)) for px in diagonal)  # есть промежуточные цвета, а не ступенька


def _hex(color: str):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def test_panel_with_outline_and_degenerate_boxes_do_not_fail():
    canvas = Canvas(100)
    cards.panel(canvas.img, (10, 10, 110, 60), "#00ff00", outline="#ffffff")
    assert canvas.img.getpixel((60, 35)) == (0, 255, 0)
    cards.panel(canvas.img, (10, 10, 10, 60), "#00ff00")   # нулевая ширина
    cards.panel(canvas.img, (10, 10, 11, 11), "#00ff00", outline="#fff")  # 1×1 с рамкой


def test_pill_returns_width_and_aligns():
    canvas = Canvas(200)
    left = cards.pill(canvas.img, canvas.draw, 100, 50, "ПОБЕДА", cards.BG, cards.WIN)
    right = cards.pill(canvas.img, canvas.draw, 600, 50, "ПОБЕДА", cards.BG, cards.WIN, align="right")
    assert left == right > 60
    assert canvas.img.getpixel((100 + 4, 50)) != _hex(cards.BG)       # слева от x100 таблетка начинается
    assert canvas.img.getpixel((600 + 10, 50)) == _hex(cards.BG)      # справа от right-края пусто


def test_hero_icon_falls_back_for_missing_and_broken_data():
    good = cards.hero_icon(_icon_bytes(), 1)
    assert good.size == (cards.ICON_W, cards.ICON_H) and good.mode == "RGBA"
    for data in (None, b"not a png", b""):
        fallback = cards.hero_icon(data, 1)
        assert fallback.size == good.size
    assert cards.hero_icon(None, None).size == good.size
    small = cards.hero_icon(_icon_bytes(), 1, 56, 32, 6)
    assert small.size == (56, 32)
    assert good.getpixel((0, 0))[3] < 255  # углы скруглены


def test_avatar_is_circular_with_initial_fallback_and_ring():
    plain = cards.avatar(None, "Вася", 64)
    assert plain.size == (64, 64) and plain.getpixel((0, 0))[3] == 0 and plain.getpixel((32, 32))[3] == 255
    assert cards.avatar(_icon_bytes(), "Вася", 64).getpixel((32, 32))[:3] == (200, 50, 50)
    assert cards.avatar(b"broken", "", 48).size == (48, 48)
    ringed = cards.avatar(None, "Вася", 64, ring=cards.GOLD, ring_w=3)
    assert ringed.size == (70, 70)
    assert ringed.getpixel((35, 1))[:3] != plain.getpixel((32, 32))[:3]  # на кольце золото
    # разные ники — разные цвета заглушки (хотя бы не все одинаковые)
    colors = {cards.avatar(None, name, 40).getpixel((3, 20))[:3] for name in ("Вася", "Петя", "Оля", "Макс", "Ира")}
    assert len(colors) > 1


def test_rank_badge_each_tier_distinct_and_uncalibrated_neutral():
    badges = {tier: cards.rank_badge(tier, 64) for tier in (None, 11, 25, 43, 55, 62, 74, 80)}
    assert all(b.size == (64, 64) for b in badges.values())
    assert len({b.tobytes() for b in badges.values()}) == len(badges)
    assert cards.rank_badge(0, 64).tobytes() == cards.rank_badge(None, 64).tobytes()
    assert cards.rank_badge(55, 64).tobytes() != cards.rank_badge(51, 64).tobytes()  # звёзды видны
    assert cards.rank_badge(99, 48).size == (48, 48)  # неизвестная медаль — не падаем


def test_kda_and_form_dots_draw_without_error():
    canvas = Canvas(120)
    cards.kda(canvas.draw, 300, 40, 12, 3, None)
    width = cards.form_dots(canvas.img, 20, 90, [True, False, True, None], r=8, gap=6)
    assert width == 4 * 22 - 6
    assert cards.form_dots(canvas.img, 20, 90, []) == 0
    assert canvas.img.getpixel((20 + 8, 90)) == _hex(cards.WIN)
    assert canvas.img.getpixel((20 + 8 + 22, 90)) == _hex(cards.LOSS)


def test_winrate_bar_proportions():
    canvas = Canvas(100)
    cards.winrate_bar(canvas.img, (100, 20, 300, 36), wins=3, losses=1)
    assert canvas.img.getpixel((150, 28)) == _hex(cards.WIN)
    assert canvas.img.getpixel((290, 28)) != _hex(cards.WIN)
    cards.winrate_bar(canvas.img, (100, 50, 300, 66), wins=0, losses=0)
    assert canvas.img.getpixel((200, 58)) == _hex(cards.GRID)
    cards.winrate_bar(canvas.img, (100, 70, 100, 86), wins=1, losses=0)  # нулевая ширина


@pytest.mark.parametrize("values", [[], [5], [3, 3, 3], [1, 5, 2, 8, 4], [None, 4, 9], list(range(500))])
def test_sparkline_handles_any_series(values):
    canvas = Canvas(200)
    before = canvas.img.tobytes()
    cards.sparkline(canvas.img, (50, 20, 450, 140), values)
    if [v for v in values if v is not None]:
        assert canvas.img.tobytes() != before
    else:
        assert canvas.img.tobytes() == before


def test_tile_and_header_footer_return_layout_positions():
    canvas = Canvas(400)
    cards.tile(canvas.img, canvas.draw, (32, 150, 332, 260), "Винрейт", "62%", "37 из 60", cards.WIN)
    cards.tile(canvas.img, canvas.draw, (352, 150, 652, 260), "Очень длинная подпись" * 5, "9" * 40)
    y = cards.header(canvas.img, canvas.draw, "Рейтинг", "за неделю", ("ПОБЕДА", cards.WIN))
    assert y > cards.PAD + 54
    bare = cards.header(canvas.img, canvas.draw, "Без подзаголовка")
    assert bare < y
    assert cards.footer(canvas.draw, 300, "данные на 12:30") > 300


def test_hero_icon_cache_returns_same_object_for_same_args():
    data = _icon_bytes()
    assert cards.hero_icon(data, 1) is cards.hero_icon(data, 1)


def test_bar_fraction_marker_and_clamping():
    canvas = Canvas(100)
    cards.bar(canvas.img, (100, 20, 300, 36), 0.5, "#ff0000", marker=0.5)
    assert canvas.img.getpixel((130, 28)) == (255, 0, 0)
    assert canvas.img.getpixel((250, 28)) == _hex(cards.GRID)
    assert canvas.img.getpixel((200, 28)) == _hex(cards.FG)  # риска посередине
    cards.bar(canvas.img, (100, 50, 300, 66), 7.0)            # больше 1 — полная
    assert canvas.img.getpixel((290, 58)) == _hex(cards.ACCENT)
    cards.bar(canvas.img, (100, 70, 300, 86), None)           # нет значения — пусто
    cards.bar(canvas.img, (100, 70, 100, 86), 0.5)            # нулевая ширина


def test_png_is_valid_and_warmup_is_safe():
    from mmrbot import cards
    cards.warmup()  # не падает и не требует сети/диска
    png = cards.Canvas(100).png(50)
    assert png.startswith(b"\x89PNG") and cards.to_png(cards.Canvas(60).img) == cards.to_png(cards.Canvas(60).img)
