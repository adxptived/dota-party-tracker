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

ROW_H, GAP = 84, cards.ROW_GAP
NUM_D = 46  # кружок с номером: он же подпись кнопки
KDA_X = 735  # левее середины: правее K/D/A — итоговый билд матча
RIGHT = WIDTH - PAD - 24


def render_match_list_image(title: str, subtitle: Optional[str], rows: list, icons: Optional[dict] = None,
                            badge: Optional[tuple[str, str]] = None, note: Optional[str] = None,
                            item_icons: Optional[dict] = None) -> bytes:
    """Страница матчей → PNG-байты; пустая страница — шапка и пояснение. item_icons: {item_id: PNG-байты}."""
    icons, gear = icons or {}, item_icons or {}
    canvas = cards.Canvas(200 + max(len(rows), 1) * (ROW_H + GAP) + 80)
    img, draw = canvas.img, canvas.draw
    y = cards.header(img, draw, title, subtitle, badge)
    if not rows:
        cards.panel(img, (PAD, y, WIDTH - PAD, y + 100), PANEL, radius=cards.R_CARD)
        draw_text(draw, (PAD + 28, y + 50), "Ранкед-матчей пока нет.", 26, MUTED, anchor="lm")
        y += 116
    for row in rows:
        _draw_row(img, draw, y, row, icons, gear)
        y += ROW_H + GAP
    if note:
        y = cards.footer(draw, y, note)
    return canvas.png(y)


def _draw_row(img, draw, y: int, row: dict, icons: dict, gear: Optional[dict] = None) -> None:
    won = bool(row.get("won"))
    color = WIN if won else LOSS
    current = bool(row.get("current"))
    fill = cards.mix(PANEL, ACCENT, 0.12) if current else PANEL
    cards.gradient_panel(img, (PAD, y, WIDTH - PAD, y + ROW_H), cards.mix(fill, color, 0.12), fill, radius=cards.R_CARD,
                         outline=cards.mix(fill, ACCENT, 0.6) if current else None)
    cards.edge_stripe(img, PAD, y, y + ROW_H, color)
    mid = y + ROW_H / 2

    cx = PAD + 26 + NUM_D / 2
    cards.dot(img, cx, mid, NUM_D / 2, cards.mix(fill, FG, 0.9) if current else cards.mix(fill, "#ffffff", 0.12))
    draw_text(draw, (cx, mid), str(row.get("n", "")), 24, BG if current else FG, bold=True, anchor="mm", track=False)

    x = PAD + 26 + NUM_D + 20
    cards.paste(img, cards.hero_icon(icons.get(row.get("hero_id")), row.get("hero_id")), x, mid - ICON_H / 2)
    cards.hero_badges(img, draw, x, mid - ICON_H / 2, ICON_W, ICON_H, row.get("level"), row.get("plus_xp"))
    tx = x + ICON_W + 18
    room = KDA_X - 90 - tx
    draw_text(draw, (tx, mid - 14), clean(row.get("name")) or "—", 24, FG, bold=True, anchor="lm", max_w=room, shrink=18)
    sub = " · ".join(part for part in (clean(row.get("when")), f"{row['minutes']} мин" if row.get("minutes") else None,
                                         clean(row.get("extra"))) if part)
    draw_text(draw, (tx, mid + 17), sub, 18, MUTED, anchor="lm", max_w=room, shrink=16, track=False)

    cards.kda(draw, KDA_X, mid, row.get("kills"), row.get("deaths"), row.get("assists"), 30)

    x = RIGHT
    delta = row.get("delta")
    if delta is not None:  # исход и так виден по цвету полосы, фона и ±MMR — отдельная плашка не нужна
        text = signed(delta)
        draw_text(draw, (x, mid), text, 28, cards.delta_color(delta), bold=True, anchor="rm", track=False)
        x -= cards.text_width(text, 28, True, False) + 14
        if row.get("double_down"):
            x -= cards.chip(img, draw, x, mid, "×2", GOLD, size=16, pad=8, align="right", base=fill) + 10
    else:
        x -= cards.chip(img, draw, x, mid, "победа" if won else "поражение", color, size=18, pad=12, align="right",
                        base=fill) + 14
    if row.get("items"):
        _draw_items(img, draw, KDA_X + 80, x - 18, mid, row, gear or {}, fill)


ITEM_W, ITEM_H, ITEM_GAP = 44, 32, 4


def _draw_items(img, draw, left: float, right: float, mid: float, row: dict, gear: dict, fill: str) -> None:
    """Итоговый билд матча (из сохранённых): 6 слотов и нейтралка кружком, прижаты вправо к ±MMR."""
    from mmrbot.alert_image import _item_icon, _neutral_icon
    items = list(row.get("items") or [])[:6]
    neutral = row.get("neutral_item")
    has_neutral = isinstance(neutral, int) and not isinstance(neutral, bool) and neutral
    scale = min(1.0, (right - left) / (6 * (ITEM_W + ITEM_GAP) + 6 + ITEM_H))
    if scale < 0.6:  # не влезает даже мелко — лучше без билда, чем кашей
        return
    w, h, gap = round(ITEM_W * scale), round(ITEM_H * scale), max(2, round(ITEM_GAP * scale))
    x = right - (6 * (w + gap) + 6 + h)
    empty = cards.mix(fill, "#ffffff", 0.05)
    for i in range(6):
        if i < len(items):
            cards.paste(img, _item_icon(gear.get(items[i]), w, h, 4), x, mid - h / 2)
        else:
            cards.panel(img, (x, mid - h / 2, x + w, mid + h / 2), empty, radius=4)
        x += w + gap
    x += 6
    if has_neutral:
        cards.paste(img, _neutral_icon(gear.get(neutral), h), x, mid - h / 2)
    else:
        cards.panel(img, (x, mid - h / 2, x + h, mid + h / 2), empty, radius=h // 2)
