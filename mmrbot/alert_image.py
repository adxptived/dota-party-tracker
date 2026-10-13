"""Оповещение о конце матча картинкой. Цифры не толпятся наверху: шапка — только исход и лобби; в строке игрока
сверху — аватар, герой, ник, позиция и исход линии, ±MMR → ≈MMR, ранг и серия; ниже — билд со временем покупки
и подписанные ячейки (K/D/A, IMP, GPM; у коров нетворс, добито/не отдано, урон, здания; у саппортов — варды, стаки,
лечение, урон); под игроками — итог матча (счёт, золото, длительность, начало, ID) и «Сегодня вместе».

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
from mmrbot.formatting import (
    _k, _mvp_name, _thousands, fmt_local, gold_lead, is_support, lane_text, match_score, plural_games,
)
from mmrbot.heroes import hero_name
from mmrbot.ranks import rank_label
from mmrbot.upgrade_icons import paste_upgrade

TOP_H = 96  # верх строки игрока: аватар, герой, ник и ±MMR — без россыпи чисел
ROW_GAP = 10
AVATAR = 64
NAME_X = PAD + 22 + AVATAR + 14 + ICON_W + 20
RIGHT = WIDTH - PAD - 24
CELLS_X = PAD + 24
BUILD_H = 54  # линия билда под верхом строки (только если билд известен)
TIME_H = 20  # + подписи времени покупки под иконками предметов
CELLS_H = 66  # ряд подписанных ячеек: K/D/A, IMP, экономика, урон
TALENTS_H = 70  # выбранные таланты сеткой 2×2 (если известны)
ITEM_W, ITEM_H, ITEM_GAP = 54, 40, 6
UPGRADE_SIZE = 32
CELL_MAX_W = 176
SUMMARY_H = 84  # итог матча внизу: счёт, золото, длительность, дата и ID
FOOT_H = 76
BANNER_H = 112
TIME_COLOR = cards.TIME_COLOR


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


def _has_build(row: dict) -> bool:
    return bool(row.get("items") or row.get("neutral_item") or row.get("shard") or row.get("scepter"))


def _times(row: dict) -> list:
    """Подписи времени покупки по слотам билда ('' — неизвестно)."""
    return [clock(t) for t in (row.get("item_times") or [])[: len(row.get("items") or [])]]


def _build_h(row: dict) -> int:
    if not _has_build(row):
        return 0
    return BUILD_H + (TIME_H if any(_times(row)) or _upgrade_times(row) else 0)


def _upgrade_times(row: dict) -> bool:
    return any(row.get(key) and clock(row.get(f"{key}_time")) for key in ("shard", "scepter"))


def _talents(row: dict) -> list:
    """Выбранные таланты [[уровень, название]] без мусора."""
    return [t for t in row.get("talents") or [] if isinstance(t, (list, tuple)) and len(t) == 2 and t[1]]


def _row_h(row: dict) -> int:
    return TOP_H + _build_h(row) + (TALENTS_H if _talents(row) else 0) + CELLS_H


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

    Сверху — только исход и лобби; в строке игрока наверху — кто и на ком играл и ±MMR, цифры матча (K/D/A, IMP,
    экономика, урон) — подписанными ячейками внизу строки; счёт, золото, длительность, дата и ID — итогом под игроками.
    icons: {hero_id: PNG-байты}; avatars: {url: байты}; item_icons: {item_id: PNG-байты};
    отсутствующие рисуются заглушками.
    """
    icons, avatars, item_icons = icons or {}, avatars or {}, item_icons or {}
    rows = event.get("rows") or []
    label, color = _outcome(rows) if rows else ("МАТЧ", ACCENT)
    summary = _summary_cells(event, tz)
    height = (PAD + BANNER_H + 14 + sum(_row_h(r) + ROW_GAP for r in rows) + (SUMMARY_H + ROW_GAP if summary else 0)
              + FOOT_H + PAD)
    canvas = cards.Canvas(height, accent=color)
    img, draw = canvas.img, canvas.draw
    y = _draw_banner(img, draw, PAD, event, label, color) + 14

    mvp = _mvp_name(rows)
    for row in rows:
        _draw_row(img, draw, y, row, icons, avatars, mvp, item_icons)
        y += _row_h(row) + ROW_GAP

    if summary:
        _draw_summary(img, draw, y, summary, event)
        y += SUMMARY_H + ROW_GAP

    shared = event.get("shared")
    if shared and shared.get("games"):
        _draw_shared(img, draw, y, shared)
        y += FOOT_H
    return canvas.png(y)


