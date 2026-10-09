"""Оповещение о конце матча картинкой: шапка с исходом и лобби, по строке на каждого игрока пати
(аватар, иконка героя, ник, K/D/A, ±MMR → ≈MMR, серия), внизу «Сегодня вместе».

Чистая функция: иконки героев и аватары приходят готовыми байтами, сети и БД здесь нет.
"""
from __future__ import annotations

import html
import io
from functools import lru_cache
from typing import Optional

from mmrbot import cards
from mmrbot.boards import CAPTION_LIMIT
from mmrbot.cards import (
    ACCENT, BG, FG, GOLD, ICON_H, ICON_W, LOSS, MUTED, PAD, PANEL, WIDTH, WIN, clean, draw_text, signed,
)
from mmrbot.formatting import _k, _mvp_name, _thousands, fmt_local, plural_games
from mmrbot.heroes import hero_name
from mmrbot.ranks import rank_label
from mmrbot.upgrade_icons import paste_upgrade

ROW_H, ROW_GAP = 104, 10
AVATAR = 64
NAME_X = PAD + 22 + AVATAR + 14 + ICON_W + 20
NAME_MAX_W = 360
KDA_X = 760
RIGHT = WIDTH - PAD - 24
FOOT_H = 76
STRIP_H = 52  # полоса под строкой игрока: билд, апгрейды, фарм, ранг (только если есть что показать)
TIME_H = 18  # + подписи времени покупки под иконками предметов
ITEM_W, ITEM_H, ITEM_GAP = 54, 40, 6
BADGE = 40
UPGRADE_SIZE = 32
STRIP_TEXT_X = 840  # фарм и урон по зданиям — правее билда и значков апгрейдов


def _outcome(rows: list) -> tuple[str, str]:
    wins = sum(1 for r in rows if r.get("won"))
    if wins == len(rows):
        return "ПОБЕДА", WIN
    if wins == 0:
        return "ПОРАЖЕНИЕ", LOSS
    return "РАЗНЫЕ СТОРОНЫ", ACCENT


def _delta(row: dict) -> int:
    """±MMR за матч: готовое значение строки (учитывает дабл-даун), у старых событий — шаг по исходу."""
    if row.get("delta") is not None:
        return row["delta"]
    step = row.get("step") or 0
    return step if row.get("won") else -step


def clock(seconds) -> str:
    """Время игры м:сс (покупка до старта — 0:00); не число — пустая строка."""
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return ""
    seconds = max(int(seconds), 0)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _has_strip(row: dict) -> bool:
    return bool(row.get("items") or row.get("neutral_item") or row.get("rank_tier") or row.get("shard")
                or row.get("scepter") or row.get("tower_damage"))


def _times(row: dict) -> list:
    """Подписи времени покупки по слотам билда ('' — неизвестно)."""
    return [clock(t) for t in (row.get("item_times") or [])[: len(row.get("items") or [])]]


def _row_h(row: dict) -> int:
    if not _has_strip(row):
        return ROW_H
    return ROW_H + STRIP_H + (TIME_H if any(_times(row)) else 0)


@lru_cache(maxsize=512)
def _item_icon(data: Optional[bytes], w: int = ITEM_W, h: int = ITEM_H, radius: int = 6):
    """Иконка предмета со скруглением; нет/битая — тёмная плашка."""
    from PIL import Image
    icon = None
    if data:
        try:
            icon = Image.open(io.BytesIO(data)).convert("RGBA").resize((w, h), Image.LANCZOS)
        except Exception:
            icon = None
    if icon is None:
        icon = Image.new("RGBA", (w, h), cards.GRID)
    icon.putalpha(cards._rr_mask(w, h, radius))
    return icon


def render_alert_image(
    event: dict, tz: str = "UTC", icons: Optional[dict] = None, avatars: Optional[dict] = None,
    item_icons: Optional[dict] = None,
) -> bytes:
    """Событие `detect_new_games` (kind="match") → PNG-байты.

    icons: {hero_id: PNG-байты}; avatars: {url: байты}; item_icons: {item_id: PNG-байты};
    отсутствующие рисуются заглушками.
    """
    icons, avatars, item_icons = icons or {}, avatars or {}, item_icons or {}
    rows = event.get("rows") or []
    label, color = _outcome(rows) if rows else ("МАТЧ", ACCENT)
    canvas = cards.Canvas(260 + sum(_row_h(r) + ROW_GAP for r in rows) + FOOT_H + 100, accent=color)
    img, draw = canvas.img, canvas.draw
    y = _draw_banner(img, draw, PAD, event, tz, label, color) + 14

    mvp = _mvp_name(rows)
    for row in rows:
        _draw_row(img, draw, y, row, icons, avatars, mvp, item_icons)
        y += _row_h(row) + ROW_GAP

    shared = event.get("shared")
    if shared and shared.get("games"):
        _draw_shared(img, draw, y, shared)
        y += FOOT_H
    return canvas.png(y)


