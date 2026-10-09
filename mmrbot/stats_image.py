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
    """Место: у призёров — цветной жетон (золото/серебро/бронза), у остальных — просто номер."""
    color = PLACE_COLORS.get(place)
    if color:
        cards.dot(img, cx, cy, 21, color)
        cards.dot(img, cx, cy, 17, cards.mix(color, "#ffffff", 0.22))
    draw_text(draw, (cx, cy), str(place), 24, BG if color else MUTED, bold=True, anchor="mm")


def render_stats_image(
    title: str, subtitle: Optional[str], badge: Optional[tuple[str, str]], rows: list, tiles: Optional[list] = None,
    records: Optional[list] = None, awards: Optional[list] = None, note: Optional[str] = None,
    icons: Optional[dict] = None, avatars: Optional[dict] = None, big_label: str = "MMR",
) -> bytes:
    """Рейтинг → PNG-байты. icons: {hero_id: байты}; avatars: {url: байты}; отсутствующие рисуются заглушками.

    big_label — подпись столбца крупных чисел («MMR» для рейтинга, «±MMR» для периода); столбцы «Форма» и «Герой»
    подписаны, только если хоть у одной строки есть что в них показать.
    """
    icons, avatars = icons or {}, avatars or {}
    tiles, records, awards = tiles or [], records or [], awards or []
    canvas = cards.Canvas(400 + len(rows) * (ROW_H + ROW_GAP) + 240 + len(records) * 40 + len(awards) * 60 + 80)
    img, draw = canvas.img, canvas.draw

    y = cards.header(img, draw, title, subtitle, badge)
    if rows:
        draw_text(draw, (NAME_X, y + 10), "ИГРОК", 18, MUTED, anchor="lm")
        draw_text(draw, (BIG_RIGHT, y + 10), big_label, 18, MUTED, anchor="rm")
        draw_text(draw, (WL_X, y + 10), "РЕЗУЛЬТАТ", 18, MUTED, anchor="lm")
        if any(r.get("form") for r in rows):
            draw_text(draw, (FORM_X, y + 10), "ФОРМА", 18, MUTED, anchor="lm")
        if any(r.get("hero_id") for r in rows):
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
    box = (PAD, y, WIDTH - PAD, y + ROW_H)
    if place == 1:  # лидер: золотой отсвет слева и полоса
        cards.gradient_panel(img, box, cards.mix(PANEL, GOLD, 0.2), PANEL, radius=16, outline=cards.mix(PANEL, GOLD, 0.3))
        cards.stripe(img, PAD, y + 14, y + ROW_H - 14, GOLD)
    else:
        cards.panel(img, box, PANEL, radius=16)
    mid = y + ROW_H / 2
    _place(img, draw, PAD + 44, mid, place)

    name = clean(row.get("name")) or "Игрок"
    cards.paste(img, cards.avatar(avatars.get(row.get("avatar")), name, AVATAR), PAD + 78, mid - AVATAR / 2)

    draw_text(draw, (NAME_X, mid - 17), name, 28, FG, bold=True, anchor="lm", max_w=NAME_MAX_W)
    cards.paste(img, cards.rank_badge(row.get("rank_tier"), 30), NAME_X, mid + 3)
    draw_text(draw, (NAME_X + 40, mid + 18), clean(row.get("rank_text")), 20, MUTED, anchor="lm", max_w=NAME_MAX_W - 40)

    cards.value_text(draw, (BIG_RIGHT, mid - 13), row.get("big"), 38, row.get("big_color") or FG)
    if row.get("sub"):
        cards.delta_text(draw, (BIG_RIGHT, mid + 23), row["sub"], 20, row.get("sub_color") or MUTED, max_w=230)

    wins, losses = row.get("wins") or 0, row.get("losses") or 0
    games = wins + losses
    if games:
        draw_text(draw, (WL_X, mid - 15), f"{wins}–{losses}", 28, FG, bold=True, anchor="lm")
        cards.winrate_bar(img, (WL_X, mid + 12, WL_X + BAR_W, mid + 22), wins, losses)
        draw_text(draw, (WL_X + BAR_W + 12, mid + 17), f"{round(wins * 100 / games)}%", 20, MUTED, anchor="lm")
    else:
        draw_text(draw, (WL_X, mid), "игр нет", 22, MUTED, anchor="lm")

    form = list(row.get("form") or [])[-FORM_MAX:]
    if form:
        cards.form_dots(img, FORM_X, mid, form, r=8, gap=5)

    hero_id = row.get("hero_id")
    if hero_id:
        cards.paste(img, cards.hero_icon(icons.get(hero_id), hero_id, HERO_W, HERO_H, 8), HERO_X, mid - HERO_H / 2 - 9)
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
    per_row = min(3, len(records)) or 1
    w = (WIDTH - 2 * PAD - TILE_GAP * (per_row - 1)) / per_row
    for i, rec in enumerate(records):
        x0 = PAD + (i % per_row) * (w + TILE_GAP)
        y0 = y + (i // per_row) * (96 + TILE_GAP)
        cards.panel(img, (x0, y0, x0 + w, y0 + 96), PANEL, radius=16)
        hero_id = rec.get("hero_id")
        cards.paste(img, cards.hero_icon(icons.get(hero_id), hero_id, 96, 54, 8), x0 + 16, y0 + 21)
        tx = x0 + 128
        draw_text(draw, (tx, y0 + 22), clean(rec.get("label")), 18, MUTED, anchor="lm", max_w=w - 144)
        draw_text(draw, (tx, y0 + 50), clean(rec.get("value")), 26, GOLD, bold=True, anchor="lm", max_w=w - 144)
        draw_text(draw, (tx, y0 + 78), clean(rec.get("player")), 19, FG, anchor="lm", max_w=w - 144)
    rows_used = (len(records) + per_row - 1) // per_row
    return y + rows_used * (96 + TILE_GAP)


AWARD_H = 104


def _medal(img, cx: float, cy: float, r: int = 22) -> None:
    """Значок награды: золотой жетон со звездой."""
    from PIL import ImageDraw
    cards.dot(img, cx, cy, r, cards.mix(PANEL_HI, GOLD, 0.28))
    ImageDraw.Draw(img).polygon(cards._star_points(cx, cy + 0.5, r * 0.62, r * 0.27), fill=GOLD)


def _draw_awards(img, draw, y: int, awards: list, title: str = "НАГРАДЫ") -> int:
    """Награды: подпись блока и плитки «за что — кому — подробность» (до 3 в ряд, как рекорды)."""
    awards = awards[:6]
    draw_text(draw, (PAD + 6, y + 12), title, 20, ACCENT, bold=True, anchor="lm")
    y += 34
    per_row = min(3, len(awards)) or 1
    w = (WIDTH - 2 * PAD - TILE_GAP * (per_row - 1)) / per_row
    for i, award in enumerate(awards):
        x0 = PAD + (i % per_row) * (w + TILE_GAP)
        y0 = y + (i // per_row) * (AWARD_H + TILE_GAP)
        cards.panel(img, (x0, y0, x0 + w, y0 + AWARD_H), PANEL, radius=16)
        _medal(img, x0 + 44, y0 + AWARD_H / 2)
        tx, room = x0 + 84, w - 84 - 18
        draw_text(draw, (tx, y0 + 24), clean(award.get("title")), 18, MUTED, anchor="lm", max_w=room)
        draw_text(draw, (tx, y0 + 53), clean(award.get("player")), 26, FG, bold=True, anchor="lm", max_w=room)
        draw_text(draw, (tx, y0 + 82), clean(award.get("detail")), 19, GOLD, anchor="lm", max_w=room)
    rows_used = (len(awards) + per_row - 1) // per_row
    return y + rows_used * (AWARD_H + TILE_GAP) - TILE_GAP + 8


# Цвета для вызывающего кода: исход/дельта.
POSITIVE, NEGATIVE, NEUTRAL = WIN, LOSS, MUTED
