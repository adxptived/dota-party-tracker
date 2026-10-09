"""Карточки про героев: герои игрока (+ позиции), любимые герои пати, герой и кто из пати на нём играл.

Чистые функции: данные — словарями (их собирает card_data), иконки героев и аватары — готовыми байтами;
сети и БД нет. Строка героя (`rows`): hero_id, name, games, wins, losses, winrate, kda, imp, gpm.
Позиция (`roles`): position, label, games, wins, losses, winrate, kda.
"""
from __future__ import annotations

from typing import Optional

from mmrbot import cards
from mmrbot.cards import (
    ACCENT, FG, GOLD, ICON_H, ICON_W, LOSS, MUTED, PAD, PANEL, WIDTH, WIN, clean, draw_text, signed,
)

ROW_H, ROW_GAP = 84, 6
HEAD_ROW_H = 34
LIMIT = 10
COL_WL, COL_BAR_W = 600, 200
COL_KDA, COL_IMP, COL_GPM = 930, 1038, 1150


def _heads(draw, y: int, first: str, first_x: int) -> int:
    draw_text(draw, (first_x, y + 12), first, 18, MUTED, anchor="lm")
    draw_text(draw, (COL_WL, y + 12), "ПОБЕДЫ · ВИНРЕЙТ", 18, MUTED, anchor="lm")
    for x, text in ((COL_KDA, "KDA"), (COL_IMP, "IMP"), (COL_GPM, "GPM")):
        draw_text(draw, (x, y + 12), text, 18, MUTED, anchor="mm")
    return y + HEAD_ROW_H


def _stat_columns(img, draw, mid: float, row: dict) -> None:
    """Общие колонки строки: победы–поражения с полоской, KDA, IMP, GPM."""
    wins, losses = row.get("wins") or 0, row.get("losses") or 0
    draw_text(draw, (COL_WL, mid - 14), f"{wins}–{losses}", 26, FG, bold=True, anchor="lm")
    cards.winrate_bar(img, (COL_WL, mid + 10, COL_WL + COL_BAR_W, mid + 22), wins, losses)
    draw_text(draw, (COL_WL + COL_BAR_W + 14, mid + 16), f"{round((row.get('winrate') or 0) * 100)}%", 22, MUTED, anchor="lm")
    draw_text(draw, (COL_KDA, mid), f"{row.get('kda', 0):.1f}", 28, FG, bold=True, anchor="mm")
    imp = row.get("imp")
    draw_text(draw, (COL_IMP, mid), signed(imp) if imp is not None else "—", 26, cards.delta_color(imp), bold=True, anchor="mm")
    gpm = row.get("gpm")
    draw_text(draw, (COL_GPM, mid), f"{gpm:.0f}" if gpm is not None else "—", 26, FG, anchor="mm")


