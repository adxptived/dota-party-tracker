"""Картинка матча (PNG в памяти): шапка с исходом и таблица команд — иконка героя, ник, K/D/A, экономика.

Рисуем на Pillow (ставится вместе с matplotlib), шрифт DejaVu берём из matplotlib — в нём есть кириллица.
Чистая функция: иконки приходят готовыми байтами (см. hero_icons.py), сети здесь нет.
Палитра — тёмная, как у графиков (charts.py), ширина под Telegram — 1280 px.
"""
from __future__ import annotations

import io
import os
from functools import lru_cache
from typing import Optional

from mmrbot.charts import BG, FG, GRID, LOSS, MUTED, PANEL, WIN, WIDTH_PX
from mmrbot.formatting import _imp, _k, fmt_local
from mmrbot.heroes import hero_name

RADIANT, DIRE = "#5cc46a", "#e5553f"
TRACKED_PANEL, TRACKED_MARK = "#1f2f40", "#f0b429"  # строка своего игрока: светлее фон + золотая полоса
GOLD = "#f0b429"

PAD = 32
HEAD_H = 132
TEAM_HEAD_H = 58
ROW_H, ROW_GAP = 78, 6
TEAM_GAP = 22
ICON_W, ICON_H = 112, 63  # 16:9, как у иконок dota_react
NAME_X = PAD + 24 + ICON_W + 20
NAME_MAX_W = 540 - NAME_X  # дальше — K/D/A (широкая: «12 / 11 / 25»)
# центры колонок (x) и их заголовки
COLUMNS = [("kda", 660, "K / D / A"), ("nw", 820, "Нетворт"), ("gpm", 960, "GPM / XPM"),
           ("dmg", 1090, "Урон"), ("imp", 1196, "IMP")]


@lru_cache(maxsize=16)
def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    try:
        import matplotlib
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        return ImageFont.truetype(os.path.join(matplotlib.get_data_path(), "fonts", "ttf", name), size)
    except Exception:
        return ImageFont.load_default(size)


def _clean(text) -> str:
    """Убираем управляющие символы и эмодзи вне BMP — в DejaVu их нет, рисовались бы квадраты."""
    return "".join(ch for ch in str(text or "") if ch.isprintable() and ord(ch) <= 0xFFFF).strip()


def _fit(text: str, font, max_w: int) -> str:
    if font.getlength(text) <= max_w:
        return text
    while text and font.getlength(text + "…") > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _center(draw, x: float, y: float, text: str, font, fill) -> None:
    draw.text((x, y), text, font=font, fill=fill, anchor="mm")