BANNER_H = 136


def _draw_banner(img, draw, y: int, event: dict, tz: str, label: str, color: str) -> int:
    """Шапка-плашка: исход крупно цветом (это главное в оповещении), под ним «Матч завершён · дата · длительность»,
    справа — средний ранг лобби и ID матча. Возвращает y под плашкой."""
    box = (PAD, y, WIDTH - PAD, y + BANNER_H)
    cards.gradient_panel(img, box, cards.mix(PANEL, color, 0.34), cards.mix(PANEL, color, 0.04), radius=20,
                         outline=cards.mix(PANEL, color, 0.42))
    cards.stripe(img, PAD, y + 20, y + BANNER_H - 20, color)
    when = fmt_local(event.get("start_time") or 0, tz, "%d.%m.%Y %H:%M")
    sub = "Матч завершён  ·  " + when + (f"  ·  {event['duration'] // 60} мин" if event.get("duration") else "")
    right = WIDTH - PAD - 28
    rank = event.get("average_rank")
    side_w = 300 if rank else 240
    draw_text(draw, (PAD + 32, y + 52), label, 56, cards.mix(color, "#ffffff", 0.12), bold=True, anchor="lm",
              max_w=WIDTH - 2 * PAD - 60 - side_w)
    draw_text(draw, (PAD + 34, y + 104), sub, 22, cards.mix(MUTED, "#ffffff", 0.25), anchor="lm",
              max_w=WIDTH - 2 * PAD - 60 - side_w)
    match_id = f"ID {event.get('match_id')}"
    if rank:
        cards.paste(img, cards.rank_badge(rank, 64), right - 64, y + 20)
        draw_text(draw, (right - 78, y + 38), "ЛОББИ", 18, cards.mix(MUTED, "#ffffff", 0.2), bold=True, anchor="rm")
        draw_text(draw, (right - 78, y + 66), rank_label(rank), 24, FG, bold=True, anchor="rm", max_w=side_w - 90)
        draw_text(draw, (right, y + 108), match_id, 18, cards.mix(MUTED, "#ffffff", 0.1), anchor="rm")
    else:
        draw_text(draw, (right, y + BANNER_H / 2), match_id, 20, cards.mix(MUTED, "#ffffff", 0.1), anchor="rm")
    return y + BANNER_H


def _draw_row(
    img, draw, y: int, row: dict, icons: dict, avatars: dict, mvp: Optional[str], item_icons: Optional[dict] = None,
) -> None:
    won = bool(row.get("won"))
    accent = WIN if won else LOSS
    fill = cards.mix(PANEL, accent, 0.05)
    cards.gradient_panel(img, (PAD, y, WIDTH - PAD, y + _row_h(row)), cards.mix(PANEL, accent, 0.16), fill, radius=16,
                         outline=cards.mix(fill, "#ffffff", 0.07))
    cards.stripe(img, PAD, y + 16, y + ROW_H - 16, accent)
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

    cards.kda(draw, KDA_X, mid - 8, row.get("kills"), row.get("deaths"), row.get("assists"), 36)
    draw_text(draw, (KDA_X, mid + 26), "K / D / A", 18, cards.mix(MUTED, PANEL, 0.25), anchor="mm")

    delta = _delta(row)
    mmr = row.get("current_mmr")
    streak = row.get("streak_len") or 0
    top = mid - 12 if streak >= 3 else mid
    x = RIGHT
    if mmr is not None:
        x -= cards.value_text(draw, (x, top), f"≈{mmr}", 36, FG) + 12
        draw_text(draw, (x, top), "→", 24, cards.mix(MUTED, PANEL, 0.3), anchor="rm")
        x -= cards.text_width("→", 24) + 12
    draw_text(draw, (x, top), signed(delta), 36, cards.delta_color(delta), bold=True, anchor="rm")
    if streak >= 3:
        is_win = row.get("streak_type") == "W"
        text = f"▲ {streak} подряд" if is_win else f"▼ {streak} подряд"
        cards.chip(img, draw, RIGHT, mid + 28, text, WIN if is_win else LOSS, size=18, pad=12, align="right", base=fill)
    if _has_strip(row):
        _draw_strip(img, draw, y + ROW_H + STRIP_H / 2 - 2, row, item_icons or {})


