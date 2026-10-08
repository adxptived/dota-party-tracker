"""Картинка матча (PNG в памяти): шапка с исходом и таблица команд — иконка героя, ник, K/D/A, экономика.

Рисуем на Pillow (ставится вместе с matplotlib), шрифт DejaVu берём из matplotlib — в нём есть кириллица.
Чистая функция: иконки приходят готовыми байтами (см. hero_icons.py), сети здесь нет.
Палитра — тёмная, как у графиков (charts.py), ширина под Telegram — 1280 px.
"""
from __future__ import annotations

from typing import Optional

from mmrbot import cards
from mmrbot.cards import (
    DIRE, FG, GOLD, ICON_H, ICON_W, LOSS, MINE_PANEL, MUTED, PAD, PANEL, RADIANT, WIDTH, WIN, clean, draw_text,
)
from mmrbot.charts import BG
from mmrbot.formatting import _k, fmt_local
from mmrbot.heroes import hero_name

TRACKED_PANEL, TRACKED_MARK = MINE_PANEL, GOLD  # строка своего игрока: светлее фон + золотая полоса

HEAD_H = 132
TEAM_HEAD_H = 58
ROW_H, ROW_GAP = 78, 6
TEAM_GAP = 22
NAME_X = PAD + 24 + ICON_W + 20
NAME_MAX_W = 540 - NAME_X  # дальше — K/D/A (широкая: «12 / 11 / 25»)
# центры колонок (x) и их заголовки
COLUMNS = [("kda", 660, "K / D / A"), ("nw", 820, "Нетворт"), ("gpm", 960, "GPM / XPM"),
           ("dmg", 1090, "Урон"), ("imp", 1196, "IMP")]


def _sorted_team(players: list[dict]) -> list[dict]:
    return sorted(players, key=lambda p: p.get("position") or 9)


def _height(teams: list[list[dict]]) -> int:
    body = sum(TEAM_HEAD_H + len(team) * (ROW_H + ROW_GAP) for team in teams) + TEAM_GAP * (len(teams) - 1)
    return HEAD_H + body + PAD


def render_match_image(match: dict, tracked: dict, focus=None, tz: str = "UTC",
                       icons: Optional[dict] = None) -> bytes:
    """Матч (формат Stratz.get_match: 1–10 игроков) → PNG-байты.

    tracked: {account_id: имя в боте} — свои игроки подсвечены и подписаны именем из бота;
    focus — чей исход в шапке («ПОБЕДА»/«ПОРАЖЕНИЕ»); без него — какая сторона победила.
    icons: {hero_id: PNG-байты}; отсутствующие рисуются заглушкой.
    """
    icons = icons or {}
    players = match.get("players") or []
    teams = [(True, _sorted_team([p for p in players if p.get("is_radiant")])),
             (False, _sorted_team([p for p in players if not p.get("is_radiant")]))]
    teams = [(side, team) for side, team in teams if team]
    height = _height([team for _, team in teams]) if teams else HEAD_H + PAD

    canvas = cards.Canvas(height)
    img, draw = canvas.img, canvas.draw

    # --- шапка ---
    draw_text(draw, (PAD, 30), f"Матч {match.get('match_id')}", 40, FG, bold=True)
    when = fmt_local(match.get("start_time") or 0, tz, "%d.%m.%Y %H:%M")
    sub = when + (f"  ·  {match['duration'] // 60} мин" if match.get("duration") else "")
    draw_text(draw, (PAD, 84), sub, 24, MUTED)
    radiant_win = match.get("radiant_win")
    me = next((p for p in players if focus is not None and p.get("account_id") == focus), None)
    if me is not None and radiant_win is not None:
        won = bool(me.get("is_radiant")) == bool(radiant_win)
        label, color = ("ПОБЕДА", WIN) if won else ("ПОРАЖЕНИЕ", LOSS)
    elif radiant_win is not None:
        label, color = ("ПОБЕДА RADIANT", RADIANT) if radiant_win else ("ПОБЕДА DIRE", DIRE)
    else:
        label, color = None, None
    if label:
        cards.pill(img, draw, WIDTH - PAD, 68, label, BG, color, size=28, align="right", pad=24)

    # --- команды ---
    y = HEAD_H
    for side, team in teams:
        team_color = RADIANT if side else DIRE
        cards.stripe(img, PAD, y + 12, y + 44, team_color)
        title = "RADIANT" if side else "DIRE"
        draw_text(draw, (PAD + 20, y + 28), title, 28, team_color, bold=True, anchor="lm")
        tx = PAD + 20 + cards.text_width(title, 28, True) + 14
        if radiant_win is not None and bool(radiant_win) == side:
            draw_text(draw, (tx, y + 29), "победа", 20, MUTED, anchor="lm")
        for _key, cx, head in COLUMNS:
            draw_text(draw, (cx, y + 30), head, 18, MUTED, anchor="mm")
        y += TEAM_HEAD_H
        for p in team:
            _draw_row(img, draw, y, p, tracked, icons)
            y += ROW_H + ROW_GAP
        y += TEAM_GAP

    return canvas.png()


def _draw_row(img, draw, y: int, p: dict, tracked: dict, icons: dict) -> None:
    mine = p.get("account_id") is not None and p.get("account_id") in tracked
    cards.panel(img, (PAD, y, WIDTH - PAD, y + ROW_H), TRACKED_PANEL if mine else PANEL, radius=12)
    if mine:
        cards.stripe(img, PAD, y, y + ROW_H, TRACKED_MARK)
    mid = y + ROW_H / 2

    cards.paste(img, cards.hero_icon(icons.get(p.get("hero_id")), p.get("hero_id")), PAD + 24, mid - ICON_H / 2)

    name = clean(tracked.get(p.get("account_id")) or p.get("name")) or "Скрытый профиль"
    star = "★ " if mine else ""
    draw_text(draw, (NAME_X, mid - 14), star + name, 26, GOLD if mine else FG, bold=True, anchor="lm", max_w=NAME_MAX_W)
    hero = hero_name(p.get("hero_id"))
    if p.get("position"):
        hero += f"  ·  P{p['position']}"
    draw_text(draw, (NAME_X, mid + 18), hero, 20, MUTED, anchor="lm", max_w=NAME_MAX_W)

    cols = {key: cx for key, cx, _ in COLUMNS}
    cards.kda(draw, cols["kda"], mid, p.get("kills"), p.get("deaths"), p.get("assists"), 28)

    draw_text(draw, (cols["nw"], mid), _k(p.get("net_worth")), 26, GOLD, bold=True, anchor="mm")
    gpm, xpm = p.get("gpm"), p.get("xpm")
    econ = f"{gpm:.0f} / {xpm:.0f}" if gpm is not None and xpm is not None else (f"{gpm:.0f}" if gpm is not None else "—")
    draw_text(draw, (cols["gpm"], mid), econ, 24, FG, anchor="mm")
    draw_text(draw, (cols["dmg"], mid), _k(p.get("hero_damage")), 24, FG, anchor="mm")
    imp = p.get("imp")
    imp_color = MUTED if imp is None or round(imp) == 0 else (WIN if imp > 0 else LOSS)
    draw_text(draw, (cols["imp"], mid), cards.signed(imp), 26, imp_color, bold=True, anchor="mm")
