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


def Flat(height: int) -> Canvas:
    """Холст без свечения: тесты примитивов сверяют пиксели с ровным BG."""
    return Canvas(height, accent=None)


def test_text_falls_back_for_glyphs_missing_in_inter_and_tracks_small_caps():
    assert cards.font(24).getname()[0].startswith("Inter") and cards.font(40, True).getname()[0].startswith("Inter")
    assert len(cards._runs("Вася ok 123", 24, False)) == 1
    mixed = cards._runs("Вася 日本", 24, False)  # иероглифов в Inter нет — их рисует запасной шрифт
    assert len(mixed) == 2 and mixed[0][0] is not mixed[1][0]
    assert cards.text_width("Вася 日本", 24) > cards.text_width("Вася ", 24)
    # мелкие подписи заглавными — с разрядкой; значения с числами и крупный текст — без
    plain = cards.text_width("ИГРОК", 18, track=False)
    assert cards.text_width("ИГРОК", 18) > plain and cards.text_width("ИГРОК", 28) == cards.text_width("ИГРОК", 28, track=False)
    assert cards.text_width("+75 MMR", 18) == cards.text_width("+75 MMR", 18, track=False)
    canvas = Flat(120)
    cards.draw_text(canvas.draw, (600, 40), "Вася 日本", 24, anchor="rm")
    cards.draw_text(canvas.draw, (600, 80), "ПОСЛЕДНИЕ 20 ИГР", 18, anchor="mm", max_w=120)
    assert canvas.img.getpixel((620, 40)) == _hex(cards.BG)  # правее якоря "r" ничего не нарисовано


def test_canvas_top_glows_with_accent_and_flat_canvas_has_none():
    plain, red = Canvas(800), Canvas(800, accent=cards.LOSS)
    assert sum(plain.img.getpixel((40, 10))) > sum(plain.img.getpixel((40, 390)))  # сверху фон светлее
    assert plain.img.getpixel((1200, 700)) == _hex(cards.BG)  # ниже свечения — ровный фон
    assert plain.img.getpixel((40, cards.GLOW_H - 1)) == _hex(cards.BG)  # свечение сходит на нет без границы
    assert plain.img.getpixel((40, 10)) == plain.img.getpixel((1200, 10))  # только по вертикали — PNG жмёт такой фон даром
    assert red.img.getpixel((60, 20))[0] > plain.img.getpixel((60, 20))[0]  # свечение берёт цвет акцента
    assert Flat(800).img.getpixel((40, 10)) == _hex(cards.BG)  # accent=None — ровный фон
    cards.panel(plain.img, (100, 100, 300, 200), "#ff0000", radius=0, outline="#ff0000")
    assert _open(plain.png()).getpixel((200, 150)) == (255, 0, 0)


def test_text_masks_and_widths_are_cached():
    cards._text_mask.cache_clear()
    canvas = Flat(120)
    for _ in range(3):
        cards.draw_text(canvas.draw, (40, 40), "ИГРОК", 18)
        cards.draw_text(canvas.draw, (40, 80), "Вася", 28, bold=True)
    info = cards._text_mask.cache_info()
    assert info.misses == 2 and info.hits == 4  # буквы растеризуются один раз на строку
    cards.draw_text(canvas.draw, (40, 40), "", 18)  # пустая строка — ничего не рисуем и не падаем
    mask = cards._text_mask("Вася", 28, True, False)[0]
    assert 2 < len(mask.getcolors()) <= cards.LEVELS  # сглаживание в несколько ступеней — PNG с текстом легче


def test_rim_matches_outline_on_all_sides():
    img = Image.new("RGB", (200, 120), cards.BG)
    cards.panel(img, (20, 20, 180, 100), "#102030", radius=16, outline="#00ff00")
    for xy in ((100, 20), (100, 99), (20, 60), (179, 60)):  # середины сторон — ровно цвет рамки
        assert img.getpixel(xy) == (0, 255, 0), xy
    assert img.getpixel((100, 60)) == (16, 32, 48) and img.getpixel((21, 21)) == _hex(cards.BG)
    square = Image.new("RGB", (60, 60), cards.BG)
    cards.panel(square, (10, 10, 50, 50), "#102030", radius=0, outline="#00ff00")
    assert square.getpixel((10, 10)) == (0, 255, 0) and square.getpixel((49, 49)) == (0, 255, 0)


def test_value_and_delta_text_split_mark_from_number():
    canvas = Flat(200)
    wide = cards.value_text(canvas.draw, (600, 50), "≈5420", 38)
    assert wide > cards.value_text(canvas.draw, (600, 100), "5420", 38) > 0
    cards.delta_text(canvas.draw, (600, 150), "+75 за 56 игр", 20, cards.WIN)
    cards.delta_text(canvas.draw, (600, 180), "нет игр", 20, cards.MUTED, max_w=40)
    colors = {canvas.img.getpixel((x, 150)) for x in range(440, 600)}
    assert _hex(cards.WIN) in colors and _hex(cards.MUTED) in colors  # число — цветом, пояснение — приглушённо


