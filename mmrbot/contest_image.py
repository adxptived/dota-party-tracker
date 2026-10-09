"""Соревнование чата картинкой (/achievements): подиум общего зачёта и карточки номинаций с топ-3.

Чистая функция: данные — словарями (их собирает card_data.contest_view), аватары — готовыми байтами; сети и БД нет.
Эмодзи в Pillow без цветного шрифта не нарисовать, поэтому номинации различаются названием и цветом полосы,
а места — цветными кружками (золото/серебро/бронза), а не медалями-эмодзи.
Таблица: [{name, avatar, points, golds}] от лидера; номинации: [{title, anti, entries: [{name, avatar, place, text}]}].
"""
from __future__ import annotations

from typing import Optional

from mmrbot import cards
from mmrbot.cards import ACCENT, BG, FG, LOSS, MUTED, PAD, PANEL, PANEL_HI, PLACE_COLORS, WIDTH, clean, draw_text

MAX_TABLE = 8  # игроков в общем зачёте (подиум + строки под ним)
MAX_NOMS = 12  # номинаций на картинке (в каталоге их не больше двенадцати)
GAP = 20
CARD_W = (WIDTH - 2 * PAD - GAP) // 2
CARD_HEAD, ROW_H, CARD_PAD = 64, 58, 14
PODIUM_H = 272
ROW_SMALL = 52
LABEL_H = 38


def _place_color(place: int) -> str:
    return PLACE_COLORS.get(place, MUTED)


def _label(draw, y: float, text: str, color: str = MUTED) -> float:
    draw_text(draw, (PAD + 6, y + 14), text, 18, color, bold=True, anchor="lm")
    return y + LABEL_H


def _place_dot(img, draw, cx: float, cy: float, place: int, r: int = 16) -> None:
    cards.dot(img, cx, cy, r, _place_color(place))
    draw_text(draw, (cx, cy - 1), str(place), 20 if r >= 15 else 16, BG, bold=True, anchor="mm")


def _plural_points(n: int) -> str:
    n10, n100 = n % 10, n % 100
    word = "очко" if n10 == 1 and n100 != 11 else "очка" if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else "очков"
    return f"{n} {word}"


def _places(table: list) -> list[int]:
    """Места в общем зачёте: поровну очков и первых мест — делят место (1, 2, 2, 4)."""
    places = []
    for i, row in enumerate(table):
        same = i and (row["points"], row.get("golds", 0)) == (table[i - 1]["points"], table[i - 1].get("golds", 0))
        places.append(places[-1] if same else i + 1)
    return places


def _podium(img, draw, y: int, table: list, places: list[int], avatars: dict) -> int:
    cards.panel(img, (PAD, y, WIDTH - PAD, y + PODIUM_H), PANEL, radius=20)
    shown = list(zip(table[:3], places[:3]))
    # подиум: 1-е место по центру, 2-е слева, 3-е справа (вдвоём — 1-е правее центра)
    fracs = {1: [0.5], 2: [0.66, 0.34], 3: [0.5, 0.17, 0.83]}[len(shown)]
    inner = WIDTH - 2 * PAD
    for frac, (row, place) in zip(fracs, shown):
        cx = PAD + inner * frac
        first = place == 1
        size = 112 if first else 88
        ring = _place_color(place)
        # «ступень» подиума: подсвеченная колонка цвета места, у первого — выше остальных
        half = min(inner / len(shown) / 2 - 10, 190)
        cards.panel(img, (cx - half, y + (12 if first else 36), cx + half, y + PODIUM_H - 12),
                    cards.mix(PANEL, ring, 0.11 if first else 0.07), radius=16,
                    outline=cards.mix(PANEL, ring, 0.3 if first else 0.18))
        top = y + (24 if first else 48)
        name = clean(row.get("name")) or "Игрок"
        sprite = cards.avatar(avatars.get(row.get("avatar")), name, size, ring=ring, ring_w=4)
        cards.paste(img, sprite, cx - sprite.width / 2, top)
        _place_dot(img, draw, cx + sprite.width / 2 - 8, top + sprite.height - 10, place)
        draw_text(draw, (cx, y + 170), name, 28, FG, bold=True, anchor="mm", max_w=inner / 3 - 40)
        draw_text(draw, (cx, y + 208), _plural_points(row["points"]), 30 if first else 26, ring, bold=True,
                  anchor="mm", max_w=inner / 3 - 40)
        golds = row.get("golds") or 0
        draw_text(draw, (cx, y + 240), f"первых мест: {golds}", 18, MUTED, anchor="mm", max_w=inner / 3 - 40)
    return y + PODIUM_H + 16


