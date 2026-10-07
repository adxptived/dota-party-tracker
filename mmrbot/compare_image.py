"""Сравнение игроков картинкой (/compare): таблица «сила в чате» — индекс и показатели с местом среди участников.

Строка (`rows`, уже по убыванию индекса): name, avatar, rank_tier, rank_text, power (0..1 | None), index_text,
cells — до четырёх показателей {label, value, rank} (value — готовая строка или None; rank — место 1..n | None).
Чистая функция: сети и БД нет; аватары — готовыми байтами.
"""
from __future__ import annotations

from typing import Optional

from mmrbot import cards
from mmrbot.cards import ACCENT, FG, GOLD, LOSS, MUTED, PAD, PANEL, WIDTH, clean, draw_text

ROW_H, ROW_GAP = 96, 8
HEAD_ROW_H = 36
AVATAR = 64
NAME_X = PAD + 78 + AVATAR + 16
NAME_MAX_W = 270
INDEX_X = 640
CELL_X = (790, 925, 1060, 1180)
COLUMNS = ("ПЕРФ", "ВИНРЕЙТ", "KDA", "GPM")
BAR_W = 100


def _rank_color(rank: Optional[int], size: int) -> str:
    if rank == 1 and size > 1:
        return GOLD
    if rank is not None and rank == size and size > 2:
        return LOSS
    return MUTED


def render_compare_image(rows: list, avatars: Optional[dict] = None, note: Optional[str] = None) -> bytes:
    """Сравнение игроков → PNG-байты. Показатель без данных рисуется «—»."""
    avatars = avatars or {}
    size = len(rows)
    canvas = cards.Canvas(300 + size * (ROW_H + ROW_GAP) + 100)
    img, draw = canvas.img, canvas.draw
    y = cards.header(img, draw, "Сравнение игроков", "индекс — среднее положение среди участников по четырём показателям",
                     (f"УЧАСТНИКОВ: {size}", ACCENT))
    if not rows:
        draw_text(draw, (PAD, y + 20), "Игроков пока нет.", 26, MUTED, anchor="lm")
        y += 50
    else:
        draw_text(draw, (NAME_X, y + 10), "ИГРОК", 18, MUTED, anchor="lm")
        draw_text(draw, (INDEX_X, y + 10), "ИНДЕКС", 18, MUTED, anchor="mm")
        for x, label in zip(CELL_X, COLUMNS):
            draw_text(draw, (x, y + 10), label, 18, MUTED, anchor="mm")
        y += HEAD_ROW_H
    for place, row in enumerate(rows, start=1):
        _draw_row(img, draw, y, place, row, size, avatars)
        y += ROW_H + ROW_GAP
    if rows:
        draw_text(draw, (PAD, y + 14), "#N — место среди участников: 1 — лучший. Показатель появляется после нескольких игр с деталями.",
                  18, MUTED, anchor="lm", max_w=WIDTH - 2 * PAD)
        y += 34
    if note:
        y = cards.footer(draw, y, note)
    return canvas.png(y)


def _draw_row(img, draw, y: int, place: int, row: dict, size: int, avatars: dict) -> None:
    cards.panel(img, (PAD, y, WIDTH - PAD, y + ROW_H), PANEL, radius=16)
    if place == 1:
        cards.stripe(img, PAD, y, y + ROW_H, GOLD)
    mid = y + ROW_H / 2
    color = cards.PLACE_COLORS.get(place)
    cards.dot(img, PAD + 44, mid, 22, color or cards.PANEL_HI)
    draw_text(draw, (PAD + 44, mid), str(place), 24, cards.BG if color else MUTED, bold=True, anchor="mm")
    name = clean(row.get("name")) or "Игрок"
    cards.paste(img, cards.avatar(avatars.get(row.get("avatar")), name, AVATAR), PAD + 78, mid - AVATAR / 2)
    draw_text(draw, (NAME_X, mid - 16), name, 28, FG, bold=True, anchor="lm", max_w=NAME_MAX_W)
    cards.paste(img, cards.rank_badge(row.get("rank_tier"), 32), NAME_X, mid + 2)
    draw_text(draw, (NAME_X + 42, mid + 18), clean(row.get("rank_text")), 20, MUTED, anchor="lm", max_w=NAME_MAX_W - 42)

    power = row.get("power")
    draw_text(draw, (INDEX_X, mid - 12), clean(row.get("index_text")) or "—", 38, GOLD if place == 1 else FG, bold=True, anchor="mm")
    if power is not None:
        cards.bar(img, (INDEX_X - BAR_W / 2, mid + 20, INDEX_X + BAR_W / 2, mid + 30), max(0.0, min(1.0, power)), ACCENT)

    cells = row.get("cells") or []
    for x, cell in zip(CELL_X, cells):
        value, rank = cell.get("value"), cell.get("rank")
        draw_text(draw, (x, mid - 10), clean(value) if value else "—", 30, FG if value else MUTED, bold=bool(value), anchor="mm",
                  max_w=124)
        if value and rank:
            draw_text(draw, (x, mid + 24), f"#{rank}", 22, _rank_color(rank, size), bold=rank == 1 or rank == size, anchor="mm")
