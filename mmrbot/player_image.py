"""Карточка игрока картинкой (/player): шапка с аватаром, рангом и ≈MMR, плитки показателей, динамика MMR и форма,
соло против группы и короткие факты (лучшая серия, пул героев, средняя игра), топ-герои, последняя игра,
лента последних игр (герой, исход, K/D/A, ±MMR), предупреждения плашкой.

Длинные ники, ранги и подписи сначала уменьшаются в кегле и лишь потом обрезаются — текст не уходит за края блоков.

Чистая функция: данные приходят словарём (его собирает card_data.player_card), иконки героев и аватар — готовыми
байтами; сети и БД здесь нет. Ключи словаря — в card_data.player_card.
"""
from __future__ import annotations

from typing import Optional

from mmrbot import cards
from mmrbot.cards import (
    ACCENT, BG, FG, GOLD, ICON_H, ICON_W, LOSS, MUTED, PAD, PANEL, WIDTH, WIN, clean, draw_text, signed,
)
from mmrbot.formatting import plural_games

HEADER_H = 190
TILE_H = 112
GAP = cards.GAP
LEFT_W = 760
RIGHT_W = WIDTH - 2 * PAD - LEFT_W - GAP
HERO_ROW_H = 84
RECENT_N = 6
RECENT_H = 292


def _section(img, draw, box, title: str) -> tuple[int, int]:
    """Панель с заголовком раздела; возвращает (x0, y0) левого верхнего угла содержимого."""
    cards.panel(img, box, PANEL, radius=cards.R_CARD)
    draw_text(draw, (box[0] + 24, box[1] + 28), title.upper(), 18, MUTED, bold=True, anchor="lm")
    return box[0] + 24, box[1] + 56


def render_player_image(card: dict, icons: Optional[dict] = None, avatars: Optional[dict] = None) -> bytes:
    """Карточка игрока → PNG-байты. icons: {hero_id: байты}; avatars: {url: байты}; нет данных — заглушки/пропуск блока."""
    icons, avatars = icons or {}, avatars or {}
    tone = _tone(card)
    canvas = cards.Canvas(2600, accent=tone)
    img, draw = canvas.img, canvas.draw
    y = PAD

    y = _draw_header(img, draw, y, card, avatars, tone) + GAP
    warnings = [clean(text) for text in card.get("warnings") or [] if clean(text)]
    if warnings:
        y = _draw_warnings(img, draw, y, warnings) + GAP

    tiles = (card.get("tiles") or [])[:5]
    if tiles:
        w = (WIDTH - 2 * PAD - GAP * (len(tiles) - 1)) / len(tiles)
        for i, tile in enumerate(tiles):
            x0 = PAD + i * (w + GAP)
            cards.tile(img, draw, (x0, y, x0 + w, y + TILE_H), tile.get("label", ""), tile.get("value", "—"),
                       tile.get("sub"), tile.get("color") or FG, value_size=32, fill=PANEL)
        y += TILE_H + GAP

    if card.get("series") or card.get("form") or card.get("split") or card.get("facts"):
        y = _draw_trend_row(img, draw, y, card) + GAP

    heroes, last = card.get("heroes") or [], card.get("last_game")
    if heroes or last:
        y = _draw_heroes_row(img, draw, y, heroes, last, icons) + GAP

    recent = card.get("recent") or []
    if recent:
        y = _draw_recent(img, draw, y, recent[:RECENT_N], icons, card.get("recent_mmr", True)) + GAP

    if card.get("lobby_rank") or card.get("standing"):
        y = _draw_footer_row(img, draw, y, card)
    if card.get("note"):
        y = cards.footer(draw, y, card["note"])
    return canvas.png(y)


