"""Ежедневная сводка картинкой: баннер с итогами суток, плитки, таблица игроков с динамикой ±MMR, таймлайн игр,
рекорды и лучшая игра суток (K/D/A, показатели, билд). Окно — последние 24 часа до отправки (недельных данных здесь нет).

Чистая функция: описание карточки приходит словарём `view` (его собирает card_data.daily_card), иконки героев и
аватары — готовыми байтами; сети и БД здесь нет. Нет иконки/аватара — рисуется заглушка (см. cards.py).

view: title, window, span, badge (текст, цвет), big {value, color, label, sub}, tiles, rows, timeline, records,
best_game, footer, note. Строка таблицы (`rows`): name, avatar (url), rank_tier, rank_text, games, wins, losses, big,
big_color, sub, series [накопленное ±MMR от нуля], hero_id, hero_note. Таймлайн: since, until, ticks [(время, подпись)],
lanes [{name, avatar, games [{start, end, won}]}].
"""
from __future__ import annotations

from typing import Optional

from mmrbot import cards
from mmrbot.cards import ACCENT, BG, EDGE, FG, GOLD, LOSS, MUTED, PAD, PANEL, PANEL_HI, WIDTH, WIN, clean, draw_text, mix
from mmrbot.alert_image import _item_icon, clock
from mmrbot.heroes import hero_name
from mmrbot.stats_image import HERO_H, HERO_W, _draw_records, _draw_tiles, _place
from mmrbot.upgrade_icons import paste_upgrade

BANNER_H = 204
ROW_H, IDLE_H, ROW_GAP = 104, 68, 8
HEAD_ROW_H = 36
AVATAR, IDLE_AVATAR = 64, 44
NAME_X = PAD + 72 + AVATAR + 16
NAME_MAX_W = 290
BIG_RIGHT = 670
WL_X = 712
BAR_W = 110
SPARK_X0, SPARK_X1 = 900, 1090
HERO_X = WIDTH - PAD - 24 - HERO_W
LANE_H, LANE_GAP = 30, 10
LANE_LABEL_W = 220
BEST_TOP_H, BEST_BUILD_H = 210, 96
BEST_ITEM_W, BEST_ITEM_H, BEST_ITEM_GAP = 64, 48, 8
BEST_UPGRADE = 48
MAX_LANES = 8  # дорожек на таймлайне: больше — картинка превращается в простыню (в таблице всё равно видны все)


def _has_build(best: Optional[dict]) -> bool:
    build = (best or {}).get("build") or {}
    return bool(build.get("items") or build.get("neutral_item") or build.get("shard") or build.get("scepter"))