def _draw_banner(img, draw, y: int, event: dict, label: str, color: str) -> int:
    """Шапка-плашка: исход крупно цветом (это главное в оповещении), справа — средний ранг лобби. Счёт, золото, дата и ID — в итоге под игроками: верх картинки не пестрит цифрами."""
    box = (PAD, y, WIDTH - PAD, y + BANNER_H)
    cards.gradient_panel(img, box, cards.mix(PANEL, color, 0.34), cards.mix(PANEL, color, 0.04), radius=20,
                         outline=cards.mix(PANEL, color, 0.42))
    cards.stripe(img, PAD, y + 20, y + BANNER_H - 20, color)
    right = WIDTH - PAD - 28
    rank = event.get("average_rank")
    side_w = 300 if rank else 0
    room = WIDTH - 2 * PAD - 60 - side_w
    draw_text(draw, (PAD + 32, y + 48), label, 56, cards.mix(color, "#ffffff", 0.12), bold=True, anchor="lm",
              max_w=room, shrink=36)
    sub = "Матч завершён"  # длительность, дата и ID — в итоге внизу
    draw_text(draw, (PAD + 34, y + 90), sub, 21, cards.mix(MUTED, "#ffffff", 0.25), anchor="lm", max_w=room)
    if rank:
        mid = y + BANNER_H / 2
        cards.paste(img, cards.rank_badge(rank, 64), right - 64, mid - 32)
        draw_text(draw, (right - 78, mid - 13), "ЛОББИ", 18, cards.mix(MUTED, "#ffffff", 0.2), bold=True, anchor="rm")
        draw_text(draw, (right - 78, mid + 15), rank_label(rank), 24, FG, bold=True, anchor="rm", max_w=side_w - 90,
                  shrink=18)
    return y + BANNER_H


def _summary_cells(event: dict, tz: str) -> list:
    """Итог матча ячейками (подпись, значение[, цвет]): счёт, перевес по золоту, длительность, начало."""
    cells = []
    score = match_score(event)
    if score:
        label = "Radiant : Dire" if score["mixed"] else "Счёт"
        cells.append((label, f"{score['left']} : {score['right']}"))
        if score["lead"] is not None and not score["mixed"]:
            cells.append(("Золото", gold_lead(score["lead"]), cards.delta_color(score["lead"])))
    if event.get("duration"):
        cells.append(("Длительность", clock(event["duration"])))
    if event.get("start_time"):
        cells.append(("Начало", fmt_local(event["start_time"], tz, "%d.%m %H:%M")))
    return cells


def _draw_summary(img, draw, y: int, cells: list, event: dict) -> None:
    cards.panel(img, (PAD, y, WIDTH - PAD, y + SUMMARY_H), cards.PANEL_HI, radius=16)
    mid = y + SUMMARY_H / 2
    match_id = f"матч {event.get('match_id')}" if event.get("match_id") else ""
    id_w = cards.text_width(match_id, 18) + 24 if match_id else 0
    cell_w = min(230, (RIGHT - CELLS_X - id_w) / max(len(cells), 1))
    cards.stat_cells(draw, CELLS_X, mid, cells, cell_w, value_size=26)
    if match_id:
        draw_text(draw, (RIGHT, mid), match_id, 18, cards.mix(MUTED, "#ffffff", 0.1), anchor="rm")


