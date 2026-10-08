"""Карточка игрока картинкой (/player): шапка с аватаром, рангом и ≈MMR, плитки показателей, динамика MMR и форма,
соло против группы, топ-герои, последняя игра, профиль навыков, предупреждения плашкой.

Чистая функция: данные приходят словарём (его собирает card_data.player_card), иконки героев и аватар — готовыми
байтами; сети и БД здесь нет. Ключи словаря — в card_data.player_card.
"""
from __future__ import annotations

from typing import Optional

from mmrbot import cards
from mmrbot.cards import (
    ACCENT, BG, FG, GOLD, ICON_H, ICON_W, LOSS, MUTED, PAD, PANEL, WIDTH, WIN, clean, draw_text, signed,
)

HEADER_H = 190
TILE_H = 112
GAP = 16
LEFT_W = 760
RIGHT_W = WIDTH - 2 * PAD - LEFT_W - GAP
HERO_ROW_H = 84


def _section(img, draw, box, title: str) -> tuple[int, int]:
    """Панель с заголовком раздела; возвращает (x0, y0) левого верхнего угла содержимого."""
    cards.panel(img, box, PANEL, radius=20)
    draw_text(draw, (box[0] + 24, box[1] + 28), title.upper(), 18, MUTED, bold=True, anchor="lm")
    return box[0] + 24, box[1] + 56


def render_player_image(card: dict, icons: Optional[dict] = None, avatars: Optional[dict] = None) -> bytes:
    """Карточка игрока → PNG-байты. icons: {hero_id: байты}; avatars: {url: байты}; нет данных — заглушки/пропуск блока."""
    icons, avatars = icons or {}, avatars or {}
    canvas = cards.Canvas(2600)
    img, draw = canvas.img, canvas.draw
    y = PAD

    y = _draw_header(img, draw, y, card, avatars) + GAP
    for text in card.get("warnings") or []:
        cards.panel(img, (PAD, y, WIDTH - PAD, y + 56), cards.mix(PANEL, GOLD, 0.16), radius=14)
        draw_text(draw, (PAD + 22, y + 28), clean(text), 21, GOLD, anchor="lm", max_w=WIDTH - 2 * PAD - 44)
        y += 56 + 10
    if card.get("warnings"):
        y += GAP - 10

    tiles = (card.get("tiles") or [])[:6]
    if tiles:
        w = (WIDTH - 2 * PAD - GAP * (len(tiles) - 1)) / len(tiles)
        for i, tile in enumerate(tiles):
            x0 = PAD + i * (w + GAP)
            cards.tile(img, draw, (x0, y, x0 + w, y + TILE_H), tile.get("label", ""), tile.get("value", "—"),
                       tile.get("sub"), tile.get("color") or FG, value_size=32, fill=PANEL)
        y += TILE_H + GAP

    if card.get("series") or card.get("form") or card.get("split") or card.get("hours"):
        y = _draw_trend_row(img, draw, y, card) + GAP

    heroes, last = card.get("heroes") or [], card.get("last_game")
    if heroes or last:
        y = _draw_heroes_row(img, draw, y, heroes, last, icons) + GAP

    skills = card.get("skills") or []
    if skills:
        y = _draw_skills(img, draw, y, skills) + GAP

    if card.get("lobby_rank") or card.get("standing"):
        y = _draw_footer_row(img, draw, y, card)
    if card.get("note"):
        y = cards.footer(draw, y, card["note"])
    return canvas.png(y)


