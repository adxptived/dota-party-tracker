"""Карточка «Соперники и союзники»: четыре списка героев — против кого тяжело и легко, с кем в команде хуже и лучше.

Чистая функция: данные — словарём (matchups.player_matchups / party_matchups + имена героев), иконки героев —
готовыми байтами; сети и БД нет.
"""
from __future__ import annotations

from typing import Optional

from mmrbot import cards
from mmrbot.cards import ACCENT, FG, LOSS, MUTED, PAD, PANEL, WIDTH, WIN, clean, draw_text

GAP = 16
COL_W = (WIDTH - 2 * PAD - GAP) // 2
ROW_H = 62
HEAD_H = 58
ICON_W, ICON_H = 80, 45
ROWS = 5

# (ключ отчёта, заголовок, цвет акцента) — по рядам: соперники, союзники; слева «плохо», справа «хорошо».
BLOCKS = (
    (("hard", "ТЯЖЁЛЫЕ СОПЕРНИКИ", LOSS), ("easy", "УДОБНЫЕ СОПЕРНИКИ", WIN)),
    (("bad_allies", "С НИМИ ХУЖЕ", LOSS), ("good_allies", "С НИМИ ЛУЧШЕ", WIN)),
)
HINTS = {"hard": "против них", "easy": "против них", "bad_allies": "в своей команде", "good_allies": "в своей команде"}


def _block(img, draw, x: int, y: int, title: str, hint: str, color: str, rows: list, icons: dict, height: int) -> None:
    cards.panel(img, (x, y, x + COL_W, y + height), PANEL, radius=18)
    cards.stripe(img, x, y + 14, y + HEAD_H - 14, color)
    draw_text(draw, (x + 24, y + HEAD_H / 2), title, 18, FG, bold=True, anchor="lm")
    draw_text(draw, (x + COL_W - 22, y + HEAD_H / 2), hint, 18, MUTED, anchor="rm")
    if not rows:
        draw_text(draw, (x + 24, y + HEAD_H + (height - HEAD_H) / 2 - 6), "пока мало игр", 22, MUTED, anchor="lm")
        return
    for i, row in enumerate(rows[:ROWS]):
        mid = y + HEAD_H + i * ROW_H + ROW_H / 2 - 4
        if i:
            img.paste(cards.mix(PANEL, "#ffffff", 0.05), (x + 22, round(mid - ROW_H / 2), x + COL_W - 22, round(mid - ROW_H / 2) + 1))
        cards.paste(img, cards.hero_icon(icons.get(row["hero_id"]), row["hero_id"], ICON_W, ICON_H, 8), x + 22, mid - ICON_H / 2)
        right = x + COL_W - 22
        pct = f"{round(row['winrate'] * 100)}%"
        draw_text(draw, (right, mid), pct, 26, WIN if row["winrate"] >= 0.5 else LOSS, bold=True, anchor="rm")
        score_x = right - 86
        draw_text(draw, (score_x, mid), f"{row['wins']}–{row['losses']}", 22, MUTED, anchor="rm")
        name_x = x + 22 + ICON_W + 16
        draw_text(draw, (name_x, mid), clean(row.get("name")) or "?", 24, FG, bold=True, anchor="lm",
                  max_w=score_x - cards.text_width(f"{row['wins']}–{row['losses']}", 22) - 16 - name_x)


def render_matchups_image(view: dict, icons: Optional[dict] = None, note: Optional[str] = None) -> bytes:
    """view: title, subtitle, badge (текст периода), hard/easy/good_allies/bad_allies — строки {hero_id, name, wins,
    losses, winrate}, footer — пояснение под карточкой."""
    icons = icons or {}
    longest = max((len(view.get(key) or []) for row in BLOCKS for key, _, _ in row), default=0)
    height = HEAD_H + max(min(longest, ROWS), 1) * ROW_H + 10
    canvas = cards.Canvas(260 + 2 * (height + GAP) + 140)
    img, draw = canvas.img, canvas.draw
    badge = (view["badge"], ACCENT) if view.get("badge") else None
    y = cards.header(img, draw, view.get("title") or "Соперники и союзники", view.get("subtitle"), badge)
    for pair in BLOCKS:
        for col, (key, title, color) in enumerate(pair):
            _block(img, draw, PAD + col * (COL_W + GAP), y, title, HINTS[key], color, view.get(key) or [], icons, height)
        y += height + GAP
    y -= GAP - 6
    if view.get("footer"):
        y = cards.footer(draw, y, view["footer"])
    if note:
        y = cards.footer(draw, y, note)
    return canvas.png(y)