def _draw_row(
    img, draw, y: int, row: dict, icons: dict, avatars: dict, mvp: Optional[str], item_icons: Optional[dict] = None,
) -> None:
    won = bool(row.get("won"))
    accent = WIN if won else LOSS
    fill = cards.mix(PANEL, accent, 0.05)
    row_h = _row_h(row)
    cards.gradient_panel(img, (PAD, y, WIDTH - PAD, y + row_h), cards.mix(PANEL, accent, 0.16), fill, radius=16,
                         outline=cards.mix(fill, "#ffffff", 0.07))
    cards.stripe(img, PAD, y + 16, y + TOP_H - 12, accent)
    mid = y + TOP_H / 2

    name = clean(row.get("name")) or "Игрок"
    cards.paste(img, cards.avatar(avatars.get(row.get("avatar")), name, AVATAR), PAD + 22, mid - AVATAR / 2)
    cards.paste(img, cards.hero_icon(icons.get(row.get("hero_id")), row.get("hero_id")), PAD + 22 + AVATAR + 14,
                mid - ICON_H / 2)

    mmr_left = _draw_mmr(img, draw, mid, row, fill)
    name_room = mmr_left - 28 - NAME_X  # ник и строка героя не заходят на ±MMR справа

    tags = []
    if name == mvp:
        tags.append(("MVP", GOLD))
    if (row.get("leaver_status") or 0) >= 2:
        tags.append(("вышел", LOSS))
    tags_w = sum(cards.text_width(t, 18, True) + 20 + 8 for t, _ in tags)
    name_max = max(name_room - tags_w, 120)
    size = cards.fit_size(name, 28, True, name_max, 22)
    draw_text(draw, (NAME_X, mid - 15), name, size, FG, bold=True, anchor="lm", max_w=name_max)
    tag_x = NAME_X + min(cards.text_width(name, size, True), name_max) + 12
    for text, tag_color in tags:
        tag_x += cards.pill(img, draw, tag_x, mid - 15, text, BG, tag_color, size=18, pad=10) + 8
    hero = hero_name(row.get("hero_id")) + (f"  ·  P{row['position']}" if row.get("position") else "")
    if lane_text(row):
        hero += f"  ·  {lane_text(row)}"
    draw_text(draw, (NAME_X, mid + 17), hero, 20, MUTED, anchor="lm", max_w=name_room, shrink=17)

    sep = y + TOP_H - 2
    img.paste(cards.mix(fill, "#ffffff", 0.07), (CELLS_X, sep, RIGHT, sep + 1))
    if _has_build(row):
        _draw_build(img, draw, y + TOP_H + 8 + ITEM_H / 2, row, item_icons or {})
    talents_h = TALENTS_H if _talents(row) else 0
    if talents_h:
        _draw_talents(img, draw, y + TOP_H + _build_h(row) + 4, row, fill)
    _draw_cells(draw, y + TOP_H + _build_h(row) + talents_h + CELLS_H / 2 - 2, row)


