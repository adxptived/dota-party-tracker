"""Рекорды пати картинкой (/records): плитки 2 в ряд — иконка героя, показатель, значение, игрок и дата;
внизу широкая плитка «Лучшая серия побед».

Чистая функция: данные — словарями (их собирает card_data.record_tiles), иконки героев — готовыми байтами;
сети и БД нет. Рекорд: label, value, player, hero_id, date, anti (антирекорд — красным).
"""
from __future__ import annotations

from typing import Optional

from mmrbot import cards
from mmrbot.cards import ACCENT, FG, GOLD, ICON_H, ICON_W, LOSS, MUTED, PAD, PANEL, WIDTH, clean, draw_text

TILE_H, GAP = 118, 14
PER_ROW = 2
LIMIT = 12
TILE_W = (WIDTH - 2 * PAD - GAP * (PER_ROW - 1)) / PER_ROW


def render_records_image(
    period_label: str, records: list, streak: Optional[tuple[str, int]] = None, icons: Optional[dict] = None,
    note: Optional[str] = None,
) -> bytes:
    """Рекорды пати → PNG-байты. streak: (имя, длина); нет рекордов — шапка и пояснение."""
    icons = icons or {}
    records = records[:LIMIT]
    rows = (len(records) + PER_ROW - 1) // PER_ROW
    canvas = cards.Canvas(260 + rows * (TILE_H + GAP) + 140 + (60 if note else 0))
    img, draw = canvas.img, canvas.draw
    y = cards.header(img, draw, "Рекорды пати", "лучшая отдельная игра по каждому показателю", (period_label.upper(), ACCENT))

    if not records:
        cards.panel(img, (PAD, y, WIDTH - PAD, y + 110), PANEL, radius=18)
        draw_text(draw, (PAD + 28, y + 55), "За период нет данных — нужны сыгранные игры.", 26, MUTED, anchor="lm",
                  max_w=WIDTH - 2 * PAD - 56)
        y += 126
    for i, rec in enumerate(records):
        x0 = PAD + (i % PER_ROW) * (TILE_W + GAP)
        y0 = y + (i // PER_ROW) * (TILE_H + GAP)
        _draw_tile(img, draw, x0, y0, rec, icons)
    y += rows * (TILE_H + GAP)

    if streak and streak[1] >= 2:
        y = _draw_streak(img, draw, y, streak)
    if note:
        y = cards.footer(draw, y, note)
    return canvas.png(y)


def _draw_tile(img, draw, x0: float, y0: float, rec: dict, icons: dict) -> None:
    anti = bool(rec.get("anti"))
    cards.panel(img, (x0, y0, x0 + TILE_W, y0 + TILE_H), cards.mix(PANEL, LOSS, 0.08) if anti else PANEL, radius=16)
    if anti:
        cards.stripe(img, x0, y0, y0 + TILE_H, LOSS)
    mid = y0 + TILE_H / 2
    hero_id = rec.get("hero_id")
    cards.paste(img, cards.hero_icon(icons.get(hero_id), hero_id), x0 + 20, mid - ICON_H / 2)
    tx = x0 + 20 + ICON_W + 20
    room = TILE_W - (tx - x0) - 18
    draw_text(draw, (tx, y0 + 26), clean(rec.get("label")), 19, MUTED, anchor="lm", max_w=room)
    draw_text(draw, (tx, y0 + 62), clean(rec.get("value")), 34, LOSS if anti else GOLD, bold=True, anchor="lm", max_w=room)
    date = clean(rec.get("date"))
    date_w = cards.text_width(date, 20) + 16 if date else 0
    draw_text(draw, (tx, y0 + 96), clean(rec.get("player")), 20, FG, anchor="lm", max_w=room - date_w)
    if date:
        draw_text(draw, (x0 + TILE_W - 18, y0 + 96), date, 20, MUTED, anchor="rm")


def _draw_streak(img, draw, y: int, streak: tuple[str, int]) -> int:
    name, length = streak
    h = 96
    cards.panel(img, (PAD, y, WIDTH - PAD, y + h), cards.mix(PANEL, GOLD, 0.12), radius=18)
    cards.stripe(img, PAD, y, y + h, GOLD)
    draw_text(draw, (PAD + 32, y + h / 2), "ЛУЧШАЯ СЕРИЯ ПОБЕД", 20, GOLD, bold=True, anchor="lm")
    draw_text(draw, (PAD + 330, y + h / 2), clean(name) or "Игрок", 32, FG, bold=True, anchor="lm", max_w=520)
    draw_text(draw, (WIDTH - PAD - 32, y + h / 2), f"▲ {length} подряд", 36, GOLD, bold=True, anchor="rm")
    return y + h + 8