def _draw_strip(img, draw, mid: float, row: dict, item_icons: dict) -> None:
    """Билд (6 слотов + нейтралка) слева, фарм посередине, ранг справа."""
    x = PAD + 22
    times = _times(row)
    for i, item_id in enumerate(row.get("items") or []):
        cards.paste(img, _item_icon(item_icons.get(item_id)), x, mid - ITEM_H / 2)
        if i < len(times) and times[i]:
            draw_text(draw, (x + ITEM_W / 2, mid + ITEM_H / 2 + 11), times[i], 15, MUTED, anchor="mm")
        x += ITEM_W + ITEM_GAP
    if row.get("neutral_item"):
        x += 10
        cards.paste(img, _item_icon(item_icons.get(row["neutral_item"])), x, mid - ITEM_H / 2)
        x += ITEM_W
    x += 14
    for key, label, color in (("shard", "ШАРД", ACCENT), ("scepter", "СКИПЕТР", GOLD)):
        if row.get(key):
            when = clock(row.get(f"{key}_time"))
            icon_w = paste_upgrade(img, key, x, mid, UPGRADE_SIZE)
            if icon_w is None:
                x += cards.pill(img, draw, x, mid, f"{label} {when}".strip(), BG, color, size=16, pad=10) + 8
                continue
            if when:  # время покупки — подписью под иконкой, как у предметов
                draw_text(draw, (x + icon_w / 2, mid + ITEM_H / 2 + 11), when, 15, MUTED, anchor="mm")
            x += max(icon_w, cards.text_width(when, 15) if when else 0) + 10
    farm = []
    if row.get("net_worth"):
        farm.append(f"NW {_k(row['net_worth'])}")
    if row.get("last_hits") is not None:
        farm.append(f"{row['last_hits']}/{row.get('denies') or 0}")
    lines = ["  ·  ".join(farm)] if farm else []
    if isinstance(row.get("tower_damage"), (int, float)) and row["tower_damage"]:
        lines.append(f"{_k(row['tower_damage'])} по зданиям")
    for i, line in enumerate(lines):
        draw_text(draw, (STRIP_TEXT_X, mid + (i - (len(lines) - 1) / 2) * 24), line, 18, MUTED, anchor="lm")
    if row.get("rank_tier"):
        cards.paste(img, cards.rank_badge(row["rank_tier"], BADGE), RIGHT - BADGE, mid - BADGE / 2)
        draw_text(draw, (RIGHT - BADGE - 10, mid), rank_label(row["rank_tier"]), 20, FG, anchor="rm")


def _draw_shared(img, draw, y: int, shared: dict) -> None:
    cards.panel(img, (PAD, y + 6, WIDTH - PAD, y + FOOT_H - 6), cards.PANEL_HI, radius=16)
    mid = y + FOOT_H / 2
    draw_text(draw, (PAD + 24, mid), "СЕГОДНЯ ВМЕСТЕ", 18, MUTED, bold=True, anchor="lm")
    x = PAD + 24 + cards.text_width("СЕГОДНЯ ВМЕСТЕ", 18, True) + 20
    text = plural_games(shared["games"])
    draw_text(draw, (x, mid), text, 26, FG, bold=True, anchor="lm")
    score = f"{shared.get('wins', 0)}–{shared.get('losses', 0)}"
    draw_text(draw, (WIDTH - PAD - 24, mid), score, 30, FG, bold=True, anchor="rm")
    bar_x1 = WIDTH - PAD - 24 - cards.text_width(score, 30, True) - 24
    bar_x0 = x + cards.text_width(text, 26, True) + 28
    if bar_x1 - bar_x0 > 80:
        cards.winrate_bar(img, (bar_x0, mid - 6, bar_x1, mid + 6), shared.get("wins", 0), shared.get("losses", 0))



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