def render_player_heroes_image(
    title: str, subtitle: Optional[str], badge: Optional[tuple[str, str]], rows: list, roles: Optional[list] = None,
    icons: Optional[dict] = None, hidden_note: Optional[str] = None, extra_heroes: int = 0, note: Optional[str] = None,
) -> bytes:
    """Герои игрока (до 10) и его позиции → PNG-байты. Без героев и без позиций — шапка и пояснение."""
    icons = icons or {}
    roles = roles or []
    canvas = cards.Canvas(300 + len(rows[:LIMIT]) * (ROW_H + ROW_GAP) + 120 + len(roles) * 64 + 160)
    img, draw = canvas.img, canvas.draw
    y = cards.header(img, draw, title, subtitle, badge)

    if rows:
        y = _heads(draw, y, "ГЕРОЙ", PAD + 60)
        for place, row in enumerate(rows[:LIMIT], start=1):
            cards.panel(img, (PAD, y, WIDTH - PAD, y + ROW_H), PANEL, radius=16)
            if place == 1:
                cards.stripe(img, PAD, y, y + ROW_H, GOLD)
            mid = y + ROW_H / 2
            draw_text(draw, (PAD + 30, mid), str(place), 24, cards.PLACE_COLORS.get(place, MUTED), bold=True, anchor="mm")
            cards.paste(img, cards.hero_icon(icons.get(row["hero_id"]), row["hero_id"]), PAD + 60, mid - ICON_H / 2)
            tx = PAD + 60 + ICON_W + 20
            draw_text(draw, (tx, mid - 14), clean(row["name"]), 26, FG, bold=True, anchor="lm", max_w=COL_WL - tx - 20)
            draw_text(draw, (tx, mid + 18), f"{row['games']} игр", 20, MUTED, anchor="lm")
            _stat_columns(img, draw, mid, row)
            y += ROW_H + ROW_GAP
        if extra_heroes > 0:
            draw_text(draw, (PAD + 10, y + 16), f"и ещё {extra_heroes} героев — полный список текстом", 20, MUTED, anchor="lm")
            y += 40
    elif not roles:
        cards.panel(img, (PAD, y, WIDTH - PAD, y + 110), PANEL, radius=18)
        draw_text(draw, (PAD + 28, y + 55), "За указанный период игр нет.", 28, MUTED, anchor="lm")
        y += 126
    if hidden_note:
        draw_text(draw, (PAD + 10, y + 18), clean(hidden_note), 20, GOLD, anchor="lm", max_w=WIDTH - 2 * PAD - 20)
        y += 44

    if roles:
        y += 12
        y = _draw_roles(img, draw, y, roles)
    if note:
        y = cards.footer(draw, y, note)
    return canvas.png(y)


def _draw_roles(img, draw, y: int, roles: list) -> int:
    h = 62 + len(roles) * 64 + 8
    cards.panel(img, (PAD, y, WIDTH - PAD, y + h), PANEL, radius=20)
    draw_text(draw, (PAD + 24, y + 30), "ПОЗИЦИИ", 18, MUTED, bold=True, anchor="lm")
    top = max((r["games"] for r in roles), default=1) or 1
    for i, role in enumerate(roles):
        cy = y + 62 + i * 64 + 26
        draw_text(draw, (PAD + 24, cy), f"P{role['position']}", 26, GOLD, bold=True, anchor="lm")
        draw_text(draw, (PAD + 90, cy), clean(role["label"]), 22, FG, anchor="lm", max_w=230)
        cards.bar(img, (PAD + 330, cy - 9, PAD + 630, cy + 9), role["games"] / top, ACCENT)
        draw_text(draw, (PAD + 652, cy), f"{role['games']} игр", 22, MUTED, anchor="lm")
        draw_text(draw, (COL_KDA - 20, cy), f"{round(role['winrate'] * 100)}%", 26, FG, bold=True, anchor="rm")
        draw_text(draw, (COL_KDA + 10, cy), f"KDA {role['kda']:.1f}", 22, MUTED, anchor="lm")
    return y + h + 8


# --- любимые герои пати --------------------------------------------------------------------------

PARTY_ROW_H = 112
CELL_X = (330, 640, 950)
CELL_ICON_W, CELL_ICON_H = 80, 45