def _draw_header(img, draw, y: int, card: dict, avatars: dict) -> int:
    cards.panel(img, (PAD, y, WIDTH - PAD, y + HEADER_H), PANEL, radius=22)
    name = clean(card.get("name")) or "Игрок"
    ring = cards.avatar(avatars.get(card.get("avatar")), name, 128, ring=GOLD, ring_w=4)
    cards.paste(img, ring, PAD + 28, y + (HEADER_H - ring.size[1]) / 2)
    x = PAD + 28 + ring.size[0] + 28

    draw_text(draw, (x, y + 52), name, 44, FG, bold=True, anchor="lm", max_w=560)
    if card.get("steam_name"):
        draw_text(draw, (x, y + 92), f"Steam: {clean(card['steam_name'])}", 22, MUTED, anchor="lm", max_w=560)
    cards.paste(img, cards.rank_badge(card.get("rank_tier"), 56), x, y + 112)
    rank_text = clean(card.get("rank_text")) or "Без ранга"
    draw_text(draw, (x + 72, y + 140), rank_text, 28, FG, bold=True, anchor="lm", max_w=300)
    streak = card.get("streak")
    if streak and streak[1] >= 2:
        is_win = streak[0] == "W"
        tx = x + 72 + min(cards.text_width(rank_text, 28, True), 300) + 20
        cards.pill(img, draw, tx, y + 140, f"{'▲' if is_win else '▼'} {streak[1]} подряд", BG, WIN if is_win else LOSS,
                   size=20, pad=14)

    right = WIDTH - PAD - 32
    draw_text(draw, (right, y + 66), clean(card.get("mmr_text")) or "—", 66, FG, bold=True, anchor="rm")
    delta = card.get("mmr_delta")
    if delta is not None and card.get("delta_note"):
        draw_text(draw, (right, y + 118), f"{signed(delta)} {clean(card['delta_note'])}", 26, cards.delta_color(delta),
                  anchor="rm")
    if card.get("perf") is not None:
        cards.pill(img, draw, right, y + 156, f"перф {card['perf']}/100", BG, GOLD, size=20, align="right", pad=14)
    return y + HEADER_H


def _draw_trend_row(img, draw, y: int, card: dict) -> int:
    h = 244
    x0, y0 = _section(img, draw, (PAD, y, PAD + LEFT_W, y + h), card.get("series_label") or "Динамика ≈MMR")
    series = card.get("series") or []
    if len(series) >= 2:
        draw_text(draw, (PAD + LEFT_W - 24, y + 28), f"{series[0]} → {series[-1]}", 20, FG, bold=True, anchor="rm")
        cards.sparkline(img, (x0, y0 - 6, PAD + LEFT_W - 24, y0 + 108), series, ACCENT)
    else:
        draw_text(draw, (x0, y0 + 40), "мало игр для графика", 22, MUTED, anchor="lm")
    form = card.get("form") or []
    if form:
        draw_text(draw, (x0, y + h - 60), "ФОРМА", 18, MUTED, bold=True, anchor="lm")
        cards.form_dots(img, x0 + 90, y + h - 60, form[-10:], r=9, gap=6)
        wins = sum(1 for f in form if f)
        draw_text(draw, (PAD + LEFT_W - 24, y + h - 60), f"{wins}–{len(form) - wins} в последних {len(form)}", 22, FG,
                  anchor="rm")

    rx = PAD + LEFT_W + GAP
    x1, y1 = _section(img, draw, (rx, y, rx + RIGHT_W, y + h), "Соло и группа")
    row_y = y1 + 4
    for item in card.get("split") or []:
        games = item["wins"] + item["losses"]
        draw_text(draw, (x1, row_y + 4), clean(item["label"]), 22, FG, bold=True, anchor="lm")
        draw_text(draw, (rx + RIGHT_W - 24, row_y + 4), f"{item['wins']}–{item['losses']}" if games else "—", 22, FG,
                  bold=True, anchor="rm")
        if games:
            cards.winrate_bar(img, (x1, row_y + 24, rx + RIGHT_W - 24, row_y + 36), item["wins"], item["losses"])
        row_y += 58
    hours = card.get("hours")
    if hours:
        draw_text(draw, (x1, row_y + 8), "Лучший час", 20, MUTED, anchor="lm")
        draw_text(draw, (rx + RIGHT_W - 24, row_y + 8), clean(hours["best"]), 20, WIN, bold=True, anchor="rm")
        draw_text(draw, (x1, row_y + 38), "Худший час", 20, MUTED, anchor="lm")
        draw_text(draw, (rx + RIGHT_W - 24, row_y + 38), clean(hours["worst"]), 20, LOSS, bold=True, anchor="rm")
    return y + h


