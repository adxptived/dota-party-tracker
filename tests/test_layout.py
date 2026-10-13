"""Вёрстка карточек: надписи не налезают друг на друга и не вылезают за край картинки.

Каждая надпись сообщает рамку своих букв (cards.text_hook); две рамки, пересекающиеся больше чем на пару пикселей,
значат, что текст залез на текст. Проверяются все образцы из scripts/render_samples.py — те же, что смотрим глазами.
"""
import sys
from pathlib import Path

import pytest
from PIL import Image

from mmrbot import cards

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

TOLERANCE = 2  # px: соседние буквы, чьи рамки касаются краями сглаживания, — не наложение


def _overlap(a, b) -> bool:
    return min(a[2], b[2]) - max(a[0], b[0]) > TOLERANCE and min(a[3], b[3]) - max(a[1], b[1]) > TOLERANCE


def _collisions(boxes):
    found = []
    for i, (text_a, box_a) in enumerate(boxes):
        for text_b, box_b in boxes[i + 1:]:
            if _overlap(box_a, box_b):
                found.append((text_a, text_b))
    return found


@pytest.fixture
def boxes(monkeypatch):
    seen = []
    monkeypatch.setattr(cards, "text_hook", lambda text, box: seen.append((text, box)))
    return seen


def test_overlap_detector_catches_text_on_text(boxes):
    from PIL import ImageDraw
    draw = ImageDraw.Draw(Image.new("RGB", (300, 100)))
    cards.draw_text(draw, (10, 10), "Вася", 30)
    cards.draw_text(draw, (40, 20), "Петя", 30)
    cards.draw_text(draw, (200, 10), "Ира", 30)
    assert _collisions(boxes) == [("Вася", "Петя")]


def test_sample_cards_have_no_overlapping_text(monkeypatch):
    """Все образцы: надписи каждой картинки (холста) не пересекаются и лежат в её пределах."""
    import render_samples
    canvases: list = []  # [(холст, [(текст, рамка)])]
    real_init = cards.Canvas.__init__

    def init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        canvases.append((self, []))

    monkeypatch.setattr(cards.Canvas, "__init__", init)
    monkeypatch.setattr(cards, "text_hook", lambda text, box: canvases[-1][1].append((text, box)) if canvases else None)
    render_samples.build()
    assert len(canvases) > 20
    bad = []
    for canvas, found in canvases:
        width = canvas.width
        bad += [("наложение", pair) for pair in _collisions(found)]
        bad += [("за краем", text) for text, box in found if box[0] < -1 or box[2] > width + 1]
    assert not bad, bad
