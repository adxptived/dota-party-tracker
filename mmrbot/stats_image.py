"""Рейтинг пати картинкой (/stats, «Сегодня», «Неделя», «Месяц»): таблица игроков и блок «Стата пати».

Таблица: место (1–3 — золото/серебро/бронза), аватар, ник и значок ранга, крупное число (≈MMR или ±за период)
с пояснением, победы–поражения с полоской винрейта, форма точками, топ-герой иконкой. Ниже — плитки
(сегодня, неделя, лидер…), рекорды с иконками героев и награды. Чистая функция: данные приходят словарями
(их собирает service.py), иконки и аватары — готовыми байтами; сети и БД здесь нет.

Строка таблицы (`rows`): name, avatar (url), rank_tier, rank_text, big, big_color, sub, sub_color, wins, losses,
form [bool], hero_id, hero_note. Плитка (`tiles`): label, value, sub, color. Рекорд (`records`): label, value,
player, hero_id. Награда (`awards`): title, player, detail.
"""
from __future__ import annotations

from typing import Optional

from mmrbot import cards
from mmrbot.cards import (
    ACCENT, BG, FG, GOLD, LOSS, MUTED, PAD, PANEL, PANEL_HI, PLACE_COLORS, WIDTH, WIN, clean, draw_text,
)

ROW_H, ROW_GAP = 96, 8
HEAD_ROW_H = 36
AVATAR = 64
NAME_X = PAD + 78 + AVATAR + 16
NAME_MAX_W = 330
BIG_RIGHT = 700
WL_X = 740
BAR_W = 140
FORM_X = 962
HERO_W, HERO_H = 80, 45
HERO_X = WIDTH - PAD - 24 - HERO_W
FORM_MAX = 10
TILE_GAP = 16


def _place(img, draw, cx: float, cy: float, place: int) -> None:
    color = PLACE_COLORS.get(place)
    cards.dot(img, cx, cy, 22, color or PANEL_HI)
    draw_text(draw, (cx, cy), str(place), 24, BG if color else MUTED, bold=True, anchor="mm")


def render_stats_image(
    title: str, subtitle: Optional[str], badge: Optional[tuple[str, str]], rows: list, tiles: Optional[list] = None,
    records: Optional[list] = None, awards: Optional[list] = None, note: Optional[str] = None,
    icons: Optional[dict] = None, avatars: Optional[dict] = None,
) -> bytes:
    """Рейтинг → PNG-байты. icons: {hero_id: байты}; avatars: {url: байты}; отсутствующие рисуются заглушками."""
    icons, avatars = icons or {}, avatars or {}
    tiles, records, awards = tiles or [], records or [], awards or []
    canvas = cards.Canvas(400 + len(rows) * (ROW_H + ROW_GAP) + 240 + len(records) * 40 + len(awards) * 60)
    img, draw = canvas.img, canvas.draw

    y = cards.header(img, draw, title, subtitle, badge)
    if rows:
        draw_text(draw, (NAME_X, y + 10), "ИГРОК", 18, MUTED, anchor="lm")
        draw_text(draw, (BIG_RIGHT, y + 10), "MMR", 18, MUTED, anchor="rm")
        draw_text(draw, (WL_X, y + 10), "РЕЗУЛЬТАТ", 18, MUTED, anchor="lm")
        draw_text(draw, (FORM_X, y + 10), "ФОРМА", 18, MUTED, anchor="lm")
        draw_text(draw, (HERO_X + HERO_W / 2, y + 10), "ГЕРОЙ", 18, MUTED, anchor="mm")
        y += HEAD_ROW_H
    for place, row in enumerate(rows, start=1):
        _draw_row(img, draw, y, place, row, icons, avatars)
        y += ROW_H + ROW_GAP

    if tiles:
        y += 14
        y = _draw_tiles(img, draw, y, tiles)
    if records:
        y += 6
        y = _draw_records(img, draw, y, records, icons)
    if awards:
        y += 14
        y = _draw_awards(img, draw, y, awards)
    if note:
        y = cards.footer(draw, y, note)
    return canvas.png(y)


