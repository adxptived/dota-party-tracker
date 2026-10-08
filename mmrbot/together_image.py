"""Совместные игры картинкой (/together): плитки «вместе» и «лучшая пара» + матрица пар.

Матрица: строки и столбцы — игроки (до 8 с наибольшим числом совместных игр); в ячейке — сколько игр сыграли
на одной стороне и винрейт пары, цвет ячейки — от красного (низкий) к зелёному (высокий).
Чистая функция: сети и БД нет; аватары — готовыми байтами.

summary: games, wins, losses; duo: {names: (a, b), games, wins} | None;
players: [{name, avatar}]; pairs: [{a, b, games, wins}] — индексы в `players`.
"""
from __future__ import annotations

from typing import Optional

from mmrbot import cards
from mmrbot.cards import ACCENT, FG, GOLD, MUTED, PAD, PANEL, WIDTH, clean, draw_text
from mmrbot.formatting import plural_games

MAX_PLAYERS = 8
LABEL_W = 230
CELL_H = 88
AVATAR = 48
TILE_H = 112
GAP = 14


def _shown(players: list, pairs: list) -> list[int]:
    """Индексы игроков для матрицы: до MAX_PLAYERS с наибольшим числом совместных игр (порядок — как в чате)."""
    totals = {i: 0 for i in range(len(players))}
    for pair in pairs:
        totals[pair["a"]] += pair["games"]
        totals[pair["b"]] += pair["games"]
    top = sorted(totals, key=lambda i: (-totals[i], i))[:MAX_PLAYERS]
    return sorted(top)


def _heat(winrate: float) -> str:
    """Цвет ячейки: 50% — нейтральный, ниже — к красному, выше — к зелёному."""
    if winrate >= 0.5:
        return cards.mix(PANEL, cards.WIN, min(0.55, (winrate - 0.5) * 1.2 + 0.12))
    return cards.mix(PANEL, cards.LOSS, min(0.55, (0.5 - winrate) * 1.2 + 0.12))


def render_together_image(
    summary: dict, duo: Optional[dict], players: list, pairs: list, avatars: Optional[dict] = None,
    note: Optional[str] = None,
) -> bytes:
    """Совместные игры → PNG-байты; нет совместных игр — шапка и пояснение."""
    avatars = avatars or {}
    shown = _shown(players, pairs)
    n = len(shown)
    canvas = cards.Canvas(420 + (n + 1) * CELL_H + 160)
    img, draw = canvas.img, canvas.draw
    y = cards.header(img, draw, "Совместные игры", "ранкед-матчи на одной стороне", ("ПАРЫ", ACCENT))

    games = summary.get("games", 0)
    if not games:
        cards.panel(img, (PAD, y, WIDTH - PAD, y + 130), PANEL, radius=18)
        draw_text(draw, (PAD + 28, y + 45), "Совместные ранкед-игры не обнаружены.", 28, FG, bold=True, anchor="lm")
        draw_text(draw, (PAD + 28, y + 90), "Возможно, данные ещё загружаются. После первой общей игры появятся винрейт и лучшая пара.",
                  21, MUTED, anchor="lm", max_w=WIDTH - 2 * PAD - 56)
        y += 150
        if note:
            y = cards.footer(draw, y, note)
        return canvas.png(y)

    wins, losses = summary.get("wins", 0), summary.get("losses", 0)
    tiles = [("Сыграно вместе", plural_games(games),
              f"{wins}–{losses} ({round(wins * 100 / games)}%)", cards.WIN if wins >= losses else cards.LOSS)]
    if duo:
        a, b = duo["names"]
        tiles.append(("Лучшая пара", f"{clean(a)} + {clean(b)}", f"{plural_games(duo['games'])} · {round(duo['wins'] * 100 / duo['games'])}%", GOLD))
    tiles.append(("Пар играло вместе", str(len(pairs)), None, FG))
    w = (WIDTH - 2 * PAD - GAP * (len(tiles) - 1)) / len(tiles)
    for i, (label, value, sub, color) in enumerate(tiles):
        x0 = PAD + i * (w + GAP)
        cards.tile(img, draw, (x0, y, x0 + w, y + TILE_H), label, value, sub, color, value_size=32, fill=PANEL)
    y += TILE_H + GAP * 2

    y = _draw_matrix(img, draw, y, shown, players, pairs, avatars)
    if len(players) > n:
        draw_text(draw, (PAD, y + 12), f"Показаны {n} игроков с наибольшим числом совместных игр из {len(players)}.", 18, MUTED, anchor="lm")
        y += 30
    if note:
        y = cards.footer(draw, y, note)
    return canvas.png(y)


def _draw_matrix(img, draw, y: int, shown: list, players: list, pairs: list, avatars: dict) -> int:
    n = len(shown)
    if n < 2:
        return y
    by_pair = {(p["a"], p["b"]): p for p in pairs}
    by_pair.update({(p["b"], p["a"]): p for p in pairs})
    cell_w = (WIDTH - 2 * PAD - LABEL_W) / n
    for col, idx in enumerate(shown):  # шапка: аватар и ник над столбцом
        cx = PAD + LABEL_W + col * cell_w + cell_w / 2
        name = clean(players[idx].get("name")) or "Игрок"
        cards.paste(img, cards.avatar(avatars.get(players[idx].get("avatar")), name, AVATAR), cx - AVATAR / 2, y)
        draw_text(draw, (cx, y + AVATAR + 18), name, 18, MUTED, anchor="mm", max_w=cell_w - 8)
    y += AVATAR + 40
    for ridx in shown:
        mid = y + CELL_H / 2
        name = clean(players[ridx].get("name")) or "Игрок"
        cards.paste(img, cards.avatar(avatars.get(players[ridx].get("avatar")), name, AVATAR), PAD, mid - AVATAR / 2)
        draw_text(draw, (PAD + AVATAR + 14, mid), name, 24, FG, bold=True, anchor="lm", max_w=LABEL_W - AVATAR - 24)
        for col, cidx in enumerate(shown):
            x0 = PAD + LABEL_W + col * cell_w
            box = (x0 + 3, y + 3, x0 + cell_w - 3, y + CELL_H - 3)
            cx = x0 + cell_w / 2
            pair = by_pair.get((ridx, cidx)) if ridx != cidx else None
            if ridx == cidx:  # игрок с самим собой: тёмная ячейка с косой чертой — «здесь не бывает»
                cards.panel(img, box, cards.BG, radius=12)
                draw.line((box[0] + 18, box[3] - 18, box[2] - 18, box[1] + 18), fill=cards.mix(cards.BG, cards.MUTED, 0.38), width=3)
            elif pair and pair["games"]:
                cards.panel(img, box, _heat(pair["wins"] / pair["games"]), radius=12)
                draw_text(draw, (cx, mid - 12), str(pair["games"]), 30, FG, bold=True, anchor="mm")
                draw_text(draw, (cx, mid + 22), f"{round(pair['wins'] * 100 / pair['games'])}%", 20, FG, anchor="mm")
            else:
                cards.panel(img, box, PANEL, radius=12)
                draw_text(draw, (cx, mid), "—", 24, MUTED, anchor="mm")
        y += CELL_H
    return y + 8
