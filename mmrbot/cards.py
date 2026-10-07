"""Кирпичики карточек-картинок (PNG в памяти): шрифты, панели, таблетки, иконки, аватары, значки рангов,
K/D/A, форма, полоска винрейта, спарклайн, плитки показателей.

Все карточки бота (матч, рейтинг, игрок, рекорды…) собираются из этих функций, чтобы выглядеть одинаково:
единая тёмная палитра (как у графиков, charts.py), ширина 1280 px, шрифт не мельче 18 px (на телефоне
картинка показывается втрое мельче), победа — зелёный, поражение — красный, свои игроки — золото.
Рисуем на Pillow, шрифт DejaVu берём из matplotlib (в нём есть кириллица). Скруглённые фигуры и круги
сглажены (маска рисуется в крупном масштабе и ужимается). Здесь нет ни сети, ни БД — иконки и аватары
приходят готовыми байтами; нет данных или файл битый — рисуется аккуратная заглушка.
"""
from __future__ import annotations

import hashlib
import io
import math
import os
import logging
from functools import lru_cache
from typing import Optional, Sequence

from mmrbot.charts import BG, FG, GRID, LOSS, MUTED, PALETTE, PANEL, WIDTH_PX, WIN
from mmrbot.heroes import hero_name

# --- палитра и размеры ---------------------------------------------------------------------------
PANEL_HI = "#1c2a3a"  # приподнятая плитка поверх PANEL
EDGE = "#26364a"  # тонкая рамка панелей
MINE_PANEL = "#1f2f40"  # строка своего игрока
GOLD = "#f0b429"
SILVER = "#c9d3de"
BRONZE = "#d9904f"
ACCENT = PALETTE[0]
RADIANT, DIRE = "#5cc46a", "#e5553f"
log = logging.getLogger(__name__)

WIDTH = WIDTH_PX
PAD = 32

# Цвет медали по номеру (1 Herald … 8 Immortal) — как «градиент» рангов в игре.
MEDAL_COLORS = {1: "#9aa5b1", 2: "#c98a4b", 3: "#e0c04f", 4: "#4fbf80", 5: "#4f8df0", 6: "#9a74e6", 7: "#4fd0e0", 8: "#ff6a3d"}
PLACE_COLORS = {1: GOLD, 2: SILVER, 3: BRONZE}

# --- текст ---------------------------------------------------------------------------------------

@lru_cache(maxsize=32)
def font(size: int, bold: bool = False):
    from PIL import ImageFont
    try:
        import matplotlib
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        return ImageFont.truetype(os.path.join(matplotlib.get_data_path(), "fonts", "ttf", name), size)
    except Exception:
        return ImageFont.load_default(size)


def clean(text) -> str:
    """Убираем управляющие символы и эмодзи вне BMP — в DejaVu их нет, рисовались бы квадраты."""
    return "".join(ch for ch in str(text or "") if ch.isprintable() and ord(ch) <= 0xFFFF).strip()


def fit(text: str, fnt, max_w: float) -> str:
    """Обрезает текст многоточием, чтобы он влез в max_w пикселей."""
    if fnt.getlength(text) <= max_w:
        return text
    while text and fnt.getlength(text + "…") > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def text_width(text: str, size: int, bold: bool = False) -> float:
    return font(size, bold).getlength(text)


def draw_text(draw, xy, text: str, size: int, fill=FG, bold: bool = False, anchor: str = "la", max_w: Optional[float] = None) -> None:
    fnt = font(size, bold)
    draw.text(xy, fit(text, fnt, max_w) if max_w else text, font=fnt, fill=fill, anchor=anchor)


def signed(value, zero: str = "0") -> str:
    """+75 / −12 (настоящий минус) / 0; None → «—»."""
    if value is None:
        return "—"
    value = round(value)
    if value == 0:
        return zero
    return f"+{value}" if value > 0 else f"−{abs(value)}"


def delta_color(value, neutral: str = MUTED) -> str:
    if value is None or round(value) == 0:
        return neutral
    return WIN if value > 0 else LOSS


def mix(a: str, b: str, t: float) -> str:
    """Смесь двух #rrggbb: t=0 → a, t=1 → b."""
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ra, rb))


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


# --- холст ---------------------------------------------------------------------------------------

class Canvas:
    """Тёмный холст шириной 1280 px. Рисуем на высоком, в конце `png(bottom)` обрезает по низу содержимого."""

    def __init__(self, height: int = 2400) -> None:
        from PIL import Image, ImageDraw
        self.img = Image.new("RGB", (WIDTH, max(int(height), 1)), BG)
        self.draw = ImageDraw.Draw(self.img)

    def png(self, bottom: Optional[int] = None) -> bytes:
        img = self.img
        if bottom is not None:
            img = img.crop((0, 0, WIDTH, min(max(int(bottom) + PAD, 1), img.height)))
        return to_png(img)