def _draw_row(img, draw, y: int, place: int, row: dict, icons: dict, avatars: dict) -> None:
    cards.panel(img, (PAD, y, WIDTH - PAD, y + ROW_H), PANEL, radius=16)
    if place == 1:
        cards.stripe(img, PAD, y, y + ROW_H, GOLD)
    mid = y + ROW_H / 2
    _place(img, draw, PAD + 44, mid, place)

    name = clean(row.get("name")) or "Игрок"
    cards.paste(img, cards.avatar(avatars.get(row.get("avatar")), name, AVATAR), PAD + 78, mid - AVATAR / 2)

    draw_text(draw, (NAME_X, mid - 16), name, 28, FG, bold=True, anchor="lm", max_w=NAME_MAX_W)
    cards.paste(img, cards.rank_badge(row.get("rank_tier"), 32), NAME_X, mid + 2)
    draw_text(draw, (NAME_X + 42, mid + 18), clean(row.get("rank_text")), 20, MUTED, anchor="lm", max_w=NAME_MAX_W - 42)

    draw_text(draw, (BIG_RIGHT, mid - 12), clean(row.get("big")), 36, row.get("big_color") or FG, bold=True, anchor="rm")
    if row.get("sub"):
        draw_text(draw, (BIG_RIGHT, mid + 22), clean(row["sub"]), 20, row.get("sub_color") or MUTED, anchor="rm", max_w=230)

    wins, losses = row.get("wins") or 0, row.get("losses") or 0
    games = wins + losses
    if games:
        draw_text(draw, (WL_X, mid - 14), f"{wins}–{losses}", 28, FG, bold=True, anchor="lm")
        cards.winrate_bar(img, (WL_X, mid + 10, WL_X + BAR_W, mid + 22), wins, losses)
        draw_text(draw, (WL_X + BAR_W + 12, mid + 16), f"{round(wins * 100 / games)}%", 20, MUTED, anchor="lm")
    else:
        draw_text(draw, (WL_X, mid), "игр нет", 22, MUTED, anchor="lm")

    form = list(row.get("form") or [])[-FORM_MAX:]
    if form:
        cards.form_dots(img, FORM_X, mid, form, r=7, gap=4)

    hero_id = row.get("hero_id")
    if hero_id:
        cards.paste(img, cards.hero_icon(icons.get(hero_id), hero_id, HERO_W, HERO_H, 8), HERO_X, mid - HERO_H / 2 - 8)
        draw_text(draw, (HERO_X + HERO_W / 2, mid + HERO_H / 2 + 6), clean(row.get("hero_note")), 18, MUTED,
                  anchor="mm", max_w=HERO_W + 20)


def _draw_tiles(img, draw, y: int, tiles: list) -> int:
    """Плитки показателей в ряд (до 4)."""
    tiles = tiles[:4]
    w = (WIDTH - 2 * PAD - TILE_GAP * (len(tiles) - 1)) / len(tiles)
    for i, tile in enumerate(tiles):
        x0 = PAD + i * (w + TILE_GAP)
        cards.tile(img, draw, (x0, y, x0 + w, y + 124), tile.get("label", ""), tile.get("value", "—"), tile.get("sub"),
                   tile.get("color") or FG, value_size=34)
    return y + 124 + 14


def _draw_records(img, draw, y: int, records: list, icons: dict) -> int:
    """Рекорды: плитка с иконкой героя, значением и игроком (до 3 в ряд)."""
    records = records[:6]
    per_row = 3
    w = (WIDTH - 2 * PAD - TILE_GAP * (per_row - 1)) / per_row
    for i, rec in enumerate(records):
        x0 = PAD + (i % per_row) * (w + TILE_GAP)
        y0 = y + (i // per_row) * (96 + TILE_GAP)
        cards.panel(img, (x0, y0, x0 + w, y0 + 96), PANEL, radius=16)
        hero_id = rec.get("hero_id")
        cards.paste(img, cards.hero_icon(icons.get(hero_id), hero_id, 96, 54, 8), x0 + 16, y0 + 21)
        tx = x0 + 128
        draw_text(draw, (tx, y0 + 22), clean(rec.get("label")), 18, MUTED, anchor="lm", max_w=w - 144)
        draw_text(draw, (tx, y0 + 52), clean(rec.get("value")), 28, GOLD, bold=True, anchor="lm", max_w=w - 144)
        draw_text(draw, (tx, y0 + 80), clean(rec.get("player")), 20, FG, anchor="lm", max_w=w - 144)
    rows_used = (len(records) + per_row - 1) // per_row
    return y + rows_used * (96 + TILE_GAP)


def _draw_awards(img, draw, y: int, awards: list) -> int:
    """Награды: заголовок блока и по строке «название — игрок (деталь)»."""
    awards = awards[:5]
    height = 56 + len(awards) * 48
    cards.panel(img, (PAD, y, WIDTH - PAD, y + height), PANEL, radius=16)
    draw_text(draw, (PAD + 24, y + 30), "НАГРАДЫ", 20, ACCENT, bold=True, anchor="lm")
    for i, award in enumerate(awards):
        cy = y + 56 + i * 48 + 20
        draw_text(draw, (PAD + 24, cy), clean(award.get("title")), 24, FG, bold=True, anchor="lm", max_w=420)
        draw_text(draw, (PAD + 470, cy), clean(award.get("player")), 24, GOLD, bold=True, anchor="lm", max_w=300)
        draw_text(draw, (PAD + 790, cy), clean(award.get("detail")), 20, MUTED, anchor="lm", max_w=WIDTH - 2 * PAD - 814)
    return y + height + 8


# Цвета для вызывающего кода: исход/дельта.
POSITIVE, NEGATIVE, NEUTRAL = WIN, LOSS, MUTED