def _draw_talents(img, draw, top: float, row: dict, fill: str) -> None:
    """Выбранные таланты сеткой 2×2 (10 и 15 — слева, 20 и 25 — справа): уровень золотой таблеткой и название."""
    label_color = cards.mix(MUTED, PANEL, 0.2)
    draw_text(draw, (CELLS_X, top + 16), "ТАЛАНТЫ", 16, label_color, bold=True, anchor="lm")
    left = CELLS_X + KDA_CELL_W
    col = (RIGHT - left) / 2
    for i, (level, name) in enumerate(_talents(row)[:4]):
        x, cy = left + (i // 2) * col, top + 16 + (i % 2) * 32
        w = cards.chip(img, draw, x, cy, str(level), GOLD, size=15, pad=8, base=fill)
        lx = x + w + 10
        draw_text(draw, (lx, cy), clean(name), 18, cards.mix(FG, MUTED, 0.15), anchor="lm", max_w=x + col - 18 - lx,
                  shrink=14, track=False)


def _draw_mmr(img, draw, mid: float, row: dict, fill: str) -> float:
    """Справа в верхней части строки: «±MMR → ≈MMR», под ним ранг игрока и серия. Возвращает левый край блока."""
    delta = _delta(row)
    mmr = row.get("current_mmr")
    streak = row.get("streak_len") or 0
    rank = row.get("rank_tier")
    second = rank or streak >= 3
    top = mid - 14 if second else mid
    x = RIGHT
    if mmr is not None:
        x -= cards.value_text(draw, (x, top), f"≈{mmr}", 34, FG) + 12
        draw_text(draw, (x, top), "→", 22, cards.mix(MUTED, PANEL, 0.3), anchor="rm")
        x -= cards.text_width("→", 22) + 12
    draw_text(draw, (x, top), signed(delta), 34, cards.delta_color(delta), bold=True, anchor="rm")
    left = x - cards.text_width(signed(delta), 34, True)
    if not second:
        return left
    low, x = mid + 22, RIGHT
    if rank:
        badge = 28
        cards.paste(img, cards.rank_badge(rank, badge), x - badge, low - badge / 2)
        text = rank_label(rank)
        draw_text(draw, (x - badge - 8, low), text, 18, cards.mix(FG, MUTED, 0.25), anchor="rm")
        x -= badge + 8 + cards.text_width(text, 18) + 14
    if streak >= 3:
        is_win = row.get("streak_type") == "W"
        text = f"▲ {streak} подряд" if is_win else f"▼ {streak} подряд"
        x -= cards.chip(img, draw, x, low, text, WIN if is_win else LOSS, size=16, pad=10, align="right", base=fill)
    return min(left, x)


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _strip_cells(row: dict) -> list:
    """Экономика и урон игрока ячейками с подписями; чего нет в данных — той ячейки нет.

    Кор — нетворс, крипы (добито/не отдано), урон, здания; саппорт (P4/P5) — то, чем он полезен: варды, стаки, лечение,
    и лишь затем урон и нетворс. Не больше четырёх: вместе с K/D/A, IMP и GPM ряд занимает ширину строки.
    """
    def k(key: str, fmt=_k) -> Optional[str]:
        return fmt(row[key]) if _number(row.get(key)) and row[key] else None

    hits = row.get("last_hits")
    net_worth, damage = ("Нетворс", k("net_worth")), ("Урон", k("hero_damage", _thousands))
    if is_support(row):
        cells = [
            ("Варды", str(row["wards"]) if _number(row.get("wards")) else None),
            ("Стаки", str(row["stacks"]) if _number(row.get("stacks")) else None),
            ("Лечение", k("hero_healing")), damage, net_worth,
        ]
        return [cell for cell in cells if cell[1]][:4]
    return [net_worth, ("Крипы", f"{hits}/{row.get('denies') or 0}" if _number(hits) else None), damage,
            ("Здания", k("tower_damage"))]


def _row_cells(row: dict) -> list:
    """Все ячейки ряда под строкой: IMP и GPM, затем экономика и урон (K/D/A рисуется первой отдельно)."""
    cells = []
    imp = row.get("imp")
    if _number(imp):
        cells.append(("IMP", signed(imp), cards.delta_color(imp)))
    if _number(row.get("gpm")) and row["gpm"]:
        cells.append(("GPM", str(round(row["gpm"]))))
    return cells + [cell for cell in _strip_cells(row) if cell[1]]


KDA_CELL_W = 190  # ширина ячейки K/D/A (и подписи «ТАЛАНТЫ» над талантами)


def _draw_cells(draw, mid: float, row: dict) -> None:
    """Ряд ячеек «подпись над значением»: K/D/A (смерти красным), IMP, GPM, экономика и урон."""
    label_color = cards.mix(MUTED, PANEL, 0.2)
    draw_text(draw, (CELLS_X, mid - 14), "K / D / A", 16, label_color, bold=True, anchor="lm")
    cards.kda(draw, CELLS_X, mid + 13, row.get("kills"), row.get("deaths"), row.get("assists"), 24, align="left")
    cells = _row_cells(row)
    if cells:
        x = CELLS_X + KDA_CELL_W
        cards.stat_cells(draw, x, mid, cells, min(CELL_MAX_W, (RIGHT - x) / len(cells)), value_size=22)


def _draw_build(img, draw, mid: float, row: dict, item_icons: dict) -> None:
    """Билд: 6 слотов, нейтралка, шард и скипетр; под иконками — время покупки."""
    x = CELLS_X
    times = _times(row)
    for i, item_id in enumerate(row.get("items") or []):
        cards.paste(img, _item_icon(item_icons.get(item_id)), x, mid - ITEM_H / 2)
        if i < len(times) and times[i]:
            draw_text(draw, (x + ITEM_W / 2, mid + ITEM_H / 2 + 12), times[i], 17, TIME_COLOR, anchor="mm", track=False)
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
                draw_text(draw, (x + icon_w / 2, mid + ITEM_H / 2 + 12), when, 17, TIME_COLOR, anchor="mm", track=False)
            x += max(icon_w, cards.text_width(when, 17) if when else 0) + 10


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
    """Подпись к картинке (она же текст пуша): исход и длительность, затем ±MMR игроков — остальное на картинке."""
    rows = event.get("rows") or []
    wins = sum(1 for r in rows if r.get("won"))
    result = "Победа" if rows and wins == len(rows) else "Поражение" if rows and wins == 0 else "Разные стороны"
    icon = "🏆" if rows and wins == len(rows) else "💀" if rows and wins == 0 else "⚔️"
    duration = f" · {event['duration'] // 60} мин" if event.get("duration") else ""
    head = f"{icon} <b>{result}</b>{duration}"
    parts = [f"{html.escape(clean(r.get('name')) or 'Игрок')} {signed(_delta(r))}" for r in rows]
    room = CAPTION_LIMIT - len(head) - 2
    line = " · ".join(parts)
    while parts and len(line) > room:  # много игроков с длинными никами — лишних не показываем
        parts.pop()
        line = " · ".join(parts) + " …"
    return head + ("\n" + line if parts else "")
