import sys

import pytest


@pytest.fixture
def drawn(monkeypatch):
    """Надписи, которые рисуют карточки: список (текст, цвет, жирный) в порядке отрисовки."""
    from mmrbot import cards
    calls = []
    real = cards.draw_text

    def spy(draw, xy, text, size, fill=cards.FG, bold=False, *args, **kwargs):
        calls.append((text, fill, bold))
        return real(draw, xy, text, size, fill, bold, *args, **kwargs)

    for name, module in list(sys.modules.items()):
        if name.startswith("mmrbot.") and getattr(module, "draw_text", None) is real:
            monkeypatch.setattr(module, "draw_text", spy)
    return calls
