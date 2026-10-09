"""Графики (PNG в памяти). matplotlib подключается лениво — тесты и старт бота остаются лёгкими.

Картинка рассчитана на Telegram: 1280 px по ширине (фото шире Telegram всё равно ужимает) и крупный
текст — в ленте на телефоне она показывается втрое мельче. Рисуем без pyplot (Figure + Agg-канва):
так нет общего состояния, и графики разных чатов можно строить в параллельных потоках.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from mmrbot.timezones import zone

# Категориальная палитра для тёмной поверхности: восемь оттенков в фиксированном порядке. Порядок —
# часть защиты от неразличимости при дальтонизме (соседние слоты проверены), поэтому не переставлять.
PALETTE = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
BG, PANEL, FG, MUTED, GRID = "#0a0f16", "#141d29", "#eef2f8", "#8f9dac", "#243140"
CARD_EDGE = "#202c3a"  # тёмная тема Telegram
WIN, LOSS = "#3ddc84", "#ff5c5c"  # исход игры (статус) — не используются как цвет игрока
MAX_POINTS = 300  # длиннее — прореживаем (история в тысячи игр рисовалась бы долго и выглядела кашей)
DOTS_LIMIT = 60  # отдельные точки-игры рисуем, пока их на графике не больше (иначе каша)
NAME_LIMIT = 18  # длиннее — обрезаем в таблице
FONTS = ("Inter", "Segoe UI", "Roboto", "Noto Sans", "DejaVu Sans")
WIDTH_PX = 1280


def _games_word(n: int) -> str:
    n10, n100 = n % 10, n % 100
    word = "игра" if n10 == 1 and n100 != 11 else "игры" if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else "игр"
    return f"{n} {word}"


def series_stats(points: list[tuple[int, int]]) -> tuple[int, int, int]:
    """(игр, побед, итог ±MMR) по серии накопленных значений."""
    wins, prev = 0, 0
    for _, value in points:
        wins += 1 if value > prev else 0
        prev = value
    return len(points), wins, points[-1][1]


def _spread_labels(ys: list[float], min_gap: float) -> list[float]:
    """Раздвигает подписи итогов, чтобы они не наезжали друг на друга (порядок по y сохраняется)."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    placed = list(ys)
    for prev, cur in zip(order, order[1:]):
        if placed[cur] - placed[prev] < min_gap:
            placed[cur] = placed[prev] + min_gap
    shift = (sum(placed) - sum(ys)) / len(ys)  # возвращаем облако подписей к центру исходных значений
    return [y - shift for y in placed]


def _thin(points: list[tuple[int, int]], limit: int = MAX_POINTS) -> list[tuple[int, int]]:
    """Равномерно прореживает серию, сохраняя первую и последнюю точки."""
    if len(points) <= limit:
        return points
    buckets = limit // 3
    stride = len(points) / buckets
    picked: list[tuple[int, int]] = []
    for i in range(buckets):  # в каждой корзине оставляем минимум, максимум и последнюю точку — пики не теряются
        chunk = points[int(i * stride):int((i + 1) * stride)] or [points[-1]]
        keep = {min(chunk, key=lambda p: p[1]), max(chunk, key=lambda p: p[1]), chunk[-1]}
        if i == 0:
            keep.add(chunk[0])  # начало серии сохраняем
        picked.extend(sorted(keep, key=lambda p: p[0]))
    if picked[-1] != points[-1]:
        picked.append(points[-1])
    return picked


def color_slots(names: list[str], order: Optional[list[str]] = None) -> dict[str, int]:
    """Номер цвета для каждого игрока: {имя: слот}.

    Цвет закреплён за игроком, а не за его местом: слот — позиция в `order` (состав чата в порядке
    добавления), поэтому при смене периода или лидера игроки не перекрашиваются. Имён вне `order`
    (или без него) — по алфавиту после остальных.
    """
    known = [name for name in (order or []) if name in names]
    rest = sorted(name for name in names if name not in known)
    base = list(order) if order else []
    slots: dict[str, int] = {}
    for name in known:
        slots[name] = base.index(name)
    for offset, name in enumerate(rest):
        slots[name] = len(base) + offset
    return slots


def _ink_on(color: str) -> str:
    """Цвет текста поверх заливки: тёмный или белый — у кого контраст с заливкой выше (WCAG)."""
    def luminance(hex_color: str) -> float:
        channels = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    fill = luminance(color)
    dark = (fill + 0.05) / (luminance(BG) + 0.05)
    light = 1.05 / (fill + 0.05)
    return BG if dark >= light else "#ffffff"