def test_chip_is_tinted_and_header_uses_it_for_non_outcome_badges():
    canvas = Flat(200)
    width = cards.chip(canvas.img, canvas.draw, 100, 50, "ЗА НЕДЕЛЮ", cards.ACCENT)
    assert width > 100 and canvas.img.getpixel((100 + width // 2, 34)) not in (_hex(cards.BG), _hex(cards.ACCENT))
    cards.header(canvas.img, canvas.draw, "Рейтинг", None, ("ПОБЕДА", cards.WIN), y=100)
    assert _hex(cards.WIN) in {canvas.img.getpixel((x, 130)) for x in range(1100, 1248)}  # исход — залитая таблетка


def test_canvas_png_has_telegram_width_and_is_cropped_to_content():
    canvas = Flat(1000)
    img = _open(canvas.png(bottom=300))
    assert img.width == cards.WIDTH == 1280
    assert img.height == 300 + cards.PAD
    assert _open(Flat(500).png()).height == 500  # без bottom — как есть


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
    canvas = Flat(200)
    cards.panel(canvas.img, (20, 20, 220, 120), "#ff0000", radius=30)
    img = canvas.img
    assert img.getpixel((120, 70)) == (255, 0, 0)
    assert img.getpixel((20, 20)) == _hex(cards.BG)  # угол скруглён — фон
    diagonal = {img.getpixel((20 + i, 20 + i)) for i in range(0, 20)}  # по диагонали через дугу
    assert any(px not in (_hex(cards.BG), (255, 0, 0)) for px in diagonal)  # есть промежуточные цвета, а не ступенька


def _hex(color: str):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def test_panel_with_outline_and_degenerate_boxes_do_not_fail():
    canvas = Flat(100)
    cards.panel(canvas.img, (10, 10, 110, 60), "#00ff00", outline="#ffffff")
    assert canvas.img.getpixel((60, 35)) == (0, 255, 0)
    cards.panel(canvas.img, (10, 10, 10, 60), "#00ff00")   # нулевая ширина
    cards.panel(canvas.img, (10, 10, 11, 11), "#00ff00", outline="#fff")  # 1×1 с рамкой


def test_pill_returns_width_and_aligns():
    canvas = Flat(200)
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


def test_rank_badge_uses_real_icons_when_available(monkeypatch):
    import io
    from PIL import Image

    def png(color):
        buf = io.BytesIO()
        Image.new("RGBA", (20, 20), color).save(buf, "PNG")
        return buf.getvalue()

    files = {"rank_icon_5": png((255, 0, 0, 255)), "rank_star_3": png((0, 0, 0, 0))}
    monkeypatch.setattr(cards, "rank_icon_source", files.get)
    badge = cards.rank_badge(53, 40)
    assert badge.size == (40, 40) and badge.getpixel((20, 20))[:3] == (255, 0, 0)
    drawn = cards._drawn_badge(53, 40)
    assert cards.rank_badge(62, 40).tobytes() == cards._drawn_badge(62, 40).tobytes()  # нет значка — своя медаль
    assert badge.tobytes() != drawn.tobytes()
    monkeypatch.setattr(cards, "rank_icon_source", lambda name: 1 / 0)
    assert cards.rank_badge(53, 40).tobytes() == drawn.tobytes()  # сбой загрузчика — не падаем


def test_kda_and_form_dots_draw_without_error():
    canvas = Flat(120)
    cards.kda(canvas.draw, 300, 40, 12, 3, None)
    width = cards.form_dots(canvas.img, 20, 90, [True, False, True, None], r=8, gap=6)
    assert width == 4 * 16 - 6  # штрих шириной 10 + зазор 6
    assert cards.form_dots(canvas.img, 20, 90, []) == 0
    # победа — зелёный штрих выше середины, поражение — красный ниже: исход виден и по высоте
    assert canvas.img.getpixel((20 + 5, 80)) == _hex(cards.WIN)
    assert canvas.img.getpixel((20 + 5, 101)) == _hex(cards.BG)
    assert canvas.img.getpixel((20 + 16 + 5, 100)) == _hex(cards.LOSS)
    assert canvas.img.getpixel((20 + 16 + 5, 79)) == _hex(cards.BG)
    assert canvas.img.getpixel((20 + 48 + 5, 90)) == _hex(cards.GRID)  # исход неизвестен — серый по центру


def test_winrate_bar_proportions():
    canvas = Flat(100)
    cards.winrate_bar(canvas.img, (100, 20, 300, 36), wins=3, losses=1)
    assert canvas.img.getpixel((150, 28)) == _hex(cards.WIN)
    assert canvas.img.getpixel((290, 28)) != _hex(cards.WIN)
    cards.winrate_bar(canvas.img, (100, 50, 300, 66), wins=0, losses=0)
    assert canvas.img.getpixel((200, 58)) == _hex(cards.GRID)
    cards.winrate_bar(canvas.img, (100, 70, 100, 86), wins=1, losses=0)  # нулевая ширина


@pytest.mark.parametrize("values", [[], [5], [3, 3, 3], [1, 5, 2, 8, 4], [None, 4, 9], list(range(500))])
def test_sparkline_handles_any_series(values):
    canvas = Flat(200)
    before = canvas.img.tobytes()
    cards.sparkline(canvas.img, (50, 20, 450, 140), values)
    if [v for v in values if v is not None]:
        assert canvas.img.tobytes() != before
    else:
        assert canvas.img.tobytes() == before


def test_tile_and_header_footer_return_layout_positions():
    canvas = Flat(400)
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
    canvas = Flat(100)
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


def test_gradient_panel_blends_two_colors_and_keeps_rounded_corners():
    img = Image.new("RGB", (200, 100), cards.BG)
    background = img.getpixel((0, 0))
    cards.gradient_panel(img, (10, 10, 190, 90), "#000000", "#ffffff", radius=24)
    left, right = img.getpixel((20, 50)), img.getpixel((180, 50))
    assert sum(left) < sum(img.getpixel((100, 50))) < sum(right)
    assert img.getpixel((10, 10)) == background  # угол скруглён — фон не закрашен
    cards.gradient_panel(img, (5, 5, 5, 50), "#000000", "#ffffff")  # пустая панель — без ошибки
