"""Кирпичики карточек-картинок (PNG в памяти): шрифты, панели, таблетки, иконки, аватары, значки рангов,
K/D/A, форма, полоска винрейта, спарклайн, плитки показателей.

Все карточки бота (матч, рейтинг, игрок, рекорды…) собираются из этих функций, чтобы выглядеть одинаково:
единая тёмная палитра (как у графиков, charts.py), ширина 1280 px, шрифт не мельче 18 px (на телефоне
картинка показывается втрое мельче), победа — зелёный, поражение — красный, свои игроки — золото.
Рисуем на Pillow. Шрифт — Inter из assets/fonts (подмножество с кириллицей и табличными цифрами: столбцы чисел
стоят ровно); крупные жирные надписи — Inter Display. Символы, которых в Inter нет (редкие знаки в никах),
рисуются запасным DejaVu из matplotlib. Скруглённые фигуры и круги сглажены (маска рисуется в крупном масштабе
и ужимается). Панели — с тонкой светлой кромкой, фон — с мягким свечением акцентного цвета сверху (см. Canvas).
Скорость: ширины строк и маски подписей с разрядкой кэшируются, свечение — готовая полоса из кэша.
Здесь нет ни сети, ни БД — иконки и аватары приходят готовыми байтами; нет данных или файл битый — заглушка.
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
PANEL_HI = "#1a2535"  # приподнятая плитка поверх PANEL
EDGE = "#26364a"  # тонкая рамка панелей
MINE_PANEL = "#1d2a3d"  # строка своего игрока
GOLD = "#f5b83d"
SILVER = "#c9d3de"
BRONZE = "#d9904f"
BG_TOP = "#121a27"  # верх фона: к низу холста плавно уходит в BG
ACCENT = PALETTE[0]
RADIANT, DIRE = "#5cc46a", "#e5553f"
log = logging.getLogger(__name__)

WIDTH = WIDTH_PX
PAD = 32

# Цвет медали по номеру (1 Herald … 8 Immortal) — как «градиент» рангов в игре.
MEDAL_COLORS = {1: "#9aa5b1", 2: "#c98a4b", 3: "#e0c04f", 4: "#4fbf80", 5: "#4f8df0", 6: "#9a74e6", 7: "#4fd0e0", 8: "#ff6a3d"}
PLACE_COLORS = {1: GOLD, 2: SILVER, 3: BRONZE}

# --- текст ---------------------------------------------------------------------------------------

FONT_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")
DISPLAY_FROM = 30  # жирный текст от этого кегля — Inter Display (плотнее и выразительнее в крупных числах)
TRACK_MAX_SIZE = 20  # мелкие подписи ЗАГЛАВНЫМИ разряжаем — так они читаются как подписи, а не как текст
TRACKING = 0.07  # разрядка в долях кегля


@lru_cache(maxsize=96)
def font(size: int, bold: bool = False):
    from PIL import ImageFont
    name = ("InterDisplay-ExtraBold.otf" if size >= DISPLAY_FROM else "Inter-Bold.otf") if bold else "Inter-Medium.otf"
    try:  # BASIC: одинаковая раскладка текста с libraqm и без него (в Docker-образе его может не быть)
        return ImageFont.truetype(os.path.join(FONT_DIR, name), size, layout_engine=ImageFont.Layout.BASIC)
    except Exception:
        return _spare_font(size, bold)


@lru_cache(maxsize=96)
def _spare_font(size: int, bold: bool = False):
    """Запасной шрифт DejaVu из matplotlib: в нём есть редкие символы, которых нет в Inter."""
    from PIL import ImageFont
    try:
        import matplotlib
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        return ImageFont.truetype(os.path.join(matplotlib.get_data_path(), "fonts", "ttf", name), size,
                                  layout_engine=ImageFont.Layout.BASIC)
    except Exception:
        return ImageFont.load_default(size)


@lru_cache(maxsize=1)
def _covered() -> Optional[frozenset]:
    """Коды символов, которые есть в Inter (None — узнать не удалось, тогда всё рисуем основным шрифтом)."""
    try:
        from fontTools.ttLib import TTFont
        with TTFont(os.path.join(FONT_DIR, "Inter-Medium.otf"), lazy=True) as ttf:
            return frozenset(ttf.getBestCmap())
    except Exception:
        return None


def _runs(text: str, size: int, bold: bool) -> list:
    """Текст кусками [(шрифт, строка)]: символы, которых нет в Inter, идут отдельными кусками запасным шрифтом."""
    main = font(size, bold)
    covered = _covered()
    if covered is None or text.isascii() or all(ord(ch) in covered for ch in text):
        return [(main, text)]
    spare = _spare_font(size, bold)
    runs: list = []
    for ch in text:
        fnt = main if ord(ch) in covered else spare
        if runs and runs[-1][0] is fnt:
            runs[-1][1] += ch
        else:
            runs.append([fnt, ch])
    return [(fnt, part) for fnt, part in runs]


def _tracked(text: str, size: int) -> bool:
    """Мелкая подпись заглавными («ИГРОК», «НАГРАДЫ», «K / D / A») — её рисуем с разрядкой."""
    if size > TRACK_MAX_SIZE or len(text) < 3 or not text.isupper():
        return False
    digits = sum(ch.isdigit() for ch in text)  # «ПОСЛЕДНИЕ 20 ИГР» — подпись; «+75 MMR», «KDA 3.4» — значения, их не трогаем
    return digits == 0 or (digits <= 3 and sum(ch.isalpha() for ch in text) >= 6)


def clean(text) -> str:
    """Убираем управляющие символы и эмодзи вне BMP — в шрифтах карточек их нет, рисовались бы квадраты."""
    return "".join(ch for ch in str(text or "") if ch.isprintable() and ord(ch) <= 0xFFFF).strip()


def fit(text: str, fnt, max_w: float) -> str:
    """Обрезает текст многоточием, чтобы он влез в max_w пикселей."""
    if fnt.getlength(text) <= max_w:
        return text
    while text and fnt.getlength(text + "…") > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


@lru_cache(maxsize=4096)
def text_width(text: str, size: int, bold: bool = False, track: Optional[bool] = None) -> float:
    """Ширина текста в пикселях. track: разрядка (None — по правилу `_tracked`, False — никогда).
    Результат кэшируется: одни и те же подписи, ники и числа измеряются на каждой карточке."""
    width = sum(fnt.getlength(part) for fnt, part in _runs(text, size, bold))
    tracked = _tracked(text, size) if track is None else track
    return width + size * TRACKING * (len(text) - 1) if tracked else width


def _fit(text: str, size: int, bold: bool, max_w: float) -> str:
    if text_width(text, size, bold) <= max_w:
        return text
    while text and text_width(text + "…", size, bold) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


# Сглаживание букв — LEVELS ступеней прозрачности вместо 256: глазу разницы нет даже при увеличении вдвое,
# а оттенков на краях букв в десятки раз меньше, и PNG сжимает текст на 25–35% лучше (замер на карточках 1280 px).
LEVELS = 8
_ALPHA_STEPS = [round(round(v * (LEVELS - 1) / 255) * 255 / (LEVELS - 1)) for v in range(256)]


@lru_cache(maxsize=1024)
def _text_mask(text: str, size: int, bold: bool, tracked: bool):
    """Готовая маска строки: (маска "L", подъём над базовой линией, высота строки, ширина, поле вокруг).

    Растеризация букв — заметная доля времени карточки, а строки повторяются от картинки к картинке (подписи
    столбцов, ники, ранги, числа), поэтому строка рисуется один раз и дальше ставится на холст из кэша.
    Здесь же разрядка и запасной шрифт для символов, которых нет в Inter: строка собирается по кускам.
    """
    from PIL import Image, ImageDraw
    runs = _runs(text, size, bold)
    if tracked:
        runs = [(fnt, ch) for fnt, part in runs for ch in part]
    gap = size * TRACKING if tracked else 0.0
    ascent, descent = font(size, bold).getmetrics()
    total = sum(fnt.getlength(part) for fnt, part in runs) + gap * (len(runs) - 1)
    pad = max(2, size // 5)  # запас под выносные элементы, свисающие буквы и сглаживание
    mask = Image.new("L", (math.ceil(total) + pad * 2, ascent + descent + pad * 2), 0)
    pen = ImageDraw.Draw(mask)
    x = float(pad)
    for fnt, part in runs:
        pen.text((x, pad + ascent), part, font=fnt, fill=255, anchor="ls")
        x += fnt.getlength(part) + gap
    mask = mask.point(_ALPHA_STEPS)
    return mask, ascent, ascent + descent, total, pad


def draw_text(draw, xy, text: str, size: int, fill=FG, bold: bool = False, anchor: str = "la",
              max_w: Optional[float] = None, track: Optional[bool] = None) -> None:
    if max_w:
        text = _fit(text, size, bold, max_w)
    if not text:
        return
    tracked = _tracked(text, size) if track is None else track
    mask, ascent, line_h, total, pad = _text_mask(text, size, bold, tracked)
    x = xy[0] - (total if anchor[0] == "r" else total / 2 if anchor[0] == "m" else 0)
    v = anchor[1]
    top = xy[1] - (0 if v == "a" else line_h / 2 if v == "m" else line_h if v == "d" else ascent)
    draw.bitmap((round(x) - pad, round(top) - pad), mask, fill=fill)


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
    """Тёмный холст шириной 1280 px. Рисуем на высоком, в конце `png(bottom)` обрезает по низу содержимого.

    Верх холста чуть светлее и подсвечен цветом `accent` (синий по умолчанию; карточка исхода матча ставит
    зелёный или красный). accent=None — ровный фон BG без свечения.
    """

    def __init__(self, height: int = 2400, width: int = WIDTH, accent: Optional[str] = ACCENT) -> None:
        from PIL import Image, ImageDraw
        self.width = width
        self.accent = accent
        self.img = Image.new("RGB", (width, max(int(height), 1)), BG)
        if accent:
            try:  # готовая полоса свечения из кэша: одна копия блока пикселей, без масок
                self.img.paste(_glow(width, accent), (0, 0))
            except Exception:
                log.warning("Свечение фона не собралось, рисуем на ровном", exc_info=True)
        self.draw = ImageDraw.Draw(self.img)

    def png(self, bottom: Optional[int] = None, fmt: str = "PNG") -> bytes:
        """Байты картинки (обрезка по низу содержимого). fmt="JPEG" — лёгкий файл: Telegram пережимает фото сам."""
        img = self.img
        if bottom is not None:
            img = img.crop((0, 0, self.width, min(max(int(bottom) + PAD, 1), img.height)))
        return to_jpeg(img) if fmt == "JPEG" else to_png(img)


GLOW_H = 560  # высота свечения сверху, px
GLOW_STRENGTH = 0.07  # доля акцентного цвета у верхнего края


@lru_cache(maxsize=16)
def _glow(width: int, accent: str):
    """Верх фона (width × GLOW_H): сверху BG_TOP с примесью акцентного цвета, книзу плавно уходит в BG.

    Переход только по вертикали: все пиксели строки одинаковые, PNG сжимает такой фон почти в ноль
    (пятно с переходом ещё и по горизонтали добавляло карточке ~5% веса).
    """
    from PIL import Image
    top = mix(BG_TOP, accent, GLOW_STRENGTH)
    column = Image.new("RGB", (1, GLOW_H))
    column.putdata([_rgb(mix(top, BG, (j / (GLOW_H - 1)) ** 0.8)) for j in range(GLOW_H)])
    return column.resize((width, GLOW_H), Image.NEAREST)


def to_jpeg(img, quality: int = 86) -> bytes:
    # 4:2:0 и q86 — как раз то, во что Telegram пережмёт фото; файл втрое легче PNG (на медленной сети это секунды).
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, subsampling=2, optimize=True)
    return buf.getvalue()


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


@lru_cache(maxsize=1024)
def _rr_mask(w: int, h: int, r: int):
    from PIL import Image, ImageDraw
    ss = _scale(w, h)
    big = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=r * ss, fill=255)
    return big.resize((w, h), Image.LANCZOS)


@lru_cache(maxsize=64)
def _circle_mask(d: int):
    return _rr_mask(d, d, d // 2)


RIM_MIN = 44  # панели не меньше этого размера получают светлую кромку (мелкие таблетки и полоски — нет)
RIM = 0.07  # насколько кромка светлее заливки


@lru_cache(maxsize=64)
def _rim_corners(r: int):
    """Четыре угловые маски рамки в 1 px для радиуса r (лев-верх, прав-верх, лев-низ, прав-низ)."""
    side = r * 2
    ring = _rr_mask(side, side, r).copy()
    if side > 2:
        ring.paste(0, (1, 1), _rr_mask(side - 2, side - 2, max(r - 1, 0)))
    return (ring.crop((0, 0, r, r)), ring.crop((r, 0, side, r)), ring.crop((0, r, r, side)), ring.crop((r, r, side, side)))


def _rim(img, x0: int, y0: int, w: int, h: int, r: int, color: str) -> None:
    """Рамка в 1 px поверх уже залитой панели: четыре прямые полоски и четыре маленьких сглаженных угла.
    Так панель с рамкой стоит одной заливки по маске, а не двух во всю площадь."""
    x1, y1 = x0 + w, y0 + h
    if r <= 0:
        for box in ((x0, y0, x1, y0 + 1), (x0, y1 - 1, x1, y1), (x0, y0, x0 + 1, y1), (x1 - 1, y0, x1, y1)):
            img.paste(color, box)
        return
    for box in ((x0 + r, y0, x1 - r, y0 + 1), (x0 + r, y1 - 1, x1 - r, y1), (x0, y0 + r, x0 + 1, y1 - r), (x1 - 1, y0 + r, x1, y1 - r)):
        if box[2] > box[0] and box[3] > box[1]:
            img.paste(color, box)
    tl, tr, bl, br = _rim_corners(r)
    img.paste(color, (x0, y0), tl)
    img.paste(color, (x1 - r, y0), tr)
    img.paste(color, (x0, y1 - r), bl)
    img.paste(color, (x1 - r, y1 - r), br)


def panel(img, box, fill: str = PANEL, radius: int = 16, outline: Optional[str] = None) -> None:
    """Скруглённая панель со сглаженными углами; outline — рамка в 1 px.

    Без outline панель крупнее RIM_MIN получает едва заметную светлую кромку — она отделяет панель от фона
    и соседних панелей лучше, чем одна разница заливок.
    """
    x0, y0, x1, y1 = (round(v) for v in box)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    r = max(0, min(radius, w // 2, h // 2))
    if outline is None and w >= RIM_MIN and h >= RIM_MIN and isinstance(fill, str):
        outline = mix(fill, "#ffffff", RIM)
    img.paste(fill, (x0, y0), _rr_mask(w, h, r))
    if outline and w > 2 and h > 2:
        _rim(img, x0, y0, w, h, r, outline)


@lru_cache(maxsize=128)
def _gradient_strip(w: int, left: str, right: str):
    from PIL import Image
    strip = Image.new("RGB", (w, 1))
    strip.putdata([_rgb(mix(left, right, i / max(w - 1, 1))) for i in range(w)])
    return strip


def gradient_panel(img, box, left: str, right: str, radius: int = 16, outline: Optional[str] = None) -> None:
    """Скруглённая панель с горизонтальным градиентом left → right; outline — рамка в 1 px."""
    from PIL import Image
    x0, y0, x1, y1 = (round(v) for v in box)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    r = max(0, min(radius, w // 2, h // 2))
    img.paste(_gradient_strip(w, left, right).resize((w, h), Image.NEAREST), (x0, y0), _rr_mask(w, h, r))
    if outline and w > 2 and h > 2:
        _rim(img, x0, y0, w, h, r, outline)


def dot(img, cx: float, cy: float, r: float, fill: str) -> None:
    d = max(2, round(r * 2))
    img.paste(fill, (round(cx - d / 2), round(cy - d / 2)), _circle_mask(d))


def pill(img, draw, x: float, cy: float, text: str, fg: str = BG, bg: str = GOLD, size: int = 20,
         bold: bool = True, pad: int = 14, align: str = "left") -> float:
    """Таблетка с текстом; x — левый край (align='right' — правый, 'center' — середина). Возвращает ширину."""
    text = clean(text)
    h = size + 16
    w = round(text_width(text, size, bold, track=False) + pad * 2)
    left = x if align == "left" else x - w if align == "right" else x - w / 2
    panel(img, (left, cy - h / 2, left + w, cy + h / 2), bg, radius=h // 2)
    draw_text(draw, (left + w / 2, cy), text, size, fg, bold, anchor="mm", track=False)
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


# Источник настоящих значков рангов: name ("rank_icon_5", "rank_star_3") -> PNG | None. Ставится при старте
# (`__main__`, см. rank_icons.py); без него или без значка рисуем свою медаль.
rank_icon_source = None


@lru_cache(maxsize=128)
def _real_badge(medal_png: bytes, star_png: Optional[bytes], size: int):
    from PIL import Image
    badge = Image.open(io.BytesIO(medal_png)).convert("RGBA").resize((size, size), Image.LANCZOS)
    if star_png:
        stars = Image.open(io.BytesIO(star_png)).convert("RGBA").resize((size, size), Image.LANCZOS)
        badge.alpha_composite(stars)
    return badge


def rank_badge(rank_tier: Optional[int], size: int = 64):
    """Значок ранга: настоящая медаль со звёздами (если загружена), иначе нарисованная."""
    source = rank_icon_source
    medal, stars = (rank_tier // 10, rank_tier % 10) if rank_tier else (0, 0)
    if source is not None and 0 <= medal <= 8:
        try:
            medal_png = source(f"rank_icon_{medal}")
            star_png = source(f"rank_star_{stars}") if 1 <= medal <= 7 and 1 <= stars <= 5 else None
            if medal_png:
                return _real_badge(medal_png, star_png, size)
        except Exception:
            log.warning("Значок ранга %s не собрался, рисуем свой", rank_tier, exc_info=True)
    return _drawn_badge(rank_tier, size)


@lru_cache(maxsize=64)
def _drawn_badge(rank_tier: Optional[int], size: int = 64):
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
    small = max(size * 3 // 4, 14)  # косые черты мельче и тоньше цифр — цифры остаются главным
    slash = mix(MUTED, PANEL, 0.35)
    parts = [(str(kills or 0), FG, size, bold), (" / ", slash, small, False), (str(deaths or 0), LOSS, size, bold),
             (" / ", slash, small, False), (str(assists or 0), FG, size, bold)]
    x = cx - sum(text_width(text, sz, b, False) for text, _, sz, b in parts) / 2
    for text, color, sz, b in parts:
        draw_text(draw, (x, cy), text, sz, color, b, anchor="lm", track=False)
        x += text_width(text, sz, b, False)


def value_text(draw, xy, text: str, size: int, fill=FG, anchor: str = "rm") -> float:
    """Крупное число. Знак «≈» перед ним (оценка MMR) рисуется мельче и приглушённо: главное — цифры.

    anchor — только "lm" или "rm". Возвращает ширину нарисованного.
    """
    text = clean(text)
    approx = text.startswith("≈") and len(text) > 1
    body = text[1:] if approx else text
    mark_size = max(size * 2 // 3, 18)
    body_w = text_width(body, size, True)
    mark_w = text_width("≈", mark_size, True) + size * 0.06 if approx else 0
    x = xy[0] - (body_w + mark_w if anchor[0] == "r" else 0)
    if approx:
        draw_text(draw, (x, xy[1] + size * 0.02), "≈", mark_size, mix(MUTED, BG, 0.15), bold=True, anchor="lm")
    draw_text(draw, (x + mark_w, xy[1]), body, size, fill, bold=True, anchor="lm")
    return body_w + mark_w


def delta_text(draw, xy, text: str, size: int, color: str = MUTED, anchor: str = "rm", max_w: Optional[float] = None) -> None:
    """Строка «+75 за 56 игр»: число со знаком — цветом color, пояснение после него — приглушённо."""
    text = clean(text)
    if max_w:
        text = _fit(text, size, False, max_w)
    head, _, tail = text.partition(" ")
    if not tail or head[:1] not in "+−-":
        draw_text(draw, xy, text, size, color, anchor=anchor)
        return
    tail = " " + tail
    head_w, tail_w = text_width(head, size, True), text_width(tail, size)
    x = xy[0] - (head_w + tail_w if anchor[0] == "r" else 0)
    draw_text(draw, (x, xy[1]), head, size, color, bold=True, anchor="l" + anchor[1])
    draw_text(draw, (x + head_w, xy[1]), tail, size, MUTED, anchor="l" + anchor[1])


def form_dots(img, x: float, cy: float, results: Sequence[Optional[bool]], r: int = 8, gap: int = 6) -> float:
    """Форма: штрихи слева направо от старых игр к новым. Победа — зелёный штрих выше середины, поражение —
    красный ниже: исход читается и по высоте, не только по цвету. r задаёт размер, gap — зазор. Возвращает ширину."""
    w, h, shift = max(6, round(r * 1.25)), max(12, round(r * 2.25)), max(3, round(r * 0.55))
    step = w + gap
    for i, won in enumerate(results):
        color = GRID if won is None else WIN if won else LOSS
        top = cy - h / 2 + (0 if won is None else -shift if won else shift)
        left = round(x + i * step)
        img.paste(color, (left, round(top)), _rr_mask(w, h, w // 2))
    return max(len(results) * step - gap, 0)


def winrate_bar(img, box, wins: int, losses: int, radius: Optional[int] = None) -> None:
    """Полоска винрейта: зелёная доля побед, после зазора — приглушённый красный; нет игр — серая."""
    x0, y0, x1, y1 = (round(v) for v in box)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    r = radius if radius is not None else h // 2
    total = wins + losses
    lose = mix(LOSS, BG, 0.5)
    if total == 0 or wins == 0 or losses == 0 or w < h * 3:
        img.paste(GRID if total == 0 else WIN if losses == 0 else lose, (x0, y0), _rr_mask(w, h, min(r, w // 2)))
        return
    gap = 3
    green = min(max(round(w * wins / total), h), w - h - gap)  # обе части видны даже при 1 из 100
    img.paste(WIN, (x0, y0), _rr_mask(green, h, min(r, green // 2)))
    rest = w - green - gap
    img.paste(lose, (x0 + green + gap, y0), _rr_mask(rest, h, min(r, rest // 2)))


def bar(img, box, frac: float, color: str = ACCENT, track: str = GRID, marker: Optional[float] = None) -> None:
    """Горизонтальная полоска заполнения (0–1) на тёмной дорожке; marker — риска-ориентир (например, 0.5 — «средний игрок»)."""
    x0, y0, x1, y1 = (round(v) for v in box)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    frac = max(0.0, min(1.0, float(frac or 0)))
    img.paste(track, (x0, y0), _rr_mask(w, h, h // 2))
    filled = round(w * frac)
    if filled:
        filled = min(max(filled, h), w)  # короче высоты скруглённую полоску не нарисовать
        img.paste(color, (x0, y0), _rr_mask(filled, h, h // 2))
    if marker is not None and 0 < marker < 1:
        mx = x0 + round(w * marker)
        img.paste(FG, (max(mx - 1, x0), y0, min(mx + 1, x1), y1))


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
    layer = layer.reduce(ss)  # усреднение блоками ss×ss: для сглаживания линии этого достаточно, а LANCZOS втрое медленнее
    img.paste(layer, (x0, y0), layer)


def tile(img, draw, box, label: str, value: str, sub: Optional[str] = None, color: str = FG, value_size: int = 40,
         fill: str = PANEL_HI) -> None:
    """Плитка показателя: мелкая подпись сверху, крупное значение, необязательная строка под ним."""
    x0, y0, x1, y1 = box
    panel(img, box, fill, radius=16)
    inner = x1 - x0 - 40
    draw_text(draw, (x0 + 20, y0 + 16), clean(label), 18, MUTED, anchor="la", max_w=inner)
    value_mid = (y0 + 42 + (y1 - 40 if sub else y1 - 14)) / 2  # между подписью и нижней строкой
    draw_text(draw, (x0 + 20, value_mid), clean(value), value_size, color, bold=True, anchor="lm", max_w=inner)
    if sub:
        draw_text(draw, (x0 + 20, y1 - 16), clean(sub), 18, MUTED, anchor="ld", max_w=inner)


SOLID_BADGES = (WIN, LOSS, RADIANT, DIRE)  # исход матча — главное на карточке, такая таблетка залита целиком


def chip(img, draw, x: float, cy: float, text: str, color: str = ACCENT, size: int = 22, pad: int = 16,
         align: str = "left", base: str = BG) -> float:
    """Спокойная метка: тонированный фон, рамка и текст одного цвета (период, число участников). Возвращает ширину."""
    text = clean(text)
    h = size + 20
    w = round(text_width(text, size, True, track=False) + pad * 2)
    left = x if align == "left" else x - w if align == "right" else x - w / 2
    panel(img, (left, cy - h / 2, left + w, cy + h / 2), mix(base, color, 0.16), radius=h // 2, outline=mix(base, color, 0.45))
    draw_text(draw, (left + w / 2, cy), text, size, mix(color, "#ffffff", 0.25), bold=True, anchor="mm", track=False)
    return w


def header(img, draw, title: str, subtitle: Optional[str] = None, badge: Optional[tuple[str, str]] = None, y: int = PAD) -> int:
    """Шапка карточки: заголовок, строка под ним, справа метка (текст, цвет). Возвращает y под шапкой.

    Метка исхода (цвет победы/поражения/стороны) — залитая таблетка; остальные (период и т. п.) — спокойный chip.
    """
    right = WIDTH - PAD
    if badge:
        if badge[1] in SOLID_BADGES:
            w = pill(img, draw, right, y + 30, badge[0], BG, badge[1], size=26, align="right", pad=22)
        else:
            w = chip(img, draw, right, y + 30, badge[0], badge[1], size=22, align="right", pad=18)
        right -= w + 24
    draw_text(draw, (PAD, y - 4), clean(title), 46, FG, bold=True, max_w=right - PAD)
    if subtitle:
        draw_text(draw, (PAD, y + 56), clean(subtitle), 22, MUTED, max_w=WIDTH - 2 * PAD)
    return y + (54 + 36 if subtitle else 54) + 18


def footer(draw, y: int, text: str) -> int:
    """Мелкая приглушённая строка под карточкой (когда обновлено, пояснение к цифрам). Возвращает y под ней."""
    draw_text(draw, (PAD, y + 8), clean(text), 18, mix(MUTED, BG, 0.25), max_w=WIDTH - 2 * PAD)
    return y + 8 + 26