def _draw_heroes_row(img, draw, y: int, heroes: list, last: Optional[dict], icons: dict) -> int:
    h = 56 + max(len(heroes), 1) * HERO_ROW_H + 12
    x0, y0 = _section(img, draw, (PAD, y, PAD + LEFT_W, y + h), "Топ героев")
    for i, hero in enumerate(heroes[:3]):
        top = y0 + i * HERO_ROW_H
        cards.paste(img, cards.hero_icon(icons.get(hero["hero_id"]), hero["hero_id"]), x0, top + (HERO_ROW_H - ICON_H) / 2 - 4)
        tx = x0 + ICON_W + 20
        draw_text(draw, (tx, top + 22), clean(hero["name"]), 26, FG, bold=True, anchor="lm", max_w=330)
        draw_text(draw, (tx, top + 52), f"{hero['games']} игр · {hero['wins']}–{hero['games'] - hero['wins']}", 20, MUTED,
                  anchor="lm")
        right = PAD + LEFT_W - 24
        cards.winrate_bar(img, (right - 170, top + 14, right, top + 26), hero["wins"], hero["games"] - hero["wins"])
        draw_text(draw, (right, top + 52), f"{round(hero['winrate'] * 100)}%", 24, FG, bold=True, anchor="rm")

    rx = PAD + LEFT_W + GAP
    x1, y1 = _section(img, draw, (rx, y, rx + RIGHT_W, y + h), "Последняя игра")
    if last:
        cards.paste(img, cards.hero_icon(icons.get(last["hero_id"]), last["hero_id"]), x1, y1 + 4)
        draw_text(draw, (x1 + ICON_W + 20, y1 + 20), clean(last["name"]), 24, FG, bold=True, anchor="lm", max_w=RIGHT_W - ICON_W - 70)
        draw_text(draw, (x1 + ICON_W + 20, y1 + 52), "победа" if last.get("won") else "поражение", 22,
                  WIN if last.get("won") else LOSS, bold=True, anchor="lm")
        cards.kda(draw, rx + RIGHT_W / 2, y1 + 118, last["kills"], last["deaths"], last["assists"], 44)
    else:
        draw_text(draw, (x1, y1 + 30), "пока нет игр", 22, MUTED, anchor="lm")
    return y + h


def _draw_skills(img, draw, y: int, skills: list) -> int:
    skills = skills[:4]
    h = 56 + len(skills) * 46 + 14
    x0, y0 = _section(img, draw, (PAD, y, WIDTH - PAD, y + h), "Профиль навыков · мировой перцентиль")
    draw_text(draw, (WIDTH - PAD - 24, y + 28), "50% — средний игрок", 18, MUTED, anchor="rm")
    for i, skill in enumerate(skills):
        cy = y0 + i * 46 + 18
        pct = max(0.0, min(1.0, skill["pct"]))
        color = WIN if pct >= 0.6 else LOSS if pct < 0.4 else ACCENT
        draw_text(draw, (x0, cy), clean(skill["label"]), 22, FG, bold=True, anchor="lm", max_w=250)
        cards.bar(img, (x0 + 290, cy - 9, WIDTH - PAD - 24 - 110, cy + 9), pct, color, marker=0.5)
        draw_text(draw, (WIDTH - PAD - 24, cy), f"{round(pct * 100)}%", 24, color, bold=True, anchor="rm")
    return y + h


def _draw_footer_row(img, draw, y: int, card: dict) -> int:
    h = 76
    cards.panel(img, (PAD, y, WIDTH - PAD, y + h), PANEL, radius=18)
    x = PAD + 24
    if card.get("lobby_rank"):
        cards.paste(img, cards.rank_badge(card["lobby_rank"], 44), x, y + (h - 44) / 2)
        draw_text(draw, (x + 58, y + h / 2), f"Средний уровень лобби · {clean(card.get('lobby_text'))}", 22, FG, anchor="lm", max_w=520)
    if card.get("standing"):
        draw_text(draw, (WIDTH - PAD - 24, y + h / 2), clean(card["standing"]), 22, GOLD, bold=True, anchor="rm", max_w=560)
    return y + h + 6
