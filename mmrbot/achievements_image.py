"""Достижения картинкой (/achievements): у каждого игрока — значки с крупным числом, антирекорды отдельным рядом.

Чистая функция: данные — словарями (их собирает card_data.achievements_players), аватары — готовыми байтами;
сети и БД нет. Игрок: name, avatar, items [{code, detail}]. Эмодзи в Pillow без цветного шрифта не нарисовать,
поэтому значок — число (5, 100, 500…) и подпись, а не картинка: читается на любом экране.
У серий (победы подряд, игры, игры на герое) показывается только высший порог — младшие подразумеваются.
"""
from __future__ import annotations

from typing import Optional

from mmrbot import cards
from mmrbot.achievements import CATALOG
from mmrbot.cards import ACCENT, FG, GOLD, LOSS, MUTED, PAD, PANEL, PANEL_HI, WIDTH, WIN, clean, draw_text

PURPLE = "#9a74e6"
MAX_PLAYERS = 8
PER_ROW, GAP = 6, 14
TILE_W = (WIDTH - 2 * PAD - 2 * 22 - GAP * (PER_ROW - 1)) / PER_ROW  # плитки лежат в панели игрока с отступом 22
TILE_H = 132
HEAD_H = 84

# Серии по порогам: префикс кода → (подпись, цвет)
SERIES = {
    "win_streak_": ("побед подряд", WIN),
    "games_": ("ранкед-игр", ACCENT),
    "hero_": ("игр на герое", PURPLE),
    "lose_streak_": ("поражений подряд", LOSS),
}
# Одиночные: код → (число на значке, подпись, цвет)
SINGLES = {
    "kills_20": ("20+", "убийств за игру", GOLD),
    "deathless": ("0", "смертей за игру", GOLD),
    "deaths_20": ("20+", "смертей за игру", LOSS),
    "marathon": ("60+", "минут матча", GOLD),
}
ORDER = ["win_streak_", "games_", "hero_", "kills_20", "deathless", "marathon", "lose_streak_", "deaths_20"]


def _series(code: str) -> Optional[tuple[str, int]]:
    for prefix in SERIES:
        if code.startswith(prefix) and code[len(prefix):].isdigit():
            return prefix, int(code[len(prefix):])
    return None


def collapse(items: list) -> list:
    """Оставить высший порог в каждой серии; порядок — как в ORDER (сначала достижения, потом антирекорды)."""
    best: dict[str, tuple[int, dict]] = {}
    for item in items:
        code = item["code"]
        series = _series(code)
        key, rank = series if series else (code, 0)
        if key not in best or rank > best[key][0]:
            best[key] = (rank, item)
    keys = sorted(best, key=lambda k: ORDER.index(k) if k in ORDER else len(ORDER))
    return [best[k][1] for k in keys]


def badge_of(item: dict) -> dict:
    """Значок: big (число), label (подпись), sub (деталь: герой/счёт), color, anti."""
    code, detail = item["code"], item.get("detail")
    ach = CATALOG.get(code)
    anti = bool(ach and ach.anti)
    detail = None if detail is None else str(detail)
    series = _series(code)
    if series:
        prefix, need = series
        label, color = SERIES[prefix]
        sub = None
        if prefix == "hero_" and detail:
            sub = detail.split(" · ")[0]
        elif prefix in ("win_streak_", "lose_streak_") and detail and detail.isdigit() and int(detail) > need:
            sub = f"рекорд: {detail}"
        elif prefix == "games_" and detail and detail.isdigit() and int(detail) > need:
            sub = f"сейчас: {detail}"
        return {"big": str(need), "label": label, "sub": sub, "color": color, "anti": anti}
    if code in SINGLES:
        big, label, color = SINGLES[code]
        sub = detail
        if code == "marathon" and detail:
            sub = detail.split(" · ")[0]  # «Pudge · 63 мин» → герой; минуты и так на значке
        return {"big": big, "label": label, "sub": sub, "color": color, "anti": anti}
    return {"big": "★", "label": ach.title if ach else str(code), "sub": detail, "color": LOSS if anti else GOLD, "anti": anti}


