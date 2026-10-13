"""Матчи игрока картинкой (кнопка «📜 Матчи»): страница до 10 игр, у каждой — номер, под которым её открывает
кнопка с той же цифрой, иконка героя, герой и позиция, исход, K/D/A, ±MMR, длительность и дата.

Чистая функция: строки готовит card_data.match_list_rows, иконки героев приходят байтами; сети и БД нет.
Строка: n, hero_id, name, won, kills, deaths, assists, delta (None — ±MMR не показываем), double_down,
minutes, when, extra (GPM и т.п., необязательно), current (открытый сейчас матч — подсвечен).
"""
from __future__ import annotations

from typing import Optional

from mmrbot import cards
from mmrbot.cards import ACCENT, BG, FG, GOLD, ICON_H, ICON_W, LOSS, MUTED, PAD, PANEL, WIDTH, WIN, clean, draw_text, signed

ROW_H, GAP = 84, 8
NUM_D = 46  # кружок с номером: он же подпись кнопки
KDA_X = 770
RIGHT = WIDTH - PAD - 24


def render_match_list_image(title: str, subtitle: Optional[str], rows: list, icons: Optional[dict] = None,
                            badge: Optional[tuple[str, str]] = None, note: Optional[str] = None) -> bytes:
    """Страница матчей → PNG-байты; пустая страница — шапка и пояснение."""
    icons = icons or {}
    canvas = cards.Canvas(200 + max(len(rows), 1) * (ROW_H + GAP) + 80)
    img, draw = canvas.img, canvas.draw
    y = cards.header(img, draw, title, subtitle, badge)
    if not rows:
        cards.panel(img, (PAD, y, WIDTH - PAD, y + 100), PANEL, radius=18)
        draw_text(draw, (PAD + 28, y + 50), "Ранкед-матчей пока нет.", 26, MUTED, anchor="lm")
        y += 116
    for row in rows:
        _draw_row(img, draw, y, row, icons)
        y += ROW_H + GAP
    if note:
        y = cards.footer(draw, y, note)
    return canvas.png(y)


def _draw_row(img, draw, y: int, row: dict, icons: dict) -> None:
    won = bool(row.get("won"))
    color = WIN if won else LOSS
    current = bool(row.get("current"))
    fill = cards.mix(PANEL, ACCENT, 0.12) if current else PANEL
    cards.gradient_panel(img, (PAD, y, WIDTH - PAD, y + ROW_H), cards.mix(fill, color, 0.12), fill, radius=16,
                         outline=cards.mix(fill, ACCENT, 0.6) if current else None)
    cards.stripe(img, PAD, y + 14, y + ROW_H - 14, color)
    mid = y + ROW_H / 2

    cx = PAD + 26 + NUM_D / 2
    cards.dot(img, cx, mid, NUM_D / 2, cards.mix(fill, FG, 0.9) if current else cards.mix(fill, "#ffffff", 0.12))
    draw_text(draw, (cx, mid), str(row.get("n", "")), 24, BG if current else FG, bold=True, anchor="mm", track=False)

    x = PAD + 26 + NUM_D + 20
    cards.paste(img, cards.hero_icon(icons.get(row.get("hero_id")), row.get("hero_id")), x, mid - ICON_H / 2)
    cards.hero_badges(img, draw, x, mid - ICON_H / 2, ICON_W, ICON_H, row.get("level"), row.get("plus_xp"))
    tx = x + ICON_W + 18
    room = KDA_X - 110 - tx
    draw_text(draw, (tx, mid - 14), clean(row.get("name")) or "—", 24, FG, bold=True, anchor="lm", max_w=room, shrink=18)
    sub = "  ·  ".join(part for part in (clean(row.get("when")), f"{row['minutes']} мин" if row.get("minutes") else None,
                                         clean(row.get("extra"))) if part)
    draw_text(draw, (tx, mid + 17), sub, 18, MUTED, anchor="lm", max_w=room, shrink=15, track=False)

    cards.kda(draw, KDA_X, mid, row.get("kills"), row.get("deaths"), row.get("assists"), 30)

    x = RIGHT
    delta = row.get("delta")
    if delta is not None:
        text = signed(delta)
        draw_text(draw, (x, mid), text, 28, cards.delta_color(delta), bold=True, anchor="rm", track=False)
        x -= cards.text_width(text, 28, True, False) + 14
        if row.get("double_down"):
            x -= cards.chip(img, draw, x, mid, "×2", GOLD, size=16, pad=8, align="right", base=fill) + 10
    cards.chip(img, draw, x, mid, "победа" if won else "поражение", color, size=18, pad=12, align="right", base=fill)