def _tone(card: dict) -> str:
    """Цвет карточки — цвет медали игрока (Legend — синий, Divine — бирюзовый…); без ранга — обычный акцент."""
    return cards.MEDAL_COLORS.get((card.get("rank_tier") or 0) // 10, ACCENT)


def _draw_warnings(img, draw, y: int, warnings: list) -> int:
    """Предупреждения одной негромкой плашкой: значок слева, по строке на каждое."""
    line_h = 32
    h = 24 + len(warnings) * line_h
    fill = cards.mix(PANEL, GOLD, 0.09)
    cards.panel(img, (PAD, y, WIDTH - PAD, y + h), fill, radius=cards.R_CARD, outline=cards.mix(PANEL, GOLD, 0.3))
    cards.dot(img, PAD + 36, y + h / 2, 14, cards.mix(PANEL, GOLD, 0.85))
    draw_text(draw, (PAD + 36, y + h / 2), "!", 20, BG, bold=True, anchor="mm")
    for i, text in enumerate(warnings):
        draw_text(draw, (PAD + 66, y + 12 + line_h * i + line_h / 2), text, 20, cards.mix(GOLD, FG, 0.45), anchor="lm",
                  max_w=WIDTH - 2 * PAD - 66 - 22)
    return y + h


def _draw_header(img, draw, y: int, card: dict, avatars: dict, tone: str = GOLD) -> int:
    cards.gradient_panel(img, (PAD, y, WIDTH - PAD, y + HEADER_H), cards.mix(PANEL, tone, 0.26), PANEL, radius=cards.R_CARD,
                         outline=cards.mix(PANEL, tone, 0.3))
    name = clean(card.get("name")) or "Игрок"
    ring = cards.avatar(avatars.get(card.get("avatar")), name, 128, ring=tone, ring_w=4)
    cards.paste(img, ring, PAD + 28, y + (HEADER_H - ring.size[1]) / 2)
    x = PAD + 28 + ring.size[0] + 28

    # правый блок (≈MMR, дельта, перф) рисуем первым: его ширина ограничивает ник и ранг слева
    right = WIDTH - PAD - 32
    mmr_w = cards.value_text(draw, (right, y + 62), clean(card.get("mmr_text")) or "—", 72, FG)
    block_w = mmr_w
    delta = card.get("mmr_delta")
    if delta is not None and card.get("delta_note"):
        text = f"{signed(delta)} {clean(card['delta_note'])}"
        cards.delta_text(draw, (right, y + 116), text, 24, cards.delta_color(delta), max_w=360)
        block_w = max(block_w, min(cards.text_width(text, 24), 360))
    elif card.get("headline_note"):  # пояснение к крупному числу без знака (винрейт у игрока не из пати)
        text = clean(card["headline_note"])
        draw_text(draw, (right, y + 116), text, 22, MUTED, anchor="rm", max_w=360)
        block_w = max(block_w, min(cards.text_width(text, 22), 360))
    if card.get("perf") is not None:
        block_w = max(block_w, cards.chip(img, draw, right, y + 156, f"перф {card['perf']}/100", GOLD, size=20,
                                          align="right", pad=14, base=PANEL))
    room = right - block_w - 32 - x

    draw_text(draw, (x, y + 50), name, 46, FG, bold=True, anchor="lm", max_w=room, shrink=28)
    subtitle = clean(card.get("subtitle")) or (f"Steam: {clean(card['steam_name'])}" if card.get("steam_name") else "")
    if subtitle:
        draw_text(draw, (x, y + 92), subtitle, 22, cards.mix(MUTED, "#ffffff", 0.12), anchor="lm", max_w=room, shrink=18)
    cards.paste(img, cards.rank_badge(card.get("rank_tier"), 56), x, y + 112)
    rank_text = clean(card.get("rank_text")) or "Без ранга"
    streak = card.get("streak")
    chip_text = None
    if streak and streak[1] >= 2:
        chip_text = f"{'▲' if streak[0] == 'W' else '▼'} {streak[1]} подряд"
    chip_w = cards.text_width(chip_text, 20, True, False) + 28 + 20 if chip_text else 0
    rank_room = room - 72
    if chip_text and rank_room - chip_w < 140:  # серия не помещается рядом с рангом — ранг важнее
        chip_text, chip_w = None, 0
    size = cards.fit_size(rank_text, 28, True, rank_room - chip_w, 20)
    draw_text(draw, (x + 72, y + 140), rank_text, size, FG, bold=True, anchor="lm", max_w=rank_room - chip_w)
    if chip_text:
        tx = x + 72 + min(cards.text_width(rank_text, size, True), rank_room - chip_w) + 20
        is_win = streak[0] == "W"
        cards.chip(img, draw, tx, y + 140, chip_text, WIN if is_win else LOSS, size=20, pad=14, base=PANEL)
    return y + HEADER_H


def _draw_trend_row(img, draw, y: int, card: dict) -> int:
    facts = (card.get("facts") or [])[:3]
    h = max(244, 56 + 4 + len(card.get("split") or []) * 58 + len(facts) * 30 + 24)
    x0, y0 = _section(img, draw, (PAD, y, PAD + LEFT_W, y + h), card.get("series_label") or "Динамика ≈MMR")
    series = card.get("series") or []
    if len(series) >= 2:
        draw_text(draw, (PAD + LEFT_W - 24, y + 28), f"{series[0]} → {series[-1]}", 20, FG, bold=True, anchor="rm")
        cards.sparkline(img, (x0, y0 - 6, PAD + LEFT_W - 24, y + h - 96), series, ACCENT)
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
        draw_text(draw, (x1, row_y + 4), clean(item["label"]), 22, FG, bold=True, anchor="lm", max_w=RIGHT_W - 160)
        draw_text(draw, (rx + RIGHT_W - 24, row_y + 4), f"{item['wins']}–{item['losses']}" if games else "—", 22, FG,
                  bold=True, anchor="rm")
        if games:
            cards.winrate_bar(img, (x1, row_y + 24, rx + RIGHT_W - 24, row_y + 36), item["wins"], item["losses"])
        row_y += 58
    inner = RIGHT_W - 48
    for label, value, *color in facts:
        value = clean(value)
        value_w = min(cards.text_width(value, 20, True), inner * 0.55)
        draw_text(draw, (rx + RIGHT_W - 24, row_y + 8), value, 20, (color[0] if color and color[0] else FG), bold=True,
                  anchor="rm", max_w=inner * 0.55)
        draw_text(draw, (x1, row_y + 8), clean(label), 20, MUTED, anchor="lm", max_w=inner - value_w - 12)
        row_y += 30
    return y + h


def _draw_heroes_row(img, draw, y: int, heroes: list, last: Optional[dict], icons: dict) -> int:
    h = 56 + max(len(heroes), 1) * HERO_ROW_H + 12
    x0, y0 = _section(img, draw, (PAD, y, PAD + LEFT_W, y + h), "Топ героев")
    for i, hero in enumerate(heroes[:3]):
        top = y0 + i * HERO_ROW_H
        cards.paste(img, cards.hero_icon(icons.get(hero["hero_id"]), hero["hero_id"]), x0, top + (HERO_ROW_H - ICON_H) / 2 - 4)
        tx = x0 + ICON_W + 20
        draw_text(draw, (tx, top + 22), clean(hero["name"]), 26, FG, bold=True, anchor="lm", max_w=PAD + LEFT_W - 24 - 190 - tx,
                  shrink=20)
        line = f"{plural_games(hero['games'])} · {hero['wins']}–{hero['games'] - hero['wins']}"
        if isinstance(hero.get("kda"), (int, float)):
            line += f" · KDA {hero['kda']:.1f}"
        draw_text(draw, (tx, top + 52), line, 20, MUTED, anchor="lm", max_w=PAD + LEFT_W - 24 - 90 - tx, shrink=17)
        right = PAD + LEFT_W - 24
        cards.winrate_bar(img, (right - 170, top + 14, right, top + 26), hero["wins"], hero["games"] - hero["wins"])
        draw_text(draw, (right, top + 52), f"{round(hero['winrate'] * 100)}%", 24, FG, bold=True, anchor="rm")

    rx = PAD + LEFT_W + GAP
    x1, y1 = _section(img, draw, (rx, y, rx + RIGHT_W, y + h), "Последняя игра")
    if last:
        cards.paste(img, cards.hero_icon(icons.get(last["hero_id"]), last["hero_id"]), x1, y1 + 4)
        cards.hero_badges(img, draw, x1, y1 + 4, ICON_W, ICON_H, last.get("level"), last.get("plus_xp"))
        draw_text(draw, (x1 + ICON_W + 20, y1 + 18), clean(last["name"]), 24, FG, bold=True, anchor="lm",
                  max_w=RIGHT_W - ICON_W - 70, shrink=18)
        cards.chip(img, draw, x1 + ICON_W + 20, y1 + 52, "победа" if last.get("won") else "поражение",
                   WIN if last.get("won") else LOSS, size=18, pad=12, base=PANEL)
        if last.get("when"):
            draw_text(draw, (rx + RIGHT_W - 24, y + 28), clean(last["when"]), 18, MUTED, anchor="rm")
        stats = [cell for cell in last.get("stats") or [] if cell[1]][:3]
        # K/D/A и подпись под ним — по центру оставшегося места; под ними — ячейки подробностей, если они есть
        bottom = y + h - (78 if stats else 20)
        centre = (y1 + 4 + ICON_H + bottom) / 2
        cards.kda(draw, rx + RIGHT_W / 2, centre - 12, last["kills"], last["deaths"], last["assists"], 48)
        ratio = f"KDA {last['kda']:.1f}" if isinstance(last.get("kda"), (int, float)) else "K / D / A"
        draw_text(draw, (rx + RIGHT_W / 2, centre + 32), ratio, 20, MUTED, anchor="mm")
        if stats:
            img.paste(cards.mix(PANEL, "#ffffff", 0.07), (round(x1), round(y + h - 76), round(rx + RIGHT_W - 24), round(y + h - 75)))
            cards.stat_cells(draw, x1, y + h - 40, stats, (RIGHT_W - 48) / len(stats))
    else:
        draw_text(draw, (x1, y1 + 30), "пока нет игр", 22, MUTED, anchor="lm")
    return y + h


def _draw_recent(img, draw, y: int, games: list, icons: dict, show_delta: bool = True) -> int:
    """Лента последних игр слева направо от новой к старой: иконка героя, исход и ±MMR, K/D/A, длительность и дата."""
    h = RECENT_H
    x0, y0 = _section(img, draw, (PAD, y, WIDTH - PAD, y + h), "Последние игры")
    draw_text(draw, (WIDTH - PAD - 24, y + 28), "новые слева", 18, MUTED, anchor="rm")
    gap = 12
    col_w = (WIDTH - 2 * PAD - 48 - gap * (RECENT_N - 1)) / RECENT_N
    icon_w = round(col_w - 24)
    icon_h = round(icon_w * 9 / 16)
    for i, game in enumerate(games):
        left = x0 + i * (col_w + gap)
        won = bool(game.get("won"))
        color = WIN if won else LOSS
        fill = cards.mix(PANEL, color, 0.07)
        bottom = y + h - 18
        cards.panel(img, (left, y0, left + col_w, bottom), fill, radius=cards.R_TILE, outline=cards.mix(fill, color, 0.3))
        cx = left + col_w / 2
        cards.paste(img, cards.hero_icon(icons.get(game.get("hero_id")), game.get("hero_id"), icon_w, icon_h, 8),
                    left + 12, y0 + 12)
        cards.hero_badges(img, draw, left + 12, y0 + 12, icon_w, icon_h, game.get("level"), game.get("plus_xp"),
                          level_r=12, plus_size=40, overhang=8)
        line_y = y0 + 12 + icon_h + 22
        result = "ПОБЕДА" if won else "ПОРАЖЕНИЕ"
        delta = game.get("delta") if show_delta else None
        if delta is not None:
            text = signed(delta) + (" ×2" if game.get("double_down") else "")
            draw_text(draw, (left + col_w - 12, line_y), text, 18, color, bold=True, anchor="rm", track=False)
            draw_text(draw, (left + 12, line_y), result, 15, color, bold=True, anchor="lm",
                      max_w=col_w - 30 - cards.text_width(text, 18, True, False))
        else:
            draw_text(draw, (cx, line_y), result, 16, color, bold=True, anchor="mm")
        cards.kda(draw, cx, line_y + 34, game.get("kills"), game.get("deaths"), game.get("assists"), 26)
        info = "  ·  ".join(part for part in (f"{game['minutes']} мин" if game.get("minutes") else None,
                                              clean(game.get("when"))) if part)
        if info:
            draw_text(draw, (cx, line_y + 68), info, 17, MUTED, anchor="mm", max_w=col_w - 16, shrink=14, track=False)
    return y + h


def _draw_footer_row(img, draw, y: int, card: dict) -> int:
    h = 76
    cards.panel(img, (PAD, y, WIDTH - PAD, y + h), PANEL, radius=cards.R_CARD)
    x = PAD + 24
    if card.get("lobby_rank"):
        cards.paste(img, cards.rank_badge(card["lobby_rank"], 44), x, y + (h - 44) / 2)
        draw_text(draw, (x + 58, y + h / 2), f"Средний уровень лобби · {clean(card.get('lobby_text'))}", 22, FG, anchor="lm",
                  max_w=520, shrink=18)
    if card.get("standing"):
        draw_text(draw, (WIDTH - PAD - 24, y + h / 2), clean(card["standing"]), 22, GOLD, bold=True, anchor="rm", max_w=560,
                  shrink=18)
    return y + h + 6
