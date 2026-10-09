"""Картинка матча (PNG в памяти): шапка с исходом и таблица команд — иконка героя, ник, билд, K/D/A, экономика.

Рисуем на Pillow (ставится вместе с matplotlib), шрифт DejaVu берём из matplotlib — в нём есть кириллица.
Чистая функция: иконки приходят готовыми байтами (см. hero_icons.py), сети здесь нет.
Палитра — тёмная, как у графиков (charts.py). Ширина больше карточек (1560 против 1280): в строке рядом
с ником помещается билд, и колонки не наезжают друг на друга; Telegram держит фото до 2560 px.
"""
from __future__ import annotations

from typing import Optional

from mmrbot import cards
from mmrbot.alert_image import _item_icon, clock
from mmrbot.cards import (
    ACCENT, DIRE, FG, GOLD, ICON_H, ICON_W, LOSS, MINE_PANEL, MUTED, PAD, PANEL, RADIANT, WIN, clean, draw_text,
)
from mmrbot.charts import BG
from mmrbot.formatting import _k, fmt_local
from mmrbot.heroes import hero_name
from mmrbot.upgrade_icons import paste_upgrade

MATCH_WIDTH = 1560
TRACKED_PANEL, TRACKED_MARK = MINE_PANEL, GOLD  # строка своего игрока: светлее фон + золотая полоса

HEAD_H = 132
TEAM_HEAD_H = 58
ROW_H, ROW_GAP = 78, 6
ROW_BEAR_H = 118  # у Лон Друида две строки предметов: свои и медведя
TEAM_GAP = 22
NAME_X = PAD + 24 + ICON_W + 20
NAME_W = 250  # с билдом: до начала предметов
NAME_W_BEAR = 200  # в строке медведя левее предметов стоят подписи «Герой»/«Медведь»
NAME_W_FREE = 640  # без билда ник может занять всё место до K/D/A
ITEMS_X = 452
SLOT_W, SLOT_H, SLOT_GAP = 44, 33, 3
TAGS_X = 800  # иконки шарда и скипетра — после предметов и нейтралки
UPGRADE_SIZE = 24
# центры колонок (x) и их заголовки
COLUMNS = [("kda", 940, "K / D / A"), ("nw", 1090, "Нетворт"), ("gpm", 1225, "GPM / XPM"),
           ("dmg", 1360, "Урон"), ("imp", 1480, "IMP")]


def _sorted_team(players: list[dict]) -> list[dict]:
    return sorted(players, key=lambda p: p.get("position") or 9)


def _ids(values) -> list:
    """Только настоящие id предметов: мусор и пустые слоты отбрасываем."""
    return [i for i in values or [] if isinstance(i, int) and not isinstance(i, bool) and i]


def _has_build(players: list[dict]) -> bool:
    return any(p.get("items") or p.get("neutral_item") or _ids(p.get("bear_items")) for p in players)


def _has_bear(p: dict) -> bool:
    return bool(_ids(p.get("bear_items")))


def _row_h(p: dict) -> int:
    return ROW_BEAR_H if _has_bear(p) else ROW_H


def _height(teams: list[list[dict]]) -> int:
    body = sum(TEAM_HEAD_H + sum(_row_h(p) + ROW_GAP for p in team) for team in teams) + TEAM_GAP * (len(teams) - 1)
    return HEAD_H + body + PAD


def render_match_image(match: dict, tracked: dict, focus=None, tz: str = "UTC",
                       icons: Optional[dict] = None, item_icons: Optional[dict] = None, fmt: str = "PNG") -> bytes:
    """Матч (формат Stratz.get_match: 1–10 игроков) → байты картинки (PNG, либо JPEG при fmt="JPEG").

    tracked: {account_id: имя в боте} — свои игроки подсвечены и подписаны именем из бота;
    focus — чей исход в шапке («ПОБЕДА»/«ПОРАЖЕНИЕ»); без него — какая сторона победила.
    icons: {hero_id: PNG-байты}, item_icons: {item_id: PNG-байты}; отсутствующие рисуются заглушкой.
    Игрок с известным билдом (items, item_times, neutral_item, shard, scepter) — предметы со временем покупки
    между ником и K/D/A; у Лон Друида вторая строка — инвентарь медведя (bear_items, bear_item_times, bear_neutral).
    """
    icons, item_icons = icons or {}, item_icons or {}
    players = match.get("players") or []
    teams = [(True, _sorted_team([p for p in players if p.get("is_radiant")])),
             (False, _sorted_team([p for p in players if not p.get("is_radiant")]))]
    teams = [(side, team) for side, team in teams if team]
    me = next((p for p in players if focus is not None and p.get("account_id") == focus), None)
    build = _has_build(players)
    height = _height([team for _, team in teams]) if teams else HEAD_H + PAD

    canvas = cards.Canvas(height, MATCH_WIDTH)
    img, draw = canvas.img, canvas.draw

    # --- шапка ---
    draw_text(draw, (PAD, 30), f"Матч {match.get('match_id')}", 40, FG, bold=True)
    when = fmt_local(match.get("start_time") or 0, tz, "%d.%m.%Y %H:%M")
    sub = when + (f"  ·  {match['duration'] // 60} мин" if match.get("duration") else "")
    draw_text(draw, (PAD, 84), sub, 24, MUTED)
    radiant_win = match.get("radiant_win")
    if me is not None and radiant_win is not None:
        won = bool(me.get("is_radiant")) == bool(radiant_win)
        label, color = ("ПОБЕДА", WIN) if won else ("ПОРАЖЕНИЕ", LOSS)
    elif radiant_win is not None:
        label, color = ("ПОБЕДА RADIANT", RADIANT) if radiant_win else ("ПОБЕДА DIRE", DIRE)
    else:
        label, color = None, None
    if label:
        cards.pill(img, draw, MATCH_WIDTH - PAD, 68, label, BG, color, size=28, align="right", pad=24)

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
        if build:
            draw_text(draw, (ITEMS_X, y + 30), "Билд · время покупки", 18, MUTED, anchor="lm")
        for _key, cx, head in COLUMNS:
            draw_text(draw, (cx, y + 30), head, 18, MUTED, anchor="mm")
        y += TEAM_HEAD_H
        for p in team:
            _draw_row(img, draw, y, p, tracked, icons, item_icons, build)
            y += _row_h(p) + ROW_GAP
        y += TEAM_GAP

    return canvas.png(fmt=fmt)