def _tile(img, draw, x0: float, y0: float, badge: dict) -> None:
    color = badge["color"]
    cards.panel(img, (x0, y0, x0 + TILE_W, y0 + TILE_H), PANEL_HI, radius=16, outline=color if badge["anti"] else None)
    cards.stripe(img, x0 + 12, y0 + 18, y0 + TILE_H - 18, color, width=5)
    cx = x0 + TILE_W / 2 + 4
    draw_text(draw, (cx, y0 + 46), clean(badge["big"]), 46, color, bold=True, anchor="mm", max_w=TILE_W - 44)
    label, size = clean(badge["label"]), 16
    while size > 13 and cards.text_width(label, size, False) > TILE_W - 26:  # длинная подпись — мельче, а не с «…»
        size -= 1
    draw_text(draw, (cx, y0 + 88), label, size, FG, anchor="mm", max_w=TILE_W - 26)
    if badge.get("sub"):
        draw_text(draw, (cx, y0 + 112), clean(badge["sub"]), 16, MUTED, anchor="mm", max_w=TILE_W - 36)


def _plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    word = one if n10 == 1 and n100 != 11 else few if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else many
    return f"{n} {word}"


def _rows(n: int) -> int:
    return (n + PER_ROW - 1) // PER_ROW


def _block_height(good: list, anti: list) -> int:
    if not good and not anti:
        return HEAD_H + 56
    h = HEAD_H + 8
    if good:
        h += _rows(len(good)) * (TILE_H + GAP)
    if anti:
        h += 38 + _rows(len(anti)) * (TILE_H + GAP)
    return h + 4


def _split(player: dict) -> tuple[list, list]:
    badges = [badge_of(i) for i in collapse(player.get("items") or [])]
    return [b for b in badges if not b["anti"]], [b for b in badges if b["anti"]]


def render_achievements_image(players: list, avatars: Optional[dict] = None, note: Optional[str] = None,
                              subtitle: Optional[str] = None) -> bytes:
    """Достижения игроков → PNG-байты. Показывается до MAX_PLAYERS игроков (остальные — строкой «и ещё N»)."""
    avatars = avatars or {}
    shown, hidden = players[:MAX_PLAYERS], max(len(players) - MAX_PLAYERS, 0)
    split = [_split(p) for p in shown]
    total = 320 + sum(_block_height(g, a) + 16 for g, a in split) + (50 if hidden else 0) + (60 if note else 0)
    canvas = cards.Canvas(total)
    img, draw = canvas.img, canvas.draw
    y = cards.header(img, draw, "Достижения", subtitle or "значки за всю историю ранкеда, антирекорды — отдельным рядом")

    if not shown:
        cards.panel(img, (PAD, y, WIDTH - PAD, y + 110), PANEL, radius=18)
        draw_text(draw, (PAD + 28, y + 55), "Игроков пока нет.", 28, MUTED, anchor="lm")
        y += 126
    for player, (good, anti) in zip(shown, split):
        h = _block_height(good, anti)
        cards.panel(img, (PAD, y, WIDTH - PAD, y + h), PANEL, radius=20)
        name = clean(player.get("name")) or "Игрок"
        cards.paste(img, cards.avatar(avatars.get(player.get("avatar")), name, 52), PAD + 22, y + 16)
        draw_text(draw, (PAD + 22 + 52 + 16, y + 42), name, 28, FG, bold=True, anchor="lm", max_w=520)
        right = WIDTH - PAD - 22
        if anti:
            right -= cards.pill(img, draw, right, y + 42, _plural(len(anti), "антирекорд", "антирекорда", "антирекордов"), cards.BG, LOSS, size=18, align="right", pad=12) + 10
        if good:
            cards.pill(img, draw, right, y + 42, _plural(len(good), "достижение", "достижения", "достижений"), cards.BG, GOLD, size=18, align="right", pad=12)
        ty = y + HEAD_H
        if not good and not anti:
            draw_text(draw, (PAD + 22, ty + 16), "пока нет достижений", 22, MUTED, anchor="lm")
        for i, badge in enumerate(good):
            _tile(img, draw, PAD + 22 + (i % PER_ROW) * (TILE_W + GAP), ty + (i // PER_ROW) * (TILE_H + GAP), badge)
        if good:
            ty += _rows(len(good)) * (TILE_H + GAP)
        if anti:
            draw_text(draw, (PAD + 22, ty + 12), "АНТИРЕКОРДЫ", 17, LOSS, bold=True, anchor="lm")
            ty += 38
            for i, badge in enumerate(anti):
                _tile(img, draw, PAD + 22 + (i % PER_ROW) * (TILE_W + GAP), ty + (i // PER_ROW) * (TILE_H + GAP), badge)
        y += h + 16
    if hidden:
        draw_text(draw, (PAD + 10, y + 14), f"и ещё {hidden} игроков — полный список текстом", 20, MUTED, anchor="lm")
        y += 40
    if note:
        y = cards.footer(draw, y, note)
    return canvas.png(y)