def to_png(img) -> bytes:
    # compress_level=6 без optimize: в ~4 раза быстрее optimize=True при размере на ~2% больше (замер на карточках 1280 px).
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    return buf.getvalue()


def warmup() -> None:
    """Прогрев при старте: шрифты всех размеров карточек и один пробный рендер — первая карточка без задержки."""
    try:
        for size in range(16, 72, 2):
            font(size)
            font(size, True)
        canvas = Canvas(200)
        draw_text(canvas.draw, (PAD, 40), "Прогрев 0123", 24, FG)
        canvas.png(100)
    except Exception:
        log.warning("Прогрев карточек не удался", exc_info=True)


# --- сглаженные фигуры ---------------------------------------------------------------------------

def _scale(w: int, h: int) -> int:
    return 4 if w * h <= 200_000 else 2


@lru_cache(maxsize=256)
def _rr_mask(w: int, h: int, r: int):
    from PIL import Image, ImageDraw
    ss = _scale(w, h)
    big = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=r * ss, fill=255)
    return big.resize((w, h), Image.LANCZOS)


@lru_cache(maxsize=64)
def _circle_mask(d: int):
    return _rr_mask(d, d, d // 2)


def panel(img, box, fill: str = PANEL, radius: int = 16, outline: Optional[str] = None) -> None:
    """Скруглённая панель со сглаженными углами; outline — рамка в 1 px."""
    x0, y0, x1, y1 = (round(v) for v in box)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    r = max(0, min(radius, w // 2, h // 2))
    if outline and w > 2 and h > 2:
        img.paste(outline, (x0, y0), _rr_mask(w, h, r))
        img.paste(fill, (x0 + 1, y0 + 1), _rr_mask(w - 2, h - 2, max(r - 1, 0)))
    else:
        img.paste(fill, (x0, y0), _rr_mask(w, h, r))


def dot(img, cx: float, cy: float, r: float, fill: str) -> None:
    d = max(2, round(r * 2))
    img.paste(fill, (round(cx - d / 2), round(cy - d / 2)), _circle_mask(d))


def pill(img, draw, x: float, cy: float, text: str, fg: str = BG, bg: str = GOLD, size: int = 20,
         bold: bool = True, pad: int = 14, align: str = "left") -> float:
    """Таблетка с текстом; x — левый край (align='right' — правый, 'center' — середина). Возвращает ширину."""
    text = clean(text)
    h = size + 16
    w = round(text_width(text, size, bold) + pad * 2)
    left = x if align == "left" else x - w if align == "right" else x - w / 2
    panel(img, (left, cy - h / 2, left + w, cy + h / 2), bg, radius=h // 2)
    draw_text(draw, (left + w / 2, cy), text, size, fg, bold, anchor="mm")
    return w


def stripe(img, x: float, y0: float, y1: float, color: str, width: int = 6) -> None:
    """Акцентная вертикальная полоса у левого края строки."""
    panel(img, (x, y0, x + width, y1), color, radius=width // 2)


# --- иконки героев и аватары ---------------------------------------------------------------------

ICON_W, ICON_H = 112, 63  # 16:9, как у иконок dota_react


@lru_cache(maxsize=256)
def _hero_icon_cached(data: Optional[bytes], hero_id, w: int, h: int, radius: int):
    from PIL import Image, ImageDraw
    icon = None
    if data:
        try:
            icon = Image.open(io.BytesIO(data)).convert("RGBA").resize((w, h), Image.LANCZOS)
        except Exception:
            icon = None
    if icon is None:
        icon = Image.new("RGBA", (w, h), GRID)
        name = hero_name(hero_id) if hero_id else "?"
        initials = "".join(word[0] for word in name.replace("-", " ").split()[:2]).upper() or "?"
        ImageDraw.Draw(icon).text((w / 2, h / 2), initials, font=font(max(12, h * 5 // 12), True), fill=MUTED, anchor="mm")
    icon.putalpha(_rr_mask(w, h, radius))
    return icon


def hero_icon(data: Optional[bytes], hero_id, w: int = ICON_W, h: int = ICON_H, radius: int = 8):
    """Иконка героя со скруглением; нет/битая — серая плашка с инициалами. Результат кэшируется (уже уменьшенной)."""
    return _hero_icon_cached(data, hero_id, w, h, radius)


def paste(img, sprite, x: float, y: float) -> None:
    img.paste(sprite, (round(x), round(y)), sprite)


@lru_cache(maxsize=256)
def _avatar_cached(data: Optional[bytes], label: str, size: int):
    from PIL import Image, ImageDraw, ImageOps
    face = None
    if data:
        try:
            face = ImageOps.fit(Image.open(io.BytesIO(data)).convert("RGBA"), (size, size), Image.LANCZOS)
        except Exception:
            face = None
    if face is None:
        seed = int(hashlib.md5(label.encode("utf-8")).hexdigest()[:6], 16)
        base = PALETTE[seed % len(PALETTE)]
        face = Image.new("RGBA", (size, size), mix(base, BG, 0.45))
        letter = (clean(label) or "?")[0].upper()
        ImageDraw.Draw(face).text((size / 2, size / 2), letter, font=font(max(12, size * 9 // 20), True),
                                  fill=mix(base, FG, 0.55), anchor="mm")
    face.putalpha(_circle_mask(size))
    return face


def avatar(data: Optional[bytes], label: str, size: int = 64, ring: Optional[str] = None, ring_w: int = 3):
    """Круглый аватар; нет картинки — кружок с инициалом (цвет зависит от ника). ring — цветное кольцо вокруг."""
    from PIL import Image
    face = _avatar_cached(data, label or "?", size)
    if not ring:
        return face
    total = size + ring_w * 2
    out = Image.new("RGBA", (total, total), (0, 0, 0, 0))
    out.paste(ring, (0, 0), _circle_mask(total))
    out.paste(Image.new("RGBA", (size + 2, size + 2), BG), (ring_w - 1, ring_w - 1), _circle_mask(size + 2))
    out.paste(face, (ring_w, ring_w), face)
    return out


# --- значок ранга --------------------------------------------------------------------------------

def _star_points(cx: float, cy: float, outer: float, inner: float, points: int = 5) -> list[tuple[float, float]]:
    out = []
    for i in range(points * 2):
        radius = outer if i % 2 == 0 else inner
        angle = -math.pi / 2 + i * math.pi / points
        out.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return out


@lru_cache(maxsize=64)
def rank_badge(rank_tier: Optional[int], size: int = 64):
    """Нарисованная медаль ранга (цвет тира, звезда, точки-звёзды 1–5); без ранга — серое кольцо. Без сети."""
    from PIL import Image, ImageDraw
    ss = 4
    s = size * ss
    big = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    medal, stars = (rank_tier // 10, rank_tier % 10) if rank_tier else (0, 0)
    color = MEDAL_COLORS.get(medal)
    c = s / 2
    if color is None:  # без ранга
        d.ellipse((s * 0.06, s * 0.06, s * 0.94, s * 0.94), outline=GRID, width=max(2, s // 16))
        d.text((c, c), "?", font=font(size * 5 // 12 * ss, True), fill=MUTED, anchor="mm")
    else:
        d.ellipse((s * 0.02, s * 0.02, s * 0.98, s * 0.98), fill=color)
        d.ellipse((s * 0.10, s * 0.10, s * 0.90, s * 0.90), fill=mix(color, BG, 0.62))
        star_cy = c - s * (0.04 if 1 <= medal <= 7 and stars else 0.0)
        d.polygon(_star_points(c, star_cy, s * 0.27, s * 0.115), fill=mix(color, "#ffffff", 0.18))
        if 1 <= medal <= 7 and stars:
            gap, r = s * 0.115, s * 0.036
            x0 = c - gap * (stars - 1) / 2
            for i in range(stars):
                d.ellipse((x0 + i * gap - r, c + s * 0.27 - r, x0 + i * gap + r, c + s * 0.27 + r), fill="#ffffff")
    return big.resize((size, size), Image.LANCZOS)


# --- мелкие графические элементы -----------------------------------------------------------------

def kda(draw, cx: float, cy: float, kills, deaths, assists, size: int = 28, bold: bool = True) -> None:
    """K / D / A по центру в cx: смерти — красным, чтобы читалось с одного взгляда."""
    parts = [(str(kills or 0), FG), (" / ", MUTED), (str(deaths or 0), LOSS), (" / ", MUTED), (str(assists or 0), FG)]
    fnt = font(size, bold)
    x = cx - sum(fnt.getlength(text) for text, _ in parts) / 2
    for text, color in parts:
        draw.text((x, cy), text, font=fnt, fill=color, anchor="lm")
        x += fnt.getlength(text)


def form_dots(img, x: float, cy: float, results: Sequence[Optional[bool]], r: int = 8, gap: int = 6) -> float:
    """Форма: кружки слева направо от старых игр к новым (True — победа). Возвращает ширину."""
    step = r * 2 + gap
    for i, won in enumerate(results):
        color = GRID if won is None else WIN if won else LOSS
        dot(img, x + r + i * step, cy, r, color)
    return max(len(results) * step - gap, 0)


def winrate_bar(img, box, wins: int, losses: int, radius: Optional[int] = None) -> None:
    """Полоска винрейта: зелёная доля побед, остальное — приглушённый красный; нет игр — серая."""
    from PIL import Image
    x0, y0, x1, y1 = (round(v) for v in box)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    total = wins + losses
    bar = Image.new("RGB", (w, h), GRID if total == 0 else mix(LOSS, BG, 0.45))
    if total:
        green = round(w * wins / total)
        if green:
            bar.paste(WIN, (0, 0, green, h))
    img.paste(bar, (x0, y0), _rr_mask(w, h, radius if radius is not None else h // 2))


def bar(img, box, frac: float, color: str = ACCENT, track: str = GRID, marker: Optional[float] = None) -> None:
    """Горизонтальная полоска заполнения (0–1) на тёмной дорожке; marker — риска-ориентир (например, 0.5 — «средний игрок»)."""
    from PIL import Image
    x0, y0, x1, y1 = (round(v) for v in box)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    frac = max(0.0, min(1.0, float(frac or 0)))
    strip = Image.new("RGB", (w, h), track)
    filled = round(w * frac)
    if filled:
        strip.paste(color, (0, 0, filled, h))
    if marker is not None and 0 < marker < 1:
        mx = round(w * marker)
        strip.paste(FG, (max(mx - 1, 0), 0, min(mx + 1, w), h))
    img.paste(strip, (x0, y0), _rr_mask(w, h, h // 2))


def sparkline(img, box, values: Sequence[float], color: str = ACCENT, fill: bool = True, last_dot: bool = True,
              width: int = 3) -> None:
    """Линия по значениям (сглажена суперсэмплингом) с мягкой заливкой под ней и точкой на последнем значении."""
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = (round(v) for v in box)
    w, h = x1 - x0, y1 - y0
    pts = [float(v) for v in values if v is not None]
    if w <= 8 or h <= 8 or not pts:
        return
    if len(pts) == 1:
        pts = pts * 2
    ss, m = 3, 6
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    xy = [((m + (w - 2 * m) * i / (len(pts) - 1)) * ss, (h - m - (h - 2 * m) * ((v - lo) / span if hi != lo else 0.5)) * ss)
          for i, v in enumerate(pts)]
    layer = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if fill:
        r, g, b = _rgb(color)
        d.polygon(xy + [(xy[-1][0], h * ss), (xy[0][0], h * ss)], fill=(r, g, b, 48))
    d.line(xy, fill=color, width=width * ss, joint="curve")
    if last_dot:
        lx, ly = xy[-1]
        rr = (width + 2) * ss
        d.ellipse((lx - rr, ly - rr, lx + rr, ly + rr), fill=color)
    layer = layer.resize((w, h), Image.LANCZOS)
    img.paste(layer, (x0, y0), layer)


def tile(img, draw, box, label: str, value: str, sub: Optional[str] = None, color: str = FG, value_size: int = 40,
         fill: str = PANEL_HI) -> None:
    """Плитка показателя: мелкая подпись сверху, крупное значение, необязательная строка под ним."""
    x0, y0, x1, y1 = box
    panel(img, box, fill, radius=16)
    inner = x1 - x0 - 36
    draw_text(draw, (x0 + 18, y0 + 14), clean(label), 18, MUTED, anchor="la", max_w=inner)
    value_y = y0 + 40 + (0 if sub else (y1 - y0 - 40 - value_size) / 2 - 2)
    draw_text(draw, (x0 + 18, value_y), clean(value), value_size, color, bold=True, anchor="la", max_w=inner)
    if sub:
        draw_text(draw, (x0 + 18, y1 - 14), clean(sub), 18, MUTED, anchor="ld", max_w=inner)


def header(img, draw, title: str, subtitle: Optional[str] = None, badge: Optional[tuple[str, str]] = None, y: int = PAD) -> int:
    """Шапка карточки: заголовок, строка под ним, справа таблетка (текст, цвет). Возвращает y под шапкой."""
    right = WIDTH - PAD
    if badge:
        w = pill(img, draw, right, y + 30, badge[0], BG, badge[1], size=26, align="right", pad=22)
        right -= w + 24
    draw_text(draw, (PAD, y), clean(title), 40, FG, bold=True, max_w=right - PAD)
    if subtitle:
        draw_text(draw, (PAD, y + 54), clean(subtitle), 24, MUTED, max_w=WIDTH - 2 * PAD)
    return y + (54 + 36 if subtitle else 54) + 18


def footer(draw, y: int, text: str) -> int:
    """Мелкая приглушённая строка под карточкой (когда обновлено, пояснение к цифрам). Возвращает y под ней."""
    draw_text(draw, (PAD, y + 8), clean(text), 18, MUTED, max_w=WIDTH - 2 * PAD)
    return y + 8 + 26