def render_daily_image(
    view: dict, icons: Optional[dict] = None, avatars: Optional[dict] = None, item_icons: Optional[dict] = None,
) -> bytes:
    """Сводка суток → PNG-байты. icons: {hero_id: байты}; avatars: {url: байты}; item_icons: {item_id: байты};
    отсутствующие рисуются заглушками."""
    icons, avatars, item_icons = icons or {}, avatars or {}, item_icons or {}
    rows, tiles = view.get("rows") or [], view.get("tiles") or []
    lanes = (view.get("timeline") or {}).get("lanes") or []
    records, best = view.get("records") or [], view.get("best_game")
    played = sum(1 for r in rows if r.get("games"))
    estimate = (PAD + BANNER_H + 40 + 150 + HEAD_ROW_H + played * (ROW_H + ROW_GAP) + (len(rows) - played) * (IDLE_H + ROW_GAP)
                + 120 + len(lanes[:MAX_LANES]) * (LANE_H + LANE_GAP) + 36 + ((len(records) + 2) // 3) * 112
                + ((80 + BEST_TOP_H + (BEST_BUILD_H if _has_build(best) else 0)) if best else 0) + 160)
    canvas = cards.Canvas(estimate)
    img, draw = canvas.img, canvas.draw

    y = _draw_banner(img, draw, PAD, view)
    if tiles:
        y = _draw_tiles(img, draw, y, tiles)
    if rows:
        y = _draw_table(img, draw, y + 8, rows, icons, avatars)
    if lanes:
        y = _draw_timeline(img, draw, y + 8, view["timeline"], avatars)
    if records:
        y = _section(draw, y + 14, "РЕКОРДЫ СУТОК")
        y = _draw_records(img, draw, y, records, icons)
    if best:
        y = _draw_best_game(img, draw, y + 14, best, icons, item_icons)
    if view.get("footer"):
        y = cards.footer(draw, y + 4, view["footer"])
    if view.get("note"):
        y = cards.footer(draw, y, view["note"])
    return canvas.png(y)


def _draw_best_game(img, draw, y: int, best: dict, icons: dict, item_icons: dict) -> int:
    """Лучшая игра суток: герой, игрок, крупные K/D/A и KDA, плитки показателей, ниже — билд (если известен)."""
    build = best.get("build") or {}
    height = BEST_TOP_H + (BEST_BUILD_H if _has_build(best) else 0)
    won = best.get("won")
    accent = WIN if won else LOSS
    cards.gradient_panel(img, (PAD, y, WIDTH - PAD, y + height), mix(PANEL, accent, 0.22), PANEL, radius=20, outline=EDGE)
    draw_text(draw, (PAD + 28, y + 32), "ЛУЧШАЯ ИГРА СУТОК", 20, ACCENT, bold=True, anchor="lm")
    cards.pill(img, draw, WIDTH - PAD - 28, y + 32, "ПОБЕДА" if won else "ПОРАЖЕНИЕ", BG, accent, size=18, pad=14, align="right")

    hero_id = best.get("hero_id")
    cards.paste(img, cards.hero_icon(icons.get(hero_id), hero_id, 160, 90, 10), PAD + 28, y + 62)
    tx = PAD + 28 + 160 + 24
    draw_text(draw, (tx, y + 80), clean(best.get("player")), 32, FG, bold=True, anchor="lm", max_w=330)
    draw_text(draw, (tx, y + 112), clean(hero_name(hero_id)), 22, MUTED, anchor="lm", max_w=330)
    cards.kda(draw, tx + 112, y + 160, best.get("kills"), best.get("deaths"), best.get("assists"), 44)
    draw_text(draw, (tx + 360, y + 160), f"KDA {clean(best.get('kda'))}", 26, GOLD, bold=True, anchor="rm")

    stats = (best.get("stats") or [])[:6]
    gx0, gx1 = PAD + 28 + 160 + 24 + 400, WIDTH - PAD - 28
    col_w = (gx1 - gx0) / 3
    for i, stat in enumerate(stats):
        cx = gx0 + (i % 3) * col_w
        cy = y + 80 + (i // 3) * 68
        draw_text(draw, (cx, cy), clean(stat.get("label")), 18, MUTED, anchor="lm", max_w=col_w - 10)
        draw_text(draw, (cx, cy + 28), clean(stat.get("value")), 28, FG, bold=True, anchor="lm", max_w=col_w - 10)

    if _has_build(best):
        by = y + BEST_TOP_H - 6
        draw.line([(PAD + 28, by), (WIDTH - PAD - 28, by)], fill=mix(PANEL_HI, MUTED, 0.3), width=1)
        _draw_best_build(img, draw, PAD + 28, by + 14, build, item_icons)
    return y + height + 14


def _draw_best_build(img, draw, x: float, top: float, build: dict, item_icons: dict) -> None:
    """Ряд билда: предметы с временами покупки, нейтралка, затем иконки шарда и скипетра (с временем)."""
    times = build.get("item_times") if isinstance(build.get("item_times"), list) else []
    ids = [i for i in build.get("items") or [] if isinstance(i, int) and not isinstance(i, bool) and i]
    for i, item_id in enumerate(ids):
        cards.paste(img, _item_icon(item_icons.get(item_id), BEST_ITEM_W, BEST_ITEM_H, 6), x, top)
        when = clock(times[i]) if i < len(times) else ""
        if when:
            draw_text(draw, (x + BEST_ITEM_W / 2, top + BEST_ITEM_H + 14), when, 16, MUTED, anchor="mm")
        x += BEST_ITEM_W + BEST_ITEM_GAP
    neutral = build.get("neutral_item")
    if isinstance(neutral, int) and not isinstance(neutral, bool) and neutral:
        x += 12
        cards.paste(img, _item_icon(item_icons.get(neutral), BEST_ITEM_W, BEST_ITEM_H, 6), x, top)
        draw_text(draw, (x + BEST_ITEM_W / 2, top + BEST_ITEM_H + 14), "нейтралка", 16, MUTED, anchor="mm")
        x += BEST_ITEM_W + BEST_ITEM_GAP
    x += 16
    for key, label, color in (("shard", "Ш", ACCENT), ("scepter", "С", GOLD)):
        if not build.get(key):
            continue
        width = paste_upgrade(img, key, x, top + BEST_ITEM_H / 2, BEST_UPGRADE)
        if width is None:  # иконки нет — прежняя подпись
            width = cards.pill(img, draw, x, top + BEST_ITEM_H / 2, label, BG, color, size=18, pad=10)
        when = clock(build.get(f"{key}_time"))
        if when:
            draw_text(draw, (x + width / 2, top + BEST_ITEM_H + 14), when, 16, MUTED, anchor="mm")
        x += width + 14


def _section(draw, y: int, title: str) -> int:
    draw_text(draw, (PAD + 6, y + 14), title, 20, ACCENT, bold=True, anchor="lm")
    return y + 36


def _draw_banner(img, draw, y: int, view: dict) -> int:
    """Баннер с градиентом: слева — что за сводка и за какое окно, справа — крупно ±MMR пати за сутки."""
    cards.gradient_panel(img, (PAD, y, WIDTH - PAD, y + BANNER_H), mix(PANEL, ACCENT, 0.34), PANEL, radius=24, outline=EDGE)
    x = PAD + 40
    badge_text, badge_color = view.get("badge") or ("24 ЧАСА", ACCENT)
    cards.chip(img, draw, x, y + 40, badge_text, badge_color, size=20, pad=16, base=mix(PANEL, ACCENT, 0.3))
    draw_text(draw, (x, y + 76), clean(view.get("title")), 46, FG, bold=True, max_w=640)
    draw_text(draw, (x, y + 140), clean(view.get("window")), 22, mix(FG, MUTED, 0.4), max_w=700)
    draw_text(draw, (x, y + 170), clean(view.get("span")), 22, MUTED, max_w=700)
    big = view.get("big") or {}
    right = WIDTH - PAD - 44
    draw_text(draw, (right, y + 84), clean(big.get("value")), 104, big.get("color") or FG, bold=True, anchor="rm")
    draw_text(draw, (right, y + 150), clean(big.get("label")), 22, MUTED, anchor="rm")
    draw_text(draw, (right, y + 180), clean(big.get("sub")), 26, FG, bold=True, anchor="rm", max_w=520)
    return y + BANNER_H + 18


def _draw_table(img, draw, y: int, rows: list, icons: dict, avatars: dict) -> int:
    """Таблица игроков суток: подписи столбцов и строки (игравшие — подробно, не игравшие — коротко)."""
    played = [r for r in rows if r.get("games")]
    draw_text(draw, (NAME_X, y + 10), "ИГРОК", 18, MUTED, anchor="lm")
    draw_text(draw, (BIG_RIGHT, y + 10), "±MMR", 18, MUTED, anchor="rm")
    draw_text(draw, (WL_X, y + 10), "РЕЗУЛЬТАТ", 18, MUTED, anchor="lm")
    if played:
        draw_text(draw, (SPARK_X0, y + 10), "ДИНАМИКА ДНЯ", 18, MUTED, anchor="lm")
    if any(r.get("hero_id") for r in played):
        draw_text(draw, (HERO_X + HERO_W / 2, y + 10), "ГЕРОЙ", 18, MUTED, anchor="mm")
    y += HEAD_ROW_H
    leader_possible = len(played) >= 2
    for place, row in enumerate(rows, start=1):
        if row.get("games"):
            _draw_row(img, draw, y, place, row, icons, avatars, leader=leader_possible and place == 1 and row.get("big_color") == WIN)
            y += ROW_H + ROW_GAP
        else:
            _draw_idle_row(img, draw, y, row, avatars)
            y += IDLE_H + ROW_GAP
    return y


def _draw_row(img, draw, y: int, place: int, row: dict, icons: dict, avatars: dict, leader: bool = False) -> None:
    box = (PAD, y, WIDTH - PAD, y + ROW_H)
    if leader:  # как у лидера рейтинга: золотой отсвет слева и полоса
        cards.gradient_panel(img, box, mix(PANEL, GOLD, 0.2), PANEL, radius=16, outline=mix(PANEL, GOLD, 0.3))
        cards.stripe(img, PAD, y + 14, y + ROW_H - 14, GOLD)
    else:
        cards.panel(img, box, PANEL, radius=16)
    mid = y + ROW_H / 2
    _place(img, draw, PAD + 44, mid, place)

    name = clean(row.get("name")) or "Игрок"
    cards.paste(img, cards.avatar(avatars.get(row.get("avatar")), name, AVATAR), PAD + 78, mid - AVATAR / 2)
    name_w = NAME_MAX_W - (100 if leader else 0)
    draw_text(draw, (NAME_X, mid - 16), name, 28, FG, bold=True, anchor="lm", max_w=name_w)
    if leader:
        shown = min(cards.text_width(name, 28, True), name_w)
        cards.pill(img, draw, NAME_X + shown + 12, mid - 16, "ЛИДЕР", BG, GOLD, size=16, pad=10)
    cards.paste(img, cards.rank_badge(row.get("rank_tier"), 32), NAME_X, mid + 2)
    draw_text(draw, (NAME_X + 42, mid + 18), clean(row.get("rank_text")), 20, MUTED, anchor="lm", max_w=NAME_MAX_W - 42)

    cards.value_text(draw, (BIG_RIGHT, mid - 13), row.get("big"), 38, row.get("big_color") or FG)
    draw_text(draw, (BIG_RIGHT, mid + 22), clean(row.get("sub")), 20, MUTED, anchor="rm", max_w=250)

    wins, losses = row.get("wins") or 0, row.get("losses") or 0
    games = wins + losses
    draw_text(draw, (WL_X, mid - 14), f"{wins}–{losses}", 28, FG, bold=True, anchor="lm")
    cards.winrate_bar(img, (WL_X, mid + 12, WL_X + BAR_W, mid + 22), wins, losses)
    draw_text(draw, (WL_X + BAR_W + 10, mid + 16), f"{round(wins * 100 / games)}%" if games else "", 20, MUTED, anchor="lm")

    series = list(row.get("series") or [])
    if series:
        color = row.get("big_color") if row.get("big_color") not in (None, MUTED) else ACCENT
        cards.sparkline(img, (SPARK_X0, mid - 34, SPARK_X1, mid + 34), series, color=color)

    hero_id = row.get("hero_id")
    if hero_id:
        cards.paste(img, cards.hero_icon(icons.get(hero_id), hero_id, HERO_W, HERO_H, 8), HERO_X, mid - HERO_H / 2 - 8)
        draw_text(draw, (HERO_X + HERO_W / 2, mid + HERO_H / 2 + 6), clean(row.get("hero_note")), 18, MUTED,
                  anchor="mm", max_w=HERO_W + 20)


def _draw_idle_row(img, draw, y: int, row: dict, avatars: dict) -> None:
    """Не играл за сутки: компактная приглушённая строка."""
    cards.panel(img, (PAD, y, WIDTH - PAD, y + IDLE_H), PANEL, radius=16)
    mid = y + IDLE_H / 2
    cards.dot(img, PAD + 44, mid, 14, PANEL_HI)
    draw_text(draw, (PAD + 44, mid), "–", 22, MUTED, bold=True, anchor="mm")
    name = clean(row.get("name")) or "Игрок"
    cards.paste(img, cards.avatar(avatars.get(row.get("avatar")), name, IDLE_AVATAR), PAD + 78, mid - IDLE_AVATAR / 2)
    nx = PAD + 78 + IDLE_AVATAR + 16
    draw_text(draw, (nx, mid), name, 24, MUTED, bold=True, anchor="lm", max_w=NAME_MAX_W)
    cards.paste(img, cards.rank_badge(row.get("rank_tier"), 30), nx + NAME_MAX_W + 14, mid - 15)
    draw_text(draw, (nx + NAME_MAX_W + 52, mid), clean(row.get("rank_text")), 20, MUTED, anchor="lm", max_w=250)
    draw_text(draw, (WL_X + 200, mid), clean(row.get("sub")) or "не играл", 22, MUTED, anchor="lm")


def _draw_timeline(img, draw, y: int, timeline: dict, avatars: dict) -> int:
    """Таймлайн суток: по дорожке на игрока, цветные отрезки — игры (зелёный — победа, красный — поражение)."""
    lanes = timeline["lanes"][:MAX_LANES]
    since, until = timeline["since"], timeline["until"]
    top = 66
    lanes_h = len(lanes) * LANE_H + (len(lanes) - 1) * LANE_GAP
    height = top + lanes_h + 56
    cards.panel(img, (PAD, y, WIDTH - PAD, y + height), PANEL, radius=16)
    draw_text(draw, (PAD + 24, y + 32), "ТАЙМЛАЙН ИГР · 24 ЧАСА", 20, ACCENT, bold=True, anchor="lm")
    legend_x = WIDTH - PAD - 24
    for label, color in (("поражение", LOSS), ("победа", WIN)):
        draw_text(draw, (legend_x, y + 32), label, 18, MUTED, anchor="rm")
        legend_x -= cards.text_width(label, 18) + 16
        cards.dot(img, legend_x, y + 32, 7, color)
        legend_x -= 30

    x0, x1 = PAD + 24 + LANE_LABEL_W, WIDTH - PAD - 24
    span = max(until - since, 1)

    def at(ts: float) -> float:
        return x0 + (min(max(ts, since), until) - since) / span * (x1 - x0)

    lane_y = [y + top + i * (LANE_H + LANE_GAP) for i in range(len(lanes))]
    for ly in lane_y:  # дорожки
        cards.panel(img, (x0, ly, x1, ly + LANE_H), PANEL_HI, radius=LANE_H // 2)
    for ts, label in timeline.get("ticks") or []:  # сетка по часам чата и подписи оси
        gx = round(at(ts))
        draw.line([(gx, y + top - 6), (gx, y + top + lanes_h + 6)], fill=mix(PANEL_HI, MUTED, 0.35), width=1)
        half = cards.text_width(label, 18) / 2  # крайние подписи не вылезают за панель
        lx = min(max(gx, PAD + 16 + half), WIDTH - PAD - 16 - half)
        draw_text(draw, (lx, y + top + lanes_h + 28), label, 18, MUTED, anchor="mm")
    for lane, ly in zip(lanes, lane_y):
        name = clean(lane.get("name")) or "Игрок"
        cards.paste(img, cards.avatar(avatars.get(lane.get("avatar")), name, 26), PAD + 24, ly + (LANE_H - 26) / 2)
        draw_text(draw, (PAD + 24 + 36, ly + LANE_H / 2), name, 22, FG, anchor="lm", max_w=LANE_LABEL_W - 44)
        for game in lane.get("games") or []:
            gx0, gx1 = at(game["start"]), at(game["end"])
            gx1 = max(gx1 - 1, gx0 + 8)  # зазор между соседними играми и минимальная ширина «короткой» игры
            cards.panel(img, (gx0, ly + 3, gx1, ly + LANE_H - 3), WIN if game.get("won") else LOSS, radius=(LANE_H - 6) // 2)
    return y + height + 8
