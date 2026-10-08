"""Оповещение о конце матча картинкой: шапка с исходом и лобби, по строке на каждого игрока пати
(аватар, иконка героя, ник, K/D/A, ±MMR → ≈MMR, серия), внизу «Сегодня вместе».

Чистая функция: иконки героев и аватары приходят готовыми байтами, сети и БД здесь нет.
"""
from __future__ import annotations

import html
from typing import Optional

from mmrbot import cards
from mmrbot.boards import CAPTION_LIMIT
from mmrbot.cards import (
    ACCENT, BG, FG, GOLD, ICON_H, ICON_W, LOSS, MUTED, PAD, PANEL, WIDTH, WIN, clean, draw_text, signed,
)
from mmrbot.formatting import _mvp_name, _thousands, fmt_local, plural_games
from mmrbot.heroes import hero_name
from mmrbot.ranks import rank_label

ROW_H, ROW_GAP = 104, 10
AVATAR = 64
NAME_X = PAD + 22 + AVATAR + 14 + ICON_W + 20
NAME_MAX_W = 360
KDA_X = 760
RIGHT = WIDTH - PAD - 24
FOOT_H = 76


def _outcome(rows: list) -> tuple[str, str]:
    wins = sum(1 for r in rows if r.get("won"))
    if wins == len(rows):
        return "ПОБЕДА", WIN
    if wins == 0:
        return "ПОРАЖЕНИЕ", LOSS
    return "РАЗНЫЕ СТОРОНЫ", ACCENT


def _delta(row: dict) -> int:
    step = row.get("step") or 0
    return step if row.get("won") else -step


def render_alert_image(event: dict, tz: str = "UTC", icons: Optional[dict] = None, avatars: Optional[dict] = None) -> bytes:
    """Событие `detect_new_games` (kind="match") → PNG-байты.

    icons: {hero_id: PNG-байты}; avatars: {url: байты}; отсутствующие рисуются заглушками.
    """
    icons, avatars = icons or {}, avatars or {}
    rows = event.get("rows") or []
    canvas = cards.Canvas(260 + len(rows) * (ROW_H + ROW_GAP) + FOOT_H + 100)
    img, draw = canvas.img, canvas.draw

    when = fmt_local(event.get("start_time") or 0, tz, "%d.%m.%Y %H:%M")
    sub = when + (f"  ·  {event['duration'] // 60} мин" if event.get("duration") else "")
    label, color = _outcome(rows) if rows else ("МАТЧ", ACCENT)
    y = cards.header(img, draw, "Матч завершён", sub, (label, color))

    if event.get("average_rank"):
        cards.paste(img, cards.rank_badge(event["average_rank"], 48), PAD, y - 4)
        draw_text(draw, (PAD + 62, y + 20), f"Лобби · {rank_label(event['average_rank'])}", 24, FG, anchor="lm")
        draw_text(draw, (WIDTH - PAD, y + 20), f"ID матча {event.get('match_id')}", 20, MUTED, anchor="rm")
        y += 64
    else:
        draw_text(draw, (WIDTH - PAD, y + 8), f"ID матча {event.get('match_id')}", 20, MUTED, anchor="rm")
        y += 34

    mvp = _mvp_name(rows)
    for row in rows:
        _draw_row(img, draw, y, row, icons, avatars, mvp)
        y += ROW_H + ROW_GAP

    shared = event.get("shared")
    if shared and shared.get("games"):
        _draw_shared(img, draw, y, shared)
        y += FOOT_H
    return canvas.png(y)