@lru_cache(maxsize=1)
def _font_family() -> tuple[str, ...]:
    """Первый установленный шрифт из FONTS (+ DejaVu как запасной для символов).

    Проверяем наличие сами: иначе matplotlib на каждый текст пишет в лог «Font family not found»
    (в Docker-образе нет ни Inter, ни Segoe UI).
    """
    import os

    from matplotlib import font_manager

    # Тот же Inter, что на карточках (cards.py): лежит в assets/fonts, от шрифтов системы график не зависит.
    fonts_dir = os.path.join(os.path.dirname(__file__), "assets", "fonts")
    for name in ("Inter-Medium.otf", "Inter-Bold.otf"):
        try:
            font_manager.fontManager.addfont(os.path.join(fonts_dir, name))
        except Exception:
            pass
    installed = {font.name for font in font_manager.fontManager.ttflist}
    first = next((name for name in FONTS if name in installed), "DejaVu Sans")
    return (first,) if first == "DejaVu Sans" else (first, "DejaVu Sans")


def _signed(value: int) -> str:
    return f"{value:+d}".replace("-", "−") if value else "0"


@lru_cache(maxsize=1)
def _epoch_offset() -> float:
    import matplotlib.dates as mdates
    return float(mdates.date2num(datetime(1970, 1, 1)))


def date_num(ts: float) -> float:
    """Unix-время → число matplotlib (дни от эпохи). То же, что date2num(datetime), но без объекта datetime на точку:
    aware-datetime date2num и так приводит к UTC, часовой пояс остаётся забота оси."""
    return ts / 86400.0 + _epoch_offset()


def warmup() -> None:
    """Прогрев matplotlib (импорт и кэш шрифтов) — вызывается фоном при старте, чтобы первый график был быстрым."""
    try:
        render_mmr_chart({"w": [(1, 25), (2, 0)]}, "w", "UTC")
    except Exception:
        pass