def _icon_image(data: Optional[bytes], hero_id):
    """Иконка героя, скруглённая; нет/битая — серая плашка с инициалами."""
    from PIL import Image, ImageDraw
    mask = Image.new("L", (ICON_W, ICON_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, ICON_W - 1, ICON_H - 1), radius=8, fill=255)
    icon = None
    if data:
        try:
            icon = Image.open(io.BytesIO(data)).convert("RGBA").resize((ICON_W, ICON_H), Image.LANCZOS)
        except Exception:
            icon = None
    if icon is None:
        icon = Image.new("RGBA", (ICON_W, ICON_H), GRID)
        name = hero_name(hero_id) if hero_id else "?"
        initials = "".join(word[0] for word in name.replace("-", " ").split()[:2]).upper() or "?"
        _center(ImageDraw.Draw(icon), ICON_W / 2, ICON_H / 2, initials, _font(26, True), MUTED)
    icon.putalpha(mask)
    return icon


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
    from PIL import Image, ImageDraw

    icons = icons or {}
    players = match.get("players") or []
    teams = [(True, _sorted_team([p for p in players if p.get("is_radiant")])),
             (False, _sorted_team([p for p in players if not p.get("is_radiant")]))]
    teams = [(side, team) for side, team in teams if team]
    height = _height([team for _, team in teams]) if teams else HEAD_H + PAD

    img = Image.new("RGB", (WIDTH_PX, height), BG)
    draw = ImageDraw.Draw(img)

    # --- шапка ---
    draw.text((PAD, 30), f"Матч {match.get('match_id')}", font=_font(40, True), fill=FG)
    when = fmt_local(match.get("start_time") or 0, tz, "%d.%m.%Y %H:%M")
    sub = when + (f"  ·  {match['duration'] // 60} мин" if match.get("duration") else "")
    draw.text((PAD, 84), sub, font=_font(24), fill=MUTED)
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
        font = _font(28, True)
        w = font.getlength(label) + 48
        x1, y0 = WIDTH_PX - PAD, 40
        draw.rounded_rectangle((x1 - w, y0, x1, y0 + 56), radius=28, fill=color)
        _center(draw, x1 - w / 2, y0 + 28, label, font, BG)

    # --- команды ---
    y = HEAD_H
    for side, team in teams:
        team_color = RADIANT if side else DIRE
        draw.rectangle((PAD, y + 12, PAD + 6, y + 44), fill=team_color)
        title = "RADIANT" if side else "DIRE"
        draw.text((PAD + 20, y + 28), title, font=_font(28, True), fill=team_color, anchor="lm")
        if radiant_win is not None and bool(radiant_win) == side:
            tx = PAD + 20 + _font(28, True).getlength(title) + 14
            draw.text((tx, y + 29), "победа", font=_font(20), fill=MUTED, anchor="lm")
        for _key, cx, head in COLUMNS:
            _center(draw, cx, y + 30, head, _font(18), MUTED)
        y += TEAM_HEAD_H
        for p in team:
            _draw_row(img, draw, y, p, tracked, icons)
            y += ROW_H + ROW_GAP
        y += TEAM_GAP

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _draw_row(img, draw, y: int, p: dict, tracked: dict, icons: dict) -> None:
    mine = p.get("account_id") is not None and p.get("account_id") in tracked
    draw.rounded_rectangle((PAD, y, WIDTH_PX - PAD, y + ROW_H), radius=12, fill=TRACKED_PANEL if mine else PANEL)
    if mine:
        draw.rounded_rectangle((PAD, y, PAD + 6, y + ROW_H), radius=3, fill=TRACKED_MARK)
    mid = y + ROW_H / 2

    icon = _icon_image(icons.get(p.get("hero_id")), p.get("hero_id"))
    img.paste(icon, (PAD + 24, int(mid - ICON_H / 2)), icon)

    name = _clean(tracked.get(p.get("account_id")) or p.get("name")) or "Скрытый профиль"
    name_font = _font(26, True)
    star = "★ " if mine else ""
    draw.text((NAME_X, mid - 14), _fit(star + name, name_font, NAME_MAX_W), font=name_font,
              fill=GOLD if mine else FG, anchor="lm")
    hero = hero_name(p.get("hero_id"))
    if p.get("position"):
        hero += f"  ·  P{p['position']}"
    draw.text((NAME_X, mid + 18), _fit(hero, _font(20), NAME_MAX_W), font=_font(20), fill=MUTED, anchor="lm")

    cols = {key: cx for key, cx, _ in COLUMNS}
    # K / D / A: смерти — красным, чтобы читалось с одного взгляда
    parts = [(str(p.get("kills") or 0), FG), (" / ", MUTED), (str(p.get("deaths") or 0), LOSS),
             (" / ", MUTED), (str(p.get("assists") or 0), FG)]
    kda_font = _font(28, True)
    x = cols["kda"] - sum(kda_font.getlength(text) for text, _ in parts) / 2
    for text, color in parts:
        draw.text((x, mid), text, font=kda_font, fill=color, anchor="lm")
        x += kda_font.getlength(text)

    _center(draw, cols["nw"], mid, _k(p.get("net_worth")), _font(26, True), GOLD)
    gpm, xpm = p.get("gpm"), p.get("xpm")
    econ = f"{gpm:.0f} / {xpm:.0f}" if gpm is not None and xpm is not None else (f"{gpm:.0f}" if gpm is not None else "—")
    _center(draw, cols["gpm"], mid, econ, _font(24), FG)
    _center(draw, cols["dmg"], mid, _k(p.get("hero_damage")), _font(24), FG)
    imp = p.get("imp")
    imp_color = MUTED if imp is None or round(imp) == 0 else (WIN if imp > 0 else LOSS)
    _center(draw, cols["imp"], mid, _imp(imp), _font(26, True), imp_color)