def _draw_items(img, draw, top: float, items, times, neutral, item_icons: dict) -> None:
    """Одна линия билда: предметы по слотам, под каждым время покупки, затем нейтралка."""
    x = ITEMS_X
    times = times if isinstance(times, list) else []
    for i, item_id in enumerate(_ids(items)):
        cards.paste(img, _item_icon(item_icons.get(item_id), SLOT_W, SLOT_H, 5), x, top)
        when = clock(times[i]) if i < len(times) else ""
        if when:
            draw_text(draw, (x + SLOT_W / 2, top + SLOT_H + 10), when, 14, MUTED, anchor="mm")
        x += SLOT_W + SLOT_GAP
    if isinstance(neutral, int) and not isinstance(neutral, bool) and neutral:
        cards.paste(img, _item_icon(item_icons.get(neutral), SLOT_W, SLOT_H, 5), x + 5, top)


def _draw_build(img, draw, y: int, p: dict, item_icons: dict) -> None:
    """Билд игрока между ником и K/D/A; Лон Друид — две линии (герой и медведь) с подписями."""
    mid = y + _row_h(p) / 2
    bear = _has_bear(p)
    top = y + 12 if bear else mid - SLOT_H / 2 - 4
    _draw_items(img, draw, top, p.get("items"), p.get("item_times"), p.get("neutral_item"), item_icons)
    if bear:
        bear_top = top + SLOT_H + 28
        _draw_items(img, draw, bear_top, p.get("bear_items"), p.get("bear_item_times"), p.get("bear_neutral"),
                    item_icons)
        draw_text(draw, (ITEMS_X - 10, top + SLOT_H / 2), "Герой", 14, MUTED, anchor="rm")
        draw_text(draw, (ITEMS_X - 10, bear_top + SLOT_H / 2), "Медведь", 14, MUTED, anchor="rm")
    for cy, key, tag, color in ((mid - 14, "shard", "Ш", ACCENT), (mid + 14, "scepter", "С", GOLD)):
        if p.get(key) and paste_upgrade(img, key, TAGS_X, cy, UPGRADE_SIZE) is None:
            cards.pill(img, draw, TAGS_X, cy, tag, BG, color, size=13, pad=5)


def _draw_row(img, draw, y: int, p: dict, tracked: dict, icons: dict, item_icons: Optional[dict] = None,
              build: bool = False) -> None:
    mine = p.get("account_id") is not None and p.get("account_id") in tracked
    row_h = _row_h(p)
    cards.panel(img, (PAD, y, MATCH_WIDTH - PAD, y + row_h), TRACKED_PANEL if mine else PANEL, radius=12)
    if mine:
        cards.stripe(img, PAD, y, y + row_h, TRACKED_MARK)
    mid = y + row_h / 2

    cards.paste(img, cards.hero_icon(icons.get(p.get("hero_id")), p.get("hero_id")), PAD + 24, mid - ICON_H / 2)

    name_w = (NAME_W_BEAR if _has_bear(p) else NAME_W) if build else NAME_W_FREE
    name = clean(tracked.get(p.get("account_id")) or p.get("name")) or "Скрытый профиль"
    star = "★ " if mine else ""
    draw_text(draw, (NAME_X, mid - 14), star + name, 26, GOLD if mine else FG, bold=True, anchor="lm", max_w=name_w)
    hero = hero_name(p.get("hero_id"))
    if p.get("position"):
        hero += f"  ·  P{p['position']}"
    draw_text(draw, (NAME_X, mid + 18), hero, 20, MUTED, anchor="lm", max_w=name_w)
    if build:
        _draw_build(img, draw, y, p, item_icons or {})

    cols = {key: cx for key, cx, _ in COLUMNS}
    cards.kda(draw, cols["kda"], mid, p.get("kills"), p.get("deaths"), p.get("assists"), 28)

    draw_text(draw, (cols["nw"], mid), _k(p.get("net_worth")), 26, GOLD, bold=True, anchor="mm")
    gpm, xpm = p.get("gpm"), p.get("xpm")
    econ = f"{gpm:.0f} / {xpm:.0f}" if gpm is not None and xpm is not None else (f"{gpm:.0f}" if gpm is not None else "—")
    draw_text(draw, (cols["gpm"], mid), econ, 24, FG, anchor="mm")
    tower = p.get("tower_damage")
    draw_text(draw, (cols["dmg"], mid - (11 if tower else 0)), _k(p.get("hero_damage")), 24, FG, anchor="mm")
    if tower:  # урон по зданиям — вторым рядом: в колонке нет места для двух чисел в строку
        draw_text(draw, (cols["dmg"], mid + 15), f"{_k(tower)} здания", 17, MUTED, anchor="mm")
    imp = p.get("imp")
    imp_color = MUTED if imp is None or round(imp) == 0 else (WIN if imp > 0 else LOSS)
    draw_text(draw, (cols["imp"], mid), cards.signed(imp), 26, imp_color, bold=True, anchor="mm")