def _draw_row(img, draw, y: int, row: dict, icons: dict, avatars: dict, mvp: Optional[str]) -> None:
    won = bool(row.get("won"))
    accent = WIN if won else LOSS
    cards.panel(img, (PAD, y, WIDTH - PAD, y + ROW_H), cards.mix(PANEL, accent, 0.09), radius=16)
    cards.stripe(img, PAD, y, y + ROW_H, accent)
    mid = y + ROW_H / 2

    name = clean(row.get("name")) or "Игрок"
    cards.paste(img, cards.avatar(avatars.get(row.get("avatar")), name, AVATAR), PAD + 22, mid - AVATAR / 2)
    cards.paste(img, cards.hero_icon(icons.get(row.get("hero_id")), row.get("hero_id")), PAD + 22 + AVATAR + 14, mid - ICON_H / 2)

    tags = []
    if name == mvp:
        tags.append(("MVP", GOLD))
    if (row.get("leaver_status") or 0) >= 2:
        tags.append(("вышел", LOSS))
    tags_w = sum(cards.text_width(t, 18, True) + 20 + 8 for t, _ in tags)
    name_max = NAME_MAX_W - tags_w
    draw_text(draw, (NAME_X, mid - 26), name, 28, FG, bold=True, anchor="lm", max_w=name_max)
    tag_x = NAME_X + min(cards.text_width(name, 28, True), name_max) + 12
    for text, tag_color in tags:
        tag_x += cards.pill(img, draw, tag_x, mid - 26, text, BG, tag_color, size=18, pad=10) + 8
    hero = hero_name(row.get("hero_id")) + (f"  ·  P{row['position']}" if row.get("position") else "")
    draw_text(draw, (NAME_X, mid + 2), hero, 20, MUTED, anchor="lm", max_w=NAME_MAX_W + 60)
    extra = []
    if row.get("imp") is not None:
        extra.append(f"IMP {signed(row['imp'])}")
    if row.get("gpm"):
        extra.append(f"{round(row['gpm'])} GPM")
    if row.get("hero_damage"):
        extra.append(f"{_thousands(row['hero_damage'])} урона")
    if extra:
        draw_text(draw, (NAME_X, mid + 28), "  ·  ".join(extra), 18, MUTED, anchor="lm", max_w=NAME_MAX_W + 60)

    cards.kda(draw, KDA_X, mid - 6, row.get("kills"), row.get("deaths"), row.get("assists"), 34)

    delta = _delta(row)
    mmr = row.get("current_mmr")
    x = RIGHT
    if mmr is not None:
        mmr_text = f"≈{mmr}"
        draw_text(draw, (x, mid - 10), mmr_text, 34, FG, bold=True, anchor="rm")
        x -= cards.text_width(mmr_text, 34, True) + 14
        draw_text(draw, (x, mid - 10), "→", 26, MUTED, anchor="rm")
        x -= cards.text_width("→", 26) + 14
    draw_text(draw, (x, mid - 10), signed(delta), 34, cards.delta_color(delta), bold=True, anchor="rm")
    streak = row.get("streak_len") or 0
    if streak >= 3:
        is_win = row.get("streak_type") == "W"
        text = f"▲ {streak} подряд" if is_win else f"▼ {streak} подряд"
        cards.pill(img, draw, RIGHT, mid + 26, text, BG, WIN if is_win else LOSS, size=18, pad=12, align="right")


def _draw_shared(img, draw, y: int, shared: dict) -> None:
    cards.panel(img, (PAD, y + 6, WIDTH - PAD, y + FOOT_H - 6), cards.PANEL_HI, radius=16)
    mid = y + FOOT_H / 2
    text = f"Сегодня вместе: {plural_games(shared['games'])}"
    draw_text(draw, (PAD + 24, mid), text, 26, FG, bold=True, anchor="lm")
    score = f"{shared.get('wins', 0)}–{shared.get('losses', 0)}"
    draw_text(draw, (WIDTH - PAD - 24, mid), score, 30, GOLD, bold=True, anchor="rm")
    bar_x1 = WIDTH - PAD - 24 - cards.text_width(score, 30, True) - 24
    bar_x0 = PAD + 24 + cards.text_width(text, 26, True) + 28
    if bar_x1 - bar_x0 > 80:
        cards.winrate_bar(img, (bar_x0, mid - 8, bar_x1, mid + 8), shared.get("wins", 0), shared.get("losses", 0))



def alert_caption(event: dict) -> str:
    """Подпись к картинке: исход и длительность, затем ±MMR игроков одной строкой (подробности — на картинке)."""
    rows = event.get("rows") or []
    wins = sum(1 for r in rows if r.get("won"))
    result = "Победа" if rows and wins == len(rows) else "Поражение" if rows and wins == 0 else "Разные стороны"
    icon = "🏆" if rows and wins == len(rows) else "💀" if rows and wins == 0 else "⚔️"
    duration = f" · {event['duration'] // 60} мин" if event.get("duration") else ""
    head = f"🏁 <b>Матч завершён</b> · {icon} {result}{duration}"
    parts = []
    for r in rows:
        mmr = f" ➜ ≈{r['current_mmr']}" if r.get("current_mmr") is not None else ""
        parts.append(f"{html.escape(clean(r.get('name')) or 'Игрок')} {signed(_delta(r))}{mmr}")
    room = CAPTION_LIMIT - len(head) - 2
    line = " · ".join(parts)
    while parts and len(line) > room:  # много игроков с длинными никами — лишних не показываем
        parts.pop()
        line = " · ".join(parts) + " …"
    return head + ("\n" + line if parts else "")