def render_mmr_chart(
    series: dict[str, list[tuple[int, int]]], title: str, tz_name: str,
    since_ts: int | None = None, until_ts: int | None = None, by_games: bool = False,
    order: Optional[list[str]] = None,
) -> bytes:
    """Динамика ±MMR по игрокам: {имя: [(unix-время, накопленное Δ)]} → PNG-байты.

    Карточка: шапка (заголовок, период, лидер) → график → таблица игроков (итог, игры, победы–поражения,
    полоска винрейта). По времени линия ступенчатая: MMR меняется в момент конца игры и держится до
    следующей, наклонная линия между сессиями рисовала бы рост, которого не было. По номеру игры —
    обычная ломаная. У одного игрока — заливка, точки-исходы, пик и просадка.

    order — состав чата в постоянном порядке: по нему за игроком закрепляется цвет.
    """
    import matplotlib.dates as mdates
    import numpy as np
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.colors import LinearSegmentedColormap, to_rgb
    from matplotlib.figure import Figure
    from matplotlib.patches import FancyBboxPatch, Rectangle
    from matplotlib.path import Path
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    tz = zone(tz_name)
    family = list(_font_family())

    def to_dt(ts: int) -> datetime:
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(tz)

    def to_x(ts: float) -> float:
        return ts if by_games else date_num(ts)

    if by_games:  # ось X — порядковый номер игры: серии разных игроков сравнимы «игра к игре»
        series = {name: [(i, v) for i, (_, v) in enumerate(pts, 1)] for name, pts in series.items()}
        since_ts = until_ts = None

    ordered = sorted(series.items(), key=lambda kv: kv[1][-1][1], reverse=True)
    n = len(ordered)
    solo = n == 1
    slots = color_slots([name for name, _ in ordered], order)

    def color_of(name: str) -> str:
        return PALETTE[slots[name] % len(PALETTE)]

    def dash_of(name: str):  # девятый игрок и дальше: те же цвета, но пунктиром — пара «цвет + штрих» уникальна
        return (0, (5, 2.5)) if slots[name] >= len(PALETTE) else "solid"

    # --- раскладка в дюймах (1 единица оверлея = 1 дюйм) ---
    W = 8.0
    dpi = WIDTH_PX / W
    margin = 0.3
    row_h, table_head = 0.4, 0.5
    table_h = table_head + row_h * n + 0.1
    plot_h = 4.2
    footer_h = 0.42
    head_h = 1.1
    gap = 0.2
    H = footer_h + table_h + gap + plot_h + head_h
    table_y0 = footer_h
    card_y0 = table_y0 + table_h + gap
    card_y1 = card_y0 + plot_h
    label_w = 0.95  # поле справа под значения-«таблетки»
    ax_box = (margin + 0.75, card_y0 + 0.55, W - margin - label_w, card_y1 - 0.3)  # x0, y0, x1, y1

    fig = Figure(figsize=(W, H), dpi=dpi)
    FigureCanvasAgg(fig)
    fig.patch.set_facecolor(BG)
    back = fig.add_axes([0, 0, 1, 1], zorder=0)
    back.set_xlim(0, W)
    back.set_ylim(0, H)
    back.axis("off")
    gradient = np.linspace(0, 1, 256).reshape(-1, 1)
    back.imshow(gradient, extent=(0, W, 0, H), aspect="auto", zorder=-10, origin="upper",
                cmap=LinearSegmentedColormap.from_list("bg", ["#121a27", BG]))

    def text(x, y, value, **kwargs):
        kwargs.setdefault("va", "center")
        return back.text(x, y, value, fontfamily=family, **kwargs)

    def card(x0, y0, x1, y1):
        back.add_patch(FancyBboxPatch(
            (x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=0.14", linewidth=1,
            edgecolor=CARD_EDGE, facecolor=PANEL, zorder=1,
        ))

    def swatch(x, y, color, size=0.15):
        back.add_patch(FancyBboxPatch((x, y - size / 2), size, size, zorder=3, edgecolor="none", facecolor=color,
                                      boxstyle=f"round,pad=0,rounding_size={size / 2}"))

    card(margin, card_y0, W - margin, card_y1)
    card(margin, table_y0, W - margin, table_y0 + table_h)

    ax = fig.add_axes(
        [ax_box[0] / W, ax_box[1] / H, (ax_box[2] - ax_box[0]) / W, (ax_box[3] - ax_box[1]) / H], zorder=2
    )
    ax.set_facecolor("none")

    all_values = [v for _, pts in ordered for _, v in pts] + [0]
    top, low = max(all_values), min(all_values)
    pad = max(25, (top - low) * 0.16)
    y_lo, y_hi = low - pad, top + pad
    ax.set_ylim(y_lo, y_hi)
    ax.axhspan(0, y_hi, color=WIN, alpha=0.035, zorder=0, linewidth=0)
    ax.axhspan(y_lo, 0, color=LOSS, alpha=0.035, zorder=0, linewidth=0)
    ax.axhline(0, color=FG, linewidth=1, alpha=0.4, zorder=1)

    total_points = sum(min(len(pts), MAX_POINTS) for _, pts in ordered)
    draw_style = "default" if by_games else "steps-post"
    ends: list[tuple] = []
    x_min = x_max = None
    for name, points in reversed(ordered):  # лидер рисуется последним — поверх остальных
        color = color_of(name)
        games, wins, total = series_stats(points)
        shown = _thin(points)
        start_ts = 0 if by_games else since_ts if since_ts is not None and since_ts < shown[0][0] else shown[0][0]
        xs = [to_x(start_ts)] + [to_x(ts) for ts, _ in shown]  # линия стартует с нуля в начале периода
        ys = [0] + [value for _, value in shown]
        x_min = xs[0] if x_min is None else min(x_min, xs[0])
        x_max = xs[-1] if x_max is None else max(x_max, xs[-1])
        ax.plot(xs, ys, color=color, linewidth=1.8 if solo else 1.6, zorder=3, drawstyle=draw_style,
                linestyle=dash_of(name), solid_joinstyle="round", solid_capstyle="round")
        if solo and xs[-1] > xs[0]:  # градиентная заливка: плотнее у линии, к нулю растворяется
            poly = ax.fill_between(xs, ys, 0, alpha=0, linewidth=0, step=None if by_games else "post")
            span = max(abs(y_lo), abs(y_hi))
            col = np.linspace(y_hi, y_lo, 256).reshape(-1, 1)
            rgba = np.zeros((256, 1, 4))
            rgba[..., :3] = to_rgb(color)
            rgba[..., 3] = np.clip(np.abs(col) / span, 0, 1) * 0.38
            image = ax.imshow(rgba, extent=(xs[0], xs[-1], y_lo, y_hi), aspect="auto", zorder=2, origin="upper")
            image.set_clip_path(Path.make_compound_path(*poly.get_paths()), ax.transData)
        if total_points <= DOTS_LIMIT:  # кольцо цвета поверхности отделяет точку от линий под ней
            dots = [(x, y, y > before) for x, y, before in zip(xs[1:], ys[1:], ys[:-1])]
            ax.scatter([d[0] for d in dots], [d[1] for d in dots], s=46 if solo else 30, zorder=5,
                       edgecolors=PANEL, linewidths=1.6,
                       c=[WIN if d[2] else LOSS for d in dots] if solo else color)  # соло: цвет — исход игры
        ax.scatter([xs[-1]], [ys[-1]], s=52, zorder=6, c=color, edgecolors=PANEL, linewidths=1.8)  # конец серии
        ends.append((xs[-1], ys[-1], total, color))
        if solo and games >= 3:  # у одного игрока подписываем пик и просадку
            full_ys = [value for _, value in points]
            hi, lo = max(full_ys), min(full_ys)
            hi_ts, lo_ts = points[full_ys.index(hi)][0], points[full_ys.index(lo)][0]
            tag = {"fontsize": 9.5, "fontweight": "bold", "ha": "center", "zorder": 7, "color": FG,
                   "textcoords": "offset points", "fontfamily": family}
            if hi > 0:
                ax.annotate(f"пик {_signed(hi)}", (to_x(hi_ts), hi), xytext=(0, 11), **tag)
            if lo < 0:
                ax.annotate(f"просадка {_signed(lo)}", (to_x(lo_ts), lo), xytext=(0, -18), **tag)

    # --- ось X ---
    if by_games:
        ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=8))
        ax.set_xlabel("номер игры", color=MUTED, fontsize=10, labelpad=6, fontfamily=family)
        span = max(x_max - x_min, 1)
        ax.set_xlim(x_min - span * 0.02, x_max + span * 0.04)
    else:
        ax.xaxis_date(tz=tz)
        locator = mdates.AutoDateLocator(tz=tz, minticks=3, maxticks=7)
        ax.xaxis.set_major_locator(locator)
        fmt = mdates.ConciseDateFormatter(locator, tz=tz)
        fmt.formats = ["%Y", "%m.%Y", "%d.%m", "%H:%M", "%H:%M", "%H:%M"]
        fmt.zero_formats = ["", "%Y", "%d.%m", "%d.%m", "%H:%M", "%H:%M"]
        fmt.offset_formats = [""] * 6  # без подписи «2026-Oct» справа внизу
        ax.xaxis.set_major_formatter(fmt)
        if since_ts is not None and until_ts is not None:  # ось — выбранный период целиком
            ax.set_xlim(to_x(since_ts), to_x(until_ts + (until_ts - since_ts) // 40))
        else:
            span = max(x_max - x_min, 1e-3)
            ax.set_xlim(x_min - span * 0.02, x_max + span * 0.04)
        if until_ts is not None:  # после последней игры значение держится до «сейчас»
            for x_end, y_end, _, color in ends:
                if to_x(until_ts) - x_end > (to_x(until_ts) - to_x(since_ts or until_ts)) * 0.04:  # короткий хвост — мусор
                    ax.hlines(y_end, x_end, to_x(until_ts), color=color, linewidth=1.2, linestyles=":",
                              alpha=0.7, zorder=3)
    ax.set_ylim(y_lo, y_hi)

    # --- значения-«таблетки» справа от линий; сдвинутую подпись связываем с её линией выноской ---
    label_ys = _spread_labels([e[1] for e in ends], (y_hi - y_lo) * 0.085)
    for (_, y_end, total, color), y_label in zip(ends, label_ys):
        if abs(y_label - y_end) > (y_hi - y_lo) * 0.01:
            ax.annotate("", (1.0, y_end), xycoords=("axes fraction", "data"), xytext=(1.012, y_label),
                        textcoords=("axes fraction", "data"), annotation_clip=False, zorder=7,
                        arrowprops={"arrowstyle": "-", "color": color, "linewidth": 1, "alpha": 0.8})
        ax.annotate(
            _signed(total), (1.0, y_label), xycoords=("axes fraction", "data"), xytext=(9, 0),
            textcoords="offset points", va="center", ha="left", color=_ink_on(color), fontsize=10.5,
            fontweight="bold", zorder=8, annotation_clip=False, fontfamily=family,
            bbox={"boxstyle": "round,pad=0.3,rounding_size=0.5", "facecolor": color, "edgecolor": "none"},
        )

    # Шаг делений — «круглый» и кратный типичному шагу MMR (25/50/100), а не 80/160.
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6, steps=[1, 2, 2.5, 5, 10], integer=True))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _signed(int(round(v)))))
    ax.tick_params(colors=MUTED, labelsize=10, length=0, pad=6, labelfontfamily=family)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.grid(axis="x", color=GRID, linewidth=0.8, alpha=0.5)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)

    # --- шапка: заголовок слева, главный итог справа ---
    text(margin + 0.1, H - 0.42, title, color=FG, fontsize=17, fontweight="bold", ha="left")
    if since_ts is not None and until_ts is not None:
        sub = f"{to_dt(since_ts):%d.%m.%Y} — {to_dt(until_ts):%d.%m.%Y}"
    else:
        sub = "по порядку игр" if by_games else "все игры"
    text(margin + 0.1, H - 0.78, sub, color=MUTED, fontsize=10.5, ha="left")
    lead_name, lead_pts = ordered[0]
    lead_total = series_stats(lead_pts)[2]
    text(W - margin - 0.1, H - 0.36, "ИТОГ" if solo else "ЛИДЕР", color=MUTED, fontsize=8.5, fontweight="bold",
         ha="right")
    lead_label = lead_name if len(lead_name) <= 14 else lead_name[:13] + "…"
    lead = text(W - margin - 0.1, H - 0.74, f"{lead_label}  {_signed(lead_total)}", color=FG, fontsize=14,
                fontweight="bold", ha="right")
    lead_box = lead.get_window_extent(fig.canvas.get_renderer())
    swatch(lead_box.x0 / dpi - 0.25, H - 0.74, color_of(lead_name))  # кто это — показывает цветная метка, не цвет текста

    # --- таблица игроков: она же легенда ---
    col_total, col_games, col_wr, bar = 3.95, 5.5, 6.2, (6.35, W - margin - 0.2)
    head_y = table_y0 + table_h - 0.28
    for x, label, ha in ((margin + 0.2, "ИГРОК", "left"), (col_total, "±MMR", "right"),
                         (col_games, "ИГРЫ · В–П", "right"), (col_wr, "ПОБЕДЫ", "right")):
        text(x, head_y, label, color=MUTED, fontsize=8.5, fontweight="bold", ha=ha)
    for i, (name, points) in enumerate(ordered):
        color = color_of(name)
        games, wins, total = series_stats(points)
        y = table_y0 + table_h - table_head - row_h * i - row_h / 2 + 0.04
        if i:
            back.plot([margin + 0.2, W - margin - 0.2], [y + row_h / 2] * 2, color=GRID, linewidth=0.8, zorder=2)
        swatch(margin + 0.2, y, color)
        shown_name = name if len(name) <= NAME_LIMIT else name[:NAME_LIMIT - 1] + "…"
        text(margin + 0.47, y, shown_name, color=FG, fontsize=11.5, fontweight="bold", ha="left", zorder=3)
        # Знак и стрелка дублируют цвет: итог читается и без различения красного с зелёным.
        arrow, tone = ("▲", WIN) if total > 0 else ("▼", LOSS) if total < 0 else ("", MUTED)
        value = text(col_total, y, _signed(total), color=FG, fontsize=12, fontweight="bold", ha="right", zorder=3)
        if arrow:
            value_box = value.get_window_extent(fig.canvas.get_renderer())
            text(value_box.x0 / dpi - 0.07, y, arrow, color=tone, fontsize=7.5, ha="right", zorder=3)
        text(col_games, y, f"{games} · {wins}–{games - wins}", color=FG, fontsize=10.5, ha="right", zorder=3)
        rate = wins / games
        text(col_wr, y, f"{rate * 100:.0f}%", color=FG, fontsize=10.5, ha="right", zorder=3)
        bx0, bx1 = bar
        back.add_patch(FancyBboxPatch((bx0, y - 0.05), bx1 - bx0, 0.1, boxstyle="round,pad=0,rounding_size=0.05",
                                      facecolor=GRID, edgecolor="none", zorder=3))
        if rate > 0:
            back.add_patch(FancyBboxPatch((bx0, y - 0.05), max(0.1, (bx1 - bx0) * rate), 0.1,
                                          boxstyle="round,pad=0,rounding_size=0.05", facecolor=color,
                                          edgecolor="none", zorder=4))
        back.add_patch(Rectangle((bx0 + (bx1 - bx0) / 2 - 0.01, y - 0.09), 0.02, 0.18, facecolor=FG, alpha=0.6,
                                 edgecolor="none", zorder=5))  # отметка 50%

    note = "оценка: ± шаг за каждую ранкед-игру"
    if solo and total_points <= DOTS_LIMIT:
        note = "точки: зелёная — победа, красная — поражение  ·  " + note
    text(W / 2, footer_h / 2, note, color=MUTED, fontsize=9, ha="center")

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=BG)
    return buffer.getvalue()