def _table_rows(img, draw, y: int, table: list, places: list[int], avatars: dict) -> int:
    rest = list(zip(table[3:MAX_TABLE], places[3:MAX_TABLE]))
    hidden = max(len(table) - MAX_TABLE, 0)
    if not rest:
        return y
    h = len(rest) * ROW_SMALL + 20 + (30 if hidden else 0)
    cards.panel(img, (PAD, y, WIDTH - PAD, y + h), PANEL, radius=18)
    for i, (row, place) in enumerate(rest):
        cy = y + 10 + i * ROW_SMALL + ROW_SMALL / 2
        name = clean(row.get("name")) or "Игрок"
        _place_dot(img, draw, PAD + 40, cy, place, r=14)
        cards.paste(img, cards.avatar(avatars.get(row.get("avatar")), name, 36), PAD + 70, cy - 18)
        draw_text(draw, (PAD + 120, cy), name, 24, FG, bold=True, anchor="lm", max_w=560)
        draw_text(draw, (WIDTH - PAD - 28, cy), _plural_points(row["points"]), 22, MUTED, anchor="rm", max_w=260)
    if hidden:
        draw_text(draw, (PAD + 28, y + h - 24), f"и ещё {hidden} в полном списке (текстом)", 18, MUTED, anchor="lm")
    return y + h + 16


def _nom_height(nom: dict) -> int:
    return CARD_HEAD + max(len(nom.get("entries") or []), 1) * ROW_H + CARD_PAD


def _card(img, draw, x0: int, y0: int, nom: dict, height: int, avatars: dict) -> None:
    anti = bool(nom.get("anti"))
    color = LOSS if anti else ACCENT
    cards.panel(img, (x0, y0, x0 + CARD_W, y0 + height), cards.mix(PANEL_HI, LOSS, 0.07) if anti else PANEL_HI, radius=18,
                outline=cards.mix(PANEL_HI, LOSS, 0.5) if anti else None)
    cards.stripe(img, x0 + 12, y0 + 16, y0 + CARD_HEAD - 12, color, width=5)
    draw_text(draw, (x0 + 30, y0 + CARD_HEAD / 2), clean(nom.get("title")), 26, FG, bold=True, anchor="lm", max_w=CARD_W - 54)
    for i, entry in enumerate(nom.get("entries") or []):
        cy = y0 + CARD_HEAD + i * ROW_H + ROW_H / 2
        name = clean(entry.get("name")) or "Игрок"
        _place_dot(img, draw, x0 + 42, cy, entry.get("place") or i + 1, r=15)
        cards.paste(img, cards.avatar(avatars.get(entry.get("avatar")), name, 40), x0 + 70, cy - 20)
        draw_text(draw, (x0 + 122, cy), name, 24, FG, bold=entry.get("place") == 1, anchor="lm", max_w=190)
        draw_text(draw, (x0 + CARD_W - 24, cy), clean(entry.get("text")), 21, MUTED if not anti else LOSS,
                  anchor="rm", max_w=CARD_W - 122 - 190 - 24 - 12)


def _grid(img, draw, y: int, noms: list, avatars: dict) -> int:
    for i in range(0, len(noms), 2):
        pair = noms[i:i + 2]
        height = max(_nom_height(n) for n in pair)
        for j, nom in enumerate(pair):
            _card(img, draw, PAD + j * (CARD_W + GAP), y, nom, height, avatars)
        y += height + GAP
    return y


def _grid_height(noms: list) -> int:
    return sum(max(_nom_height(n) for n in noms[i:i + 2]) + GAP for i in range(0, len(noms), 2))


def render_contest_image(period: str, table: list, noms: list, avatars: Optional[dict] = None,
                         note: Optional[str] = None, subtitle: Optional[str] = None) -> bytes:
    """Соревнование чата → PNG-байты. period — подпись в углу («ЗА НЕДЕЛЮ»); показывается до MAX_TABLE игроков и MAX_NOMS номинаций."""
    avatars = avatars or {}
    places = _places(table)
    good = [n for n in noms if not n.get("anti")][:MAX_NOMS]
    anti = [n for n in noms if n.get("anti")][:max(MAX_NOMS - len(good), 0)]
    total = 340 + (PODIUM_H + 16 if table else 130) + len(table[3:MAX_TABLE]) * ROW_SMALL + 80 \
        + _grid_height(good) + _grid_height(anti) + 3 * LABEL_H + (60 if note else 0)
    canvas = cards.Canvas(total)
    img, draw = canvas.img, canvas.draw
    y = cards.header(img, draw, "Соревнование", subtitle or "кто лучший в чате: места, очки и антирекорды",
                     badge=(clean(period), ACCENT))

    if not table:
        cards.panel(img, (PAD, y, WIDTH - PAD, y + 110), PANEL, radius=18)
        draw_text(draw, (PAD + 28, y + 55), "Пока не с кем соревноваться: нужны двое игроков с играми за период.",
                  26, MUTED, anchor="lm", max_w=WIDTH - 2 * PAD - 56)
        y += 126
    else:
        y = _label(draw, y, "ОБЩИЙ ЗАЧЁТ · 3 очка за 1-е место, 2 за 2-е, 1 за 3-е")
        y = _podium(img, draw, y, table, places, avatars)
        y = _table_rows(img, draw, y, table, places, avatars)
        if good:
            y = _label(draw, y, "НОМИНАЦИИ")
            y = _grid(img, draw, y, good, avatars)
        if anti:
            y = _label(draw, y, "АНТИРЕКОРДЫ", LOSS)
            y = _grid(img, draw, y, anti, avatars)
        if not good and not anti:
            draw_text(draw, (PAD + 6, y + 20), "Номинаций пока нет: за период слишком мало игр.", 22, MUTED, anchor="lm")
            y += 50
    if note:
        y = cards.footer(draw, y, note)
    return canvas.png(y)