def render_party_heroes_image(rows: list, icons: Optional[dict] = None, avatars: Optional[dict] = None,
                              note: Optional[str] = None) -> bytes:
    """Любимые герои пати: строка на игрока — аватар, ник и до трёх героев с иконкой, играми и винрейтом.

    rows: name, avatar, heroes [{hero_id, name, games, winrate}].
    """
    icons, avatars = icons or {}, avatars or {}
    canvas = cards.Canvas(260 + len(rows) * (PARTY_ROW_H + ROW_GAP) + 100)
    img, draw = canvas.img, canvas.draw
    y = cards.header(img, draw, "Любимые герои", "топ-3 по числу игр с начала отслеживания")
    for row in rows:
        cards.panel(img, (PAD, y, WIDTH - PAD, y + PARTY_ROW_H), PANEL, radius=16)
        mid = y + PARTY_ROW_H / 2
        name = clean(row.get("name")) or "Игрок"
        cards.paste(img, cards.avatar(avatars.get(row.get("avatar")), name, 64), PAD + 24, mid - 32)
        draw_text(draw, (PAD + 24 + 64 + 16, mid), name, 26, FG, bold=True, anchor="lm", max_w=170)
        heroes = row.get("heroes") or []
        if not heroes:
            draw_text(draw, (CELL_X[0], mid), "пока нет игр", 22, MUTED, anchor="lm")
        for hero, x in zip(heroes, CELL_X):
            cards.paste(img, cards.hero_icon(icons.get(hero["hero_id"]), hero["hero_id"], CELL_ICON_W, CELL_ICON_H, 8), x,
                        mid - CELL_ICON_H / 2)
            tx = x + CELL_ICON_W + 12
            room = WIDTH - PAD - 16 - tx if x == CELL_X[-1] else 205
            draw_text(draw, (tx, mid - 18), clean(hero["name"]), 20, FG, bold=True, anchor="lm", max_w=room)
            draw_text(draw, (tx, mid + 10), f"{hero['games']} игр", 19, MUTED, anchor="lm")
            wr = hero["winrate"]
            draw_text(draw, (tx, mid + 34), f"{round(wr * 100)}%", 20, WIN if wr >= 0.55 else LOSS if wr < 0.45 else FG,
                      bold=True, anchor="lm")
        y += PARTY_ROW_H + ROW_GAP
    if not rows:
        draw_text(draw, (PAD, y + 20), "Игроков пока нет.", 26, MUTED, anchor="lm")
        y += 50
    if note:
        y = cards.footer(draw, y, note)
    return canvas.png(y)


# --- герой и игроки пати на нём -------------------------------------------------------------------

def render_hero_image(
    hero_id, hero_title: str, period_label: str, rows: list, icons: Optional[dict] = None,
    avatars: Optional[dict] = None, note: Optional[str] = None,
) -> bytes:
    """Герой: крупная иконка и таблица игроков пати на нём. rows: name, avatar, games, wins, losses, winrate, kda, imp, gpm."""
    icons, avatars = icons or {}, avatars or {}
    canvas = cards.Canvas(420 + len(rows) * (ROW_H + ROW_GAP) + 100)
    img, draw = canvas.img, canvas.draw
    big_w, big_h = 224, 126
    cards.paste(img, cards.hero_icon(icons.get(hero_id), hero_id, big_w, big_h, 14), PAD, PAD)
    draw_text(draw, (PAD + big_w + 28, PAD + 38), clean(hero_title), 44, FG, bold=True, anchor="lm", max_w=640)
    draw_text(draw, (PAD + big_w + 28, PAD + 90), "кто из пати играл на этом герое", 24, MUTED, anchor="lm")
    cards.chip(img, draw, WIDTH - PAD, PAD + 30, period_label.upper(), ACCENT, size=22, align="right", pad=18)
    y = PAD + big_h + 28
    if not rows:
        cards.panel(img, (PAD, y, WIDTH - PAD, y + 110), PANEL, radius=18)
        draw_text(draw, (PAD + 28, y + 55), "На этом герое участники пати не играли.", 26, MUTED, anchor="lm")
        y += 126
    else:
        y = _heads(draw, y, "ИГРОК", PAD + 60)
    for place, row in enumerate(rows, start=1):
        cards.panel(img, (PAD, y, WIDTH - PAD, y + ROW_H), PANEL, radius=16)
        if place == 1:
            cards.stripe(img, PAD, y, y + ROW_H, GOLD)
        mid = y + ROW_H / 2
        draw_text(draw, (PAD + 30, mid), str(place), 24, cards.PLACE_COLORS.get(place, MUTED), bold=True, anchor="mm")
        name = clean(row.get("name")) or "Игрок"
        cards.paste(img, cards.avatar(avatars.get(row.get("avatar")), name, 60), PAD + 60, mid - 30)
        draw_text(draw, (PAD + 60 + 60 + 18, mid - 14), name, 26, FG, bold=True, anchor="lm", max_w=COL_WL - 190)
        draw_text(draw, (PAD + 60 + 60 + 18, mid + 18), f"{row['games']} игр", 20, MUTED, anchor="lm")
        _stat_columns(img, draw, mid, row)
        y += ROW_H + ROW_GAP
    if note:
        y = cards.footer(draw, y, note)
    return canvas.png(y)
