"""Картинка матча (PNG в памяти): шапка с исходом и таблица команд — иконка героя, ник, билд, K/D/A, экономика.

Шапка — табло: слева номер и время матча, по центру счёт по убийствам цветом сторон, справа исход.
под счётом — золото команд и перевес. В строке игрока под нетворсом — полоска доли от самого богатого в матче,
лучшие в матче GPM и урон — жирным, в последней колонке — дерево талантов (IMP в таблице нет).
Рисуем на Pillow (ставится вместе с matplotlib), шрифты — из cards.py.
Чистая функция: иконки приходят готовыми байтами (см. hero_icons.py), сети здесь нет.
Палитра — тёмная, как у графиков (charts.py). Ширина больше карточек (1640 против 1280): в строке рядом
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
from mmrbot.talents import tree_rows
from mmrbot.upgrade_icons import paste_upgrade

MATCH_WIDTH = 1640
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
TIME_COLOR = cards.TIME_COLOR
TAGS_X = 800
ITEMS_END = 878  # правее — K/D/A
UNTIMED_HEAD = "БИЛД · времена после разбора матча"  # иконки шарда и скипетра — после предметов и нейтралки
UPGRADE_SIZE = 26
# центры колонок (x) и их заголовки
COLUMNS = [("kda", 962, "K / D / A"), ("nw", 1078, "НЕТВОРС"), ("lh", 1178, "КРИПЫ"), ("gpm", 1283, "GPM / XPM"),
           ("dmg", 1393, "УРОН"), ("talents", 1520, "ТАЛАНТЫ")]
RANK_BADGE = 34  # значок ранга игрока на верхнем правом углу иконки героя
TREE_W, TREE_H = 72, 52  # дерево талантов графикой в последней колонке


def _sorted_team(players: list[dict]) -> list[dict]:
    return sorted(players, key=lambda p: p.get("position") or 9)


def _ids(values) -> list:
    """Только настоящие id предметов: мусор и пустые слоты отбрасываем."""
    return [i for i in values or [] if isinstance(i, int) and not isinstance(i, bool) and i]


def _has_build(players: list[dict]) -> bool:
    return any(p.get("items") or p.get("neutral_item") or _ids(p.get("bear_items")) for p in players)


def _has_times(players: list[dict]) -> bool:
    """Известно ли время покупки хоть одного предмета в матче (иначе под иконками пусто — объясняем почему)."""
    return any(_num(t) for p in players for t in (p.get("item_times") or []) + (p.get("bear_item_times") or []))


def _has_bear(p: dict) -> bool:
    return bool(_ids(p.get("bear_items")))


def _talents(p: dict) -> list:
    """Дерево талантов игрока (talents.tree_rows); пусто — талантов не знаем."""
    return tree_rows(p.get("talents"))


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
    timed = _has_times(players)
    height = _height([team for _, team in teams]) if teams else HEAD_H + PAD

    radiant_win = match.get("radiant_win")
    if me is not None and radiant_win is not None:
        won = bool(me.get("is_radiant")) == bool(radiant_win)
        label, color = ("ПОБЕДА", WIN) if won else ("ПОРАЖЕНИЕ", LOSS)
    elif radiant_win is not None:
        label, color = ("ПОБЕДА RADIANT", RADIANT) if radiant_win else ("ПОБЕДА DIRE", DIRE)
    else:
        label, color = None, None

    canvas = cards.Canvas(height, MATCH_WIDTH, accent=color or ACCENT)
    img, draw = canvas.img, canvas.draw

    # --- шапка: слева матч и время, по центру счёт по убийствам, справа исход ---
    draw_text(draw, (PAD, 26), f"Матч {match.get('match_id')}", 40, FG, bold=True)
    when = fmt_local(match.get("start_time") or 0, tz, "%d.%m.%Y %H:%M")
    sub = when + (f"  ·  {clock(match['duration'])}" if match.get("duration") else "")
    draw_text(draw, (PAD, 82), sub, 22, MUTED)
    if label:
        cards.pill(img, draw, MATCH_WIDTH - PAD, 62, label, BG, color, size=28, align="right", pad=24)
    if len(teams) == 2:
        _draw_score(draw, MATCH_WIDTH / 2, 62, *(sum(p.get("kills") or 0 for p in team) for _, team in teams),
                    gold=_team_gold([team for _, team in teams]))
    top_nw = max((p.get("net_worth") or 0 for p in players), default=0)
    best = {key: _best(players, key) for key in ("hero_damage", "gpm")}

    # --- команды ---
    y = HEAD_H
    for side, team in teams:
        team_color = RADIANT if side else DIRE
        cards.stripe(img, PAD, y + 14, y + 42, team_color)
        title = "RADIANT" if side else "DIRE"
        draw_text(draw, (PAD + 20, y + 28), title, 26, team_color, bold=True, anchor="lm")
        tx = PAD + 20 + cards.text_width(title, 26, True) + 14
        if radiant_win is not None and bool(radiant_win) == side:
            cards.chip(img, draw, tx, y + 28, "победа", team_color, size=18, pad=12)
        if build:
            draw_text(draw, (ITEMS_X, y + 30), "БИЛД · ВРЕМЯ ПОКУПКИ" if timed else UNTIMED_HEAD, 18, MUTED,
                      anchor="lm", max_w=ITEMS_END - ITEMS_X)
        for _key, cx, head in COLUMNS:
            draw_text(draw, (cx, y + 30), head, 18, MUTED, anchor="mm")
        y += TEAM_HEAD_H
        for p in team:
            _draw_row(img, draw, y, p, tracked, icons, item_icons, build, top_nw, best)
            y += _row_h(p) + ROW_GAP
        y += TEAM_GAP

    return canvas.png(fmt=fmt)


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _team_gold(teams: list[list[dict]]) -> Optional[tuple[float, float]]:
    """Суммарный нетворс сторон (radiant, dire); None — если он известен не у всех: неполная сумма обманывает."""
    if any(not _num(p.get("net_worth")) or p["net_worth"] <= 0 for team in teams for p in team):
        return None
    radiant, dire = (sum(p["net_worth"] for p in team) for team in teams)
    return radiant, dire


def _best(players: list[dict], key: str) -> Optional[float]:
    """Лучшее значение показателя в матче; None — сравнивать нечего (меньше двух игроков или у всех поровну)."""
    values = [p[key] for p in players if _num(p.get(key))]
    return max(values) if len(values) >= 2 and max(values) > min(values) else None


def _draw_score(draw, cx: float, cy: float, radiant: int, dire: int,
                gold: Optional[tuple[float, float]] = None) -> None:
    """Счёт по убийствам, как на табло: числа цветом сторон, по бокам подписи команд; под подписями — золото
    команд (у богатой — золотом и с перевесом): кто вёл по экономике, видно без сложения десяти чисел."""
    gap = 26
    if gold:
        cy -= 8  # табло чуть выше: строка под ним стала содержательной
        lead = abs(gold[0] - gold[1])
        for side, anchor, mine, other in ((-1, "rm", gold[0], gold[1]), (1, "lm", gold[1], gold[0])):
            text = f"{_k(mine)} золота" + (f"  ·  +{_k(lead)}" if mine > other else "")
            edge = cx + side * (gap + cards.text_width(str(radiant if side < 0 else dire), 60, True) + 22)
            draw_text(draw, (edge, cy + 46), text, 18, GOLD if mine > other else cards.mix(MUTED, BG, 0.2),
                      bold=mine > other, anchor=anchor, max_w=330, track=False)
    draw_text(draw, (cx, cy - 2), ":", 44, cards.mix(MUTED, BG, 0.3), bold=True, anchor="mm")
    draw_text(draw, (cx - gap, cy), str(radiant), 60, RADIANT, bold=True, anchor="rm")
    draw_text(draw, (cx + gap, cy), str(dire), 60, DIRE, bold=True, anchor="lm")
    left = cx - gap - cards.text_width(str(radiant), 60, True) - 22
    right = cx + gap + cards.text_width(str(dire), 60, True) + 22
    draw_text(draw, (left, cy + 2), "RADIANT", 18, cards.mix(RADIANT, BG, 0.2), bold=True, anchor="rm")
    draw_text(draw, (right, cy + 2), "DIRE", 18, cards.mix(DIRE, BG, 0.2), bold=True, anchor="lm")
    draw_text(draw, (cx, cy + 46), "УБИЙСТВА", 18, cards.mix(MUTED, BG, 0.25), anchor="mm")


def _draw_items(img, draw, top: float, items, times, neutral, item_icons: dict) -> None:
    """Одна линия билда: предметы по слотам, под каждым время покупки, затем нейтралка."""
    x = ITEMS_X
    times = times if isinstance(times, list) else []
    for i, item_id in enumerate(_ids(items)):
        cards.paste(img, _item_icon(item_icons.get(item_id), SLOT_W, SLOT_H, 5), x, top)
        when = clock(times[i]) if i < len(times) else ""
        if when:
            draw_text(draw, (x + SLOT_W / 2, top + SLOT_H + 12), when, 15, TIME_COLOR, anchor="mm", track=False)
        x += SLOT_W + SLOT_GAP
    if isinstance(neutral, int) and not isinstance(neutral, bool) and neutral:
        draw.line((x + 2, top + 3, x + 2, top + SLOT_H - 3), fill=cards.mix(PANEL, "#ffffff", 0.22), width=2)  # нейтралка — не слот билда
        cards.paste(img, _item_icon(item_icons.get(neutral), SLOT_W, SLOT_H, 5), x + 8, top)


def _draw_build(img, draw, y: int, p: dict, item_icons: dict) -> None:
    """Билд игрока между ником и K/D/A; Лон Друид — две линии (герой и медведь) с подписями."""
    mid = y + _base_h(p) / 2
    bear = _has_bear(p)
    top = y + 12 if bear else mid - SLOT_H / 2 - 4
    _draw_items(img, draw, top, p.get("items"), p.get("item_times"), p.get("neutral_item"), item_icons)
    if bear:
        bear_top = top + SLOT_H + 28
        _draw_items(img, draw, bear_top, p.get("bear_items"), p.get("bear_item_times"), p.get("bear_neutral"),
                    item_icons)
        draw_text(draw, (ITEMS_X - 10, top + SLOT_H / 2), "Герой", 14, MUTED, anchor="rm")
        draw_text(draw, (ITEMS_X - 10, bear_top + SLOT_H / 2), "Медведь", 14, MUTED, anchor="rm")
    for cy, key, tag, color in ((mid - 15, "shard", "Ш", ACCENT), (mid + 15, "scepter", "С", GOLD)):
        if not p.get(key):
            continue
        icon_w = paste_upgrade(img, key, TAGS_X, cy, UPGRADE_SIZE)
        if icon_w is None:
            icon_w = cards.pill(img, draw, TAGS_X, cy, tag, BG, color, size=13, pad=5)
        when = clock(p.get(f"{key}_time"))
        if when:  # время покупки шарда/скипетра — справа от значка, как у предметов
            draw_text(draw, (TAGS_X + icon_w + 6, cy), when, 15, TIME_COLOR, anchor="lm", track=False)


def _base_h(p: dict) -> int:
    """Высота строки без талантов: по ней центруется всё, кроме строки талантов."""
    return ROW_BEAR_H if _has_bear(p) else ROW_H


def _draw_row(img, draw, y: int, p: dict, tracked: dict, icons: dict, item_icons: Optional[dict] = None,
              build: bool = False, top_nw: float = 0, best: Optional[dict] = None) -> None:
    best = best or {}
    mine = p.get("account_id") is not None and p.get("account_id") in tracked
    row_h = _row_h(p)
    box = (PAD, y, MATCH_WIDTH - PAD, y + row_h)
    if mine:  # свой игрок: золотой отсвет слева, полоса и звезда у ника
        cards.gradient_panel(img, box, cards.mix(TRACKED_PANEL, TRACKED_MARK, 0.2), TRACKED_PANEL, radius=12,
                             outline=cards.mix(TRACKED_PANEL, TRACKED_MARK, 0.28))
        cards.stripe(img, PAD, y + 12, y + row_h - 12, TRACKED_MARK)
    else:
        cards.panel(img, box, PANEL, radius=12)
    mid = y + _base_h(p) / 2

    cards.paste(img, cards.hero_icon(icons.get(p.get("hero_id")), p.get("hero_id")), PAD + 24, mid - ICON_H / 2)
    cards.level_badge(img, draw, PAD + 24 + 6, mid + ICON_H / 2 - 4, p.get("level"))
    cards.plus_badge(img, draw, PAD + 24 + 4, mid - ICON_H / 2 + 4, p.get("plus_xp"))
    if p.get("rank_tier"):  # ранг игрока (тир) значком на верхнем правом углу иконки героя
        cards.paste(img, cards.rank_badge(p["rank_tier"], RANK_BADGE), PAD + 24 + ICON_W - RANK_BADGE + 8,
                    mid - ICON_H / 2 - 8)
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

    net_worth = p.get("net_worth")
    if isinstance(net_worth, (int, float)) and not isinstance(net_worth, bool) and net_worth > 0 and top_nw > 0:
        # полоска — доля от самого богатого в матче: расклад по золоту виден без чтения десяти чисел
        draw_text(draw, (cols["nw"], mid - 8), _k(net_worth), 26, GOLD, bold=True, anchor="mm")
        cards.bar(img, (cols["nw"] - 48, mid + 16, cols["nw"] + 48, mid + 22), net_worth / top_nw,
                  cards.mix(GOLD, PANEL, 0.25), track=cards.mix(PANEL, "#ffffff", 0.08))
    else:
        draw_text(draw, (cols["nw"], mid), _k(net_worth), 26, GOLD, bold=True, anchor="mm")
    hits = p.get("last_hits")
    if _num(hits):  # крипы: добито / не отдано
        draw_text(draw, (cols["lh"], mid), f"{hits:.0f}/{p.get('denies') or 0:.0f}", 22, FG, anchor="mm", track=False)
    else:
        draw_text(draw, (cols["lh"], mid), "—", 22, MUTED, anchor="mm")
    gpm, xpm = p.get("gpm"), p.get("xpm")
    econ = f"{gpm:.0f} / {xpm:.0f}" if gpm is not None and xpm is not None else (f"{gpm:.0f}" if gpm is not None else "—")
    # лучший в матче GPM и урон — жирным и ярче, остальные чуть приглушены: лидер столбца находится взглядом
    calm = cards.mix(FG, MUTED, 0.3) if best.get("gpm") is not None else FG
    top = gpm is not None and gpm == best.get("gpm")
    draw_text(draw, (cols["gpm"], mid), econ, 24, FG if top else calm, bold=top, anchor="mm")
    tower = p.get("tower_damage")
    calm = cards.mix(FG, MUTED, 0.3) if best.get("hero_damage") is not None else FG
    top = p.get("hero_damage") is not None and p.get("hero_damage") == best.get("hero_damage")
    draw_text(draw, (cols["dmg"], mid - (11 if tower else 0)), _k(p.get("hero_damage")), 24, FG if top else calm,
              bold=top, anchor="mm")
    if tower:  # урон по зданиям — вторым рядом: в колонке нет места для двух чисел в строку
        draw_text(draw, (cols["dmg"], mid + 15), f"{_k(tower)} здания", 17, MUTED, anchor="mm")
    if _talents(p):  # дерево талантов — в последней колонке, где раньше стоял IMP
        cx = cols["talents"]
        cards.talent_tree(img, (cx - TREE_W / 2, mid - TREE_H / 2, cx + TREE_W / 2, mid + TREE_H / 2), _talents(p),
                          TRACKED_PANEL if mine else PANEL)
